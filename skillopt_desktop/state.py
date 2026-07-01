"""Shared application state for SkillOpt Studio.

Resolves the data dir (``~/.skillopt``) and locates a SkillOpt checkout so the
desktop app can drive real training/sleep when available, while remaining fully
functional (demo mode) when it is not.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path

from .services.acp import AcpManager
from .services.backends import BackendRegistry
from .services.presets import PresetCatalog
from .services.skills import SkillLibrary
from .services.sleep import SleepService
from .services.training import TrainingService

# Bundled copy of SkillOpt's configs/, used for Pro-mode display and as a
# fallback when no SkillOpt checkout is found on disk.
BUNDLED_CONFIGS = Path(__file__).parent / "skillopt_assets_configs"


def default_home() -> Path:
    return Path(os.environ.get("SKILLOPT_STUDIO_HOME",
                               Path.home() / ".skillopt")).expanduser()


def find_skillopt_root() -> Path | None:
    """Locate a SkillOpt repo checkout (for configs/ + scripts/)."""
    env = os.environ.get("SKILLOPT_REPO")
    if env and (Path(env) / "scripts" / "train.py").exists():
        return Path(env)
    # if skillopt is pip-installed, scripts/ ships with it but configs/ may not
    spec = importlib.util.find_spec("scripts")
    if spec and spec.origin:
        root = Path(spec.origin).parent.parent
        if (root / "scripts" / "train.py").exists():
            return root
    for cand in (Path.cwd(), Path.home() / "SkillOpt", Path.home() / "repos" / "SkillOpt"):
        if (cand / "scripts" / "train.py").exists():
            return cand
    return None


@dataclass
class AppState:
    home: Path
    skillopt_root: Path | None
    backends: BackendRegistry
    presets: PresetCatalog
    skills: SkillLibrary
    training: TrainingService
    sleep: SleepService
    acp: AcpManager
    window: object | None = None      # pywebview window, when running as desktop

    @property
    def configs_root(self) -> Path:
        if self.skillopt_root and (self.skillopt_root / "configs").exists():
            return self.skillopt_root / "configs"
        return BUNDLED_CONFIGS

    @classmethod
    def create(cls) -> "AppState":
        home = default_home()
        home.mkdir(parents=True, exist_ok=True)
        root = find_skillopt_root()
        backends = BackendRegistry(home)
        return cls(
            home=home,
            skillopt_root=root,
            backends=backends,
            presets=PresetCatalog(),
            skills=SkillLibrary(home),
            training=TrainingService(home, root, backends.as_env),
            sleep=SleepService(home, root, backends.as_env),
            acp=AcpManager(home),
        )
