# PyInstaller spec for SkillOpt Studio — one-click single-folder/onefile build.
#
#   pip install -e ".[build]"
#   pyinstaller packaging/skillopt_studio.spec
#
# Produces a native, double-clickable app that bundles the embedded FastAPI
# server, the web UI, and the vendored configs:
#   * Windows -> dist/SkillOptStudio/SkillOptStudio.exe
#   * Linux   -> dist/SkillOptStudio/SkillOptStudio
#   * macOS   -> dist/SkillOptStudio.app (plus the SkillOptStudio folder)
import sys

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
IS_MAC = sys.platform == "darwin"

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + collect_submodules("webview")
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
    excludes=["tkinter", "matplotlib", "torch", "vllm"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="SkillOptStudio", console=False, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=True,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, name="SkillOptStudio",
)

# On macOS, also wrap the collected app into a double-clickable .app bundle.
if IS_MAC:
    app = BUNDLE(
        coll,
        name="SkillOptStudio.app",
        icon=None,
        bundle_identifier="com.skillopt.studio",
        info_plist={"NSHighResolutionCapable": True},
    )
