# -*- mode: python ; coding: utf-8 -*-
# Build with:  powershell -File tools\build.ps1
import os

from PyInstaller.utils.hooks import collect_data_files

# Windows file-properties block (name, version, publisher). Written by tools/make_version_info.py.
version_file = 'version_info.txt' if os.path.exists('version_info.txt') else None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')] + collect_data_files('sv_ttk'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing the app uses; keeps the exe smaller.
    excludes=['pytest', 'unittest', 'pydoc', 'doctest', 'PIL', 'numpy', 'pandas'],
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
    name='DataMapperX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables are flagged by many antivirus products; the size saving is not worth it.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='assets/DataMapperX.ico',
    version=version_file,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
