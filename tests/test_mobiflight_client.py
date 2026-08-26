"""
Unit tests for the MobiFlight CDU display-data sanitiser.
"""

import unittest
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from mobiflight_client import (
    MobiFlightClient,
    sanitise_display_data,
    _CDU_SAFE_CHARS,
    _CDU_CHAR_MAP,
)


class TestSanitiseDisplayData(unittest.TestCase):
    """Characters must be mapped to renderable glyphs without changing meaning."""

    def test_empty_cells_preserved(self):
        self.assertEqual(sanitise_display_data([[], [], []]), [[], [], []])

    def test_safe_chars_pass_through(self):
        data = [["A", "w", 0], ["7", "c", 1], ["/", "g", 0]]
        self.assertEqual(sanitise_display_data(data), data)

    def test_colour_and_size_preserved(self):
        result = sanitise_display_data([["Q", "m", 1]])
        self.assertEqual(result[0][1], "m")
        self.assertEqual(result[0][2], 1)

    def test_plus_is_not_turned_into_minus(self):
        """Regression: '+' folded onto '-' inverted the sign of real values."""
        result = sanitise_display_data([["+", "g", 0]])
        self.assertNotEqual(
            result[0][0], "-",
            "'+' must never become '-' — that inverts temperature and V/S values",
        )

    def test_unsupported_char_becomes_space(self):
        result = sanitise_display_data([["é", "w", 0]])
        self.assertEqual(result[0][0], " ")

    def test_multi_char_takes_first(self):
        result = sanitise_display_data([["AB", "w", 0]])
        self.assertEqual(result[0][0], "A")

    def test_chevrons_are_not_folded_onto_arrows(self):
        """The MCDU draws both, on the same page.

        A real capture has a true left arrow (shaft plus solid head) beside
        the second nav database, and a plain chevron at the end of
        STATUS/XLOAD> on the line below. Rewriting one into the other changes
        what the CDU shows. MobiFlight's reference A330 script agrees: it maps
        '{' and '}' onto the arrows and leaves '<' and '>' alone.
        """
        result = sanitise_display_data([["<", "w", 0], [">", "w", 0]])
        self.assertEqual(result[0][0], "<")
        self.assertEqual(result[1][0], ">")

    def test_real_arrows_pass_through(self):
        result = sanitise_display_data([["←", "c", 0], ["→", "w", 0]])
        self.assertEqual(result[0][0], "←")
        self.assertEqual(result[1][0], "→")

    def test_parens_become_brackets(self):
        result = sanitise_display_data([["(", "w", 0], [")", "w", 0]])
        self.assertEqual(result[0][0], "[")
        self.assertEqual(result[1][0], "]")

    def test_output_length_matches_input(self):
        data = [[] if i % 2 else ["X", "w", 0] for i in range(336)]
        self.assertEqual(len(sanitise_display_data(data)), 336)

    def test_every_output_char_is_renderable(self):
        """No mapping may produce a glyph outside the safe set."""
        data = [[ch, "w", 0] for ch in
                "ABZ019 .-/<>[]()+*:_~=&#@éü☐"]
        for cell in sanitise_display_data(data):
            self.assertIn(
                cell[0], _CDU_SAFE_CHARS,
                f"sanitiser emitted unrenderable glyph {cell[0]!r}",
            )

    def test_char_map_targets_are_all_safe(self):
        """Every value in _CDU_CHAR_MAP must itself be renderable."""
        for src, dst in _CDU_CHAR_MAP.items():
            self.assertIn(
                dst, _CDU_SAFE_CHARS,
                f"_CDU_CHAR_MAP maps {src!r} to unrenderable {dst!r}",
            )

    def test_does_not_mutate_input(self):
        data = [["(", "w", 0]]
        sanitise_display_data(data)
        self.assertEqual(data[0][0], "(")


class TestRetryBackoff(unittest.TestCase):
    """max_retries controls how fast the client backs off, not whether it quits."""

    def _client(self, max_retries=3):
        return MobiFlightClient("ws://localhost:8320/test", max_retries=max_retries)

    def test_delay_is_flat_within_max_retries(self):
        c = self._client(max_retries=3)
        for attempt in range(0, 4):
            c.retries = attempt
            self.assertEqual(c._retry_delay(), MobiFlightClient.BASE_RETRY_DELAY)

    def test_delay_grows_past_max_retries(self):
        c = self._client(max_retries=3)
        c.retries = 4
        first = c._retry_delay()
        c.retries = 5
        second = c._retry_delay()
        self.assertGreater(first, MobiFlightClient.BASE_RETRY_DELAY)
        self.assertGreater(second, first)

    def test_delay_is_capped(self):
        c = self._client(max_retries=3)
        c.retries = 500
        self.assertEqual(c._retry_delay(), MobiFlightClient.MAX_RETRY_DELAY)

    def test_max_retries_actually_changes_behaviour(self):
        """Regression: the setting used to be stored and never read."""
        patient = self._client(max_retries=10)
        impatient = self._client(max_retries=1)
        patient.retries = impatient.retries = 5
        self.assertLess(
            patient._retry_delay(), impatient._retry_delay(),
            "max_retries had no effect on the retry delay",
        )

    def test_client_never_stops_running(self):
        """Backing off must not turn into giving up."""
        c = self._client(max_retries=1)
        c.retries = 1000
        self.assertTrue(c.running)
        self.assertLessEqual(c._retry_delay(), MobiFlightClient.MAX_RETRY_DELAY)


if __name__ == "__main__":
    unittest.main()
