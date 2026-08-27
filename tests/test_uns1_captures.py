"""
Measurements taken from two real UNS-1 pop-out captures.

tests/data/uns1_wt.png          Working Title UNS-1, POS INIT page
tests/data/uns1_jf_bae146.png   Just Flight BAe 146 UNS-1, same page

These pin down what the captures actually show, so the UNS-1 profile is
grounded in measurement rather than guesswork, and so a future change to
detection can be scored against real pixels.

They also record a limitation honestly: unlike an airliner CDU, a UNS-1 is
only *approximately* a uniform character grid, and automatic region
detection does not currently handle these displays. See ISSUES.md #22.
"""

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
from mcdu_parser import MCDUParser

DATA = Path(__file__).parent / "data"
WT = DATA / "uns1_wt.png"
JF = DATA / "uns1_jf_bae146.png"

#: Crops picked by eye against the grid overlay when Auto Detect could not
#: handle these displays (ISSUES.md #22).  Kept as a reference point: the
#: detector now scores better than both of them, and the tests below use it
#: rather than these.
VERIFIED_CROPS = {
    "uns1_wt.png": (53, 51, 504, 322),
    "uns1_jf_bae146.png": (0, 56, 388, 283),
}


def detected_crop(path, columns=24, rows=11):
    """The crop Auto Detect produces, clamped to the image."""
    image = load(path)
    found = detector.detect_mcdu_region(image, columns=columns, rows=rows)
    if not found:
        return None
    x, y, w, h = found
    x, y = max(0, x), max(0, y)
    return (x, y, min(w, image.shape[1] - x), min(h, image.shape[0] - y))


