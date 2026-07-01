"""Desktop-side ACP manager: register the SkillOpt ACP agent with editors.

The ACP agent itself lives in :mod:`skillopt_acp`. This manager reports its
status and writes the small config snippet an ACP client (e.g. Zed) needs to
launch ``skillopt-acp`` as a subprocess, so a non-technical user can wire
SkillOpt into their editor's AI dev agent with one click.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RegisterResult:
    ok: bool
    message: str
    path: str = ""


# How each supported editor expects an external ACP agent to be declared.
ZED_KEY = "agent_servers"


def _zed_settings_path() -> Path:
    """Cross-platform location of Zed's ``settings.json``.

    * Windows: ``%APPDATA%\\Zed\\settings.json``
    * macOS / Linux: ``~/.config/zed/settings.json`` (Zed uses XDG-style on both)
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "Zed" / "settings.json"
    return Path.home() / ".config" / "zed" / "settings.json"


class AcpManager:
    def __init__(self, home: Path):
        self.home = home

    # ── status ───────────────────────────────────────────────────────────
    def command(self) -> list[str]:
        """The argv an ACP client should launch."""
        exe = shutil.which("skillopt-acp")
        if exe:
            return [exe]
        return [sys.executable, "-m", "skillopt_acp.server"]

    def status(self) -> dict:
        return {
            "installed": shutil.which("skillopt-acp") is not None,
            "command": self.command(),
            "agent_name": "skillopt",
            "editors": ["zed", "manual"],
        }

    def command_snippet(self) -> dict:
        """A generic, copy-pasteable launch spec for any ACP client."""
        cmd = self.command()
        return {
            "name": "skillopt",
            "command": cmd[0],
            "args": cmd[1:],
            "env": {},
        }

    # ── editor registration ──────────────────────────────────────────────
    def register_with_editor(self, editor: str) -> RegisterResult:
        editor = (editor or "").lower()
        if editor == "zed":
            return self._register_zed()
        return RegisterResult(False, f"automatic registration for '{editor}' "
                                     "is not supported; use the manual snippet.")

    def _register_zed(self) -> RegisterResult:
        settings = _zed_settings_path()
        settings.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if settings.exists():
            try:
                data = json.loads(settings.read_text(encoding="utf-8") or "{}")
            except Exception:
                return RegisterResult(False, f"could not parse {settings}; edit it manually.")
        cmd = self.command()
        servers = data.setdefault(ZED_KEY, {})
        servers["skillopt"] = {"command": cmd[0], "args": cmd[1:], "env": {}}
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return RegisterResult(True, f"registered SkillOpt ACP agent in {settings}",
                              str(settings))
