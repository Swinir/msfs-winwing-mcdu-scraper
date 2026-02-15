# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for MSFS MCDU Scraper CLI
"""

block_cipher = None

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('config.yaml.example', '.'),
        ('README.md', '.'),
    ],
    hiddenimports=[
        'PIL',
        'numpy',
        'cv2',
        'yaml',
        'pytesseract',
        'mss',
        'websockets',
        'websockets.asyncio',
        'websockets.asyncio.client',
        'asyncio',
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
    name='MSFS-MCDU-Scraper-CLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Console window for CLI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
