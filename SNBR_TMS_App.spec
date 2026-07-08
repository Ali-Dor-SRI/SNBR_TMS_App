# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SNBR TMS App — Windows single-file executable.

Builds a self-contained ``--onefile --windowed`` executable that can be
handed out as a single ``.exe`` (no folder, no installer).

Companion of the macOS spec at ``macos_build/SNBR_TMS_App_macos.spec``, which
produces a ``.app`` bundle. Do **not** run this spec on macOS or that spec on
Windows — they bundle platform-specific runtime libraries.

Output: ``dist/SNBR_TMS_App.exe``
"""

import os
import sys

import customtkinter

block_cipher = None

# Locate customtkinter package data (themes, assets).
ctk_path = os.path.dirname(customtkinter.__file__)

# Bundle the Python runtime / VC++ DLLs explicitly when they sit next to the
# interpreter (only those that actually exist; PyInstaller also finds the core
# Python DLL on its own).
_python_dir = os.path.dirname(sys.executable)
_runtime_dlls = []
for _dll in ('python3.dll', 'python312.dll', 'python313.dll', 'python314.dll',
             'vcruntime140.dll', 'vcruntime140_1.dll'):
    _path = os.path.join(_python_dir, _dll)
    if os.path.isfile(_path):
        _runtime_dlls.append((_path, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_runtime_dlls,
    datas=[
        # CustomTkinter theme/assets
        (ctk_path, 'customtkinter/'),
        # Institutional letterhead PNGs used on the report cover page
        ('icons', 'icons'),
    ],
    hiddenimports=[
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends.backend_agg',
        'matplotlib.backends.backend_pdf',
        'tkcalendar',
        'babel.numbers',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest', 'IPython', 'notebook', 'sphinx',
        'matplotlib.backends.backend_qt5agg',
        'matplotlib.backends.backend_wxagg',
        'matplotlib.backends.backend_gtk3agg',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --onefile: fold the scripts, binaries and data into a single executable.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SNBR_TMS_App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # --windowed (no terminal window)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,       # drop a .ico in the project and set its path to customise
)
