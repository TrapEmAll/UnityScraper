# -*- mode: python ; coding: utf-8 -*-

import sys


icon = 'assets/UnityScraper.ico' if sys.platform == 'win32' else None

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('JSON.txt', '.'),
        ('VERSION', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'backup_gui',
        'backup_manager',
        'backup_service',
        'collection_gui',
        'collection_intelligence',
        'console_sync',
        'consolemods_adapters',
        'database_migrations',
        'dat_adapters',
        'knowledge_gui',
        'knowledge_service',
        'knowledge_sync',
        'plugins',
        'updater',
        'wiki_adapters',
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
