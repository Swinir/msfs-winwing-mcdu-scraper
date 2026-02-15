"""
MCDU parser for extracting character grid from screen captures
"""

import numpy as np
import cv2
import logging
from typing import List, Tuple, Optional
import pytesseract

logger = logging.getLogger(__name__)


class MCDUParser:
    """Parser for MCDU screen captures to extract character grid"""
    
    def __init__(self, image: np.ndarray, columns: int = 24, rows: int = 14):
        """
        Initialize MCDU parser
        
        Args:
            image: numpy array of captured screen (RGB)
            columns: Number of columns in MCDU grid (default: 24)
            rows: Number of rows in MCDU grid (default: 14)
        """
        self.image = image
        self.columns = columns
        self.rows = rows
        self.cell_width = image.shape[1] // columns
        self.cell_height = image.shape[0] // rows
        
        # Cache for detected characters
        self.cache_enabled = True
        self.character_cache = {}
        
        logger.debug(
            f"MCDU Parser initialized: {rows}x{columns} grid, "
            f"cell size: {self.cell_width}x{self.cell_height}px"
        )
    
    def extract_cell(self, row: int, col: int) -> np.ndarray:
        """
        Extract single cell from grid
        
        Args:
            row: Row index (0-based)
            col: Column index (0-based)
            
        Returns:
            numpy.ndarray: Cell image
        """
        x = col * self.cell_width
        y = row * self.cell_height
        return self.image[y:y+self.cell_height, x:x+self.cell_width]
    
    def detect_color(self, cell: np.ndarray) -> str:
        """
        Detect cell color by sampling center pixel
        
        Args:
            cell: Cell image array
            
        Returns:
            str: Color code ('w', 'c', 'g', 'a', 'm', 'r', 'y', 'e', 'o')
        """
        # Sample center and a few nearby pixels for better accuracy
        center_y, center_x = cell.shape[0]//2, cell.shape[1]//2
        
        # Sample 3x3 grid around center and average
        sample_pixels = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                y = max(0, min(cell.shape[0]-1, center_y + dy))
                x = max(0, min(cell.shape[1]-1, center_x + dx))
                sample_pixels.append(cell[y, x])
        
        # Average the sampled pixels
        avg_pixel = np.mean(sample_pixels, axis=0).astype(int)
        r, g, b = avg_pixel
        
        # Color detection thresholds
        # White: High R, G, B
        if r > 200 and g > 200 and b > 200:
            return "w"
        
        # Cyan: Low R, High G, High B
        elif r < 100 and g > 150 and b > 150:
            return "c"
        
        # Green: Low R, High G, Low B
        elif r < 100 and g > 150 and b < 100:
            return "g"
        
        # Amber/Yellow: High R, High G, Low B
        elif r > 200 and g > 150 and b < 100:
            return "a"
        
        # Magenta: High R, Low G, High B
        elif r > 150 and g < 100 and b > 150:
            return "m"
        
        # Red: High R, Low G, Low B
        elif r > 150 and g < 100 and b < 100:
            return "r"
        
        # Yellow: Similar to amber but brighter
        elif r > 200 and g > 200 and b < 150:
            return "y"
        
        # Grey/disabled: Mid-range values
        elif 80 < r < 150 and 80 < g < 150 and 80 < b < 150:
            return "e"
        
        # Default to white
        return "w"
    
    def detect_character(self, cell: np.ndarray) -> Optional[str]:
        """
        Detect character using OCR
        
        Args:
            cell: Cell image array
            
        Returns:
            str or None: Detected character or None if empty
        """
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(cell, cv2.COLOR_RGB2GRAY)
            
            # Apply thresholding to make text more visible
            _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            
            # Upscale for better OCR accuracy
            scale_factor = 3
            upscaled = cv2.resize(
                binary, 
                (cell.shape[1] * scale_factor, cell.shape[0] * scale_factor),
                interpolation=cv2.INTER_CUBIC
            )
            
            # Use Tesseract OCR with single character mode
            config = '--psm 10 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-*/.<>[]()°← →↑↓ '
            text = pytesseract.image_to_string(upscaled, config=config).strip()
            
            # Return first character or None
            if text and len(text) > 0:
                char = text[0]
                # Handle special characters
                if char in ['\xa0', '\u2610', '⬦', '←', '→', '↑', '↓']:
                    return char
                return char.upper() if char.isalnum() else char
            
            return None
            
        except Exception as e:
            logger.debug(f"Character detection failed: {e}")
            return None
    
    def is_empty_cell(self, cell: np.ndarray, threshold: int = 30) -> bool:
        """
        Check if cell is empty (dark/black)
        
        Args:
            cell: Cell image array
            threshold: Brightness threshold for considering cell empty
            
        Returns:
            bool: True if cell appears empty
        """
        # Calculate average brightness
        avg_brightness = np.mean(cell)
        return avg_brightness < threshold
    
    def is_small_font(self, row: int) -> bool:
        """
        Determine if row should use small font based on MCDU layout pattern
        
        Pattern: 
        - Odd rows (1,3,5,7,9,11) are small (labels)
        - Even rows (0,2,4,6,8,10,12) are large (data)
        - Row 13 (scratchpad) is large
        
        Args:
            row: Row index (0-based)
            
        Returns:
            bool: True if small font should be used
        """
        return (row % 2 == 1) and (row != 13)
    
    def parse_grid(self) -> List:
        """
        Parse entire MCDU grid and extract all cells
        
        Returns:
            list: List of 336 elements, each either [] or [char, color, size]
        """
        message_data = []
        
        for row in range(self.rows):
            for col in range(self.columns):
                cell = self.extract_cell(row, col)
                
                # Check if cell is empty
                if self.is_empty_cell(cell):
                    message_data.append([])
                    continue
                
                # Detect character
                char = self.detect_character(cell)
                
                if char and char != ' ':
                    # Detect color
                    color = self.detect_color(cell)
                    
                    # Determine font size
                    size = 1 if self.is_small_font(row) else 0
                    
                    message_data.append([char, color, size])
                else:
                    message_data.append([])
        
        return message_data
