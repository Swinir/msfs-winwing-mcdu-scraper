"""
MobiFlight WebSocket client for communication with WinWing CDU hardware
"""

import asyncio
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
        
        logger.info(f"MobiFlightClient initialized for {websocket_uri}")
    
    async def run(self):
        """Connect to MobiFlight WebSocket server and maintain connection"""
        while self.running and self.retries < self.max_retries:
            try:
                if self.websocket is None:
                    logger.info(f"Connecting to MobiFlight at {self.websocket_uri}")
                    
                    # Connect with ping disabled as per MobiFlight requirements
                    self.websocket = await ws_client.connect(
                        self.websocket_uri,
                        ping_interval=None  # CRITICAL: Must be None for stability
                    )
                    
                    logger.info(f"MobiFlight connected at {self.websocket_uri}")
                    
                    # Set font (CRITICAL - must be done first)
                    await self._set_font()
                    
                    # Wait for font to load
                    await asyncio.sleep(1)
                    
                    # Reset retry counter on successful connection
                    self.retries = 0
                    self.connected.set()
                
                # Keep connection alive by receiving messages
                await self.websocket.recv()
                
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"WebSocket connection closed for {self.websocket_uri}")
                self.websocket = None
                self.connected.clear()
                self.retries += 1
                await asyncio.sleep(5)
                
            except Exception as e:
                self.retries += 1
                logger.error(
                    f"WebSocket error for {self.websocket_uri}: {e}, "
                    f"retry {self.retries}/{self.max_retries}"
                )
                self.websocket = None
                self.connected.clear()
                await asyncio.sleep(5)
        
        if self.retries >= self.max_retries:
            logger.error(f"Max retries reached for {self.websocket_uri}")
        
        # Set connected even on failure to prevent blocking
        self.connected.set()
    
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
        Send JSON data to WinWing CDU
        
        Args:
            data: JSON string to send
        """
        if self.websocket and self.connected.is_set():
            try:
                await self.websocket.send(data)
                logger.debug(f"Sent data: {data[:100]}...")  # Log first 100 chars
            except Exception as e:
                logger.error(f"Failed to send data: {e}")
                self.websocket = None
                self.connected.clear()
        else:
            logger.debug("WebSocket not connected, skipping send")
    
    async def send_display_data(self, display_data: list):
        """
        Send display data to WinWing CDU
        
        Args:
            display_data: List of 336 elements, each either [] or [char, color, size]
        """
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
