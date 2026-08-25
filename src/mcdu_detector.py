"""
Automatic MCDU display detection.

Finds the character grid inside a captured window so that the crop handed to
the parser lines up with the cells.

Precision matters far more here than it looks.  Measured against rendered
pages, a crop half a character cell out of position scores 0% recognition,
and one 5% too wide scores 41%.  A box that merely looks right is worthless,
which is why this detects the character *pitch* and phase-aligns to it rather
than returning a bounding box around the text:

  1. Isolate ink sitting on a dark background, which excludes window chrome.
  2. Find the text rows, discarding solid rules and bezel lines.
  3. Estimate row and column pitch from the spacing between glyphs, then
     refit to reject anything off the lattice.
  4. Place the grid origin on that lattice and return columns x pitch.

Returning the grid rather than the text bounds also handles sparse pages: one
whose right-hand columns are blank still yields the full 24x14 area, where a
bounding box would crop the empty columns away and shift every character into
the wrong cell.

The older bounding-box strategies remain as fallbacks for captures where the
pitch cannot be established.
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
#  Pitch-based grid detection (primary strategy)
# ------------------------------------------------------------------

#: Minimum local contrast for a pixel to count as ink.
_INK_CONTRAST = 40

#: A band this thin that runs edge to edge is a rule, not a line of text.
_RULE_MAX_THICKNESS = 6
_RULE_MIN_SOLIDITY = 0.92


def _ink_mask(image: np.ndarray) -> Optional[np.ndarray]:
    """Ink that sits on a dark background.

    Window chrome carries text too - a title bar, tab labels, menus - and
    including it wrecks the pitch estimate.  MCDU glyphs are distinguished by
    what they sit on: a dark screen, where chrome text sits on a light one.
    """
    gray = np.max(image, axis=2) if image.ndim == 3 else image
    height, width = gray.shape[:2]

    # A median wide enough to swallow the glyphs leaves the background behind.
    kernel = max(5, (min(height, width) // 20) | 1)
    background = cv2.medianBlur(gray, kernel)

    ink = (gray.astype(np.int16) - background.astype(np.int16)) > _INK_CONTRAST
    if not ink.any():
        return None

    threshold, _ = cv2.threshold(background, 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    on_dark = ink & (background < threshold)

    # If almost nothing survives, the capture is probably the screen alone
    # with no chrome to exclude; keep the unfiltered ink instead.
    if on_dark.sum() > ink.sum() * 0.3:
        return on_dark
    return ink


def _text_rows(mask: np.ndarray) -> List[Tuple[int, int]]:
    """Vertical extents of text rows, excluding solid rules and borders."""
    projection = mask.sum(axis=1)
    rows: List[Tuple[int, int]] = []
    start = None
    for i, has_ink in enumerate(projection > 0):
        if has_ink and start is None:
            start = i
        elif not has_ink and start is not None:
            rows.append((start, i - 1))
            start = None
    if start is not None:
        rows.append((start, len(projection) - 1))

    kept = []
    for top, bottom in rows:
        occupied = mask[top:bottom + 1, :].any(axis=0)
        extent = np.nonzero(occupied)[0]
        if extent.size == 0:
            continue
        # Text is broken up by the gaps between glyphs; a bezel line or an
        # underline runs continuously from one edge to the other.
        solidity = occupied[extent[0]:extent[-1] + 1].mean()
        if (solidity > _RULE_MIN_SOLIDITY
                and (bottom - top + 1) <= _RULE_MAX_THICKNESS):
            continue
        kept.append((top, bottom))
    return kept


def _glyph_centers_per_row(mask: np.ndarray,
                           rows: List[Tuple[int, int]]) -> List[List[float]]:
    """Horizontal glyph centres, gathered one text row at a time.

    Projecting the whole image onto the x axis fails as soon as the page is
    busy: nearly every column has ink in some row, so the projection never
    returns to zero and the entire width reads as a single run.  Within one
    row the gaps between glyphs survive.
    """
    per_row = []
    for top, bottom in rows:
        projection = mask[top:bottom + 1, :].sum(axis=0)
        centers, start = [], None
        for i, has_ink in enumerate(projection > 0):
            if has_ink and start is None:
                start = i
            elif not has_ink and start is not None:
                centers.append((start + i - 1) / 2.0)
                start = None
        if start is not None:
            centers.append((start + len(projection) - 1) / 2.0)
        if len(centers) >= 2:
            per_row.append(centers)
    return per_row


def _fit_lattice(centers, pitch: float):
    """Drop centres that do not sit on the pitch lattice, then refit."""
    values = np.asarray(centers, dtype=float)
    phase = values[0] % pitch
    index = np.round((values - phase) / pitch)
    residual = np.abs((values - phase) - index * pitch)
    keep = residual < pitch * 0.3
    if keep.sum() < 2:
        return list(centers), pitch

    values, index = values[keep], index[keep]
    span = index[-1] - index[0]
    if span >= 1:
        # Fitting across the whole span averages out per-glyph rounding.
        pitch = float((values[-1] - values[0]) / span)
    return values.tolist(), pitch


def _pitch_from_spacings(spacings: np.ndarray) -> Optional[float]:
    """Cell pitch from centre-to-centre spacings, which are whole multiples."""
    spacings = spacings[spacings > 0.5]
    if spacings.size == 0:
        return None
    # Most neighbouring glyphs sit one cell apart; wider gaps are multiples.
    base = np.percentile(spacings, 20)
    single = spacings[spacings <= base * 1.6]
    if single.size == 0:
        single = spacings
    pitch = float(np.median(single))
    return pitch if pitch >= 2 else None


def _choose_origin(centers, pitch: float, n_cells: int,
                   lo: float, hi: float) -> float:
    """Place the grid origin on the lattice so that it covers all the text."""
    phase = (centers[0] - pitch / 2) % pitch
    highest = int(np.floor((lo - phase) / pitch)) + 1
    for k in range(highest, highest - n_cells - 2, -1):
        origin = phase + k * pitch
        if origin > lo + 0.5:
            continue
        if origin + n_cells * pitch < hi - 0.5:
            continue
        if origin < -pitch * 0.6:
            continue
        return origin
    return phase + np.floor((lo - phase) / pitch) * pitch


def _detect_via_pitch(image: np.ndarray, columns: int,
                      rows: int) -> Optional[Tuple[int, int, int, int]]:
    """Locate the character grid by its pitch.  Returns (x, y, width, height)."""
    mask = _ink_mask(image)
    if mask is None:
        return None
    height, width = mask.shape

    row_bounds = _text_rows(mask)
    if len(row_bounds) < 2:
        return None

    row_centers = [(top + bottom) / 2.0 for top, bottom in row_bounds]
    row_pitch = _pitch_from_spacings(np.diff(np.asarray(row_centers, float)))
    if row_pitch is None:
        return None
    row_centers, row_pitch = _fit_lattice(row_centers, row_pitch)

    per_row = _glyph_centers_per_row(mask, row_bounds)
    if not per_row:
        return None
    spacings = np.concatenate([np.diff(np.asarray(c, float)) for c in per_row])
    col_pitch = _pitch_from_spacings(spacings)
    if col_pitch is None:
        return None
    col_centers = sorted(c for centers in per_row for c in centers)
    col_centers, col_pitch = _fit_lattice(col_centers, col_pitch)

    # Bounds come from validated text, never from the raw ink bounding box:
    # a bezel line or window border stretches the bbox and slides the whole
    # grid a cell out of place, which alone is enough to destroy recognition.
    y_lo, y_hi = row_bounds[0][0], row_bounds[-1][1] + 1
    x_lo = min(col_centers) - col_pitch / 2
    x_hi = max(col_centers) + col_pitch / 2

    x = int(round(_choose_origin(col_centers, col_pitch, columns, x_lo, x_hi)))
    y = int(round(_choose_origin(row_centers, row_pitch, rows, y_lo, y_hi)))
    x, y = max(0, x), max(0, y)
    w = min(int(round(columns * col_pitch)), width - x)
    h = min(int(round(rows * row_pitch)), height - y)

    if w < columns or h < rows:
        return None
    return (x, y, w, h)


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

    # Preferred: lock onto the character pitch.  This is the only strategy
    # that yields a crop aligned to the cells rather than merely surrounding
    # the text, and alignment is what recognition actually depends on.
    grid = _detect_via_pitch(image, columns, rows)
    if grid is not None:
        gx, gy, gw, gh = grid
        area_frac = (gw * gh) / total_area
        aspect = gw / max(gh, 1)
        if (min_area_frac <= area_frac <= max_area_frac
                and _ASPECT_MIN <= aspect <= _ASPECT_MAX):
            logger.info(
                "Detected MCDU grid by pitch: x=%d, y=%d, w=%d, h=%d "
                "(cell %.2fx%.2f px)",
                gx, gy, gw, gh, gw / columns, gh / rows,
            )
            return grid
        logger.debug(
            "Pitch detection rejected: area_frac=%.3f aspect=%.2f",
            area_frac, aspect,
        )

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
    # 3×3 median blur removes single-pixel noise (JPEG/capture artefacts)
    # before Otsu without blurring text edges (median is edge-preserving).
    blurred = cv2.medianBlur(gray, 3)
    otsu_val, binary = cv2.threshold(blurred, 0, 255,
                                     cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # If Otsu picks a very low threshold (image is mostly dark), enforce a minimum
    if otsu_val < 40:
        _, binary = cv2.threshold(blurred, 40, 255, cv2.THRESH_BINARY)
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
