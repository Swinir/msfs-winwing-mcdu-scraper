"""
Unit tests for MCDU Parser, Template Matcher, and Auto Detector.
"""

import unittest
import numpy as np
from pathlib import Path
import sys
import tempfile

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from mcdu_parser import MCDUParser, TemplateMatcher
from mcdu_detector import detect_mcdu_region
from config import Config


class TestMCDUParser(unittest.TestCase):
    """Test cases for MCDUParser"""

    def setUp(self):
        # 24×14 grid, 20×20 px per cell → 480×280
        self.test_image = np.zeros((280, 480, 3), dtype=np.uint8)

    def test_parser_initialization(self):
        parser = MCDUParser(self.test_image)
        self.assertEqual(parser.columns, 24)
        self.assertEqual(parser.rows, 14)
        self.assertEqual(parser.cell_width, 20)
        self.assertEqual(parser.cell_height, 20)

    def test_extract_cell(self):
        parser = MCDUParser(self.test_image)
        cell = parser.extract_cell(0, 0)
        self.assertEqual(cell.shape, (20, 20, 3))

    def test_extract_cell_last(self):
        parser = MCDUParser(self.test_image)
        cell = parser.extract_cell(13, 23)
        self.assertEqual(cell.shape, (20, 20, 3))

    def test_color_detection_white(self):
        white_cell = np.ones((20, 20, 3), dtype=np.uint8) * 255
        parser = MCDUParser(self.test_image)
        self.assertEqual(parser.detect_color(white_cell), "w")

    def test_color_detection_cyan(self):
        cyan_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        cyan_cell[:, :, 1] = 200
        cyan_cell[:, :, 2] = 200
        parser = MCDUParser(self.test_image)
        self.assertEqual(parser.detect_color(cyan_cell), "c")

    def test_color_detection_green(self):
        green_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        green_cell[:, :, 1] = 200
        parser = MCDUParser(self.test_image)
        self.assertEqual(parser.detect_color(green_cell), "g")

    def test_color_detection_amber(self):
        amber_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        amber_cell[:, :, 0] = 200   # R
        amber_cell[:, :, 1] = 140   # G
        amber_cell[:, :, 2] = 50    # B
        parser = MCDUParser(self.test_image)
        self.assertEqual(parser.detect_color(amber_cell), "a")

    def test_is_empty_cell(self):
        black_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        parser = MCDUParser(self.test_image)
        self.assertTrue(parser.is_empty_cell(black_cell))

    def test_is_not_empty_cell(self):
        bright_cell = np.ones((20, 20, 3), dtype=np.uint8) * 200
        parser = MCDUParser(self.test_image)
        self.assertFalse(parser.is_empty_cell(bright_cell))

    def test_is_small_font(self):
        parser = MCDUParser(self.test_image)
        self.assertFalse(parser.is_small_font(0))   # even → large
        self.assertTrue(parser.is_small_font(1))     # odd  → small
        self.assertFalse(parser.is_small_font(2))
        self.assertFalse(parser.is_small_font(13))   # scratchpad exception

    def test_parse_grid_empty(self):
        parser = MCDUParser(self.test_image)
        result = parser.parse_grid()
        self.assertEqual(len(result), 336)
        for cell_data in result:
            self.assertEqual(cell_data, [])

    def test_preprocess_cell_binary(self):
        """Preprocessing must return single-channel binary."""
        parser = MCDUParser(self.test_image)
        cell = np.zeros((20, 20, 3), dtype=np.uint8)
        cell[5:15, 5:15, :] = 200
        binary = parser._preprocess_cell(cell)
        self.assertEqual(len(binary.shape), 2)
        unique = set(np.unique(binary))
        self.assertTrue(unique.issubset({0, 255}))


