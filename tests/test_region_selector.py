"""
Unit tests for the region-selector geometry and crop validation.

These exercise src/region_geometry.py directly.  The previous version of this
file recomputed the arithmetic inline and asserted the recomputation, so every
case passed regardless of what the selector actually did.

No GUI toolkit is imported, so the suite runs headless.
"""

import unittest
from pathlib import Path
import sys

import numpy as np

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from region_geometry import (
    MIN_SELECTION,
    Rect,
    RegionSelection,
)


class TestRect(unittest.TestCase):

    def test_width_and_height(self):
        r = Rect(10, 20, 110, 120)
        self.assertEqual((r.width, r.height), (100, 100))

    def test_normalised_swaps_inverted_corners(self):
        r = Rect(200, 150, 50, 50).normalised()
        self.assertEqual((r.x1, r.y1, r.x2, r.y2), (50, 50, 200, 150))

    def test_normalise_is_idempotent(self):
        r = Rect(200, 150, 50, 50).normalised()
        self.assertEqual(r.normalised(), r)

    def test_contains_interior_point(self):
        self.assertTrue(Rect(0, 0, 100, 100).contains(50, 50))

    def test_contains_excludes_edges_and_outside(self):
        r = Rect(0, 0, 100, 100)
        self.assertFalse(r.contains(0, 50))       # on the edge
        self.assertFalse(r.contains(150, 50))     # outside

    def test_contains_works_on_inverted_rect(self):
        self.assertTrue(Rect(100, 100, 0, 0).contains(50, 50))

    def test_corner_detection(self):
        r = Rect(10, 10, 210, 160)
        self.assertEqual(r.corner_at(10, 10), "nw")
        self.assertEqual(r.corner_at(210, 10), "ne")
        self.assertEqual(r.corner_at(10, 160), "sw")
        self.assertEqual(r.corner_at(210, 160), "se")

    def test_corner_detection_within_radius(self):
        r = Rect(10, 10, 210, 160)
        self.assertEqual(r.corner_at(14, 14), "nw")
        self.assertIsNone(r.corner_at(110, 85), "centre is not a corner")

    def test_resize_moves_the_named_corner_only(self):
        r = Rect(0, 0, 100, 100).with_corner_at("se", 200, 200)
        self.assertEqual((r.x1, r.y1, r.x2, r.y2), (0, 0, 200, 200))

    def test_resize_normalises_when_dragged_past_opposite_corner(self):
        r = Rect(0, 0, 100, 100).with_corner_at("nw", 150, 150)
        self.assertLessEqual(r.x1, r.x2)
        self.assertLessEqual(r.y1, r.y2)

    def test_resize_refuses_to_go_below_minimum(self):
        original = Rect(0, 0, 100, 100)
        shrunk = original.with_corner_at("se", 5, 5)
        self.assertEqual(shrunk, original, "allowed a selection below MIN_SELECTION")

    def test_resize_allows_exactly_minimum(self):
        r = Rect(0, 0, 100, 100).with_corner_at("se", MIN_SELECTION, MIN_SELECTION)
        self.assertEqual(r.width, MIN_SELECTION)

    def test_resize_rejects_unknown_corner(self):
        with self.assertRaises(ValueError):
            Rect(0, 0, 100, 100).with_corner_at("middle", 10, 10)

    def test_move_within_bounds(self):
        r = Rect(10, 10, 110, 110).moved_by(20, 30, (500, 500))
        self.assertEqual((r.x1, r.y1, r.x2, r.y2), (30, 40, 130, 140))

    def test_move_blocked_at_edge_preserves_size(self):
        r = Rect(0, 0, 100, 100).moved_by(-50, 0, (500, 500))
        self.assertEqual((r.x1, r.x2), (0, 100), "rect slid outside the preview")

    def test_move_axes_are_independent(self):
        """Blocked horizontally must still move vertically."""
        r = Rect(0, 10, 100, 110).moved_by(-50, 20, (500, 500))
        self.assertEqual(r.x1, 0, "x should be blocked")
        self.assertEqual(r.y1, 30, "y should still move")

    def test_move_blocked_at_far_edge(self):
        r = Rect(400, 0, 500, 100).moved_by(50, 0, (500, 500))
        self.assertEqual((r.x1, r.x2), (400, 500))


