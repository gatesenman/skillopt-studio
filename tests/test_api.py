"""API smoke tests against the FastAPI app in demo mode (no skillopt installed)."""
import time

import pytest
from fastapi.testclient import TestClient

from skillopt_desktop.server import create_app
from skillopt_desktop.state import AppState


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLOPT_STUDIO_HOME", str(tmp_path / "home"))
    # force demo mode regardless of host environment
    monkeypatch.setenv("SKILLOPT_REPO", str(tmp_path / "nope"))
    state = AppState.create()
    # force demo mode: detach any SkillOpt checkout the host happens to have
    state.skillopt_root = None
    state.training.skillopt_root = None
    state.sleep.skillopt_root = None
    return TestClient(create_app(state))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_presets_and_benchmarks(client):
    presets = client.get("/api/presets").json()
    assert any(p["id"] == "docvqa_quickstart" for p in presets)
    benches = client.get("/api/benchmarks").json()
    assert "docvqa" in benches  # served from vendored configs


def test_backends_listed(client):
    bs = client.get("/api/backends").json()
    ids = {b["id"] for b in bs}
    assert {"openai_chat", "claude_chat", "codex_exec"} <= ids


def test_train_demo_run_produces_skill(client):
    r = client.post("/api/train/start",
                    json={"preset_id": "docvqa_quickstart", "mock": True,
                          "overrides": {"train.num_epochs": 1, "train.batch_size": 16}})
    run_id = r.json()["run_id"]
    # poll until the simulated run finishes
    for _ in range(120):
        st = client.get(f"/api/train/{run_id}/status").json()
        if not st["running"]:
            break
        time.sleep(0.1)
    assert st["running"] is False
    assert st["returncode"] == 0
    # a skill artifact should now be discoverable
    skills = client.get("/api/skills").json()
    assert len(skills) >= 1


def test_sleep_demo(client):
    r = client.post("/api/sleep/run", json={"project": "/tmp", "backend": "mock", "dry_run": True})
    body = r.json()
    assert body["ok"] is True and body["n_tasks"] >= 1


def test_acp_status(client):
    r = client.get("/api/acp/status").json()
    assert r["agent_name"] == "skillopt"
    assert "command" in r


def test_train_status_reports_mock_flag(client):
    r = client.post("/api/train/start",
                    json={"preset_id": "docvqa_quickstart", "mock": True,
                          "overrides": {"train.num_epochs": 1, "train.batch_size": 16}})
    run_id = r.json()["run_id"]
    st = client.get(f"/api/train/{run_id}/status").json()
    assert st["mock"] is True


def _run_demo_skill(client):
    r = client.post("/api/train/start",
                    json={"preset_id": "docvqa_quickstart", "mock": True,
                          "overrides": {"train.num_epochs": 1, "train.batch_size": 16}})
    run_id = r.json()["run_id"]
    for _ in range(120):
        st = client.get(f"/api/train/{run_id}/status").json()
        if not st["running"]:
            break
        time.sleep(0.1)
    return client.get("/api/skills").json()


def test_skill_detail_has_score_curve(client):
    skills = _run_demo_skill(client)
    assert skills
    detail = client.get(f"/api/skills/{skills[0]['id']}").json()
    assert isinstance(detail["score_curve"], list) and len(detail["score_curve"]) >= 1


