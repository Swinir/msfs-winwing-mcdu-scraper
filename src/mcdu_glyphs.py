"""
Naming a glyph by its shape alone.

An MCDU page is mostly punctuation and entry boxes, and those are exactly
the characters an OCR engine has the least to go on for: a CRNN is trained
on words, has no box in its alphabet at all, and reads a dash, a slash or a
chevron as whichever letter comes nearest.  Their shapes, on the other
hand, are unmistakable, so they are decided here instead - ahead of both
the template matcher and EasyOCR.

Two kinds of test live in this module and they are not interchangeable:

* :func:`is_entry_box` and the detectors behind :data:`GEOMETRY_OWNED` are
  trusted to have the last word.  Scored over 2831 labelled glyphs from the
  real captures and the rendered pages, they name every one of those
  characters that is present and claim no letter, so a proposal of one of
  them that they did not make is contradicted by the pixels.

* :func:`_disambiguate_confusables` is a rule of thumb about stroke shape.
  It breaks ties EasyOCR cannot, and it is applied *only* to what EasyOCR
  proposed - never to a template match, which is evidence from the pixels
  of a glyph that already won a consensus.  Applying it more widely than
  that has cost accuracy every time it has been tried (ISSUES.md #5, #25).

Every threshold here is measured against tests/data before it is kept, and
tests/test_geometry_recognition.py scores the lot.
"""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from mcdu_charset import BALLOT_BOX

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Entry boxes
# ---------------------------------------------------------------------------
#  An Airbus CDU marks every field the crew must fill in with a hollow
#  rectangle, and a cold-start page is mostly made of them: INIT A alone
#  shows 22.  Neither EasyOCR nor the template matcher can name that glyph -
#  a CRNN has no box in its alphabet and picks whichever letter is closest,
#  which a real capture showed reading as "CS S  S S I" and " SSSSSSSI".
#  Worse, those wrong letters were then learned as templates, so the error
#  spread to genuine text.
#
#  The shape is unmistakable, though: ink all the way round the border and
#  none at all inside.  No letter does that - O and D curve away from their
#  corners, so their top and bottom rows do not span the full width.  So it
#  is recognised structurally, ahead of both engines, and cells that match
#  are never offered to the template learner.


#: The characters the geometry pass is trusted to have the last word on.
#: It runs over every cell that has ink, and on the 2831-glyph corpus it
#: named all of these that were present and claimed nothing else - so when
#: it has not named a cell, the cell is not one of these shapes, and any
#: other engine proposing one is contradicted by the pixels rather than
#: merely unconfirmed.
#:
#: The arrows are deliberately absent.  The detector does read them, but
#: the corpus holds a single left arrow and no right one - enough to
#: recognise a shape, nowhere near enough to overrule someone else about
#: it.  On the UNS-1's reverse-video ACCEPT prompt the rule does not fire,
#: and vetoing on that silence deleted an arrow a template had read
#: correctly.
GEOMETRY_OWNED = frozenset(
    [".", ":", "-", "/", "<", ">", "[", "]", "°", BALLOT_BOX]
)

#: Round brackets are deliberately absent, though the CDU draws them as
#: square ones (see SUBSTITUTIONS).  Folding them in caught a few C that
#: EasyOCR had proposed as "(" - and deleted the real parentheses of the
#: ATR's "GPS (UTC)", because a round bracket has no arms and the
#: bracket rule rightly does not fire on one.  The veto only covers
#: shapes the pass actually finds.


def vetoable(char: Optional[str]) -> bool:
    """True when *char* names a shape the geometry pass would have found."""
    return bool(char) and char in GEOMETRY_OWNED


