"""
Just Flight Fokker 70/100 (Honeywell/Pegasus FMC), from a real capture.

tests/data/jf-f70-f100-fcu.png is the identification page of a Fokker 100.
Green monochrome CRT, alternating small label rows and large value rows,
slashed zeros.

This capture is what exposed the row-pitch bug fixed alongside it: its
label rows sit closer to their value rows than a uniform pitch implies, so
the centre-to-centre gaps alternate 26px and 17px.  Choosing the pitch by
its most common gap picked one of the two rather than their 21.7px average,
compressing the grid until rows bled into one another.
"""

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import mcdu_detector as detector
import mcdu_parser
import mcdu_templates
from aircraft_profiles import PROFILES
from mcdu_detector import detect_mcdu_region
from mcdu_parser import MCDUParser, TemplateMatcher
from mobiflight_client import sanitise_display_data

CAPTURE = Path(__file__).parent / "data" / "jf-f70-f100-fcu.png"

#: The identification page as displayed, 24 columns by 14 rows.
TRUTH = [
    "      F.28 MK0100       ",
    "  ENG                   ",
    "TAY MK620-15            ",
    "  ACTIVE DATA BASE      ",
    "20MAR17APR/25           ",
    "  SECOND DATA BASE      ",
    "20MAR17APR/25           ",
    "  OP PROGRAM            ",
    "PS4052538-352           ",
    "                        ",
    "                        ",
    "FUEL CONSUMPTION        ",
    "+1.0                    ",
    "                        ",
]

#: Rows carrying content, and whether the display draws them small.
#: Rows 9, 10 and 13 are blank on this page, so their size is unobservable.
ROW_IS_SMALL = {0: False, 1: True, 2: False, 3: True, 4: False, 5: True,
                6: False, 7: True, 8: False, 11: True, 12: False}


def load():
    from PIL import Image
    return np.array(Image.open(CAPTURE).convert("RGB"))


def detected_crop():
    image = load()
    found = detect_mcdu_region(image, columns=24, rows=14)
    if not found:
        return None
    x, y, w, h = found
    x, y = max(0, x), max(0, y)
    return image[y:y + min(h, image.shape[0] - y),
                 x:x + min(w, image.shape[1] - x)]


@unittest.skipIf(not CAPTURE.exists(), "Fokker capture missing")
class TestFokkerGeometry(unittest.TestCase):

    def setUp(self):
        for line in TRUTH:
            self.assertEqual(len(line), 24)
        self.crop = detected_crop()
        self.assertIsNotNone(self.crop, "nothing detected")
        self.parser = MCDUParser(self.crop, columns=24, rows=14,
                                 source_id="fokker")

    def test_profile_matches(self):
        profile = PROFILES["fokker"]
        self.assertEqual((profile.columns, profile.rows), (24, 14))
        self.assertEqual(profile.small_font_rule, "labels_small")

    def test_row_pitch_is_the_average_not_a_mode(self):
        """21.7px, midway between the alternating 26px and 17px gaps."""
        self.assertAlmostEqual(self.parser.cell_height, 21.7, delta=0.6)

    def test_rows_do_not_bleed_into_each_other(self):
        """A compressed pitch made neighbouring rows read identically."""
        patterns = []
        for row in range(14):
            patterns.append("".join(
                "." if self.parser.is_empty_cell(self.parser.extract_cell(row, c))
                else "#" for c in range(24)
            ))
        for row in range(13):
            if "#" not in patterns[row]:
                continue
            self.assertNotEqual(
                patterns[row], patterns[row + 1],
                f"rows {row} and {row + 1} read identically - grid compressed",
            )

    def test_occupancy_matches_the_page(self):
        wrong = []
        for row in range(14):
            for col in range(24):
                empty = self.parser.is_empty_cell(
                    self.parser.extract_cell(row, col))
                if empty != (TRUTH[row][col] == " "):
                    wrong.append(f"R{row:02d}C{col:02d}")
        self.assertLessEqual(len(wrong), 2, f"misclassified: {wrong}")

    def test_label_rows_render_small(self):
        """The rule matches the display, checked against the glyphs.

        Only rows with content are checked: a blank row has no observable
        size, so asserting one would be asserting the rule against itself.
        """
        for row, expected_small in ROW_IS_SMALL.items():
            self.assertEqual(self.parser.is_small_font(row), expected_small,
                             f"row {row}: rule disagrees with the page")

        heights = {}
        for row in ROW_IS_SMALL:
            tops, bottoms = [], []
            for col in range(24):
                cell = self.parser.extract_cell(row, col)
                if self.parser.is_empty_cell(cell):
                    continue
                ink = np.nonzero(np.max(cell, axis=2)
                                 > self.parser.INK_THRESHOLD
                                 + self.parser._bg_floor)[0]
                if ink.size:
                    tops.append(ink.min())
                    bottoms.append(ink.max())
            if tops:
                heights[row] = max(bottoms) - min(tops) + 1

        # Means, not extremes: a large row whose glyphs are all short - row
        # 12 is "+1.0", none of which is full height - measures no taller
        # than a label row without that meaning the rule is wrong.
        small = [h for r, h in heights.items() if ROW_IS_SMALL[r]]
        large = [h for r, h in heights.items() if not ROW_IS_SMALL[r]]
        self.assertLess(
            np.mean(small), np.mean(large),
            f"label rows are not smaller on average: "
            f"small={small} large={large}",
        )

    def test_display_is_monochrome_green(self):
        seen = {
            self.parser.detect_color(self.parser.extract_cell(r, c))
            for r in range(14) for c in range(24)
            if not self.parser.is_empty_cell(self.parser.extract_cell(r, c))
        }
        self.assertEqual(seen, {"g"}, f"expected green only, saw {seen}")

    def test_no_reverse_video_on_this_page(self):
        for row in range(14):
            for col in range(24):
                cell = self.parser.extract_cell(row, col)
                if not self.parser.is_empty_cell(cell):
                    self.assertFalse(self.parser.is_inverted_cell(cell),
                                     f"R{row:02d}C{col:02d} read as inverted")


