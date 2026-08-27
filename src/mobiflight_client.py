"""
MobiFlight WebSocket client for communication with WinWing CDU hardware
"""

import asyncio
import websockets
import websockets.asyncio.client as ws_client
import json
import logging

from mcdu_charset import RENDERABLE, SUBSTITUTIONS, sanitise_char

logger = logging.getLogger(__name__)

# The renderable set and the substitution table live in mcdu_charset so the
# parser and this client cannot drift apart on what a character may be.
# Re-exported under the old private names: existing callers and tests use them.
_CDU_SAFE_CHARS = RENDERABLE
_CDU_CHAR_MAP = SUBSTITUTIONS


def sanitise_display_data(display_data: list) -> list:
    """Map a 336-cell display grid onto glyphs the CDU font can render.

    Any character that is neither in ``_CDU_CHAR_MAP`` nor already in
    ``_CDU_SAFE_CHARS`` becomes a space.  Not for the device's safety - it
    forwards whatever it is given, see the note in mcdu_charset - but so
    that a glyph the font cannot draw shows as a blank rather than as
    whatever the font happens to have at that code point.

    Args:
        display_data: List of elements, each either ``[]`` or
            ``[char, colour, size]``.

    Returns:
        A new list of the same length with every character sanitised.
    """
    sanitised = []
    for cell in display_data:
        if not cell:
            sanitised.append([])
            continue
        out = [sanitise_char(cell[0]), cell[1], cell[2]]
        # Optional fourth element: reverse video.  Only sent when set, so
        # ordinary cells stay three-element as every other integration
        # sends them.
        if len(cell) > 3 and cell[3]:
            out.append(True)
        sanitised.append(out)
    return sanitised


class MobiFlightClient:
    """WebSocket client for MobiFlight/WinWing CDU communication"""

    #: Delay between the first few reconnect attempts, in seconds.
    BASE_RETRY_DELAY = 2.0
    #: Upper bound on the backoff delay, in seconds.
    MAX_RETRY_DELAY = 30.0

    def __init__(self, websocket_uri: str, font: str = "AirbusThales", max_retries: int = 3):
        """
        Initialize MobiFlight client

        Args:
            websocket_uri: WebSocket URI (e.g., ws://localhost:8320/winwing/cdu-captain)
            font: Font name to use (default: AirbusThales)
            max_retries: Consecutive failures tolerated at the base retry
                delay before the client starts backing off exponentially.
                The client never stops trying — MobiFlight is often simply
                not running yet — so this controls how fast it gives the
                socket a rest, not whether it gives up.
        """
        self.websocket = None
        self.connected = asyncio.Event()
        self.websocket_uri = websocket_uri
        self.font = font
        self.retries = 0
        self.max_retries = max_retries
        self.running = True
        self._connect_lock = asyncio.Lock()

        logger.info(f"MobiFlightClient initialized for {websocket_uri}")

    async def _connect(self):
        """Establish (or re-establish) the WebSocket connection.

        Uses a lock so that concurrent callers (run() and send()) don't
        open two sockets at the same time.
        """
        async with self._connect_lock:
            # Another caller may have already reconnected while we waited
            if self.websocket is not None and self.connected.is_set():
                return
            self.websocket = None
            self.connected.clear()
            logger.info(f"Connecting to MobiFlight at {self.websocket_uri}")
            self.websocket = await ws_client.connect(
                self.websocket_uri,
                ping_interval=None  # CRITICAL: Must be None for stability
            )
            logger.info(f"MobiFlight connected at {self.websocket_uri}")
            await self._set_font()
            await asyncio.sleep(1)
            self.retries = 0
            self.connected.set()

    def _retry_delay(self) -> float:
        """Seconds to wait before the next reconnect attempt.

        Retries stay at BASE_RETRY_DELAY while the failure count is within
        max_retries, then double up to MAX_RETRY_DELAY.  This is what
        max_retries actually controls: previously it was stored, incremented
        against, and never read, so a mistyped URL reconnected every two
        seconds forever and filled the log.
        """
        if self.retries <= self.max_retries:
            return self.BASE_RETRY_DELAY
        excess = self.retries - self.max_retries
        return min(self.BASE_RETRY_DELAY * (2 ** excess), self.MAX_RETRY_DELAY)

    def _log_retry(self, reason: str) -> None:
        """Report a failed connection, escalating once past max_retries."""
        delay = self._retry_delay()
        message = (
            "%s for %s (attempt %d) — retrying in %.0fs"
        )
        args = (reason, self.websocket_uri, self.retries, delay)
        if self.retries > self.max_retries:
            logger.error(message, *args)
        else:
            logger.warning(message, *args)

    async def run(self):
        """Connect to MobiFlight WebSocket server and maintain connection.

        Automatically reconnects on any error with a short back-off.
        Never gives up while self.running is True.
        """
        while self.running:
            try:
                if self.websocket is None:
                    await self._connect()

                # Drain incoming messages (non-blocking, with a short timeout
                # so we don't block the event loop forever).
                try:
                    await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass  # nothing received — that's fine

            except websockets.exceptions.ConnectionClosed:
                self.websocket = None
                self.connected.clear()
                self.retries += 1
                self._log_retry("WebSocket connection closed")
                await asyncio.sleep(self._retry_delay())

            except Exception as e:
                self.websocket = None
                self.connected.clear()
                self.retries += 1
                self._log_retry(f"WebSocket error ({e})")
                await asyncio.sleep(self._retry_delay())

    async def _set_font(self):
        """Send font configuration to WinWing CDU"""
        try:
            font_message = json.dumps({
                "Target": "Font",
                "Data": self.font
            })
            await self.websocket.send(font_message)
            logger.info(f"Font set to: {self.font}")
        except Exception as e:
            logger.error(f"Failed to set font: {e}")

    async def send(self, data: str) -> bool:
        """Send one JSON message, reconnecting once if the socket has gone.

        Returns:
            True if the message reached the socket.  The caller needs to
            know: the pipeline only sends a grid when it differs from the
            last one it sent, so a failure it is not told about leaves the
            CDU showing the previous page until the aircraft happens to
            change something.
        """
        for _ in range(2):      # try once, reconnect and try once more
            if self.websocket and self.connected.is_set():
                try:
                    await self.websocket.send(data)
                    logger.debug("Sent %d bytes", len(data))
                    return True
                except Exception as exc:
                    logger.warning("Send failed (%s), reconnecting …", exc)
                    self.websocket = None
                    self.connected.clear()
            try:
                await self._connect()
            except Exception as exc:
                logger.error("Reconnect failed: %s", exc)
                await asyncio.sleep(1)
        logger.error("Failed to send data after a reconnect attempt")
        return False

    async def send_display_data(self, display_data: list) -> bool:
        """
        Send display data to WinWing CDU.  Returns True if it was sent.

        Sanitises every character first, so the CDU is never asked to draw
        a glyph its font does not carry.

        Args:
            display_data: List of 336 elements, each either [] or
            [char, colour, size] - optionally [char, colour, size, inverted]
            for reverse video.
        """
        sanitised = sanitise_display_data(display_data)

        if logger.isEnabledFor(logging.DEBUG):
            non_empty = sum(1 for cell in sanitised if cell)
            logger.debug("Sending display data: %d/%d non-empty cells",
                         non_empty, len(sanitised))
        return await self.send(json.dumps({
            "Target": "Display",
            "Data": sanitised,
        }))

    async def close(self):
        """Close WebSocket connection"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            logger.info(f"WebSocket closed for {self.websocket_uri}")
