"""
Main application entry point for MSFS A330 WinWing MCDU Scraper
"""

import asyncio
import logging
import sys

from config import Config
from mobiflight_client import MobiFlightClient
from pipeline import MCDUPipeline, PipelineSettings
from window_capture import WindowCapture


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
        self.pipelines = {}
        self._tasks = []

        logger.info("MCDU Scraper initialized")

    def _settings(self) -> PipelineSettings:
        """Build pipeline settings from configuration."""
        return PipelineSettings(
            fps=self.config.get_capture_fps(),
            enable_caching=self.config.get_enable_caching(),
        )

    async def start(self):
        """Start the MCDU scraper application"""
        # Initialize captain MCDU if enabled
        if self.config.get_captain_enabled():
            logger.info("Initializing Captain MCDU...")
            await self._init_mcdu('captain', self.config.get_captain_url())

        # Initialize copilot MCDU if enabled
        if self.config.get_copilot_enabled():
            logger.info("Initializing Co-Pilot MCDU...")
            await self._init_mcdu('copilot', self.config.get_copilot_url())

        if not self.clients:
            logger.error("No MCDUs enabled in configuration!")
            return

        # Wait for all clients to connect
        logger.info("Waiting for WebSocket connections...")
        for name, client in self.clients.items():
            await client.connected.wait()
            logger.info(f"{name.capitalize()} MCDU WebSocket ready")

        # Each MCDU runs its own pipeline concurrently.  Driving them from a
        # single shared loop would halve each one's effective frame rate.
        logger.info("Starting capture pipelines...")
        try:
            await asyncio.gather(*(p.run() for p in self.pipelines.values()))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
        finally:
            await self.stop()

    async def _init_mcdu(self, name: str, websocket_uri: str):
        """
        Initialize MCDU client, window capture and pipeline.

        Args:
            name: MCDU name ('captain' or 'copilot')
            websocket_uri: WebSocket URI
        """
        # Resolve window title from config
        if name == 'captain':
            window_title = self.config.get_captain_window_title()
        else:
            window_title = self.config.get_copilot_window_title()

        if not window_title:
            raise ValueError(
                f"No window_title configured for the {name} MCDU. "
                f"Please set mcdu.{name}.window_title in config.yaml to a "
                f"substring of the MSFS pop-out window title "
                f"(e.g. 'Microsoft Flight Simulator')."
            )

        crop_region = self.config.get_crop_region(name)

        # Create window capture
        capture = WindowCapture(window_title=window_title,
                                crop_region=crop_region)
        self.captures[name] = capture
        logger.info(
            f"{name.capitalize()} MCDU window capture initialised "
            f"for '{window_title}'"
        )
        if crop_region:
            x, y, w, h = crop_region
            logger.info(
                f"{name.capitalize()} MCDU crop region: "
                f"x={x}, y={y}, w={w}, h={h}"
            )
        else:
            logger.warning(
                f"No crop region configured for the {name} MCDU - the whole "
                f"window will be carved into a {Config.CDU_COLUMNS}x"
                f"{Config.CDU_ROWS} character grid. Unless the window is "
                f"exactly the MCDU screen, set mcdu.{name}.crop in "
                f"config.yaml. The GUI's 'Select Screen Area' button reports "
                f"the right values."
            )

        # Create MobiFlight client
        client = MobiFlightClient(
            websocket_uri=websocket_uri,
            font=self.config.get_font(),
            max_retries=self.config.get_max_retries()
        )
        self.clients[name] = client

        # Start client connection task
        self._tasks.append(asyncio.create_task(client.run()))

        # Build the capture pipeline
        self.pipelines[name] = MCDUPipeline(
            name=name,
            capture=capture,
            client=client,
            columns=Config.CDU_COLUMNS,
            rows=Config.CDU_ROWS,
            settings=self._settings(),
        )

    async def stop(self):
        """Stop the MCDU scraper application"""
        logger.info("Stopping MCDU scraper...")

        for pipeline in self.pipelines.values():
            pipeline.stop()

        # Cancel the WebSocket keep-alive tasks
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

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
    logger.info("=" * 60)
    logger.info("MSFS A330 WinWing MCDU Scraper")
    logger.info("=" * 60)

    scraper = None
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
    except asyncio.CancelledError:
        if scraper:
            await scraper.stop()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
