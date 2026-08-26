"""
Aircraft profiles: non-24x14 grids, per-profile template stores, padding.

The scraper is aircraft-agnostic — it OCRs pixels and learns glyphs — so
what profiles must get right is: grid dimensions flowing through detection
and parsing, the small-font convention, padding a smaller grid out to the
fixed 24x14 hardware, and keeping each font family's learned templates in
its own store.
"""

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import mcdu_parser
from aircraft_profiles import (
    DEFAULT_PROFILE_ID,
    KNOWN_FONTS,
    PROFILES,
    SMALL_FONT_RULES,
    get_profile,
)
from mcdu_detector import detect_mcdu_region
from mcdu_parser import MCDUParser, TemplateMatcher, set_template_store
from mcdu_fixtures import (
    embed_in_window,
    find_mono_font,
    grid_accuracy,
    region_iou,
    render_mcdu,
    uns1_page,
)
from pipeline import HARDWARE_COLUMNS, HARDWARE_ROWS, pad_to_hardware


class TestProfileDefinitions(unittest.TestCase):
    """The built-in profiles must be internally consistent."""

    def test_default_profile_exists(self):
        self.assertIn(DEFAULT_PROFILE_ID, PROFILES)

    def test_unknown_id_falls_back_to_default(self):
        self.assertEqual(get_profile("does-not-exist").id, DEFAULT_PROFILE_ID)

    def test_grids_are_sane(self):
        for profile in PROFILES.values():
            self.assertGreaterEqual(profile.columns, 8, profile.id)
            self.assertLessEqual(profile.columns, HARDWARE_COLUMNS, profile.id)
            self.assertGreaterEqual(profile.rows, 4, profile.id)
            self.assertLessEqual(profile.rows, HARDWARE_ROWS, profile.id)

    def test_fonts_are_ones_mobiflight_ships(self):
        """An unknown font name is silently ignored by MobiFlight's
        FontLoader, leaving the previous font loaded — so only ship names
        that exist as .dat files."""
        for profile in PROFILES.values():
            self.assertIn(profile.font, KNOWN_FONTS, profile.id)

    def test_small_font_rules_are_known(self):
        for profile in PROFILES.values():
            self.assertIn(profile.small_font_rule, SMALL_FONT_RULES, profile.id)

    def test_template_stores_are_distinct(self):
        """Boeing glyphs must never be matched against Airbus templates."""
        paths = [profile.template_path() for profile in PROFILES.values()]
        self.assertEqual(len(paths), len(set(paths)),
                         "two profiles share a template store")

    def test_airbus_keeps_the_legacy_store(self):
        """Templates learned before profiles existed were all Airbus."""
        self.assertEqual(PROFILES["airbus"].template_path(),
                         TemplateMatcher.DEFAULT_TEMPLATE_PATH)


class TestPadding(unittest.TestCase):
    """Smaller grids must land top-left in the fixed hardware grid."""

    @staticmethod
    def _grid(columns, rows, char="X"):
        return [[char, "g", 0] for _ in range(columns * rows)]

    def test_full_size_passes_through(self):
        cells = self._grid(24, 14)
        self.assertIs(pad_to_hardware(cells, 24, 14), cells)

    def test_output_is_always_the_hardware_size(self):
        padded = pad_to_hardware(self._grid(24, 10), 24, 10)
        self.assertEqual(len(padded), HARDWARE_COLUMNS * HARDWARE_ROWS)

    def test_content_lands_top_left(self):
        cells = self._grid(20, 10)
        padded = pad_to_hardware(cells, 20, 10)
        for row in range(10):
            for col in range(20):
                self.assertEqual(
                    padded[row * HARDWARE_COLUMNS + col],
                    cells[row * 20 + col],
                    f"cell ({row},{col}) moved during padding",
                )

    def test_area_outside_the_profile_grid_is_empty(self):
        padded = pad_to_hardware(self._grid(20, 10), 20, 10)
        for row in range(HARDWARE_ROWS):
            for col in range(HARDWARE_COLUMNS):
                if row >= 10 or col >= 20:
                    self.assertEqual(padded[row * HARDWARE_COLUMNS + col], [],
                                     f"padding at ({row},{col}) is not empty")

    def test_short_input_is_tolerated(self):
        padded = pad_to_hardware([["A", "g", 0]], 24, 10)
        self.assertEqual(len(padded), HARDWARE_COLUMNS * HARDWARE_ROWS)
        self.assertEqual(padded[0], ["A", "g", 0])


