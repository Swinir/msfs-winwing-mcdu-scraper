"""
Main application entry point for MSFS A330 WinWing MCDU Scraper
"""

import asyncio
import logging
import sys
from pathlib import Path

from config import Config
from screen_capture import ScreenCapture
from mcdu_parser import MCDUParser
from mobiflight_client import MobiFlightClient


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('mcdu_scraper.log')
    ]
)

logger = logging.getLogger(__name__)


class MCDUScraper:
    """Main MCDU scraper application"""
    
    def __init__(self, config: Config):
        """
        Initialize MCDU scraper
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.clients = {}
        self.captures = {}
        self.running = False
        
        logger.info("MCDU Scraper initialized")
    
    async def start(self):
        """Start the MCDU scraper application"""
        self.running = True
        
        # Initialize captain MCDU if enabled
        if self.config.get_captain_enabled():
            logger.info("Initializing Captain MCDU...")
            await self._init_mcdu(
                'captain',
                self.config.get_captain_url(),
                self.config.get_captain_region()
            )
        
        # Initialize copilot MCDU if enabled
        if self.config.get_copilot_enabled():
            logger.info("Initializing Co-Pilot MCDU...")
            await self._init_mcdu(
                'copilot',
                self.config.get_copilot_url(),
                self.config.get_copilot_region()
            )
        
        if not self.clients:
            logger.error("No MCDUs enabled in configuration!")
            return
        
        # Wait for all clients to connect
        logger.info("Waiting for WebSocket connections...")
        for name, client in self.clients.items():
            await client.connected.wait()
            logger.info(f"{name.capitalize()} MCDU WebSocket ready")
        
        # Start main capture loop
        logger.info("Starting main capture loop...")
        await self._main_loop()
    
    async def _init_mcdu(self, name: str, websocket_uri: str, screen_region: dict):
        """
        Initialize MCDU client and screen capture
        
        Args:
            name: MCDU name ('captain' or 'copilot')
            websocket_uri: WebSocket URI
            screen_region: Screen region dictionary
        """
        # Create MobiFlight client
        client = MobiFlightClient(
            websocket_uri=websocket_uri,
            font=self.config.get_font(),
            max_retries=self.config.get_max_retries()
        )
        self.clients[name] = client
        
        # Create screen capture
        capture = ScreenCapture(screen_region)
        self.captures[name] = capture
        
        # Start client connection task
        asyncio.create_task(client.run())
    
    async def _main_loop(self):
        """Main capture and processing loop"""
        fps = self.config.get_capture_fps()
        frame_delay = 1.0 / fps
        
        logger.info(f"Main loop running at {fps} FPS")
        
        frame_count = 0
        
        try:
            while self.running:
                frame_start = asyncio.get_event_loop().time()
                
                # Process each enabled MCDU
                for name, capture in self.captures.items():
                    try:
                        # Capture screen
                        img = capture.capture()
                        
                        # Parse MCDU grid
                        parser = MCDUParser(
                            img,
                            columns=Config.CDU_COLUMNS,
                            rows=Config.CDU_ROWS
                        )
                        display_data = parser.parse_grid()
                        
                        # Send to WinWing
                        client = self.clients[name]
                        await client.send_display_data(display_data)
                        
                        frame_count += 1
                        if frame_count % (fps * 10) == 0:  # Log every 10 seconds
                            logger.info(f"{name.capitalize()} MCDU: {frame_count} frames processed")
                        
                    except Exception as e:
                        logger.error(f"Error processing {name} MCDU: {e}")
                
                # Maintain target FPS
                frame_elapsed = asyncio.get_event_loop().time() - frame_start
                sleep_time = max(0, frame_delay - frame_elapsed)
                await asyncio.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the MCDU scraper application"""
        self.running = False
        logger.info("Stopping MCDU scraper...")
        
        # Close all clients
        for name, client in self.clients.items():
            await client.close()
            logger.info(f"{name.capitalize()} MCDU client closed")
        
        # Close all screen captures
        for name, capture in self.captures.items():
            capture.close()
            logger.info(f"{name.capitalize()} MCDU screen capture closed")
        
        logger.info("MCDU scraper stopped")


async def main():
    """Main entry point"""
    logger.info("="*60)
    logger.info("MSFS A330 WinWing MCDU Scraper")
    logger.info("="*60)
    
    try:
        # Load configuration
        config = Config()
        logger.info("Configuration loaded successfully")
        
        # Create and start scraper
        scraper = MCDUScraper(config)
        await scraper.start()
        
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please copy config.yaml.example to config.yaml and configure it")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
