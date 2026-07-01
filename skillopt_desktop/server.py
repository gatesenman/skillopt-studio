"""FastAPI backend for SkillOpt Studio.

Serves the web frontend and a small JSON API over 127.0.0.1 that the desktop
window (pywebview) talks to. All heavy lifting is delegated to the service
layer in :mod:`skillopt_desktop.services`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import AppState
from .services.training import TrainStartReq

WEB_DIR = Path(__file__).parent / "web"


def _open_dialog(state: AppState, *, folder: bool) -> dict:
    """Open a native pywebview file/folder picker. Returns the chosen path or
    ``{"unsupported": True}`` when not running inside a desktop window (e.g. a
    plain browser), so the UI can fall back to manual path entry."""
    window = getattr(state, "window", None)
    if window is None:
        return {"unsupported": True}
    try:
        import webview  # type: ignore
        dtype = webview.FOLDER_DIALOG if folder else webview.OPEN_DIALOG
        result = window.create_file_dialog(dtype)
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return {"path": str(path)}
    except Exception as exc:  # noqa: BLE001
        return {"unsupported": True, "error": str(exc)}


# ── request models ───────────────────────────────────────────────────────
class BackendCreds(BaseModel):
    backend: str
    creds: dict = {}


class TrainBody(BaseModel):
    config_path: str = ""
    preset_id: str = ""
    overrides: dict = {}
    backend: str = ""
    mock: bool = False


class EvalBody(BaseModel):
    config_path: str = ""
    skill_path: str = ""
    backend: str = ""
    overrides: dict = {}
    mock: bool = False


class SleepBody(BaseModel):
    project: str = ""
    backend: str = "mock"
    dry_run: bool = True
    auto_adopt: bool = False
    max_tasks: int = 40


class ExportBody(BaseModel):
    dest: str


class ImportBody(BaseModel):
    src: str
    name: str = ""


class AcpRegisterBody(BaseModel):
    editor: str


class ValidateBody(BaseModel):
    config_path: str = ""
    overrides: dict = {}


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="SkillOpt Studio", version="0.1.0")

    def _resolve_config(req: TrainBody) -> str:
        """Resolve a preset/config path to an absolute file when possible."""
        path = req.config_path
        if req.preset_id and not path:
            preset = state.presets.get(req.preset_id)
            if preset:
                path = preset.config_path
        if not path:
            return path
        p = Path(path)
        if p.is_absolute() and p.exists():
            return str(p)
        # try repo root, then bundled configs (strip leading "configs/")
        if state.skillopt_root and (state.skillopt_root / path).exists():
            return str(state.skillopt_root / path)
        rel = path[len("configs/"):] if path.startswith("configs/") else path
        bundled = state.configs_root / rel
        if bundled.exists():
            return str(bundled)
        return path

    # ── meta ─────────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "version": app.version,
            "skillopt_root": str(state.skillopt_root) if state.skillopt_root else None,
            "live": state.training._can_run_real(),
            "home": str(state.home),
        }

    # ── presets / benchmarks ───────────────────────────────────────────────
    @app.get("/api/presets")
    def presets():
        return [p.to_dict() for p in state.presets.list()]

    @app.get("/api/benchmarks")
    def benchmarks():
        root = state.configs_root
        names = []
        if root.exists():
            for d in sorted(root.iterdir()):
                if d.is_dir() and d.name != "_base_" and (d / "default.yaml").exists():
                    names.append(d.name)
        return names

    # ── backends ───────────────────────────────────────────────────────────
    @app.get("/api/backends")
    def backends():
        return [b.__dict__ for b in state.backends.list_status()]

    @app.post("/api/backends/test")
    def backends_test(body: BackendCreds):
        return state.backends.test_connection(body.backend, body.creds).__dict__

    @app.post("/api/backends")
    def backends_save(body: BackendCreds):
        state.backends.save(body.backend, body.creds)
        return {"ok": True}

    # ── training / eval ─────────────────────────────────────────────────────
    @app.post("/api/train/start")
    def train_start(body: TrainBody):
        req = TrainStartReq(
            config_path=_resolve_config(body),
            preset_id=body.preset_id, overrides=body.overrides,
            backend=body.backend, mock=body.mock,
        )
        return {"run_id": state.training.start(req)}

    @app.post("/api/eval/start")
    def eval_start(body: EvalBody):
        cfg = _resolve_config(TrainBody(config_path=body.config_path))
        req = TrainStartReq(config_path=cfg, backend=body.backend,
                            overrides=body.overrides, kind="eval",
                            skill_path=body.skill_path, mock=body.mock)
        return {"run_id": state.training.start_eval(req)}

    @app.get("/api/train/{run_id}/status")
    def train_status(run_id: str):
        st = state.training.status(run_id)
        if st is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return st

    @app.post("/api/train/{run_id}/stop")
    def train_stop(run_id: str):
        return {"message": state.training.stop(run_id)}

    @app.get("/api/runs")
    def runs_list():
        """Run history: past + live runs with best score / status / artifacts."""
        return state.training.list_runs()

    @app.get("/api/train/{run_id}/trajectory")
    def train_trajectory(run_id: str):
        """Per-step edit + held-out gate trajectory (accept/reject + scores)."""
        traj = state.training.trajectory(run_id)
        if traj is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return traj

    @app.post("/api/config/validate")
    def config_validate(body: ValidateBody):
        """Flag override keys SkillOpt would silently ignore (pre-flight)."""
        from .services.configspec import known_keys, unknown_overrides
        cfg = _resolve_config(TrainBody(config_path=body.config_path))
        known = known_keys(state.skillopt_root, cfg)
        return {
            "checked": known is not None,
            "unknown": unknown_overrides(body.overrides, known),
        }

    @app.get("/api/train/{run_id}/log")
    def train_log(run_id: str, offset: int = 0):
        """Polling-friendly log tail + status (used by the UI; no websocket needed)."""
        run = state.training.runs.get(run_id)
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        lines = run.log_lines[offset:]
        return {"lines": lines, "next_offset": offset + len(lines), "status": run.status()}

    @app.websocket("/api/train/{run_id}/logs")
    async def train_logs(ws: WebSocket, run_id: str):
        await ws.accept()
        loop = asyncio.get_event_loop()
        gen = state.training.stream_logs(run_id)
        try:
            while True:
                line = await loop.run_in_executor(None, lambda: next(gen, None))
                if line is None:
                    st = state.training.status(run_id)
                    await ws.send_json({"type": "status", "data": st})
                    break
                await ws.send_json({"type": "log", "line": line})
                st = state.training.status(run_id)
                await ws.send_json({"type": "status", "data": st})
        except (WebSocketDisconnect, RuntimeError):
            pass

    # ── skills ───────────────────────────────────────────────────────────
    @app.get("/api/skills")
    def skills_list():
        return [s.to_dict() for s in state.skills.list()]

    @app.get("/api/skills/{skill_id}")
    def skills_get(skill_id: str):
        d = state.skills.get(skill_id)
        if d is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return d.__dict__

    @app.post("/api/skills/{skill_id}/export")
    def skills_export(skill_id: str, body: ExportBody):
        try:
            return {"path": state.skills.export(skill_id, body.dest)}
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @app.post("/api/skills/import")
    def skills_import(body: ImportBody):
        try:
            return state.skills.import_file(body.src, body.name).to_dict()
        except FileNotFoundError:
            return JSONResponse({"error": "source not found"}, status_code=404)

    @app.delete("/api/skills/{skill_id}")
    def skills_delete(skill_id: str):
        try:
            return state.skills.delete(skill_id)
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    # ── native file dialogs (pywebview desktop only) ─────────────────────
    @app.get("/api/dialog/folder")
    def dialog_folder():
        return _open_dialog(state, folder=True)

    @app.get("/api/dialog/file")
    def dialog_file():
        return _open_dialog(state, folder=False)

    # ── sleep ────────────────────────────────────────────────────────────
    @app.post("/api/sleep/run")
    def sleep_run(body: SleepBody):
        return state.sleep.run(body.project, body.backend, dry_run=body.dry_run,
                               auto_adopt=body.auto_adopt,
                               max_tasks=body.max_tasks).to_dict()

    @app.post("/api/sleep/adopt")
    def sleep_adopt(body: SleepBody):
        return state.sleep.adopt(body.project, body.backend).to_dict()

    @app.get("/api/sleep/status")
    def sleep_status(project: str = "", backend: str = "mock"):
        return state.sleep.status(project, backend).to_dict()

    # ── acp ──────────────────────────────────────────────────────────────
    @app.get("/api/acp/status")
    def acp_status():
        return {**state.acp.status(), "snippet": state.acp.command_snippet()}

    @app.post("/api/acp/register")
    def acp_register(body: AcpRegisterBody):
        return state.acp.register_with_editor(body.editor).__dict__

    # ── frontend ───────────────────────────────────────────────────────────
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html")

    return app
