"""ACP stdio server loop for the SkillOpt agent.

Launched by an ACP client (editor) as a subprocess. Reads newline-delimited
JSON-RPC from stdin, dispatches to :class:`ACPAgent`, and writes responses /
notifications to stdout. Anything that is not a valid ACP message must never
touch stdout, so all logging goes to stderr.

Console entry point: ``skillopt-acp``.
"""
from __future__ import annotations

import sys
import threading
from typing import Any

from . import jsonrpc as rpc
from .agent import ACPAgent

# JSON-RPC method name -> (handler attribute, is_notification)
_METHODS = {
    "initialize": ("initialize", False),
    "authenticate": ("authenticate", False),
    "session/new": ("new_session", False),
    "session/prompt": ("prompt", False),     # special: needs notify callback
    "session/cancel": ("cancel", True),
}


def serve_stdio(agent: ACPAgent | None = None,
                stdin: Any = None, stdout: Any = None) -> int:
    """Run the blocking ACP stdio loop. Returns process exit code."""
    agent = agent or ACPAgent()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    write_lock = threading.Lock()

    def write(msg: dict) -> None:
        with write_lock:
            stdout.write(rpc.encode(msg))
            stdout.flush()

    def notify(params: dict) -> None:
        write(rpc.make_notification("session/update", params))

    for msg in rpc.read_messages(stdin):
        method = msg.get("method")
        msg_id = msg.get("id")
        if method is None:  # a response to a server->client request; ignore
            continue
        entry = _METHODS.get(method)
        if entry is None:
            if msg_id is not None:
                write(rpc.make_response(msg_id, error=rpc.make_error(
                    rpc.METHOD_NOT_FOUND, f"method not found: {method}")))
            continue
        attr, is_notification = entry
        params = msg.get("params", {}) or {}
        try:
            if method == "session/prompt":
                result = agent.prompt(params, notify)
            else:
                handler = getattr(agent, attr)
                result = handler(params)
        except Exception as exc:  # noqa: BLE001
            _log(f"handler error in {method}: {exc}")
            if msg_id is not None:
                write(rpc.make_response(msg_id, error=rpc.make_error(
                    rpc.INTERNAL_ERROR, str(exc))))
            continue
        if not is_notification and msg_id is not None:
            write(rpc.make_response(msg_id, result=result))
    return 0


def _log(text: str) -> None:
    print(f"[skillopt-acp] {text}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    # The transport carries UTF-8 JSON (``ensure_ascii=False``). Console stdio
    # defaults to the locale encoding (e.g. cp1252 on Windows), which would
    # mangle non-ASCII payloads, so force UTF-8 on both ends when possible.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
