"""
ROI pixel coordinates for the Topcon "3D Wide Glaucoma Report with VF test
points (Hood report)" layout, calibrated by hand against the two sample
reports in reference/ (both 1286x909).

All boxes are (x1, y1, x2, y2) in absolute image pixels.
"""

# Simple text fields: cropped and OCR'd as a single line, value read out with regex.
TEXT_FIELDS = {
    "patient_id": (20, 70, 340, 98),
    "name": (20, 98, 400, 122),
    "ethnicity": (445, 70, 800, 90),
    "gender": (445, 88, 800, 107),
    "dob_age": (445, 105, 800, 125),
    "technician": (810, 70, 1180, 90),
    "fixation": (810, 88, 1180, 107),
    "scan_info": (810, 105, 1180, 125),
    "capture_date": (125, 162, 310, 180),
}

# Eye laterality box, e.g. "OS(L)" / "OD(R)". Inset inside the box's own border --
# OCR'ing the border together with the text confuses line segmentation.
EYE_BOX = (46, 133, 118, 157)

# Image Quality score box (Topcon color-codes its border green/yellow/red).
IMAGE_QUALITY_BOX = (215, 130, 262, 160)

# RNFL sector wheels: each printed number is cropped individually (tight boxes,
# found via connected-component analysis after masking out the wheel graphic --
# OCR'ing the whole wheel at once merges the circle/crosshair into a garbage
# glyph). Position is geometric (top/right/bottom/left, clock-hour 1-12 from
# center), NOT the semantic label -- N/T flips sides depending on eye (L vs R
# mirror each other), which src/sectors.py resolves using the extracted eye field.
RNFL_QUADRANT_LABEL_BOXES = {
    "top": (683, 619, 719, 640),
    "left": (633, 668, 658, 688),
    "right": (742, 668, 767, 688),
    "bottom": (683, 718, 719, 739),
}

RNFL_CLOCK_LABEL_BOXES = {
    11: (662, 746, 688, 761),
    12: (688, 742, 714, 757),
    1: (714, 746, 740, 761),
    10: (645, 765, 666, 780),
    2: (735, 765, 756, 780),
    9: (639, 791, 660, 806),
    3: (741, 791, 762, 806),
    8: (645, 817, 666, 832),
    4: (735, 817, 756, 832),
    7: (662, 836, 688, 851),
    5: (714, 836, 740, 851),
    6: (688, 841, 714, 856),
}
