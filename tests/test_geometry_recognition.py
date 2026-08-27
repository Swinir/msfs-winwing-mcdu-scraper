"""
The geometry pass: what it names, what it refuses, and where it ranks.

An MCDU page is mostly punctuation and entry boxes, and those are exactly
the characters a CRNN is worst at - it has no box in its alphabet at all,
and reads a dash, a slash or a chevron as whichever letter comes nearest.
A real session against an Airbus INIT page showed the cost: the amber entry
boxes came back as "CS S  S S I" and " SSSSSSSI", and because those letters
were then learned as templates the damage spread into genuine text.

So those glyphs are decided from their shape instead, ahead of both
engines.  That is only defensible if the shape tests are actually better
than the engines on the characters they claim, which is what these tests
measure - over every labelled glyph the project has, from three real
captures and four rendered pages at four cell sizes.

The thresholds in the detector were fitted to this same corpus, so a score
here is not an out-of-sample result.  What it does guarantee is that the
detector never trades a letter for a symbol, which is the failure mode that
matters: a wrong symbol used to become a permanent template.
"""

import string
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

import mcdu_parser
from mcdu_charset import BALLOT_BOX
from mcdu_detector import detect_mcdu_region
from mcdu_parser import GEOMETRY_OWNED, MCDUParser
from mcdu_fixtures import ALL_PAGES, MCDUPage, find_mono_font, render_mcdu

DATA = Path(__file__).parent / "data"

#: Cell sizes spanning what the pop-out window actually produces: the
#: smallest capture in tests/data is 14x23 px per cell, the largest window a
#: user reported was 24x38.
CELL_SIZES = [(12, 18), (15, 23), (20, 24), (24, 38)]


def load(path):
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def detected_parser(path, columns=24, rows=14):
    image = load(path)
    found = detect_mcdu_region(image, columns=columns, rows=rows)
    if not found:
        return None
    x, y, w, h = found
    x, y = max(0, x), max(0, y)
    crop = image[y:y + min(h, image.shape[0] - y),
                 x:x + min(w, image.shape[1] - x)]
    return MCDUParser(crop, columns=columns, rows=rows, source_id=path.stem)


def labelled_glyphs():
    """Every (parser, row, col, expected char) the project has ground truth for."""
    from test_fokker_capture import TRUTH as FOKKER
    from test_new_captures import ATR2_TRUTH
    from test_real_capture import TRUTH as A330

    sources = []
    for name, truth in (("mcdu_real_capture.png", A330),
                        ("atr_mcdu_screenshot (2).png", ATR2_TRUTH),
                        ("jf-f70-f100-fcu.png", FOKKER)):
        path = DATA / name
        if not path.exists():
            continue
        parser = detected_parser(path)
        if parser is not None:
            sources.append((parser, truth))
    if find_mono_font() is not None:
        for name in ('alpha_numeric', 'flight_plan', 'perf', 'airbus_init'):
            for cell in CELL_SIZES:
                page = ALL_PAGES[name]()
                sources.append((MCDUParser(render_mcdu(page, cell_size=cell),
                                           source_id=name), page.padded()))

    for parser, truth in sources:
        for row in range(parser.rows):
            for col in range(parser.columns):
                want = truth[row][col]
                if want == " ":
                    continue
                if parser.is_empty_cell(parser.extract_cell(row, col)):
                    continue
                yield parser, row, col, want


