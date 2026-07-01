"""Minimal JSON-RPC 2.0 helpers for the ACP stdio transport.

stdlib-only on purpose: the ACP agent is launched as a subprocess by an editor
and must not pull heavy dependencies. Messages are newline-delimited JSON
objects (one per line) per the ACP stdio transport spec.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, TextIO

JSONRPC_VERSION = "2.0"


def read_messages(stream: TextIO) -> Iterator[dict]:
    """Yield parsed JSON-RPC messages from a newline-delimited stream.

    Blank lines and malformed lines are skipped (malformed lines are ignored
    rather than crashing the loop, matching lenient editor behaviour).
    """
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            yield msg


def make_response(msg_id: Any, result: Any = None, error: dict | None = None) -> dict:
    """Build a JSON-RPC response object."""
    out: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def make_notification(method: str, params: dict | None = None) -> dict:
    """Build a JSON-RPC notification (no id, no response expected)."""
    out: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        out["params"] = params
    return out


def make_error(code: int, message: str, data: Any = None) -> dict:
    """Build a JSON-RPC error object."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


# Standard JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def encode(msg: dict) -> str:
    """Serialise a message to a single newline-terminated line (no embedded \\n)."""
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n"