def is_entry_box(binary: np.ndarray, cell_h: int, cell_w: int) -> bool:
    """True when *binary* holds a hollow rectangle rather than a character.

    Args:
        binary: One preprocessed cell, ink as 255.
        cell_h: Height of the cell the glyph came from.
        cell_w: Width of the cell the glyph came from.
    """
    coords = cv2.findNonZero(binary)
    if coords is None:
        return False
    x, y, w, h = cv2.boundingRect(coords)

    # Big enough to be a box rather than a dash, dot or degree sign, and
    # roughly as tall as it is wide.  A real box fills a little over half
    # the cell each way.
    if h < max(4, cell_h * 0.28) or w < max(4, cell_w * 0.28):
        return False
    if not 0.35 <= w / h <= 1.9:
        return False

    glyph = binary[y:y + h, x:x + w]
    band = lambda a: float(np.count_nonzero(a)) / max(a.size, 1)
    edge_h = max(1, h // 8)
    edge_w = max(1, w // 8)

    # Every border must be continuous: measured per row/column rather than
    # as a fill ratio, so a two-pixel stroke in an eight-pixel band still
    # scores 1.0.
    top = float(np.count_nonzero(glyph[:edge_h].any(axis=0))) / w
    bottom = float(np.count_nonzero(glyph[-edge_h:].any(axis=0))) / w
    left = float(np.count_nonzero(glyph[:, :edge_w].any(axis=1))) / h
    right = float(np.count_nonzero(glyph[:, -edge_w:].any(axis=1))) / h
    if min(top, bottom, left, right) < 0.80:
        return False

    # ...and the middle must be empty.  This is what rejects 0, 8, B and D,
    # every one of which puts ink through the centre of the glyph.
    inner = glyph[h // 4:h - h // 4, w // 4:w - w // 4]
    return inner.size > 0 and band(inner) <= 0.12


# ---------------------------------------------------------------------------
#  Structural disambiguation for commonly confused character pairs
# ---------------------------------------------------------------------------

def _disambiguate_confusables(cell_binary: np.ndarray, char: str) -> str:
    """Correct EasyOCR / template confusions using glyph geometry.

    EasyOCR confuses D/O, A/B, B/8 and I// because at cell resolution
    those glyphs share an outline.  Each test below looks at the one
    structural feature that actually separates the pair.

    Every rule here is measured against the real captures before it is
    kept.  Tests for N/H and S/5 used to sit below these, unreachable
    because the guard above never listed those characters; making them
    reachable turned 18 correct N into H and 12 correct S into 5, so they
    were deleted rather than repaired.

    Applied only to characters EasyOCR proposed.  It is deliberately not
    applied to template matches or to learned labels: a template already
    is evidence from these pixels, and letting a heuristic relabel it on
    the way into the store made every later frame worse.

    A ']' vs '1' test used to live here too and was removed - measured
    against the real captures it corrupted six genuine '1's to buy one
    repair, and the contour detector already tells brackets apart by
    their arms.
    """
    if char not in ('D', 'O', '0', 'A', 'B', '8', 'I', '/'):
        return char

    coords = cv2.findNonZero(cell_binary)
    if coords is None:
        return char
    x, y, bw, bh = cv2.boundingRect(coords)
    if bw < 3 or bh < 3:
        return char
    glyph = cell_binary[y : y + bh, x : x + bw]
    h, w = glyph.shape

    # ------------------------------------------------------------------
    #  D vs O  (and 0)
    # ------------------------------------------------------------------
    if char in ('D', 'O', '0'):
        # D has square corners on the left and a stem that runs the whole
        # height; O and 0 curve away from both left corners.  Thresholds
        # measured over 340 D/O/0 glyphs from the real captures and the
        # rendered pages: 87 of 87 D correct, 1 of 253 O/0 misread.  The
        # previous test (left-strip fill alone) turned real O and 0 into D
        # on eight of the real capture's glyphs.
        left_cols = max(2, w // 6)
        left_rows = np.any(glyph[:, :left_cols] > 0, axis=1)
        left_continuity = float(np.count_nonzero(left_rows)) / h
        corner = max(1, min(w, h) // 4)
        fill = lambda a: float(np.count_nonzero(a)) / max(a.size, 1)
        top_left = fill(glyph[:corner, :corner])
        bottom_left = fill(glyph[-corner:, :corner])

        if min(top_left, bottom_left) >= 0.60 and left_continuity >= 0.94:
            return 'D'
        if char == 'D':
            return 'O'
        # An O or a 0 without square corners is left as OCR read it: the
        # two are told apart by context, not by shape.

    # ------------------------------------------------------------------
    #  A vs B vs 8
    # ------------------------------------------------------------------
    if char in ('A', 'B', '8'):
        # A B is built on a stem: ink in its left-hand columns on every row
        # from top to bottom.  An A's left side is a diagonal, so it reaches
        # the left edge only near the foot.  Over 60 A and 23 B drawn by
        # five different displays, A never gets past 0.92 of the height and
        # B is at 1.00 every single time.
        #
        # Two earlier tests failed here.  Comparing the top quarter's span
        # against the bottom quarter's overlaps outright.  Using the top
        # span alone looked clean until the Avro was included - its A has a
        # flat top and reaches 1.00, indistinguishable from a B that way.
        # The stem is what actually differs.
        left_cols = max(2, w // 5)
        strip = glyph[:, :left_cols]
        continuity = float(np.count_nonzero(np.any(strip > 0, axis=1))) / h
        fill = float(np.count_nonzero(strip)) / max(strip.size, 1)

        if continuity < 0.96:
            # No stem, so not a B.  An 8 can also fall here, so a reading of
            # 8 is left alone rather than rewritten.
            if char != '8':
                return 'A'
        else:
            # A full-height stem: B or 8, never A.
            if char == 'A':
                char = 'B'
            # The two overlap in the middle of the fill range, so only the
            # unmistakable cases are rewritten and the rest stand as read -
            # _correct_row_context already separates letters from digits by
            # the token they sit in.
            if fill >= 0.90:
                return 'B'
            if fill <= 0.55:
                return '8'
            return char

    # ------------------------------------------------------------------
    #  I vs / (and 1)
    # ------------------------------------------------------------------
    if char in ('I', '/'):
        # / has a strong diagonal: top-right ink, bottom-left ink.
        # I is vertically symmetric: ink centred on every row.
        if h > 3 and w > 3:
            tr = np.count_nonzero(glyph[: h // 2, w // 2 :])
            bl = np.count_nonzero(glyph[h // 2 :, : w // 2])
            tl = np.count_nonzero(glyph[: h // 2, : w // 2])
            br = np.count_nonzero(glyph[h // 2 :, w // 2 :])
            diag_score = (tr + bl) / max(tl + br + 1, 1)
            if diag_score > 2.0:
                return '/'
            else:
                return 'I'

    return char
