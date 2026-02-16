"""
MobiFlight WebSocket client for communication with WinWing CDU hardware
"""

import asyncio
import websockets
import websockets.asyncio.client as ws_client
import json
import logging

logger = logging.getLogger(__name__)


class MobiFlightClient:
    """WebSocket client for MobiFlight/WinWing CDU communication"""
    
    def __init__(self, websocket_uri: str, font: str = "AirbusThales", max_retries: int = 3):
        """
        Initialize MobiFlight client
        
        Args:
            websocket_uri: WebSocket URI (e.g., ws://localhost:8320/winwing/cdu-captain)
            font: Font name to use (default: AirbusThales)
            max_retries: Maximum connection retry attempts
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
                logger.warning(f"WebSocket connection closed for {self.websocket_uri}")
                self.websocket = None
                self.connected.clear()
                self.retries += 1
                await asyncio.sleep(2)

            except Exception as e:
                self.retries += 1
                logger.error(
                    f"WebSocket error for {self.websocket_uri}: {e}, "
                    f"retry {self.retries}"
                )
                self.websocket = None
                self.connected.clear()
                await asyncio.sleep(2)
    
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
    
    async def send(self, data: str):
        """
        Send JSON data to WinWing CDU.
        If the connection is lost, attempt an immediate reconnect.
        """
        for attempt in range(2):  # try once, reconnect once if needed
            if self.websocket and self.connected.is_set():
                try:
                    await self.websocket.send(data)
                    logger.debug(f"Sent data: {data[:100]}...")
                    return
                except Exception as e:
                    logger.warning(f"Send failed ({e}), reconnecting...")
                    self.websocket = None
                    self.connected.clear()
            # Try to reconnect before the second attempt
            try:
                await self._connect()
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")
                await asyncio.sleep(1)
        logger.error("Failed to send data after reconnect attempt")
    
    async def send_display_data(self, display_data: list):
        """
        Send display data to WinWing CDU
        
        Args:
            display_data: List of 336 elements, each either [] or [char, color, size]
        """
        non_empty = sum(1 for cell in display_data if cell)
        logger.debug(f"Sending display data: {non_empty}/{len(display_data)} non-empty cells")
        message = {
            "Target": "Display",
            "Data": display_data
        }
        await self.send(json.dumps(message))
    
    async def close(self):
        """Close WebSocket connection"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            logger.info(f"WebSocket closed for {self.websocket_uri}")
