"""cv2 preprocessing + pytesseract wrapper used by every field extractor."""
import re

import cv2
import numpy as np
import pytesseract

from config import settings

pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

# Upscale factors read_number() tries (see its docstring). 3x alone was the
# single most reliable setting for 2-3 digit numbers; 4x is the cross-check.
NUMBER_UPSCALES = (3, 4)


def crop(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2]


def _preprocess(roi_bgr: np.ndarray, dark_threshold: int | None = None, scale: int | None = None) -> np.ndarray:
    """Grayscale, upscale (by `scale`, default settings.OCR_UPSCALE), binarize.
    Otsu by default; `dark_threshold` instead keeps only pixels darker than
    that value as ink -- for black print over a busy mid-tone background,
    where Otsu would keep the background detail too."""
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    scale = scale or settings.OCR_UPSCALE
    gray = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    if dark_threshold is not None:
        _, thresh = cv2.threshold(gray, dark_threshold, 255, cv2.THRESH_BINARY)
    else:
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def read_line(roi_bgr: np.ndarray, psm: int = 7) -> tuple[str, float]:
    """OCR a ROI expected to contain a single line of text. Returns (text, mean_confidence 0-100)."""
    words = read_line_words(roi_bgr, psm=psm)
    line = " ".join(w for w, _ in words)
    mean_conf = sum(c for _, c in words) / len(words) if words else 0.0
    return line, mean_conf


def read_line_words(roi_bgr: np.ndarray, psm: int = 7) -> list[tuple[str, float]]:
    """OCR a ROI, returning each recognized word with its own confidence, in reading order."""
    processed = _preprocess(roi_bgr)
    data = pytesseract.image_to_data(
        processed, config=f"--psm {psm}", output_type=pytesseract.Output.DICT
    )
    words = []
    for text, conf in zip(data["text"], data["conf"]):
        text = text.strip()
        conf = float(conf)
        if text and conf >= 0:
            words.append((text, conf))
    return words


def char_boxes(roi_bgr: np.ndarray, psm: int = 7) -> list[tuple[str, float, float, float, float]]:
    """Tesseract's per-character boxes for a single-line ROI, as
    (char, x1, y1, x2, y2) in the ROI's own (un-upscaled) pixel coordinates."""
    processed = _preprocess(roi_bgr)
    scale = settings.OCR_UPSCALE
    height = processed.shape[0]
    chars = []
    for line in pytesseract.image_to_boxes(processed, config=f"--psm {psm}").splitlines():
        parts = line.split(" ")
        if len(parts) < 5:
            continue
        char, left, bottom, right, top = parts[0], *map(int, parts[1:5])
        # image_to_boxes measures y from the bottom edge.
        chars.append((char, left / scale, (height - top) / scale, right / scale, (height - bottom) / scale))
    return chars


def _read_number_at(roi_bgr: np.ndarray, dark_threshold: int | None, allowed: str, scale: int) -> tuple[str, float]:
    processed = _preprocess(roi_bgr, dark_threshold, scale)
    processed = cv2.GaussianBlur(processed, (3, 3), 0)
    processed = cv2.copyMakeBorder(processed, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    data = pytesseract.image_to_data(
        processed,
        config=f"--psm 7 -c tessedit_char_whitelist={allowed}",
        output_type=pytesseract.Output.DICT,
    )
    digits, confs = [], []
    for text, conf in zip(data["text"], data["conf"]):
        text = re.sub(f"[^{re.escape(allowed)}]", "", text)
        conf = float(conf)
        if text and conf >= 0:
            digits.append(text)
            confs.append(conf)
    value = "".join(digits)
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    return value, mean_conf


def read_number(
    roi_bgr: np.ndarray, dark_threshold: int | None = None, decimal: bool = False,
) -> tuple[str, float]:
    """OCR a tight crop expected to contain exactly one small number.

    A white border is added after thresholding -- tesseract's confidence scoring
    is markedly less reliable on text that touches the crop edge.
    `dark_threshold` is passed through to _preprocess(). `decimal` also allows
    a "." (Disc Topography values like "0.81").

    The binarized crop is then lightly blurred: upscaling + hard thresholding
    leaves stair-stepped glyph edges, and softening them lifted the weakest
    reads without changing any value.

    Tesseract's read of a 2-3 digit number is erratic in a way that depends on
    the upscale factor -- across the 13 GlaucomaReport samples, 3x and 4x each
    occasionally return nothing, drop a digit or score a clean "75" at 0, but
    rarely on the same crop. So the number is read at both (NUMBER_UPSCALES)
    and combined: an empty read defers to the other; agreeing reads keep the
    higher confidence; disagreeing reads return the more confident value but
    the *lower* confidence, so the field gets flagged -- two scales seeing
    different digits is exactly the case a human should check.
    """
    allowed = "0123456789." if decimal else "0123456789"
    reads = [_read_number_at(roi_bgr, dark_threshold, allowed, scale) for scale in NUMBER_UPSCALES]
    reads = [r for r in reads if r[0]] or reads
    values = {v for v, _ in reads}
    best = max(reads, key=lambda r: r[1])
    if len(values) == 1:
        return best
    return best[0], min(c for _, c in reads)
