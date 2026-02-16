"""
Window-specific capture module for capturing windows even when minimized or behind other windows.
Includes automatic fallback to mss screen capture for hardware-accelerated (DirectX/OpenGL) windows.
"""

import logging
import numpy as np
from PIL import Image
from typing import List, Tuple, Optional
import sys
import ctypes
import ctypes.wintypes

# ---------- DPI awareness (must run before any GUI / coordinate calls) --------
# Without this, GetWindowRect returns DPI-scaled (logical) coords on Win10/11,
# while mss captures in physical pixels.  The mismatch grows as the window moves
# away from (0, 0), causing a blank / wrong capture region.
if sys.platform == 'win32':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-Monitor V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # fallback
        except Exception:
            pass

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

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

        # MSS fallback state (initialised lazily on first capture)
        self._use_mss: Optional[bool] = None          # None = not yet probed
        self._mss_instance: Optional["mss.mss"] = None  # persistent instance
        self._frame_count: int = 0
        self._prev_hash: Optional[int] = None          # for change-detection debug
        
        if not self.hwnd and window_title:
            self.hwnd = self._find_window_by_title(window_title)
        
        if not self.hwnd:
            raise ValueError(
                f"Could not find window with title containing: '{window_title}'. "
                f"Use list_windows() to see available windows."
            )
        
        # Get actual window title
        self.actual_title = win32gui.GetWindowText(self.hwnd)
        self._was_topmost = False  # track whether we set TOPMOST
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
    
    @staticmethod
    def _is_mostly_black(img: np.ndarray, threshold: float = 5.0) -> bool:
        """
        Check if an image is mostly black (average brightness below threshold).
        Hardware-accelerated windows (DirectX/OpenGL) often return all-black
        frames when captured via BitBlt/PrintWindow.

        Args:
            img: RGB image as numpy array
            threshold: Average brightness threshold (0-255)

        Returns:
            True if the image is mostly black
        """
        return float(np.mean(img)) < threshold

    def _get_mss(self):
        """Return a persistent mss instance, creating one if needed."""
        if self._mss_instance is None:
            self._mss_instance = mss.mss()
            logger.info("Created persistent mss screen-capture instance")
        return self._mss_instance

    def _get_window_rect(self) -> Tuple[int, int, int, int]:
        """Return the *visual* bounds of the window (left, top, right, bottom).

        On Windows 10/11 ``GetWindowRect`` includes the invisible DWM shadow
        border (~7 px each side).  ``DwmGetWindowAttribute`` with
        ``DWMWA_EXTENDED_FRAME_BOUNDS`` returns the real visible rectangle
        so the mss capture is pixel-accurate.
        """
        try:
            rect = ctypes.wintypes.RECT()
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                ctypes.wintypes.HWND(self.hwnd),
                ctypes.wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return win32gui.GetWindowRect(self.hwnd)

    def _capture_via_mss(self) -> np.ndarray:
        """
        Capture the window's screen region using mss (Desktop Duplication API).
        This works for hardware-accelerated / DirectX / OpenGL windows as long
        as the window is visible on screen.

        Uses a persistent mss instance so the Desktop Duplication API session
        stays alive between frames, preventing stale/cached captures.

        Returns:
            numpy.ndarray: RGB image array (height, width, 3)
        """
        left, top, right, bottom = self._get_window_rect()
        monitor = {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }
        sct = self._get_mss()
        screenshot = sct.grab(monitor)
        img = np.array(screenshot)[:, :, :3]  # drop alpha; result is BGR
        # mss returns BGRA on Windows, first 3 channels are B, G, R
        img = img[:, :, [2, 1, 0]]  # convert BGR to RGB
        return img

    def capture(self) -> np.ndarray:
        """
        Capture window and return as numpy array.

        Strategy:
        1. If mss is available, prefer it (works for DX/OpenGL and gives
           live frames via the Desktop Duplication API).
        2. Fall back to GDI (PrintWindow/BitBlt) when mss is unavailable
           or returns a blank frame.
        3. Cache which path works so subsequent frames skip the probe.

        Returns:
            numpy.ndarray: RGB image array (height, width, 3)
        """
        self._frame_count += 1
        try:
            # Get window coordinates (needed for both paths and crop)
            left, top, right, bottom = self._get_window_rect()
            width = right - left
            height = bottom - top

            # ----- Fast path: backend already chosen -----
            if self._use_mss is True:
                img = self._capture_via_mss()
            elif self._use_mss is False:
                img = self._capture_via_gdi(width, height)
            else:
                # ----- First-frame probe: try mss first, then GDI -----
                if MSS_AVAILABLE:
                    img = self._capture_via_mss()
                    if self._is_mostly_black(img):
                        logger.info(
                            "mss returned a black frame — falling back to "
                            "GDI (PrintWindow/BitBlt) capture."
                        )
                        img = self._capture_via_gdi(width, height)
                        self._use_mss = False
                    else:
                        self._use_mss = True
                        logger.info("Using mss (Desktop Duplication) for live capture.")
                else:
                    img = self._capture_via_gdi(width, height)
                    self._use_mss = False
                    logger.info("mss not available — using GDI capture.")

            # Apply crop if specified
            if self.crop_region:
                img = self._apply_crop(img, width, height)

            self._log_frame_change(img)
            return img

        except Exception as e:
            logger.error(f"Window capture failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _capture_via_gdi(self, width: int, height: int) -> np.ndarray:
        """Capture via PrintWindow / BitBlt (GDI). Returns RGB ndarray."""
        hwndDC = win32gui.GetWindowDC(self.hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()

        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        # Try PrintWindow first (better for minimized/offscreen windows)
        pw_flags = getattr(win32con, 'PW_RENDERFULLCONTENT', 2)
        try:
            res = win32gui.PrintWindow(self.hwnd, saveDC.GetSafeHdc(), pw_flags)
        except Exception:
            res = 0

        if not res:
            saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)

        bmpstr = saveBitMap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype=np.uint8).copy()  # .copy() owns the data
        img = img.reshape((height, width, 4))  # BGRA
        img = img[:, :, [2, 1, 0]]  # BGR → RGB (drop alpha)

        # Cleanup GDI resources
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, hwndDC)
        win32gui.DeleteObject(saveBitMap.GetHandle())

        return img

    def _log_frame_change(self, img: np.ndarray):
        """Log a debug message whenever the captured frame content changes."""
        h = hash(img.tobytes()[:4096])  # hash a prefix for speed
        if self._prev_hash is not None and h != self._prev_hash:
            logger.debug(f"Frame #{self._frame_count}: content CHANGED")
        elif self._prev_hash is not None and h == self._prev_hash:
            if self._frame_count % 30 == 0:
                logger.debug(f"Frame #{self._frame_count}: content unchanged")
        self._prev_hash = h

    def _apply_crop(self, img: np.ndarray, window_width: int, window_height: int) -> np.ndarray:
        """Apply the stored crop_region to an image, clamping to bounds."""
        x, y, w, h = self.crop_region

        if x >= window_width or y >= window_height:
            logger.warning(
                f"Crop region ({x}, {y}, {w}, {h}) is outside window bounds "
                f"({window_width}x{window_height}). Skipping crop."
            )
            return img

        if x + w > window_width or y + h > window_height:
            original_w, original_h = w, h
            x = max(0, min(x, window_width - 1))
            y = max(0, min(y, window_height - 1))
            w = min(w, window_width - x)
            h = min(h, window_height - y)

            if w < original_w * 0.5 or h < original_h * 0.5:
                logger.warning(
                    f"Crop region ({self.crop_region[0]}, {self.crop_region[1]}, "
                    f"{self.crop_region[2]}, {self.crop_region[3]}) significantly exceeds "
                    f"window bounds ({window_width}x{window_height}). "
                    f"Adjusted to ({x}, {y}, {w}, {h})."
                )

        return img[y:y+h, x:x+w]
    
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
    
    def pin_on_top(self, enable: bool = True):
        """Set or remove the 'always on top' flag for the captured window.

        mss captures whatever is drawn at the screen coordinates, so the
        target window must be visible.  Pinning it on top lets the user
        interact with other applications while the small instrument window
        stays visible.
        """
        try:
            flag = win32con.HWND_TOPMOST if enable else win32con.HWND_NOTOPMOST
            win32gui.SetWindowPos(
                self.hwnd, flag, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
            self._was_topmost = enable
            logger.info(f"Window '{self.actual_title}' pinned on top: {enable}")
        except Exception as e:
            logger.warning(f"Failed to set window topmost flag: {e}")

    def close(self):
        """Close window capture session and release resources."""
        # Remove TOPMOST so the window goes back to normal
        if self._was_topmost:
            self.pin_on_top(False)
        if self._mss_instance is not None:
            try:
                self._mss_instance.close()
            except Exception:
                pass
            self._mss_instance = None
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
