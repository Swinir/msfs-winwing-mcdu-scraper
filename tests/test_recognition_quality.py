"""
End-to-end recognition accuracy against rendered MCDU pages.

These are the regression guard for the recognition work: they score the
parser against ground truth rather than asserting on internals, so a change
that makes recognition worse fails here even if every unit test still passes.

Most of them teach the template matcher from ground truth first, which
measures template matching but says nothing about the path a user is
actually on: an empty store, EasyOCR warmup, and whatever comes out.  A
whole class of failure hid in that gap - a real session read an Airbus INIT
page as "CS S  S S I" and "C0 T INNEX" while every test here passed.  So
TestColdStart at the bottom scores the cold path too.  It is slow, because
it runs the warmup for real; that is the point of it.

The thresholds are set below measured accuracy, not at it, so ordinary
rendering jitter does not turn the suite red.
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
                    binary = parser.cell_binary(row, col)
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
        # alpha_numeric is scored against its own teaching, so it is a
        # template-matching floor, not an OCR one.  It was lowered to 0.90
        # while the geometry disambiguator was overruling learned glyphs;
        # with that scoped back the page reads exactly, and the floor
        # returns to where it was.
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
        """Having seen every glyph in both sizes, recognition is exact.

        This used to be capped at 92%, because the geometry disambiguator
        re-tested every emitted character and flipped Consolas's straight-
        edged '0' to 'D' and its '8' to 'B' however well they had been
        learned.  Trusting a confirmed template - ISSUES.md #5 - lifts all
        four pages to 100%, so the threshold is where the measurement is
        rather than two thirds of the way down to it.
        """
        self._teach(*ALL_PAGES)
        for name in ALL_PAGES:
            score = self._score(name)
            self.assertGreaterEqual(
                score["char_accuracy"], 0.99,
                f"{name}: {score['char_accuracy']:.1%}, "
                f"confusions={score['confusions']}",
            )

    def test_a_learned_glyph_is_not_second_guessed(self):
        """The confusable pairs survive being learned.

        alpha_numeric is built out of them - OOO000III111BBB888SSS555 and
        ZZZ222DDD000GGGCCCQQQOOO - in a font whose '0' has the straight
        left edge the D/O rule looks for.  Once those glyphs are in the
        store, nothing downstream may relabel them.
        """
        self._teach("alpha_numeric")
        score = self._score("alpha_numeric")
        self.assertEqual(
            score["confusions"], {},
            f"a learned glyph was overruled: {score['confusions']}",
        )

    def test_dashes_are_recognised(self):
        """A hyphen renders ~1px tall and used to be discarded outright."""
        self._teach("flight_plan")
        score = self._score("flight_plan")
        self.assertNotIn("-> ", score["confusions"],
                         "dashes are being dropped again")

    def test_label_dictionary_corrects_errors(self):
        """The label dictionary should fix confusions on known label rows."""
        # Teach the matcher, but intentionally poison the 'O' template
        # so it consistently misreads 'O' as '0'
        self._teach("flight_plan")
        glyph = self.matcher._extract_glyph(self.matcher._templates["O"][0])
        # Replace the 'O' template with '0'
        del self.matcher._templates["O"]
        self.matcher.learn("0", glyph, confidence=1.0)
        self.matcher.learn("0", glyph, confidence=1.0)

        # Parse the page, which will now have '0' where 'O' should be
        score = self._score("flight_plan")

        # The label dictionary should have fixed the '0' back to 'O' in 'CO RTE'
        # etc., so the confusions should be lower than if we hadn't run it.
        # Check that "FROM/TO" and "CO RTE" are not listed as confusions
        self.assertNotIn("O->0", score["confusions"],
                         "Label dictionary failed to correct O->0 on label row")


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
            "T": self._cell(12, 16, 4),   # a full-height glyph for contrast
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

    def test_colour_codes_match_mobiflight(self):
        """Verified against MobiFlight's FormatTable in WinCtrlCduController.cs
        and the reference headwind_a33_winwing_cdu.py script."""
        from config import Config
        self.assertEqual(
            Config.COLORS,
            {
                "a": "amber", "c": "cyan", "e": "grey", "g": "green",
                "k": "khaki", "m": "magenta", "o": "blue", "r": "red",
                "w": "white", "y": "yellow",
            },
        )

    def test_parser_only_emits_known_colour_codes(self):
        """A code outside MobiFlight's table is rendered grey by the device."""
        import numpy as np
        from config import Config
        from mcdu_parser import MCDUParser
        parser = MCDUParser(np.zeros((280, 480, 3), dtype=np.uint8), source_id="c")
        for rgb in ((255, 255, 255), (0, 220, 235), (0, 230, 60), (255, 170, 0),
                    (240, 240, 0), (240, 0, 240), (240, 40, 40), (130, 130, 130)):
            cell = np.zeros((20, 20, 3), dtype=np.uint8)
            cell[:, :] = rgb
            self.assertIn(parser.detect_color(cell), Config.COLORS,
                          f"{rgb} produced a code MobiFlight does not define")


