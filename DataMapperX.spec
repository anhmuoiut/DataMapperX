# -*- mode: python ; coding: utf-8 -*-
# Build with:  powershell -File tools\build.ps1
import os
import sys

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
    ] + collect_data_files('reportlab'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing the app uses. lxml is only an optional speed-up for openpyxl and would add 3.5 MB; multiprocessing is
    # only pulled in by a part of concurrent.futures that is never called. tkinter is the old interface: it must not
    # sneak back in (it would carry the whole of Tcl/Tk). Of Qt the application imports QtCore, QtGui and QtWidgets only.
    excludes=[
        'pytest', 'unittest', 'pydoc', 'doctest', 'numpy', 'pandas', 'lxml', 'multiprocessing', 'xmlrpc',
        'setuptools', 'pkg_resources', 'distutils', 'lib2to3', 'test',
        'tkinter', '_tkinter', 'turtle',
        'PySide6.QtNetwork', 'PySide6.QtDBus', 'PySide6.QtSvg', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtPdf',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtTest', 'PySide6.QtPrintSupport', 'PySide6.QtSql',
        'PySide6.QtXml', 'PySide6.QtConcurrent', 'PySide6.QtHelp', 'PySide6.QtUiTools',
    ],
    noarchive=False,
    optimize=0,  # not 2: without docstrings every dataclass would call inspect.signature when it is imported
)

# A one-file exe unpacks all of its files into a temporary folder every time it starts, and deletes them when it
# exits, so the NUMBER of files and their size matter (each one is also scanned by antivirus). These Qt files are never
# used: the translations only translate Qt's own dialogs (the application's text is English), the image-format plugins
# other than the one that reads the .ico are not needed (PNG is built into QtGui), and Windows 11's native style is not
# used because the application draws with Fusion and its own palette.
_UNUSED = ('PySide6/translations/', 'PySide6/qml/', 'PySide6/plugins/styles/', 'PySide6/plugins/tls/',
           'PySide6/plugins/networkinformation/', 'PySide6/plugins/generic/', 'PySide6/plugins/iconengines/')
_KEEP_IMAGE_PLUGINS = ('qico',)  # a window icon is an .ico


def _used(item) -> bool:
    name = item[0].replace('\\', '/')
    if name.startswith(_UNUSED):
        return False
    if name.startswith('PySide6/plugins/imageformats/'):
        return os.path.basename(name).split('.')[0] in _KEEP_IMAGE_PLUGINS
    return True


a.datas = [item for item in a.datas if _used(item)]
a.binaries = [item for item in a.binaries if _used(item)]

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
