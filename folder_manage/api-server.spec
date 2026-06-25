# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# Spec lives in folder_manage; build deterministically from here on every platform.
FOLDER_MANAGE = os.path.abspath(SPECPATH)
if FOLDER_MANAGE not in sys.path:
    sys.path.insert(0, FOLDER_MANAGE)

# GUI-only / non-sidecar modules that must NOT be pulled into the headless API build.
_EXCLUDE_LOCAL = {"people_folder_manager"}


def _discover_local_modules():
    """自動掃描 folder_manage 根目錄的頂層單檔模組，新增後端模組免再手動維護 hidden-import。"""
    modules = []
    for name in sorted(os.listdir(FOLDER_MANAGE)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        module = name[:-3]
        if module in _EXCLUDE_LOCAL:
            continue
        modules.append(module)
    return modules


hiddenimports = []
hiddenimports += collect_submodules("api")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += _discover_local_modules()

a = Analysis(
    [os.path.join(FOLDER_MANAGE, "api", "main.py")],
    pathex=[FOLDER_MANAGE],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "customtkinter", "tkinterdnd2"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="api-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
