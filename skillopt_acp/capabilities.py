"""Bridge from ACP prompts to SkillOpt capabilities.

Kept dependency-light (stdlib only) so the ACP agent can run as a subprocess
launched by an editor without importing FastAPI / pywebview. Heavy work is
delegated to the installed ``skillopt`` / ``skillopt_sleep`` packages by
shelling out to their console scripts, streaming progress back through a
callback.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Protocol

# A progress sink: receives short human-readable status lines.
ProgressFn = Callable[[str], None]


def _skillopt_root() -> str | None:
    """Locate a SkillOpt checkout so ``configs/`` resolves for ``scripts.train``."""
    env = os.environ.get("SKILLOPT_REPO")
    if env and os.path.exists(os.path.join(env, "scripts", "train.py")):
        return env
    spec = importlib.util.find_spec("scripts")
    if spec and spec.origin:
        root = os.path.dirname(os.path.dirname(spec.origin))
        if os.path.exists(os.path.join(root, "scripts", "train.py")):
            return root
    for cand in (os.getcwd(), os.path.join(os.path.expanduser("~"), "SkillOpt")):
        if os.path.exists(os.path.join(cand, "scripts", "train.py")):
            return cand
    return None


# Reviewed, fully-offline demo tasks the deterministic mock backend can improve
# on (mirrors the desktop SleepService): baseline SKILL.md lacks the rule, the
# engine mines it, the held-out gate measures a real lift, the edit is staged.
_DEMO_SKILL = "# Project skill\n\nGeneric assistant guidance.\n"
_DEMO_TASKS_TEMPLATE = {
    "format": "skillopt_sleep.tasks.v1", "transcript_source": "skillopt-acp-demo",
    "n_sessions": 4, "reviewed": True,
    "tasks": [
        {"id": "demo-train-1", "intent": "Answer and wrap the final answer in tags",
         "context_excerpt": "tag the final answer", "outcome": "fail",
         "reference_kind": "rule", "reference": "Paris", "tags": ["rule:wrap-answer"],
         "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
         "split": "train", "origin": "real"},
        {"id": "demo-train-2", "intent": "Compute and wrap the final answer in tags",
         "context_excerpt": "tag the final answer", "outcome": "fail",
         "reference_kind": "rule", "reference": "4", "tags": ["rule:wrap-answer"],
         "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
         "split": "val", "origin": "real"},
        {"id": "demo-test-1", "intent": "Name and wrap the final answer in tags",
         "context_excerpt": "tag the final answer", "outcome": "fail",
         "reference_kind": "rule", "reference": "Jupiter", "tags": ["rule:wrap-answer"],
         "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
         "split": "test", "origin": "real"},
    ],
}


@dataclass
class CommandResult:
    ok: bool
    summary: str
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)


class SkillOptCapabilities(Protocol):
    """Operations the ACP agent can expose to a connected client."""

    def optimize(self, target: str, *, backend: str, overrides: dict,
                 progress: ProgressFn, is_cancelled: Callable[[], bool]) -> CommandResult: ...

    def sleep(self, action: str, *, project: str, backend: str,
              progress: ProgressFn, is_cancelled: Callable[[], bool]) -> CommandResult: ...

    def list_skills(self, progress: ProgressFn) -> CommandResult: ...


class SubprocessCapabilities:
    """Default implementation that shells out to SkillOpt console scripts.

    ``home`` is the SkillOpt Studio data dir (``~/.skillopt`` by default) used to
    resolve the skill library and training outputs.
    """

    def __init__(self, home: str | None = None, python: str | None = None):
        self.home = home or os.path.join(os.path.expanduser("~"), ".skillopt")
        self.python = python or sys.executable
        os.makedirs(self.home, exist_ok=True)

    # ── helpers ──────────────────────────────────────────────────────────
    def _run(self, argv: list[str], progress: ProgressFn,
             is_cancelled: Callable[[], bool], cwd: str | None = None) -> tuple[int, list[str]]:
        progress(f"$ {' '.join(argv)}")
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1, env=os.environ.copy(), cwd=cwd,
        )
        lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if line.strip():
                progress(line)
            if is_cancelled():
                proc.terminate()
                progress("[cancelled]")
                break
        proc.wait()
        return proc.returncode or 0, lines

    @staticmethod
    def _has(cmd: str) -> bool:
        return shutil.which(cmd) is not None

    # ── capabilities ─────────────────────────────────────────────────────
    def optimize(self, target: str, *, backend: str, overrides: dict,
                 progress: ProgressFn, is_cancelled: Callable[[], bool]) -> CommandResult:
        """Run a SkillOpt training job for a benchmark/config ``target``."""
        if not self._has("skillopt-train") and not _module_available("skillopt"):
            return CommandResult(False, "skillopt is not installed",
                                 "Install it with: pip install skillopt")
        config = target if target.endswith((".yaml", ".yml")) else f"configs/{target}/default.yaml"
        argv = [self.python, "-m", "scripts.train", "--config", config]
        cfg_opts: list[str] = []
        if backend:
            cfg_opts += [f"model.target_backend={backend}", f"model.optimizer_backend={backend}"]
        for k, v in (overrides or {}).items():
            cfg_opts.append(f"{k}={v}")
        if cfg_opts:
            argv += ["--cfg-options", *cfg_opts]
        # run from the SkillOpt checkout so relative configs/ resolve
        code, lines = self._run(argv, progress, is_cancelled, cwd=_skillopt_root())
        ok = code == 0
        return CommandResult(
            ok,
            "optimization finished" if ok else f"training exited with code {code}",
            "\n".join(lines[-20:]),
        )

    def sleep(self, action: str, *, project: str, backend: str,
              progress: ProgressFn, is_cancelled: Callable[[], bool]) -> CommandResult:
        """Drive SkillOpt-Sleep (run / dry-run / adopt / status)."""
        if action not in {"run", "dry-run", "adopt", "status"}:
            return CommandResult(False, f"unknown sleep action: {action}")
        backend = backend or "mock"
        proj = project or os.path.join(self.home, "sleep_demo_project")
        os.makedirs(proj, exist_ok=True)
        skill = os.path.join(proj, "SKILL.md")
        argv = [self.python, "-m", "skillopt_sleep", action,
                "--project", proj, "--backend", backend,
                "--target-skill-path", skill, "--json"]
        # offline mock preview: seed a reviewed tasks file so the real engine
        # runs end-to-end with no credentials and no session history.
        if backend == "mock" and action in {"run", "dry-run"}:
            if action != "adopt":
                with open(skill, "w", encoding="utf-8") as f:
                    f.write(_DEMO_SKILL)
            tasks_file = self._write_demo_tasks(proj, skill)
            argv += ["--tasks-file", tasks_file]
            if action == "run":
                argv.append("--auto-adopt")
        code, lines = self._run(argv, progress, is_cancelled, cwd=_skillopt_root())
        ok = code == 0
        return CommandResult(ok, f"sleep {action} {'ok' if ok else 'failed'}",
                             "\n".join(lines[-20:]))

    def _write_demo_tasks(self, project: str, skill_path: str) -> str:
        payload = json.loads(json.dumps(_DEMO_TASKS_TEMPLATE))
        payload["project"] = project
        payload["target_skill_path"] = skill_path
        for task in payload["tasks"]:
            task["project"] = project
        out = os.path.join(project, ".skillopt-acp-demo-tasks.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return out

    def list_skills(self, progress: ProgressFn) -> CommandResult:
        """List exported skill artifacts found in the data dir."""
        skills: list[str] = []
        runs = os.path.join(self.home, "runs")
        for root, _dirs, files in os.walk(runs):
            for f in files:
                if f in ("best_skill.md", "SKILL.md"):
                    skills.append(os.path.join(root, f))
        progress(f"found {len(skills)} skill artifact(s)")
        return CommandResult(True, f"{len(skills)} skills", "\n".join(skills), skills)


def _module_available(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None
