"""Desktop shell for SkillOpt Studio.

Starts the embedded FastAPI backend on a loopback port in a background thread,
then opens a native desktop window (pywebview) pointed at it. Falls back to
"server-only" mode (printing the URL) when no GUI/webview is available, e.g. on
a headless machine.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import uvicorn

from .server import create_app
from .state import AppState


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _chrome_candidates() -> list[str]:
    """Likely Chrome/Edge executables, per platform (for app-mode windows)."""
    if sys.platform.startswith("win"):
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        names = []
        for base in (pf, pfx86):
            names += [
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
        if local:
            names.append(os.path.join(local, "Google", "Chrome",
                                      "Application", "chrome.exe"))
        return names + ["chrome.exe", "msedge.exe"]
    if sys.platform == "darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "google-chrome", "chromium",
        ]
    return ["google-chrome", "google-chrome-stable", "chromium",
            "chromium-browser", "microsoft-edge"]


def _open_app_window(url: str) -> bool:
    """Open *url* as a chromeless app-mode window when a browser supports it.

    Falls back to the default browser. Returns True if anything was launched.
    This gives the packaged (no-pywebview) build a desktop-like window without
    requiring the native webview runtime.
    """
    for cand in _chrome_candidates():
        exe = cand if os.path.isabs(cand) and os.path.exists(cand) else shutil.which(cand)
        if exe:
            try:
                subprocess.Popen([exe, f"--app={url}",
                                  "--window-size=1180,820"])
                return True
            except Exception:  # noqa: BLE001
                continue
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001
        return False


class _ServerThread(threading.Thread):
    def __init__(self, app, port: int):
        super().__init__(daemon=True)
        self._config = uvicorn.Config(app, host="127.0.0.1", port=port,
                                      log_level="warning")
        self.server = uvicorn.Server(self._config)

    def run(self) -> None:
        self.server.run()

    def wait_until_up(self, port: int, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.1)
        return False


def run_desktop(port: int = 0, open_window: bool = True, dev: bool = False) -> int:
    """Launch the backend and (optionally) the native window."""
    state = AppState.create()
    app = create_app(state)
    port = port or _free_port()
    server = _ServerThread(app, port)
    server.start()
    server.wait_until_up(port)
    url = f"http://127.0.0.1:{port}"

    if not open_window:
        print(f"SkillOpt Studio backend running at {url} (Ctrl+C to quit)")
        try:
            while server.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        return 0

    try:
        import webview  # type: ignore
    except Exception:  # noqa: BLE001
        # No native webview runtime (e.g. the lightweight packaged build):
        # open a chromeless app-mode browser window instead, so the app still
        # behaves like a desktop program.
        opened = _open_app_window(url)
        if opened:
            print(f"SkillOpt Studio opened at {url} (close the window or Ctrl+C to quit)")
        else:
            print("Open this URL in your browser:", url)
        try:
            while server.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        return 0

    window = webview.create_window("SkillOpt Studio", url,
                                   width=1180, height=820, min_size=(900, 640))
    state.window = window      # expose for native file dialogs
    # Disable private mode so the embedded webview exposes a real, persistent
    # localStorage (otherwise it is ``null`` and the language toggle cannot be
    # remembered). Store the webview profile under the app home directory.
    storage_path = str(state.home / "webview")
    try:
        webview.start(debug=dev, private_mode=False, storage_path=storage_path)
    except Exception:  # noqa: BLE001 - fall back to default ephemeral storage
        webview.start(debug=dev)
    # window closed -> stop the server and exit
    server.server.should_exit = True
    return 0
