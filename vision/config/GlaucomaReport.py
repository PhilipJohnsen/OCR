"""
ROI pixel coordinates for the Topcon "3D Wide(H) Glaucoma Report" layout -- a
different report body than the Hood report (config/GlaucomaHood.py), built
around a Color photo / RNFL ThicknessMap / GCL macula grids / RNFL Circular
Tomogram / Disc Topography panel instead of the Hood report's VF-test-point
view. Calibrated by hand, field-by-field, against reference/Glaucoma Report 1
philip.tif (1285x908) -- the project's canonical baseline sample for this
report type.

All boxes are (x1, y1, x2, y2) in absolute image pixels, same convention as
GlaucomaHood.py. This report type previously scaled boxes as fractions of
image width/height (USES_RATIO_BOXES) to tolerate export resolutions other
than the baseline's -- but the ratio math introduced enough rounding/rescale
drift that several fields (particularly the RNFL clock wheel and GCL sector
grids, each a tight crop around one small number) landed low-confidence or
misread entirely. Static pixel boxes hand-fit to the baseline read
consistently in the 90s. An image whose page is the same size but sits at
a slightly different offset (extra margin, a hand-cropped screenshot) is
shifted onto the baseline first via PAGE_LANDMARKS below; one at a different
scale gets flagged for human review rather than cropped from rescaled boxes.

The header block (patient/scan info, eye laterality box, image quality box)
sits at the same relative position as GlaucomaHood.py -- both are printed
from the same Topcon template header -- so those boxes are duplicated here
rather than shared, in case the two report layouts drift apart later.
"""

# This report type's own reference resolution -- one pixel narrower/shorter
# than GlaucomaHood's (settings.EXPECTED_IMAGE_SIZE, 1286x909), close enough
# that reusing the shared constant would be tempting but still exact-match
# wrong for either layout. src/extract.py checks a config's own
# EXPECTED_IMAGE_SIZE when present, falling back to the shared one for
# GlaucomaHood (which has none of its own).
EXPECTED_IMAGE_SIZE = (1285, 908)  # (width, height)

# Where the page's full-width ruled lines sit on the baseline, as measured by
# src/align.find_page_rules: the rule under the title (top) and the one above
# "Comments:" (bottom). An image of any other size is translated so its rules
# land here (see src/align.py) instead of being rejected outright -- so a
# hand-cropped screenshot of this report a few pixels off EXPECTED_IMAGE_SIZE
# still reads. Rule length/spacing must match to within a few pixels, so a
# different export scale is still flagged rather than mis-cropped.
PAGE_LANDMARKS = {
    "top_rule_y": 63,
    "left_x": 39,
    "rule_length": 1206,
    "rule_spacing": 814,
}

# Simple text fields: cropped and OCR'd as a single line, value read out with regex.
# The three header-table rows sit at y 71-89 / 89-107 / 107-125 -- the bottom
# row stops above the full-width page rule at y 126-128, which OCR otherwise
# reads as a trailing run of underscores/dashes.
TEXT_FIELDS = {
    "patient_id": (18, 72, 330, 96),
    "name": (18, 98, 420, 122),
    "ethnicity": (585, 71, 880, 89),
    "gender": (585, 89, 880, 107),
    "technician": (896, 71, 1185, 89),
    "fixation": (896, 89, 1185, 107),
    "scan_info": (896, 107, 1185, 125),
}

# Dates are printed DD/MM/YYYY. Each box is the whole line the date sits on;
# src/fields.extract_date finds the two "/" glyphs in it and OCRs day, month
# and year as three separate digit-only reads, then recomposites them. The
# date's x position within the line differs between exports (it follows the
# label's rendered width), so fixed per-part boxes don't carry over.
CAPTURE_DATE_LINE = (128, 159, 300, 179)
DOB_LINE = (585, 107, 880, 125)
# Age isn't OCR'd -- it's derived from DOB and Capture Date (age at time of
# scan, matching what the report itself prints). See src/extract.py.

# Eye laterality box, e.g. "OS(L)" / "OD(R)". Inset inside the box's own border --
# OCR'ing the border together with the text confuses line segmentation.
EYE_BOX = (44, 131, 118, 157)

# Image Quality score box (Topcon color-codes its border green/yellow/red).
IMAGE_QUALITY_BOX = (217, 133, 257, 156)