class TestRegionSelectionScaling(unittest.TestCase):

    def test_small_image_is_not_scaled_up(self):
        sel = RegionSelection((400, 300), (850, 550))
        self.assertEqual(sel.scale_factor, 1.0)
        self.assertEqual(sel.display_size, (400, 300))

    def test_large_image_scaled_to_fit(self):
        sel = RegionSelection((1600, 1200), (800, 600))
        self.assertAlmostEqual(sel.scale_factor, 0.5)
        self.assertEqual(sel.display_size, (800, 600))

    def test_scale_uses_the_more_constrained_axis(self):
        # Very wide image: width is the limiting factor.
        sel = RegionSelection((2000, 400), (1000, 600))
        self.assertAlmostEqual(sel.scale_factor, 0.5)

    def test_zero_size_rejected(self):
        with self.assertRaises(ValueError):
            RegionSelection((0, 100), (800, 600))

    def test_display_never_exceeds_the_limit(self):
        for size in ((3840, 2160), (1024, 4000), (7, 9)):
            sel = RegionSelection(size, (850, 550))
            w, h = sel.display_size
            self.assertLessEqual(w, 850)
            self.assertLessEqual(h, 550)


class TestCoordinateConversion(unittest.TestCase):
    """The crop must land on the pixels the user framed in the preview."""

    def test_unscaled_conversion_is_identity(self):
        sel = RegionSelection((400, 300), (850, 550))
        self.assertEqual(sel.to_original(Rect(50, 50, 200, 150)), (50, 50, 150, 100))

    def test_scaled_conversion_maps_back_to_original_pixels(self):
        sel = RegionSelection((1600, 1200), (800, 600))   # scale 0.5
        # A selection covering the middle of the preview...
        crop = sel.to_original(Rect(100, 100, 300, 250))
        # ...is twice as large in original coordinates.
        self.assertEqual(crop, (200, 200, 400, 300))

    def test_round_trip_is_stable(self):
        sel = RegionSelection((1600, 1200), (800, 600))
        crop = (200, 160, 480, 280)
        self.assertEqual(sel.to_original(sel.from_original(crop)), crop)

    def test_round_trip_on_unscaled_image(self):
        sel = RegionSelection((900, 700), (1000, 1000))
        crop = (10, 20, 480, 280)
        self.assertEqual(sel.to_original(sel.from_original(crop)), crop)

    def test_conversion_handles_inverted_selection(self):
        sel = RegionSelection((400, 300), (850, 550))
        self.assertEqual(sel.to_original(Rect(200, 150, 50, 50)), (50, 50, 150, 100))

    def test_default_rect_is_centred_and_inside(self):
        sel = RegionSelection((800, 600), (850, 550))
        rect = sel.default_rect()
        w, h = sel.display_size
        self.assertEqual(rect.x1, w - rect.x2, "not horizontally centred")
        self.assertEqual(rect.y1, h - rect.y2, "not vertically centred")

    def test_clamp_keeps_pointer_in_the_preview(self):
        sel = RegionSelection((800, 600), (850, 550))
        w, h = sel.display_size
        self.assertEqual(sel.clamp_to_display(-10, -10), (0, 0))
        self.assertEqual(sel.clamp_to_display(9999, 9999), (w, h))

    def test_cell_size_reflects_the_grid(self):
        sel = RegionSelection((480, 280), (850, 550))     # unscaled
        cell_w, cell_h = sel.cell_size(Rect(0, 0, 480, 280), 24, 14)
        self.assertAlmostEqual(cell_w, 20.0)
        self.assertAlmostEqual(cell_h, 20.0)


class TestCropApplication(unittest.TestCase):
    """WindowCapture._apply_crop clamps rather than raising."""

    def _capture(self, crop):
        from window_capture import WindowCapture
        # Build without __init__: it needs a real HWND.
        capture = WindowCapture.__new__(WindowCapture)
        capture.crop_region = crop
        return capture

    def test_crop_within_bounds(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        out = self._capture((100, 50, 400, 300))._apply_crop(img, 800, 600)
        self.assertEqual(out.shape, (300, 400, 3))

    def test_crop_clamped_to_window(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        out = self._capture((700, 500, 400, 300))._apply_crop(img, 800, 600)
        self.assertEqual(out.shape, (100, 100, 3))

    def test_crop_entirely_outside_is_ignored(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        out = self._capture((900, 700, 100, 100))._apply_crop(img, 800, 600)
        self.assertEqual(out.shape, img.shape, "expected the crop to be skipped")

    def test_crop_selects_the_right_pixels(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        img[50:350, 100:500] = 255
        out = self._capture((100, 50, 400, 300))._apply_crop(img, 800, 600)
        self.assertTrue((out == 255).all(), "crop landed on the wrong pixels")


if __name__ == "__main__":
    unittest.main()
