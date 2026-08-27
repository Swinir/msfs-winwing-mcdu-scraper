import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from mcdu_labels import (
    Label,
    PageLayout,
    _apply_label,
    _extract_title,
    _find_matching_pages,
    apply_label_corrections,
)


class TestLabelCorrection(unittest.TestCase):

    def test_extract_title(self):
        # 24 columns, title is padded
        row = [[" "] for _ in range(24)]
        for i, char in enumerate("  INIT  "):
            row[i] = [char]
        
        self.assertEqual(_extract_title(row, 24), "INIT")

    def test_find_matching_pages_exact(self):
        pages = _find_matching_pages("INIT")
        self.assertTrue(len(pages) >= 2)  # INIT A and INIT B
        self.assertEqual(pages[0].title, "INIT")

    def test_find_matching_pages_fuzzy(self):
        # 1 error in 4 chars = 25% edit distance (threshold is 30%)
        pages = _find_matching_pages("IN1T")
        self.assertTrue(len(pages) >= 2)
        self.assertEqual(pages[0].title, "INIT")

        # 2 errors in 4 chars = 50% edit distance (threshold is 30%) -> no match
        pages = _find_matching_pages("1N1T")
        self.assertEqual(len(pages), 0)

    def test_find_matching_pages_substring(self):
        pages = _find_matching_pages("      INIT        67")
        self.assertTrue(len(pages) >= 2)
        self.assertEqual(pages[0].title, "INIT")

    def _make_grid(self, text_rows, columns=24):
        grid = []
        for row_text in text_rows:
            padded = row_text.ljust(columns)[:columns]
            for char in padded:
                grid.append([char] if char != " " else [])
        return grid

    def test_apply_label_fixes_errors(self):
        # "C0 RTE" instead of "CO RTE"
        grid = self._make_grid([" C0 RTE                 "])
        label = Label(1, "CO RTE")
        
        fixes = _apply_label(grid, 24, 0, label)
        
        self.assertEqual(fixes, 1)
        self.assertEqual(grid[1][0], "C")
        self.assertEqual(grid[2][0], "O")  # Fixed
        self.assertEqual(grid[3], [])      # Space untouched

    def test_apply_label_requires_minimum_match(self):
        # Only 2 out of 5 non-space chars match (40%), threshold is 60%
        grid = self._make_grid([" C0 XXX                 "])
        label = Label(1, "CO RTE")
        
        fixes = _apply_label(grid, 24, 0, label)
        
        self.assertEqual(fixes, 0)
        self.assertEqual(grid[2][0], "0")  # Not fixed

    def test_apply_label_never_inserts(self):
        # The 'E' in 'RTE' is completely missing (empty cell)
        grid = self._make_grid([" C0 RT                  "])
        label = Label(1, "CO RTE")
        
        fixes = _apply_label(grid, 24, 0, label)
        
        self.assertEqual(fixes, 1)  # Only the '0' -> 'O' is fixed
        self.assertEqual(grid[2][0], "O")
        self.assertEqual(grid[6], [])  # 'E' position remains empty

    def test_apply_label_corrections_integration(self):
        # Simulate an INIT page with a few OCR errors in the labels
        rows = [
            "  INIT                  ", # Row 0: title
            " C0 RTE         FROM/T0 ", # Row 1: labels (errors)
            "LFPG/EDDF               ", # Row 2: value
            "ALTN/C0 RTE             ", # Row 3: label (error)
            "NONE                    ", # Row 4: value
        ]
        # Pad to 14 rows
        while len(rows) < 14:
            rows.append("                        ")
            
        grid = self._make_grid(rows)
        
        total_fixes = apply_label_corrections(grid, 24, 14, "labels_small")
        
        self.assertEqual(total_fixes, 3) # C0->CO, T0->TO, C0->CO
        
        # Verify grid was updated
        self.assertEqual(grid[1 * 24 + 2][0], "O") # CO RTE
        self.assertEqual(grid[1 * 24 + 22][0], "O") # FROM/TO
        self.assertEqual(grid[3 * 24 + 6][0], "O") # ALTN/CO RTE

    def test_wrong_font_rule_skipped(self):
        grid = self._make_grid(["INIT".ljust(24)] + [" "*24]*13)
        # Should return immediately and not try to match
        fixes = apply_label_corrections(grid, 24, 14, "all_large")
        self.assertEqual(fixes, 0)

if __name__ == "__main__":
    unittest.main()
