"""Orchestrates ROI extraction for one report image into a flat CSV-ready row.

Supports multiple Topcon report layouts (config/GlaucomaHood.py,
config/GlaucomaReport.py, ...) selected via the `report_type` argument. Both
currently share the same human-readable column-naming convention --
"<Display Name>" / "<Display Name> confidence", a single `avg_confidence`
rollup, and Nasal/Temporal eye-mirrored labels via _hood_clock_label() /
_gcl_sector_label() -- but each report type has its own header/body
extractor since the underlying fields printed on the two layouts differ.
"""
import re
import shutil
from pathlib import Path
from typing import Any

import cv2

from config import GlaucomaHood, GlaucomaReport, settings
from . import align, fields, sectors

REPORT_CONFIGS = {
    "GlaucomaHood": GlaucomaHood,
    "GlaucomaReport": GlaucomaReport,
}

FILENAME_RE = re.compile(
    r"^(?P<patient_id>\d{6}-\d{4})_(?P<date>\d{8})_(?P<time>\d{6})"
    r"_OCTReport_(?P<eye>[LR])_(?P<seq>\d+)"
)

# (min, max) plausibility ranges for fields where "OCR succeeded but produced
# nonsense" needs to be caught (e.g. misread digits giving RNFL thickness of 900um).
NUMERIC_RANGES = {
    "image_quality": (0, 100),
    "age": (0, 120),
    "rnfl": (0, 350),  # applies to every quadrant/clock-hour/GCL sector thickness value, in um
}

# A name never ends in punctuation, but a stray mark just after the last glyph
# (Glaucoma Report 1 philip.tif has a 2px dot after "Jo") OCRs as ":" or "." --
# match lazily and drop any trailing run of those.
NAME_PATTERN = r"Name:?\s*(.*?)[\s.:;,'`]*$"

# DOB and Age are OCR'd as two separate tokens out of the same "DOB: .../ Age:
# .." crop -- tesseract scores digit-only "15" much higher than a slash-
# separated date like "2008/07/03" even when both read correctly, so DOB sits
# well below the general FIELD_CONFIDENCE_THRESHOLD on essentially every
# report, for both report types (they share this header layout). A
# dedicated, lower bar for this one field avoids flagging that as
# review-worthy while still catching an actually bad read.
DOB_CONFIDENCE_THRESHOLD = 70

# 12-clock-hour RNFL labels, for a LEFT eye report (Nasal on the left of the
# wheel, at 9 o'clock). 12 = top/Superior, clockwise. For a RIGHT eye report,
# Nasal and Temporal sit on opposite sides of the wheel -- _hood_clock_label()
# below swaps those two words rather than re-deriving a second table, since
# the clock-hour position itself doesn't move, only which side of the eye it
# corresponds to. Originally GlaucomaHood-specific, now also used by
# GlaucomaReport's RNFL clock wheel (same naming scheme, per request).
HOOD_CLOCK_LABELS_L = {
    12: "RNFL Superior Superior",
    1: "RNFL Superior Temporal",
    2: "RNFL Temporal Top",
    3: "RNFL Temporal Temporal",
    4: "RNFL Temporal Bottom",
    5: "RNFL Inferior Temporal",
    6: "RNFL Inferior Inferior",
    7: "RNFL Inferior Nasal",
    8: "RNFL Nasal Bottom",
    9: "RNFL Nasal Nasal",
    10: "RNFL Nasal Top",
    11: "RNFL Superior Nasal",
}

HOOD_QUADRANT_LABELS = {"S": "RNFL Superior", "T": "RNFL Temporal", "N": "RNFL Nasal", "I": "RNFL Inferior"}


def _hood_clock_label(hour: int, eye: str) -> str:
    base = HOOD_CLOCK_LABELS_L[hour]
    if eye == "L":
        return base
    # Right eye: Nasal and Temporal swap sides. Three-step swap avoids one
    # word's replacement being re-matched by the other's.
    return base.replace("Temporal", "\0").replace("Nasal", "Temporal").replace("\0", "Nasal")


# GlaucomaReport's GCL++/GCL+ macula 6-sector grids, for a LEFT eye report
# (Nasal on the left, same convention as the RNFL wheel above). The grid's
# four diagonal sectors are named by which side (Nasal/Temporal) they're on
# and whether they're the upper or lower one on that side; top/bottom are
# always Superior/Inferior regardless of eye.
GLAUCOMA_REPORT_GCL_LABELS_L = {
    "top": "Superior",
    "upper_left": "NasalTop",
    "upper_right": "TemporalTop",
    "lower_left": "NasalBottom",
    "lower_right": "TemporalBottom",
    "bottom": "Inferior",
}


