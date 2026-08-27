"""
Real captures: ATR 42/72-600 (FMS 220), Just Flight Avro RJ (GNLU),
Black Square Starship (FMS-850).

Ground truth is transcribed by hand from the screenshots.  What each one
established:

- The ATR is a true 24x14 Thales-style grid, as profiled, and its title bar
  sits flush against the screen - which is what motivated flattening chrome
  rows before the ink pass and clamping the crop to the chrome boundary.
- The Avro GNLU renders 25 columns, one more than the WinWing hardware, so
  its rows are squeezed by dropping blank cells (pipeline._squeeze_row).
- The Starship's FMS-850 is roughly twice the hardware's width and is not
  supported; the test pins the measurement so the claim stays honest.
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
from pipeline import HARDWARE_COLUMNS, pad_to_hardware, _squeeze_row

DATA = Path(__file__).parent / "data"
ATR1 = DATA / "atr_mcdu_screenshot (1).png"
ATR2 = DATA / "atr_mcdu_screenshot (2).png"
AVRO = DATA / "jf-avro-fcu.png"
STARSHIP = DATA / "blacksquare_starship.png"

#: The ATR INIT page (screenshot 2), 24 columns by 14 rows.
ATR2_TRUTH = [
    "M      INIT      GPS .06",
    "DATE           GPS (UTC)",
    "26-AUG-26       16H39:10",
    "STD DATA   LOCAL    DIFF",
    "01-DEC-25  17H39  +01H00",
    "                        ",
    "                        ",
    "------------------------",
    "<POS INIT        WEIGHT>",
    "                        ",
    "<NAV DATA     PERF INIT>",
    "                        ",
    "<FPLN INIT        UNITS>",
    "                        ",
]


def load(path):
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def detected_crop(image, columns, rows):
    found = detect_mcdu_region(image, columns=columns, rows=rows)
    if not found:
        return None
    x, y, w, h = found
    x, y = max(0, x), max(0, y)
    w = min(w, image.shape[1] - x)
    h = min(h, image.shape[0] - y)
    return image[y:y + h, x:x + w]


@unittest.skipIf(not ATR2.exists(), "ATR captures missing")
class TestAtrCapture(unittest.TestCase):
    """The ATR FMS 220 under the atr profile (24x14, Thales style)."""

    def setUp(self):
        for line in ATR2_TRUTH:
            self.assertEqual(len(line), 24)
        self.crop = detected_crop(load(ATR2), 24, 14)
        self.assertIsNotNone(self.crop, "no grid detected on the ATR capture")
        self.parser = MCDUParser(self.crop, columns=24, rows=14,
                                 source_id="atr2")

    def test_profile_grid_matches(self):
        profile = PROFILES["atr"]
        self.assertEqual((profile.columns, profile.rows), (24, 14))

    def test_detection_excludes_the_title_bar(self):
        """The screen sits flush under the chrome; the crop must not include
        it.  Before the chrome clamp, row 0 read as fully occupied because
        four pixels of title bar were inked across every column."""
        row0 = [self.parser.is_empty_cell(self.parser.extract_cell(0, c))
                for c in range(24)]
        self.assertGreater(sum(row0), 8,
                           "row 0 has almost no empty cells - chrome bleed")

    def test_occupancy_matches_the_page(self):
        wrong = []
        for row in range(14):
            for col in range(24):
                empty = self.parser.is_empty_cell(
                    self.parser.extract_cell(row, col))
                if empty != (ATR2_TRUTH[row][col] == " "):
                    wrong.append(f"R{row:02d}C{col:02d}")
        # Measured at 0/336 on this capture; the slack of 2 covers nothing
        # but antialiasing at a future OpenCV version bump.
        self.assertLessEqual(len(wrong), 2, f"misclassified: {wrong}")

    def test_colours(self):
        self.assertEqual(
            self.parser.detect_color(self.parser.extract_cell(2, 0)), "g",
            "26-AUG-26 renders green")
        self.assertEqual(
            self.parser.detect_color(self.parser.extract_cell(4, 18)), "c",
            "+01H00 renders cyan")
        self.assertEqual(
            self.parser.detect_color(self.parser.extract_cell(8, 0)), "w",
            "<POS INIT renders white")

    def test_second_page_detects_too(self):
        if not ATR1.exists():
            self.skipTest("first ATR capture missing")
        crop = detected_crop(load(ATR1), 24, 14)
        self.assertIsNotNone(crop)
        parser = MCDUParser(crop, columns=24, rows=14, source_id="atr1")
        occupied = sum(
            1 for r in range(14) for c in range(24)
            if not parser.is_empty_cell(parser.extract_cell(r, c))
        )
        self.assertGreater(occupied, 100, "page content missing from crop")
        self.assertLess(occupied, 250, "crop includes non-text area")


@unittest.skipIf(not ATR2.exists(), "ATR captures missing")
class TestAtrRecognition(unittest.TestCase):
    """Characters read back from the real ATR pixels, taught as warmup would."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_templates._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "atr.npz")
        mcdu_templates._template_matcher = self.matcher

        self.crop = detected_crop(load(ATR2), 24, 14)
        parser = MCDUParser(self.crop, columns=24, rows=14, source_id="teach")
        for row in range(14):
            for col in range(24):
                char = ATR2_TRUTH[row][col]
                if char == " ":
                    continue
                if parser.is_empty_cell(parser.extract_cell(row, col)):
                    continue        # borderline cell; nothing to learn from
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

    def test_characters_read_back(self):
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(self.crop, columns=24, rows=14,
                            source_id="read").parse_grid()
        total = correct = 0
        errors = []
        for row in range(14):
            for col in range(24):
                want = ATR2_TRUTH[row][col]
                if want == " ":
                    continue
                cell = parsed[row * 24 + col]
                got = cell[0] if cell else " "
                total += 1
                if got == want:
                    correct += 1
                else:
                    errors.append(f"R{row:02d}C{col:02d} {want!r}->{got!r}")
        # Measured at 147/147 on this capture.
        self.assertGreater(correct / total, 0.99,
                           f"{correct}/{total}; errors: {errors[:12]}")

    def test_plus_survives_to_the_display(self):
        """+01H00: the third real capture in a row showing '+' on screen."""
        from mobiflight_client import sanitise_display_data
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(self.crop, columns=24, rows=14,
                            source_id="plus").parse_grid()
        sent = sanitise_display_data(parsed)
        row4 = "".join(cell[0] if cell else " "
                       for cell in sent[4 * 24:(4 + 1) * 24])
        self.assertIn("+01H00", row4, f"row 4 reached the CDU as {row4!r}")


