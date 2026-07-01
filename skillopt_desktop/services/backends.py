"""Provider/backend credential management for SkillOpt Studio.

SkillOpt supports many model backends (OpenAI, Azure OpenAI, Claude, Qwen,
MiniMax, Codex CLI, Claude Code CLI). For beginners we present each as a small
form ("fill one key"); credentials are stored locally (0600) under
``~/.skillopt/credentials.json`` and translated to the environment variables
SkillOpt expects when a training job launches.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Field:
    key: str
    label: str
    required: bool = True
    secret: bool = True
    placeholder: str = ""


@dataclass
class BackendSpec:
    id: str
    name: str
    kind: str                       # "api" | "cli"
    fields: list[Field]
    note: str = ""


@dataclass
class BackendStatus:
    id: str
    name: str
    kind: str
    configured: bool
    fields: list[dict]
    note: str = ""


@dataclass
class ConnResult:
    ok: bool
    message: str


# Declarative catalogue of supported backends and the fields each needs.
SPECS: list[BackendSpec] = [
    BackendSpec("openai_chat", "OpenAI", "api", [
        Field("OPENAI_API_KEY", "API Key", placeholder="sk-..."),
        Field("OPENAI_BASE_URL", "Base URL (optional)", required=False, secret=False,
              placeholder="https://api.openai.com/v1"),
    ], "Works with OpenAI-compatible endpoints."),
    BackendSpec("azure_openai", "Azure OpenAI", "api", [
        Field("AZURE_OPENAI_ENDPOINT", "Endpoint", secret=False,
              placeholder="https://your-resource.openai.azure.com/"),
        Field("AZURE_OPENAI_API_KEY", "API Key"),
        Field("AZURE_OPENAI_API_VERSION", "API Version", required=False, secret=False,
              placeholder="2024-12-01-preview"),
    ]),
    BackendSpec("claude_chat", "Anthropic Claude", "api", [
        Field("ANTHROPIC_API_KEY", "API Key", placeholder="sk-ant-..."),
    ]),
    BackendSpec("qwen_chat", "Qwen (vLLM/DashScope)", "api", [
        Field("QWEN_CHAT_BASE_URL", "Base URL", secret=False,
              placeholder="http://localhost:8000/v1"),
        Field("QWEN_CHAT_API_KEY", "API Key", required=False),
    ]),
    BackendSpec("minimax_chat", "MiniMax", "api", [
        Field("MINIMAX_API_KEY", "API Key"),
        Field("MINIMAX_BASE_URL", "Base URL (optional)", required=False, secret=False,
              placeholder="https://api.minimax.io/v1"),
    ]),
    BackendSpec("codex_exec", "Codex CLI", "cli", [
        Field("CODEX_EXEC_PATH", "codex binary path", required=False, secret=False,
              placeholder="codex"),
    ], "Requires the `codex` CLI installed and logged in."),
    BackendSpec("claude_code_exec", "Claude Code CLI", "cli", [
        Field("CLAUDE_CODE_EXEC_PATH", "claude binary path", required=False, secret=False,
              placeholder="claude"),
    ], "Requires the `claude` CLI installed and logged in."),
]
_SPEC_BY_ID = {s.id: s for s in SPECS}


class BackendRegistry:
    """Loads/saves provider credentials and reports connectivity."""

    def __init__(self, home: Path):
        self.home = home
        self.path = home / "credentials.json"
        self._creds: dict[str, dict[str, str]] = self._load()

    # ── persistence ──────────────────────────────────────────────────────
    def _load(self) -> dict[str, dict[str, str]]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _persist(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._creds, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ── public API ───────────────────────────────────────────────────────
    def list_status(self) -> list[BackendStatus]:
        out: list[BackendStatus] = []
        for spec in SPECS:
            saved = self._creds.get(spec.id, {})
            fields = []
            for f in spec.fields:
                d = asdict(f)
                # never echo secret values back; only whether they are set
                d["set"] = bool(saved.get(f.key))
                fields.append(d)
            configured = all(
                saved.get(f.key) for f in spec.fields if f.required
            ) if spec.kind == "api" else True
            out.append(BackendStatus(spec.id, spec.name, spec.kind,
                                     configured, fields, spec.note))
        return out

    def save(self, backend: str, creds: dict[str, str]) -> None:
        spec = _SPEC_BY_ID.get(backend)
        if spec is None:
            raise ValueError(f"unknown backend: {backend}")
        # drop empty values so we don't clobber previously stored secrets
        clean = {k: v for k, v in creds.items() if v not in (None, "")}
        self._creds.setdefault(backend, {}).update(clean)
        self._persist()

    def test_connection(self, backend: str, creds: dict[str, str]) -> ConnResult:
        spec = _SPEC_BY_ID.get(backend)
        if spec is None:
            return ConnResult(False, f"unknown backend: {backend}")
        merged = {**self._creds.get(backend, {}), **{k: v for k, v in creds.items() if v}}
        if spec.kind == "cli":
            binary = merged.get(spec.fields[0].key) or spec.fields[0].placeholder or backend
            found = shutil.which(binary)
            return ConnResult(bool(found),
                              f"found {binary} at {found}" if found else f"{binary} not on PATH")
        url = self._endpoint_for(backend, merged)
        if not url:
            return ConnResult(False, "missing endpoint/base URL")
        # When a key is present, do a real authenticated probe; otherwise fall
        # back to a plain reachability check (DNS + TCP/HTTP).
        probe = self._auth_probe(backend, url, merged)
        if probe is not None:
            return probe
        return self._can_connect(url)

    def as_env(self) -> dict[str, str]:
        """Flatten all saved credentials into environment variables."""
        env: dict[str, str] = {}
        for _backend, creds in self._creds.items():
            for k, v in creds.items():
                if v:
                    env[k] = v
        return env

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _endpoint_for(backend: str, merged: dict[str, str]) -> str:
        if backend == "azure_openai":
            return merged.get("AZURE_OPENAI_ENDPOINT", "")
        if backend == "openai_chat":
            return merged.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        if backend == "claude_chat":
            return "https://api.anthropic.com"
        if backend == "qwen_chat":
            return merged.get("QWEN_CHAT_BASE_URL", "")
        if backend == "minimax_chat":
            return merged.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1"
        return ""

    @staticmethod
    def _auth_probe(backend: str, url: str, merged: dict[str, str],
                    timeout: float = 8.0) -> ConnResult | None:
        """Authenticated reachability probe. Returns ``None`` when no key is
        available (caller falls back to a plain reachability check). Otherwise
        hits a cheap, auth-protected endpoint and interprets the status:
        2xx -> key works; 401/403 -> reachable but key rejected."""
        base = url.rstrip("/")
        probe_url: str
        headers: dict[str, str] = {}
        if backend in ("openai_chat", "qwen_chat", "minimax_chat"):
            key = (merged.get("OPENAI_API_KEY") or merged.get("QWEN_CHAT_API_KEY")
                   or merged.get("MINIMAX_API_KEY"))
            if not key:
                return None
            probe_url = f"{base}/models"
            headers = {"Authorization": f"Bearer {key}"}
        elif backend == "azure_openai":
            key = merged.get("AZURE_OPENAI_API_KEY")
            if not key:
                return None
            ver = merged.get("AZURE_OPENAI_API_VERSION") or "2024-12-01-preview"
            probe_url = f"{base}/openai/models?api-version={ver}"
            headers = {"api-key": key}
        elif backend == "claude_chat":
            key = merged.get("ANTHROPIC_API_KEY")
            if not key:
                return None
            probe_url = f"{base}/v1/models"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        else:
            return None
        try:
            req = urllib.request.Request(probe_url, method="GET", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    return ConnResult(True, f"authenticated OK ({resp.status})")
                return ConnResult(True, f"reachable ({resp.status})")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return ConnResult(False, f"reachable but key rejected ({exc.code})")
            if exc.code == 404:
                # endpoint reachable; some gateways hide /models
                return ConnResult(True, f"reachable ({exc.code}); key not verified")
            return ConnResult(True, f"reachable ({exc.code})")
        except Exception as exc:  # noqa: BLE001
            return ConnResult(False, f"cannot reach {probe_url}: {exc}")

    @staticmethod
    def _can_connect(url: str, timeout: float = 5.0) -> ConnResult:
        """Best-effort reachability check (DNS + TCP/HTTP), no auth required."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if "://" in url else f"https://{url}")
            host = parsed.hostname or url
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            socket.create_connection((host, port), timeout=timeout).close()
        except Exception as exc:  # noqa: BLE001
            return ConnResult(False, f"cannot reach {url}: {exc}")
        # try a lightweight HTTP request (any status counts as reachable)
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            pass  # reachable, just unauthorized/not-found -> fine
        except Exception:
            pass
        return ConnResult(True, f"reachable: {url}")