def _gcl_sector_label(prefix: str, position: str, eye: str) -> str:
    suffix = GLAUCOMA_REPORT_GCL_LABELS_L[position]
    if eye != "L":
        suffix = suffix.replace("Temporal", "\0").replace("Nasal", "Temporal").replace("\0", "Nasal")
    return f"{prefix} {suffix}"


class LayoutMismatch(Exception):
    pass


def _write_named_field(
    row, field_confidences, low_confidence_rois, reasons, display_name: str,
    result: fields.FieldResult, box, numeric_range=None, confidence_threshold=None, review_as=None,
) -> bool:
    """Writes value + confidence under human-readable column names --
    "<Display Name>" / "<Display Name> confidence" -- and registers the ROI
    for review-crop saving when the field is invalid or low-confidence.
    "/" is swapped for "-" in the saved crop's filename only (e.g. "R/L eye"
    -> "R-L eye.png", "C/D Area Ratio" -> "C-D Area Ratio.png") since "/" is
    a path separator, not a valid filename character -- the CSV column
    itself keeps the real display_name.

    confidence_threshold overrides settings.FIELD_CONFIDENCE_THRESHOLD for
    fields (like DOB) whose realistic OCR confidence ceiling sits below the
    general bar even when read correctly.

    review_as saves the review crop under another column's name instead --
    for a derived field (GlaucomaReport's Age) whose fix is made in the field
    it came from (DOB), not in the derived value itself."""
    if confidence_threshold is None:
        confidence_threshold = settings.FIELD_CONFIDENCE_THRESHOLD
    row[display_name] = result.value
    row[f"{display_name} confidence"] = round(result.confidence, 1)
    valid = result.valid
    if valid and numeric_range and result.value != "":
        try:
            valid = numeric_range[0] <= float(result.value) <= numeric_range[1]
        except ValueError:
            valid = False
    field_confidences.append(result.confidence)
    if not valid or result.confidence < confidence_threshold:
        low_confidence_rois.append(((review_as or display_name).replace("/", "-"), box))
        reasons.append(f"{display_name}_low_confidence")
    return valid


def extract_report(image_path: Path, report_type: str = "GlaucomaHood") -> dict[str, Any]:
    if report_type not in REPORT_CONFIGS:
        raise ValueError(f"Unknown report_type {report_type!r}; expected one of {sorted(REPORT_CONFIGS)}")
    config = REPORT_CONFIGS[report_type]
    is_hood = report_type == "GlaucomaHood"

    row: dict[str, Any] = {"source_file": image_path.name, "report_type": report_type}
    low_confidence_rois: list[tuple[str, tuple[int, int, int, int]]] = []
    reasons: list[str] = []

    # Wipe any review crops left over from a previous run of this same file --
    # otherwise a field that used to be flagged but now reads fine leaves a
    # stale, misleading crop behind (review dir isn't touched at all when a
    # row no longer needs review).
    shutil.rmtree(Path(settings.REVIEW_DIR) / image_path.stem, ignore_errors=True)

    image = cv2.imread(str(image_path))
    if image is None:
        row["layout_error"] = "image could not be read"
        row["needs_human_review"] = True
        return row

    # Every report type's boxes are calibrated for one exact export
    # resolution -- a config can declare its own EXPECTED_IMAGE_SIZE (see
    # config/GlaucomaReport.py) when it differs from the shared default
    # (settings.EXPECTED_IMAGE_SIZE, which GlaucomaHood uses). A config with
    # PAGE_LANDMARKS gets its image shifted onto the reference page first
    # (src/align.py), so a few pixels of extra margin or offset -- e.g. a
    # hand-cropped screenshot -- still reads. Otherwise (or if alignment
    # fails) don't silently crop garbage out of a differently-shaped report:
    # flag it, with the reason in layout_error.
    expected_size = getattr(config, "EXPECTED_IMAGE_SIZE", settings.EXPECTED_IMAGE_SIZE)
    landmarks = getattr(config, "PAGE_LANDMARKS", None)
    if landmarks:
        image, align_error = align.align_to_reference(image, landmarks, expected_size)
        if image is None:
            row["layout_error"] = align_error
            row["needs_human_review"] = True
            return row
    else:
        h, w = image.shape[:2]
        if (w, h) != expected_size:
            row["layout_error"] = f"image is {w}x{h}, expected {expected_size[0]}x{expected_size[1]}"
            row["needs_human_review"] = True
            return row

    field_confidences: list[float] = []

    if is_hood:
        eye_for_mapping = _extract_hood_header(image, config, row, field_confidences, low_confidence_rois, reasons)
        _extract_hood_body(image, config, eye_for_mapping, row, field_confidences, low_confidence_rois, reasons)
    else:
        eye_for_mapping = _extract_glaucoma_report_header(
            image, config, row, field_confidences, low_confidence_rois, reasons
        )
        _extract_glaucoma_report_body(
            image, config, eye_for_mapping, row, field_confidences, low_confidence_rois, reasons
        )

    # --- cross-check against the filename, when it follows the known pattern --
    m = FILENAME_RE.match(image_path.stem)
    if m:
        row["filename_patient_id_match"] = m.group("patient_id") == row.get("ID")
        row["filename_eye_match"] = m.group("eye") == row.get("R/L eye")
        if not row["filename_patient_id_match"]:
            reasons.append("patient_id_filename_mismatch")
        if not row["filename_eye_match"]:
            reasons.append("eye_filename_mismatch")
    else:
        row["filename_patient_id_match"] = None
        row["filename_eye_match"] = None

    # --- roll up overall confidence + review flag ------------------------------
    overall_confidence = sum(field_confidences) / len(field_confidences) if field_confidences else 0.0
    row["avg_confidence"] = round(overall_confidence, 1)
    needs_review = bool(reasons) or overall_confidence < settings.ROW_CONFIDENCE_THRESHOLD
    row["needs_human_review"] = needs_review

    if needs_review:
        _save_review_crops(image, image_path.stem, low_confidence_rois)

    return row


