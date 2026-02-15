"""
Window-specific capture module for capturing windows even when minimized or behind other windows
"""

import logging
import numpy as np
from PIL import Image
from typing import List, Tuple, Optional
import sys

logger = logging.getLogger(__name__)

# Platform-specific imports
if sys.platform == 'win32':
    try:
        import win32gui
        import win32ui
        import win32con
        import win32api
        WINDOWS_AVAILABLE = True
    except ImportError:
        logger.warning("pywin32 not available. Window capture will not work. Install with: pip install pywin32")
        WINDOWS_AVAILABLE = False
else:
    WINDOWS_AVAILABLE = False


class WindowCapture:
    """
    Window-specific capture class for capturing specific windows
    Works even when window is minimized or behind other windows (Windows only)
    """
    
    def __init__(self, window_title: Optional[str] = None, window_handle: Optional[int] = None, 
                 crop_region: Optional[Tuple[int, int, int, int]] = None):
        """
        Initialize window capture
        
        Args:
            window_title: Title of the window to capture (will search for partial match)
            window_handle: Direct window handle (HWND) if known
            crop_region: Optional crop region (x, y, width, height) to extract from captured window
        """
        if not WINDOWS_AVAILABLE:
            raise RuntimeError(
                "Window capture is only supported on Windows with pywin32 installed. "
                "Install with: pip install pywin32"
            )
        
        self.window_title = window_title
        self.hwnd = window_handle
        self.crop_region = crop_region
        
        if not self.hwnd and window_title:
            self.hwnd = self._find_window_by_title(window_title)
        
        if not self.hwnd:
            raise ValueError(
                f"Could not find window with title containing: '{window_title}'. "
                f"Use list_windows() to see available windows."
            )
        
        # Get actual window title
        self.actual_title = win32gui.GetWindowText(self.hwnd)
        logger.info(f"Window capture initialized for: {self.actual_title} (HWND: {self.hwnd})")
        if self.crop_region:
            logger.info(f"Crop region set: x={self.crop_region[0]}, y={self.crop_region[1]}, "
                       f"w={self.crop_region[2]}, h={self.crop_region[3]}")

    
    @staticmethod
    def _find_window_by_title(title: str) -> Optional[int]:
        """
        Find window handle by title (partial match, case-insensitive)
        
        Args:
            title: Window title to search for
            
        Returns:
            Window handle (HWND) or None if not found
        """
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                if title.lower() in window_text.lower() and window_text:
                    windows.append((hwnd, window_text))
        
        windows = []
        win32gui.EnumWindows(callback, windows)
        
        if windows:
            # Return the first match
            return windows[0][0]
        return None
    
    @staticmethod
    def list_windows() -> List[Tuple[int, str]]:
        """
        List all visible windows
        
        Returns:
            List of tuples (hwnd, title)
        """
        if not WINDOWS_AVAILABLE:
            return []
        
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                if window_text:  # Only include windows with titles
                    windows.append((hwnd, window_text))
        
        windows = []
        win32gui.EnumWindows(callback, windows)
        return sorted(windows, key=lambda x: x[1])
    
    def capture(self) -> np.ndarray:
        """
        Capture window and return as numpy array
        
        Returns:
            numpy.ndarray: RGB image array (height, width, 3)
        """
        try:
            # Get window coordinates
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
            width = right - left
            height = bottom - top
            
            # Get window device context
            hwndDC = win32gui.GetWindowDC(self.hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            
            # Create bitmap
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)
            
            # Capture window content (works even if window is behind others)
            result = saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)
            
            # Convert to numpy array
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img = img.reshape((height, width, 4))  # BGRA format
            
            # Convert BGRA to RGB
            img = img[:, :, [2, 1, 0]]  # BGR to RGB (drop alpha)
            
            # Apply crop if specified
            if self.crop_region:
                x, y, w, h = self.crop_region
                # Ensure crop is within bounds
                x = max(0, min(x, width - 1))
                y = max(0, min(y, height - 1))
                w = min(w, width - x)
                h = min(h, height - y)
                img = img[y:y+h, x:x+w]
            
            # Cleanup
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwndDC)
            win32gui.DeleteObject(saveBitMap.GetHandle())
            
            return img
            
        except Exception as e:
            logger.error(f"Window capture failed: {e}")
            raise
    
    def capture_to_pil(self) -> Image.Image:
        """
        Capture window and return as PIL Image
        
        Returns:
            PIL.Image: RGB image
        """
        img_array = self.capture()
        return Image.fromarray(img_array)
    
    def is_window_valid(self) -> bool:
        """
        Check if window still exists
        
        Returns:
            bool: True if window is valid
        """
        if not WINDOWS_AVAILABLE:
            return False
        return win32gui.IsWindow(self.hwnd)
    
    def set_crop_region(self, crop_region: Optional[Tuple[int, int, int, int]]):
        """
        Set or update the crop region
        
        Args:
            crop_region: Crop region (x, y, width, height) or None to disable cropping
        """
        self.crop_region = crop_region
        if crop_region:
            logger.info(f"Crop region updated: x={crop_region[0]}, y={crop_region[1]}, "
                       f"w={crop_region[2]}, h={crop_region[3]}")
        else:
            logger.info("Crop region cleared")
    
    def close(self):
        """Close window capture session"""
        logger.info(f"Window capture session closed for: {self.actual_title}")


def list_msfs_windows() -> List[Tuple[int, str]]:
    """
    List windows that might be MSFS-related (convenience function)
    
    Returns:
        List of tuples (hwnd, title)
    """
    all_windows = WindowCapture.list_windows()
    msfs_keywords = ['microsoft flight simulator', 'msfs', 'flight simulator', 'mcdu']
    
    msfs_windows = [
        (hwnd, title) for hwnd, title in all_windows
        if any(keyword in title.lower() for keyword in msfs_keywords)
    ]
    
    return msfs_windows