# RNFL Circular Tomogram sector wheel: the 12 clock-hour thickness numbers
# printed around the wheel below the tomogram plot. Same geometric (not
# semantic) convention as GlaucomaHood's RNFL_CLOCK_LABEL_BOXES -- 12 = top,
# clockwise -- read via src/sectors.read_clock_wheel. Unlike the Hood report,
# this layout has no separate S/N/T/I quadrant-average numbers: the N/S/T/I
# letters printed at the wheel's center are static labels only.
# Boxes are fit to each number's glyph extents plus a 3px margin, so a crop
# never clips a digit or picks up its neighbour (6 o'clock's "137" sits
# directly between 5's "93" and 7's "104").
RNFL_CLOCK_LABEL_BOXES = {
    12: (812, 427, 836, 442),
    1: (839, 432, 863, 447),
    2: (861, 451, 879, 466),
    3: (867, 478, 885, 493),
    4: (861, 504, 878, 519),
    5: (842, 524, 860, 539),
    6: (812, 529, 836, 544),
    7: (786, 524, 810, 539),
    8: (769, 504, 787, 519),
    9: (763, 478, 781, 493),
    10: (769, 451, 787, 466),
    11: (786, 432, 810, 447),
}

# GCL++ Macula 6-Sector Grid: six values around a hexagonal macula grid
# (top / upper-left / upper-right / lower-left / lower-right / bottom).
GCL_PLUS_PLUS_SECTOR_BOXES = {
    "top": (128, 454, 150, 471),
    "upper_left": (78, 483, 99, 500),
    "upper_right": (175, 483, 204, 500),
    "lower_left": (78, 541, 100, 558),
    "lower_right": (175, 541, 204, 558),
    "bottom": (129, 570, 150, 587),
}

# GCL+ Macula 6-Sector Grid: same layout as GCL++, printed lower on the page.
GCL_PLUS_SECTOR_BOXES = {
    "top": (128, 679, 150, 696),
    "upper_left": (78, 708, 99, 725),
    "upper_right": (178, 708, 199, 725),
    "lower_left": (78, 766, 99, 783),
    "lower_right": (179, 766, 200, 783),
    "bottom": (129, 795, 150, 812),
}

# The GCL grids' bold black digits sit on a green/yellow retina photo crossed
# by darker blood vessels and the grid's own sector lines. Otsu thresholding
# per crop keeps those as "ink" too (GCL+ upper-right "71" read as "74"); a
# fixed cutoff keeps only near-black pixels. Every cutoff from 50-80 read all
# 12 baseline values correctly; per-value confidence just jitters within that
# range (e.g. GCL+ "72" scores 78-94 depending on cutoff), so 60 sits mid-band
# rather than being tuned to this one sample. Both GCL grids' boxes are fit to
# the digits' ink extents at this cutoff plus a 3px margin.
GCL_DARK_THRESHOLD = 60

# "Average thickness RNFL(um)" panel: each row is a "Label   value" line, read
# the same way as the header TEXT_FIELDS (OCR the row, regex out the trailing
# number).
# Each box stops just above its row's underline rule (y 481/505/529).
RNFL_AVERAGE_FIELDS = {
    "rnfl_avg_total": (1083, 463, 1252, 481),
    "rnfl_avg_superior": (1083, 487, 1252, 505),
    "rnfl_avg_inferior": (1083, 511, 1252, 529),
}

# Disc Topography panel: ten "Label (unit)   value" rows, read the same way.
# Same as above, each box ends just above that row's underline rule (every
# 23px from y 585 to 792).
DISC_TOPOGRAPHY_FIELDS = {
    "disc_area": (1006, 566, 1252, 585),
    "cup_area": (1006, 589, 1252, 608),
    "rim_area": (1006, 612, 1252, 631),
    "cd_area_ratio": (1006, 638, 1252, 654),
    "linear_cdr": (1006, 661, 1252, 677),
    "vertical_cdr": (1006, 684, 1252, 700),
    "cup_volume": (1006, 704, 1252, 723),
    "rim_volume": (1006, 727, 1252, 746),
    "horizontal_dd": (1006, 753, 1252, 769),
    "vertical_dd": (1006, 776, 1252, 792),
}
