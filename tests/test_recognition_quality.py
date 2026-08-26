"""
End-to-end recognition accuracy against rendered MCDU pages.

These are the regression guard for the recognition work: they score the
parser against ground truth rather than asserting on internals, so a change
that makes recognition worse fails here even if every unit test still passes.

The thresholds are set below measured accuracy, not at it, so ordinary
rendering jitter does not turn the suite red.  Measured at the time of
writing: 98% / 90% / 100% per page, 96% mean.
"""

import tempfile
import unittest
from pathlib import Path
import sys

# Add src and tests to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import mcdu_parser
from mcdu_parser import MCDUParser, TemplateMatcher, _correct_row_context, _correct_token
from mcdu_fixtures import (
    ALL_PAGES,
    find_mono_font,
    grid_accuracy,
    render_mcdu,
)

CELL = (20, 24)


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestRecognitionAccuracy(unittest.TestCase):
    """Score the parser on synthetic pages with known content."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz"
        )
        mcdu_parser._template_matcher = self.matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _teach(self, *page_names):
        """Warm the matcher from ground truth, as EasyOCR warmup would."""
        for name in page_names:
            page = ALL_PAGES[name]()
            parser = MCDUParser(render_mcdu(page, cell_size=CELL),
                                source_id="teach")
            for row, line in enumerate(page.padded()):
                for col, char in enumerate(line):
                    if char == " ":
                        continue
                    binary = parser._preprocess_cell(parser.extract_cell(row, col))
                    self.matcher.learn(char, binary, confidence=1.0)
                    self.matcher.learn(char, binary, confidence=1.0)

    def _score(self, name):
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        page = ALL_PAGES[name]()
        parsed = MCDUParser(render_mcdu(page, cell_size=CELL),
                            source_id=name).parse_grid()
        return grid_accuracy(page.expected_cells(), parsed)

    def test_occupancy_detection_is_reliable(self):
        """Knowing *where* characters are must not depend on templates."""
        for name in ALL_PAGES:
            score = self._score(name)
            self.assertGreaterEqual(
                score["occupancy_accuracy"], 0.99,
                f"{name}: empty/non-empty classification degraded",
            )

    def test_accuracy_after_single_page_warmup(self):
        self._teach("alpha_numeric")
        for name, floor in (("flight_plan", 0.90),
                            ("perf", 0.85),
                            ("alpha_numeric", 0.97)):
            score = self._score(name)
            self.assertGreaterEqual(
                score["char_accuracy"], floor,
                f"{name}: {score['char_accuracy']:.1%} "
                f"({score['correct']}/{score['total']}), "
                f"confusions={score['confusions']}",
            )

    def test_accuracy_after_full_warmup(self):
        """Having seen every glyph in both sizes, recognition is near-perfect."""
        self._teach(*ALL_PAGES)
        for name in ALL_PAGES:
            score = self._score(name)
            self.assertGreaterEqual(
                score["char_accuracy"], 0.98,
                f"{name}: {score['char_accuracy']:.1%}, "
                f"confusions={score['confusions']}",
            )

    def test_zero_is_not_relabelled_as_d(self):
        """The old geometry heuristic turned nearly every 0 into a D."""
        self._teach("alpha_numeric")
        score = self._score("alpha_numeric")
        for confusion in score["confusions"]:
            self.assertNotEqual(confusion, "0->D",
                                "zeros are being relabelled as D again")
            self.assertNotEqual(confusion, "8->B",
                                "eights are being relabelled as B again")

    def test_dashes_are_recognised(self):
        """A hyphen renders ~1px tall and used to be discarded outright."""
        self._teach("flight_plan")
        score = self._score("flight_plan")
        self.assertNotIn("-> ", score["confusions"],
                         "dashes are being dropped again")


class TestThinGlyphs(unittest.TestCase):
    """Aspect ratio is the only thing separating the thin symbols."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "t.npz"
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    @staticmethod
    def _cell(width, height, top):
        cell = np.zeros((24, 20), dtype=np.uint8)
        left = (20 - width) // 2
        cell[top:top + height, left:left + width] = 255
        return cell

    def test_thin_glyphs_stay_distinct(self):
        glyphs = {
            "-": self._cell(8, 1, 12),    # dash, mid height, 1px tall
            ".": self._cell(2, 2, 20),    # period, bottom
            "_": self._cell(9, 1, 20),    # underscore, bottom, 1px tall
            "0": self._cell(12, 16, 4),   # a full-height glyph
        }
        for char, glyph in glyphs.items():
            self.matcher.learn(char, glyph, confidence=1.0)
            self.matcher.learn(char, glyph, confidence=1.0)

        self.assertEqual(
            len(self.matcher._templates), len(glyphs),
            "distinct glyphs collapsed onto the same template",
        )
        for char, glyph in glyphs.items():
            result = self.matcher.recognize(glyph)
            self.assertIsNotNone(result, f"{char!r} was not recognised at all")
            self.assertEqual(result[0], char,
                             f"{char!r} came back as {result[0]!r}")

    def test_one_pixel_tall_glyph_is_not_discarded(self):
        dash = self._cell(8, 1, 12)
        self.assertIsNotNone(
            TemplateMatcher._extract_glyph(dash),
            "a 1px-tall dash was discarded before it could be learned",
        )


