"""
MCDU parser for extracting character grid from screen captures.

Uses **EasyOCR** (deep-learning CRNN) as the primary OCR engine for much
better accuracy on the small, coloured MCDU text.  Falls back to Tesseract
or a contour-based heuristic when EasyOCR is not installed.

Colour and font-size are detected per-cell via pixel analysis.
"""

import os
import sys
import time
import numpy as np
import cv2
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR engine priority:  EasyOCR  >  Tesseract  >  contour-only
# ---------------------------------------------------------------------------
_EASYOCR_AVAILABLE = False
_easyocr_reader = None          # singleton, created on first use

try:
    import easyocr as _easyocr_mod
    _EASYOCR_AVAILABLE = True
    logger.info("EasyOCR available — using deep-learning OCR (best accuracy)")
except ImportError:
    logger.info("EasyOCR not installed. Trying Tesseract…")

_TESSERACT_AVAILABLE = False
if not _EASYOCR_AVAILABLE:
    try:
        import pytesseract

        if sys.platform == 'win32':
            _default_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for _p in _default_paths:
                if os.path.isfile(_p):
                    pytesseract.pytesseract.tesseract_cmd = _p
                    break

        pytesseract.get_tesseract_version()
        _TESSERACT_AVAILABLE = True
        logger.info("Tesseract OCR available — using row-based recognition")
    except Exception:
        logger.info(
            "No OCR engine found — using contour-only fallback. "
            "Install EasyOCR (pip install easyocr) or Tesseract for better accuracy."
        )


# ---------------------------------------------------------------------------
# Persistent row-level OCR cache  (survives across MCDUParser instances)
# ---------------------------------------------------------------------------
_prev_row_imgs: dict = {}    # row index → np.ndarray (last row image)
_prev_row_ocr: dict = {}     # row index → OCR result
_ROW_CHANGE_MSE = 5.0        # MSE below this ⇒ row is "unchanged"

# Characters that the Airbus MCDU can actually display
_MCDU_VALID_CHARS = set(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '0123456789'
    ' +-*/.<>[]()/-.:°'
)

# Common OCR misreads → correct MCDU character
_OCR_FIXUPS = {
    'l': '1', '|': '1', '!': '1',
    'o': 'O', '{': '[', '}': ']',
    ',': '.', ';': '.',
    '\\': '/',
    '_': '-', '~': '-',
    '"': ' ', "'": ' ',
    '@': 'A', '#': 'H',
    '$': 'S', '&': '8',
}

# EasyOCR character allowlist
_EASYOCR_ALLOWLIST = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-/<>[]() '


