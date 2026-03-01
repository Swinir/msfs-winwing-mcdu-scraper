"""
Automatic MCDU display detection for Airbus A330.

Detects the MCDU text grid within a captured window image by finding the
rectangular region with bright text on a dark background whose aspect ratio
is consistent with the 24×14 character grid.

The detection pipeline:
  1. Max-channel grayscale  (preserves coloured text brightness)
  2. Multi-strategy candidate generation:
     a) Row-gap analysis — look for evenly-spaced text rows (the hallmark
        of an MCDU grid) by analysing horizontal projection profiles.
     b) Contour-based fallback — dilate text blobs, score by area & aspect.
  3. Grid-structure validation  (count row gaps ≈ rows−1)
  4. Projection-profile refinement  (trim to exact text bounds)
"""

import numpy as np
import cv2
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

# Width/height ratio range that a valid MCDU text region can have.
# 24 columns / 14 rows ≈ 1.71, but the pixel aspect depends on cell shape.
_ASPECT_MIN = 1.0
_ASPECT_MAX = 3.0


# ------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------

def detect_mcdu_region(
    image: np.ndarray,
    columns: int = 24,
    rows: int = 14,
    min_area_frac: float = 0.01,
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

    # 2. Binary threshold for text
    thresh = _adaptive_text_threshold(gray)

    # Strategy A: row-gap analysis (most reliable for MCDU grids)
    best = _detect_via_row_gaps(gray, thresh, columns, rows,
                                min_area_frac, max_area_frac)

    # Strategy B: contour-based fallback
    if best is None:
        best = _detect_via_contours(gray, thresh, columns, rows,
                                     min_area_frac, max_area_frac)

    if best is None:
        logger.debug("Auto-detect: no region matched MCDU criteria")
        return None

    bx, by, bw, bh = best

    # 3. Refine with projection profiles (trim dead border pixels)
    refined = _refine_with_projections(gray[by:by + bh, bx:bx + bw])
    if refined is not None:
        rx, ry, rw, rh = refined
        bx += rx
        by += ry
        bw = rw
        bh = rh

    # 4. Small padding so edge characters aren't clipped
    pad_x = max(2, int(bw * 0.01))
    pad_y = max(2, int(bh * 0.01))
    bx = max(0, bx - pad_x)
    by = max(0, by - pad_y)
    bw = min(w - bx, bw + 2 * pad_x)
    bh = min(h - by, bh + 2 * pad_y)

    logger.info(f"Auto-detected MCDU region: x={bx}, y={by}, "
                f"w={bw}, h={bh} (aspect={bw / max(bh, 1):.2f})")
    return (bx, by, bw, bh)


# ------------------------------------------------------------------
#  Strategy A: Row-gap detection
# ------------------------------------------------------------------

def _detect_via_row_gaps(
    gray: np.ndarray,
    thresh: np.ndarray,
    columns: int,
    rows: int,
    min_area_frac: float,
    max_area_frac: float,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Find the MCDU by looking for a vertical region with roughly-evenly-spaced
    horizontal text rows.

    An MCDU has *rows* character rows, but some may be **empty** (no text at
    all), so we cannot require exactly *rows* text bands.  Instead we:

      1. Find all text bands via horizontal projection.
      2. Estimate the dominant row pitch from the most common center-to-center
         spacing among adjacent bands.
      3. Search for the largest cluster of bands whose spacings are multiples
         of the row pitch (within tolerance), allowing for empty-row gaps.
      4. Extend the bounding box to cover the full expected grid height
         (row_pitch × rows), since the first/last visible row may not be
         at the very edge.
    """
    h, w = gray.shape[:2]
    total_area = h * w

    # Horizontal projection of the thresholded image
    h_proj = np.sum(thresh, axis=1).astype(np.float64)
    if np.max(h_proj) == 0:
        return None

    h_proj /= np.max(h_proj)

    # Identify contiguous text bands
    gap_thresh = 0.08
    is_text = h_proj > gap_thresh

    bands: List[Tuple[int, int]] = []  # (start_y, end_y)
    in_band = False
    band_start = 0
    for y in range(h):
        if is_text[y] and not in_band:
            in_band = True
            band_start = y
        elif not is_text[y] and in_band:
            in_band = False
            if y - band_start >= 3:
                bands.append((band_start, y))
    if in_band and h - band_start >= 3:
        bands.append((band_start, h))

    if len(bands) < 4:
        logger.debug("Row-gap detection: only %d text bands found", len(bands))
        return None

    # Compute all adjacent center-to-center spacings
    centers = [(b[0] + b[1]) / 2.0 for b in bands]
    adj_spacings = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]

    if not adj_spacings:
        return None

    # Estimate dominant row pitch: the smallest common spacing.
    # On an MCDU, adjacent text rows are separated by one row pitch;
    # empty rows create gaps that are multiples of the pitch.
    # Use the 25th percentile of spacings as the pitch estimate
    # (most gaps are 1-row apart; empty rows create larger gaps).
    sorted_sp = sorted(adj_spacings)
    pitch_estimate = float(sorted_sp[max(0, len(sorted_sp) // 4)])
    if pitch_estimate < 5:
        pitch_estimate = float(np.median(sorted_sp))
    if pitch_estimate < 5:
        return None

    # Refine: take the median of spacings that are close to 1× pitch
    close_to_1x = [s for s in adj_spacings if abs(s - pitch_estimate) < pitch_estimate * 0.4]
    if close_to_1x:
        pitch = float(np.median(close_to_1x))
    else:
        pitch = pitch_estimate

    # Find the largest cluster of bands where each spacing is ~ N × pitch
    # (N = 1, 2, 3 … for empty rows between).
    tolerance = 0.35  # fraction of pitch
    best_cluster: List[int] = []  # indices into bands[]

    for start_idx in range(len(bands)):
        cluster = [start_idx]
        for j in range(start_idx + 1, len(bands)):
            gap = centers[j] - centers[cluster[-1]]
            # How many row-pitches does this gap correspond to?
            n_rows = gap / pitch
            n_rounded = round(n_rows)
            if n_rounded < 1:
                continue
            # Allow gaps up to (rows) pitches (entire grid height)
            if n_rounded > rows:
                break
            deviation = abs(n_rows - n_rounded) / max(n_rounded, 1)
            if deviation < tolerance:
                cluster.append(j)

        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) < 4:
        logger.debug("Row-gap detection: largest cluster has only %d bands",
                     len(best_cluster))
        return None

    # Compute bounding box from the cluster
    cluster_bands = [bands[i] for i in best_cluster]
    y1 = cluster_bands[0][0]
    y2 = cluster_bands[-1][1]

    # Extend to cover the full expected grid height.
    # Count how many row pitches the cluster spans.
    cluster_span = centers[best_cluster[-1]] - centers[best_cluster[0]]
    visible_rows = round(cluster_span / pitch) + 1
    if visible_rows < rows:
        # Extend symmetrically if possible
        missing = rows - visible_rows
        extend_top = int((missing / 2) * pitch)
        extend_bot = int(((missing + 1) / 2) * pitch)
        y1 = max(0, y1 - extend_top)
        y2 = min(h, y2 + extend_bot)

    region_h = y2 - y1

    # Horizontal bounds from active columns in this region
    roi_thresh = thresh[y1:y2, :]
    v_proj = np.sum(roi_thresh, axis=0).astype(np.float64)
    v_max = np.max(v_proj)
    if v_max == 0:
        return None
    v_proj /= v_max
    active_cols = np.where(v_proj > 0.03)[0]
    if len(active_cols) < 10:
        return None
    x1 = int(active_cols[0])
    x2 = int(active_cols[-1]) + 1
    region_w = x2 - x1

    # Check aspect ratio
    aspect = region_w / max(region_h, 1)
    if not (_ASPECT_MIN <= aspect <= _ASPECT_MAX):
        logger.debug("Row-gap detection: aspect %.2f out of range", aspect)
        return None

    # Check area
    area_frac = (region_w * region_h) / total_area
    if area_frac < min_area_frac or area_frac > max_area_frac:
        return None

    logger.debug("Row-gap detection: found %d bands, pitch=%.1f, "
                 "~%d visible rows out of %d",
                 len(best_cluster), pitch, visible_rows, rows)
    return (x1, y1, region_w, region_h)


# ------------------------------------------------------------------
#  Strategy B: Contour-based detection (fallback)
# ------------------------------------------------------------------

def _detect_via_contours(
    gray: np.ndarray,
    thresh: np.ndarray,
    columns: int,
    rows: int,
    min_area_frac: float,
    max_area_frac: float,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Fallback: dilate text into blobs, find bounding boxes, pick the one
    with the best aspect ratio and area.  Avoids merging with title bars
    by using conservative dilation.
    """
    h, w = gray.shape[:2]
    total_area = h * w
    expected_aspect = columns / rows

    # Conservative horizontal dilation (connect characters in a row but not rows)
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(8, w // 60), 2))
    dilated = cv2.dilate(thresh, kernel_h, iterations=2)
    # Mild vertical dilation to connect rows
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (2, max(3, h // 50)))
    dilated = cv2.dilate(dilated, kernel_v, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best, best_score = None, 0.0
    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        area_frac = (bw * bh) / total_area
        if area_frac < min_area_frac or area_frac > max_area_frac:
            continue
        aspect = bw / max(bh, 1)
        if not (_ASPECT_MIN <= aspect <= _ASPECT_MAX):
            continue

        # Validate that this region has grid-like row structure
        roi = gray[by:by + bh, bx:bx + bw]
        grid_score = _score_grid_structure(roi, rows)

        aspect_score = 1.0 - min(abs(aspect - expected_aspect) / expected_aspect, 1.0)
        score = grid_score * 0.5 + area_frac * 0.2 + aspect_score * 0.3

        if score > best_score:
            best_score = score
            best = (bx, by, bw, bh)

    # If individual contours didn't work, try the bounding box of ALL text
    # but only if there are multiple small contours (characteristic of
    # text rows that didn't get merged by dilation)
    if best is None and len(contours) > 3:
        all_pts = np.vstack(contours)
        bx, by, bw, bh = cv2.boundingRect(all_pts)
        area_frac = (bw * bh) / total_area
        aspect = bw / max(bh, 1)
        if (min_area_frac <= area_frac <= max_area_frac
                and _ASPECT_MIN <= aspect <= _ASPECT_MAX):
            best = (bx, by, bw, bh)

    return best


# ------------------------------------------------------------------
#  Internal helpers
# ------------------------------------------------------------------

def _adaptive_text_threshold(gray: np.ndarray) -> np.ndarray:
    """Threshold *gray* to isolate bright text, adapting to image brightness."""
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


def _score_grid_structure(
    region: np.ndarray,
    rows: int,
) -> float:
    """
    Score how well a region looks like a character grid (0.0–1.0).

    Checks for evenly-spaced horizontal text rows by counting valleys
    in the horizontal projection profile.
    """
    h, w = region.shape[:2]
    if h < rows * 2:
        return 0.0

    _, binary = cv2.threshold(region, 50, 255, cv2.THRESH_BINARY)
    h_proj = np.sum(binary, axis=1).astype(float)
    mx = np.max(h_proj)
    if mx == 0:
        return 0.0
    h_proj /= mx

    # Count valleys in the horizontal profile
    is_valley = h_proj < 0.15
    transitions = np.diff(is_valley.astype(int))
    n_valleys = int(np.sum(transitions == 1))

    expected = rows - 1
    if expected == 0:
        return 0.5

    # Score: 1.0 when valleys == expected, degrades linearly
    diff = abs(n_valleys - expected)
    return max(0.0, 1.0 - diff / expected)
