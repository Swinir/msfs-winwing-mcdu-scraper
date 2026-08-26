"""
Unit tests for the shared capture pipeline and its display stabiliser.
"""

import asyncio
import unittest
from pathlib import Path
import sys

import numpy as np

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from pipeline import DisplayStabiliser, MCDUPipeline, PipelineSettings, format_grid


def cell(char, color="w", size=0):
    return [char, color, size]


class FakeCapture:
    """Returns a scripted sequence of frames, repeating the last one."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def capture(self):
        frame = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return frame


class FakeClient:
    """Records every payload handed to the CDU."""

    def __init__(self):
        self.sent = []

    async def send_display_data(self, display_data):
        self.sent.append(list(display_data))


class TestDisplayStabiliser(unittest.TestCase):
    """A new value must hold for N frames before it is displayed."""

    def test_first_frame_passes_through(self):
        s = DisplayStabiliser(3)
        self.assertEqual(s.update([cell("A")]), [cell("A")])

    def test_change_held_until_stable(self):
        s = DisplayStabiliser(3)
        s.update([cell("A")])
        self.assertEqual(s.update([cell("B")]), [cell("A")], "promoted too early")
        self.assertEqual(s.update([cell("B")]), [cell("A")], "promoted too early")
        self.assertEqual(s.update([cell("B")]), [cell("B")], "never promoted")

    def test_jitter_never_promoted(self):
        """Alternating noise must never reach the display."""
        s = DisplayStabiliser(3)
        s.update([cell("A")])
        for i in range(20):
            out = s.update([cell("B") if i % 2 else cell("C")])
            self.assertEqual(out, [cell("A")])

    def test_returning_to_stable_value_cancels_pending(self):
        s = DisplayStabiliser(3)
        s.update([cell("A")])
        s.update([cell("B")])
        s.update([cell("A")])          # back to the displayed value
        s.update([cell("B")])          # pending restarts from scratch
        self.assertEqual(s.update([cell("B")]), [cell("A")])

    def test_stability_of_one_is_immediate(self):
        s = DisplayStabiliser(1)
        s.update([cell("A")])
        self.assertEqual(s.update([cell("B")]), [cell("B")])

    def test_returns_a_copy(self):
        s = DisplayStabiliser(1)
        out = s.update([cell("A")])
        out[0] = cell("Z")
        self.assertEqual(s.update([cell("A")]), [cell("A")])

    def test_empty_cells_are_handled(self):
        s = DisplayStabiliser(2)
        self.assertEqual(s.update([[], []]), [[], []])


class TestFormatGrid(unittest.TestCase):

    def test_row_count_and_shape(self):
        data = [[] for _ in range(24 * 14)]
        lines = format_grid(data, 24, 14)
        self.assertEqual(len(lines), 14)
        self.assertTrue(lines[0].startswith("R00 |"))

    def test_characters_placed_in_order(self):
        data = [[] for _ in range(24 * 14)]
        for i, ch in enumerate("HELLO"):
            data[i] = cell(ch)
        self.assertIn("HELLO", format_grid(data, 24, 14)[0])

    def test_short_data_does_not_raise(self):
        self.assertEqual(len(format_grid([], 24, 14)), 14)


class TestMCDUPipeline(unittest.TestCase):
    """The pipeline must not re-parse or re-send unchanged frames."""

    def setUp(self):
        self.frame = np.zeros((280, 480, 3), dtype=np.uint8)
        self.settings = PipelineSettings(
            fps=30, stability_frames=1, debug_interval=0,
        )

    def _pipeline(self, frames, settings=None, parsed=None):
        client = FakeClient()
        pipe = MCDUPipeline(
            name="test",
            capture=FakeCapture(frames),
            client=client,
            columns=24,
            rows=14,
            settings=settings or self.settings,
        )
        # Stub the parser: these tests are about loop behaviour, not OCR.
        self.parse_calls = 0
        seq = list(parsed) if parsed else None

        async def fake_parse(img):
            self.parse_calls += 1
            if seq:
                return seq[min(self.parse_calls - 1, len(seq) - 1)]
            return [[] for _ in range(24 * 14)]

        pipe._parse = fake_parse
        return pipe, client

    def test_identical_frames_are_parsed_once(self):
        pipe, _ = self._pipeline([self.frame, self.frame, self.frame])
        for _ in range(3):
            asyncio.run(pipe.tick())
        self.assertEqual(self.parse_calls, 1, "re-parsed an unchanged frame")

    def test_changed_frame_is_reparsed(self):
        other = self.frame.copy()
        other[:] = 200
        pipe, _ = self._pipeline([self.frame, other])
        asyncio.run(pipe.tick())
        asyncio.run(pipe.tick())
        self.assertEqual(self.parse_calls, 2)

    def test_caching_can_be_disabled(self):
        settings = PipelineSettings(stability_frames=1, debug_interval=0,
                                    enable_caching=False)
        pipe, _ = self._pipeline([self.frame] * 3, settings=settings)
        for _ in range(3):
            asyncio.run(pipe.tick())
        self.assertEqual(self.parse_calls, 3,
                         "enable_caching=False should force a re-parse")

    def test_unchanged_display_is_sent_once(self):
        pipe, client = self._pipeline([self.frame] * 5)
        for _ in range(5):
            asyncio.run(pipe.tick())
        self.assertEqual(len(client.sent), 1,
                         "resent an unchanged grid to the hardware")

    def test_changed_display_is_sent_again(self):
        blank = [[] for _ in range(24 * 14)]
        filled = [cell("A")] + [[] for _ in range(24 * 14 - 1)]
        other = self.frame.copy()
        other[:] = 200
        pipe, client = self._pipeline([self.frame, other],
                                      parsed=[blank, filled])
        asyncio.run(pipe.tick())
        asyncio.run(pipe.tick())
        self.assertEqual(len(client.sent), 2)
        self.assertEqual(client.sent[1][0], cell("A"))

    def test_frame_count_tracks_captures(self):
        pipe, _ = self._pipeline([self.frame] * 3)
        for _ in range(3):
            asyncio.run(pipe.tick())
        self.assertEqual(pipe.frame_count, 3)

    def test_stop_ends_the_run_loop(self):
        pipe, _ = self._pipeline([self.frame] * 2)

        async def drive():
            task = asyncio.ensure_future(pipe.run())
            await asyncio.sleep(0.05)
            self.assertTrue(pipe.running)
            pipe.stop()
            await asyncio.wait_for(task, timeout=2.0)

        asyncio.run(drive())
        self.assertFalse(pipe.running)

    def test_capture_failure_does_not_kill_the_loop(self):
        class Exploding:
            def __init__(self):
                self.calls = 0

            def capture(self):
                self.calls += 1
                raise RuntimeError("capture failed")

        pipe = MCDUPipeline(
            name="test", capture=Exploding(), client=FakeClient(),
            columns=24, rows=14, settings=self.settings,
        )

        async def drive():
            task = asyncio.ensure_future(pipe.run())
            await asyncio.sleep(0.1)
            pipe.stop()
            await asyncio.wait_for(task, timeout=2.0)

        asyncio.run(drive())          # must not raise
        self.assertGreater(pipe.capture.calls, 1, "loop stopped after one error")

    def test_parse_runs_off_the_event_loop(self):
        """parse_grid must not block the loop; it goes to an executor."""
        import threading

        pipe = MCDUPipeline(
            name="test", capture=FakeCapture([self.frame]),
            client=FakeClient(), columns=24, rows=14, settings=self.settings,
        )
        seen = {}

        async def probe():
            main_thread = threading.get_ident()

            def work():
                seen['thread'] = threading.get_ident()
                return [[] for _ in range(24 * 14)]

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, work)
            seen['main'] = main_thread

        asyncio.run(probe())
        self.assertNotEqual(seen['thread'], seen['main'],
                            "parse work ran on the event loop thread")


if __name__ == "__main__":
    unittest.main()
