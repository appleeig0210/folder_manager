# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['api.deps', 'api.routes.config', 'api.routes.tree', 'api.routes.preview', 'api.routes.thumbnails', 'api.routes.tags', 'api.routes.files', 'media_keyword_service', 'folder_tags_migration', 'tag_index_store', 'app_paths', 'exiftool_session', 'media_path_filters', 'people_data_store']
hiddenimports += collect_submodules('uvicorn')


a = Analysis(
    ['api\\main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='api-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