def geometry_reading(parser, row, col):
    """What the geometry pass alone makes of one cell."""
    cell = parser.extract_cell(row, col)
    if parser._is_entry_box(cell):
        return BALLOT_BOX
    return parser._detect_via_contours(cell)


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestEntryBoxes(unittest.TestCase):
    """The Airbus square that marks a field the crew must fill in."""

    def test_every_box_on_the_page_is_found(self):
        for cell in CELL_SIZES:
            page = ALL_PAGES['airbus_init']()
            parser = MCDUParser(render_mcdu(page, cell_size=cell),
                                source_id="box")
            lines = page.padded()
            want = [(r, c) for r in range(14) for c in range(24)
                    if lines[r][c] == BALLOT_BOX]
            self.assertGreater(len(want), 20, "fixture has no boxes to find")
            missed = [rc for rc in want
                      if not parser._is_entry_box(parser.extract_cell(*rc))]
            self.assertEqual(missed, [], f"cell {cell}: boxes missed")

    def test_no_character_is_mistaken_for_a_box(self):
        """The test that matters: a false box is a character destroyed."""
        chars = string.ascii_uppercase + string.digits + ".-+/<>[]()"
        lines = [chars[i:i + 24].ljust(24) for i in range(0, len(chars), 24)]
        lines += [" " * 24] * (14 - len(lines))
        page = MCDUPage(lines=lines, colors=["w"] * 14)
        for cell in CELL_SIZES:
            parser = MCDUParser(render_mcdu(page, cell_size=cell),
                                source_id="chars")
            wrong = [lines[r][c] for r in range(14) for c in range(24)
                     if lines[r][c] != " "
                     and parser._is_entry_box(parser.extract_cell(r, c))]
            self.assertEqual(wrong, [], f"cell {cell}: read as boxes")

    def test_the_real_captures_hold_no_boxes(self):
        """None of the captured pages shows one, so none may be reported."""
        for name, columns, rows in (
            ("mcdu_real_capture.png", 24, 14),
            ("atr_mcdu_screenshot (1).png", 24, 14),
            ("atr_mcdu_screenshot (2).png", 24, 14),
            ("jf-f70-f100-fcu.png", 24, 14),
            ("jf-avro-fcu.png", 25, 14),
            ("uns1_wt.png", 24, 11),
            ("uns1_jf_bae146.png", 24, 11),
        ):
            path = DATA / name
            if not path.exists():
                continue
            parser = detected_parser(path, columns, rows)
            self.assertIsNotNone(parser, f"{name}: nothing detected")
            found = [(r, c) for r in range(rows) for c in range(columns)
                     if not parser.is_empty_cell(parser.extract_cell(r, c))
                     and parser._is_entry_box(parser.extract_cell(r, c))]
            self.assertEqual(found, [], f"{name}: invented entry boxes")

    def test_a_box_reaches_the_display(self):
        """It has to survive sanitisation, or the work is wasted."""
        from mobiflight_client import sanitise_display_data
        out = sanitise_display_data([[BALLOT_BOX, "a", 0]])
        self.assertEqual(out[0][0], BALLOT_BOX,
                         "the entry box is filtered out on the way to the CDU")


class TestGeometryDetectors(unittest.TestCase):
    """Scored over every labelled glyph in the project."""

    @classmethod
    def setUpClass(cls):
        cls.glyphs = list(labelled_glyphs())
        if len(cls.glyphs) < 500:
            raise unittest.SkipTest("no glyph corpus available")

    def test_no_letter_or_digit_is_claimed(self):
        """A false symbol is worse than a missing one.

        The detector's answer now outranks both engines and its cells are
        excluded from learning, so anything it gets wrong is both shown and
        remembered.  An audit of the version this replaced found 113 wrong
        calls in 260 - L and C read as brackets, and L, E, F, 5 and I read
        as degree signs.
        """
        wrong = {}
        for parser, row, col, want in self.glyphs:
            got = geometry_reading(parser, row, col)
            if got is not None and got != want:
                wrong[f"{want}->{got}"] = wrong.get(f"{want}->{got}", 0) + 1
        self.assertEqual(wrong, {}, f"geometry claimed the wrong character")

    def test_it_names_the_symbols_it_is_there_for(self):
        """Precision would be trivial to buy by never answering."""
        missed = {}
        named = 0
        for parser, row, col, want in self.glyphs:
            if want not in GEOMETRY_OWNED:
                continue
            if geometry_reading(parser, row, col) == want:
                named += 1
            else:
                missed[want] = missed.get(want, 0) + 1
        self.assertGreater(named, 400, "the detector went quiet")
        self.assertEqual(missed, {}, "symbols left unnamed")

    def test_only_well_evidenced_shapes_carry_a_veto(self):
        """GEOMETRY_OWNED silences other engines, so it must earn its scope.

        Reading a shape and being entitled to overrule someone else about
        it are different bars.  The arrows clear the first and not the
        second: the corpus holds one left arrow and no right one, and when
        they were owned, the rule's silence on the UNS-1's reverse-video
        ACCEPT prompt deleted an arrow a template had read correctly.
        """
        exempt = {"←", "→"}
        produced = {geometry_reading(p, r, c) for p, r, c, _ in self.glyphs}
        produced.discard(None)
        self.assertTrue(
            produced <= GEOMETRY_OWNED | exempt,
            f"detector produced {produced - GEOMETRY_OWNED - exempt}, "
            f"which is neither vetoed nor knowingly exempt",
        )
        for char in GEOMETRY_OWNED:
            seen = sum(1 for _, _, _, want in self.glyphs if want == char)
            if seen:
                self.assertGreaterEqual(
                    seen, 5,
                    f"{char!r} carries a veto on only {seen} example(s)",
                )


