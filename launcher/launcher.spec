# PyInstaller spec for tracker.exe (the GUI launcher).
#
# Build (from repo root, on Windows):
#   pip install pyinstaller psutil
#   pyinstaller launcher\launcher.spec --noconfirm --clean
#
# Output: launcher\dist\tracker.exe (single-file, ~30 MB).
#
# CI (release.yml) runs this on windows-latest. The exe is NEVER committed
# to the repo — only the .py source is.

# ruff: noqa
# mypy: ignore-errors

import sys
from pathlib import Path

block_cipher = None

# When PyInstaller invokes this spec, __file__ is not defined; resolve via sys.argv.
SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821 - injected by PyInstaller
REPO_ROOT = SPEC_DIR.parent

ICON = REPO_ROOT / "service" / "native" / "resources" / "tracker.ico"
MANIFEST = SPEC_DIR / "tracker.exe.manifest"

a = Analysis(
    [str(SPEC_DIR / "tracker_launcher.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        # psutil ships C extensions for Windows process info; PyInstaller
        # picks them up automatically when psutil is importable, but list
        # the platform-specific module explicitly to be safe.
        "psutil._pswindows",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "numpy",
        "PIL",
        "pytest",
        "tornado",
    ],
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
    name="tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,           # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    manifest=str(MANIFEST) if MANIFEST.exists() else None,
    uac_admin=True,           # bake requestedExecutionLevel=requireAdministrator into manifest
    uac_uiaccess=False,
    version=None,
)