def _extract_hood_header(image, config, row, field_confidences, low_confidence_rois, reasons) -> str:
    """GlaucomaHood's header fields, under the human-readable column names
    requested for this report type: ID, Name, Gender, DOB, Age, Fixation
    type, Scan type, R/L eye, Image Quality. Ethnicity/Technician/Capture
    Date aren't extracted at all for this report type. Returns the eye value
    ('L'/'R'), defaulting to 'L' when unreadable, so callers can resolve N/T
    sides."""
    text_fields = {
        "ID": (config.TEXT_FIELDS["patient_id"], r"ID:?\s*([\w-]+)"),
        "Name": (config.TEXT_FIELDS["name"], NAME_PATTERN),
        "Gender": (config.TEXT_FIELDS["gender"], r"Gender:?\s*(\w*)"),
        "Fixation type": (config.TEXT_FIELDS["fixation"], r"Fixation:?\s*(.*)"),
        "Scan type": (config.TEXT_FIELDS["scan_info"], r"Scan:?\s*(.*)"),
    }
    for display_name, (box, pattern) in text_fields.items():
        result = fields.extract_labeled_field(image, box, pattern)
        _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)

    dob_age_box = config.TEXT_FIELDS["dob_age"]
    dob_result = fields.extract_labeled_field(image, dob_age_box, r"DOB:?\s*(\d{4}/\d{2}/\d{2})")
    _write_named_field(
        row, field_confidences, low_confidence_rois, reasons, "DOB", dob_result, dob_age_box,
        confidence_threshold=DOB_CONFIDENCE_THRESHOLD,
    )
    # Match the trailing number rather than anchoring on the "Age" label text --
    # OCR sometimes mangles that label (e.g. "Aaqe") while the digits stay clean.
    age_result = fields.extract_labeled_field(image, dob_age_box, r"(\d{1,3})\s*$")
    _write_named_field(
        row, field_confidences, low_confidence_rois, reasons, "Age", age_result, dob_age_box,
        numeric_range=NUMERIC_RANGES["age"],
    )

    # --- eye laterality ------------------------------------------------------
    eye_result = fields.extract_eye_laterality(image, config.EYE_BOX)
    _write_named_field(row, field_confidences, low_confidence_rois, reasons, "R/L eye", eye_result, config.EYE_BOX)

    # --- image quality ---------------------------------------------------------
    quality_result, quality_band = fields.extract_image_quality(image, config.IMAGE_QUALITY_BOX)
    quality_valid = _write_named_field(
        row, field_confidences, low_confidence_rois, reasons, "Image Quality", quality_result,
        config.IMAGE_QUALITY_BOX, numeric_range=NUMERIC_RANGES["image_quality"],
    )
    row["image_quality_band"] = quality_band
    is_low_scan_quality = quality_valid and float(quality_result.value) < settings.IMAGE_QUALITY_LOW_THRESHOLD
    row["low_scan_quality"] = is_low_scan_quality
    if is_low_scan_quality:
        reasons.append("low_scan_quality")

    return eye_result.value if eye_result.value in ("L", "R") else "L"


