"""
Configuration management for MSFS A330 WinWing MCDU Scraper
"""

import os
import yaml
import logging
from typing import Any, Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for MCDU scraper"""
    
    # Grid specifications (CRITICAL - Must Match MobiFlight)
    CDU_COLUMNS = 24
    CDU_ROWS = 14
    CDU_CELLS = CDU_COLUMNS * CDU_ROWS  # 336 cells total
    
    # Font sizes
    FONT_SIZE_LARGE = 0
    FONT_SIZE_SMALL = 1
    
    # Color codes (MobiFlight Standard)
    COLORS = {
        "w": "white",
        "c": "cyan",
        "g": "green",
        "m": "magenta",
        "a": "amber",
        "r": "red",
        "y": "yellow",
        "e": "grey",  # for disabled/background
        "o": "brown/blue"  # alternate
    }
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration
        
        Args:
            config_path: Path to configuration YAML file
        """
        if config_path is None:
            # Look for config.yaml in current directory, then parent
            config_path = self._find_config_file()
        
        self.config_path = config_path
        self.config_data = self._load_config()
        self._validate_config()
    
    def _find_config_file(self) -> str:
        """Find config.yaml in current or parent directories"""
        search_paths = [
            Path.cwd() / "config.yaml",
            Path(__file__).parent.parent / "config.yaml",
            Path.cwd() / "config.yaml.example",
            Path(__file__).parent.parent / "config.yaml.example"
        ]
        
        for path in search_paths:
            if path.exists():
                logger.info(f"Found configuration file at: {path}")
                return str(path)
        
        raise FileNotFoundError(
            "No config.yaml found. Please copy config.yaml.example to config.yaml "
            "and configure your screen regions."
        )
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _validate_config(self):
        """Validate configuration has required fields"""
        required_sections = ['mcdu', 'mobiflight', 'performance']
        for section in required_sections:
            if section not in self.config_data:
                raise ValueError(f"Missing required configuration section: {section}")
        
        # Validate MCDU configuration
        if 'captain' not in self.config_data['mcdu']:
            raise ValueError("Missing MCDU captain configuration")
        
        logger.info("Configuration validation passed")
    
    def get_captain_enabled(self) -> bool:
        """Check if captain MCDU is enabled"""
        return self.config_data['mcdu']['captain'].get('enabled', False)
    
    def get_copilot_enabled(self) -> bool:
        """Check if copilot MCDU is enabled"""
        return self.config_data['mcdu'].get('copilot', {}).get('enabled', False)
    
    def get_captain_url(self) -> str:
        """Get captain WebSocket URL."""
        url = self.config_data['mobiflight'].get('captain_url')
        if not url:
            raise ValueError(
                "Missing 'mobiflight.captain_url' in config. "
                "Please set it to the WinWing CDU captain WebSocket URI "
                "(e.g. ws://localhost:8320/winwing/cdu-captain)."
            )
        return url

    def get_copilot_url(self) -> str:
        """Get copilot WebSocket URL."""
        url = self.config_data['mobiflight'].get('copilot_url')
        if not url:
            raise ValueError(
                "Missing 'mobiflight.copilot_url' in config. "
                "Please set it to the WinWing CDU co-pilot WebSocket URI "
                "(e.g. ws://localhost:8320/winwing/cdu-co-pilot)."
            )
        return url

    def get_crop_region(self, mcdu: str) -> Optional[Tuple[int, int, int, int]]:
        """Get the optional crop region for an MCDU, as (x, y, width, height).

        The captured window usually contains far more than the MCDU screen.
        Without a crop the whole window is carved into the character grid and
        the parse is meaningless, so this is how the CLI is told which part of
        the window to look at.  The GUI sets the same thing interactively via
        its region selector.

        Args:
            mcdu: 'captain' or 'copilot'.

        Returns:
            (x, y, width, height), or None when no crop is configured.
        """
        section = self.config_data['mcdu'].get(mcdu) or {}
        crop = section.get('crop')
        if not crop:
            return None

        missing = [k for k in ('x', 'y', 'width', 'height') if k not in crop]
        if missing:
            raise ValueError(
                f"Incomplete crop region for the {mcdu} MCDU: missing "
                f"{', '.join(missing)}. A crop needs x, y, width and height."
            )

        try:
            x, y = int(crop['x']), int(crop['y'])
            width, height = int(crop['width']), int(crop['height'])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Crop region for the {mcdu} MCDU has non-numeric values: {exc}"
            ) from exc

        if width <= 0 or height <= 0:
            raise ValueError(
                f"Crop region for the {mcdu} MCDU must have a positive width "
                f"and height, got {width}x{height}."
            )
        if x < 0 or y < 0:
            raise ValueError(
                f"Crop region for the {mcdu} MCDU must have non-negative x/y, "
                f"got x={x}, y={y}."
            )

        return (x, y, width, height)

    def get_captain_window_title(self) -> str:
        """Get the window title used to locate the captain MCDU capture window."""
        return self.config_data['mcdu']['captain'].get('window_title', '')

    def get_copilot_window_title(self) -> str:
        """Get the window title used to locate the copilot MCDU capture window."""
        return self.config_data['mcdu'].get('copilot', {}).get('window_title', '')
    
    def get_font(self) -> str:
        """Get font name"""
        return self.config_data['mobiflight'].get('font', 'AirbusThales')
    
    def get_max_retries(self) -> int:
        """Get max WebSocket connection retries"""
        return self.config_data['mobiflight'].get('max_retries', 3)
    
    def get_capture_fps(self) -> int:
        """Get capture frame rate, clamped to [1, 120]."""
        raw = self.config_data['performance'].get('capture_fps', 30)
        return max(1, min(120, int(raw)))
    
    def get_enable_caching(self) -> bool:
        """Check if caching is enabled"""
        return self.config_data['performance'].get('enable_caching', True)
