# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SNBR TMS App — macOS .app bundle.

Companion of the Windows spec at ``SNBR_TMS_App/SNBR_TMS_App.spec``. Do
**not** use this on Windows, and do not use the Windows spec on macOS.

Usage
-----
From the project root (one level up from this file)::

    cd SNBR_TMS_App
    ./macos_build/build.sh

The build script passes ``--distpath dist_macos`` and
``--workpath build_macos`` so the macOS output lands in
``SNBR_TMS_App/dist_macos/`` and never overwrites the Windows build's
default ``dist/`` and ``build/`` directories.

Output: ``dist_macos/SNBR_TMS_App.app``
"""

import os
from pathlib import Path

import customtkinter

block_cipher = None

# This spec lives in SNBR_TMS_App/macos_build/, but PyInstaller runs with the
# current working directory set to wherever ``pyinstaller`` is invoked from.
# Resolve data paths relative to the project root so the build works no
# matter where it's started from.
_PROJECT_ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = dir of this file

ctk_path = os.path.dirname(customtkinter.__file__)

a = Analysis(
    [str(_PROJECT_ROOT / 'main.py')],
    pathex=[str(_PROJECT_ROOT)],
    binaries=[],
    datas=[
        # CustomTkinter theme/assets
        (ctk_path, 'customtkinter/'),
        # Institutional letterhead PNGs used on the report cover page
        (str(_PROJECT_ROOT / 'icons'), 'icons'),
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SNBR_TMS_App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX is unreliable on macOS — never enable it here
    console=False,        # windowed app, no terminal pops up
    disable_windowed_traceback=False,
    target_arch=None,     # build for the arch of the Python you invoke
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SNBR_TMS_App',
)

app = BUNDLE(
    coll,
    name='SNBR_TMS_App.app',
    icon=None,  # drop a .icns into macos_build/ and set its path here to customise
    bundle_identifier='ca.sunnybrook.snbr.tms',
    info_plist={
        'CFBundleName': 'SNBR TMS App',
        'CFBundleDisplayName': 'SNBR TMS App',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,  # crisp matplotlib on Retina displays
        'LSMinimumSystemVersion': '11.0',
        'NSAppleEventsUsageDescription':
            'Report generation uses AppleEvents for file dialogs.',
    },
)
