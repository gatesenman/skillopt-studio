# SkillOpt Studio

A **cross-vendor desktop application** that puts Microsoft
[SkillOpt](https://microsoft.github.io/SkillOpt/) into the hands of everyone —
from non-technical beginners to power users — and exposes its skill-optimization
capabilities to **any ACP-compatible AI dev agent**.

> SkillOpt treats a skill document (`SKILL.md`) as trainable state and runs a
> reflective `rollout → reflect → aggregate → select → update → gate` loop to
> produce a compact, high-signal skill — with zero inference-time cost. SkillOpt
> Studio is a friendly shell on top of it.

## Why

| Goal | How Studio delivers it |
| --- | --- |
| 非技术人员也能使用专业能力 | 🟢 **向导模式**：选场景 → 填 1 个 Key → 开始，专业超参已预设 |
| 小白易用但不丢专业功能 | 🔵 **专家模式**：完整超参 / config / 多后端，等价于 CLI |
| 一键安装 | 📦 **PyInstaller** 打包成双击即用的本地 App |
| 支持 ACP 的 AI 智能体调用 | 🟣 **ACP Agent**：`skillopt-acp` 通过 stdio JSON-RPC 暴露能力 |
| 跨厂商 | OpenAI / Azure / Claude / Qwen / MiniMax / Codex CLI / Claude Code CLI |

## Architecture

```
skillopt_desktop/            native window (pywebview) + embedded FastAPI
  __main__.py  app.py        launch backend on 127.0.0.1, open desktop window
  server.py    state.py      JSON API + shared AppState
  services/                  training · sleep · skills · backends · presets · acp
  web/                       vanilla-JS UI (wizard · pro · monitor · skills · sleep · acp · settings)
  skillopt_assets_configs/   vendored copy of SkillOpt configs (offline-friendly)
skillopt_acp/                ACP agent (stdlib only)
  agent.py  server.py  jsonrpc.py  capabilities.py
plugins/acp/                 drop-in ACP manifest for editors
packaging/                   PyInstaller spec + build script
```

The desktop app **drives the real SkillOpt** when it is installed / a checkout
is found, and otherwise runs a fully-functional **demo mode** (simulated
pipeline + artifacts) so the whole UI is usable with no credentials.

## Quick start (from source)

```bash
cd skillopt-studio
python -m venv .venv && source .venv/bin/activate
pip install -e .                       # demo mode works immediately
pip install -e ".[skillopt]"           # (optional) enable live runs
skillopt-studio                         # opens the native desktop window
# headless / no GUI:
skillopt-studio --no-window             # serves the UI; open the printed URL
```

### Native desktop window backend

`skillopt-studio` opens a real native window via **pywebview**:

* **macOS** — uses the built-in WKWebView; nothing extra to install.
* **Windows** — uses the Edge **WebView2** runtime (preinstalled on Win 10/11;
  otherwise grab the free Evergreen runtime from Microsoft).
* **Linux** — needs a WebKitGTK runtime plus the Python GObject bindings:

```bash
# Debian/Ubuntu system libraries:
sudo apt-get install -y gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
    python3-gi python3-gi-cairo libgirepository1.0-dev libcairo2-dev pkg-config
# Python bindings into your venv (GTK backend):
pip install -e ".[desktop-gtk]"        # or ".[desktop-qt]" for the Qt backend
```

If no GUI backend is available the app automatically falls back to server-only
mode (it prints a `http://127.0.0.1:<port>` URL you can open in any browser),
so it is always usable.

To run real (non-demo) optimization, also have a SkillOpt checkout available —
set `SKILLOPT_REPO=/path/to/SkillOpt` (for the `configs/` + benchmark data), and
configure a provider in **厂商设置**.

## One-click install (packaged app)

Build a native, double-clickable bundle for the current OS with PyInstaller:

```bash
# macOS / Linux:
bash packaging/build.sh
#   Linux  -> dist/SkillOptStudio/SkillOptStudio
#   macOS  -> dist/SkillOptStudio.app

# Windows (either one):
packaging\build.bat
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#   -> dist\SkillOptStudio\SkillOptStudio.exe
```

> Packaged builds are **per-OS** — build on each target platform (or in CI) to
> get that platform's binary; PyInstaller does not cross-compile.

## ACP integration

```bash
skillopt-acp                            # stdio JSON-RPC agent
```

See [`plugins/acp/README.md`](plugins/acp/README.md). The **ACP 接入** tab can
register the agent into Zed with one click, or copy a generic config snippet.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## License

MIT — same as upstream SkillOpt. This project builds *on top of* SkillOpt and
does not modify it.
