"""Finds report images anywhere under an arbitrary export tree and tells
GlaucomaHood and GlaucomaReport images apart before the real extraction
pipeline runs.

The tree's shape isn't assumed -- one site might export as
<root>/<month>/<patient>/<report>/*.jpg, another as <root>/<patient>/*.jpg,
folder names vary, and nesting depth varies. So this crawls every folder
under a chosen root looking for image files directly, with no folder-name
filtering, capped at MAX_CRAWL_DEPTH levels below root (a folder tree deeper
than that is almost certainly not what someone meant to point this at).
Classification can't rely on folder name, file name, or image dimensions
either (both layouts export at the same resolution) -- it reads a small crop
of the title, printed at the same position on both layouts, and checks for
wording unique to each ("Created by Prof. Donald Hood" vs "3D Wide(H)
Glaucoma Report").
"""
from pathlib import Path

import cv2

from config import settings
from . import ocr

# root itself is depth 0; a folder MAX_CRAWL_DEPTH levels below root is the
# last one descended into. Any deeper subfolder is left unexplored and its
# parent reported back as truncated, so a caller can warn loudly rather than
# silently return an incomplete result.
MAX_CRAWL_DEPTH = 7

# Crop tight enough to avoid the TOPCON logo (left) and the Ethnicity column
# (right, starts ~x445) bleeding into the OCR'd line -- see config/GlaucomaHood.py
# and config/GlaucomaReport.py, which both place TEXT_FIELDS["ethnicity"] there.
# Calibrated against a report exported at settings.EXPECTED_IMAGE_SIZE --
# _scale_box() below rescales it for any other export resolution (a device
# can print the same report at multiple DPIs/qualities; the title's position
# stays proportional to the page either way).
TITLE_BOX = (160, 40, 440, 82)


def _scale_box(box: tuple[int, int, int, int], image_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    ref_w, ref_h = settings.EXPECTED_IMAGE_SIZE
    h, w = image_shape[:2]
    if (w, h) == (ref_w, ref_h):
        return box
    sx, sy = w / ref_w, h / ref_h
    x1, y1, x2, y2 = box
    return (round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy))


def find_candidate_images(
    root: Path, max_depth: int = MAX_CRAWL_DEPTH, exclude_dirs: tuple[Path, ...] = (),
) -> tuple[list[Path], list[Path]]:
    """Recursively finds every image file anywhere under `root`, regardless of
    folder names or nesting depth, refusing to descend past `max_depth`
    folder levels below `root`.

    `exclude_dirs` are skipped entirely -- the app's own output folder, for
    one: the GUI writes review crops to <output>/review/, and output defaults
    to the input folder, so a later crawl of that folder would otherwise pick
    up dozens of tiny field crops as candidate reports.

    Returns (image_paths, truncated_dirs) -- truncated_dirs are directories at
    the depth limit that still had subfolders left unexplored. A non-empty
    truncated_dirs means the result may be incomplete; callers should surface
    that loudly rather than silently trusting `image_paths` as the full set.
    """
    root = Path(root)
    excluded = {Path(d).resolve() for d in exclude_dirs}
    images: list[Path] = []
    truncated_dirs: list[Path] = []

    def _walk(dir_path: Path, depth: int):
        try:
            entries = list(dir_path.iterdir())
        except OSError:
            return
        subdirs = [e for e in entries if e.is_dir() and e.resolve() not in excluded]
        files = [e for e in entries if e.is_file()]
        images.extend(f for f in files if f.suffix.lower() in settings.INPUT_EXTENSIONS)
        if not subdirs:
            return
        if depth >= max_depth:
            truncated_dirs.append(dir_path)
            return
        for sub in subdirs:
            _walk(sub, depth + 1)

    _walk(root, 0)
    return sorted(images), truncated_dirs


def detect_report_type(image_path: Path) -> str | None:
    """Returns 'GlaucomaHood', 'GlaucomaReport', or None if the title crop
    isn't confidently one or the other (unreadable image, unexpected layout,
    truncated export) -- callers should skip/flag those rather than guess."""
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    # Anything much smaller than a report page (a stray thumbnail, an
    # individual field crop) can't hold the title -- its scaled title crop
    # comes out empty, which OpenCV rejects outright.
    h, w = image.shape[:2]
    ref_w, ref_h = settings.EXPECTED_IMAGE_SIZE
    if w < ref_w / 2 or h < ref_h / 2:
        return None
    box = _scale_box(TITLE_BOX, image.shape)
    roi = ocr.crop(image, box)
    line, _ = ocr.read_line(roi, psm=6)
    line_lower = line.lower()
    if not line_lower.strip():
        return None
    if "hood" in line_lower:
        return "GlaucomaHood"
    if "glaucoma" in line_lower or "wide" in line_lower:
        return "GlaucomaReport"
    return None


def classify_images(
    paths: list[Path], wanted_report_type: str
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Splits `paths` into (matching wanted_report_type, [(path, reason) for the rest]).
    `reason` is either the other report type's name or "undetected"."""
    matched: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for path in paths:
        detected = detect_report_type(path)
        if detected == wanted_report_type:
            matched.append(path)
        else:
            skipped.append((path, detected or "undetected"))
    return matched, skipped
