"""
Window-specific capture module.

Capture priority:
1. Windows Graphics Capture (WGC) — works in the background for
   DirectX / hardware-accelerated windows (Windows 10 1903+).
2. GDI (PrintWindow / BitBlt) — works in the background for most
    non-hardware-accelerated windows.
3. mss (Desktop Duplication API) — last resort; requires the
   target window to be visible on screen.
"""

import logging
import numpy as np
import threading
from PIL import Image
from typing import List, Tuple, Optional
import sys
import ctypes
import ctypes.wintypes

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    from windows_capture import WindowsCapture, CaptureControl
    WGC_AVAILABLE = True
except ImportError:
    WGC_AVAILABLE = False

logger = logging.getLogger(__name__)

if sys.platform == 'win32' and not WGC_AVAILABLE:
    logger.warning(
        "windows-capture is not installed. MSFS renders with DirectX, so GDI "
        "capture usually returns a black frame and the only fallback left is "
        "mss, which reads screen pixels -- meaning the MCDU window must stay "
        "visible and uncovered. Install it with: pip install windows-capture"
    )

# Platform-specific imports
if sys.platform == 'win32':
    try:
        import win32gui
        import win32ui
        import win32con
        WINDOWS_AVAILABLE = True
    except ImportError:
        logger.warning("pywin32 not available. Window capture will not work. Install with: pip install pywin32")
        WINDOWS_AVAILABLE = False
else:
    WINDOWS_AVAILABLE = False


