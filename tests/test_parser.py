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
    """Test cases for TemplateMatcher"""

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
        matcher = TemplateMatcher()
        glyph = self._make_glyph(65)  # 'A' pattern
        matcher.learn("A", glyph, confidence=1.0)
        result = matcher.recognize(glyph)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "A")
        self.assertGreaterEqual(result[1], 0.78)

    def test_no_match_returns_none(self):
        matcher = TemplateMatcher()
        glyph = self._make_glyph(66)
        result = matcher.recognize(glyph)
        self.assertIsNone(result)

    def test_low_confidence_not_learned(self):
        matcher = TemplateMatcher()
        glyph = self._make_glyph(67)
        matcher.learn("C", glyph, confidence=0.1)
        self.assertEqual(matcher.template_count, 0)

    def test_duplicate_not_stored(self):
        matcher = TemplateMatcher()
        glyph = self._make_glyph(68)
        matcher.learn("D", glyph)
        matcher.learn("D", glyph)  # exact duplicate
        self.assertEqual(len(matcher._templates.get("D", [])), 1)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            matcher = TemplateMatcher()
            matcher._template_path = Path(tmpdir) / "test_templates.npz"
            glyph_a = self._make_glyph(65)
            glyph_b = self._make_glyph(66)
            matcher.learn("A", glyph_a)
            matcher.learn("B", glyph_b)
            matcher.save()

            # Load into a fresh matcher
            matcher2 = TemplateMatcher()
            matcher2._template_path = Path(tmpdir) / "test_templates.npz"
            matcher2._load()
            self.assertEqual(matcher2.template_count, matcher.template_count)

    def test_hash_cache_exact_match(self):
        matcher = TemplateMatcher()
        glyph = self._make_glyph(69)
        matcher.learn("E", glyph)
        # Second recognition should hit hash cache
        r1 = matcher.recognize(glyph)
        r2 = matcher.recognize(glyph)
        self.assertEqual(r1, r2)
        self.assertEqual(r2[1], 1.0)  # hash cache returns confidence 1.0

    def test_max_templates_per_char(self):
        matcher = TemplateMatcher()
        for i in range(10):
            glyph = self._make_glyph(70 + i * 100)
            matcher.learn("X", glyph)
        self.assertLessEqual(
            len(matcher._templates.get("X", [])),
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
