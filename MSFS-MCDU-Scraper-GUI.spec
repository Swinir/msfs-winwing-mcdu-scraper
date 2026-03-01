# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\gui.py'],
    pathex=['src'],
    binaries=[],
    datas=[('config.yaml.example', '.')],
    hiddenimports=['PIL', 'PIL._tkinter_finder', 'numpy', 'cv2', 'yaml', 'win32gui', 'win32ui', 'win32con', 'win32api'],
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
    name='MSFS-MCDU-Scraper-GUI',
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
    icon='NONE',
)
