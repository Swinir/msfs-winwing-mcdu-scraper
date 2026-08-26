"""
Shared capture -> parse -> stabilise -> send pipeline.

Both front ends drive this module, so their behaviour cannot drift apart.
Previously the GUI had frame-change detection, temporal stabilisation and
send-on-change while the CLI had none of it, and the two loops had to be
kept in sync by hand.

Progress is reported through the logging module rather than callbacks: the
GUI already attaches a handler to the root logger, so it picks these up
without any extra wiring.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from mcdu_parser import MCDUParser

logger = logging.getLogger(__name__)


@dataclass
class PipelineSettings:
    """Tuning knobs for one MCDU's capture loop."""

    fps: int = 30
    #: When True, a frame close enough to the previous one reuses its parse
    #: result instead of re-running OCR.
    enable_caching: bool = True
    #: Mean-squared-error below which two frames count as identical.
    frame_change_mse: float = 3.0
    #: A cell only reaches the CDU once its new value has held for this many
    #: consecutive frames.  Suppresses per-frame OCR jitter.
    stability_frames: int = 3
    #: Emit a diagnostic frame/grid dump every N frames.  0 disables it.
    debug_interval: int = 150


class DisplayStabiliser:
    """Holds a cell's displayed value until a new one proves itself.

    OCR output jitters from frame to frame.  Forwarding every change makes
    the physical CDU flicker, so a new value must be seen
    stability_frames times in a row before it is promoted.
    """

    def __init__(self, stability_frames: int = 3) -> None:
        self.stability_frames = max(1, stability_frames)
        self._stable: Optional[list] = None
        self._pending: Optional[list] = None
        self._counts: Optional[list] = None

    def update(self, display_data: list) -> list:
        """Feed one parsed frame, return the stabilised grid to display."""
        if self._stable is None:
            self._stable = list(display_data)
            self._pending = list(display_data)
            self._counts = [0] * len(display_data)
            return list(self._stable)

        for i in range(min(len(display_data), len(self._stable))):
            incoming = display_data[i]
            if incoming == self._stable[i]:
                # Already displayed - cancel any pending change.
                self._counts[i] = 0
                self._pending[i] = incoming
            elif incoming == self._pending[i]:
                self._counts[i] += 1
                if self._counts[i] >= self.stability_frames:
                    self._stable[i] = incoming
                    self._counts[i] = 0
            else:
                # A different candidate - restart its count.  The promotion
                # check has to run here too, otherwise stability_frames=1
                # (promote on first sighting) would still take two frames.
                self._pending[i] = incoming
                self._counts[i] = 1
                if self._counts[i] >= self.stability_frames:
                    self._stable[i] = incoming
                    self._counts[i] = 0

        return list(self._stable)

    def reset(self) -> None:
        self._stable = None
        self._pending = None
        self._counts = None


#: The WinWing CDU hardware always shows this grid, whatever the aircraft's
#: FMS displays.  Smaller profile grids are padded out before sending.
HARDWARE_COLUMNS = 24
HARDWARE_ROWS = 14