class TestTemplateMatcher(unittest.TestCase):
    """Test cases for TemplateMatcher.

    Every matcher is pointed at a temp directory.  A bare ``TemplateMatcher()``
    would load the user's real ``templates/mcdu_templates.npz``, making these
    results depend on whether the app has ever been run on this machine.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _matcher(self, name: str = "templates.npz") -> TemplateMatcher:
        """An isolated matcher backed by a file under the temp directory."""
        return TemplateMatcher(template_path=self.tmp_path / name)

    def _make_glyph(self, char_code: int, size: tuple = (12, 18)):
        """Create a synthetic binary glyph for testing."""
        np.random.seed(char_code)
        glyph = np.zeros(size, dtype=np.uint8)
        # Draw a deterministic pattern based on char_code
        for i in range(char_code % 5 + 3):
            y = (char_code * (i + 1) * 7) % size[0]
            x = (char_code * (i + 1) * 13) % size[1]
            h = min(3, size[0] - y)
            w = min(4, size[1] - x)
            glyph[y:y + h, x:x + w] = 255
        return glyph

    def test_learn_and_recognize(self):
        matcher = self._matcher()
        glyph = self._make_glyph(65)  # 'A' pattern
        matcher.learn("A", glyph, confidence=1.0)
        matcher.learn("A", glyph, confidence=1.0)
        result = matcher.recognize(glyph)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "A")
        self.assertGreaterEqual(result[1], 0.78)

    def test_no_match_returns_none(self):
        matcher = self._matcher()
        glyph = self._make_glyph(66)
        result = matcher.recognize(glyph)
        self.assertIsNone(result)

    def test_low_confidence_not_learned(self):
        matcher = self._matcher()
        glyph = self._make_glyph(67)
        matcher.learn("C", glyph, confidence=0.1)
        self.assertEqual(matcher.template_count, 0)

    def test_duplicate_not_stored(self):
        matcher = self._matcher()
        glyph = self._make_glyph(68)
        matcher.learn("D", glyph)
        matcher.learn("D", glyph)  # exact duplicate
        self.assertEqual(matcher.template_count, 1)

    def test_save_and_load(self):
        matcher = self._matcher("roundtrip.npz")
        glyph_a = self._make_glyph(65)
        glyph_b = self._make_glyph(66)
        matcher.learn("A", glyph_a)
        matcher.learn("A", glyph_a)
        matcher.learn("B", glyph_b)
        matcher.learn("B", glyph_b)
        matcher.save()

        # A fresh matcher on the same path loads what was written.
        matcher2 = self._matcher("roundtrip.npz")
        self.assertEqual(matcher2.template_count, matcher.template_count)

    def test_fresh_matcher_ignores_unrelated_templates(self):
        """Two matchers on different paths must not see each other's glyphs."""
        first = self._matcher("one.npz")
        first.learn("A", self._make_glyph(65))
        first.learn("A", self._make_glyph(65))
        first.save()

        second = self._matcher("two.npz")
        self.assertEqual(second.template_count, 0)

    def test_default_path_is_not_used_when_path_given(self):
        matcher = self._matcher("explicit.npz")
        self.assertNotEqual(
            matcher._template_path, TemplateMatcher.DEFAULT_TEMPLATE_PATH
        )

    def test_hash_cache_exact_match(self):
        matcher = self._matcher()
        glyph = self._make_glyph(69)
        matcher.learn("E", glyph)
        matcher.learn("E", glyph)
        # Second recognition should hit hash cache
        r1 = matcher.recognize(glyph)
        r2 = matcher.recognize(glyph)
        self.assertEqual(r1, r2)
        self.assertEqual(r2[1], 1.0)  # hash cache returns confidence 1.0

    def test_max_templates_per_char(self):
        matcher = self._matcher()
        for i in range(10):
            glyph = self._make_glyph(70 + i * 100)
            matcher.learn("X", glyph)
        self.assertLessEqual(
            matcher.template_count,
            TemplateMatcher.MAX_TEMPLATES
        )


