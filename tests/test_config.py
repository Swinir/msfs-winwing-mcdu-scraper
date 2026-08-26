"""
Unit tests for configuration loading.

The window to capture and the crop region are chosen in the GUI, so they are
no longer configuration; what remains is where to send the result and how
hard to work.
"""

import copy
import tempfile
import unittest
from pathlib import Path
import sys

import yaml

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from config import Config


BASE = {
    "mobiflight": {
        "captain_url": "ws://localhost:8320/winwing/cdu-captain",
        "copilot_url": "ws://localhost:8320/winwing/cdu-co-pilot",
    },
    "performance": {"capture_fps": 30},
}


def make_config(**overrides) -> Config:
    """Write a temp config.yaml built from BASE plus overrides."""
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


def write_raw(data) -> str:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8",
    )
    yaml.safe_dump(data, tmp)
    tmp.close()
    return tmp.name


class TestValidation(unittest.TestCase):

    def test_minimal_config_loads(self):
        cfg = make_config()
        self.assertEqual(cfg.get_capture_fps(), 30)

    def test_missing_mobiflight_section_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Config(write_raw({"performance": {"capture_fps": 30}}))
        self.assertIn("mobiflight", str(ctx.exception))

    def test_missing_performance_section_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Config(write_raw({"mobiflight": BASE["mobiflight"]}))
        self.assertIn("performance", str(ctx.exception))

    def test_mcdu_section_is_no_longer_required(self):
        """Window and crop moved into the GUI, so the section went away."""
        cfg = Config(write_raw({
            "mobiflight": BASE["mobiflight"],
            "performance": {"capture_fps": 30},
        }))
        self.assertEqual(cfg.get_font(), "AirbusThales")

    def test_stale_mcdu_section_is_ignored(self):
        """An old config file must still load rather than break on startup."""
        cfg = Config(write_raw({
            "mcdu": {"captain": {"enabled": True,
                                 "window_title": "Microsoft Flight Simulator",
                                 "crop": {"x": 0, "y": 0,
                                          "width": 480, "height": 280}}},
            "mobiflight": BASE["mobiflight"],
            "performance": {"capture_fps": 30},
        }))
        self.assertEqual(cfg.get_capture_fps(), 30)


class TestWebSocketUrls(unittest.TestCase):

    def test_captain_url(self):
        self.assertEqual(make_config().get_captain_url(),
                         "ws://localhost:8320/winwing/cdu-captain")

    def test_copilot_url(self):
        self.assertEqual(make_config().get_copilot_url(),
                         "ws://localhost:8320/winwing/cdu-co-pilot")

    def test_missing_captain_url_raises(self):
        cfg = Config(write_raw({
            "mobiflight": {"copilot_url": "ws://x"},
            "performance": {"capture_fps": 30},
        }))
        with self.assertRaises(ValueError):
            cfg.get_captain_url()

    def test_missing_copilot_url_raises(self):
        """The co-pilot MCDU cannot start without somewhere to send it."""
        cfg = Config(write_raw({
            "mobiflight": {"captain_url": "ws://x"},
            "performance": {"capture_fps": 30},
        }))
        with self.assertRaises(ValueError):
            cfg.get_copilot_url()

    def test_the_two_urls_differ_by_default(self):
        cfg = make_config()
        self.assertNotEqual(cfg.get_captain_url(), cfg.get_copilot_url())


class TestPerformanceSettings(unittest.TestCase):

    def test_fps_clamped_to_range(self):
        self.assertEqual(make_config(performance={"capture_fps": 0}).get_capture_fps(), 1)
        self.assertEqual(make_config(performance={"capture_fps": 999}).get_capture_fps(), 120)

    def test_enable_caching_defaults_true(self):
        self.assertTrue(make_config().get_enable_caching())

    def test_enable_caching_respected(self):
        cfg = make_config(performance={"capture_fps": 30, "enable_caching": False})
        self.assertFalse(cfg.get_enable_caching())

    def test_font_default(self):
        self.assertEqual(make_config().get_font(), "AirbusThales")

    def test_font_override(self):
        cfg = make_config(mobiflight={"font": "Boeing"})
        self.assertEqual(cfg.get_font(), "Boeing")

    def test_max_retries_default(self):
        self.assertEqual(make_config().get_max_retries(), 3)


class TestShippedExample(unittest.TestCase):
    """config.yaml.example must actually load."""

    def test_example_config_is_valid(self):
        example = Path(__file__).parent.parent / "config.yaml.example"
        cfg = Config(str(example))
        self.assertTrue(cfg.get_captain_url())
        self.assertTrue(cfg.get_copilot_url())
        self.assertEqual(cfg.get_font(), "AirbusThales")
        self.assertGreater(cfg.get_capture_fps(), 0)

    def test_example_has_no_settings_nothing_reads(self):
        """Every key in the example must map to a getter.

        Silent no-op settings are worse than absent ones (see ISSUES.md #7).
        """
        example = Path(__file__).parent.parent / "config.yaml.example"
        data = yaml.safe_load(example.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"mobiflight", "performance"})
        self.assertEqual(
            set(data["mobiflight"]),
            {"captain_url", "copilot_url", "font", "max_retries"},
        )
        self.assertEqual(
            set(data["performance"]), {"capture_fps", "enable_caching"},
        )


if __name__ == "__main__":
    unittest.main()