class TestContextCorrection(unittest.TestCase):
    """Letter/digit repair driven by the token, not by stroke geometry."""

    def test_numeric_tokens_repaired(self):
        self.assertEqual(_correct_row_context("GS 4S2 TAS 46O"), "GS 452 TAS 460")

    def test_alpha_prefixed_values_repaired(self):
        self.assertEqual(_correct_row_context("N045O FL35O"), "N0450 FL350")

    def test_decimals_stay_one_token(self):
        self.assertEqual(_correct_row_context("ILS 11O.3O"), "ILS 110.30")

    def test_nav_database_dates_are_not_rewritten(self):
        """Regression from a real capture: 22JAN came back as 2ZJAN.

        J, A and N are unambiguous letters while both 2s are ambiguous, so a
        digit-to-letter rule read the whole token as alphabetic.  Dates in
        DDMMM form are common on the nav database pages.
        """
        for token in ("22JAN", "19FEB", "19MAR", "01DEC", "22JAN-19FEB"):
            self.assertEqual(_correct_row_context(token), token,
                             f"{token} was rewritten")

    def test_identifiers_are_left_alone(self):
        """The leading character carries identity and must not be rewritten."""
        for token in ("B738", "G5", "A1", "C10", "C1"):
            self.assertEqual(_correct_token(token), token,
                             f"{token} was mangled by context correction")

    def test_icao_codes_untouched(self):
        self.assertEqual(_correct_row_context("LFPG EDDF KJFK"), "LFPG EDDF KJFK")

    def test_placeholder_rows_untouched(self):
        self.assertEqual(_correct_row_context("---/---"), "---/---")

    def test_ambiguous_only_token_left_alone(self):
        """No unambiguous evidence means no guess."""
        self.assertEqual(_correct_token("IO"), "IO")
        self.assertEqual(_correct_token("OS"), "OS")

    def test_single_character_untouched(self):
        self.assertEqual(_correct_token("O"), "O")


class TestCharsetConsistency(unittest.TestCase):
    """The parser and the client must agree on what a character may be."""

    def test_ocr_allowlist_is_renderable(self):
        from mcdu_charset import OCR_ALLOWLIST, RENDERABLE
        for char in OCR_ALLOWLIST:
            self.assertIn(char, RENDERABLE,
                          f"OCR may emit {char!r}, which the CDU cannot draw")

    def test_substitution_targets_are_renderable(self):
        from mcdu_charset import SUBSTITUTIONS, RENDERABLE
        for src, dst in SUBSTITUTIONS.items():
            self.assertIn(dst, RENDERABLE,
                          f"{src!r} maps to unrenderable {dst!r}")

    def test_client_and_parser_share_one_definition(self):
        import mcdu_parser as parser
        import mobiflight_client as client
        from mcdu_charset import OCR_ALLOWLIST, RENDERABLE
        self.assertEqual(parser._EASYOCR_ALLOWLIST, OCR_ALLOWLIST)
        self.assertEqual(client._CDU_SAFE_CHARS, RENDERABLE)

    def test_plus_never_becomes_minus(self):
        from mcdu_charset import sanitise_char
        self.assertNotEqual(sanitise_char("+"), "-")


if __name__ == "__main__":
    unittest.main()