class TestAutoDetector(unittest.TestCase):
    """Test cases for MCDU auto-detection"""

    def test_empty_image_returns_none(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        result = detect_mcdu_region(img)
        self.assertIsNone(result)

    def test_text_on_black_background(self):
        """A bright rectangle on black should be detected."""
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        # Simulate MCDU: bright text area with good aspect ratio
        # Place text-like bright pixels in a 400×230 region (aspect ~1.74)
        x, y, w, h = 200, 150, 400, 230
        for row_i in range(14):
            ry = y + int(row_i * h / 14) + 2
            for col_i in range(24):
                cx = x + int(col_i * w / 24) + 2
                # Small bright blob
                img[ry:ry + 8, cx:cx + 6, :] = 200
        result = detect_mcdu_region(img)
        self.assertIsNotNone(result)
        rx, ry, rw, rh = result
        # Should be close to our drawn region
        self.assertGreater(rw, 100)
        self.assertGreater(rh, 50)

    def test_wrong_aspect_ratio_rejected(self):
        """A very tall thin region shouldn't be detected as MCDU."""
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        # Very narrow vertical stripe
        img[50:550, 395:405, :] = 200
        result = detect_mcdu_region(img)
        # Should be None because aspect < 1.1
        self.assertIsNone(result)


class TestConfig(unittest.TestCase):
    """Test cases for Config constants"""

    def test_constants(self):
        self.assertEqual(Config.CDU_COLUMNS, 24)
        self.assertEqual(Config.CDU_ROWS, 14)
        self.assertEqual(Config.CDU_CELLS, 336)

    def test_font_sizes(self):
        self.assertEqual(Config.FONT_SIZE_LARGE, 0)
        self.assertEqual(Config.FONT_SIZE_SMALL, 1)

    def test_color_codes(self):
        self.assertIn("w", Config.COLORS)
        self.assertIn("c", Config.COLORS)
        self.assertIn("g", Config.COLORS)
        self.assertEqual(Config.COLORS["w"], "white")
        self.assertEqual(Config.COLORS["c"], "cyan")


class TestGuiFrozenPathLogic(unittest.TestCase):
    """Test the PyInstaller frozen-path logic used in gui.py"""

    def test_frozen_path_resolves_to_meipass(self):
        import unittest.mock as mock
        fake_meipass = '/tmp/fake_meipass'
        with mock.patch.dict(sys.__dict__, {'frozen': True, '_MEIPASS': fake_meipass}):
            if getattr(sys, 'frozen', False):
                resolved = sys._MEIPASS
            else:
                resolved = str(Path(__file__).parent)
            self.assertEqual(resolved, fake_meipass)

    def test_non_frozen_path_resolves_to_file_parent(self):
        frozen = getattr(sys, 'frozen', False)
        self.assertFalse(frozen)
        if getattr(sys, 'frozen', False):
            resolved = sys._MEIPASS
        else:
            resolved = str(Path(__file__).parent)
        self.assertEqual(resolved, str(Path(__file__).parent))


if __name__ == '__main__':
    unittest.main()


class TestRowCacheScoping(unittest.TestCase):
    """Regression tests for the captain/co-pilot row-cache collision.

    The row-level OCR caches used to be keyed by row index alone.  Because
    both MCDUs are parsed in the same process, each display was served the
    other's cached OCR results.  They are now namespaced by ``source_id``.
    """

    def setUp(self):
        import mcdu_parser
        self.mod = mcdu_parser

        # Isolate the module-level caches for the duration of the test.
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()

        # Swap the module singleton for a matcher backed by a temp file, so
        # this test neither reads nor writes the user's real template store.
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved_matcher = mcdu_parser._template_matcher
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz"
        )
        mcdu_parser._template_matcher = self.matcher

        # parse_grid() short-circuits to a contour-only path when there is
        # no OCR engine *and* no templates.  Seed one template so the
        # caching path under test is actually reached.
        self.matcher.learn("A", self._seed_glyph())
        self.matcher.learn("A", self._seed_glyph())
        self.assertGreater(self.matcher.template_count, 0)

        # 24x14 grid at 20 px per cell.  Row 3, columns 0-9 carry a glyph
        # whose normalised form matches the seeded template, so the cells
        # are recognised and the row reaches the caching path under test.
        self.image = np.zeros((280, 480, 3), dtype=np.uint8)
        for col in range(10):
            x = col * 20
            self.image[65:75, x + 5:x + 15, :] = 220

    @staticmethod
    def _seed_glyph():
        """A centred 10x10 block — matches the cells drawn in setUp."""
        glyph = np.zeros((20, 20), dtype=np.uint8)
        glyph[5:15, 5:15] = 255
        return glyph

    def tearDown(self):
        self.mod._prev_row_imgs.clear()
        self.mod._prev_row_ocr.clear()
        self.mod._prev_row_imgs.update(self._saved_imgs)
        self.mod._prev_row_ocr.update(self._saved_ocr)
        self.mod._template_matcher = self._saved_matcher
        self._tmpdir.cleanup()

    def test_cache_keys_are_namespaced_by_source(self):
        parser = MCDUParser(self.image, source_id="captain")
        parser.parse_grid()
        self.assertTrue(self.mod._prev_row_imgs, "expected rows to be cached")
        for key in self.mod._prev_row_imgs:
            self.assertIsInstance(key, tuple)
            self.assertEqual(key[0], "captain")

    def test_two_sources_do_not_share_entries(self):
        MCDUParser(self.image, source_id="captain").parse_grid()
        MCDUParser(self.image, source_id="copilot").parse_grid()
        sources = {key[0] for key in self.mod._prev_row_imgs}
        self.assertEqual(sources, {"captain", "copilot"})

    def test_copilot_does_not_inherit_captain_cached_ocr(self):
        """The core regression: identical frames must not cross-contaminate."""
        # Prime the captain's cache with a sentinel character that could
        # never come out of parsing this image.  Seed it under *both* the
        # namespaced key and the bare row index, so this test reproduces
        # the collision whichever keying the implementation uses — that is
        # what makes it a regression test rather than a tautology.
        for row in range(14):
            row_img = self.image[row * 20:(row + 1) * 20, :].copy()
            for key in (("captain", row), row):
                self.mod._prev_row_imgs[key] = row_img
                self.mod._prev_row_ocr[key] = [("Z", 10.0)]

        # The co-pilot sees a pixel-identical frame.  Under the old keying
        # its rows matched the captain's cache and it emitted the captain's
        # characters instead of parsing its own.
        result = MCDUParser(self.image, source_id="copilot").parse_grid()

        emitted = {cell[0] for cell in result if cell}
        self.assertNotIn(
            "Z", emitted,
            "co-pilot inherited the captain's cached OCR result",
        )

    def test_same_source_still_uses_its_cache(self):
        """Namespacing must not defeat caching for a single source."""
        MCDUParser(self.image, source_id="captain").parse_grid()
        cached_before = dict(self.mod._prev_row_ocr)
        # An identical second frame should be served from cache, leaving the
        # stored entries untouched.
        MCDUParser(self.image, source_id="captain").parse_grid()
        self.assertEqual(
            set(cached_before), set(self.mod._prev_row_ocr),
            "second identical frame changed the cache key set",
        )