class TestColdStart(unittest.TestCase):
    """What a user gets on the first run: no templates, no ground truth.

    Slow - each page pays a full EasyOCR warmup - and deliberately so.  This
    is the only place the warmup, the template learner, the geometry pass
    and the position assignment are all exercised together against known
    text, which is the combination that failed in the field.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._template_matcher = TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "cold.npz")

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def _cold_score(self, name):
        page = ALL_PAGES[name]()
        parsed = MCDUParser(
            render_mcdu(page, cell_size=CELL),
            columns=page.columns, rows=page.rows,
            source_id=name, small_font_rule=page.small_font_rule,
        ).parse_grid()
        return grid_accuracy(page.expected_cells(), parsed)

    def test_an_airbus_cold_start_page_reads(self):
        """INIT A: the page a cold start opens on, two thirds entry boxes.

        The reported failure read its boxes as "CS S  S S I" and
        " SSSSSSSI" and then learned those letters.  Measured 97% here.
        """
        score = self._cold_score("airbus_init")
        self.assertGreaterEqual(
            score["char_accuracy"], 0.90,
            f"{score['char_accuracy']:.1%} ({score['correct']}/"
            f"{score['total']}), confusions={score['confusions']}",
        )

    def test_entry_boxes_are_not_read_as_letters(self):
        """The specific failure, asserted on its own.

        A box misread is worse than a box missed: it used to be learned as
        whichever letter EasyOCR guessed, and that template then spread the
        error into genuine text.
        """
        from mcdu_charset import BALLOT_BOX
        page = ALL_PAGES["airbus_init"]()
        parsed = MCDUParser(render_mcdu(page, cell_size=CELL),
                            source_id="boxes").parse_grid()
        expected = page.expected_cells()
        wrong = [
            i for i, want in enumerate(expected)
            if want and want[0] == BALLOT_BOX
            and (not parsed[i] or parsed[i][0] != BALLOT_BOX)
        ]
        self.assertEqual(wrong, [], "entry boxes did not survive a cold start")

    def test_a_dense_mixed_page_reads(self):
        """Every confusable pair, at both font sizes.  Measured 92%."""
        score = self._cold_score("alpha_numeric")
        self.assertGreaterEqual(
            score["char_accuracy"], 0.85,
            f"{score['char_accuracy']:.1%} ({score['correct']}/"
            f"{score['total']}), confusions={score['confusions']}",
        )

    def test_the_grid_lands_on_the_text(self):
        """Occupancy does not depend on recognition and must be exact."""
        for name in ("airbus_init", "alpha_numeric"):
            score = self._cold_score(name)
            self.assertGreaterEqual(score["occupancy_accuracy"], 0.99, name)


if __name__ == "__main__":
    unittest.main()
