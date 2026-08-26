"""
End-to-end checks against a real MSFS MCDU pop-out screenshot.

tests/data/mcdu_real_capture.png is an actual capture of the A330 MCDU
window, title bar and all — the A330-200 nav database / status page.  The
synthetic fixtures approximate this; these tests confirm the approximation
holds where it counts.

Everything here is anchored on TRUTH, transcribed from the image by hand.
"""

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import mcdu_parser
from mcdu_parser import MCDUParser, TemplateMatcher
from mcdu_detector import detect_mcdu_region, _ink_mask
from mobiflight_client import sanitise_display_data

CAPTURE = Path(__file__).parent / "data" / "mcdu_real_capture.png"

#: The page as displayed, 24 columns by 14 rows.
TRUTH = [
    "      A330-200          ",
    " ENG                    ",
    "CF6-80AE3               ",
    " ACTIVE NAV DATA BASE   ",
    "19FEB-19MAR   AB49012001",
    " SECOND NAV DATA BASE   ",
    "←22JAN-19FEB            ",
    "                        ",
    "                        ",
    "CHG CODE                ",
    "[ ]                     ",
    "IDLE/PERF     SOFTWARE  ",
    "+0.0/+0.0  STATUS/XLOAD>",
    "NAV ACCUR DOWNGRADED    ",
]

#: Colour of a few cells, read off the capture.
EXPECTED_COLOURS = {
    (2, 0): "g",    # CF6-80AE3, engine type
    (4, 0): "c",    # 19FEB, active database validity
    (4, 14): "g",   # AB49012001, database identifier
    (6, 1): "c",    # 22JAN, second database
    (10, 0): "c",   # [ ] entry field
    (12, 0): "g",   # +0.0, IDLE value
    (13, 0): "a",   # NAV ACCUR DOWNGRADED
}


def _load():
    from PIL import Image
    return np.array(Image.open(CAPTURE).convert("RGB"))


@unittest.skipIf(not CAPTURE.exists(), "real capture fixture not present")
class TestRealCaptureDetection(unittest.TestCase):
    """Detection has to work on an actual pop-out, chrome included."""

    def setUp(self):
        self.image = _load()
        self.region = detect_mcdu_region(self.image)

    def test_a_region_is_found(self):
        self.assertIsNotNone(self.region, "no MCDU region found in a real capture")

    def test_title_bar_is_excluded(self):
        """The window title bar sits in the top ~30px and must not be included."""
        x, y, w, h = self.region
        self.assertGreater(y, 30, f"grid starts at y={y}, inside the title bar")

    def test_grid_is_plausibly_sized(self):
        x, y, w, h = self.region
        self.assertGreater(w, self.image.shape[1] * 0.7)
        self.assertGreater(h, self.image.shape[0] * 0.7)
        self.assertLessEqual(x + w, self.image.shape[1])
        self.assertLessEqual(y + h, self.image.shape[0])

    def test_cell_boundaries_fall_between_glyphs(self):
        """The physical test of alignment: boundaries should land in the gaps.

        Bounding-box centring is not a valid check here — this font sits
        right of centre in its cell — so instead compare the ink lying on the
        chosen cell boundaries against nearby alternatives.
        """
        x, y, w, h = self.region
        mask = _ink_mask(self.image)
        pitch = w / 24

        def boundary_ink(origin):
            return sum(
                int(mask[:, c].sum())
                for c in (int(round(origin + i * pitch)) for i in range(25))
                if 0 <= c < mask.shape[1]
            )

        chosen = boundary_ink(x)
        for shift in (-4, -3, 3, 4):
            self.assertLess(
                chosen, boundary_ink(x + shift),
                f"a grid shifted by {shift}px cuts through less ink than the "
                f"one chosen — the columns are misaligned",
            )


