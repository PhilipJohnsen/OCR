"""Per-field extraction: crop -> OCR -> regex parse -> validate -> confidence."""
import re
from dataclasses import dataclass
from datetime import date

import cv2
import numpy as np

from . import ocr


@dataclass
class FieldResult:
    value: str
    confidence: float  # 0-100
    valid: bool


def _confidence_for_span(words: list[tuple[str, float]], span: tuple[int, int]) -> float:
    """Mean confidence of only the word tokens overlapping `span` in the joined line.

    Falls back to the full-line average when nothing overlaps (e.g. an empty
    match). Scoring the matched value instead of the whole line keeps a garbled
    label -- "Aaqe:" for "Age:" -- from dragging down a value that actually read
    cleanly.
    """
    start, end = span
    if start == end:
        return sum(c for _, c in words) / len(words) if words else 0.0
    matched, offset = [], 0
    for word, conf in words:
        w_start, w_end = offset, offset + len(word)
        if w_start < end and w_end > start:
            matched.append(conf)
        offset = w_end + 1  # +1 for the joining space
    if not matched:
        return sum(c for _, c in words) / len(words) if words else 0.0
    return sum(matched) / len(matched)


def extract_labeled_field(
    image: np.ndarray, box: tuple[int, int, int, int], pattern: str, group: int = 1
) -> FieldResult:
    """OCR a 'Label: value' line and pull out the value with `pattern`.

    Confidence is scored from only the token(s) making up the matched value, not
    the whole line -- an unrelated label elsewhere in the crop shouldn't be able
    to drag down a value that read perfectly cleanly.

    A label that OCR'd cleanly but has no trailing value (e.g. an intentionally
    blank "Ethnicity:") is treated as a valid empty field, not a failure.
    """
    roi = ocr.crop(image, box)
    words = ocr.read_line_words(roi)
    line = " ".join(w for w, _ in words)
    m = re.search(pattern, line, re.IGNORECASE)
    if not m:
        # Label itself missing/unreadable entirely.
        fallback_conf = sum(c for _, c in words) / len(words) if words else 0.0
        return FieldResult(value="", confidence=fallback_conf, valid=False)
    value = m.group(group).strip()
    conf = _confidence_for_span(words, m.span(group))
    return FieldResult(value=value, confidence=conf, valid=True)


# Glyph ink for date segmentation: darker than this gray level.
_DATE_INK = 140
# Largest ink gap between two glyphs of one number -- a "1"'s wide side
# bearings leave up to ~4px (see src/sectors._DIGIT_GAP).
_DIGIT_GAP = 5


