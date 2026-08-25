"""
Unit tests for configuration loading, in particular the crop region.
"""

import tempfile
import unittest
from pathlib import Path
import sys

import yaml

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from config import Config


BASE = {
    "mcdu": {
        "captain": {"enabled": True, "window_title": "Sim"},
        "copilot": {"enabled": False},
    },
    "mobiflight": {
        "captain_url": "ws://localhost:8320/winwing/cdu-captain",
        "copilot_url": "ws://localhost:8320/winwing/cdu-co-pilot",
    },
    "performance": {"capture_fps": 30},
}


def make_config(**overrides) -> Config:
    """Write a temp config.yaml built from BASE plus overrides."""
    import copy
    data = copy.deepcopy(BASE)
    for section, values in overrides.items():
        data.setdefault(section, {})
        data[section].update(values)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8",
    )
    yaml.safe_dump(data, tmp)
    tmp.close()
    return Config(tmp.name)


class TestCropRegion(unittest.TestCase):
    """Crop config is what makes the CLI usable, so it must fail loudly."""

    def test_absent_crop_returns_none(self):
        self.assertIsNone(make_config().get_crop_region("captain"))

    def test_valid_crop_returned_as_tuple(self):
        cfg = make_config(mcdu={
            "captain": {"enabled": True, "window_title": "Sim",
                        "crop": {"x": 10, "y": 20, "width": 480, "height": 280}},
        })
        self.assertEqual(cfg.get_crop_region("captain"), (10, 20, 480, 280))

    def test_zero_origin_is_valid(self):
        cfg = make_config(mcdu={
            "captain": {"enabled": True, "window_title": "Sim",
                        "crop": {"x": 0, "y": 0, "width": 4, "height": 4}},
        })
        self.assertEqual(cfg.get_crop_region("captain"), (0, 0, 4, 4))

    def test_missing_key_raises(self):
        cfg = make_config(mcdu={
            "captain": {"enabled": True, "window_title": "Sim",
                        "crop": {"x": 0, "y": 0, "width": 480}},
        })
        with self.assertRaises(ValueError) as ctx:
            cfg.get_crop_region("captain")
        self.assertIn("height", str(ctx.exception))

    def test_zero_width_raises(self):
        cfg = make_config(mcdu={
            "captain": {"enabled": True, "window_title": "Sim",
                        "crop": {"x": 0, "y": 0, "width": 0, "height": 280}},
        })
        with self.assertRaises(ValueError):
            cfg.get_crop_region("captain")

    def test_negative_origin_raises(self):
        cfg = make_config(mcdu={
            "captain": {"enabled": True, "window_title": "Sim",
                        "crop": {"x": -5, "y": 0, "width": 480, "height": 280}},
        })
        with self.assertRaises(ValueError):
            cfg.get_crop_region("captain")

    def test_non_numeric_raises(self):
        cfg = make_config(mcdu={
            "captain": {"enabled": True, "window_title": "Sim",
                        "crop": {"x": "left", "y": 0,
                                 "width": 480, "height": 280}},
        })
        with self.assertRaises(ValueError):
            cfg.get_crop_region("captain")

    def test_missing_copilot_section_is_safe(self):
        cfg = make_config(mcdu={"captain": BASE["mcdu"]["captain"]})
        self.assertIsNone(cfg.get_crop_region("copilot"))


class TestPerformanceSettings(unittest.TestCase):

    def test_fps_clamped_to_range(self):
        self.assertEqual(make_config(performance={"capture_fps": 0}).get_capture_fps(), 1)
        self.assertEqual(make_config(performance={"capture_fps": 999}).get_capture_fps(), 120)

    def test_enable_caching_defaults_true(self):
        self.assertTrue(make_config().get_enable_caching())

    def test_enable_caching_respected(self):
        cfg = make_config(performance={"capture_fps": 30, "enable_caching": False})
        self.assertFalse(cfg.get_enable_caching())


if __name__ == "__main__":
    unittest.main()
