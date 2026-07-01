"""Training/eval orchestration for SkillOpt Studio.

Wraps SkillOpt's ``scripts.train`` / ``scripts.eval_only`` CLIs as managed
subprocesses, parses their stdout into structured stage/epoch/step progress
(logic adapted from the Gradio ``skillopt_webui`` ``TrainingManager``), and
streams coloured log lines to the UI over a websocket.

When SkillOpt is not importable (or the user selects the ``mock`` backend) it
falls back to a **demo run** that simulates the full pipeline so the desktop UI
is fully usable without any provider credentials.
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# The six pipeline stages SkillOpt walks through each step.
STAGES = ["rollout", "reflect", "aggregate", "select", "update", "gate"]

_RE_EPOCH = re.compile(r"\bepoch\s*\[?(\d+)\s*/\s*(\d+)\]?", re.I)
_RE_STEP = re.compile(r"\bstep\s*\[?(\d+)\s*/\s*(\d+)\]?", re.I)
_RE_SCORE = re.compile(r"\b(?:val|held[- ]?out|score)[^0-9]*([01]?\.\d+)", re.I)


@dataclass
class StageUpdate:
    stage: str = ""
    epoch: int = 0
    total_epochs: int = 0
    step: int = 0
    total_steps: int = 0
    score: float | None = None


@dataclass
class TrainRun:
    run_id: str
    config_path: str
    overrides: dict
    out_dir: str
    kind: str = "train"                 # "train" | "eval"
    process: subprocess.Popen | None = None
    stage: str = ""
    epoch: int = 0
    total_epochs: int = 0
    step: int = 0
    total_steps: int = 0
    best_score: float | None = None
    running: bool = False
    mock: bool = False
    returncode: int | None = None
    log_lines: list[str] = field(default_factory=list)
    _q: "queue.Queue[str]" = field(default_factory=queue.Queue)

    def status(self) -> dict:
        progress = 0.0
        if self.total_steps:
            done_epochs = max(0, self.epoch - 1)
            progress = (done_epochs * self.total_steps + self.step) / \
                       (max(1, self.total_epochs) * self.total_steps)
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "stage": self.stage,
            "stages": STAGES,
            "epoch": self.epoch,
            "total_epochs": self.total_epochs,
            "step": self.step,
            "total_steps": self.total_steps,
            "best_score": self.best_score,
            "running": self.running,
            "mock": self.mock,
            "returncode": self.returncode,
            "progress": round(min(1.0, progress), 4),
            "out_dir": self.out_dir,
        }


@dataclass
class TrainStartReq:
    config_path: str = ""
    preset_id: str = ""
    overrides: dict = field(default_factory=dict)
    backend: str = ""
    mock: bool = False
    kind: str = "train"               # "train" | "eval"
    skill_path: str = ""              # required for eval


class TrainingService:
    def __init__(self, home: Path, skillopt_root: Path | None, env_provider):
        self.home = home
        self.skillopt_root = skillopt_root
        self.env_provider = env_provider          # callable -> dict[str,str]
        self.runs: dict[str, TrainRun] = {}

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self, req: TrainStartReq) -> str:
        run_id = "run_" + uuid.uuid4().hex[:10]
        out_dir = self.home / "runs" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        run = TrainRun(run_id=run_id, config_path=req.config_path,
                       overrides=dict(req.overrides), out_dir=str(out_dir),
                       kind=req.kind,
                       total_epochs=int(req.overrides.get("train.num_epochs", 4)),
                       total_steps=int(req.overrides.get("train.batch_size", 40)) // 8 or 5)
        self.runs[run_id] = run
        # A blank backend means "demo/mock" (the UI labels the empty option
        # "演示模式 (mock)"). Real runs always carry an explicit backend, so we
        # never invoke the real train/eval CLIs without provider credentials.
        use_mock = (req.mock or not req.backend or req.backend == "mock"
                    or not self._can_run_real())
        run.mock = use_mock
        target = self._run_mock if use_mock else self._run_real
        run.running = True
        threading.Thread(target=target, args=(run, req), daemon=True).start()
        return run_id

    def start_eval(self, req: TrainStartReq) -> str:
        req.kind = "eval"
        return self.start(req)

    def status(self, run_id: str) -> dict | None:
        run = self.runs.get(run_id)
        return run.status() if run else None

    # ── history & trajectory (P1-5 / P1-6) ───────────────────────────────
    def list_runs(self) -> list[dict]:
        """List past runs (in-memory + persisted under ``home/runs``)."""
        runs_dir = self.home / "runs"
        out: dict[str, dict] = {}
        if runs_dir.is_dir():
            for d in runs_dir.iterdir():
                if not d.is_dir():
                    continue
                hist = self._find_history(d)
                steps = self._load_history(d)
                best = max((s.get("best_score") for s in steps
                            if s.get("best_score") is not None), default=None)
                has_skill = bool(list(d.glob("**/best_skill.md")) or list(d.glob("**/SKILL.md")))
                out[d.name] = {
                    "run_id": d.name,
                    "out_dir": str(d),
                    "best_score": best,
                    "n_steps": len(steps),
                    "has_skill": has_skill,
                    "has_trajectory": hist is not None,
                    "mtime": d.stat().st_mtime,
                    "running": False,
                    "kind": "train",
                }
        # overlay live in-memory runs (more accurate status)
        for rid, run in self.runs.items():
            rec = out.get(rid, {"run_id": rid, "out_dir": run.out_dir})
            rec.update({
                "best_score": run.best_score if run.best_score is not None else rec.get("best_score"),
                "running": run.running, "kind": run.kind, "mock": run.mock,
                "returncode": run.returncode, "stage": run.stage,
            })
            out[rid] = rec
        return sorted(out.values(), key=lambda r: r.get("mtime", 0), reverse=True)

    def trajectory(self, run_id: str) -> dict | None:
        """Return the per-step edit/gate trajectory for a run, if available."""
        run = self.runs.get(run_id)
        run_dir = Path(run.out_dir) if run else (self.home / "runs" / run_id)
        if not run_dir.is_dir():
            return None
        steps = self._load_history(run_dir)
        return {"run_id": run_id, "steps": steps,
                "running": run.running if run else False}

    @staticmethod
    def _find_history(run_dir: Path) -> Path | None:
        cand = run_dir / "history.json"
        if cand.exists():
            return cand
        return next(iter(sorted(run_dir.glob("**/history.json"))), None)

    @classmethod
    def _load_history(cls, run_dir: Path) -> list[dict]:
        import json as _json
        hist = cls._find_history(run_dir)
        if not hist:
            return []
        try:
            data = _json.loads(hist.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        norm: list[dict] = []
        for rec in data:
            if not isinstance(rec, dict):
                continue
            norm.append({
                "step": rec.get("step"),
                "epoch": rec.get("epoch"),
                "action": rec.get("action", "unknown"),
                "score_before": rec.get("score_before"),
                "score_after": rec.get("score_after"),
                "current_score": rec.get("current_score"),
                "best_score": rec.get("best_score"),
                "edit_budget": rec.get("edit_budget"),
                "skill_len": rec.get("skill_len"),
            })
        return norm

    def stop(self, run_id: str) -> str:
        run = self.runs.get(run_id)
        if not run:
            return "no such run"
        if run.process and run.process.poll() is None:
            run.process.terminate()
        run.running = False
        run._q.put("[stopped by user]")
        return "stopping"

    def stream_logs(self, run_id: str) -> Iterator[str]:
        """Blocking generator of log lines for the websocket."""
        run = self.runs.get(run_id)
        if not run:
            return
        # replay backlog first
        for line in list(run.log_lines):
            yield line
        while True:
            try:
                line = run._q.get(timeout=1.0)
            except queue.Empty:
                if not run.running:
                    break
                continue
            if line is None:
                break
            yield line

    # ── execution backends ───────────────────────────────────────────────
    def _can_run_real(self) -> bool:
        if self.skillopt_root and (self.skillopt_root / "scripts" / "train.py").exists():
            return True
        import importlib.util
        return importlib.util.find_spec("skillopt") is not None

    def _emit(self, run: TrainRun, line: str) -> None:
        run.log_lines.append(line)
        if len(run.log_lines) > 5000:
            run.log_lines = run.log_lines[-4000:]
        run._q.put(line)
        self._apply_progress(run, line)

    def _apply_progress(self, run: TrainRun, line: str) -> None:
        upd = self._parse_stage(line)
        if upd.stage:
            run.stage = upd.stage
        if upd.total_epochs:
            run.epoch, run.total_epochs = upd.epoch, upd.total_epochs
        if upd.total_steps:
            run.step, run.total_steps = upd.step, upd.total_steps
        if upd.score is not None:
            run.best_score = upd.score if run.best_score is None else max(run.best_score, upd.score)

    @staticmethod
    def _parse_stage(line: str) -> StageUpdate:
        low = line.lower()
        upd = StageUpdate()
        for s in STAGES:
            if s in low:
                upd.stage = s
                break
        m = _RE_EPOCH.search(line)
        if m:
            upd.epoch, upd.total_epochs = int(m.group(1)), int(m.group(2))
        m = _RE_STEP.search(line)
        if m:
            upd.step, upd.total_steps = int(m.group(1)), int(m.group(2))
        m = _RE_SCORE.search(line)
        if m:
            try:
                upd.score = float(m.group(1))
            except ValueError:
                pass
        return upd

    def _run_real(self, run: TrainRun, req: TrainStartReq) -> None:
        try:
            argv = self._build_argv(run, req)
            env = os.environ.copy()
            env.update(self.env_provider() or {})
            env["SKILLOPT_OUT_ROOT"] = run.out_dir
            cwd = str(self.skillopt_root) if self.skillopt_root else None
            self._emit(run, f"$ {' '.join(argv)}")
            run.process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, env=env, cwd=cwd,
            )
            assert run.process.stdout is not None
            for line in run.process.stdout:
                self._emit(run, line.rstrip("\n"))
            run.process.wait()
            run.returncode = run.process.returncode
            self._emit(run, f"[exited with code {run.returncode}]")
        except Exception as exc:  # noqa: BLE001
            self._emit(run, f"[error] {exc}")
            run.returncode = -1
        finally:
            run.running = False
            run._q.put(None)

    def _build_argv(self, run: TrainRun, req: TrainStartReq) -> list[str]:
        import sys
        if not run.config_path:
            raise ValueError("no config selected")
        # resolve relative configs against the SkillOpt checkout
        cfg = Path(run.config_path)
        if not cfg.is_absolute() and self.skillopt_root:
            resolved = self.skillopt_root / run.config_path
            if resolved.exists():
                cfg = resolved
        if cfg.is_absolute() and not cfg.exists():
            raise FileNotFoundError(f"config not found: {cfg}")
        module = "scripts.eval_only" if run.kind == "eval" else "scripts.train"
        argv = [sys.executable, "-m", module, "--config", str(cfg)]
        if run.kind == "eval":
            if not req.skill_path:
                raise ValueError("eval requires a skill path (--skill)")
            argv += ["--skill", req.skill_path]

        # Warn (don't silently ignore) about override keys SkillOpt would drop.
        from .configspec import known_keys, unknown_overrides
        bad = unknown_overrides(run.overrides, known_keys(self.skillopt_root, run.config_path))
        for key in bad:
            self._emit(run, f"[warn] unknown config key '{key}' — SkillOpt will "
                            "silently ignore it (check spelling against the schema).")

        cfg_opts: list[str] = []
        # Only auto-fill the backend(s) the caller didn't set explicitly, so a
        # separate optimizer model / target model can be expressed via overrides.
        if req.backend and req.backend != "mock":
            if "model.target_backend" not in run.overrides:
                cfg_opts.append(f"model.target_backend={req.backend}")
            if "model.optimizer_backend" not in run.overrides:
                cfg_opts.append(f"model.optimizer_backend={req.backend}")
        for k, v in run.overrides.items():
            if k.startswith("_"):
                continue
            cfg_opts.append(f"{k}={v}")
        if cfg_opts:
            argv += ["--cfg-options", *cfg_opts]
        return argv

    def _run_mock(self, run: TrainRun, req: TrainStartReq) -> None:
        """Simulate a full SkillOpt run so the UI is usable without credentials."""
        try:
            run.total_epochs = run.total_epochs or 2
            run.total_steps = run.total_steps or 4
            explicit = req.mock or req.backend == "mock"
            if explicit:
                self._emit(run, "[demo] mock backend selected — running a "
                                "simulated pipeline (no provider credentials used).")
            else:
                self._emit(run, "[demo] no live SkillOpt backend configured — "
                                "running a simulated preview. Add a provider key "
                                "in Settings to run for real.")
            self._emit(run, f"[demo] config={req.config_path or req.preset_id} "
                            f"backend={req.backend or 'mock'} kind={run.kind}")
            if run.kind == "eval":
                self._run_mock_eval(run, req)
                return
            score = 0.42
            best_score = score
            best_md = ""
            history: list[dict] = []
            global_step = 0
            for ep in range(1, run.total_epochs + 1):
                if not run.running:
                    break
                self._emit(run, f"epoch [{ep}/{run.total_epochs}] starting")
                for st in range(1, run.total_steps + 1):
                    if not run.running:
                        break
                    global_step += 1
                    self._emit(run, f"  step [{st}/{run.total_steps}]")
                    for stage in STAGES:
                        if not run.running:
                            break
                        self._emit(run, f"    [{stage}] ...")
                        time.sleep(0.18)
                    score_before = score
                    # Simulate the held-out gate: most edits improve and are
                    # accepted; occasionally a candidate regresses and is rejected.
                    cand = score_before + (0.05 if global_step % 4 else -0.02)
                    accepted = cand >= score_before
                    edit_budget = max(2, 4 - (global_step // max(1, run.total_steps)))
                    if accepted:
                        score = min(0.95, cand)
                        action = "accept_new_best" if score > best_score else "accept"
                        best_score = max(best_score, score)
                        best_md = self._demo_skill(req, score)
                        self._emit(run, f"    [gate] {action}: held-out "
                                        f"{score_before:.3f} -> {score:.3f} "
                                        f"(budget={edit_budget})")
                    else:
                        action = "reject"
                        self._emit(run, f"    [gate] reject: held-out "
                                        f"{score_before:.3f} -> {cand:.3f} "
                                        "(kept previous skill)")
                    self._emit(run, f"    held-out score: {score:.3f}")
                    history.append({
                        "step": global_step, "epoch": ep, "action": action,
                        "score_before": round(score_before, 4),
                        "score_after": round(cand, 4),
                        "current_score": round(score, 4),
                        "best_score": round(best_score, 4),
                        "edit_budget": edit_budget,
                        "skill_len": len(best_md),
                    })
                self._emit(run, f"epoch [{ep}/{run.total_epochs}] done "
                                f"(best held-out {best_score:.3f})")
            # write real artifacts so Skill Library / Results / Trajectory work
            (Path(run.out_dir) / "best_skill.md").write_text(best_md, encoding="utf-8")
            (Path(run.out_dir) / "config.yaml").write_text(
                f"env:\n  name: {req.preset_id or 'demo'}\n"
                f"train:\n  num_epochs: {run.total_epochs}\n", encoding="utf-8")
            (Path(run.out_dir) / "metrics.jsonl").write_text(
                "\n".join(f'{{"score": {h["current_score"]}}}' for h in history),
                encoding="utf-8")
            import json as _json
            (Path(run.out_dir) / "history.json").write_text(
                _json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            run.returncode = 0
            self._emit(run, f"[demo] exported best_skill.md ({_tok(best_md)} tokens)")
        finally:
            run.running = False
            run._q.put(None)

    def _run_mock_eval(self, run: TrainRun, req: TrainStartReq) -> None:
        """Simulate held-out evaluation of an existing skill (no real env/data).

        Mirrors a real ``eval_only`` run for the UI: reports the skill under
        test, the benchmark, and a held-out score — without booting heavy task
        environments (e.g. ALFWorld) that need data the demo box doesn't have.
        """
        bench = req.config_path or req.preset_id or "demo"
        skill_path = req.skill_path or "(none)"
        skill_md = ""
        try:
            p = Path(skill_path)
            if p.exists():
                skill_md = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
        self._emit(run, f"[demo] evaluating skill {skill_path} on {bench}")
        self._emit(run, f"[demo] skill length: {len(skill_md)} chars")
        run.total_epochs = 1
        run.total_steps = run.total_steps or 4
        run.epoch = 1
        for st in range(1, run.total_steps + 1):
            if not run.running:
                break
            run.step = st
            self._emit(run, f"  eval batch [{st}/{run.total_steps}] ...")
            time.sleep(0.18)
        # Deterministic demo score derived from the skill so different skills
        # produce stable, comparable held-out numbers.
        base = 0.40 + (len(skill_md) % 17) / 100.0
        score = round(min(0.95, base), 4)
        run.best_score = score
        run.step = run.total_steps
        self._emit(run, f"[demo] held-out score: {score:.3f}")
        import json as _json
        (Path(run.out_dir) / "eval.json").write_text(
            _json.dumps({"skill": skill_path, "benchmark": bench,
                         "score": score}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        run.returncode = 0
        self._emit(run, "[demo] evaluation complete")

    @staticmethod
    def _demo_skill(req: TrainStartReq, score: float) -> str:
        name = req.preset_id or req.config_path or "task"
        return (
            f"# Skill for {name}\n\n"
            "## When to use\n"
            "Apply this skill whenever you must answer questions grounded in the "
            "provided context or documents.\n\n"
            "## Procedure\n"
            "1. Identify the exact sub-question being asked.\n"
            "2. Locate the minimal supporting evidence before answering.\n"
            "3. Prefer concise, directly-quoted answers; avoid speculation.\n"
            "4. Double-check units, names, and numbers against the source.\n\n"
            f"<!-- demo artifact, held-out score ~{score:.3f} -->\n"
        )


def _tok(text: str) -> int:
    return max(1, len(text) // 4)