@unittest.skipIf(not CAPTURE.exists(), "real capture fixture not present")
class TestRealCaptureParsing(unittest.TestCase):
    """Occupancy, colour and font size on real pixels."""

    def setUp(self):
        self.image = _load()
        x, y, w, h = detect_mcdu_region(self.image)
        self.crop = self.image[y:y + h, x:x + w]
        self.parser = MCDUParser(self.crop, source_id="real")

    def test_occupancy_matches_the_page(self):
        """Every one of the 336 cells must agree with the transcription."""
        wrong = []
        for row in range(14):
            for col in range(24):
                empty = self.parser.is_empty_cell(
                    self.parser.extract_cell(row, col))
                if empty != (TRUTH[row][col] == " "):
                    wrong.append(f"R{row:02d}C{col:02d}")
        self.assertEqual(wrong, [], f"{len(wrong)} cells misclassified")

    def test_colours(self):
        for (row, col), expected in EXPECTED_COLOURS.items():
            cell = self.parser.extract_cell(row, col)
            self.assertEqual(
                self.parser.detect_color(cell), expected,
                f"R{row:02d}C{col:02d} ({TRUTH[row][col]!r}) colour",
            )

    def test_font_size_heuristic_matches_the_page(self):
        """Label rows render small, content rows large; row 13 is large."""
        for row in (1, 3, 5, 9, 11):
            self.assertTrue(self.parser.is_small_font(row),
                            f"row {row} is a label row and renders small")
        for row in (0, 2, 4, 6, 10, 12, 13):
            self.assertFalse(self.parser.is_small_font(row),
                             f"row {row} renders large")


@unittest.skipIf(not CAPTURE.exists(), "real capture fixture not present")
class TestRealCaptureRecognition(unittest.TestCase):
    """Recognition on real pixels, taught the way warmup teaches."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()

        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz")
        mcdu_parser._template_matcher = self.matcher

        image = _load()
        x, y, w, h = detect_mcdu_region(image)
        self.crop = image[y:y + h, x:x + w]

        parser = MCDUParser(self.crop, source_id="teach")
        for row in range(14):
            for col in range(24):
                char = TRUTH[row][col]
                if char == " ":
                    continue
                binary = parser._preprocess_cell(parser.extract_cell(row, col))
                self.matcher.learn(char, binary, confidence=1.0)
                self.matcher.learn(char, binary, confidence=1.0)

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _parse(self):
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        return MCDUParser(self.crop, source_id="read").parse_grid()

    def test_every_character_is_read_back(self):
        parsed = self._parse()
        errors = []
        for row in range(14):
            for col in range(24):
                want = TRUTH[row][col]
                if want == " ":
                    continue
                cell = parsed[row * 24 + col]
                got = cell[0] if cell else " "
                if got != want:
                    errors.append(f"R{row:02d}C{col:02d} {want!r}->{got!r}")
        self.assertEqual(errors, [], f"{len(errors)} characters misread")

    def test_dates_survive_context_correction(self):
        """22JAN once came back as 2ZJAN — the reason that rule was dropped."""
        parsed = self._parse()
        row6 = "".join(
            (parsed[6 * 24 + c][0] if parsed[6 * 24 + c] else " ")
            for c in range(24)
        )
        self.assertIn("22JAN", row6, f"row 6 read as {row6!r}")
        row4 = "".join(
            (parsed[4 * 24 + c][0] if parsed[4 * 24 + c] else " ")
            for c in range(24)
        )
        self.assertIn("19FEB-19MAR", row4, f"row 4 read as {row4!r}")

    def test_plus_signs_reach_the_display_intact(self):
        """IDLE/PERF shows +0.0/+0.0, so the sign has to survive the trip.

        Folding '+' onto '-' would invert the value silently; dropping it to
        a space loses the sign. Both were live behaviours at some point.
        """
        parsed = self._parse()
        row12 = sanitise_display_data([parsed[12 * 24 + c] for c in range(24)])
        text = "".join(cell[0] if cell else " " for cell in row12)
        self.assertIn("+0.0/+0.0", text, f"row 12 reached the CDU as {text!r}")
        for cell in row12:
            if cell:
                self.assertNotEqual(
                    cell[0], "-",
                    "a '+' reached the display as '-', inverting the value",
                )


if __name__ == "__main__":
    unittest.main()
