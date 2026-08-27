"""
The rule that decides when a new reading is allowed to reach the hardware.

OCR output jitters, and a physical CDU shows every change, so a cell has to
hold its new value for `stability_frames` frames *in a row* before it is
promoted.  The run must be consecutive: an implementation that instead took
the most common value in a sliding window was tried and reverted, because
three sightings out of five is a description of alternating noise as much
as of a settled value.  Under it "0 O 0 O O" promoted the O, which is
precisely the flicker the stabiliser exists to stop.

tests/test_pipeline.py covers the promotion timings; this file covers what
the display does while a value is still making up its mind, and the cases
that are easy to get wrong when a cell empties or a flag changes.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from pipeline import DisplayStabiliser


def cell(char, inverted=False):
    return [char, "g", 1, True] if inverted else [char, "g", 1]


class TestDisplayStabiliser(unittest.TestCase):

    def test_initial_frame_promotes_immediately(self):
        """There is nothing on the display yet to protect."""
        stabiliser = DisplayStabiliser(stability_frames=3)
        frame = [cell("A"), cell("B")]
        self.assertEqual(stabiliser.update(frame), frame)

    def test_a_consecutive_run_promotes(self):
        stabiliser = DisplayStabiliser(stability_frames=3)
        stabiliser.update([cell("A")])
        for sighting in (1, 2):
            self.assertEqual(stabiliser.update([cell("B")]), [cell("A")],
                             f"promoted on sighting {sighting}")
        self.assertEqual(stabiliser.update([cell("B")]), [cell("B")])

    def test_alternating_noise_is_never_promoted(self):
        """The case that decided against a sliding-window majority.

        A cell flickering between O and 0 has not settled on either, so
        neither may be shown - however often one of them turns up.
        """
        stabiliser = DisplayStabiliser(stability_frames=3)
        stabiliser.update([cell("0")])
        for i in range(20):
            reading = [cell("O")] if i % 2 else [cell("0")]
            self.assertEqual(stabiliser.update(reading), [cell("0")],
                             f"jitter promoted at frame {i}")

    def test_a_run_broken_by_the_displayed_value_starts_again(self):
        stabiliser = DisplayStabiliser(stability_frames=3)
        stabiliser.update([cell("A")])
        stabiliser.update([cell("B")])
        stabiliser.update([cell("A")])          # back to what is displayed
        stabiliser.update([cell("B")])
        self.assertEqual(stabiliser.update([cell("B")]), [cell("A")],
                         "a broken run was allowed to carry on counting")

    def test_a_cell_that_empties_is_promoted_like_any_other_change(self):
        stabiliser = DisplayStabiliser(stability_frames=3)
        stabiliser.update([cell("A")])
        self.assertEqual(stabiliser.update([[]]), [cell("A")])
        self.assertEqual(stabiliser.update([[]]), [cell("A")])
        self.assertEqual(stabiliser.update([[]]), [[]])

    def test_reverse_video_turning_on_is_a_change(self):
        """The flag is the fourth element, and comparison must see it."""
        stabiliser = DisplayStabiliser(stability_frames=1)
        stabiliser.update([cell("A")])
        self.assertEqual(stabiliser.update([cell("A", inverted=True)])[0],
                         cell("A", inverted=True))

    def test_cells_are_judged_independently(self):
        """One unsettled cell must not hold up the rest of the page."""
        stabiliser = DisplayStabiliser(stability_frames=2)
        stabiliser.update([cell("A"), cell("B")])
        stabiliser.update([cell("A"), cell("C")])
        out = stabiliser.update([cell("Z"), cell("C")])
        self.assertEqual(out[1], cell("C"), "settled cell was held back")
        self.assertEqual(out[0], cell("A"), "unsettled cell was promoted")

    def test_reset_forgets_everything(self):
        stabiliser = DisplayStabiliser(stability_frames=3)
        stabiliser.update([cell("A")])
        stabiliser.reset()
        self.assertEqual(stabiliser.update([cell("Z")]), [cell("Z")],
                         "reset did not clear the displayed grid")


if __name__ == "__main__":
    unittest.main()
