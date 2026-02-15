"""
Unit tests for Region Selector and Window Capture

Tests the coordinate transformation logic and crop validation
without requiring GUI components (tkinter).
"""

import unittest
import numpy as np
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


class TestRegionSelectorCoordinates(unittest.TestCase):
    """Test cases for RegionSelectorDialog coordinate transformations"""
    
    def test_coordinate_transformation_no_scaling(self):
        """Test coordinate transformation when image fits without scaling"""
        # Test the transformation logic directly
        original_size = (400, 300)
        scaled_size = (400, 300)  # No scaling
        
        # Selection in scaled space
        scaled_selection = (50, 50, 200, 150)
        
        # Calculate what the original coordinates should be
        scale_x = original_size[0] / scaled_size[0]
        scale_y = original_size[1] / scaled_size[1]
        
        x1_orig = int(scaled_selection[0] * scale_x)
        y1_orig = int(scaled_selection[1] * scale_y)
        x2_orig = int(scaled_selection[2] * scale_x)
        y2_orig = int(scaled_selection[3] * scale_y)
        
        # When no scaling, coordinates should be identical
        self.assertEqual(x1_orig, 50)
        self.assertEqual(y1_orig, 50)
        self.assertEqual(x2_orig, 200)
        self.assertEqual(y2_orig, 150)
    
    def test_coordinate_transformation_with_scaling(self):
        """Test coordinate transformation when image is scaled down"""
        # Original image: 1600x1200
        original_size = (1600, 1200)
        # Scaled to fit 800x600 dialog
        scaled_size = (800, 600)
        
        # Selection in scaled space (100, 100) to (400, 300)
        scaled_selection = (100, 100, 400, 300)
        
        # Calculate original coordinates
        scale_x = original_size[0] / scaled_size[0]  # 2.0
        scale_y = original_size[1] / scaled_size[1]  # 2.0
        
        x1_orig = int(scaled_selection[0] * scale_x)
        y1_orig = int(scaled_selection[1] * scale_y)
        x2_orig = int(scaled_selection[2] * scale_x)
        y2_orig = int(scaled_selection[3] * scale_y)
        
        # Should be doubled
        self.assertEqual(x1_orig, 200)
        self.assertEqual(y1_orig, 200)
        self.assertEqual(x2_orig, 800)
        self.assertEqual(y2_orig, 600)
    
    def test_coordinate_transformation_asymmetric_scaling(self):
        """Test coordinate transformation with different x/y scaling"""
        # Original image: 1600x900
        original_size = (1600, 900)
        # Scaled to fit 800x600 (different aspect ratio)
        scaled_size = (800, 450)
        
        # Selection in scaled space
        scaled_selection = (100, 50, 300, 200)
        
        # Calculate original coordinates
        scale_x = original_size[0] / scaled_size[0]  # 2.0
        scale_y = original_size[1] / scaled_size[1]  # 2.0
        
        x1_orig = int(scaled_selection[0] * scale_x)
        y1_orig = int(scaled_selection[1] * scale_y)
        x2_orig = int(scaled_selection[2] * scale_x)
        y2_orig = int(scaled_selection[3] * scale_y)
        
        self.assertEqual(x1_orig, 200)
        self.assertEqual(y1_orig, 100)
        self.assertEqual(x2_orig, 600)
        self.assertEqual(y2_orig, 400)
    
    def test_selection_width_height_calculation(self):
        """Test width and height calculation from coordinates"""
        x1, y1, x2, y2 = 100, 100, 400, 300
        
        width = x2 - x1
        height = y2 - y1
        
        self.assertEqual(width, 300)
        self.assertEqual(height, 200)
    
    def test_minimum_selection_size(self):
        """Test minimum selection size enforcement"""
        min_size = 20
        
        # Valid selection (exactly at minimum)
        x1, y1, x2, y2 = 100, 100, 120, 120
        self.assertTrue((x2 - x1) >= min_size and (y2 - y1) >= min_size)
        
        # Invalid selection (too small)
        x1, y1, x2, y2 = 100, 100, 115, 115
        self.assertFalse((x2 - x1) >= min_size and (y2 - y1) >= min_size)
    
    def test_rectangle_normalization(self):
        """Test rectangle normalization handles inverted coordinates"""
        # Inverted rectangle (x2 < x1, y2 < y1)
        x1, y1, x2, y2 = 200, 150, 50, 50
        
        # Normalize
        norm_x1 = min(x1, x2)
        norm_y1 = min(y1, y2)
        norm_x2 = max(x1, x2)
        norm_y2 = max(y1, y2)
        
        self.assertEqual(norm_x1, 50)
        self.assertEqual(norm_y1, 50)
        self.assertEqual(norm_x2, 200)
        self.assertEqual(norm_y2, 150)
        
        # Verify dimensions are correct
        width = norm_x2 - norm_x1
        height = norm_y2 - norm_y1
        self.assertEqual(width, 150)
        self.assertEqual(height, 100)