@unittest.skipIf(not CAPTURE.exists(), "Fokker capture missing")
class TestFokkerRecognition(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_templates._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "fokker.npz")
        mcdu_templates._template_matcher = self.matcher

        self.crop = detected_crop()
        parser = MCDUParser(self.crop, columns=24, rows=14, source_id="teach")
        for row in range(14):
            for col in range(24):
                char = TRUTH[row][col]
                if char == " ":
                    continue
                if parser.is_empty_cell(parser.extract_cell(row, col)):
                    continue
                binary = parser.cell_binary(row, col)
                self.matcher.learn(char, binary, confidence=1.0)
                self.matcher.learn(char, binary, confidence=1.0)

    def tearDown(self):
        mcdu_templates._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _parse(self):
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        return MCDUParser(self.crop, columns=24, rows=14,
                          source_id="read").parse_grid()

    def test_characters_read_back(self):
        parsed = self._parse()
        total = correct = 0
        errors = []
        for row in range(14):
            for col in range(24):
                want = TRUTH[row][col]
                if want == " ":
                    continue
                cell = parsed[row * 24 + col]
                got = cell[0] if cell else " "
                total += 1
                if got == want:
                    correct += 1
                else:
                    errors.append(f"R{row:02d}C{col:02d} {want!r}->{got!r}")
        self.assertGreater(correct / total, 0.97,
                           f"{correct}/{total}; errors: {errors[:12]}")

    def test_slashed_zeros_read_as_zero(self):
        """This FMC draws a slash through its zeros; they are still zeros."""
        parsed = self._parse()
        row0 = "".join(
            (parsed[c][0] if parsed[c] else " ") for c in range(24)
        )
        self.assertIn("MK0100", row0, f"row 0 read as {row0!r}")

    def test_plus_reaches_the_display(self):
        """FUEL CONSUMPTION +1.0 - the fourth capture showing '+' on screen."""
        parsed = self._parse()
        sent = sanitise_display_data(parsed)
        row12 = "".join(cell[0] if cell else " "
                        for cell in sent[12 * 24:13 * 24])
        self.assertTrue(row12.startswith("+1.0"),
                        f"row 12 reached the CDU as {row12!r}")


if __name__ == "__main__":
    unittest.main()
