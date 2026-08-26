"""
Reverse video (ISSUES.md #17).

MobiFlight's display protocol takes an optional fourth element per cell,
``[char, colour, size, inverted]``, which the CDU renders as reverse video.
The MCDU uses it for scratchpad messages and the UNS-1 for its ACCEPT
prompt — visible as a white block with dark text in tests/data/uns1_wt.png.

Detection is by fill: a reverse-video cell is mostly at foreground
brightness, where an ordinary one is mostly background. Measured across 929
cells from six real captures, ordinary cells reach at most 40.9% fill and
inverted ones start at 47.8%.
"""

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import mcdu_parser
from mcdu_detector import detect_mcdu_region
from mcdu_parser import MCDUParser, TemplateMatcher
from mobiflight_client import sanitise_display_data
from pipeline import DisplayStabiliser, pad_to_hardware

DATA = Path(__file__).parent / "data"

#: Captures with no reverse video anywhere, and how to crop them.
PLAIN = (
    ("mcdu_real_capture.png", 24, 14, None, "labels_small"),
    ("atr_mcdu_screenshot (1).png", 24, 14, None, "labels_small"),
    ("atr_mcdu_screenshot (2).png", 24, 14, None, "labels_small"),
    ("jf-avro-fcu.png", 25, 14, None, "labels_small"),
)

#: Both UNS-1 captures show <-ACCEPT in reverse video across columns 0-6.
INVERTED = (
    ("uns1_wt.png", (53, 51, 504, 322)),
    ("uns1_jf_bae146.png", (0, 56, 388, 283)),
)
ACCEPT_ROW = 10
ACCEPT_COLUMNS = tuple(range(7))

WT_ROW10 = "←ACCEPT FMC VER  WT2.2.3"


def load(name):
    from PIL import Image
    return np.array(Image.open(DATA / name).convert("RGB"))


def parser_for(name, columns, rows, crop, rule):
    image = load(name)
    if crop is None:
        found = detect_mcdu_region(image, columns=columns, rows=rows)
        x, y, w, h = found
        x, y = max(0, x), max(0, y)
        w = min(w, image.shape[1] - x)
        h = min(h, image.shape[0] - y)
    else:
        x, y, w, h = crop
    return MCDUParser(image[y:y + h, x:x + w], columns=columns, rows=rows,
                      source_id=name[:6], small_font_rule=rule)


def inverted_cells(parser, columns, rows):
    return [(r, c) for r in range(rows) for c in range(columns)
            if not parser.is_empty_cell(parser.extract_cell(r, c))
            and parser.is_inverted_cell(parser.extract_cell(r, c))]


@unittest.skipIf(not (DATA / "uns1_wt.png").exists(), "captures missing")
class TestInversionDetection(unittest.TestCase):

    def test_accept_prompt_is_detected_on_both_uns1(self):
        for name, crop in INVERTED:
            parser = parser_for(name, 24, 11, crop, "all_large")
            found = inverted_cells(parser, 24, 11)
            self.assertEqual(
                found, [(ACCEPT_ROW, c) for c in ACCEPT_COLUMNS],
                f"{name}: expected the ACCEPT block, got {found}",
            )

    def test_no_false_positives_on_ordinary_displays(self):
        """929 cells across four captures, none of them reverse video."""
        for name, columns, rows, crop, rule in PLAIN:
            if not (DATA / name).exists():
                continue
            parser = parser_for(name, columns, rows, crop, rule)
            self.assertEqual(inverted_cells(parser, columns, rows), [],
                             f"{name}: reported reverse video where none exists")

    def test_empty_cells_are_never_inverted(self):
        parser = parser_for("uns1_wt.png", 24, 11, INVERTED[0][1], "all_large")
        for r in range(11):
            for c in range(24):
                cell = parser.extract_cell(r, c)
                if parser.is_empty_cell(cell):
                    self.assertFalse(parser.is_inverted_cell(cell),
                                     f"R{r}C{c} is empty but read as inverted")

    def test_threshold_has_margin_on_this_data(self):
        """Guard the measurement the threshold was chosen from."""
        highest_plain, lowest_inverted = 0.0, 1.0
        for name, columns, rows, crop, rule in PLAIN:
            if not (DATA / name).exists():
                continue
            parser = parser_for(name, columns, rows, crop, rule)
            for r in range(rows):
                for c in range(columns):
                    cell = parser.extract_cell(r, c)
                    if parser.is_empty_cell(cell):
                        continue
                    fill = float(np.mean(np.max(cell, axis=2) > parser._mid_level))
                    highest_plain = max(highest_plain, fill)
        for name, crop in INVERTED:
            parser = parser_for(name, 24, 11, crop, "all_large")
            for c in ACCEPT_COLUMNS:
                cell = parser.extract_cell(ACCEPT_ROW, c)
                fill = float(np.mean(np.max(cell, axis=2) > parser._mid_level))
                lowest_inverted = min(lowest_inverted, fill)
        self.assertLess(highest_plain, MCDUParser.INVERTED_FILL_RATIO,
                        f"an ordinary cell reaches {highest_plain:.1%}")
        self.assertGreater(lowest_inverted, MCDUParser.INVERTED_FILL_RATIO,
                           f"an inverted cell is only {lowest_inverted:.1%}")


