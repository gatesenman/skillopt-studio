"""SkillOpt-Sleep orchestration for the desktop UI.

Wraps the ``skillopt_sleep`` CLI (``run`` / ``dry-run`` / ``adopt`` / ``status``)
as a managed subprocess and parses the ``--json`` payload into a UI-friendly
report.

The desktop drives the **real** engine end-to-end:

* For real backends (``claude`` / ``codex`` / ``copilot``) it mines the user's
  actual local agent session history for the given project.
* For the ``mock`` backend (the fully-offline preview every user can run with no
  credentials) it seeds a self-contained, *reviewed* demo project + tasks file
  and replays it through the genuine harvest -> mine -> replay -> gate -> stage
  plumbing, so the gate scores, staged proposal and adopted ``SKILL.md`` edits
  are all produced by the real engine rather than hard-coded.

Only when ``skillopt_sleep`` is genuinely not importable does it fall back to a
clearly-labelled simulated report so the UI is never dead.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _extract_json(text: str) -> dict:
    """Parse the JSON report from CLI stdout, tolerating leading progress text."""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


@dataclass
class SleepReport:
    action: str
    ok: bool
    night: int = 0
    accepted: bool = False
    gate_action: str = ""
    baseline: float | None = None
    candidate: float | None = None
    n_tasks: int = 0
    n_sessions: int = 0
    edits: list[dict] = field(default_factory=list)
    rejected_edits: list[dict] = field(default_factory=list)
    staging_dir: str = ""
    adopted: bool = False
    project: str = ""
    skill_path: str = ""
    simulated: bool = False
    raw: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


# A reviewed, self-contained tasks file that the deterministic MockBackend can
# genuinely improve on: the baseline SKILL.md lacks the "wrap the final answer"
# rule, every task's rule-judge requires it, so the engine mines the gap,
# proposes exactly that rule, the held-out gate measures a real lift, and the
# edit is staged/adopted. This exercises the real pipeline with zero network.
_DEMO_TASKS = {
    "format": "skillopt_sleep.tasks.v1",
    "project": "",            # filled in at write time
    "transcript_source": "skillopt-studio-demo",
    "n_sessions": 4,
    "target_skill_path": "",  # filled in at write time
    "reviewed": True,
    "tasks": [
        {
            "id": "demo-train-1", "intent": "Answer the user's question and wrap the final answer in tags",
            "context_excerpt": "User: what is the capital of France? Please tag the final answer.",
            "outcome": "fail", "reference_kind": "rule", "reference": "Paris",
            "tags": ["rule:wrap-answer"],
            "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
            "split": "train", "origin": "real",
        },
        {
            "id": "demo-train-2", "intent": "Solve the arithmetic and wrap the final answer in tags",
            "context_excerpt": "User: compute 2 + 2 and tag the final answer.",
            "outcome": "fail", "reference_kind": "rule", "reference": "4",
            "tags": ["rule:wrap-answer"],
            "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
            "split": "train", "origin": "real",
        },
        {
            "id": "demo-val-1", "intent": "Name the largest planet and wrap the final answer in tags",
            "context_excerpt": "User: which is the largest planet? Tag the final answer.",
            "outcome": "fail", "reference_kind": "rule", "reference": "Jupiter",
            "tags": ["rule:wrap-answer"],
            "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
            "split": "val", "origin": "real",
        },
        {
            "id": "demo-test-1", "intent": "Give the chemical symbol for gold and wrap the final answer in tags",
            "context_excerpt": "User: chemical symbol for gold? Tag the final answer.",
            "outcome": "fail", "reference_kind": "rule", "reference": "Au",
            "tags": ["rule:wrap-answer"],
            "judge": {"kind": "rule", "checks": [{"op": "contains", "arg": "<answer>"}]},
            "split": "test", "origin": "real",
        },
    ],
}

_DEMO_SKILL = """# Project skill

Generic coding/QA assistant guidance for this project.

## When to use
Apply on every task in this project.