class TestPositionAssignment(unittest.TestCase):
    """Mapping one row of OCR output onto the character grid."""

    def setUp(self):
        self.parser = MCDUParser(np.zeros((280, 480, 3), dtype=np.uint8),
                                 source_id="map")
        self.width = self.parser.cell_width

    def _occupied(self, columns):
        flags = [False] * 24
        for col in columns:
            flags[col] = True
        return flags

    def _row(self, cells):
        return "".join(c or "." for c in cells)

    def test_a_crowded_row_loses_nothing(self):
        """Two characters rounding to one column used to cost one of them.

        On the A330 capture that turned "+0.0/+0.0" into "+0. 0I+.0" - the
        character was not misread, it was discarded because a neighbour got
        to its column first.
        """
        w = self.width
        chars = [("A", 2.4 * w), ("C", 3.1 * w), ("T", 3.6 * w),
                 ("I", 5.2 * w), ("V", 6.5 * w), ("E", 7.5 * w)]
        got = self.parser._map_positions_to_cells(
            chars, self._occupied(range(2, 8)))
        self.assertEqual(self._row(got), "..ACTIVE" + "." * 16)

    def test_a_spurious_character_is_dropped_not_absorbed(self):
        """...and dropping it must not shift everything else along."""
        w = self.width
        chars = [("X", 0.2 * w), ("A", 2.4 * w), ("C", 3.1 * w),
                 ("T", 3.6 * w), ("I", 5.2 * w), ("V", 6.5 * w),
                 ("E", 7.5 * w)]
        got = self.parser._map_positions_to_cells(
            chars, self._occupied(range(2, 8)))
        self.assertEqual(self._row(got), "..ACTIVE" + "." * 16)

    def test_characters_only_land_where_there_is_ink(self):
        """Which cells hold ink is measured; where OCR saw a character is
        estimated by dividing a word's bounding box evenly.  When the two
        disagree, the measurement wins."""
        w = self.width
        got = self.parser._map_positions_to_cells(
            [("A", 9.9 * w), ("B", 10.9 * w)], self._occupied([10, 11]))
        self.assertEqual(self._row(got), "." * 10 + "AB" + "." * 12)

    def test_a_character_is_not_dragged_across_the_row(self):
        """Past MAX_SHIFT the position is no longer evidence of anything."""
        w = self.width
        got = self.parser._map_positions_to_cells(
            [("A", 2.4 * w)], self._occupied([20]))
        self.assertEqual(self._row(got), "." * 24)

    def test_a_long_word_survives_accumulated_drift(self):
        """Where the collisions really come from.

        A character's x position is estimated by dividing an OCR word's
        bounding box evenly, so if the box is a few per cent narrow the
        error accumulates along the word until two characters round to one
        column.  That is what cost "+0.0/+0.0" a character on the A330
        capture - nine glyphs at a pitch read 12% short.
        """
        w = self.width
        word = "SOFTWARE"
        pitch = 0.88
        chars = [(ch, (2.5 + i * pitch) * w) for i, ch in enumerate(word)]
        columns = range(2, 2 + len(word))
        got = self.parser._map_positions_to_cells(
            chars, self._occupied(columns))
        self.assertEqual(self._row(got),
                         "." * 2 + word + "." * (24 - 2 - len(word)))

    def test_an_empty_reading_gives_an_empty_row(self):
        got = self.parser._map_positions_to_cells([], self._occupied([1, 2]))
        self.assertEqual(self._row(got), "." * 24)

    def test_a_row_with_no_ink_takes_nothing(self):
        got = self.parser._map_positions_to_cells(
            [("A", 2.5 * self.width)], [False] * 24)
        self.assertEqual(self._row(got), "." * 24)


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestGeometryVeto(unittest.TestCase):
    """A symbol geometry did not find cannot be produced by anything else."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._saved = mcdu_parser._template_matcher
        self._saved_imgs = dict(mcdu_parser._prev_row_imgs)
        self._saved_ocr = dict(mcdu_parser._prev_row_ocr)
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        self.matcher = mcdu_parser.TemplateMatcher(
            template_path=Path(self._tmpdir.name) / "veto.npz")
        mcdu_parser._template_matcher = self.matcher

    def tearDown(self):
        mcdu_parser._template_matcher = self._saved
        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        mcdu_parser._prev_row_imgs.update(self._saved_imgs)
        mcdu_parser._prev_row_ocr.update(self._saved_ocr)
        self._tmpdir.cleanup()

    def test_a_poisoned_bracket_template_cannot_reach_the_display(self):
        """The failure this veto exists for.

        Warmup taught a bracket from the I of ACTIVE and of CONSUMPTION,
        and every later frame then matched that template and put a bracket
        in the middle of the word.  Geometry examined those cells and did
        not call them brackets, so the template's answer is refused.
        """
        page = MCDUPage(lines=["ACTIVE".ljust(24)] + [" " * 24] * 13,
                        colors=["w"] * 14)
        parser = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="veto")

        # Teach '[' from the I, exactly as a bad warmup would.
        binary = parser.cell_binary(0, 3)
        for _ in range(self.matcher.CONSENSUS_MIN):
            self.matcher.learn("[", binary, confidence=1.0)
        self.assertIn("[", self.matcher._templates, "test setup failed")

        mcdu_parser._prev_row_imgs.clear()
        mcdu_parser._prev_row_ocr.clear()
        parsed = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="read").parse_grid()
        emitted = "".join(c[0] if c else " " for c in parsed[:24])
        self.assertNotIn("[", emitted,
                         f"a vetoed bracket reached the display: {emitted!r}")

    def test_a_symbol_geometry_did_find_is_kept(self):
        """The veto must not swallow the characters it is protecting."""
        page = MCDUPage(lines=["A-B/C".ljust(24)] + [" " * 24] * 13,
                        colors=["w"] * 14)
        parser = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="keep")
        self.assertEqual(parser._detect_via_contours(parser.extract_cell(0, 1)), "-")
        self.assertEqual(parser._detect_via_contours(parser.extract_cell(0, 3)), "/")

        parsed = parser.parse_grid()
        emitted = "".join(c[0] if c else " " for c in parsed[:24])
        self.assertEqual(emitted[1], "-", f"lost the dash: {emitted!r}")
        self.assertEqual(emitted[3], "/", f"lost the slash: {emitted!r}")

    def test_a_row_served_from_cache_reads_the_same(self):
        """A row that stops changing must not change what it shows.

        The row cache is what an unchanged row is served from on every
        later frame, so it has to hold what the row displayed - not what
        EasyOCR alone proposed for it.  The geometry pass and the template
        matcher both feed the assembled grid without passing through
        ocr_results, so storing the raw reading dropped what they had
        supplied the moment a row went quiet.

        An entry box makes the difference certain rather than likely: it is
        not in the OCR alphabet, so a raw reading cannot contain one.
        """
        line = "A" + BALLOT_BOX + "B"
        page = MCDUPage(lines=[line.ljust(24)] + [" " * 24] * 13,
                        colors=["w"] * 14)
        image = render_mcdu(page, cell_size=(20, 24))

        def text(grid):
            return "".join(c[0] if c else " " for c in grid[:24])

        first = MCDUParser(image, source_id="cache").parse_grid()
        self.assertIn(BALLOT_BOX, text(first),
                      "test setup: no box on the first pass")

        second = MCDUParser(image, source_id="cache").parse_grid()
        self.assertEqual(text(second), text(first),
                         "the cached frame differs from the parsed one")


@unittest.skipIf(find_mono_font() is None, "no monospace font available")
class TestShapeAgreement(unittest.TestCase):
    """Cells drawn from the same bitmap must read as the same character."""

    def _page(self):
        # Eight identical E, so one dissenter is outvoted seven to one.
        return MCDUPage(lines=["EEEEEEEE".ljust(24)] + [" " * 24] * 13,
                        colors=["w"] * 14)

    def _grid(self, parser, text):
        grid = []
        for row in range(14):
            for col in range(24):
                char = text[col] if row == 0 and col < len(text) else " "
                grid.append([] if char == " " else [char, "w", 0])
        return grid

    def test_a_lone_dissenter_is_outvoted(self):
        page = self._page()
        parser = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="agree")
        grid = self._grid(parser, "EEEBEEEE")
        changed = parser._unify_identical_glyphs(grid, set())
        self.assertEqual(changed, 1)
        self.assertEqual("".join(c[0] if c else " " for c in grid[:8]),
                         "EEEEEEEE")

    def test_an_even_split_is_left_alone(self):
        """No majority means no evidence; guessing is what this avoids."""
        page = self._page()
        parser = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="split")
        grid = self._grid(parser, "EEEEBBBB")
        self.assertEqual(parser._unify_identical_glyphs(grid, set()), 0)
        self.assertEqual("".join(c[0] if c else " " for c in grid[:8]),
                         "EEEEBBBB")

    def test_geometry_results_are_never_overruled(self):
        page = self._page()
        parser = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="fixed")
        grid = self._grid(parser, "EEE-EEEE")
        parser._unify_identical_glyphs(grid, {3})
        self.assertEqual(grid[3][0], "-",
                         "a character geometry settled was voted away")

    def test_distinct_characters_are_not_merged(self):
        """The grouping has to be tight enough to keep letters apart."""
        text = "ABCDEFGH"
        page = MCDUPage(lines=[text.ljust(24)] + [" " * 24] * 13,
                        colors=["w"] * 14)
        parser = MCDUParser(render_mcdu(page, cell_size=(20, 24)),
                            source_id="distinct")
        grid = self._grid(parser, text)
        self.assertEqual(parser._unify_identical_glyphs(grid, set()), 0)
        self.assertEqual("".join(c[0] if c else " " for c in grid[:8]), text)


if __name__ == "__main__":
    unittest.main()
