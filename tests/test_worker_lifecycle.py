"""
Starting and stopping the capture worker.

The window only leaves its running state when the worker thread finishes,
so anything that can make the worker wait forever locks the app up with
both buttons disabled.  The obvious such thing is the MobiFlight
connection: the client retries for as long as it takes, by design, because
MobiFlight is usually not running yet when someone first presses Start.

No QApplication is created here.  A QObject does not need one, and these
tests are about the worker's own lifecycle rather than about any widget.
"""

import asyncio
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

try:
    import gui
    from gui import McduSpec, ScraperWorker
    from PySide6.QtCore import Qt
    QT_AVAILABLE = True
except ImportError:                                   # pragma: no cover
    QT_AVAILABLE = False


class FakeConfig:
    """The handful of settings the worker actually asks for."""

    def get_max_retries(self):
        return 3

    def get_capture_fps(self):
        return 30

    def get_enable_caching(self):
        return True


class FakeCapture:
    def capture(self):
        return np.zeros((28, 48, 3), dtype=np.uint8)

    def close(self):
        pass


class NeverConnectingClient:
    """A MobiFlight that is not running: connects never, gives up never."""

    def __init__(self, *args, **kwargs):
        self.connected = asyncio.Event()
        self.closed = False

    async def run(self):
        while True:
            await asyncio.sleep(0.05)

    async def send_display_data(self, display_data):
        return False

    async def close(self):
        self.closed = True


@unittest.skipIf(not QT_AVAILABLE, "PySide6 not installed")
class TestStopBeforeConnected(unittest.TestCase):

    def setUp(self):
        self._saved_client = gui.MobiFlightClient
        gui.MobiFlightClient = NeverConnectingClient

    def tearDown(self):
        gui.MobiFlightClient = self._saved_client

    def _worker(self, count=1):
        specs = [
            McduSpec(name=f"mcdu{i}", capture=FakeCapture(),
                     websocket_uri=f"ws://localhost:8320/{i}")
            for i in range(count)
        ]
        return ScraperWorker(FakeConfig(), specs)

    def _run_until_stopped(self, worker, stop_after=0.4, join=6.0):
        """Start the worker on its own thread, then ask it to stop."""
        finished = threading.Event()
        # Direct, so the callback runs on the emitting thread: a queued
        # connection would need a Qt event loop, and there is no
        # QApplication here.
        worker.finished.connect(finished.set, Qt.DirectConnection)

        thread = threading.Thread(target=worker.start, daemon=True)
        thread.start()
        threading.Event().wait(stop_after)   # let it reach the connect wait
        worker.stop()
        thread.join(join)
        return thread, finished

    def test_stop_ends_the_worker_while_it_waits_to_connect(self):
        worker = self._worker()
        thread, finished = self._run_until_stopped(worker)
        self.assertFalse(
            thread.is_alive(),
            "the worker is still waiting for MobiFlight; the window would "
            "stay stuck in its running state with both buttons disabled",
        )
        self.assertTrue(finished.is_set(), "finished was never emitted")

    def test_both_mcdus_are_released(self):
        """Neither pipeline may hold the thread open."""
        worker = self._worker(count=2)
        thread, _ = self._run_until_stopped(worker)
        self.assertFalse(thread.is_alive())

    def test_stopping_before_start_is_harmless(self):
        worker = self._worker()
        worker.stop()          # no loop yet
        thread, finished = self._run_until_stopped(worker, stop_after=0.1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(finished.is_set())


if __name__ == "__main__":
    unittest.main()