## Procedure
1. Read the request carefully.
2. Produce a concise, correct answer.
"""


class SleepService:
    def __init__(self, home: Path, skillopt_root: Path | None, env_provider):
        self.home = home
        self.skillopt_root = skillopt_root
        self.env_provider = env_provider

    def _available(self) -> bool:
        import importlib.util
        if importlib.util.find_spec("skillopt_sleep") is not None:
            return True
        return bool(self.skillopt_root and
                    (self.skillopt_root / "skillopt_sleep" / "__main__.py").exists())

    # ── demo project (offline, credential-free) ──────────────────────────
    def _demo_project_dir(self) -> Path:
        d = self.home / "sleep_demo_project"
        d.mkdir(parents=True, exist_ok=True)
        skill = d / "SKILL.md"
        if not skill.exists():
            skill.write_text(_DEMO_SKILL, encoding="utf-8")
        return d

    def _write_demo_tasks(self, project: Path, skill_path: Path) -> Path:
        payload = json.loads(json.dumps(_DEMO_TASKS))  # deep copy
        payload["project"] = str(project)
        payload["target_skill_path"] = str(skill_path)
        for task in payload["tasks"]:
            task["project"] = str(project)
        out = project / ".skillopt-studio-demo-tasks.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        return out

    def _resolve_target(self, project: str, backend: str, *,
                        reset_demo: bool = False) -> tuple[Path, Path, str | None]:
        """Return (project_dir, skill_path, tasks_file_or_None).

        For the offline ``mock`` backend with no explicit project, a sandbox
        demo project is used. ``reset_demo`` rewinds that sandbox's SKILL.md to
        the baseline so a preview always shows the real baseline->candidate
        lift (idempotent); adopt does not reset, so it can apply the proposal.
        """
        use_demo = (backend or "mock").lower() == "mock"
        is_sandbox = use_demo and not project
        if project:
            proj = Path(project).expanduser()
        elif use_demo:
            proj = self._demo_project_dir()
        else:
            proj = Path.cwd()
        proj.mkdir(parents=True, exist_ok=True)
        skill = proj / "SKILL.md"
        if use_demo:
            if is_sandbox and reset_demo:
                skill.write_text(_DEMO_SKILL, encoding="utf-8")
            elif not skill.exists():
                skill.write_text(_DEMO_SKILL, encoding="utf-8")
            tasks = self._write_demo_tasks(proj, skill)
            return proj, skill, str(tasks)
        return proj, skill, None

    # ── operations ────────────────────────────────────────────────────────
    def run(self, project: str, backend: str = "mock", *, dry_run: bool = True,
            auto_adopt: bool = False, max_tasks: int = 40) -> SleepReport:
        action = "dry-run" if dry_run else "run"
        if not self._available():
            return self._demo_report(action, project, backend)
        proj, skill, tasks_file = self._resolve_target(project, backend, reset_demo=True)
        argv = [sys.executable, "-m", "skillopt_sleep", action,
                "--project", str(proj),
                "--backend", backend or "mock",
                "--target-skill-path", str(skill),
                "--max-tasks", str(max_tasks), "--json"]
        if tasks_file:
            argv += ["--tasks-file", tasks_file]
        if auto_adopt and not dry_run:
            argv.append("--auto-adopt")
        rep = self._exec_json(action, argv)
        rep.project, rep.skill_path = str(proj), str(skill)
        return rep

    def adopt(self, project: str, backend: str = "mock") -> SleepReport:
        if not self._available():
            r = self._demo_report("adopt", project, backend)
            r.adopted = True
            return r
        proj, skill, _ = self._resolve_target(project, backend)
        argv = [sys.executable, "-m", "skillopt_sleep", "adopt",
                "--project", str(proj),
                "--target-skill-path", str(skill), "--json"]
        rep = self._exec_json("adopt", argv)
        rep.project, rep.skill_path = str(proj), str(skill)
        return rep

    def status(self, project: str, backend: str = "mock") -> SleepReport:
        if not self._available():
            return self._demo_report("status", project, backend)
        proj, skill, _ = self._resolve_target(project, backend)
        argv = [sys.executable, "-m", "skillopt_sleep", "status",
                "--project", str(proj), "--json"]
        rep = self._exec_json("status", argv)
        rep.project, rep.skill_path = str(proj), str(skill)
        return rep

    # ── helpers ──────────────────────────────────────────────────────────
    def _exec_json(self, action: str, argv: list[str]) -> SleepReport:
        env = os.environ.copy()
        env.update(self.env_provider() or {})
        cwd = str(self.skillopt_root) if self.skillopt_root else None
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  env=env, cwd=cwd, timeout=1800)
        except Exception as exc:  # noqa: BLE001
            return SleepReport(action=action, ok=False, raw=str(exc))
        raw = (proc.stdout or "") + (proc.stderr or "")
        payload = _extract_json(proc.stdout or "")
        return SleepReport(
            action=action,
            ok=proc.returncode == 0,
            night=payload.get("night", 0),
            accepted=payload.get("accepted", False),
            gate_action=payload.get("gate_action", ""),
            baseline=payload.get("baseline"),
            candidate=payload.get("candidate"),
            n_tasks=payload.get("n_tasks", 0),
            n_sessions=payload.get("n_sessions", 0),
            edits=payload.get("edits", []),
            rejected_edits=payload.get("rejected_edits", []),
            staging_dir=payload.get("staging_dir", ""),
            adopted=payload.get("adopted", False),
            raw=raw[-4000:],
        )

    def _demo_report(self, action: str, project: str, backend: str) -> SleepReport:
        return SleepReport(
            action=action, ok=True, night=1, accepted=action != "status",
            gate_action="accept" if action in ("run", "adopt") else "preview",
            baseline=0.62, candidate=0.69, n_tasks=8, n_sessions=12,
            simulated=True,
            edits=[{"target": "skill", "op": "add",
                    "content": "When a task recurs, record the exact command that worked."},
                   {"target": "skill", "op": "add",
                    "content": "Prefer validated steps from prior successful sessions."}],
            rejected_edits=[{"target": "skill", "op": "replace",
                             "content": "(rejected by held-out gate)"}],
            staging_dir=str(self.home / "sleep_staging_demo"),
            adopted=(action == "adopt"),
            raw="[demo] skillopt_sleep not installed — simulated nightly report.",
        )
