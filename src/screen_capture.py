"""
Screen capture module using MSS for fast screen grabbing
"""

import mss
import numpy as np
from PIL import Image
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class ScreenCapture:
    """Screen capture class using MSS library for fast screen grabbing"""
    
    def __init__(self, monitor_region: Dict[str, int]):
        """
        Initialize screen capture
        
        Args:
            monitor_region: Dictionary with keys 'top', 'left', 'width', 'height'
                Example: {"top": 400, "left": 800, "width": 480, "height": 280}
        """
        self.sct = mss.mss()
        self.monitor = monitor_region
        
        logger.info(
            f"Screen capture initialized for region: "
            f"top={monitor_region['top']}, left={monitor_region['left']}, "
            f"width={monitor_region['width']}, height={monitor_region['height']}"
        )
    
    def capture(self) -> np.ndarray:
        """
        Capture MCDU region and return as numpy array
        
        Returns:
            numpy.ndarray: RGB image array (height, width, 3)
        """
        try:
            screenshot = self.sct.grab(self.monitor)
            # Convert to numpy array and extract RGB channels (drop alpha)
            img = np.array(screenshot)
            return img[:, :, :3]  # RGB only, drop alpha channel
        except Exception as e:
            logger.error(f"Screen capture failed: {e}")
            raise
    
    def capture_to_pil(self) -> Image.Image:
        """
        Capture MCDU region and return as PIL Image
        
        Returns:
            PIL.Image: RGB image
        """
        img_array = self.capture()
        return Image.fromarray(img_array)
    
    def close(self):
        """Close the screen capture session"""
        if self.sct:
            self.sct.close()
            logger.info("Screen capture session closed")