@unittest.skipIf(not (DATA / "uns1_wt.png").exists(), "captures missing")
class TestInvertedGlyphsAreReadable(unittest.TestCase):
    """A flipped cell must match the same template as its normal twin."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "rv.npz")
        mcdu_parser._template_matcher = self.matcher

        image = load("uns1_wt.png")
        x, y, w, h = INVERTED[0][1]
        self.crop = image[y:y + h, x:x + w]
        parser = MCDUParser(self.crop, columns=24, rows=11,
                            source_id="teach", small_font_rule="all_large")
        for col, char in enumerate(WT_ROW10):
            if char == " ":
                continue
            binary = parser._preprocess_cell(parser.extract_cell(10, col))
            self.matcher.learn(char, binary, confidence=1.0)
            self.matcher.learn(char, binary, confidence=1.0)

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _row10(self):
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        grid = MCDUParser(self.crop, columns=24, rows=11, source_id="read",
                          small_font_rule="all_large").parse_grid()
        return sanitise_display_data(grid)[10 * 24:11 * 24]

    def test_the_whole_row_reads_back(self):
        text = "".join(c[0] if c else " " for c in self._row10())
        self.assertEqual(text, WT_ROW10)

    def test_flag_is_set_exactly_on_the_block(self):
        row = self._row10()
        flagged = [c for c in range(24) if len(row[c]) > 3 and row[c][3]]
        self.assertEqual(flagged, list(ACCEPT_COLUMNS))

    def test_ordinary_cells_stay_three_elements(self):
        """Backwards compatible: the fourth element is sent only when set."""
        row = self._row10()
        for c in range(24):
            if row[c] and c not in ACCEPT_COLUMNS:
                self.assertEqual(len(row[c]), 3,
                                 f"C{c:02d} gained a fourth element")

    def test_block_colour_is_the_background_not_the_glyph(self):
        """Reverse video colours the block; the glyph is punched out of it."""
        row = self._row10()
        for c in ACCEPT_COLUMNS:
            self.assertEqual(row[c][1], "w",
                             f"C{c:02d} should carry the block's colour")


class TestFourElementCellsSurviveThePipeline(unittest.TestCase):
    """Padding, squeezing and stabilising must not drop the flag."""

    @staticmethod
    def _cell(char, inverted=False):
        return [char, "w", 0, True] if inverted else [char, "w", 0]

    def test_padding_preserves_the_flag(self):
        grid = [self._cell("A", True)] + [self._cell("B")] * (24 * 11 - 1)
        padded = pad_to_hardware(grid, 24, 11)
        self.assertEqual(padded[0], ["A", "w", 0, True])

    def test_squeeze_preserves_the_flag(self):
        row = [self._cell("<", True)] + [[]] * 15 + [self._cell("X")] * 9
        grid = row * 14
        padded = pad_to_hardware(grid, 25, 14)
        self.assertEqual(padded[0], ["<", "w", 0, True])

    def test_stabiliser_treats_a_flag_change_as_a_change(self):
        """Turning reverse video on must propagate like any other change."""
        stabiliser = DisplayStabiliser(stability_frames=1)
        stabiliser.update([self._cell("A")])
        out = stabiliser.update([self._cell("A", True)])
        self.assertEqual(out[0], ["A", "w", 0, True])

    def test_sanitiser_keeps_the_flag_and_still_maps_the_character(self):
        out = sanitise_display_data([["(", "c", 1, True]])
        self.assertEqual(out[0], ["[", "c", 1, True])

    def test_falsey_flag_is_not_forwarded(self):
        out = sanitise_display_data([["A", "w", 0, False]])
        self.assertEqual(out[0], ["A", "w", 0])


if __name__ == "__main__":
    unittest.main()
