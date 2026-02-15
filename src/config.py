"""
Configuration management for MSFS A330 WinWing MCDU Scraper
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
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
    
    # Special characters mapping (from MobiFlight)
    SPECIAL_CHARS = {
        "\xa0": " ",      # Non-breaking space
        "□": "\u2610",    # Ballot box
        "⬦": "°",         # Degree symbol
        "←": "\u2190",    # Left arrow
        "→": "\u2192",    # Right arrow
        "↑": "\u2191",    # Up arrow
        "↓": "\u2193",    # Down arrow
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
        
        # Validate screen region has required fields
        captain = self.config_data['mcdu']['captain']
        if captain.get('enabled', False):
            region = captain.get('screen_region', {})
            required_fields = ['top', 'left', 'width', 'height']
            for field in required_fields:
                if field not in region:
                    raise ValueError(f"Missing required screen_region field: {field}")
        
        logger.info("Configuration validation passed")
    
    def get_captain_enabled(self) -> bool:
        """Check if captain MCDU is enabled"""
        return self.config_data['mcdu']['captain'].get('enabled', False)
    
    def get_copilot_enabled(self) -> bool:
        """Check if copilot MCDU is enabled"""
        return self.config_data['mcdu'].get('copilot', {}).get('enabled', False)
    
    def get_captain_region(self) -> Dict[str, int]:
        """Get captain screen region"""
        return self.config_data['mcdu']['captain']['screen_region']
    
    def get_copilot_region(self) -> Dict[str, int]:
        """Get copilot screen region"""
        return self.config_data['mcdu']['copilot']['screen_region']
    
    def get_captain_url(self) -> str:
        """Get captain WebSocket URL"""
        return self.config_data['mobiflight']['captain_url']
    
    def get_copilot_url(self) -> str:
        """Get copilot WebSocket URL"""
        return self.config_data['mobiflight']['copilot_url']
    
    def get_font(self) -> str:
        """Get font name"""
        return self.config_data['mobiflight'].get('font', 'AirbusThales')
    
    def get_max_retries(self) -> int:
        """Get max WebSocket connection retries"""
        return self.config_data['mobiflight'].get('max_retries', 3)
    
    def get_capture_fps(self) -> int:
        """Get capture frame rate"""
        return self.config_data['performance'].get('capture_fps', 30)
    
    def get_enable_caching(self) -> bool:
        """Check if caching is enabled"""
        return self.config_data['performance'].get('enable_caching', True)
