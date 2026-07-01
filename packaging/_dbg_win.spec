# PyInstaller spec — Windows build WITHOUT the native pywebview backend.
#
# Produces dist/SkillOptStudio/SkillOptStudio.exe. On launch it starts the
# embedded FastAPI server and opens a chromeless app-mode browser window
# (Chrome/Edge --app), so it behaves like a desktop app without requiring the
# native webview/.NET runtime. Used for cross-building from Linux via Wine; for
# a true native-window build use skillopt_studio.spec on real Windows/macOS.
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + ["skillopt_acp", "skillopt_acp.server", "skillopt_acp.agent"]
)

datas = [
    ("../skillopt_desktop/web", "skillopt_desktop/web"),
    ("../skillopt_desktop/skillopt_assets_configs", "skillopt_desktop/skillopt_assets_configs"),
]

a = Analysis(
    ["../skillopt_desktop/__main__.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "torch", "vllm", "webview", "clr", "pythonnet"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="SkillOptStudio", console=True, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="SkillOptStudio",
)
