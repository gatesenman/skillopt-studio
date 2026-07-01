"""Skill library: discover, inspect, import and export skill artifacts.

A SkillOpt run exports a compact ``best_skill.md`` (300–2000 tokens). The
library scans the data dir for these artifacts plus any user-imported skills so
they can be reviewed, exported to a project's ``SKILL.md``, or fed to the ACP
agent / other vendors.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SkillEntry:
    id: str
    name: str
    path: str
    source: str                 # "run" | "imported"
    benchmark: str = ""
    score: float | None = None
    tokens: int = 0
    mtime: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkillDetail(SkillEntry):
    content: str = ""
    score_curve: list[float] = field(default_factory=list)


class SkillLibrary:
    def __init__(self, home: Path):
        self.home = home
        self.runs_dir = home / "runs"
        self.imported_dir = home / "imported_skills"
        self.imported_dir.mkdir(parents=True, exist_ok=True)

    # ── discovery ────────────────────────────────────────────────────────
    def list(self) -> list[SkillEntry]:
        entries: list[SkillEntry] = []
        entries += self._scan_runs()
        entries += self._scan_imported()
        entries.sort(key=lambda e: e.mtime, reverse=True)
        return entries

    def _scan_runs(self) -> list[SkillEntry]:
        out: list[SkillEntry] = []
        if not self.runs_dir.exists():
            return out
        for md in list(self.runs_dir.glob("**/best_skill.md")) + \
                list(self.runs_dir.glob("**/SKILL.md")):
            run_dir = md.parent
            score, curve = self._read_scores(run_dir)
            out.append(SkillEntry(
                id=self._make_id(md),
                name=run_dir.name,
                path=str(md),
                source="run",
                benchmark=self._guess_benchmark(run_dir),
                score=score,
                tokens=_approx_tokens(md.read_text(encoding="utf-8", errors="ignore")) if md.exists() else 0,
                mtime=md.stat().st_mtime if md.exists() else 0.0,
            ))
        return out

    def _scan_imported(self) -> list[SkillEntry]:
        out: list[SkillEntry] = []
        for md in self.imported_dir.glob("*.md"):
            out.append(SkillEntry(
                id=self._make_id(md),
                name=md.stem,
                path=str(md),
                source="imported",
                tokens=_approx_tokens(md.read_text(encoding="utf-8", errors="ignore")),
                mtime=md.stat().st_mtime,
            ))
        return out

    # ── single skill ─────────────────────────────────────────────────────
    def get(self, skill_id: str) -> SkillDetail | None:
        entry = next((e for e in self.list() if e.id == skill_id), None)
        if entry is None:
            return None
        path = Path(entry.path)
        _score, curve = (None, [])
        if entry.source == "run":
            _score, curve = self._read_scores(path.parent)
        return SkillDetail(
            **{**entry.to_dict()},
            content=path.read_text(encoding="utf-8", errors="ignore") if path.exists() else "",
            score_curve=curve,
        )

    def export(self, skill_id: str, dest: str) -> str:
        entry = next((e for e in self.list() if e.id == skill_id), None)
        if entry is None:
            raise FileNotFoundError(skill_id)
        dest_path = Path(dest).expanduser()
        if dest_path.is_dir():
            dest_path = dest_path / "SKILL.md"
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry.path, dest_path)
        return str(dest_path)

    def delete(self, skill_id: str) -> dict:
        """Delete a skill artifact. Run artifacts remove the whole run dir;
        imported skills remove just the imported markdown file."""
        entry = next((e for e in self.list() if e.id == skill_id), None)
        if entry is None:
            raise FileNotFoundError(skill_id)
        path = Path(entry.path)
        if entry.source == "imported":
            path.unlink(missing_ok=True)
            removed = str(path)
        else:
            run_dir = path.parent
            # safety: only delete inside our runs dir
            if self.runs_dir in run_dir.parents or run_dir == self.runs_dir:
                shutil.rmtree(run_dir, ignore_errors=True)
                removed = str(run_dir)
            else:
                path.unlink(missing_ok=True)
                removed = str(path)
        return {"deleted": True, "id": skill_id, "path": removed}

    def import_file(self, src: str, name: str = "") -> SkillEntry:
        src_path = Path(src).expanduser()
        if not src_path.exists():
            raise FileNotFoundError(src)
        name = name or src_path.stem
        dest = self.imported_dir / f"{name}.md"
        shutil.copyfile(src_path, dest)
        return SkillEntry(
            id=self._make_id(dest), name=name, path=str(dest),
            source="imported", tokens=_approx_tokens(dest.read_text(encoding="utf-8", errors="ignore")),
            mtime=dest.stat().st_mtime,
        )

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _make_id(path: Path) -> str:
        import hashlib
        return hashlib.sha1(str(path).encode()).hexdigest()[:12]

    @staticmethod
    def _guess_benchmark(run_dir: Path) -> str:
        cfg = run_dir / "config.yaml"
        if cfg.exists():
            try:
                import yaml
                c = yaml.safe_load(cfg.read_text(encoding="utf-8"))
                return (c.get("env", {}) or {}).get("name", "") or ""
            except Exception:
                return ""
        return ""

    @staticmethod
    def _read_scores(run_dir: Path) -> tuple[float | None, list[float]]:
        """Pull a best score + a score curve from any jsonl logs in the run."""
        best: float | None = None
        curve: list[float] = []
        for log_f in run_dir.glob("**/*.jsonl"):
            try:
                with open(log_f, encoding="utf-8") as f:
                    for line in f:
                        d = json.loads(line)
                        if "score" in d:
                            s = float(d["score"])
                            curve.append(s)
                            best = s if best is None else max(best, s)
            except Exception:
                continue
        return best, curve


def _approx_tokens(text: str) -> int:
    # rough heuristic: ~4 chars per token
    return max(1, len(text) // 4)
