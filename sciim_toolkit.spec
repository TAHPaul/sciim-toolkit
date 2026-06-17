# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SciIm Toolkit — one spec, both platforms.

Build:
    pip install ".[build]"
    pyinstaller --noconfirm sciim_toolkit.spec

Output:
    macOS   -> dist/SciIm Toolkit.app
    Windows -> dist/SciIm Toolkit/  (folder containing SciIm Toolkit.exe)

This spec is compatible with PyInstaller 6.x (no block_cipher / a.zipped_data).
"""
import sys

from PyInstaller.utils.hooks import collect_all

APP_NAME = "SciIm Toolkit"

# Packages whose submodules / data / bundled binaries PyInstaller's built-in hooks
# miss or only partially collect. numpy / scipy core / PySide6 are handled by the
# hooks that ship with PyInstaller; the rest below are collected explicitly so the
# frozen app doesn't crash on import. If a future dependency fails at runtime in a
# frozen build, add its top-level import name to this list and rebuild.
_collect_pkgs = ["pyqtgraph", "skimage", "imageio", "cv2", "scipy"]

datas, binaries, hiddenimports = [], [], []
for _pkg in _collect_pkgs:
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["src/sciim_toolkit/app/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim GUI toolkits we don't use so they can't get pulled in by accident.
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed: colleagues never see a terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
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
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,  # add an .icns here later for a custom dock icon
        bundle_identifier="com.tahpaul.sciim-toolkit",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "0.1.0",
        },
    )
