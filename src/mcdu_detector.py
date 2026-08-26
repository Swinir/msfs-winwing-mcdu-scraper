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

#: Below this occupancy a band is frame debris rather than text.
_NOISE_MAX_SOLIDITY = 0.04


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

    # Remove window chrome by its background, not its brightness.  The old
    # Otsu rule assumed chrome is light; a dark-mode title bar (background
    # 78-106) passed it and the grid stretched up over the window title.
    # Measured across seven captures, screen ink sits on background 0-18 and
    # chrome ink on 78-203, so rows whose background clearly exceeds the
    # dominant level are chrome.
    #
    # Chrome rows are *flattened to the dominant level* before the ink pass
    # rather than masked after it: the median blur straddles the boundary,
    # so a title line flush under the chrome inherits an inflated local
    # background and a mask-after approach silently ate the MCDU's top row.
    dominant = float(np.median(background))
    row_background = np.median(background, axis=1)
    chrome_rows = row_background > dominant + 40

    if chrome_rows.any():
        flattened = gray.copy()
        flattened[chrome_rows] = int(dominant)
        background = cv2.medianBlur(flattened, kernel)
        gray = flattened

    ink = (gray.astype(np.int16) - background.astype(np.int16)) > _INK_CONTRAST
    if not ink.any():
        return None

    # Whatever chrome the row rule could not catch (a floating dialog, a
    # side panel) still sits on an elevated background; drop that ink too.
    on_screen = ink & (background <= dominant + 40)
    if on_screen.sum() > ink.sum() * 0.3:
        return on_screen
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
        # The opposite extreme: a few stray pixels spanning a wide extent is
        # a window edge or resize grip, not a line of text.  One such band
        # at the bottom of an ATR capture dragged the grid past the screen.
        if solidity < _NOISE_MAX_SOLIDITY:
            continue
        kept.append((top, bottom))
    return kept