def _get_easyocr_reader():
    """Lazy-initialise the global EasyOCR reader (loads model on first call)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        # Auto-detect GPU (CUDA) — massive speedup on NVIDIA GPUs
        use_gpu = False
        try:
            import torch
            use_gpu = torch.cuda.is_available()
        except Exception:
            pass
        logger.info(
            "Loading EasyOCR model (%s) — first call may take a few seconds…",
            "GPU/CUDA" if use_gpu else "CPU",
        )
        _easyocr_reader = _easyocr_mod.Reader(
            ['en'],
            gpu=use_gpu,
            verbose=False,
        )
        logger.info("EasyOCR model loaded.")
    return _easyocr_reader


class MCDUParser:
    """Parser for MCDU screen captures to extract character grid"""

    # Brightness threshold: pixels brighter than this are considered "ink"
    INK_THRESHOLD = 80
    # Minimum fraction of bright pixels in a cell to consider it non-empty
    MIN_INK_RATIO = 0.008  # ~0.8 %

    def __init__(self, image: np.ndarray, columns: int = 24, rows: int = 14):
        self.columns = columns
        self.rows = rows

        # Resize image to exact multiples of columns × rows so every cell
        # has identical pixel dimensions and the grid doesn't drift.
        target_w = (image.shape[1] // columns) * columns
        target_h = (image.shape[0] // rows) * rows
        if image.shape[1] != target_w or image.shape[0] != target_h:
            image = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.image = image

        self.cell_width = target_w // columns
        self.cell_height = target_h // rows

        # Estimate per-image background floor (5th percentile of max-channel).
        # When MSFS gamma / lighting changes, the whole image baseline shifts
        # (e.g. min goes from 1 → 27).  Subtracting this avoids treating a
        # uniformly-bright background as "ink".
        max_ch = np.max(image, axis=2)
        self._bg_floor = int(np.percentile(max_ch, 5))

        self.cache_enabled = True
        self.character_cache = {}

        logger.debug(
            f"MCDU Parser initialized: {rows}x{columns} grid, "
            f"image resized to {target_w}x{target_h}, "
            f"cell size: {self.cell_width}x{self.cell_height}px"
        )

    # ------------------------------------------------------------------
    #  Cell extraction
    # ------------------------------------------------------------------
    def extract_cell(self, row: int, col: int) -> np.ndarray:
        x = col * self.cell_width
        y = row * self.cell_height
        return self.image[y:y + self.cell_height, x:x + self.cell_width]

    def _extract_row_image(self, row: int) -> np.ndarray:
        """Extract the full pixel strip for one grid row."""
        y = row * self.cell_height
        return self.image[y:y + self.cell_height, :]

    # ------------------------------------------------------------------
    #  Colour detection (per-cell, fast)
    # ------------------------------------------------------------------
    def detect_color(self, cell: np.ndarray) -> str:
        gray = np.max(cell, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        bright_mask = gray > ink_threshold
        if not np.any(bright_mask):
            return "w"

        bright_pixels = cell[bright_mask]
        r, g, b = np.mean(bright_pixels, axis=0).astype(int)

        if r > 180 and g > 180 and b > 180:
            return "w"
        if r < 120 and g > 140 and b > 140:
            return "c"
        if r < 120 and g > 140 and b < 120:
            return "g"
        if r > 160 and g > 120 and b < 100:
            return "a"
        if r > 140 and g < 100 and b > 140:
            return "m"
        if r > 140 and g < 100 and b < 100:
            return "r"
        if r > 180 and g > 180 and b < 150:
            return "y"
        if 60 < r < 160 and 60 < g < 160 and 60 < b < 160:
            return "e"
        return "w"

    # ------------------------------------------------------------------
    #  Empty-cell detection  (adaptive to background brightness)
    # ------------------------------------------------------------------
    def is_empty_cell(self, cell: np.ndarray, threshold: int = 30) -> bool:
        # Subtract the per-image background floor so a raised baseline
        # (e.g. min=27 from MSFS gamma) doesn't make every cell "non-empty".
        avg_brightness = float(np.mean(cell)) - self._bg_floor
        if avg_brightness >= threshold:
            return False
        gray = np.max(cell, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        ink_pixels = np.count_nonzero(gray > ink_threshold)
        ink_ratio = ink_pixels / max(gray.size, 1)
        return ink_ratio < self.MIN_INK_RATIO

    # ------------------------------------------------------------------
    #  Font-size heuristic
    # ------------------------------------------------------------------
    def is_small_font(self, row: int) -> bool:
        return (row % 2 == 1) and (row != 13)

    # ------------------------------------------------------------------
    #  EasyOCR image preprocessing
    # ------------------------------------------------------------------
    def _preprocess_for_easyocr(self, img: np.ndarray, scale: int = 4) -> np.ndarray:
        """
        Prepare an image for EasyOCR.

        MCDU = bright coloured text on a near-black background.
        1. Max-channel grayscale (preserves coloured text brightness).
        2. Binary threshold (eliminates all background noise completely).
        3. Invert → dark text on white background (matches CRAFT/CRNN
           training-data distribution for better detection accuracy).
        4. Upscale 4× with INTER_LINEAR (smooth edges, not blocky).
        5. Light Gaussian blur to recreate the anti-aliased edges the
           CRNN model expects (binary alone is too jagged).
        6. Pad with white border so edge characters aren't clipped.
        """
        gray = np.max(img, axis=2)

        # Binary threshold — cleanly separates text from background
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        _, binary = cv2.threshold(gray, ink_threshold, 255,
                                  cv2.THRESH_BINARY)

        # Invert: CRAFT + CRNN were trained mostly on dark-on-light.
        # Converting to black text on white background improves detection.
        binary = cv2.bitwise_not(binary)

        # Upscale with bilinear interpolation (smoother than NEAREST)
        upscaled = cv2.resize(
            binary,
            (binary.shape[1] * scale, binary.shape[0] * scale),
            interpolation=cv2.INTER_LINEAR,
        )

        # Light blur to soften jagged binary edges → anti-aliased look
        upscaled = cv2.GaussianBlur(upscaled, (3, 3), 0.8)

        # Pad so characters at the very edges aren't cut off
        pad = 16
        padded = cv2.copyMakeBorder(
            upscaled, pad, pad, pad, pad,
            cv2.BORDER_CONSTANT, value=255,  # white border
        )
        return padded

    @staticmethod
    def _fix_ocr_char(ch: str) -> str:
        """Map common EasyOCR misreads to the correct MCDU character."""
        if ch in _OCR_FIXUPS:
            return _OCR_FIXUPS[ch]
        upper = ch.upper()
        if upper in _MCDU_VALID_CHARS:
            return upper
        # Last resort – clamp to closest printable ASCII
        return upper if upper.isprintable() else ' '

    # ------------------------------------------------------------------
    #  Full-image EasyOCR  (one inference call for the entire MCDU)
    # ------------------------------------------------------------------
    def _ocr_full_image_easyocr(self) -> dict:
        """
        Run EasyOCR once on the whole MCDU image.

        Returns ``{row_index: [(char, centre_x), …]}`` — same per-row
        format as ``_ocr_row_easyocr`` so downstream mapping is identical.
        """
        try:
            # Full-image mode uses 3× — a compromise; large-font rows
            # (the usual trouble spot) benefit from the lower scale while
            # small-font rows still have enough resolution.
            scale = 3
            processed = self._preprocess_for_easyocr(self.image, scale)
            pad = 16  # must match _preprocess_for_easyocr

            reader = _get_easyocr_reader()
            results = reader.readtext(
                processed, detail=1, paragraph=False,
                allowlist=_EASYOCR_ALLOWLIST,
                width_ths=0.3,
                text_threshold=0.5,
                low_text=0.3,
            )

            row_results: dict = {}
            for bbox, text, conf in results:
                if conf < 0.20:
                    continue
                # Undo pad + scale
                y_center = (sum(p[1] for p in bbox) / 4 - pad) / scale
                row = int(y_center / self.cell_height)
                row = max(0, min(row, self.rows - 1))

                x_left = (min(p[0] for p in bbox) - pad) / scale
                x_right = (max(p[0] for p in bbox) - pad) / scale
                text = text.strip()
                if not text:
                    continue

                n = len(text)
                char_width = (x_right - x_left) / max(n, 1)
                if row not in row_results:
                    row_results[row] = []
                for i, ch in enumerate(text):
                    cx = x_left + char_width * (i + 0.5)
                    row_results[row].append((self._fix_ocr_char(ch), cx))

            return row_results
        except Exception as e:
            logger.debug(f"EasyOCR full-image failed: {e}")
            return {}

    # ------------------------------------------------------------------
    #  Per-row EasyOCR — returns [(char, centre_x), …]
    # ------------------------------------------------------------------
    def _ocr_row_easyocr(self, row_img: np.ndarray,
                          large_font: bool = False) -> list:
        """
        Run EasyOCR on a single row image.  Returns a list of
        ``(char, centre_x)`` in original pixel coordinates.

        *large_font*: when True (even-numbered rows), use a lower upscale
        factor so thick glyphs don't become blobs that confuse the CRNN.
        """
        try:
            scale = 3 if large_font else 4
            processed = self._preprocess_for_easyocr(row_img, scale)
            pad = 16  # must match _preprocess_for_easyocr

            reader = _get_easyocr_reader()
            results = reader.readtext(
                processed, detail=1, paragraph=False,
                allowlist=_EASYOCR_ALLOWLIST,
                width_ths=0.3,
                text_threshold=0.5,
                low_text=0.3,
            )

            char_positions: list = []
            for (bbox, text, conf) in results:
                if conf < 0.20:
                    continue
                # Undo pad + scale
                x_left = (min(p[0] for p in bbox) - pad) / scale
                x_right = (max(p[0] for p in bbox) - pad) / scale
                text = text.strip()
                if not text:
                    continue
                n = len(text)
                char_width = (x_right - x_left) / max(n, 1)
                for i, ch in enumerate(text):
                    cx = x_left + char_width * (i + 0.5)
                    char_positions.append((self._fix_ocr_char(ch), cx))

            return char_positions
        except Exception as e:
            logger.debug(f"EasyOCR row failed: {e}")
            return []

    # ------------------------------------------------------------------
    #  Per-row Tesseract OCR (fallback)
    # ------------------------------------------------------------------
    def _ocr_row_tesseract(self, row_img: np.ndarray) -> str:
        """
        Run Tesseract on a single row image using --psm 7 (single line).
        Returns the raw OCR string.
        """
        try:
            # Use max-channel so coloured text keeps full brightness.
            gray = np.max(row_img, axis=2)
            ink_threshold = self.INK_THRESHOLD + self._bg_floor
            _, binary = cv2.threshold(gray, ink_threshold, 255,
                                      cv2.THRESH_BINARY)

            scale = 2
            upscaled = cv2.resize(
                binary,
                (binary.shape[1] * scale, binary.shape[0] * scale),
                interpolation=cv2.INTER_NEAREST,
            )

            pad = 10
            padded = cv2.copyMakeBorder(
                upscaled, pad, pad, pad, pad,
                cv2.BORDER_CONSTANT, value=0,
            )

            config = (
                '--psm 7 '
                '-c tessedit_char_whitelist='
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-*/.<>[]() '
            )
            text = pytesseract.image_to_string(padded, config=config).strip()
            return text
        except Exception as e:
            logger.debug(f"Row OCR failed: {e}")
            return ""

    def _map_positions_to_cells(self, char_positions: list) -> List[Optional[str]]:
        """
        Map EasyOCR characters (with x-positions) to the 24-column grid.

        Each character is placed in the column whose centre is nearest
        to the character's centre-x.  When multiple chars land on the
        same column, the one closest to the column centre wins.
        """
        cell_chars: List[Optional[str]] = [None] * self.columns
        cell_dist: List[float] = [float('inf')] * self.columns
        if not char_positions:
            return cell_chars

        half_w = self.cell_width / 2.0
        for char, centre_x in char_positions:
            col = int(centre_x / self.cell_width)
            col = max(0, min(col, self.columns - 1))
            col_centre = col * self.cell_width + half_w
            dist = abs(centre_x - col_centre)
            if dist < cell_dist[col]:
                cell_chars[col] = char  # already fixed by _fix_ocr_char
                cell_dist[col] = dist

        return cell_chars

    def _map_text_to_cells(self, text: str, row: int) -> List[Optional[str]]:
        """
        Map OCR text to the 24-column grid for a given row.

        Uses brightness analysis to find non-empty columns, then aligns
        the OCR characters (with spaces stripped) left-to-right.
        """
        cell_chars: List[Optional[str]] = [None] * self.columns

        # Find which columns in this row are non-empty
        non_empty_cols = []
        for col in range(self.columns):
            cell = self.extract_cell(row, col)
            if not self.is_empty_cell(cell):
                non_empty_cols.append(col)

        if not text or not non_empty_cols:
            return cell_chars

        # Strip spaces — Tesseract inserts them between monospaced chars
        chars = list(text.replace(" ", ""))

        # Align characters to non-empty columns
        for i, col in enumerate(non_empty_cols):
            if i < len(chars):
                c = chars[i]
                cell_chars[col] = c.upper() if c.isalnum() else c
            else:
                cell_chars[col] = " "

        return cell_chars

    # ------------------------------------------------------------------
    #  Single-cell Tesseract (legacy fallback – slow)
    # ------------------------------------------------------------------
    def detect_character(self, cell: np.ndarray) -> Optional[str]:
        """Detect a single cell's character (used only in contour-only mode)."""
        char = self._detect_via_contours(cell)
        if char:
            return char
        return " "

    def _detect_via_contours(self, cell: np.ndarray) -> Optional[str]:
        """Contour fallback for symbols OCR often misses at small sizes:
           < > [ ] / . - ↔ ↑↓
        """
        try:
            gray = np.max(cell, axis=2)
            ink_threshold = self.INK_THRESHOLD + self._bg_floor
            _, binary = cv2.threshold(gray, ink_threshold, 255,
                                      cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(
                binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
            )
            if not contours:
                return None

            x_min = min(cv2.boundingRect(c)[0] for c in contours)
            y_min = min(cv2.boundingRect(c)[1] for c in contours)
            x_max = max(cv2.boundingRect(c)[0] + cv2.boundingRect(c)[2]
                        for c in contours)
            y_max = max(cv2.boundingRect(c)[1] + cv2.boundingRect(c)[3]
                        for c in contours)

            glyph_w = x_max - x_min
            glyph_h = y_max - y_min
            if glyph_w < 2 or glyph_h < 2:
                return None

            aspect = glyph_w / max(glyph_h, 1)
            roi = binary[y_min:y_max, x_min:x_max]
            fill = np.count_nonzero(roi) / max(roi.size, 1)
            h, w = roi.shape
            n_contours = len(contours)

            left_half = np.count_nonzero(roi[:, :w // 2])
            right_half = np.count_nonzero(roi[:, w // 2:])
            top_half = np.count_nonzero(roi[:h // 2, :])
            bot_half = np.count_nonzero(roi[h // 2:, :])

            cell_h, cell_w = cell.shape[:2]

            # --- dot / period ---
            if glyph_w < cell_w * 0.35 and glyph_h < cell_h * 0.35 and fill > 0.40:
                if y_min > cell_h * 0.55:
                    return "."

            # --- dash / minus ---
            # Wide relative to height, horizontal stroke.
            # Slightly relaxed vs. original to catch MCDU "-----" dashes.
            if aspect > 1.8 and glyph_h < cell_h * 0.30 and fill > 0.35:
                return "-"

            # --- small filled square / box  ☐  ---
            # The Airbus MCDU uses small solid box symbols for selectable
            # fields.  They look like compact, roughly-square solid blobs
            # that are shorter than full-height letters.
            # Output "[" which the mobiflight client maps to ☐ (U+2610).
            if (0.6 < aspect < 1.7
                    and fill > 0.55
                    and glyph_h < cell_h * 0.65
                    and glyph_w < cell_w * 0.65
                    and glyph_h > cell_h * 0.15
                    and glyph_w > cell_w * 0.15):
                return "["

            # --- forward slash  /  ---
            if 0.20 < aspect < 0.65 and 0.08 < fill < 0.35 and glyph_h > cell_h * 0.50:
                tl = np.count_nonzero(roi[:h // 2, :w // 2])
                tr = np.count_nonzero(roi[:h // 2, w // 2:])
                bl = np.count_nonzero(roi[h // 2:, :w // 2])
                br = np.count_nonzero(roi[h // 2:, w // 2:])
                if tr > tl and bl > br:
                    return "/"

            # --- square brackets  [ ] ---
            # Tall, with top+bottom horizontal bars and one dominant
            # vertical edge.  Slightly wider aspect tolerance for MCDU.
            if aspect < 0.70 and glyph_h > cell_h * 0.40 and 0.12 < fill < 0.60:
                top_row = roi[:max(1, h // 4), :]
                bot_row = roi[-max(1, h // 4):, :]
                has_top = np.count_nonzero(top_row) > top_row.size * 0.20
                has_bot = np.count_nonzero(bot_row) > bot_row.size * 0.20
                if has_top and has_bot:
                    if left_half > right_half * 1.3:
                        return "["
                    if right_half > left_half * 1.3:
                        return "]"
                    # When ink is symmetric, use glyph position within cell
                    glyph_cx = (x_min + x_max) / 2
                    if glyph_cx < cell_w * 0.40:
                        return "["
                    if glyph_cx > cell_w * 0.60:
                        return "]"

            # --- angle-brackets  < > ---
            if 0.3 < aspect < 0.85 and fill < 0.40:
                if left_half > right_half * 1.4:
                    return "<"
                if right_half > left_half * 1.4:
                    return ">"

            # --- bidirectional arrow  ↔ ---
            if n_contours >= 2 and 0.8 < aspect < 3.0 and fill < 0.40:
                if 0.5 < (left_half / max(right_half, 1)) < 2.0:
                    return "<>"

            # --- up/down arrow  ↑↓ ---
            if n_contours >= 2 and aspect < 0.80 and fill < 0.50:
                if 0.5 < (top_half / max(bot_half, 1)) < 2.0:
                    return "^v"

            return None
        except Exception as e:
            logger.debug(f"Contour detection failed: {e}")
            return None

    # ------------------------------------------------------------------
    #  Main entry point
    # ------------------------------------------------------------------
    def parse_grid(self) -> List:
        """
        Parse entire MCDU grid and extract all cells.

        Returns:
            list: 336 elements, each either [] or [char, color, size]
        """
        t0 = time.perf_counter()
        message_data: List = []

        use_ocr = _EASYOCR_AVAILABLE or _TESSERACT_AVAILABLE
        if not use_ocr:
            # ---- Slow path: contour-only fallback (no OCR engine) ----
            for row in range(self.rows):
                for col in range(self.columns):
                    cell = self.extract_cell(row, col)
                    if self.is_empty_cell(cell):
                        message_data.append([])
                        continue
                    char = self.detect_character(cell)
                    color = self.detect_color(cell)
                    size = 1 if self.is_small_font(row) else 0
                    if char and char.strip():
                        message_data.append([char, color, size])
                    else:
                        message_data.append([" ", color, size])

            elapsed = time.perf_counter() - t0
            logger.debug(f"parse_grid (contours) completed in {elapsed*1000:.0f} ms")
            return message_data

        # ---- Identify which rows have content (cheap brightness check) ----
        row_empty_flags: List[List[bool]] = []
        for row in range(self.rows):
            flags = []
            for col in range(self.columns):
                is_empty = self.is_empty_cell(self.extract_cell(row, col))
                flags.append(is_empty)
            row_empty_flags.append(flags)

        non_empty_rows = []
        row_images = {}
        for row in range(self.rows):
            if not all(row_empty_flags[row]):
                non_empty_rows.append(row)
                row_images[row] = self._extract_row_image(row)

        # ---- Choose OCR engine ----
        if _EASYOCR_AVAILABLE:
            # --- Row-level change detection (skip unchanged rows) ---
            changed_rows = []
            cached_rows: dict = {}
            for row in non_empty_rows:
                rim = row_images[row]
                if row in _prev_row_imgs:
                    prev = _prev_row_imgs[row]
                    if prev.shape == rim.shape:
                        mse = float(np.mean(
                            (rim.astype(np.float32) - prev.astype(np.float32)) ** 2
                        ))
                        if mse < _ROW_CHANGE_MSE:
                            cached_rows[row] = _prev_row_ocr[row]
                            continue
                changed_rows.append(row)

            ocr_results: dict = dict(cached_rows)

            if not changed_rows:
                pass  # everything cached
            elif len(changed_rows) >= 8:
                # Many rows changed — single full-image OCR (1 inference
                # call instead of N separate ones).
                full = self._ocr_full_image_easyocr()
                for row in changed_rows:
                    result = full.get(row, [])
                    ocr_results[row] = result
                    _prev_row_imgs[row] = row_images[row].copy()
                    _prev_row_ocr[row] = result
            else:
                # Few rows changed — per-row OCR
                for row in changed_rows:
                    is_large = not self.is_small_font(row)
                    result = self._ocr_row_easyocr(row_images[row],
                                                   large_font=is_large)
                    ocr_results[row] = result
                    _prev_row_imgs[row] = row_images[row].copy()
                    _prev_row_ocr[row] = result

            n_cached = len(cached_rows)
            n_ocr = len(changed_rows)
            if n_cached or n_ocr:
                logger.debug(
                    f"EasyOCR: {n_ocr} rows OCR'd, {n_cached} cached"
                )
        else:
            # Tesseract: thread-pool (each call is an independent process)
            ocr_results = {}
            with ThreadPoolExecutor(max_workers=min(len(non_empty_rows) or 1, 8)) as pool:
                futures = {
                    row: pool.submit(self._ocr_row_tesseract, row_images[row])
                    for row in non_empty_rows
                }
                for row, fut in futures.items():
                    ocr_results[row] = fut.result()

        # ---- Assemble output ----
        for row in range(self.rows):
            if row not in ocr_results:
                message_data.extend([[]] * self.columns)
                continue

            # EasyOCR returns [(char, cx), …] → position-based mapping
            # Tesseract returns str → text-based mapping
            raw = ocr_results[row]
            if isinstance(raw, list):
                cell_chars = self._map_positions_to_cells(raw)
            else:
                cell_chars = self._map_text_to_cells(raw, row)

            for col in range(self.columns):
                if row_empty_flags[row][col]:
                    message_data.append([])
                    continue

                cell_img = self.extract_cell(row, col)
                char = cell_chars[col]

                # Contour fallback when OCR missed the cell
                if not char or char == " ":
                    contour_char = self._detect_via_contours(cell_img)
                    if contour_char:
                        char = contour_char
                    else:
                        char = " "

                color = self.detect_color(cell_img)
                size = 1 if self.is_small_font(row) else 0
                message_data.append([char, color, size])

        elapsed = time.perf_counter() - t0
        logger.debug(f"parse_grid completed in {elapsed*1000:.0f} ms")
        return message_data