class WindowCapture:
    """Captures one window, choosing a backend that suits it.

    Measured behaviour of the three backends:

    ==========  ===================  =========  ==========
    backend     needs to be on top?  occluded   minimised
    ==========  ===================  =========  ==========
    GDI         no                   works      black
    WGC         no                   works      works
    mss         yes                  captures   black
                                     whatever
                                     is on top
    ==========  ===================  =========  ==========

    So the window never needs pinning on GDI or WGC.  Only the mss fallback
    reads screen pixels and therefore captures whatever covers the window --
    and mss is only reached when the other two fail, which for a DirectX
    window like an MSFS pop-out means when windows-capture is not installed.
    """

    #: Black frames tolerated before trying the next backend.
    BLACK_FRAMES_BEFORE_REPROBE = 10
    
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

        # Backend selection: None = not yet probed, 'gdi' / 'wgc' / 'mss'
        self._backend: Optional[str] = None

        # MSS fallback state (initialised lazily on first capture)
        self._mss_instance: Optional["mss.mss"] = None  # persistent instance
        self._frame_count: int = 0
        self._prev_hash: Optional[int] = None          # for change-detection debug
        self._consecutive_black: int = 0               # re-probe counter

        # WGC state (initialised lazily when needed)
        self._wgc_capture = None
        self._wgc_control: Optional["CaptureControl"] = None
        self._wgc_frame: Optional[np.ndarray] = None   # latest RGB frame
        self._wgc_lock = threading.Lock()
        self._wgc_ready = threading.Event()
        self._wgc_closed = False
        
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
    
    @staticmethod
    def _is_mostly_black(img: np.ndarray, max_threshold: int = 100,
                         avg_threshold: float = 3.0) -> bool:
        """
        Check if an image is essentially empty (all pixels very dark).

        A truly blank capture (e.g. GDI failing on a DirectX window) will
        have every pixel near zero.  An MCDU screen is dark overall but
        contains bright text, so ``np.max`` will be well above the threshold
        and the average brightness will be noticeably above zero.

        We check **both** conditions:
        * If the *brightest* pixel is below ``max_threshold`` the image
          is almost certainly a failed capture (window chrome / borders
          can produce stray pixels up to ~80 even when the content is
          completely black).
        * If the *average* brightness is below ``avg_threshold`` the
          image is too dark to contain any useful MCDU text.

        Args:
            img: RGB image as numpy array
            max_threshold: If the brightest pixel is below this value the
                frame is considered empty.
            avg_threshold: If the mean pixel value is below this the frame
                is considered empty.

        Returns:
            True if the image appears to be an empty / failed capture.
        """
        return int(np.max(img)) < max_threshold or float(np.mean(img)) < avg_threshold

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

    # ------------------------------------------------------------------
    # WGC (Windows Graphics Capture) backend
    # ------------------------------------------------------------------

    def _start_wgc(self) -> bool:
        """Start a WGC background capture session for ``self.actual_title``.

        Returns True if the session started successfully, False otherwise.
        """
        if not WGC_AVAILABLE:
            return False

        try:
            # Prefer the handle: two MSFS pop-outs can share a title, and
            # matching by name would attach the co-pilot capture to the
            # captain's window.  Older windows-capture releases only accept
            # a name, so fall back to that.
            try:
                cap = WindowsCapture(
                    cursor_capture=False,
                    draw_border=False,
                    window_hwnd=self.hwnd,
                )
            except TypeError:
                logger.debug(
                    "windows-capture does not accept window_hwnd; "
                    "falling back to matching by title."
                )
                cap = WindowsCapture(
                    cursor_capture=False,
                    draw_border=False,
                    window_name=self.actual_title,
                )

            owner = self  # prevent closure over 'self' name collision

            @cap.event
            def on_frame_arrived(frame, capture_control):
                # frame.frame_buffer is BGRA (H, W, 4).
                # Convert BGRA → RGB and copy so the native buffer can be reused.
                rgb = frame.frame_buffer[:, :, [2, 1, 0]].copy()
                with owner._wgc_lock:
                    owner._wgc_frame = rgb
                owner._wgc_ready.set()

            @cap.event
            def on_closed():
                owner._wgc_closed = True
                owner._wgc_ready.set()   # unblock any waiter
                logger.info("WGC capture session closed by the system.")

            self._wgc_control = cap.start_free_threaded()
            self._wgc_capture = cap
            logger.info(
                "WGC capture started for '%s'", self.actual_title
            )
            return True
        except Exception as e:
            logger.warning("Failed to start WGC capture: %s", e)
            self._wgc_capture = None
            self._wgc_control = None
            return False

    def _capture_via_wgc(self) -> Optional[np.ndarray]:
        """Capture via Windows Graphics Capture API.

        Returns an RGB ndarray, or ``None`` if WGC is unavailable / failed.
        """
        # Lazy-init
        if self._wgc_capture is None and not self._wgc_closed:
            if not self._start_wgc():
                return None

        # Wait for the first frame (or a very short timeout on subsequent)
        timeout = 2.0 if self._frame_count <= 1 else 0.1
        if not self._wgc_ready.wait(timeout=timeout):
            logger.debug("WGC: no frame within %.1fs", timeout)
            return None

        if self._wgc_closed:
            return None

        with self._wgc_lock:
            return self._wgc_frame.copy() if self._wgc_frame is not None else None

    def _stop_wgc(self):
        """Stop the WGC capture session and free resources."""
        if self._wgc_control is not None:
            try:
                self._wgc_control.stop()
            except Exception:
                pass
            self._wgc_control = None
        self._wgc_capture = None
        self._wgc_frame = None
        self._wgc_ready.clear()
        self._wgc_closed = False

    def capture(self) -> np.ndarray:
        """
        Capture window and return as numpy array.

        Strategy (probed on first frame, cached afterwards):
        1. WGC (Windows Graphics Capture) — background-capable for DX windows.
        2. GDI (PrintWindow) — background-capable for non-DX windows.
        3. mss (Desktop Duplication) — last resort, window must be visible.

        Returns:
            numpy.ndarray: RGB image array (height, width, 3)
        """
        self._frame_count += 1
        try:
            # Get window coordinates (needed for GDI/mss and crop)
            left, top, right, bottom = self._get_window_rect()
            width = right - left
            height = bottom - top

            # ----- Fast path: backend already chosen -----
            if self._backend == 'gdi':
                img = self._capture_via_gdi(width, height)
            elif self._backend == 'wgc':
                img = self._capture_via_wgc()
                if img is None:
                    # WGC session died — fall back to mss
                    logger.warning("WGC session lost — falling back to mss.")
                    self._backend = 'mss'
                    img = self._capture_via_mss()
            elif self._backend == 'mss':
                img = self._capture_via_mss()
            else:
                # ----- First-frame probe: WGC → GDI → mss -----
                img = self._capture_via_wgc()
                if img is not None and not self._is_mostly_black(img):
                    self._backend = 'wgc'
                    logger.info(
                        "Using WGC capture — window does "
                        "NOT need to stay on top."
                    )
                else:
                    logger.info(
                        "WGC unavailable or returned an empty frame — "
                        "trying GDI (PrintWindow)."
                    )
                    img = self._capture_via_gdi(width, height)
                    if not self._is_mostly_black(img):
                        self._backend = 'gdi'
                        logger.info(
                            "Using GDI (PrintWindow) capture — window does "
                            "NOT need to stay on top."
                        )
                    elif MSS_AVAILABLE:
                        logger.info(
                            "GDI (PrintWindow) returned an empty frame — "
                            "falling back to mss (Desktop Duplication). "
                            "The window must stay visible on screen."
                        )
                        img = self._capture_via_mss()
                        self._backend = 'mss'
                    else:
                        logger.warning(
                            "Neither GDI nor mss available — stuck with "
                            "WGC which returned an empty frame."
                        )
                        self._backend = 'gdi'

            # ---- Re-probe: if frames keep coming back black, try next ----
            if self._is_mostly_black(img):
                self._consecutive_black += 1
                if (self._consecutive_black
                        == self.BLACK_FRAMES_BEFORE_REPROBE
                        and not self.is_window_valid()):
                    # No backend can capture a window that no longer
                    # exists, so say so instead of cycling through all
                    # three and blaming the last one.
                    logger.error(
                        "The window '%s' has been closed. Stop the scraper, "
                        "re-open the pop-out and pick it again.",
                        self.actual_title,
                    )
                # Retry periodically rather than only on the tenth frame: if
                # the one attempt at switching also came back black, an
                # equality test would never fire again and the capture stayed
                # dead for the rest of the session.
                if (self._consecutive_black >= self.BLACK_FRAMES_BEFORE_REPROBE
                        and self._consecutive_black
                        % self.BLACK_FRAMES_BEFORE_REPROBE == 0):
                    if self._backend == 'gdi':
                        # Try WGC
                        wgc_img = self._capture_via_wgc()
                        if wgc_img is not None and not self._is_mostly_black(wgc_img):
                            logger.warning(
                                "10 black frames via GDI — switching to WGC."
                            )
                            self._backend = 'wgc'
                            img = wgc_img
                            self._consecutive_black = 0
                        elif MSS_AVAILABLE:
                            logger.warning(
                                "10 black frames via GDI — switching to mss. "
                                "The window must stay visible on screen."
                            )
                            self._backend = 'mss'
                            img = self._capture_via_mss()
                            self._consecutive_black = 0
                    elif self._backend == 'wgc' and MSS_AVAILABLE:
                        logger.warning(
                            "10 black frames via WGC — switching to mss. "
                            "The window must stay visible on screen."
                        )
                        self._stop_wgc()
                        self._backend = 'mss'
                        img = self._capture_via_mss()
                        self._consecutive_black = 0
                    elif self._backend == 'mss':
                        logger.warning(
                            "10 consecutive near-black frames via mss. "
                            "Try running MSFS in Windowed or Borderless "
                            "mode, or move the MSFS window so it is fully "
                            "visible on screen."
                        )
            else:
                self._consecutive_black = 0

            # Apply crop if specified.  Validate against the frame we
            # actually got: a WGC buffer is not always the same size as the
            # window rectangle, so checking the crop against the rect could
            # clamp a perfectly good region or let a bad one through.
            if self.crop_region:
                img = self._apply_crop(img, img.shape[1], img.shape[0])

            self._log_frame_change(img)
            return img

        except Exception as e:
            logger.error(f"Window capture failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _capture_via_gdi(self, width: int, height: int) -> np.ndarray:
        """Capture via PrintWindow / BitBlt (GDI). Returns RGB ndarray.

        Every handle is released in a finally block.  GDI objects are a
        per-process resource with a hard limit, and this runs up to 30 times
        a second: a capture that threw part-way through - a minimised window
        reporting a zero-sized rectangle is enough - used to leak four of
        them per frame, and the process would eventually be unable to draw
        anything at all.
        """
        if width <= 0 or height <= 0:
            raise ValueError(
                f"window reports a {width}x{height} rectangle; "
                f"it is probably minimised"
            )

        hwndDC = mfcDC = saveDC = saveBitMap = None
        try:
            hwndDC = win32gui.GetWindowDC(self.hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)

            # PrintWindow first: it works on an occluded window, BitBlt
            # copies whatever is on screen in front of it.
            pw_flags = getattr(win32con, 'PW_RENDERFULLCONTENT', 2)
            try:
                res = win32gui.PrintWindow(self.hwnd, saveDC.GetSafeHdc(),
                                           pw_flags)
            except Exception:
                res = 0

            if not res:
                saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0),
                              win32con.SRCCOPY)

            bmpstr = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).copy()  # own the data
            img = img.reshape((height, width, 4))               # BGRA
            return img[:, :, [2, 1, 0]]                         # BGR -> RGB
        finally:
            if saveBitMap is not None:
                try:
                    win32gui.DeleteObject(saveBitMap.GetHandle())
                except Exception:
                    pass
            if saveDC is not None:
                try:
                    saveDC.DeleteDC()
                except Exception:
                    pass
            if mfcDC is not None:
                try:
                    mfcDC.DeleteDC()
                except Exception:
                    pass
            if hwndDC is not None:
                try:
                    win32gui.ReleaseDC(self.hwnd, hwndDC)
                except Exception:
                    pass

    def _log_frame_change(self, img: np.ndarray):
        """Log a debug message whenever the captured frame content changes.

        Costs nothing unless debug logging is on.  It used to hash
        ``img.tobytes()[:4096]``, which serialises the *whole* frame before
        throwing all but four kilobytes of it away - about a megabyte of
        copying per frame, thirty times a second, to produce a message
        nobody was listening to.
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        h = hash(img[:4].tobytes())     # a few rows is enough to spot a change
        if self._prev_hash is not None:
            if h != self._prev_hash:
                logger.debug("Frame #%d: content CHANGED", self._frame_count)
            elif self._frame_count % 30 == 0:
                logger.debug("Frame #%d: content unchanged", self._frame_count)
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
    
    def close(self):
        """Close window capture session and release resources."""
        # Stop WGC session
        self._stop_wgc()
        if self._mss_instance is not None:
            try:
                self._mss_instance.close()
            except Exception:
                pass
            self._mss_instance = None
        logger.info(f"Window capture session closed for: {self.actual_title}")