def test_skill_delete(client):
    skills = _run_demo_skill(client)
    sid = skills[0]["id"]
    r = client.delete(f"/api/skills/{sid}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    remaining = {s["id"] for s in client.get("/api/skills").json()}
    assert sid not in remaining
    # deleting again -> 404
    assert client.delete(f"/api/skills/{sid}").status_code == 404


def test_dialog_unsupported_in_browser_mode(client):
    # no pywebview window is attached in tests -> graceful fallback
    r = client.get("/api/dialog/folder").json()
    assert r.get("unsupported") is True


def test_backend_probe_without_key_falls_back(client):
    # no key saved -> auth probe returns None, reachability check runs (local addr)
    r = client.post("/api/backends/test",
                    json={"backend": "openai_chat",
                          "creds": {"OPENAI_BASE_URL": "http://127.0.0.1:1/v1"}}).json()
    assert "ok" in r and "message" in r and r["ok"] is False


def test_cli_backend_probe(client):
    r = client.post("/api/backends/test",
                    json={"backend": "codex_exec",
                          "creds": {"CODEX_EXEC_PATH": "definitely-not-a-real-binary"}}).json()
    assert r["ok"] is False and "PATH" in r["message"]


def test_eval_requires_skill_for_live_backend():
    """Unit-level: eval argv build rejects a missing skill path."""
    from pathlib import Path
    from skillopt_desktop.services.training import (
        TrainingService, TrainStartReq, TrainRun)
    ts = TrainingService(Path("/tmp"), None, lambda: {})
    run = TrainRun(run_id="r", config_path="/tmp/cfg.yaml", overrides={},
                   out_dir="/tmp", kind="eval")
    Path("/tmp/cfg.yaml").write_text("env: {}\n")
    with pytest.raises(ValueError):
        ts._build_argv(run, TrainStartReq(kind="eval"))
    argv = ts._build_argv(run, TrainStartReq(kind="eval", skill_path="/tmp/SKILL.md"))
    assert "--skill" in argv and "scripts.eval_only" in " ".join(argv)


def test_zed_settings_path_is_platform_aware(monkeypatch):
    """Zed config resolves to the per-OS location (Windows vs POSIX)."""
    from pathlib import Path
    from skillopt_desktop.services import acp as acp_mod

    monkeypatch.setattr(acp_mod.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(Path("C:/Users/x/AppData/Roaming")))
    win = acp_mod._zed_settings_path()
    assert win.name == "settings.json" and win.parent.name == "Zed"

    monkeypatch.setattr(acp_mod.sys, "platform", "linux")
    posix = acp_mod._zed_settings_path()
    assert posix.parts[-3:] == (".config", "zed", "settings.json")


def test_acp_command_uses_current_interpreter():
    """ACP launch command never hardcodes a 'python' binary or POSIX path."""
    from pathlib import Path
    from skillopt_desktop.services.acp import AcpManager

    cmd = AcpManager(Path("/tmp")).command()
    assert cmd  # non-empty
    # either the resolved console-script, or this very interpreter + module
    assert cmd[0].endswith("skillopt-acp") or cmd[0].endswith("skillopt-acp.exe") \
        or Path(cmd[0]) == Path(__import__("sys").executable)


def _finish_run(client, run_id):
    for _ in range(120):
        st = client.get(f"/api/train/{run_id}/status").json()
        if not st["running"]:
            return st
        time.sleep(0.1)
    return st


def test_config_validate_flags_unknown_keys(client):
    """Pre-flight validation flags misspelled keys SkillOpt would ignore.

    Validation only runs when SkillOpt is importable; in demo mode it returns
    checked=False (and never raises). Either way the endpoint must be 200."""
    r = client.post("/api/config/validate",
                    json={"config_path": "configs/docvqa/default.yaml",
                          "overrides": {"optimizer.lr": 0.1,
                                        "optimizer.learning_rate": 0.1}})
    assert r.status_code == 200
    body = r.json()
    assert "checked" in body and "unknown" in body
    if body["checked"]:
        assert "optimizer.lr" in body["unknown"]
        assert "optimizer.learning_rate" not in body["unknown"]


def test_runs_history_and_trajectory(client):
    """A demo run is listed in /api/runs and exposes an accept/reject trajectory."""
    r = client.post("/api/train/start",
                    json={"preset_id": "docvqa_quickstart", "mock": True,
                          "overrides": {"train.num_epochs": 1, "train.batch_size": 24}})
    run_id = r.json()["run_id"]
    st = _finish_run(client, run_id)
    assert st["returncode"] == 0

    runs = client.get("/api/runs").json()
    assert any(x["run_id"] == run_id for x in runs)
    rec = next(x for x in runs if x["run_id"] == run_id)
    assert rec["n_steps"] >= 1 and rec["has_trajectory"] is True

    traj = client.get(f"/api/train/{run_id}/trajectory").json()
    steps = traj["steps"]
    assert steps and all("action" in s for s in steps)
    actions = {s["action"] for s in steps}
    # held-out gate produces accept/accept_new_best (and possibly reject)
    assert actions & {"accept", "accept_new_best", "force_accept"}


def test_eval_demo_simulates_score_without_real_evaluator(client):
    """One-click eval with a blank/demo backend must simulate a held-out score
    instead of invoking the real (env-heavy) eval_only CLI."""
    r = client.post("/api/train/start",
                    json={"preset_id": "docvqa_quickstart", "mock": True,
                          "overrides": {"train.num_epochs": 1, "train.batch_size": 16}})
    _finish_run(client, r.json()["run_id"])
    skill = client.get("/api/skills").json()[0]

    ev = client.post("/api/eval/start",
                     json={"config_path": "configs/docvqa/default.yaml",
                           "skill_path": skill["path"], "backend": "", "mock": True})
    st = _finish_run(client, ev.json()["run_id"])
    assert st["returncode"] == 0
    assert st["kind"] == "eval" and st["mock"] is True
    assert st["best_score"] is not None


def test_blank_backend_forces_mock_even_when_real_available(tmp_path):
    """A blank backend means demo: start() must not launch the real CLI even if
    a SkillOpt checkout is present."""
    from skillopt_desktop.services.training import TrainingService, TrainStartReq

    root = tmp_path / "SkillOpt"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "train.py").write_text("", encoding="utf-8")
    (root / "scripts" / "eval_only.py").write_text("", encoding="utf-8")
    svc = TrainingService(tmp_path / "home", root, lambda: {})
    assert svc._can_run_real() is True

    rid = svc.start_eval(TrainStartReq(config_path="configs/docvqa/default.yaml",
                                       skill_path=str(tmp_path / "SKILL.md"),
                                       backend="", mock=False))
    assert svc.runs[rid].mock is True


def test_optimizer_target_backends_kept_separate():
    """_build_argv must not force optimizer_backend == target_backend when the
    caller specifies them independently via overrides."""
    from skillopt_desktop.services.training import TrainingService, TrainRun, TrainStartReq
    from pathlib import Path

    svc = TrainingService(Path("/tmp"), None, lambda: {})
    run = TrainRun(run_id="r", config_path="configs/docvqa/default.yaml",
                   overrides={"model.optimizer_backend": "openai_chat"},
                   out_dir="/tmp/r")
    req = TrainStartReq(backend="claude_chat")
    argv = svc._build_argv(run, req)
    joined = " ".join(argv)
    assert "model.optimizer_backend=openai_chat" in joined
    assert "model.target_backend=claude_chat" in joined