@unittest.skipIf(not AVRO.exists(), "Avro capture missing")
class TestAvroGnlu(unittest.TestCase):
    """The GNLU renders 25 columns; rows are squeezed onto the hardware."""

    def test_profile_is_25_columns(self):
        profile = PROFILES["avro_gnlu"]
        self.assertEqual((profile.columns, profile.rows), (25, 14))

    def test_detection_covers_the_full_width(self):
        """At 24 columns the crop ended 36px early and cut the right-hand
        column - dates and line-select prompts - off the page."""
        image = load(AVRO)
        crop = detected_crop(image, 25, 14)
        self.assertIsNotNone(crop)
        parser = MCDUParser(crop, columns=25, rows=14, source_id="avro25")
        rightmost = max(
            c for r in range(14) for c in range(25)
            if not parser.is_empty_cell(parser.extract_cell(r, c))
        )
        self.assertGreaterEqual(rightmost, 23,
                                f"content stops at column {rightmost}")

    def test_scratchpad_row_is_left_aligned(self):
        crop = detected_crop(load(AVRO), 25, 14)
        parser = MCDUParser(crop, columns=25, rows=14, source_id="avrosp")
        # NAV DATA OUT OF DATE: 20 characters from column 0.
        filled = sum(
            1 for c in range(20)
            if not parser.is_empty_cell(parser.extract_cell(13, c))
        )
        self.assertGreaterEqual(filled, 16, "scratchpad text not where expected")


class TestSqueezeRow(unittest.TestCase):
    """25 columns into 24: blanks go first, prompts at both edges survive."""

    @staticmethod
    def _row(text):
        return [[ch, "w", 0] if ch != " " else [] for ch in text]

    def test_trailing_blank_dropped_first(self):
        row = self._row("<INDEX" + " " * 19)     # 25 cells
        out = _squeeze_row(row, 24)
        self.assertEqual(len(out), 24)
        self.assertEqual(out[0][0], "<")
        self.assertEqual("".join(c[0] if c else " " for c in out).rstrip(),
                         "<INDEX")

    def test_prompts_at_both_edges_survive(self):
        row = self._row("<INDEX" + " " * 10 + "POS INIT>")   # 25 cells
        out = _squeeze_row(row, 24)
        self.assertEqual(out[0][0], "<", "left line-select prompt lost")
        self.assertEqual(out[-1][0], ">", "right line-select prompt lost")
        text = "".join(c[0] if c else " " for c in out)
        self.assertIn("POS INIT>", text)
        self.assertTrue(text.startswith("<INDEX"))

    def test_full_row_truncates_right(self):
        row = self._row("X" * 25)
        out = _squeeze_row(row, 24)
        self.assertEqual(len(out), 24)
        self.assertTrue(all(c and c[0] == "X" for c in out))

    def test_pad_to_hardware_squeezes_wide_grids(self):
        grid = []
        for _ in range(14):
            grid.extend(self._row("<INDEX" + " " * 10 + "POS INIT>"))
        out = pad_to_hardware(grid, 25, 14)
        self.assertEqual(len(out), 24 * 14)
        for row in range(14):
            line = out[row * HARDWARE_COLUMNS:(row + 1) * HARDWARE_COLUMNS]
            self.assertEqual(line[0][0], "<")
            self.assertEqual(line[-1][0], ">")


@unittest.skipIf(not STARSHIP.exists(), "Starship capture missing")
class TestStarshipIsOutOfScope(unittest.TestCase):
    """The FMS-850 is about twice the hardware's width.  Pin the measurement
    so the unsupported claim stays honest - if a future capture measures
    differently, this fails and the decision gets revisited."""

    def test_display_is_far_wider_than_the_hardware(self):
        image = load(STARSHIP)
        mask = detector._ink_mask(image)
        mask[:42] = False                      # window chrome
        bands = detector._text_rows(mask)
        centres = []
        for a, b in bands:
            projection = mask[a:b + 1].sum(axis=0)
            start = None
            for i, has_ink in enumerate(projection > 0):
                if has_ink and start is None:
                    start = i
                elif not has_ink and start is not None:
                    if i - start >= 2:
                        centres.append((start + i - 1) / 2)
                    start = None
        centres = np.array(sorted(centres))
        gaps = np.diff(centres)
        gaps = gaps[(gaps > 2)]
        pitch = float(np.median(gaps[gaps < np.median(gaps) * 1.5]))
        span = centres.max() - centres.min()
        columns = span / pitch
        self.assertGreater(
            columns, 40,
            f"measured only {columns:.0f} columns - narrower than believed, "
            f"support may be feasible after all",
        )

    def test_no_profile_claims_the_starship(self):
        for profile in PROFILES.values():
            self.assertNotIn("starship", profile.label.lower())
            self.assertNotIn("fms-850", profile.label.lower())


if __name__ == "__main__":
    unittest.main()