class TestSmallFontRules(unittest.TestCase):

    def test_all_large_never_reports_small(self):
        image = np.zeros((200, 480, 3), dtype=np.uint8)
        parser = MCDUParser(image, columns=24, rows=10,
                            small_font_rule="all_large")
        for row in range(10):
            self.assertFalse(parser.is_small_font(row))

    def test_labels_small_generalises_the_last_row(self):
        """The scratchpad is the LAST row large, whatever the grid height."""
        image = np.zeros((200, 480, 3), dtype=np.uint8)
        parser = MCDUParser(image, columns=24, rows=10,
                            small_font_rule="labels_small")
        self.assertTrue(parser.is_small_font(1))
        self.assertFalse(parser.is_small_font(9),
                         "the last row must render large")

    def test_default_grid_unchanged(self):
        image = np.zeros((280, 480, 3), dtype=np.uint8)
        parser = MCDUParser(image)
        self.assertTrue(parser.is_small_font(1))
        self.assertFalse(parser.is_small_font(13))


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestUns1EndToEnd(unittest.TestCase):
    """Detect, parse and pad a UNS-1 style 24x10 green-phosphor page."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "uns1.npz")
        mcdu_parser._template_matcher = self.matcher

        self.page = uns1_page()
        self.screen = render_mcdu(self.page, cell_size=(18, 26))

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _teach(self):
        parser = MCDUParser(self.screen, columns=24, rows=10,
                            source_id="teach", small_font_rule="all_large")
        for row, line in enumerate(self.page.padded()):
            for col, char in enumerate(line):
                if char == " ":
                    continue
                binary = parser._preprocess_cell(parser.extract_cell(row, col))
                self.matcher.learn(char, binary, confidence=1.0)
                self.matcher.learn(char, binary, confidence=1.0)

    def test_detector_finds_a_24x10_grid(self):
        window, truth = embed_in_window(self.screen, chrome=True)
        found = detect_mcdu_region(window, columns=24, rows=10)
        self.assertIsNotNone(found, "no 24x10 grid detected")
        self.assertGreater(region_iou(found, truth), 0.93,
                           f"got {found}, want {truth}")

    def test_recognition_on_a_24x10_grid(self):
        self._teach()
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(self.screen, columns=24, rows=10,
                            source_id="uns1",
                            small_font_rule="all_large").parse_grid()
        score = grid_accuracy(self.page.expected_cells(), parsed)
        self.assertGreater(
            score["char_accuracy"], 0.95,
            f"{score['char_accuracy']:.1%}, confusions={score['confusions']}",
        )

    def test_every_cell_is_large_and_green(self):
        self._teach()
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(self.screen, columns=24, rows=10,
                            source_id="uns1g",
                            small_font_rule="all_large").parse_grid()
        for cell in parsed:
            if cell:
                self.assertEqual(cell[2], 0, "UNS-1 renders one size only")
                self.assertEqual(cell[1], "g", "green phosphor display")

    def test_padded_payload_fits_the_hardware(self):
        self._teach()
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(self.screen, columns=24, rows=10,
                            source_id="uns1p",
                            small_font_rule="all_large").parse_grid()
        padded = pad_to_hardware(parsed, 24, 10)
        self.assertEqual(len(padded), 336)
        # Rows 10-13 of the hardware grid must be blank.
        for index in range(10 * 24, 336):
            self.assertEqual(padded[index], [])


class TestTemplateStoreSwitching(unittest.TestCase):
    """Glyphs learned under one profile must not leak into another."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved_matcher = mcdu_parser._template_matcher
        self._saved_path = mcdu_parser._template_store_path

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved_matcher
        mcdu_parser._template_store_path = self._saved_path
        self._tmpdir.cleanup()

    @staticmethod
    def _glyph():
        glyph = np.zeros((20, 24), dtype=np.uint8)
        glyph[5:19, 6:16] = 255
        return glyph

    def test_switching_isolates_stores(self):
        base = Path(self._tmpdir.name)
        set_template_store(base / "airbus.npz")
        matcher = mcdu_parser._get_template_matcher()
        matcher.learn("A", self._glyph(), confidence=1.0)
        matcher.learn("A", self._glyph(), confidence=1.0)
        self.assertEqual(matcher.template_count, 1)

        set_template_store(base / "boeing.npz")
        self.assertEqual(
            mcdu_parser._get_template_matcher().template_count, 0,
            "Boeing store inherited Airbus glyphs",
        )

    def test_switching_back_restores_learned_glyphs(self):
        """The outgoing store is saved on switch, so nothing is lost."""
        base = Path(self._tmpdir.name)
        set_template_store(base / "airbus.npz")
        matcher = mcdu_parser._get_template_matcher()
        matcher.learn("A", self._glyph(), confidence=1.0)
        matcher.learn("A", self._glyph(), confidence=1.0)

        set_template_store(base / "boeing.npz")
        set_template_store(base / "airbus.npz")
        self.assertEqual(
            mcdu_parser._get_template_matcher().template_count, 1,
            "glyphs were lost when switching away and back",
        )

    def test_same_store_is_a_noop(self):
        base = Path(self._tmpdir.name)
        set_template_store(base / "a.npz")
        first = mcdu_parser._get_template_matcher()
        set_template_store(base / "a.npz")
        self.assertIs(mcdu_parser._get_template_matcher(), first)


if __name__ == "__main__":
    unittest.main()
