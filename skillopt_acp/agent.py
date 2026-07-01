"""SkillOpt as an ACP (Agent Client Protocol) agent.

An ACP-compatible editor / AI dev agent launches this as a subprocess and
drives it over JSON-RPC. Each ``session/prompt`` is interpreted as one SkillOpt
instruction:

    optimize <benchmark|config|skill> [key=value ...]   -> run a training job
    sleep <run|dry-run|adopt|status>                    -> SkillOpt-Sleep cycle
    skills [list]                                       -> list skill artifacts
    help                                                -> usage

Long-running work streams progress back as ``session/update`` notifications and
finishes by returning a ``stopReason`` from ``session/prompt``.
"""
from __future__ import annotations

import shlex
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .capabilities import CommandResult, SkillOptCapabilities, SubprocessCapabilities

PROTOCOL_VERSION = 1
AGENT_NAME = "skillopt"
AGENT_VERSION = "0.1.0"

NotifyFn = Callable[[dict], None]


@dataclass
class Session:
    session_id: str
    cwd: str = ""
    cancelled: bool = False
    history: list[dict] = field(default_factory=list)


class ACPAgent:
    """Implements the agent half of ACP for SkillOpt.

    Parameters
    ----------
    caps:
        The SkillOpt capability backend. Defaults to :class:`SubprocessCapabilities`.
    """

    def __init__(self, caps: SkillOptCapabilities | None = None):
        self.caps: SkillOptCapabilities = caps or SubprocessCapabilities()
        self.sessions: dict[str, Session] = {}

    # ── lifecycle ────────────────────────────────────────────────────────
    def initialize(self, params: dict) -> dict:
        """Negotiate protocol version + advertise capabilities."""
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentInfo": {"name": AGENT_NAME, "version": AGENT_VERSION},
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {"image": False, "audio": False,
                                       "embeddedContext": True},
            },
            "authMethods": [],
        }

    def authenticate(self, params: dict) -> dict:
        # No auth needed; provider credentials are configured out-of-band.
        return {}

    def new_session(self, params: dict) -> dict:
        sid = "sess_" + uuid.uuid4().hex[:12]
        self.sessions[sid] = Session(session_id=sid, cwd=params.get("cwd", ""))
        return {"sessionId": sid}

    def cancel(self, params: dict) -> None:
        sess = self.sessions.get(params.get("sessionId", ""))
        if sess:
            sess.cancelled = True

    # ── prompt handling ──────────────────────────────────────────────────
    def prompt(self, params: dict, notify: NotifyFn) -> dict:
        """Handle one ``session/prompt`` turn. Returns ``{"stopReason": ...}``."""
        sid = params.get("sessionId", "")
        sess = self.sessions.get(sid)
        if sess is None:
            sess = self.sessions.setdefault(sid or "default", Session(sid or "default"))
        sess.cancelled = False

        text = _blocks_to_text(params.get("prompt", []))
        sess.history.append({"role": "user", "text": text})

        def emit(line: str) -> None:
            notify({"sessionId": sid, "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": line + "\n"},
            }})

        cmd, args = _parse_command(text)
        if cmd in ("help", ""):
            emit(_USAGE)
            return {"stopReason": "end_turn"}

        try:
            result = self._dispatch(cmd, args, sess, emit)
        except Exception as exc:  # never crash the editor session
            emit(f"[error] {exc}")
            return {"stopReason": "end_turn"}

        emit(("[OK] " if result.ok else "[FAILED] ") + result.summary)
        if result.detail:
            emit(result.detail)
        return {"stopReason": "cancelled" if sess.cancelled else "end_turn"}

    def _dispatch(self, cmd: str, args: list[str], sess: Session,
                  emit: Callable[[str], None]) -> CommandResult:
        def is_cancelled() -> bool:
            return sess.cancelled
        if cmd == "optimize":
            if not args:
                return CommandResult(False, "usage: optimize <benchmark|config> [k=v ...]")
            target = args[0]
            overrides = dict(_kv.split("=", 1) for _kv in args[1:] if "=" in _kv)
            backend = overrides.pop("backend", "")
            return self.caps.optimize(target, backend=backend, overrides=overrides,
                                      progress=emit, is_cancelled=is_cancelled)
        if cmd == "sleep":
            action = args[0] if args else "dry-run"
            kv = dict(_kv.split("=", 1) for _kv in args[1:] if "=" in _kv)
            return self.caps.sleep(action, project=kv.get("project", sess.cwd),
                                   backend=kv.get("backend", "mock"),
                                   progress=emit, is_cancelled=is_cancelled)
        if cmd == "skills":
            return self.caps.list_skills(progress=emit)
        return CommandResult(False, f"unknown command: {cmd}", _USAGE)


_USAGE = (
    "SkillOpt ACP agent — commands:\n"
    "  optimize <benchmark|config.yaml> [key=value ...]   train & export a skill\n"
    "  sleep <run|dry-run|adopt|status> [project=DIR backend=mock|claude|codex]\n"
    "  skills [list]                                      list skill artifacts\n"
    "  help                                               show this message"
)


def _blocks_to_text(blocks: list[dict]) -> str:
    parts: list[str] = []
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(str(b.get("text", "")))
    return "\n".join(parts).strip()


def _parse_command(text: str) -> tuple[str, list[str]]:
    text = text.strip()
    if not text:
        return "", []
    try:
        toks = shlex.split(text)
    except ValueError:
        toks = text.split()
    if not toks:
        return "", []
    return toks[0].lower(), toks[1:]
