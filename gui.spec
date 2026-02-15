# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for MSFS MCDU Scraper GUI
"""

block_cipher = None

a = Analysis(
    ['src/gui.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('config.yaml.example', '.'),
        ('docs', 'docs'),
        ('README.md', '.'),
        ('QUICKSTART.md', '.'),
        ('LICENSE', '.'),
    ],
    hiddenimports=[
        'PIL',
        'PIL._tkinter_finder',
        'numpy',
        'cv2',
        'yaml',
        'win32gui',
        'win32ui',
        'win32con',
        'win32api',
        'pytesseract',
        'mss',
        'websockets',
        'websockets.asyncio',
        'websockets.asyncio.client',
        'asyncio',
        'queue',
        'threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MSFS-MCDU-Scraper-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window for GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
