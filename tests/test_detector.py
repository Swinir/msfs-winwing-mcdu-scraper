"""
Grid detection accuracy against rendered MCDU pages.

Detection is scored two ways: geometric overlap with the true screen area,
and — the one that actually matters — whether recognition through the
detected crop works.  A crop half a cell out of place looks almost right by
IoU and scores 0% recognition, so IoU alone would not catch a regression.
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
from mcdu_detector import detect_mcdu_region, _detect_via_pitch, _text_rows, _ink_mask
from mcdu_fixtures import (
    ALL_PAGES,
    find_mono_font,
    grid_accuracy,
    embed_in_window,
    region_iou,
    render_mcdu,
)


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestRegionDetection(unittest.TestCase):
    """The detected crop must align with the character cells."""

    CELL_SIZES = ((20, 24), (14, 17), (28, 32))

    def test_detects_screen_inside_window_chrome(self):
        """A title bar used to collapse detection to a tiny box or the lot."""
        for name, factory in ALL_PAGES.items():
            for cell in self.CELL_SIZES:
                screen = render_mcdu(factory(), cell_size=cell)
                window, truth = embed_in_window(screen, chrome=True)
                found = detect_mcdu_region(window)
                self.assertIsNotNone(found, f"{name} {cell}: nothing detected")
                iou = region_iou(found, truth)
                self.assertGreater(
                    iou, 0.95,
                    f"{name} {cell}: IoU {iou:.3f}, got {found}, want {truth}",
                )

    def test_detects_screen_without_chrome(self):
        for name, factory in ALL_PAGES.items():
            screen = render_mcdu(factory(), cell_size=(20, 24))
            window, truth = embed_in_window(screen, chrome=False)
            found = detect_mcdu_region(window)
            self.assertIsNotNone(found, f"{name}: nothing detected")
            self.assertGreater(region_iou(found, truth), 0.95, name)

    def test_cell_pitch_is_recovered(self):
        """Width and height should come out as whole multiples of the pitch."""
        for cell_w, cell_h in self.CELL_SIZES:
            screen = render_mcdu(ALL_PAGES["flight_plan"](),
                                 cell_size=(cell_w, cell_h))
            window, _ = embed_in_window(screen, chrome=True)
            x, y, w, h = detect_mcdu_region(window)
            self.assertAlmostEqual(w / 24, cell_w, delta=0.6,
                                   msg=f"column pitch wrong for {cell_w}")
            self.assertAlmostEqual(h / 14, cell_h, delta=0.6,
                                   msg=f"row pitch wrong for {cell_h}")

    def test_sparse_page_still_yields_the_full_grid(self):
        """Blank trailing columns must not be cropped away.

        A bounding box around the text would stop at the last glyph, and the
        parser would then divide a too-narrow strip into 24 columns, putting
        every character in the wrong cell.
        """
        page = ALL_PAGES["perf"]()          # right-hand columns are blank
        screen = render_mcdu(page, cell_size=(20, 24))
        window, truth = embed_in_window(screen, chrome=True)
        x, y, w, h = detect_mcdu_region(window)
        self.assertGreater(
            w, truth[2] * 0.95,
            "detected width collapsed onto the text instead of the grid",
        )

    def test_rejects_an_image_with_no_text(self):
        blank = np.zeros((400, 600, 3), dtype=np.uint8)
        self.assertIsNone(_detect_via_pitch(blank, 24, 14))

    def test_bezel_lines_are_not_counted_as_text_rows(self):
        """A solid edge-to-edge rule is furniture, not a line of characters."""
        mask = np.zeros((100, 200), dtype=bool)
        mask[10:14, :] = True                      # a solid rule
        mask[40:55, ::6] = True                    # glyph-like, gappy
        rows = _text_rows(mask)
        self.assertTrue(rows, "all rows were discarded")
        for top, bottom in rows:
            self.assertGreater(bottom, 20,
                               "the solid rule was kept as a text row")


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestDetectionFeedsRecognition(unittest.TestCase):
    """The real test: does the detected crop actually parse?"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz"
        )
        mcdu_parser._template_matcher = self.matcher

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _teach(self, cell):
        for name in ALL_PAGES:
            page = ALL_PAGES[name]()
            parser = MCDUParser(render_mcdu(page, cell_size=cell),
                                source_id="teach")
            for row, line in enumerate(page.padded()):
                for col, char in enumerate(line):
                    if char == " ":
                        continue
                    binary = parser._preprocess_cell(parser.extract_cell(row, col))
                    self.matcher.learn(char, binary, confidence=1.0)
                    self.matcher.learn(char, binary, confidence=1.0)

    def test_recognition_through_detected_crop(self):
        cell = (20, 24)
        self._teach(cell)
        for name, factory in ALL_PAGES.items():
            page = factory()
            window, _ = embed_in_window(render_mcdu(page, cell_size=cell),
                                        chrome=True)
            found = detect_mcdu_region(window)
            self.assertIsNotNone(found, f"{name}: nothing detected")

            mcdu_parser._prev_row_imgs.clear()
            mcdu_parser._prev_row_ocr.clear()
            x, y, w, h = found
            crop = window[max(0, y):y + h, max(0, x):x + w]
            parsed = MCDUParser(crop, source_id="d").parse_grid()
            score = grid_accuracy(page.expected_cells(), parsed)
            self.assertGreater(
                score["char_accuracy"], 0.90,
                f"{name}: {score['char_accuracy']:.1%} through crop {found}",
            )


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestParserToleratesImperfectCrops(unittest.TestCase):
    """Cells are partitioned with fractional edges, not by resampling.

    The parser used to resize every capture to an exact multiple of the grid.
    INTER_AREA blurs thin strokes, and the blur depended on the crop size, so
    a crop one pixel wider than the one templates were learned from dropped
    recognition from 100% to 51%.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz"
        )
        mcdu_parser._template_matcher = self.matcher
        self.page = ALL_PAGES["alpha_numeric"]()
        self.screen = render_mcdu(self.page, cell_size=(20, 24))
        parser = MCDUParser(self.screen, source_id="teach")
        for row, line in enumerate(self.page.padded()):
            for col, char in enumerate(line):
                if char == " ":
                    continue
                binary = parser._preprocess_cell(parser.extract_cell(row, col))
                self.matcher.learn(char, binary, confidence=1.0)
                self.matcher.learn(char, binary, confidence=1.0)

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self._tmpdir.cleanup()

    def _accuracy(self, image):
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(image, source_id="c").parse_grid()
        return grid_accuracy(self.page.expected_cells(), parsed)["char_accuracy"]

    def test_exact_crop_is_perfect(self):
        self.assertGreater(self._accuracy(self.screen), 0.97)

    def test_one_pixel_of_slack_is_survivable(self):
        window, (x, y, w, h) = embed_in_window(self.screen, chrome=False)
        for label, crop in (
            ("1px wider", (x, y, w + 1, h)),
            ("1px taller", (x, y, w, h + 1)),
            ("1px narrower", (x, y, w - 1, h)),
        ):
            accuracy = self._accuracy(window[crop[1]:crop[1] + crop[3],
                                             crop[0]:crop[0] + crop[2]])
            self.assertGreater(
                accuracy, 0.70,
                f"{label}: {accuracy:.1%} — the parser is resampling again",
            )

    def test_cells_partition_the_image_exactly(self):
        """Rounded edges must tile the image with no gaps or overlaps."""
        for width, height in ((481, 335), (500, 350), (337, 239)):
            image = np.zeros((height, width, 3), dtype=np.uint8)
            parser = MCDUParser(image, source_id="p")
            self.assertEqual(parser._col_edges[0], 0)
            self.assertEqual(parser._col_edges[-1], width)
            self.assertEqual(parser._row_edges[0], 0)
            self.assertEqual(parser._row_edges[-1], height)
            for edges in (parser._col_edges, parser._row_edges):
                self.assertTrue(all(b >= a for a, b in zip(edges, edges[1:])),
                                "cell edges are not monotonic")

    def test_every_cell_is_non_empty_for_odd_sizes(self):
        image = np.zeros((239, 481, 3), dtype=np.uint8)
        parser = MCDUParser(image, source_id="p")
        for row in range(14):
            for col in range(24):
                cell = parser.extract_cell(row, col)
                self.assertGreater(cell.size, 0, f"cell ({row},{col}) is empty")


if __name__ == "__main__":
    unittest.main()
