"""Line a report image up with its layout's reference page before cropping.

Reports don't always arrive at the exact export resolution the ROI boxes were
calibrated on -- a hand-cropped screenshot of the same report comes out a few
pixels wider/narrower/taller, with the page shifted by a pixel or two inside
it (vision/reference/12refs: 1278-1286 x 907-920 for a 1285x908 layout).
The page itself is still the same size, so rather than reject those outright,
this finds the page's full-width ruled lines -- the rule under the title and
the one above "Comments:" at the bottom -- and translates the image so they
land where they sit on the reference. Every ROI box then applies unchanged.

Only translation is corrected. If the rules' length or spacing doesn't match
the reference (a different export scale, a different layout, a crop that
cuts the page off), alignment fails and the caller flags the report instead
of cropping garbage from it.
"""
import cv2
import numpy as np

# A pixel counts as "ink" for rule detection below this gray level, and a row
# is a rule candidate when at least this share of its width is ink.
_DARK = 180
_ROW_FILL = 0.6
# Rules are 1-3px thick; anything thicker is a dark image panel, not a rule.
_MAX_RULE_THICKNESS = 4
# Allowed mismatch (px) in rule length/spacing before the page is treated as
# a different scale or layout rather than the same page shifted.
_TOLERANCE = 3


def _longest_run(row: np.ndarray) -> tuple[int, int]:
    """(start, end) of the longest run of True in a 1-D bool array, end inclusive."""
    padded = np.concatenate(([False], row, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = edges[::2], edges[1::2] - 1
    i = int(np.argmax(ends - starts))
    return int(starts[i]), int(ends[i])


def find_page_rules(image: np.ndarray) -> list[tuple[int, int, int]]:
    """Every thin, near-full-width horizontal rule as (top y, x start, x end),
    top to bottom. x start/end come from the rule's longest unbroken run, so
    a stray border pixel at the image edge doesn't skew them."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = gray < _DARK
    candidates = np.flatnonzero(dark.mean(axis=1) > _ROW_FILL)
    rules = []
    group: list[int] = []
    for y in list(candidates) + [None]:
        if y is not None and group and y - group[-1] <= 1:
            group.append(y)
            continue
        if group and len(group) <= _MAX_RULE_THICKNESS:
            x0, x1 = _longest_run(dark[group[0]])
            rules.append((group[0], x0, x1))
        group = [y] if y is not None else []
    return rules


def align_to_reference(image: np.ndarray, landmarks: dict, size: tuple[int, int]) -> tuple[np.ndarray | None, str]:
    """Translate `image` so its first and last page rules land on the
    reference positions in `landmarks` (see config/GlaucomaReport.PAGE_LANDMARKS),
    on a white canvas of `size` (width, height).

    Returns (aligned image, "") on success, or (None, reason) when the page
    can't be matched to the reference layout.
    """
    rules = find_page_rules(image)
    if len(rules) < 2:
        return None, "page rules not found"
    (top_y, x0, x1), (bottom_y, _, _) = rules[0], rules[-1]
    length = x1 - x0 + 1
    spacing = bottom_y - top_y
    if abs(length - landmarks["rule_length"]) > _TOLERANCE:
        return None, f"page rule is {length}px long, reference is {landmarks['rule_length']}px (different scale or layout)"
    if abs(spacing - landmarks["rule_spacing"]) > _TOLERANCE:
        return None, f"page rules are {spacing}px apart, reference is {landmarks['rule_spacing']}px (different scale or layout)"

    dx = landmarks["left_x"] - x0
    dy = landmarks["top_rule_y"] - top_y
    shift = np.float32([[1, 0, dx], [0, 1, dy]])
    aligned = cv2.warpAffine(image, shift, size, flags=cv2.INTER_NEAREST, borderValue=(255, 255, 255))
    return aligned, ""
