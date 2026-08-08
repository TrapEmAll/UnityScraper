# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


icon = 'assets/UnityScraper.ico' if sys.platform == 'win32' else None
tk_datas = []
if sys.platform == 'win32':
    tcl_root = Path(sys.base_prefix) / 'tcl' / 'tcl8.6'
    tk_root = Path(sys.base_prefix) / 'tcl' / 'tk8.6'
    if tcl_root.is_dir():
        tk_datas.append((str(tcl_root), '_tcl_data'))
    if tk_root.is_dir():
        tk_datas.append((str(tk_root), '_tk_data'))

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('JSON.txt', '.'),
        ('VERSION', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
        ('assets', 'assets'),
    ] + tk_datas,
    hiddenimports=collect_submodules('unityscraper') + [
        'backup_gui',
        'backup_manager',
        'backup_service',
        'collection_gui',
        'collection_intelligence',
        'community_gui',
        'community_services',
        'console_sync',
        'consolemods_adapters',
        'database_migrations',
        'dat_adapters',
        'knowledge_gui',
        'knowledge_service',
        'knowledge_scheduler',
        'knowledge_sync',
        'structured_knowledge',
        'tool_catalog',
        'unified_search',
        'plugins',
        'plugin_worker',
        'roadmap_services',
        'ui_theme',
        'gpd_parser',
        'profile_gui',
        'profile_intelligence',
        'profile_manager',
        'updater',
        'wiki_adapters',
        'xenia_bridge',
    ],
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
    name='UnityScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
