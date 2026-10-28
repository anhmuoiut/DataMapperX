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
    # Only runtime branding belongs in the executable.
    datas=[
        ('assets/DataMapperX.png', 'assets'),
        ('assets/DataMapperX.ico', 'assets'),
        ('assets/Jabil-Logo-*.png', 'assets'),
    ] + collect_data_files('sv_ttk'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing the app uses. lxml is only an optional speed-up for openpyxl and would add 3.5 MB; multiprocessing is
    # only pulled in by a part of concurrent.futures that is never called.
    excludes=[
        'pytest', 'unittest', 'pydoc', 'doctest', 'PIL', 'numpy', 'pandas', 'lxml', 'multiprocessing', 'xmlrpc',
        'setuptools', 'pkg_resources', 'distutils', 'lib2to3', 'test',
    ],
    noarchive=False,
    optimize=0,  # not 2: without docstrings every dataclass would call inspect.signature when it is imported
)

# A one-file exe unpacks all of its files into a temporary folder every time it starts, and deletes them when it
# exits, so the NUMBER of files matters more than their size (each one is also scanned by antivirus). These Tcl/Tk
# files are never used: time zones are only needed by Tcl's "clock" command, and the message catalogues only
# translate Tk's own dialogs, which Windows replaces with its native ones.
_UNUSED = ('_tcl_data/tzdata/', '_tcl_data/msgs/', '_tk_data/msgs/')
a.datas = [item for item in a.datas if not item[0].replace('\\', '/').startswith(_UNUSED)]

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
