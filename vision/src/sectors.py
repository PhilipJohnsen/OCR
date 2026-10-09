"""
Read a grid of individually-boxed, un-labeled numbers -- the RNFL quadrant/
clock wheels and GCL macula sector grids.

Each number is OCR'd from its own tight, individually-calibrated box (see
config/GlaucomaHood.py and config/GlaucomaReport.py) rather than the whole
graphic at once -- feeding the full wheel/grid image to tesseract merges the
circle/crosshair lines into a single garbage glyph and drops several numbers
entirely.

Quadrant-wheel box positions are geometric (top/left/right/bottom), not
semantic: Nasal vs Temporal sits on opposite sides depending on eye (L/R
mirror each other), so the S/N/T/I mapping is resolved here from the
already-extracted eye field.
"""
import cv2
import numpy as np

from . import ocr

# Ink cutoff for locating digits on a white background (the RNFL wheel's labels).
_LOCATE_INK = 140
# Extra room searched either side of an anchor box: a 3-digit value is ~7px
# wider than the 2-digit value an anchor may have been fitted to.
_LOCATE_PAD_X = 14
_LOCATE_PAD_Y = 3
# Margin left around the located digits -- the same 3px the anchors were fit with.
_LOCATE_MARGIN = 3
# Largest ink gap between two digits of the same number. A "1" is a narrow
# glyph with wide side bearings: bold GCL "102" has a 4px gap between "1" and
# "0" (a 3px limit split it into "1" + "02" and read "02"). Separate printed
# numbers are never closer than 8px.
_DIGIT_GAP = 5


def locate_number(
    image: np.ndarray, anchor: tuple[int, int, int, int], ink_threshold: int, on_white: bool,
) -> tuple[tuple[int, int, int, int], np.ndarray]:
    """Find the number printed at `anchor`, however many digits it has.

    Anchors are fit (with a 3px margin) to whichever number the reference
    report happened to print there, but the printed value is centered on the
    same point whatever its width -- a 3-digit "123" where the reference had
    a 2-digit "96" spills past both sides of the anchor and gets clipped. So
    this searches a wider window for digit-sized ink blobs (height within 2px
    of the anchor's digit height -- most graphic fragments are shorter; with
    `on_white`, ink touching saturated color is excluded too), groups nearby ones (gaps <= _DIGIT_GAP; separate
    numbers are 8px+ apart) and takes the group under the anchor's center.

    Returns (box around that group plus the margin, crop of that box). In the
    crop, everything except the group's glyphs and a 1px anti-aliasing halo
    around them is painted white -- the margin otherwise takes in corners of
    the RNFL wheel's colored segments or a blood vessel crossing a GCL sector,
    which drags tesseract's confidence down or adds a phantom digit. Falls
    back to the anchor and its raw crop if nothing qualifies.
    """
    x1, y1, x2, y2 = anchor
    digit_h = (y2 - y1) - 2 * _LOCATE_MARGIN
    center_y = (y1 + y2) / 2 - y1 + _LOCATE_PAD_Y
    wx1, wy1 = max(x1 - _LOCATE_PAD_X, 0), max(y1 - _LOCATE_PAD_Y, 0)
    window = ocr.crop(image, (wx1, wy1, x2 + _LOCATE_PAD_X, y2 + _LOCATE_PAD_Y))
    center_x = (x1 + x2) / 2 - wx1
    ink = cv2.cvtColor(window, cv2.COLOR_BGR2GRAY) < ink_threshold
    if on_white:
        # Labels printed on white beside a colored graphic (the RNFL wheel):
        # any ink within 2px of saturated color is the graphic's own rim or
        # segment borders -- 1px strokes that anti-aliasing breaks into
        # digit-height pieces, one of them ~5px from the 3 and 9 o'clock
        # labels -- not a glyph.
        hsv = cv2.cvtColor(window, cv2.COLOR_BGR2HSV)
        colored = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80)).astype(np.uint8)
        ink &= cv2.dilate(colored, np.ones((5, 5), np.uint8)) == 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    glyphs = sorted(
        (x, y, x + w, y + h, i)
        for i, (x, y, w, h, _) in enumerate(stats[:count])
        if i > 0 and abs(h - digit_h) <= 2 and w <= 3 * digit_h and abs(y + h / 2 - center_y) <= 3
    )
    groups: list[list] = []
    for g in glyphs:
        if groups and g[0] - groups[-1][-1][2] <= _DIGIT_GAP:
            groups[-1].append(g)
        else:
            groups.append([g])
    if not groups:
        return anchor, ocr.crop(image, anchor)
    best = min(groups, key=lambda grp: abs((grp[0][0] + max(g[2] for g in grp)) / 2 - center_x))
    keep = cv2.dilate(np.isin(labels, [g[4] for g in best]).astype(np.uint8), np.ones((3, 3), np.uint8))
    cleaned = window.copy()
    cleaned[keep == 0] = 255
    bx1 = min(g[0] for g in best) - _LOCATE_MARGIN
    by1 = min(g[1] for g in best) - _LOCATE_MARGIN
    bx2 = max(g[2] for g in best) + _LOCATE_MARGIN
    by2 = max(g[3] for g in best) + _LOCATE_MARGIN
    box = (bx1 + wx1, by1 + wy1, bx2 + wx1, by2 + wy1)
    return box, ocr.crop(cleaned, (max(bx1, 0), max(by1, 0), bx2, by2))


def read_number_grid(
    image: np.ndarray, boxes: dict, dark_threshold: int | None = None, locate: bool = False,
) -> dict:
    """OCR a tight, un-labeled number out of each box in `boxes`.

    Returns {key: (value, conf, box read)} for whatever keys `boxes` has --
    clock hours, quadrant positions, or macula sector names. `dark_threshold`
    is passed through to ocr.read_number (see
    config/GlaucomaReport.GCL_DARK_THRESHOLD). With `locate`, each box is
    treated as an anchor and the number is found around it first (see
    locate_number) -- the "box read" is the located box.
    """
    out = {}
    for key, box in boxes.items():
        if locate:
            # GCL digits are printed on color (dark_threshold set); wheel labels on white.
            box, roi = locate_number(image, box, dark_threshold or _LOCATE_INK, on_white=dark_threshold is None)
        else:
            roi = ocr.crop(image, box)
        value, conf = ocr.read_number(roi, dark_threshold)
        out[key] = (value, conf, box)
    return out


def read_quadrant_wheel(image: np.ndarray, eye: str, quadrant_boxes: dict) -> dict:
    """Returns {'S': (value, conf, box), 'N': ..., 'T': ..., 'I': ...}."""
    left_label, right_label = ("N", "T") if eye == "L" else ("T", "N")
    position_to_label = {
        "top": "S",
        "bottom": "I",
        "left": left_label,
        "right": right_label,
    }
    raw = read_number_grid(image, quadrant_boxes)
    return {position_to_label[position]: value for position, value in raw.items()}


def read_clock_wheel(image: np.ndarray, clock_boxes: dict, locate: bool = False) -> dict:
    """Returns {clock_hour(1-12): (value, conf, box)}, where 12 = top/Superior,
    clockwise. `locate` -- see read_number_grid."""
    return read_number_grid(image, clock_boxes, locate=locate)
