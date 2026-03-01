"""
Automatic MCDU display detection for Airbus A330.

Detects the MCDU text grid within a captured window image by finding the
rectangular region with bright text on a dark background whose aspect ratio
is consistent with the 24×14 character grid.

The detection pipeline:
  1. Max-channel grayscale  (preserves coloured text brightness)
  2. Adaptive thresholding  (handles varying MSFS brightness/gamma)
  3. Morphological dilation  (connects nearby text into row blobs)
  4. Contour analysis        (finds the display bounding box)
  5. Projection-profile refinement  (trims to exact text bounds)
"""

import numpy as np
import cv2
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Width/height ratio range that a valid MCDU text region can have.
# 24 columns / 14 rows ≈ 1.71, but the pixel aspect depends on cell shape.
_ASPECT_MIN = 1.1
_ASPECT_MAX = 2.8


# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------

def detect_mcdu_region(
    image: np.ndarray,
    columns: int = 24,
    rows: int = 14,
    min_area_frac: float = 0.02,
    max_area_frac: float = 0.95,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect the MCDU text area inside *image*.

    Args:
        image:         BGR or RGB uint8 image (H×W×3).
        columns:       Expected number of character columns.
        rows:          Expected number of character rows.
        min_area_frac: Reject regions smaller than this fraction of the image.
        max_area_frac: Reject regions larger than this fraction of the image.

    Returns:
        ``(x, y, width, height)`` in pixel coordinates, or ``None``.
    """
    h, w = image.shape[:2]
    total_area = h * w

    # 1. Max-channel grayscale (coloured text → bright)
    if len(image.shape) == 3:
        gray = np.max(image, axis=2)
    else:
        gray = image.copy()

    # 2. Adaptive threshold — robust to brightness shifts
    thresh = _adaptive_text_threshold(gray)

    # 3. Dilate to merge nearby text into row-level blobs
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 40), 3))
    dilated = cv2.dilate(thresh, kernel_h, iterations=3)
    # Vertical dilation to connect rows
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (3, max(5, h // 30)))
    dilated = cv2.dilate(dilated, kernel_v, iterations=2)

    # 4. Find contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        logger.debug("Auto-detect: no text contours found")
        return None

    # 5. Score each candidate region
    best, best_score = None, 0.0
    expected_aspect = columns / rows  # ~1.71

    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        area_frac = area / total_area
        if area_frac < min_area_frac or area_frac > max_area_frac:
            continue
        aspect = bw / max(bh, 1)
        if not (_ASPECT_MIN <= aspect <= _ASPECT_MAX):
            continue
        # Prefer large area + aspect close to expected
        aspect_score = 1.0 - min(abs(aspect - expected_aspect) / expected_aspect, 1.0)
        score = area_frac * (0.3 + 0.7 * aspect_score)
        if score > best_score:
            best_score = score
            best = (bx, by, bw, bh)

    # If individual contours didn't work, try the bounding box of ALL text
    if best is None and len(contours) > 1:
        all_pts = np.vstack(contours)
        bx, by, bw, bh = cv2.boundingRect(all_pts)
        area_frac = (bw * bh) / total_area
        aspect = bw / max(bh, 1)
        if (min_area_frac <= area_frac <= max_area_frac
                and _ASPECT_MIN <= aspect <= _ASPECT_MAX):
            best = (bx, by, bw, bh)

    if best is None:
        logger.debug("Auto-detect: no region matched MCDU criteria")
        return None

    bx, by, bw, bh = best

    # 6. Refine with projection profiles (trim dead border pixels)
    refined = _refine_with_projections(gray[by:by + bh, bx:bx + bw])
    if refined is not None:
        rx, ry, rw, rh = refined
        bx += rx
        by += ry
        bw = rw
        bh = rh

    # 7. Small padding so edge characters aren't clipped
    pad_x = max(2, int(bw * 0.01))
    pad_y = max(2, int(bh * 0.01))
    bx = max(0, bx - pad_x)
    by = max(0, by - pad_y)
    bw = min(w - bx, bw + 2 * pad_x)
    bh = min(h - by, bh + 2 * pad_y)

    # 8. Validate grid structure (optional — logs a warning if it looks off)
    _validate_grid_structure(gray[by:by + bh, bx:bx + bw], columns, rows)

    logger.info(f"Auto-detected MCDU region: x={bx}, y={by}, "
                f"w={bw}, h={bh} (aspect={bw / max(bh, 1):.2f})")
    return (bx, by, bw, bh)


# ------------------------------------------------------------------
#  Internal helpers
# ------------------------------------------------------------------

def _adaptive_text_threshold(gray: np.ndarray) -> np.ndarray:
    """Threshold *gray* to isolate bright text, adapting to image brightness."""
    # Otsu works well when there is a clear bimodal distribution
    otsu_val, binary = cv2.threshold(gray, 0, 255,
                                     cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # If Otsu picks a very low threshold (image is mostly dark), enforce a minimum
    if otsu_val < 40:
        _, binary = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)
    return binary


def _refine_with_projections(
    region: np.ndarray,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Trim a region to the actual text bounds using horizontal and vertical
    projection profiles.
    """
    h, w = region.shape[:2]
    if h < 10 or w < 10:
        return None

    _, binary = cv2.threshold(region, 40, 255, cv2.THRESH_BINARY)
    h_proj = np.sum(binary, axis=1).astype(float)
    v_proj = np.sum(binary, axis=0).astype(float)

    h_thresh = np.max(h_proj) * 0.03 if np.max(h_proj) > 0 else 1
    v_thresh = np.max(v_proj) * 0.03 if np.max(v_proj) > 0 else 1

    h_active = np.where(h_proj > h_thresh)[0]
    v_active = np.where(v_proj > v_thresh)[0]

    if len(h_active) < 2 or len(v_active) < 2:
        return None

    y1 = max(0, int(h_active[0]) - 2)
    y2 = min(h, int(h_active[-1]) + 3)
    x1 = max(0, int(v_active[0]) - 2)
    x2 = min(w, int(v_active[-1]) + 3)

    if (x2 - x1) < 10 or (y2 - y1) < 10:
        return None

    return (x1, y1, x2 - x1, y2 - y1)


def _validate_grid_structure(
    region: np.ndarray,
    columns: int,
    rows: int,
) -> bool:
    """
    Check whether the detected region looks like a valid character grid by
    examining horizontal projection gaps (the dark bands between text rows).
    """
    h, w = region.shape[:2]
    if h < rows * 2:
        return False

    _, binary = cv2.threshold(region, 50, 255, cv2.THRESH_BINARY)
    h_proj = np.sum(binary, axis=1).astype(float)
    h_proj /= max(np.max(h_proj), 1)

    # Count valleys in the horizontal profile — should be close to (rows - 1)
    is_valley = h_proj < 0.15
    transitions = np.diff(is_valley.astype(int))
    n_valleys = int(np.sum(transitions == 1))

    expected = rows - 1
    if abs(n_valleys - expected) <= 3:
        logger.debug(f"Grid validation OK: {n_valleys} row gaps "
                     f"(expected ~{expected})")
        return True
    else:
        logger.debug(f"Grid validation WARN: {n_valleys} row gaps "
                     f"(expected ~{expected}) — detection may be imprecise")
        return False
