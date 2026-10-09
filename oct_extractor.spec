# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the OCT Report Extractor GUI. Build with:
    pyinstaller oct_extractor.spec --noconfirm
(see scripts/build_windows.ps1 / scripts/build_unix.sh, which also run the
vendor_tesseract_* step first if needed.)

Why a .spec instead of plain `pyinstaller GUI/gui.py --add-data ...` flags:
the --add-data separator differs between Windows (;) and Unix (:), so a
single CLI invocation can't be copy-pasted across platforms. This file is
plain Python and works identically on every OS you run `pyinstaller` on.

vision/config and vision/src are bundled as *data* (plain .py files copied
into the frozen app), not analyzed as part of the import graph -- gui.py
inserts their parent directory into sys.path at runtime (see BASE_DIR /
sys._MEIPASS handling in GUI/gui.py) and imports them as regular top-level
`config` / `src` packages, exactly like it does when run from source. Because
PyInstaller's static analysis never sees the `import cv2` / `import
pytesseract` / `import pandas` lines buried inside those data-only files,
those three (plus numpy, which they depend on) are listed explicitly in
hiddenimports below -- pandas is only imported by vision/src/output.py, the
shared CSV writer, not by gui.py itself --
without that, the frozen exe launches fine but crashes the moment it tries to
OCR anything.

Built as onedir (COLLECT), not onefile: a onefile build self-extracts
~500-600MB to a fresh %TEMP% folder on *every* launch (cleaned up on a
graceful exit, left behind on a crash/force-kill), which can fill a
low-disk-space machine. Onedir extracts once at build time instead, at the
cost of distributing a folder instead of a single file -- zip it for
handoff (see PACKAGING.md).
"""
import platform
from pathlib import Path

REPO_ROOT = Path(SPECPATH)  # noqa: F821 -- SPECPATH is injected by PyInstaller

PLATFORM_DIRS = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}
PLATFORM_DIR = PLATFORM_DIRS[platform.system()]
IS_WINDOWS = platform.system() == "Windows"

datas = [
    (str(REPO_ROOT / "vision" / "config"), "vision/config"),
    (str(REPO_ROOT / "vision" / "src"), "vision/src"),
]

vendor_dir = REPO_ROOT / "vendor" / "tesseract" / PLATFORM_DIR
if vendor_dir.is_dir():
    datas.append((str(vendor_dir), f"vendor/tesseract/{PLATFORM_DIR}"))
else:
    print(
        f"WARNING: {vendor_dir} not found -- building without a bundled Tesseract. "
        f"Run scripts/vendor_tesseract_{'windows.ps1' if PLATFORM_DIR == 'windows' else 'unix.sh'} first "
        "if you want the packaged app to work without Tesseract installed separately."
    )

a = Analysis(
    [str(REPO_ROOT / "GUI" / "gui.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["cv2", "numpy", "pandas", "pytesseract", "PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# icon= requires a Windows .ico; version= (a Windows version-resource file) is
# a Windows-only PyInstaller feature. Both are no-ops/omitted on other OSes.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCTReportExtractor",
    console=False,
    icon=str(REPO_ROOT / "GUI" / "assets" / "app.ico") if IS_WINDOWS else None,
    version=str(REPO_ROOT / "scripts" / "version_info.txt") if IS_WINDOWS else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="OCTReportExtractor",
)
