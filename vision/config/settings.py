"""Pipeline-wide settings: paths, thresholds, and the expected report geometry."""
import os
import platform
import shutil
import sys
from pathlib import Path

# ROI coordinates in config/GlaucomaHood.py and config/GlaucomaReport.py were
# calibrated against reports exported at this exact resolution. Any input image
# that doesn't match gets flagged instead of silently mis-cropped.
EXPECTED_IMAGE_SIZE = (1286, 909)  # (width, height)

INPUT_DIR = "reference"
OUTPUT_CSV = "output/extracted_data.csv"
REVIEW_DIR = "output/review"

INPUT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


# --- Tesseract binary location -------------------------------------------------
def _repo_root() -> Path:
    """Root that both the dev tree and a frozen PyInstaller build share --
    `vendor/tesseract/<platform>/` hangs off this in both cases. PyInstaller sets
    sys._MEIPASS to the bundle's extraction root (onefile) / dist folder (onedir)
    for any frozen build, which is where --add-data "vendor:vendor" lands it."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


_PLATFORM_DIRS = {"windows": "windows", "linux": "linux", "darwin": "macos"}
_VENDOR_DIR = _repo_root() / "vendor" / "tesseract" / _PLATFORM_DIRS.get(platform.system().lower(), "")
_VENDOR_BIN = _VENDOR_DIR / ("tesseract.exe" if platform.system() == "Windows" else "tesseract")


def _resolve_tesseract_cmd() -> str:
    """Prefer the binary bundled by scripts/vendor_tesseract_*; that's what makes
    a packaged build work without the user installing Tesseract themselves. Falls
    back to whatever Tesseract a dev machine already has, for running from source."""
    if _VENDOR_BIN.exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(_VENDOR_DIR / "tessdata"))
        # The vendored .so/.dylib files sit next to the binary rather than in a
        # system loader path (they weren't re-linked with a new rpath, just
        # copied) -- point the dynamic linker at them. No-op on Windows, where
        # the OS loader already looks next to the .exe for its DLLs.
        system = platform.system()
        if system == "Linux":
            existing = os.environ.get("LD_LIBRARY_PATH", "")
            os.environ["LD_LIBRARY_PATH"] = f"{_VENDOR_DIR}{os.pathsep}{existing}" if existing else str(_VENDOR_DIR)
        elif system == "Darwin":
            existing = os.environ.get("DYLD_LIBRARY_PATH", "")
            os.environ["DYLD_LIBRARY_PATH"] = f"{_VENDOR_DIR}{os.pathsep}{existing}" if existing else str(_VENDOR_DIR)
        return str(_VENDOR_BIN)
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ):
        if Path(candidate).exists():
            return candidate
    return "tesseract"  # not found anywhere -- let pytesseract raise its own clear error


TESSERACT_CMD = _resolve_tesseract_cmd()

# --- Confidence thresholds ------------------------------------------------------
# Tesseract per-token confidences are on a 0-100 scale.
FIELD_CONFIDENCE_THRESHOLD = 90      # below this, a single field is untrustworthy
ROW_CONFIDENCE_THRESHOLD = 80        # below this average, the whole row needs review
IMAGE_QUALITY_LOW_THRESHOLD = 40     # Topcon's own scan-quality score; below is a poor scan

# OCR upscale factor applied to every ROI crop before recognition. Tesseract is
# much more reliable on small print when the crop is enlarged first. Swept 2-6x
# against the reference reports; 4x edged out 3x on
# both text and RNFL-wheel digit confidence, 5x+ started hurting.
OCR_UPSCALE = 4