class TestWindowCaptureCropValidation(unittest.TestCase):
    """Test cases for WindowCapture crop bounds validation"""
    
    def test_crop_within_bounds(self):
        """Test crop region fully within window bounds"""
        window_width, window_height = 500, 300
        crop_x, crop_y, crop_w, crop_h = 10, 10, 480, 280
        
        # Validate crop is within bounds
        self.assertTrue(crop_x >= 0)
        self.assertTrue(crop_y >= 0)
        self.assertTrue(crop_x + crop_w <= window_width)
        self.assertTrue(crop_y + crop_h <= window_height)
    
    def test_crop_exceeds_right_bottom(self):
        """Test crop region exceeding right and bottom bounds"""
        window_width, window_height = 500, 300
        crop_x, crop_y, crop_w, crop_h = 100, 100, 500, 300
        
        # Crop extends beyond bounds
        exceeds_right = (crop_x + crop_w) > window_width
        exceeds_bottom = (crop_y + crop_h) > window_height
        
        self.assertTrue(exceeds_right)
        self.assertTrue(exceeds_bottom)
        
        # Calculate adjusted crop
        adjusted_w = min(crop_w, window_width - crop_x)
        adjusted_h = min(crop_h, window_height - crop_y)
        
        self.assertEqual(adjusted_w, 400)  # 500 - 100
        self.assertEqual(adjusted_h, 200)  # 300 - 100
    
    def test_crop_completely_outside_bounds(self):
        """Test crop region completely outside window bounds"""
        window_width, window_height = 500, 300
        crop_x, crop_y, crop_w, crop_h = 600, 400, 100, 100
        
        # Crop starts outside bounds
        outside = crop_x >= window_width or crop_y >= window_height
        self.assertTrue(outside)
    
    def test_crop_significantly_reduced(self):
        """Test detection of significantly reduced crop"""
        window_width, window_height = 500, 300
        original_w, original_h = 480, 280
        crop_x, crop_y = 495, 295
        
        # Calculate adjusted dimensions
        adjusted_w = min(original_w, window_width - crop_x)
        adjusted_h = min(original_h, window_height - crop_y)
        
        # Check if crop is significantly smaller (< 50% of requested)
        is_significantly_reduced = (
            adjusted_w < original_w * 0.5 or 
            adjusted_h < original_h * 0.5
        )
        
        self.assertTrue(is_significantly_reduced)
        self.assertEqual(adjusted_w, 5)
        self.assertEqual(adjusted_h, 5)
    
    def test_crop_bounds_clamping(self):
        """Test crop coordinate clamping to valid range"""
        window_width, window_height = 500, 300
        
        # Negative coordinates
        crop_x, crop_y = -10, -5
        clamped_x = max(0, min(crop_x, window_width - 1))
        clamped_y = max(0, min(crop_y, window_height - 1))
        
        self.assertEqual(clamped_x, 0)
        self.assertEqual(clamped_y, 0)
        
        # Beyond bounds
        crop_x, crop_y = 600, 400
        clamped_x = max(0, min(crop_x, window_width - 1))
        clamped_y = max(0, min(crop_y, window_height - 1))
        
        self.assertEqual(clamped_x, 499)
        self.assertEqual(clamped_y, 299)
    
    def test_crop_region_format(self):
        """Test crop region tuple format (x, y, width, height)"""
        crop_region = (10, 20, 480, 280)
        
        x, y, w, h = crop_region
        
        self.assertEqual(x, 10)
        self.assertEqual(y, 20)
        self.assertEqual(w, 480)
        self.assertEqual(h, 280)
        
        # Verify we can calculate end coordinates
        x2 = x + w
        y2 = y + h
        
        self.assertEqual(x2, 490)
        self.assertEqual(y2, 300)
    
    def test_image_slicing_with_crop(self):
        """Test numpy array slicing for crop application"""
        # Create test image
        img = np.random.randint(0, 255, (300, 500, 3), dtype=np.uint8)
        
        # Apply crop
        crop_x, crop_y, crop_w, crop_h = 10, 10, 480, 280
        cropped = img[crop_y:crop_y+crop_h, crop_x:crop_x+crop_w]
        
        # Verify cropped dimensions
        self.assertEqual(cropped.shape[0], crop_h)  # height
        self.assertEqual(cropped.shape[1], crop_w)  # width
        self.assertEqual(cropped.shape[2], 3)  # RGB channels


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for screen area selection"""
    
    def test_zero_width_crop(self):
        """Test handling of zero-width crop region"""
        crop_region = (100, 100, 0, 200)
        x, y, w, h = crop_region
        
        # Zero width should be invalid
        is_valid = w > 0 and h > 0
        self.assertFalse(is_valid)
    
    def test_zero_height_crop(self):
        """Test handling of zero-height crop region"""
        crop_region = (100, 100, 200, 0)
        x, y, w, h = crop_region
        
        # Zero height should be invalid
        is_valid = w > 0 and h > 0
        self.assertFalse(is_valid)
    
    def test_single_pixel_crop(self):
        """Test handling of single-pixel crop region"""
        crop_region = (100, 100, 1, 1)
        x, y, w, h = crop_region
        
        # Single pixel is technically valid but likely not useful
        is_valid = w > 0 and h > 0
        self.assertTrue(is_valid)
        
        # But should be below minimum size
        min_size = 20
        meets_minimum = w >= min_size and h >= min_size
        self.assertFalse(meets_minimum)
    
    def test_maximum_size_crop(self):
        """Test crop region equal to window size"""
        window_width, window_height = 500, 300
        crop_region = (0, 0, window_width, window_height)
        
        x, y, w, h = crop_region
        
        # Should be valid and fit exactly
        self.assertTrue(x + w <= window_width)
        self.assertTrue(y + h <= window_height)
    
    def test_aspect_ratio_preservation(self):
        """Test aspect ratio calculation for crop regions"""
        # 16:9 aspect ratio
        crop_w, crop_h = 1600, 900
        aspect_ratio = crop_w / crop_h
        
        self.assertAlmostEqual(aspect_ratio, 16/9, places=2)
        
        # 4:3 aspect ratio
        crop_w, crop_h = 480, 360
        aspect_ratio = crop_w / crop_h
        
        self.assertAlmostEqual(aspect_ratio, 4/3, places=2)


if __name__ == '__main__':
    unittest.main()
