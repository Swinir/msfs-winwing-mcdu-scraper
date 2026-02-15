"""
Unit tests for MCDU Parser
"""

import unittest
import numpy as np
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from mcdu_parser import MCDUParser
from config import Config


class TestMCDUParser(unittest.TestCase):
    """Test cases for MCDU Parser"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create a simple test image (24x14 cells, 20x20 pixels each)
        self.test_image = np.zeros((280, 480, 3), dtype=np.uint8)
        
    def test_parser_initialization(self):
        """Test parser initializes correctly"""
        parser = MCDUParser(self.test_image)
        
        self.assertEqual(parser.columns, 24)
        self.assertEqual(parser.rows, 14)
        self.assertEqual(parser.cell_width, 20)
        self.assertEqual(parser.cell_height, 20)
    
    def test_extract_cell(self):
        """Test cell extraction"""
        parser = MCDUParser(self.test_image)
        
        # Extract first cell (row 0, col 0)
        cell = parser.extract_cell(0, 0)
        
        self.assertEqual(cell.shape, (20, 20, 3))
    
    def test_color_detection_white(self):
        """Test white color detection"""
        # Create white cell
        white_cell = np.ones((20, 20, 3), dtype=np.uint8) * 255
        
        parser = MCDUParser(self.test_image)
        color = parser.detect_color(white_cell)
        
        self.assertEqual(color, "w")
    
    def test_color_detection_cyan(self):
        """Test cyan color detection"""
        # Create cyan cell (low R, high G, high B)
        cyan_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        cyan_cell[:, :, 1] = 200  # Green
        cyan_cell[:, :, 2] = 200  # Blue
        
        parser = MCDUParser(self.test_image)
        color = parser.detect_color(cyan_cell)
        
        self.assertEqual(color, "c")
    
    def test_color_detection_green(self):
        """Test green color detection"""
        # Create green cell
        green_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        green_cell[:, :, 1] = 200  # Green only
        
        parser = MCDUParser(self.test_image)
        color = parser.detect_color(green_cell)
        
        self.assertEqual(color, "g")
    
    def test_is_empty_cell(self):
        """Test empty cell detection"""
        # Create black cell
        black_cell = np.zeros((20, 20, 3), dtype=np.uint8)
        
        parser = MCDUParser(self.test_image)
        is_empty = parser.is_empty_cell(black_cell)
        
        self.assertTrue(is_empty)
    
    def test_is_small_font(self):
        """Test font size determination"""
        parser = MCDUParser(self.test_image)
        
        # Row 0 should be large (even)
        self.assertFalse(parser.is_small_font(0))
        
        # Row 1 should be small (odd)
        self.assertTrue(parser.is_small_font(1))
        
        # Row 2 should be large (even)
        self.assertFalse(parser.is_small_font(2))
        
        # Row 13 should be large (scratchpad)
        self.assertFalse(parser.is_small_font(13))
    
    def test_parse_grid_empty(self):
        """Test parsing empty grid"""
        parser = MCDUParser(self.test_image)
        result = parser.parse_grid()
        
        # Should return 336 elements (24 * 14)
        self.assertEqual(len(result), 336)
        
        # All should be empty (black image)
        for cell_data in result:
            self.assertEqual(cell_data, [])


class TestConfig(unittest.TestCase):
    """Test cases for Config"""
    
    def test_constants(self):
        """Test configuration constants"""
        self.assertEqual(Config.CDU_COLUMNS, 24)
        self.assertEqual(Config.CDU_ROWS, 14)
        self.assertEqual(Config.CDU_CELLS, 336)
        
    def test_font_sizes(self):
        """Test font size constants"""
        self.assertEqual(Config.FONT_SIZE_LARGE, 0)
        self.assertEqual(Config.FONT_SIZE_SMALL, 1)
    
    def test_color_codes(self):
        """Test color code mapping"""
        self.assertIn("w", Config.COLORS)
        self.assertIn("c", Config.COLORS)
        self.assertIn("g", Config.COLORS)
        self.assertEqual(Config.COLORS["w"], "white")
        self.assertEqual(Config.COLORS["c"], "cyan")


if __name__ == '__main__':
    unittest.main()