def _extract_hood_body(image, config, eye_for_mapping, row, field_confidences, low_confidence_rois, reasons):
    """RNFL 4-slice quadrant wheel and 12-slice clock wheel, under the
    human-readable names requested for GlaucomaHood. Both follow the eye's
    Nasal/Temporal mirroring -- Superior and Inferior never move."""
    lo, hi = NUMERIC_RANGES["rnfl"]

    quad = sectors.read_quadrant_wheel(image, eye_for_mapping, config.RNFL_QUADRANT_LABEL_BOXES)
    position_by_label = {"S": "top", "I": "bottom"}
    position_by_label["N"], position_by_label["T"] = ("left", "right") if eye_for_mapping == "L" else ("right", "left")
    for label in ("S", "T", "N", "I"):
        display_name = HOOD_QUADRANT_LABELS[label]
        value, conf, box = quad[label]
        result = fields.FieldResult(value=value, confidence=conf, valid=value != "" and lo <= float(value) <= hi)
        _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)

    clock = sectors.read_clock_wheel(image, config.RNFL_CLOCK_LABEL_BOXES)
    for hour in (12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
        display_name = _hood_clock_label(hour, eye_for_mapping)
        value, conf, box = clock[hour]
        result = fields.FieldResult(value=value, confidence=conf, valid=value != "" and lo <= float(value) <= hi)
        _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)


def _extract_glaucoma_report_header(image, config, row, field_confidences, low_confidence_rois, reasons) -> str:
    """GlaucomaReport's header fields: ID, Name, Gender, DOB, Age, Fixation,
    Scantype, R/L eye, Image quality, Capture Date. Ethnicity/Technician
    aren't extracted at all for this report type. Age is computed from DOB and
    Capture Date rather than OCR'd. Returns the eye value
    ('L'/'R'), defaulting to 'L' when unreadable, so callers can resolve N/T
    sides."""
    text_fields = {
        "ID": (config.TEXT_FIELDS["patient_id"], r"ID:?\s*([\w-]+)"),
        "Name": (config.TEXT_FIELDS["name"], NAME_PATTERN),
        "Gender": (config.TEXT_FIELDS["gender"], r"Gender:?\s*(\w*)"),
        "Fixation": (config.TEXT_FIELDS["fixation"], r"Fixation:?\s*(.*)"),
        "Scantype": (config.TEXT_FIELDS["scan_info"], r"Scan:?\s*(.*)"),
    }
    for display_name, (box, pattern) in text_fields.items():
        result = fields.extract_labeled_field(image, box, pattern)
        _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)

    # Dates are read day/month/year as separate digit-only crops (see
    # config/GlaucomaReport.py), so they score like any other number -- no
    # DOB_CONFIDENCE_THRESHOLD special case needed here, unlike GlaucomaHood's
    # whole-line DOB read.
    capture_box = config.CAPTURE_DATE_LINE
    capture_result, capture_date = fields.extract_date(image, capture_box)
    _write_named_field(
        row, field_confidences, low_confidence_rois, reasons, "Capture Date", capture_result, capture_box,
    )
    dob_box = config.DOB_LINE
    dob_result, dob = fields.extract_date(image, dob_box)
    _write_named_field(row, field_confidences, low_confidence_rois, reasons, "DOB", dob_result, dob_box)

    # Age is derived, not OCR'd: age on the capture date, which is what the
    # report prints. Only as trustworthy as the two dates it came from. A bad
    # Age is reviewed via the DOB crop -- the GUI re-derives Age whenever a
    # reviewer corrects DOB or Capture Date (see GUI/gui.py).
    if dob and capture_date:
        age_result = fields.FieldResult(
            value=str(fields.age_on(dob, capture_date)),
            confidence=min(dob_result.confidence, capture_result.confidence),
            valid=True,
        )
    else:
        age_result = fields.FieldResult(value="", confidence=0.0, valid=False)
    _write_named_field(
        row, field_confidences, low_confidence_rois, reasons, "Age", age_result, dob_box,
        numeric_range=NUMERIC_RANGES["age"], review_as="DOB",
    )

    # --- eye laterality ------------------------------------------------------
    eye_result = fields.extract_eye_laterality(image, config.EYE_BOX)
    _write_named_field(row, field_confidences, low_confidence_rois, reasons, "R/L eye", eye_result, config.EYE_BOX)

    # --- image quality ---------------------------------------------------------
    quality_result, quality_band = fields.extract_image_quality(image, config.IMAGE_QUALITY_BOX)
    quality_valid = _write_named_field(
        row, field_confidences, low_confidence_rois, reasons, "Image quality", quality_result,
        config.IMAGE_QUALITY_BOX, numeric_range=NUMERIC_RANGES["image_quality"],
    )
    row["image_quality_band"] = quality_band
    is_low_scan_quality = quality_valid and float(quality_result.value) < settings.IMAGE_QUALITY_LOW_THRESHOLD
    row["low_scan_quality"] = is_low_scan_quality
    if is_low_scan_quality:
        reasons.append("low_scan_quality")

    return eye_result.value if eye_result.value in ("L", "R") else "L"


