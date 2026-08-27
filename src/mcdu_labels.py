"""
MCDU label dictionary — post-OCR correction for known fixed text.

MCDU pages have fixed labels on the small-font rows (odd rows 1, 3, 5, …, 11)
that never change for a given page type.  The page type is identified from the
title row (row 0, large font, usually read accurately), and then the known
label text is used to correct OCR errors on the label rows.

Correction rules are deliberately conservative:

  * A cell is only replaced when (a) the known label has a character there,
    (b) the OCR also produced a character there, and (c) they disagree.
  * Empty cells are never filled — the OCR may be right that the cell is
    blank due to page scrolling or variant behaviour.
  * Cells the label expects to be blank are never cleared.
  * A label is only applied when at least ``MIN_MATCH_RATIO`` of its
    non-space characters already agree with the OCR output, preventing
    false matches from corrupting a genuinely different page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Label entry: one fixed text fragment at a known column position
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Label:
    """A known fixed-text fragment on a label row.

    Attributes:
        col: 0-based column where the label starts.
        text: The known characters (may contain spaces for internal gaps).
    """
    col: int
    text: str


@dataclass(frozen=True)
class PageLayout:
    """A known MCDU page type with its fixed labels.

    Attributes:
        title: The expected text on row 0 (stripped of leading/trailing
            spaces).  Matched fuzzily against the OCR'd title row.
        labels: Mapping from row index to a list of label fragments on
            that row.  Only odd rows (label rows) should be specified.
    """
    title: str
    labels: Dict[int, List[Label]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
#  Airbus MCDU page database
# ---------------------------------------------------------------------------
#  Sources: A320 FCOM, real captures, and the user's log output.
#  Only the most common pages are listed.  A page missing from this
#  database simply gets no label correction — it does not break anything.

_AIRBUS_PAGES: List[PageLayout] = [
    # ── INIT A ──
    PageLayout(
        title="INIT",
        labels={
            1:  [Label(1, "CO RTE"), Label(16, "FROM/TO")],
            3:  [Label(0, "ALTN/CO RTE")],
            5:  [Label(0, "FLT NBR")],
            7:  [],  # empty label row
            9:  [Label(0, "COST INDEX")],
            11: [Label(0, "CRZ FL/TEMP"), Label(15, "TROPO")],
        },
    ),
    # ── INIT B ──
    PageLayout(
        title="INIT",
        labels={
            1:  [Label(2, "ENG")],
            3:  [Label(2, "ACTIVE NAV DATA BASE")],
            5:  [Label(2, "SECOND NAV DATA BASE")],
            7:  [],
            9:  [Label(0, "CHG CODE")],
            11: [Label(0, "IDLE/PERF"), Label(15, "SOFTWARE")],
        },
    ),
    # ── F-PLN ──
    PageLayout(
        title="F-PLN",
        labels={
            1:  [Label(5, "UTC"), Label(11, "SPD/ALT")],
        },
    ),
    # ── PERF CLB ──
    PageLayout(
        title="CLB",
        labels={
            1:  [Label(0, "ACT MODE")],
            3:  [Label(0, "CI")],
            5:  [Label(0, "DERATED CLB")],
            7:  [Label(0, "TRANS ALT")],
            9:  [Label(0, "SEL SPD")],
        },
    ),
    # ── PERF CRZ ──
    PageLayout(
        title="CRZ",
        labels={
            1:  [Label(0, "ACT MODE")],
            3:  [Label(0, "CI")],
            7:  [Label(0, "DES CABIN RATE")],
            9:  [Label(0, "SEL SPD")],
        },
    ),
    # ── PERF DES ──
    PageLayout(
        title="DES",
        labels={
            1:  [Label(0, "ACT MODE")],
            3:  [Label(0, "CI")],
            5:  [Label(0, "DES SPD")],
            7:  [Label(0, "TRANS ALT")],
            9:  [Label(0, "SEL SPD")],
        },
    ),
    # ── PERF APPR ──
    PageLayout(
        title="APPR",
        labels={
            1:  [Label(0, "QNH")],
            3:  [Label(0, "TEMP"), Label(12, "MAG WIND")],
            5:  [Label(0, "TRANS ALT")],
            7:  [Label(0, "VAPP"), Label(12, "LDG CONF")],
            9:  [Label(0, "FINAL")],
        },
    ),
    # ── IDENT (A31x / A32x / A33x / A34x / A38x) ──
    PageLayout(
        title="A31",
        labels={
            1:  [Label(1, "ENG")],
            3:  [Label(1, "ACTIVE NAV DATA BASE")],
            5:  [Label(1, "SECOND NAV DATA BASE")],
            9:  [Label(0, "CHG CODE")],
            11: [Label(0, "IDLE/PERF"), Label(15, "SOFTWARE")],
            13: [Label(0, "NAV ACCUR"), Label(10, "DOWNGRADED")],
        },
    ),
    PageLayout(
        title="A32",
        labels={
            1:  [Label(1, "ENG")],
            3:  [Label(1, "ACTIVE NAV DATA BASE")],
            5:  [Label(1, "SECOND NAV DATA BASE")],
            9:  [Label(0, "CHG CODE")],
            11: [Label(0, "IDLE/PERF"), Label(15, "SOFTWARE")],
            13: [Label(0, "NAV ACCUR"), Label(10, "DOWNGRADED")],
        },
    ),
    PageLayout(
        title="A33",
        labels={
            1:  [Label(1, "ENG")],
            3:  [Label(1, "ACTIVE NAV DATA BASE")],
            5:  [Label(1, "SECOND NAV DATA BASE")],
            9:  [Label(0, "CHG CODE")],
            11: [Label(0, "IDLE/PERF"), Label(15, "SOFTWARE")],
            13: [Label(0, "NAV ACCUR"), Label(10, "DOWNGRADED")],
        },
    ),
    PageLayout(
        title="A34",
        labels={
            1:  [Label(1, "ENG")],
            3:  [Label(1, "ACTIVE NAV DATA BASE")],
            5:  [Label(1, "SECOND NAV DATA BASE")],
            9:  [Label(0, "CHG CODE")],
            11: [Label(0, "IDLE/PERF"), Label(15, "SOFTWARE")],
            13: [Label(0, "NAV ACCUR"), Label(10, "DOWNGRADED")],
        },
    ),
    PageLayout(
        title="A38",
        labels={
            1:  [Label(1, "ENG")],
            3:  [Label(1, "ACTIVE NAV DATA BASE")],
            5:  [Label(1, "SECOND NAV DATA BASE")],
            9:  [Label(0, "CHG CODE")],
            11: [Label(0, "IDLE/PERF"), Label(15, "SOFTWARE")],
            13: [Label(0, "NAV ACCUR"), Label(10, "DOWNGRADED")],
        },
    ),
    # ── PROG ──
    PageLayout(
        title="PROG",
        labels={
            1:  [Label(0, "CRZ")],
            3:  [Label(0, "OPT"), Label(12, "REC MAX")],
            5:  [Label(0, "PRED TO")],
            9:  [Label(0, "BRG/DIST")],
            11: [Label(0, "PRED GPS")],
        },
    ),
    # ── FUEL PRED ──
    PageLayout(
        title="FUEL PRED",
        labels={
            1:  [Label(0, "AT")],
            3:  [Label(0, "EXTRA")],
        },
    ),
    # ── DIR TO ──
    PageLayout(
        title="DIR TO",
        labels={
            1:  [Label(0, "WAYPOINT")],
            9:  [Label(0, "ABEAM PTS")],
            11: [Label(0, "RADIAL IN")],
        },
    ),
    # ── RAD NAV ──
    PageLayout(
        title="RAD NAV",
        labels={
            1:  [Label(0, "VOR1/FREQ"), Label(12, "FREQ/VOR2")],
            3:  [Label(0, "CRS")],
            5:  [Label(0, "ILS/FREQ")],
            7:  [Label(0, "CRS")],
            9:  [Label(0, "ADF1/FREQ"), Label(12, "FREQ/ADF2")],
        },
    ),
    # ── DATA (A) INDEX ──
    PageLayout(
        title="DATA",
        labels={},
    ),
    # ── MCDU MENU ──
    PageLayout(
        title="MCDU MENU",
        labels={},
    ),
]


# ---------------------------------------------------------------------------
#  Fuzzy title matching
# ---------------------------------------------------------------------------

def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _extract_title(message_data: list, columns: int) -> str:
    """Extract the title text from row 0, stripped of whitespace."""
    chars = []
    for col in range(columns):
        cell = message_data[col] if col < len(message_data) else []
        chars.append(cell[0] if cell else " ")
    return "".join(chars).strip()


#: Maximum edit-distance ratio to accept a title match.
#: 0.30 means up to 30% of characters can be wrong.
_MAX_TITLE_DISTANCE_RATIO = 0.30

#: Minimum fraction of a label's non-space characters that must already
#: agree with the OCR output before the label is applied.
MIN_MATCH_RATIO = 0.60


def _find_matching_pages(title: str) -> List[PageLayout]:
    """Return all page layouts whose title fuzzily matches *title*."""
    if not title:
        return []
    matches = []
    for page in _AIRBUS_PAGES:
        if not page.title:
            continue
        # The title row often contains more than just the page name
        # (e.g. "      INIT        67" or "       CLB              ").
        # Check if the known title appears as a substring.
        if page.title in title:
            matches.append(page)
            continue
        # Fallback: edit-distance on the whole stripped title
        dist = _edit_distance(title, page.title)
        max_dist = max(1, int(len(page.title) * _MAX_TITLE_DISTANCE_RATIO))
        if dist <= max_dist:
            matches.append(page)
    return matches


# ---------------------------------------------------------------------------
#  Label correction
# ---------------------------------------------------------------------------

def _apply_label(message_data: list, columns: int,
                 row: int, label: Label) -> int:
    """Correct one label fragment in-place.  Returns the number of fixes."""
    base = row * columns
    fixes = 0
    # Count how many non-space characters already match
    total_chars = 0
    matching_chars = 0
    for i, expected_ch in enumerate(label.text):
        col = label.col + i
        if col >= columns:
            break
        if expected_ch == " ":
            continue
        total_chars += 1
        idx = base + col
        cell = message_data[idx] if idx < len(message_data) else []
        if cell and cell[0] == expected_ch:
            matching_chars += 1

    # Only apply if enough characters already match
    if total_chars == 0:
        return 0
    if matching_chars / total_chars < MIN_MATCH_RATIO:
        return 0

    # Apply corrections
    for i, expected_ch in enumerate(label.text):
        col = label.col + i
        if col >= columns:
            break
        if expected_ch == " ":
            # Never clear a cell — it might contain data on a variant page
            continue
        idx = base + col
        if idx >= len(message_data):
            break
        cell = message_data[idx]
        if not cell:
            # OCR says empty — don't insert.  The page might be scrolled
            # or the glyph might genuinely be missing.
            continue
        if cell[0] != expected_ch:
            cell[0] = expected_ch
            fixes += 1

    return fixes


def apply_label_corrections(message_data: list, columns: int,
                            rows: int,
                            small_font_rule: str = "labels_small") -> int:
    """Post-correct known fixed labels in the parsed grid.

    Only operates on Airbus style pages.
    Returns the total number of characters corrected.

    Args:
        message_data: The parsed grid (modified in place).
        columns: Grid width.
        rows: Grid height.
        small_font_rule: The profile's font-size convention.
    """
    if small_font_rule not in ("labels_small", "AirbusThales"):
        return 0
    if len(message_data) < columns * min(rows, 2):
        return 0

    title = _extract_title(message_data, columns)
    pages = _find_matching_pages(title)
    if not pages:
        return 0

    total_fixes = 0

    # Try each matching page layout and pick the one that matches the best
    # (highest number of already-correct characters).
    best_match_count = -1
    best_page = None
    for page in pages:
        match_count = 0
        for row, labels in page.labels.items():
            if row >= rows:
                continue
            for label in labels:
                base = row * columns
                for i, ch in enumerate(label.text):
                    col = label.col + i
                    if col >= columns or ch == " ":
                        continue
                    idx = base + col
                    cell = message_data[idx] if idx < len(message_data) else []
                    if cell and cell[0] == ch:
                        match_count += 1
        if match_count > best_match_count:
            best_match_count = match_count
            best_page = page

    if best_page is None:
        return 0

    for row, labels in best_page.labels.items():
        if row >= rows:
            continue
        for label in labels:
            fixes = _apply_label(message_data, columns, row, label)
            total_fixes += fixes

    if total_fixes > 0:
        logger.debug(
            "Label dictionary corrected %d characters on '%s' page",
            total_fixes, best_page.title,
        )

    return total_fixes