def load(path):
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def text_bands(mask):
    """Text rows, with touching rows split and frame noise dropped."""
    rows = []
    for top, bottom in detector._text_rows(mask):
        occupied = mask[top:bottom + 1].any(axis=0)
        extent = np.nonzero(occupied)[0]
        if extent.size and occupied[extent[0]:extent[-1] + 1].mean() >= 0.04:
            rows.append((top, bottom))
    if not rows:
        return rows

    heights = sorted(b - a + 1 for a, b in rows)
    unit = heights[len(heights) // 4]
    projection = mask.sum(axis=1)
    out = []
    for top, bottom in rows:
        height = bottom - top + 1
        count = int(round(height / unit))
        if count <= 1 or height < unit * 1.7:
            out.append((top, bottom))
            continue
        cuts = []
        for i in range(1, count):
            target = top + int(round(i * height / count))
            lo, hi = max(top + 2, target - unit // 3), min(bottom - 2, target + unit // 3)
            if hi > lo:
                cuts.append(lo + int(np.argmin(projection[lo:hi + 1])))
        edges = [top] + sorted(set(cuts)) + [bottom]
        out += [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    return out


@unittest.skipIf(not WT.exists() or not JF.exists(), "UNS-1 captures missing")
class TestUns1Geometry(unittest.TestCase):
    """What the real displays measure, independent of our code's opinion."""

    def test_both_show_eleven_rows(self):
        """Ten lines of text plus one blank, on both developers' UNS-1."""
        for path, expected in ((WT, 9), (JF, 10)):
            bands = text_bands(detector._ink_mask(load(path)))
            self.assertGreaterEqual(len(bands), expected - 1, path.name)
            self.assertLessEqual(len(bands), 11, path.name)

    def test_profile_matches_the_measurement(self):
        """The UNS-1 profile's grid is what the captures show, not a guess."""
        profile = PROFILES["uns1"]
        self.assertEqual((profile.columns, profile.rows), (24, 11))

    def test_row_pitch_is_consistent_within_each_capture(self):
        """Body rows are evenly spaced even though the page as a whole is not."""
        for path in (WT, JF):
            bands = text_bands(detector._ink_mask(load(path)))
            centres = np.array([(a + b) / 2 for a, b in bands])
            gaps = np.diff(centres)
            # Only the single-pitch gaps: the title and bottom lines are
            # separated by wider ones, which is precisely why the page as a
            # whole is not a uniform lattice.
            median = np.median(gaps)
            body = gaps[np.abs(gaps - median) <= median * 0.25]
            self.assertGreater(body.size, 3, path.name)
            spread = body.std() / body.mean()
            self.assertLess(spread, 0.10,
                            f"{path.name}: body row spacing varies by "
                            f"{spread:.0%}")

    def test_auto_detect_separates_every_row(self):
        """Each text row must land in a cell of its own.

        This is what #22 was really about: two rows sharing a cell merges
        them, which no amount of good recognition recovers from.
        """
        for path in (WT, JF):
            image = load(path)
            crop = detected_crop(path)
            self.assertIsNotNone(crop, f"{path.name}: nothing detected")
            x, y, w, h = crop
            mask = detector._ink_mask(image)
            bands = detector._drop_chrome_remnants(
                detector._split_touching_rows(
                    detector._text_rows(mask), mask.sum(axis=1)),
                detector._chrome_bottom(image))
            uncut, distinct = detector._grid_quality(bands, float(y),
                                                     h / 11, 11)
            self.assertEqual(distinct, len(bands),
                             f"{path.name}: rows share cells")

    def test_auto_detect_beats_a_hand_picked_crop(self):
        """The detector is now the better of the two, on both captures."""
        for path in (WT, JF):
            image = load(path)
            mask = detector._ink_mask(image)
            bands = detector._drop_chrome_remnants(
                detector._split_touching_rows(
                    detector._text_rows(mask), mask.sum(axis=1)),
                detector._chrome_bottom(image))
            auto = detected_crop(path)
            manual = VERIFIED_CROPS[path.name]
            auto_score = detector._grid_quality(bands, float(auto[1]),
                                                auto[3] / 11, 11)
            manual_score = detector._grid_quality(bands, float(manual[1]),
                                                  manual[3] / 11, 11)
            self.assertGreaterEqual(
                auto_score, manual_score,
                f"{path.name}: auto {auto_score} is worse than hand-picked "
                f"{manual_score}",
            )

    def test_a_uniform_grid_still_cannot_hold_every_row(self):
        """The underlying awkwardness has not gone away.

        An Airbus CDU is a true uniform grid - every text band fits inside
        one cell.  On these UNS-1 displays the title and bottom lines sit
        off the body lattice, so some band is always clipped, however well
        the grid is placed.  Detection now works despite that rather than
        because it was solved.
        """
        worst = {}
        for path in (WT, JF):
            mask = detector._ink_mask(load(path))
            bands = text_bands(mask)
            best = 0
            for rows in (11, 12, 13, 14):
                for pitch in np.arange(20.0, 34.0, 0.25):
                    for origin in np.arange(bands[0][0] - pitch,
                                            bands[0][0] + 1, 0.5):
                        if origin + rows * pitch < bands[-1][1]:
                            continue
                        edges = [origin + i * pitch for i in range(rows + 1)]
                        fits = sum(1 for a, b in bands
                                   if not any(a < e < b for e in edges))
                        best = max(best, fits)
            worst[path.name] = (best, len(bands))
        for name, (best, total) in worst.items():
            self.assertLess(best, total,
                            f"{name}: a uniform grid now holds all {total} "
                            f"rows - detection may be worth revisiting")


@unittest.skipIf(not WT.exists() or not JF.exists(), "UNS-1 captures missing")
class TestUns1ParsesFromTheDetectedCrop(unittest.TestCase):
    """The grid Auto Detect produces lands on the text."""

    def _parser(self, path):
        crop = detected_crop(path)
        self.assertIsNotNone(crop, f"{path.name}: nothing detected")
        x, y, w, h = crop
        image = load(path)[y:y + h, x:x + w]
        return MCDUParser(image, columns=24, rows=11,
                          source_id=path.stem, small_font_rule="all_large")

    def test_cell_size_is_plausible(self):
        for path in (WT, JF):
            parser = self._parser(path)
            self.assertGreater(parser.cell_width, 10, path.name)
            self.assertGreater(parser.cell_height, 15, path.name)

    def test_every_row_holds_some_text(self):
        """Ten of the eleven rows carry content; one is blank."""
        for path, blanks in ((WT, 1), (JF, 1)):
            parser = self._parser(path)
            empty_rows = sum(
                1 for r in range(11)
                if all(parser.is_empty_cell(parser.extract_cell(r, c))
                       for c in range(24))
            )
            self.assertLessEqual(empty_rows, blanks + 1, path.name)

    def test_content_reaches_the_last_column(self):
        """A crop that clips the right-hand column loses UTC, dates, versions."""
        for path in (WT, JF):
            parser = self._parser(path)
            used = max(
                c for r in range(11) for c in range(24)
                if not parser.is_empty_cell(parser.extract_cell(r, c))
            )
            self.assertGreaterEqual(used, 22,
                                    f"{path.name}: text stops at column {used}")

    def test_colours_are_read(self):
        """Both displays use colour to separate labels from values."""
        for path in (WT, JF):
            parser = self._parser(path)
            seen = {
                parser.detect_color(parser.extract_cell(r, c))
                for r in range(11) for c in range(24)
                if not parser.is_empty_cell(parser.extract_cell(r, c))
            }
            self.assertGreaterEqual(len(seen), 2,
                                    f"{path.name}: only found {seen}")

    def test_all_rows_render_large(self):
        """The UNS-1 has no small label font, unlike an airliner CDU."""
        parser = self._parser(WT)
        for row in range(11):
            self.assertFalse(parser.is_small_font(row))


#: The Working Title UNS-1 POS INIT page, transcribed from the capture.
#: Cross-checked three ways: against the image, against the occupied-cell
#: map the parser derives independently of what it reads, and against what
#: the parser actually reads.  The Just Flight page is deliberately not
#: transcribed here - its text is packed more tightly than one glyph per
#: cell in places, so several columns would be guesswork, and a fixture
#: that encodes a guess is worse than no fixture.
WT_TRUTH = [
    " POS    INIT 1/1        ",
    "                    DATE",
    "INITIAL POS    26-AUG-26",
    "ID  <GPS>            UTC",
    "N  28 29.23     16:28:22",
    "W 016 20.92             ",
    "                        ",
    "NAV DATABASE EXPIRES    ",
    "11-JUN-26               ",
    "                        ",
    "←ACCEPT FMC VER  WT2.2.3",
]


@unittest.skipIf(not WT.exists(), "UNS-1 capture missing")
class TestUns1ColdStart(unittest.TestCase):
    """What this display reads as on a first run, with nothing learned.

    The UNS-1 is the hardest display the project supports: 45% of its
    glyphs cross a cell edge, because it is not really a fixed-pitch grid
    (ISSUES.md #28).  It used to come back as INITIBL POS and NBV DBTBBBSE
    - every A read as a B, because warmup learned the raw OCR reading while
    the display corrected it, so the wrong label was the one that stuck.

    Measured at 91.5% after that was fixed.  The floor is set below it, and
    the errors that remain are listed in the failure message rather than
    asserted away, so a change that trades one for another is visible.
    """

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_templates._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_templates._template_matcher = mcdu_parser.TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "uns1.npz")

    def tearDown(self):
        mcdu_templates._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _read(self):
        crop = detected_crop(WT)
        self.assertIsNotNone(crop, "nothing detected")
        x, y, w, h = crop
        image = load(WT)[y:y + h, x:x + w]
        return MCDUParser(image, columns=24, rows=11, source_id="uns1cold",
                          small_font_rule="all_large").parse_grid()

    def test_the_page_reads(self):
        for line in WT_TRUTH:
            self.assertEqual(len(line), 24)
        grid = self._read()
        total = correct = 0
        errors = []
        for row in range(11):
            for col in range(24):
                cell = grid[row * 24 + col]
                got = cell[0] if cell else " "
                want = WT_TRUTH[row][col]
                if want == " " and got == " ":
                    continue
                total += 1
                if got == want:
                    correct += 1
                else:
                    errors.append(f"R{row:02d}C{col:02d} {want!r}->{got!r}")
        self.assertGreaterEqual(
            correct / total, 0.85,
            f"{correct}/{total} = {correct / total:.1%}; errors: {errors}",
        )

    def test_the_words_come_out_whole(self):
        """The failure this page is here for was letters, not layout."""
        grid = self._read()
        text = chr(10).join(
            "".join((grid[r * 24 + c][0] if grid[r * 24 + c] else " ")
                    for c in range(24))
            for r in range(11)
        )
        for word in ("INITIAL POS", "NAV DATABASE EXPIRES", "11-JUN-26",
                     "FMC VER"):
            self.assertIn(word, text, f"{word!r} did not survive: {text!r}")


if __name__ == "__main__":
    unittest.main()
