"""
Getting a whole character out of a cell that does not quite contain it.

The parser lays a uniform lattice over the display and reads one character
per cell.  Measured against the captures in tests/data, that lattice is a
good model of the hardware: the pitch is accurate to better than half a per
cent on every one of them, and re-fitting the phase row by row would move
almost no character into a different column.  So the grid puts characters in
the right cells.

What it does not always do is *contain* them.  The fraction of glyphs whose
body crosses a column edge runs from nothing on the ATR and the Fokker,
through 8% on the A330, to 40% on the Avro GNLU and the Just Flight UNS-1.
Those last two are not fixed-pitch displays at all - their glyph positions
scatter around the lattice by a sixth of a cell, and because the scatter is
not a drift, no pitch or origin correction removes it.

Cutting at the lattice there hands the matcher two half-characters and it
can name neither.  So recognition sees a window wider than the cell, with
the ink that belongs to the cell kept whole.
"""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from mcdu_detector import detect_mcdu_region
from mcdu_parser import MCDUParser

DATA = Path(__file__).parent / "data"
CELL_W, CELL_H = 20, 24


def blank_page():
    return np.zeros((CELL_H * 14, CELL_W * 24, 3), dtype=np.uint8)


def draw_bar(image, col, row, shift=0.0, width=8, height=14):
    """A solid glyph in cell (row, col), shifted by *shift* of a cell."""
    x = int(col * CELL_W + (CELL_W - width) / 2 + shift * CELL_W)
    y = int(row * CELL_H + (CELL_H - height) / 2)
    image[y:y + height, x:x + width] = 220
    return x, x + width


def ink_span(binary):
    coords = cv2.findNonZero(binary)
    if coords is None:
        return None
    x, _, w, _ = cv2.boundingRect(coords)
    return x, w


class TestGlyphIsRecoveredWhole(unittest.TestCase):

    def test_a_centred_glyph_is_unaffected(self):
        """The common case must not change."""
        image = blank_page()
        draw_bar(image, col=5, row=2)
        parser = MCDUParser(image, source_id="centred")
        plain = parser._preprocess_cell(parser.extract_cell(2, 5))
        whole = parser.cell_binary(2, 5)
        self.assertEqual(int((plain > 0).sum()), int((whole > 0).sum()),
                         "a glyph sitting inside its cell was altered")

    def test_a_glyph_that_overruns_its_cell_comes_back_whole(self):
        image = blank_page()
        left, right = draw_bar(image, col=5, row=2, shift=0.4)
        parser = MCDUParser(image, source_id="shifted")

        plain = parser._preprocess_cell(parser.extract_cell(2, 5))
        span = ink_span(plain)
        self.assertIsNotNone(span, "test setup: no ink in the cell")
        self.assertLess(span[1], right - left,
                        "test setup: the lattice did not clip this glyph")

        whole = parser.cell_binary(2, 5)
        self.assertEqual(ink_span(whole)[1], right - left,
                         "the overrunning part of the glyph was not recovered")

    def test_the_neighbour_is_not_dragged_in(self):
        """A wider window sees the next character too; it must not keep it."""
        image = blank_page()
        draw_bar(image, col=5, row=2)
        draw_bar(image, col=6, row=2)
        parser = MCDUParser(image, source_id="pair")
        whole = parser.cell_binary(2, 5)
        # One glyph's worth of ink, not two.
        self.assertLessEqual(ink_span(whole)[1], CELL_W,
                             "the neighbouring glyph came along")

    def test_touching_glyphs_still_give_one_character_each(self):
        """Splitting matters more than keeping them whole.

        Two characters that share ink are one component.  Handing the whole
        component to whichever cell its centre lands in would empty the
        other cell, losing a character outright - worse than the clipping
        this is meant to fix.  They are cut apart instead.
        """
        image = blank_page()
        draw_bar(image, col=5, row=2, width=18)
        draw_bar(image, col=6, row=2, width=18)
        parser = MCDUParser(image, source_id="touching")
        for col in (5, 6):
            binary = parser.cell_binary(2, col)
            self.assertIsNotNone(ink_span(binary),
                                 f"cell {col} lost its character entirely")

    def test_an_empty_cell_stays_empty(self):
        image = blank_page()
        draw_bar(image, col=5, row=2)
        parser = MCDUParser(image, source_id="empty")
        self.assertTrue(parser.is_empty_cell(parser.extract_cell(2, 9)))
        self.assertFalse(parser.cell_binary(2, 9).any(),
                         "ink appeared in a cell that has none")


class TestRealCapturesAreNotClipped(unittest.TestCase):
    """On the captures the project has, no glyph reaches the window edge."""

    CAPTURES = [("mcdu_real_capture.png", 24, 14),
                ("atr_mcdu_screenshot (2).png", 24, 14),
                ("jf-f70-f100-fcu.png", 24, 14)]

    def test_no_glyph_is_cut_by_the_grid(self):
        from PIL import Image
        for name, columns, rows in self.CAPTURES:
            path = DATA / name
            if not path.exists():
                continue
            image = np.array(Image.open(path).convert("RGB"))
            found = detect_mcdu_region(image, columns=columns, rows=rows)
            self.assertIsNotNone(found, f"{name}: nothing detected")
            x, y, w, h = found
            x, y = max(0, x), max(0, y)
            crop = image[y:y + min(h, image.shape[0] - y),
                         x:x + min(w, image.shape[1] - x)]
            parser = MCDUParser(crop, columns=columns, rows=rows,
                                source_id=name)
            clipped = []
            for row in range(rows):
                for col in range(columns):
                    cell = parser.extract_cell(row, col)
                    if cell.size == 0 or parser.is_empty_cell(cell):
                        continue
                    binary = parser.cell_binary(row, col)
                    span = ink_span(binary)
                    if span is None:
                        continue
                    if span[0] == 0 or span[0] + span[1] >= binary.shape[1]:
                        clipped.append(f"R{row:02d}C{col:02d}")
            self.assertLessEqual(
                len(clipped), 2,
                f"{name}: {len(clipped)} glyphs reach the window edge: "
                f"{clipped[:8]}",
            )


if __name__ == "__main__":
    unittest.main()