class TestTemplateAuthority(unittest.TestCase):
    """A confirmed template match must outrank the geometry heuristic.

    `_disambiguate_confusables` used to run on every emitted character,
    including ones the template matcher had already identified.  That capped
    recognition accuracy at the accuracy of the heuristic: a glyph the
    heuristic read wrong could never be corrected by learning, because the
    correction was re-applied on every frame.
    """

    # A solid block: the D/O branch of the heuristic reads this as 'D',
    # because its left edge is continuous and completely filled.
    @staticmethod
    def _block_cell():
        glyph = np.zeros((20, 20), dtype=np.uint8)
        glyph[5:15, 5:15] = 255
        return glyph

    def setUp(self):
        import mcdu_parser
        self.mod = mcdu_parser

        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()

        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved_matcher = mcdu_parser._template_matcher
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz"
        )
        mcdu_parser._template_matcher = self.matcher

        self.image = np.zeros((280, 480, 3), dtype=np.uint8)
        for col in range(10):
            x = col * 20
            self.image[65:75, x + 5:x + 15, :] = 220

    def tearDown(self):
        self.mod._prev_row_imgs.clear()
        self.mod._prev_row_ocr.clear()
        self.mod._prev_row_imgs.update(self._saved_imgs)
        self.mod._prev_row_ocr.update(self._saved_ocr)
        self.mod._template_matcher = self._saved_matcher
        self._tmpdir.cleanup()

    def test_heuristic_still_disagrees_with_the_label(self):
        """Guard: the premise of the test below actually holds."""
        from mcdu_parser import _disambiguate_confusables
        self.assertEqual(
            _disambiguate_confusables(self._block_cell(), "O"), "D",
            "premise broken — the heuristic no longer rewrites this glyph",
        )

    def test_template_label_survives_parse_grid(self):
        """The committed label wins over what the heuristic would decide."""
        # Commit directly so the label is not itself disambiguated on the
        # way in — this is exactly the case where the two disagree.
        glyph = self.matcher._extract_glyph(self._block_cell())
        self.matcher._commit_template("O", self.matcher._normalize(glyph))

        result = MCDUParser(self.image, source_id="t").parse_grid()
        emitted = {cell[0] for cell in result if cell}

        self.assertIn("O", emitted, "template label was discarded")
        self.assertNotIn(
            "D", emitted,
            "geometry heuristic overrode a confirmed template match",
        )

    def test_recognize_is_consistent_across_hash_and_ncc_paths(self):
        """The fast hash path and the NCC path must agree on the label."""
        cell = self._block_cell()
        glyph = self.matcher._extract_glyph(cell)
        self.matcher._commit_template("O", self.matcher._normalize(glyph))

        via_hash = self.matcher.recognize(cell)
        self.matcher._hash_cache.clear()   # force the NCC path
        via_ncc = self.matcher.recognize(cell)

        self.assertIsNotNone(via_hash)
        self.assertIsNotNone(via_ncc)
        self.assertEqual(
            via_hash[0], via_ncc[0],
            "hash-cache and NCC paths returned different characters",
        )