def _squeeze_row(row: list, target: int) -> list:
    """Reduce a row to *target* cells by dropping blanks, content last.

    Preference order: trailing blanks, then leading blanks, then one cell
    out of the widest interior blank gap (which keeps the left- and
    right-aligned fields of a line as close to their columns as possible).
    Only when a row is completely full does content get truncated, from the
    right.
    """
    row = list(row)
    excess = len(row) - target
    while excess and row and not row[-1]:
        row.pop()
        excess -= 1
    while excess and row and not row[0]:
        row.pop(0)
        excess -= 1
    while excess:
        # Widest run of empty cells, drop one from its middle.
        best_start, best_len, start = -1, 0, None
        for i, cell in enumerate(row + [["x"]]):    # sentinel ends a run
            if not cell and start is None:
                start = i
            elif cell and start is not None:
                if i - start > best_len:
                    best_start, best_len = start, i - start
                start = None
        if best_len == 0:
            row = row[:target]
            break
        row.pop(best_start + best_len // 2)
        excess -= 1
    return row + [[]] * (target - len(row))


def pad_to_hardware(cells: list, columns: int, rows: int) -> list:
    """Fit a columns x rows grid onto the fixed 24x14 hardware grid.

    Smaller grids are padded top-left with empty cells.  A grid *wider* than
    the hardware - the Just Flight GNLU910 renders 25 columns - is squeezed
    per row by dropping blank cells (see _squeeze_row), so the line-select
    prompts at both edges survive.  Extra rows are dropped from the bottom.
    MobiFlight always receives exactly HARDWARE_COLUMNS * HARDWARE_ROWS
    cells.
    """
    if columns == HARDWARE_COLUMNS and rows == HARDWARE_ROWS:
        return cells
    out = []
    for row in range(HARDWARE_ROWS):
        if row >= rows:
            out.extend([[]] * HARDWARE_COLUMNS)
            continue
        start = row * columns
        line = list(cells[start:start + columns])
        line += [[]] * (columns - len(line))
        if columns > HARDWARE_COLUMNS:
            line = _squeeze_row(line, HARDWARE_COLUMNS)
        else:
            line += [[]] * (HARDWARE_COLUMNS - columns)
        out.extend(line)
    return out


def format_grid(display_data: list, columns: int, rows: int) -> List[str]:
    """Render a parsed grid as text lines for diagnostic logging."""
    lines = []
    for r in range(rows):
        chars, colors = [], []
        for c in range(columns):
            idx = r * columns + c
            cell = display_data[idx] if idx < len(display_data) else None
            if cell:
                chars.append(cell[0][0] if len(cell[0]) > 1 else cell[0])
                colors.append(cell[1])
            else:
                chars.append(" ")
                colors.append(" ")
        lines.append(f"R{r:02d} |{''.join(chars)}| c:{''.join(colors)}")
    return lines


class MCDUPipeline:
    """Drives one MCDU: capture, parse, stabilise, send."""

    def __init__(self, name, capture, client, columns: int, rows: int,
                 settings: Optional[PipelineSettings] = None,
                 small_font_rule: str = "labels_small") -> None:
        """
        Args:
            name: Identifier for this MCDU ('captain', 'copilot', ...).  Also
                namespaces the parser's row caches, so it must be unique.
            capture: Object exposing capture() -> np.ndarray.
            client: Object exposing async send_display_data(list).
            columns: Grid width in characters.
            rows: Grid height in characters.
            settings: Tuning knobs; defaults are used when omitted.
        """
        self.name = name
        self.capture = capture
        self.client = client
        self.columns = columns
        self.rows = rows
        self.small_font_rule = small_font_rule
        self.settings = settings or PipelineSettings()

        self._running = False
        self._stabiliser = DisplayStabiliser(self.settings.stability_frames)
        self._last_frame: Optional[np.ndarray] = None
        self._last_parsed: Optional[list] = None
        self._last_sent: Optional[list] = None
        self.frame_count = 0

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Ask the loop to finish after the current frame."""
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Capture and forward frames until stop() is called."""
        self._running = True
        frame_delay = 1.0 / max(1, self.settings.fps)
        logger.info("%s pipeline running at %d FPS",
                    self.name.capitalize(), self.settings.fps)

        while self._running:
            started = asyncio.get_event_loop().time()
            try:
                await self.tick()
            except Exception as exc:
                logger.error("Error processing %s MCDU: %s",
                             self.name, exc, exc_info=True)
            elapsed = asyncio.get_event_loop().time() - started
            await asyncio.sleep(max(0.0, frame_delay - elapsed))

    # ------------------------------------------------------------------
    #  One frame
    # ------------------------------------------------------------------
    async def tick(self) -> list:
        """Process exactly one frame.  Returns the stabilised grid."""
        img = self.capture.capture()
        self.frame_count += 1

        parse_ms = 0.0
        if self._is_unchanged(img) and self._last_parsed is not None:
            display_data = self._last_parsed
        else:
            t0 = time.perf_counter()
            display_data = await self._parse(img)
            parse_ms = (time.perf_counter() - t0) * 1000
            self._last_frame = img.copy()
            self._last_parsed = display_data

        display_data = self._stabiliser.update(display_data)

        self._log_diagnostics(img, display_data, parse_ms)

        # The hardware is a fixed 24x14 whatever the FMS shows; pad smaller
        # profile grids out to it.
        display_data = pad_to_hardware(display_data, self.columns, self.rows)

        # Only touch the hardware when the stabilised grid actually changed.
        if display_data != self._last_sent:
            await self.client.send_display_data(display_data)
            self._last_sent = list(display_data)

        return display_data

    async def _parse(self, img: np.ndarray) -> list:
        """Run the parser off the event loop.

        parse_grid() is synchronous OpenCV work, and on the first run it
        includes roughly 30 seconds of EasyOCR warmup.  Calling it inline
        would stall the loop, the WebSocket task and - in the CLI - every
        other MCDU.
        """
        def work() -> list:
            parser = MCDUParser(
                img,
                columns=self.columns,
                rows=self.rows,
                source_id=self.name,
                small_font_rule=self.small_font_rule,
            )
            return parser.parse_grid()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, work)

    def _is_unchanged(self, img: np.ndarray) -> bool:
        """True when img is close enough to the last frame to reuse it."""
        if not self.settings.enable_caching:
            return False
        if self._last_frame is None or img.shape != self._last_frame.shape:
            return False
        mse = float(np.mean(
            (img.astype(np.float32) - self._last_frame.astype(np.float32)) ** 2
        ))
        return mse < self.settings.frame_change_mse

    # ------------------------------------------------------------------
    #  Diagnostics
    # ------------------------------------------------------------------
    def _log_diagnostics(self, img: np.ndarray,
                         display_data: list, parse_ms: float) -> None:
        interval = self.settings.debug_interval
        if interval <= 0 or self.frame_count % interval != 1:
            return

        brightness = float(np.mean(img))
        logger.info(
            "[%s] Frame #%d: shape=%s avg_brightness=%.1f min=%d max=%d",
            self.name, self.frame_count, img.shape, brightness,
            int(img.min()), int(img.max()),
        )
        if brightness < 5.0:
            logger.warning(
                "[%s] Captured image is nearly all black - the window "
                "content may not be captured correctly.", self.name,
            )

        non_empty = [c for c in display_data if c]
        logger.info(
            "[%s] OCR: %d/%d cells detected (%.0f ms)",
            self.name, len(non_empty), len(display_data), parse_ms,
        )
        if not non_empty:
            logger.warning(
                "[%s] No characters detected. Check that the MCDU content "
                "is visible in the captured area.", self.name,
            )
            return

        logger.info("[%s] -- MCDU Grid --", self.name)
        for line in format_grid(display_data, self.columns, self.rows):
            logger.info("[%s] %s", self.name, line)
        logger.info("[%s] -- End Grid --", self.name)
