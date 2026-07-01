"""Tests for the ACP agent + stdio server (no external deps, uses a mock backend)."""
import io
import json

from skillopt_acp.agent import ACPAgent
from skillopt_acp.capabilities import CommandResult
from skillopt_acp import jsonrpc as rpc
from skillopt_acp.server import serve_stdio


class FakeCaps:
    def __init__(self):
        self.calls = []

    def optimize(self, target, *, backend, overrides, progress, is_cancelled):
        self.calls.append(("optimize", target, backend, overrides))
        progress("rollout ...")
        return CommandResult(True, f"optimized {target}", "done")

    def sleep(self, action, *, project, backend, progress, is_cancelled):
        self.calls.append(("sleep", action, project, backend))
        return CommandResult(True, f"sleep {action}")

    def list_skills(self, progress):
        self.calls.append(("skills",))
        return CommandResult(True, "0 skills")


def _drive(agent, requests):
    stdin = io.StringIO("".join(rpc.encode(r) for r in requests))
    stdout = io.StringIO()
    serve_stdio(agent, stdin=stdin, stdout=stdout)
    return [json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()]


def test_initialize_and_new_session():
    agent = ACPAgent(FakeCaps())
    out = _drive(agent, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "/tmp"}},
    ])
    init = next(m for m in out if m.get("id") == 1)
    assert init["result"]["protocolVersion"] == 1
    assert init["result"]["agentInfo"]["name"] == "skillopt"
    sess = next(m for m in out if m.get("id") == 2)
    assert sess["result"]["sessionId"].startswith("sess_")


def test_prompt_optimize_dispatches_and_streams():
    caps = FakeCaps()
    agent = ACPAgent(caps)
    out = _drive(agent, [
        {"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/prompt",
         "params": {"sessionId": "s", "prompt": [{"type": "text", "text": "optimize docvqa backend=mock train.num_epochs=2"}]}},
    ])
    # capability invoked with parsed target + overrides
    assert ("optimize", "docvqa", "mock", {"train.num_epochs": "2"}) in caps.calls
    # streamed at least one session/update notification
    assert any(m.get("method") == "session/update" for m in out)
    # prompt returned a stopReason
    resp = next(m for m in out if m.get("id") == 2)
    assert resp["result"]["stopReason"] == "end_turn"


def test_unknown_method_returns_error():
    agent = ACPAgent(FakeCaps())
    out = _drive(agent, [{"jsonrpc": "2.0", "id": 9, "method": "bogus/method"}])
    err = next(m for m in out if m.get("id") == 9)
    assert err["error"]["code"] == rpc.METHOD_NOT_FOUND


def test_help_prompt():
    agent = ACPAgent(FakeCaps())
    out = _drive(agent, [
        {"jsonrpc": "2.0", "id": 1, "method": "session/prompt",
         "params": {"sessionId": "s", "prompt": [{"type": "text", "text": "help"}]}},
    ])
    notifs = [m for m in out if m.get("method") == "session/update"]
    assert any("optimize" in n["params"]["update"]["content"]["text"] for n in notifs)