def _split_touching_rows(rows: List[Tuple[int, int]],
                         projection: np.ndarray) -> List[Tuple[int, int]]:
    """Split bands holding several text rows with no blank line between them.

    Row detection assumes a gap between lines, which holds for an airliner
    CDU and not for a display with large glyphs and tight leading: on a
    Working Title UNS-1 capture five text rows merge into a single 141px
    band, and nothing downstream can recover the rows from it.

    A band several times the height of a normal one is cut at its internal
    projection minima, which fall in the valleys between lines.
    """
    if len(rows) < 2:
        return rows

    heights = sorted(bottom - top + 1 for top, bottom in rows)
    # Lower quartile, because merged bands are the large outliers and a
    # median would be dragged up by them.  Rules and frame noise are already
    # filtered out, so the smallest survivors are real rows.  A CDU's label
    # and content rows differ by around 25%, well under the 1.7x needed to
    # trigger a split.
    unit = heights[len(heights) // 4]
    if unit < 2:
        return rows

    out: List[Tuple[int, int]] = []
    for top, bottom in rows:
        height = bottom - top + 1
        count = int(round(height / unit))
        if count <= 1 or height < unit * 1.7:
            out.append((top, bottom))
            continue

        cuts = []
        for i in range(1, count):
            target = top + int(round(i * height / count))
            lo = max(top + 2, target - unit // 3)
            hi = min(bottom - 2, target + unit // 3)
            if hi > lo:
                cuts.append(lo + int(np.argmin(projection[lo:hi + 1])))

        edges = [top] + sorted(set(cuts)) + [bottom]
        for i in range(len(edges) - 1):
            if edges[i + 1] > edges[i]:
                out.append((edges[i], edges[i + 1]))
    return out


def _drop_chrome_remnants(rows: List[Tuple[int, int]],
                          chrome_bottom: int) -> List[Tuple[int, int]]:
    """Drop a stub of window chrome that survived the ink mask.

    Needs two signals together, because either alone removes real content.
    A band touching the chrome boundary is not enough: on the ATR the title
    row begins exactly there.  Being much shorter than a normal row is not
    enough either: the ATR draws a dashed separator only 3px tall, a fifth
    of its median row.

    A band that is *both* is chrome bleed.  On a UNS-1 capture a 9px stub at
    the title bar's edge forced the grid origin ten pixels high, putting a
    boundary through every row below it.
    """
    if len(rows) < 3 or chrome_bottom <= 0:
        return rows
    heights = [bottom - top + 1 for top, bottom in rows]
    median = float(np.median(heights))
    kept = [(top, bottom) for top, bottom in rows
            if not (top <= chrome_bottom
                    and (bottom - top + 1) < median * 0.5)]
    return kept if len(kept) >= 2 else rows


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
        # Runs a single pixel wide are edge debris, not glyphs: one at x=0
        # on an ATR capture became a phantom column centre and dragged the
        # grid origin to the window border, three cells left of the text.
        for i, has_ink in enumerate(projection > 0):
            if has_ink and start is None:
                start = i
            elif not has_ink and start is not None:
                if i - start >= 2:
                    centers.append((start + i - 1) / 2.0)
                start = None
        if start is not None and len(projection) - start >= 2:
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


def _refine_pitch_over_baselines(per_row, pitch: float) -> float:
    """Correct the pitch using whole-line spans instead of adjacent gaps.

    Adjacent glyph spacings are a biased ruler: glyphs that touch merge into
    one run and glyphs with internal gaps split into two, and the median
    lands a few percent low.  On a GNLU910 capture that gave 15.12px against
    a true ~15.8 - across 24 columns the crop ended 36px early and cut the
    page's right-hand column off.

    Glyphs are centred in their cells, so the distance between the first and
    last run centres of a line is an exact whole number of cells.  Dividing
    each line's span by that (rounded) count divides the bias by the count;
    the initial pitch is only trusted to pick the integer.
    """
    estimates = []
    for centers in per_row:
        if len(centers) < 2:
            continue
        span = centers[-1] - centers[0]
        cells = int(round(span / pitch))
        if cells >= 6:
            estimates.append(span / cells)
    if not estimates:
        return pitch
    refined = float(np.median(estimates))
    # A wild disagreement means some line's cell count was rounded wrongly;
    # in that case the original estimate is the safer one.
    if abs(refined - pitch) > pitch * 0.15:
        return pitch
    return refined


def _pitch_by_total_span(gaps: np.ndarray, seed: float) -> Optional[float]:
    """Cell pitch as total span divided by total cells.

    Each gap is a whole number of cells, so summing the gaps and dividing by
    the summed cell counts averages the estimate over the entire column of
    text.  This survives what the per-gap mode does not: a display whose
    label rows sit closer to their value rows than a uniform pitch implies.
    On the Fokker F70 those gaps alternate 26px and 17px, and the mode picks
    one of the two instead of the 21.7px average.
    """
    if gaps.size == 0 or seed < 2:
        return None
    pitch = seed
    for _ in range(3):
        counts = np.maximum(1.0, np.round(gaps / pitch))
        total = float(counts.sum())
        if total <= 0:
            return None
        pitch = float(gaps.sum() / total)
        if pitch < 2:
            return None
    return pitch


def _rows_uncut(bounds, origin: float, pitch: float, n_cells: int) -> int:
    """How many text rows sit wholly inside one cell of this grid."""
    edges = [origin + i * pitch for i in range(n_cells + 1)]
    return sum(1 for top, bottom in bounds
               if not any(top < edge < bottom for edge in edges))


def _glyph_runs(mask: np.ndarray, rows):
    """Every glyph ink run on the display, as (starts, ends) arrays."""
    runs: List[Tuple[int, int]] = []
    for top, bottom in rows:
        projection = mask[top:bottom + 1, :].sum(axis=0)
        start = None
        for i, has_ink in enumerate(projection > 0):
            if has_ink and start is None:
                start = i
            elif not has_ink and start is not None:
                if i - start >= 2:
                    runs.append((start, i - 1))
                start = None
        if start is not None and len(projection) - start >= 2:
            runs.append((start, len(projection) - 1))
    if not runs:
        return (np.empty(0), np.empty(0))
    return (np.array([r[0] for r in runs], dtype=float),
            np.array([r[1] for r in runs], dtype=float))


def _spans_a_boundary(starts: np.ndarray, ends: np.ndarray,
                      origin: float, pitch: float) -> np.ndarray:
    """Whether each [start, end] span crosses a cell boundary.

    Finds the first boundary strictly after each span's start and asks
    whether it lands before the span's end.  The search below evaluates this
    a few hundred times, so doing it in one array operation rather than a
    nested loop is the difference between a snappy Auto Detect and a
    visible pause.

    "Strictly" matters: a boundary exactly on a span's edge touches the
    glyph without dividing it, and counting those as cuts would make the
    search prefer grids that are half a cell out.
    """
    next_edge = origin + (np.floor((starts - origin) / pitch) + 1.0) * pitch
    return next_edge < ends


def _column_quality(runs, origin: float, pitch: float, n_cells: int):
    """Glyph runs that sit wholly inside one column of the grid."""
    starts, ends = runs
    if starts.size == 0:
        return (-1, -1)
    if (origin > starts.min() + 1
            or origin + n_cells * pitch < ends.max() - 1):
        return (-1, -1)
    inside = int(np.count_nonzero(
        ~_spans_a_boundary(starts, ends, origin, pitch)))
    return (inside, 0)


def _grid_quality(bounds, origin: float, pitch: float, n_cells: int):
    """How well a candidate grid suits the text, higher being better.

    Ranked by rows that sit wholly inside one cell, then by how many
    distinct cells the rows occupy.  Uncut comes first deliberately: on a
    capture whose bands are split more finely than its actual rows, chasing
    distinct cells trades many clipped rows for one extra cell and makes
    recognition worse.
    """
    tops = np.array([top for top, _ in bounds], dtype=float)
    bottoms = np.array([bottom for _, bottom in bounds], dtype=float)
    centres = (tops + bottoms) / 2.0
    index = np.floor((centres - origin) / pitch).astype(int)
    if index.min() < 0 or index.max() >= n_cells:
        return (-1, -1)
    uncut = int(np.count_nonzero(
        ~_spans_a_boundary(tops, bottoms, origin, pitch)))
    return (uncut, int(np.unique(index).size))


def _refine_columns(runs, pitch: float, origin: float, n_cells: int):
    """Nudge the column grid so fewer glyphs straddle a boundary.

    The pitch from glyph spacings can be a couple of percent out, which by
    the twenty-fourth column has drifted half a cell and started merging the
    gaps between words.  Scored against the same starting point, so it can
    only improve on it.
    """
    best_score = _column_quality(runs, origin, pitch, n_cells)
    best = (pitch, origin)
    for pitch_delta in np.arange(-0.06, 0.0601, 0.0025):
        candidate_pitch = pitch * (1.0 + pitch_delta)
        if candidate_pitch < 2:
            continue
        for origin_delta in np.arange(-0.55, 0.551, 0.05):
            candidate_origin = origin + candidate_pitch * origin_delta
            score = _column_quality(runs, candidate_origin,
                                    candidate_pitch, n_cells)
            if score > best_score:
                best_score, best = score, (candidate_pitch, candidate_origin)
    return best


def _refine_grid(bounds, pitch: float, origin: float, n_cells: int):
    """Nudge (pitch, origin) to suit the text better.

    The lattice fit gets the pitch about right, but a display that is only
    approximately uniform - a UNS-1, whose title and bottom lines sit off
    the body lattice - can end up with boundaries through its glyphs even so.
    A small search around the estimate finds a placement that cuts fewer
    rows.  It can only improve on the starting point, since that is the
    baseline it is scored against.
    """
    best_score = _grid_quality(bounds, origin, pitch, n_cells)
    best = (pitch, origin)
    for pitch_delta in np.arange(-0.08, 0.0801, 0.005):
        candidate_pitch = pitch * (1.0 + pitch_delta)
        if candidate_pitch < 2:
            continue
        for origin_delta in np.arange(-0.55, 0.551, 0.05):
            candidate_origin = origin + candidate_pitch * origin_delta
            score = _grid_quality(bounds, candidate_origin,
                                  candidate_pitch, n_cells)
            if score > best_score:
                best_score, best = score, (candidate_pitch, candidate_origin)
    return best


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


def _chrome_bottom(image: np.ndarray) -> int:
    """First image row below the window title bar, or 0 when there is none.

    Only a contiguous elevated-background block starting at the very top
    counts: that is what a title bar is.  Bright content elsewhere on the
    screen must not be mistaken for chrome.
    """
    gray = np.max(image, axis=2) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    kernel = max(5, (min(height, width) // 20) | 1)
    background = cv2.medianBlur(gray, kernel)
    dominant = float(np.median(background))
    elevated = np.median(background, axis=1) > dominant + 40

    if not elevated[:3].any():
        return 0
    bottom = 0
    for row_is_chrome in elevated:
        if not row_is_chrome:
            break
        bottom += 1
    return bottom


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
    row_bounds = _split_touching_rows(row_bounds, mask.sum(axis=1))
    row_bounds = _drop_chrome_remnants(row_bounds, _chrome_bottom(image))
    if len(row_bounds) < 2:
        return None

    row_centers = [(top + bottom) / 2.0 for top, bottom in row_bounds]
    row_gaps = np.diff(np.asarray(row_centers, float))
    row_pitch = _pitch_from_spacings(row_gaps)
    if row_pitch is None:
        return None

    # Two candidate pitches, judged by the only thing that matters: how many
    # text rows end up wholly inside a cell.  Picking by a fixed rule instead
    # meant every display that suited one estimator broke the other; this
    # decides per capture and cannot regress one that already works.
    alternative = _pitch_by_total_span(row_gaps, float(np.median(row_gaps)))
    if alternative is not None and abs(alternative - row_pitch) > 0.5:
        best_pitch, best_score = row_pitch, -1
        for candidate in (row_pitch, alternative):
            centers, refined = _fit_lattice(row_centers, candidate)
            origin = _choose_origin(centers, refined, rows,
                                    row_bounds[0][0], row_bounds[-1][1] + 1)
            score = _rows_uncut(row_bounds, origin, refined, rows)
            if score > best_score:
                best_pitch, best_score = candidate, score
        row_pitch = best_pitch

    row_centers, row_pitch = _fit_lattice(row_centers, row_pitch)

    per_row = _glyph_centers_per_row(mask, row_bounds)
    if not per_row:
        return None
    spacings = np.concatenate([np.diff(np.asarray(c, float)) for c in per_row])
    col_pitch = _pitch_from_spacings(spacings)
    if col_pitch is None:
        return None
    col_pitch = _refine_pitch_over_baselines(per_row, col_pitch)
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

    # The screen often sits flush under the title bar, and the lattice can
    # legitimately place row 0's top a few pixels inside the chrome - the
    # glyphs are top-aligned in their cells, so the phase allows it.  Those
    # pixels are bright, and once inside the crop they ink the top of every
    # column: on an ATR capture the whole first row read as occupied.  Trim
    # the crop to the chrome boundary when the trim is a small fraction of a
    # cell; a larger overlap means the fit is wrong, and trimming would only
    # disguise it.
    # Nudge the column grid so fewer glyphs straddle a boundary.
    runs = _glyph_runs(mask, row_bounds)
    col_pitch, refined_x = _refine_columns(runs, col_pitch, float(x), columns)
    x = max(0, int(round(refined_x)))

    # Nudge the row grid to cut through fewer glyphs before clamping.
    row_pitch, refined_y = _refine_grid(row_bounds, row_pitch, float(y), rows)
    y = max(0, int(round(refined_y)))

    chrome = _chrome_bottom(image)
    if y < chrome and (chrome - y) <= row_pitch * 0.35:
        y = chrome

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