def _extract_glaucoma_report_body(image, config, eye_for_mapping, row, field_confidences, low_confidence_rois, reasons):
    """RNFL 12-slice clock wheel (same naming/eye-mirroring scheme as
    GlaucomaHood), GCL++/GCL+ macula 6-sector grids (mirrored the same way),
    average RNFL thickness, and disc topography panel."""
    lo, hi = NUMERIC_RANGES["rnfl"]

    # Wheel and GCL boxes are anchors, re-fit to each printed number's actual
    # width (2 or 3 digits) before reading -- see sectors.locate_number.
    clock = sectors.read_clock_wheel(image, config.RNFL_CLOCK_LABEL_BOXES, locate=True)
    for hour in (12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
        display_name = _hood_clock_label(hour, eye_for_mapping)
        value, conf, box = clock[hour]
        result = fields.FieldResult(value=value, confidence=conf, valid=value != "" and lo <= float(value) <= hi)
        _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)

    for prefix, boxes in (("GCL++", config.GCL_PLUS_PLUS_SECTOR_BOXES), ("GCL+", config.GCL_PLUS_SECTOR_BOXES)):
        grid = sectors.read_number_grid(image, boxes, config.GCL_DARK_THRESHOLD, locate=True)
        for position, (value, conf, box) in grid.items():
            display_name = _gcl_sector_label(prefix, position, eye_for_mapping)
            result = fields.FieldResult(value=value, confidence=conf, valid=value != "" and lo <= float(value) <= hi)
            _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)

    # "Average thickness RNFL(um)" panel: "Label   value" rows; only the
    # right-aligned value is located and OCR'd (see fields.extract_panel_value).
    average_labels = {
        "rnfl_avg_total": "RNFL Total Thickness",
        "rnfl_avg_superior": "RNFL Superior",
        "rnfl_avg_inferior": "RNFL Inferior",
    }
    for key, display_name in average_labels.items():
        box = config.RNFL_AVERAGE_FIELDS[key]
        result = fields.extract_panel_value(image, box, decimal=False)
        _write_named_field(
            row, field_confidences, low_confidence_rois, reasons, display_name, result, box,
            numeric_range=NUMERIC_RANGES["rnfl"],
        )

    # Disc Topography panel: "Label (unit)   value" rows, decimal value.
    disc_labels = {
        "disc_area": "Disc Area",
        "cup_area": "Cup Area",
        "rim_area": "Rim Area",
        "cd_area_ratio": "C/D Area Ratio",
        "linear_cdr": "Linear CDR",
        "vertical_cdr": "Vertical CDR",
        "cup_volume": "Cup Volume",
        "rim_volume": "Rim Volume",
        "horizontal_dd": "Horizontal D.D",
        "vertical_dd": "Vertical D.D",
    }
    for key, display_name in disc_labels.items():
        box = config.DISC_TOPOGRAPHY_FIELDS[key]
        result = fields.extract_panel_value(image, box, decimal=True)
        _write_named_field(row, field_confidences, low_confidence_rois, reasons, display_name, result, box)


def _save_review_crops(image, stem: str, flagged_rois: list[tuple[str, tuple[int, int, int, int]]]):
    if not flagged_rois:
        return
    out_dir = Path(settings.REVIEW_DIR) / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    seen = set()
    for name, box in flagged_rois:
        if name in seen:
            continue
        seen.add(name)
        x1, y1, x2, y2 = box
        cv2.imwrite(str(out_dir / f"{name}.png"), image[y1:y2, x1:x2])