def _locate_date_parts(roi: np.ndarray) -> tuple[dict | None, np.ndarray]:
    """Find the day / month / year digit groups of a DD/MM/YYYY date inside a
    single-line ROI ("DOB: 20/03/1986   Age: 38", "Capture Date:19/03/2025").

    The date's x position isn't fixed -- it depends on the label and the
    renderer's spacing, which differs between exports -- so instead of fixed
    boxes: tesseract's character boxes identify which ink blobs are the two
    "/" glyphs; every digit-height blob is a digit; the groups are the digit
    run just left of the first slash, the digits between the slashes, and
    the run just right of the second.

    Returns ({"day"/"month"/"year": box in ROI coords}, cleaned ROI) or
    (None, roi). The cleaned ROI has every non-digit blob (slashes, the
    label's colon, ...) plus a 1px halo painted white: even a sliver of slash
    inside a digit crop drops tesseract's confidence to 0.
    """
    ink = (cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) < _DATE_INK).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    blobs = {i: tuple(stats[i][:4]) for i in range(1, count)}  # id -> (x, y, w, h)
    tall = {i: b for i, b in blobs.items() if b[3] >= 7}
    if not tall:
        return None, roi
    digit_h = float(np.median([b[3] for b in tall.values()]))

    slash_ids = set()
    for char, x1, _, x2, _ in ocr.char_boxes(roi):
        if char != "/":
            continue
        for i, (bx, _, bw, _) in tall.items():
            if x1 - 1 <= bx + bw / 2 <= x2 + 1:
                slash_ids.add(i)
                break
    # The date's two slashes: the first adjacent pair with a 1-2 digit gap.
    centers = sorted((blobs[i][0] + blobs[i][2] / 2, i) for i in slash_ids)
    pair = next(((a, b) for a, b in zip(centers, centers[1:]) if 8 <= b[0] - a[0] <= 30), None)
    if pair is None:
        return None, roi
    (s1x, s1), (s2x, s2) = pair

    digit_ids = [i for i, b in blobs.items() if i not in (s1, s2) and abs(b[3] - digit_h) <= 2]
    digit_mask = np.isin(labels, digit_ids)
    halo = cv2.dilate(((labels > 0) & ~digit_mask).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    cleaned = roi.copy()
    cleaned[halo & ~digit_mask] = 255

    digits = [(blobs[i][0], blobs[i][0] + blobs[i][2]) for i in digit_ids]  # (x1, x2)

    def run_from(candidates):
        # Walk away from a slash, collecting glyphs while gaps stay small.
        run = []
        for d in candidates:
            if run and max(d[0] - run[-1][1], run[-1][0] - d[1]) > _DIGIT_GAP:
                break
            run.append(d)
        return run

    groups = {
        "day": run_from(sorted((d for d in digits if d[1] <= s1x), key=lambda d: -d[1])),
        "month": [d for d in digits if s1x < (d[0] + d[1]) / 2 < s2x],
        "year": run_from(sorted((d for d in digits if d[0] >= s2x), key=lambda d: d[0])),
    }
    if not all(groups.values()):
        return None, roi
    height = roi.shape[0]
    boxes = {k: (min(d[0] for d in g) - 2, 0, max(d[1] for d in g) + 2, height) for k, g in groups.items()}
    return boxes, cleaned


def extract_date(image: np.ndarray, line_box: tuple[int, int, int, int]) -> tuple[FieldResult, date | None]:
    """Read a DD/MM/YYYY date from the line in `line_box` as three separate
    digit-only OCR reads -- day, month, year, located by _locate_date_parts()
    -- and recomposite them.

    Returns (field, parsed date). The field's value is "DD/MM/YYYY" when all
    three parts read as a real calendar date, else whatever parts did read
    joined by "/" (so a reviewer sees what OCR got) with valid=False and a
    parsed date of None. Confidence is the lowest of the three parts -- one bad
    part makes the whole date wrong.
    """
    parts, cleaned = _locate_date_parts(ocr.crop(image, line_box))
    if parts is None:
        return FieldResult(value="", confidence=0.0, valid=False), None
    reads = {key: ocr.read_number(ocr.crop(cleaned, box)) for key, box in parts.items()}
    day, month, year = (reads[k][0] for k in ("day", "month", "year"))
    conf = min(c for _, c in reads.values())
    value = f"{day}/{month}/{year}"
    if not (len(day) == 2 and len(month) == 2 and len(year) == 4):
        return FieldResult(value=value, confidence=conf, valid=False), None
    parsed = parse_date(value)
    return FieldResult(value=value, confidence=conf, valid=parsed is not None), parsed


DATE_TEXT_RE = re.compile(r"^\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})\s*$")


def parse_date(text: str) -> date | None:
    """Parse a hand-typed D/M/YYYY date (any of / . - as separator, day/month
    with or without a leading zero), or None if it isn't a real calendar date.
    Pair with format_date() to normalize a human-review entry to DD/MM/YYYY."""
    m = DATE_TEXT_RE.match(str(text))
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_date(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year:04d}"


def age_on(dob: date, on: date) -> int:
    """Whole years between `dob` and `on` -- the age a report prints for its capture date."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def extract_panel_value(image: np.ndarray, row_box: tuple[int, int, int, int], decimal: bool) -> FieldResult:
    """Read the right-aligned number on a "Label   value" panel row (Average
    thickness RNFL / Disc Topography).

    Only the value is OCR'd: the rightmost run of ink blobs in the row (gaps
    <= _DIGIT_GAP, so a decimal point between digits stays in), cropped with every
    other blob painted white. Reading the whole row instead let the label's
    text sway the read ("0.81" came back "0.31") and its confidence.

    A row with no ink at all is a panel the report didn't print (some exports
    leave Disc Topography empty) -- that's a valid blank, not a failed read.
    The page is already verified aligned by then (src/align.py), so a blank
    row can't be a mis-crop.
    """
    roi = ocr.crop(image, row_box)
    ink = (cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) < _DATE_INK).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    blobs = sorted(((x, y, x + w, y + h, i) for i, (x, y, w, h, _) in enumerate(stats[:count]) if i > 0), key=lambda b: -b[2])
    if not blobs:
        return FieldResult(value="", confidence=100.0, valid=True)
    run = [blobs[0]]
    for b in blobs[1:]:
        if min(r[0] for r in run) - b[2] > _DIGIT_GAP:
            break
        run.append(b)
    keep = cv2.dilate(np.isin(labels, [b[4] for b in run]).astype(np.uint8), np.ones((3, 3), np.uint8))
    cleaned = roi.copy()
    cleaned[keep == 0] = 255
    x1 = max(min(b[0] for b in run) - 3, 0)
    y1 = max(min(b[1] for b in run) - 3, 0)
    x2 = max(b[2] for b in run) + 3
    y2 = max(b[3] for b in run) + 3
    value, conf = ocr.read_number(cleaned[y1:y2, x1:x2], decimal=decimal)
    pattern = r"\d+\.\d+" if decimal else r"\d{1,3}"
    return FieldResult(value=value, confidence=conf, valid=re.fullmatch(pattern, value) is not None)


def extract_eye_laterality(image: np.ndarray, box: tuple[int, int, int, int]) -> FieldResult:
    roi = ocr.crop(image, box)
    line, conf = ocr.read_line(roi, psm=7)
    m = re.search(r"\(([LR])\)", line)
    if m:
        return FieldResult(value=m.group(1), confidence=conf, valid=True)
    if "OS" in line.upper():
        return FieldResult(value="L", confidence=conf * 0.7, valid=True)
    if "OD" in line.upper():
        return FieldResult(value="R", confidence=conf * 0.7, valid=True)
    return FieldResult(value="", confidence=conf, valid=False)


def extract_image_quality(
    image: np.ndarray, box: tuple[int, int, int, int]
) -> tuple[FieldResult, str]:
    """Returns (score field, color band). Score is inset from the box to skip the border."""
    x1, y1, x2, y2 = box
    inset = 4
    inner = (x1 + inset, y1 + inset, x2 - inset, y2 - inset)
    roi = ocr.crop(image, inner)
    line, conf = ocr.read_line(roi, psm=7)
    m = re.search(r"(\d{1,3})", line)
    if m and 0 <= int(m.group(1)) <= 100:
        result = FieldResult(value=m.group(1), confidence=conf, valid=True)
    else:
        result = FieldResult(value="", confidence=conf, valid=False)

    border_roi = ocr.crop(image, box)
    band = _classify_quality_band(border_roi)
    return result, band


def _classify_quality_band(roi_bgr: np.ndarray) -> str:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    ranges = {
        "green": ((35, 60, 40), (85, 255, 255)),
        "yellow": ((20, 60, 40), (34, 255, 255)),
        "red": ((0, 60, 40), (10, 255, 255)),
    }
    best_band, best_count = "unknown", 0
    for band, (lo, hi) in ranges.items():
        count = int(cv2.countNonZero(cv2.inRange(hsv, np.array(lo), np.array(hi))))
        if count > best_count:
            best_band, best_count = band, count
    return best_band if best_count >= 20 else "unknown"
