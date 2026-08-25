# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\main.py'],
    pathex=['src'],
    binaries=[],
    datas=[('config.yaml.example', '.')],
    hiddenimports=['PIL', 'numpy', 'cv2', 'yaml'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The CLI has no GUI; keep Qt and tkinter out of the bundle.
    excludes=['tkinter', 'PySide6', 'shiboken6', 'PyQt5', 'PyQt6'],
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
    name='MSFS-MCDU-Scraper-CLI',
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
    icon='NONE',
)
