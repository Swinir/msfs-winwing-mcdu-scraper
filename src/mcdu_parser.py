"""
MCDU parser for extracting the 24×14 character grid from screen captures.

Recognition strategy (fastest → slowest):
  1. **Template matching** — hash lookup + NCC correlation against learned
     glyph templates.  Works on CPU, ~0.5 ms per frame once warmed up.
  2. **EasyOCR** — deep-learning CRNN, used to bootstrap templates on first
     run and as a fallback for unrecognised cells.
  3. **Contour analysis** — rule-based heuristic for symbols that OCR
     engines commonly misread (brackets, dots, dashes, arrows …).

GPU support (for EasyOCR bootstrap):
  • NVIDIA  — CUDA  (auto-detected via PyTorch)
  • AMD     — ROCm on Linux, DirectML on Windows (torch-directml)
  • Apple   — MPS on macOS
  • CPU     — always available; template matching needs no GPU at all.

Colour and font-size are detected per-cell via fast pixel analysis.
"""

from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  EasyOCR availability
# ---------------------------------------------------------------------------
_EASYOCR_AVAILABLE = False
_easyocr_reader = None  # singleton, created lazily

try:
    import easyocr as _easyocr_mod
    _EASYOCR_AVAILABLE = True
except ImportError:
    logger.info(
        "EasyOCR not installed — template matching + contour fallback only.  "
        "Install with: pip install easyocr"
    )

# ---------------------------------------------------------------------------
#  MCDU character set & OCR fix-up tables
# ---------------------------------------------------------------------------
_MCDU_VALID_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " +-*/.<>[]()/-.:°"
)

_OCR_FIXUPS: Dict[str, str] = {
    "l": "1", "|": "1", "!": "1",
    "o": "O", "{": "[", "}": "]",
    ",": ".", ";": ".",
    "\\": "/",
    "_": "-", "~": "-",
    "\"": " ", "'": " ",
    "@": "A", "#": "H",
    "$": "S", "&": "8",
}

_EASYOCR_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-/<>[]() "

# ---------------------------------------------------------------------------
#  Row-level OCR cache  (persists across MCDUParser instances)
# ---------------------------------------------------------------------------
_prev_row_imgs: Dict[int, np.ndarray] = {}
_prev_row_ocr: Dict[int, list] = {}
_ROW_CHANGE_MSE = 5.0


# ═══════════════════════════════════════════════════════════════════════════
#  Template Matcher
# ═══════════════════════════════════════════════════════════════════════════

class TemplateMatcher:
    """
    Template-based character recognition for MCDU fixed-font displays.

    Learns character patterns from confirmed OCR/contour results and then
    uses hash + normalised cross-correlation matching for instant
    recognition on subsequent frames.  CPU-only — no GPU required.
    """

    NORM_SIZE = (20, 28)       # (width, height) of normalised glyph
    MATCH_THRESHOLD = 0.78     # min NCC score to accept
    MAX_TEMPLATES = 5          # max variants stored per character

    def __init__(self) -> None:
        self._hash_cache: Dict[bytes, str] = {}
        self._templates: Dict[str, List[np.ndarray]] = {}
        self._dirty = False
        self._template_path = (
            Path(__file__).resolve().parent.parent / "templates" / "mcdu_templates.npz"
        )
        self._load()

    # ----- recognition ---------------------------------------------------

    def recognize(self, cell_binary: np.ndarray) -> Optional[Tuple[str, float]]:
        """Return ``(char, confidence)`` or ``None``."""
        glyph = self._extract_glyph(cell_binary)
        if glyph is None:
            return None

        norm = self._normalize(glyph)
        key = norm.tobytes()

        # Fast: exact hash
        if key in self._hash_cache:
            return (self._hash_cache[key], 1.0)

        # Slower: NCC against all templates
        best_char: Optional[str] = None
        best_score = 0.0
        for char, templates in self._templates.items():
            for tmpl in templates:
                score = self._ncc(norm, tmpl)
                if score > best_score:
                    best_score = score
                    best_char = char

        if best_score >= self.MATCH_THRESHOLD and best_char is not None:
            self._hash_cache[key] = best_char
            return (best_char, best_score)

        return None

    # ----- learning ------------------------------------------------------

    def learn(self, char: str, cell_binary: np.ndarray,
              confidence: float = 1.0) -> None:
        """Record a confirmed character template."""
        if confidence < 0.45 or not char or not char.strip():
            return
        char = char.upper()

        glyph = self._extract_glyph(cell_binary)
        if glyph is None:
            return

        norm = self._normalize(glyph)
        self._hash_cache[norm.tobytes()] = char

        if char not in self._templates:
            self._templates[char] = []

        # skip near-duplicates
        for existing in self._templates[char]:
            if self._ncc(norm, existing) > 0.95:
                return

        if len(self._templates[char]) >= self.MAX_TEMPLATES:
            return

        self._templates[char].append(norm)
        self._dirty = True
        logger.debug(
            "Learned '%s' (%d variants, %d total templates)",
            char, len(self._templates[char]), self.template_count,
        )

    # ----- persistence ---------------------------------------------------

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self._template_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for char, templates in self._templates.items():
                for i, tmpl in enumerate(templates):
                    data[f"c{ord(char):04x}_{i}"] = tmpl
            np.savez_compressed(str(self._template_path), **data)
            self._dirty = False
            logger.info(
                "Saved %d templates for %d characters → %s",
                self.template_count, len(self._templates), self._template_path,
            )
        except Exception as exc:
            logger.warning("Failed to save templates: %s", exc)

    def _load(self) -> None:
        if not self._template_path.exists():
            return
        try:
            data = np.load(str(self._template_path))
            for key in data.files:
                char = chr(int(key.split("_")[0][1:], 16))
                if char not in self._templates:
                    self._templates[char] = []
                self._templates[char].append(data[key])
            logger.info(
                "Loaded %d templates for %d characters",
                self.template_count, len(self._templates),
            )
        except Exception as exc:
            logger.warning("Failed to load templates: %s", exc)

    # ----- helpers -------------------------------------------------------

    def _normalize(self, glyph: np.ndarray) -> np.ndarray:
        resized = cv2.resize(glyph, self.NORM_SIZE, interpolation=cv2.INTER_AREA)
        _, binary = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)
        return binary

    @staticmethod
    def _extract_glyph(binary: np.ndarray) -> Optional[np.ndarray]:
        coords = cv2.findNonZero(binary)
        if coords is None:
            return None
        x, y, w, h = cv2.boundingRect(coords)
        if w < 2 or h < 2:
            return None
        return binary[y : y + h, x : x + w]

    @staticmethod
    def _ncc(a: np.ndarray, b: np.ndarray) -> float:
        """Normalised cross-correlation (same-size images)."""
        if a.shape != b.shape:
            return 0.0
        af = a.ravel().astype(np.float32)
        bf = b.ravel().astype(np.float32)
        am, bm = af.mean(), bf.mean()
        astd, bstd = af.std(), bf.std()
        if astd < 1e-6 or bstd < 1e-6:
            return 1.0 if (astd < 1e-6 and bstd < 1e-6) else 0.0
        return float(np.dot(af - am, bf - bm) / (len(af) * astd * bstd))

    @property
    def template_count(self) -> int:
        return sum(len(v) for v in self._templates.values())


# Singleton
_template_matcher: Optional[TemplateMatcher] = None


def _get_template_matcher() -> TemplateMatcher:
    global _template_matcher
    if _template_matcher is None:
        _template_matcher = TemplateMatcher()
    return _template_matcher


# ═══════════════════════════════════════════════════════════════════════════
#  EasyOCR reader with multi-GPU support
# ═══════════════════════════════════════════════════════════════════════════

def _get_easyocr_reader():
    """Lazy-init the EasyOCR reader, probing for the best available GPU."""
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader

    use_gpu = False
    gpu_info = "CPU"

    try:
        import torch

        if torch.cuda.is_available():
            use_gpu = True
            try:
                gpu_info = f"CUDA — {torch.cuda.get_device_name(0)}"
            except Exception:
                gpu_info = "CUDA"
        elif hasattr(torch, "hip") and hasattr(torch.hip, "is_available") and torch.hip.is_available():
            use_gpu = True
            gpu_info = "ROCm (AMD)"
        elif (hasattr(torch, "backends")
              and hasattr(torch.backends, "mps")
              and torch.backends.mps.is_available()):
            use_gpu = True
            gpu_info = "MPS (Apple Silicon)"
    except ImportError:
        logger.debug("PyTorch not installed — GPU unavailable for EasyOCR")
    except Exception as exc:
        logger.debug("GPU probe error: %s", exc)

    # DirectML fallback for AMD / Intel on Windows
    if not use_gpu:
        try:
            import torch_directml  # noqa: F401
            # EasyOCR can't use DirectML directly, but log that it's present
            gpu_info = "CPU (torch-directml found but not usable by EasyOCR)"
        except ImportError:
            pass

    logger.info("Initialising EasyOCR — %s …", gpu_info)
    _easyocr_reader = _easyocr_mod.Reader(
        ["en"], gpu=use_gpu, verbose=False,
    )
    logger.info("EasyOCR ready (%s)", gpu_info)
    return _easyocr_reader


# ═══════════════════════════════════════════════════════════════════════════
#  MCDUParser
# ═══════════════════════════════════════════════════════════════════════════

class MCDUParser:
    """Parse an MCDU screen capture into a 24×14 character grid."""

    INK_THRESHOLD = 80
    MIN_INK_RATIO = 0.008

    def __init__(self, image: np.ndarray,
                 columns: int = 24, rows: int = 14) -> None:
        self.columns = columns
        self.rows = rows

        # Snap to exact multiples so every cell has identical pixel size
        target_w = (image.shape[1] // columns) * columns
        target_h = (image.shape[0] // rows) * rows
        if image.shape[1] != target_w or image.shape[0] != target_h:
            image = cv2.resize(image, (target_w, target_h),
                               interpolation=cv2.INTER_AREA)
        self.image = image

        self.cell_width = target_w // columns
        self.cell_height = target_h // rows

        # Per-image background floor (for adaptive thresholding)
        max_ch = np.max(image, axis=2)
        self._bg_floor = int(np.percentile(max_ch, 5))

        logger.debug(
            "MCDUParser: %dx%d grid, image %dx%d, "
            "cell %dx%d px, bg_floor=%d",
            rows, columns, target_w, target_h,
            self.cell_width, self.cell_height, self._bg_floor,
        )

    # ------------------------------------------------------------------
    #  Cell / row extraction
    # ------------------------------------------------------------------
    def extract_cell(self, row: int, col: int) -> np.ndarray:
        x = col * self.cell_width
        y = row * self.cell_height
        return self.image[y : y + self.cell_height, x : x + self.cell_width]

    def _extract_row_image(self, row: int) -> np.ndarray:
        y = row * self.cell_height
        return self.image[y : y + self.cell_height, :]

    # ------------------------------------------------------------------
    #  Colour detection
    # ------------------------------------------------------------------
    def detect_color(self, cell: np.ndarray) -> str:
        gray = np.max(cell, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        bright_mask = gray > ink_threshold
        if not np.any(bright_mask):
            return "w"

        r, g, b = np.mean(cell[bright_mask], axis=0).astype(int)

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
    #  Empty-cell detection  (adaptive)
    # ------------------------------------------------------------------
    def is_empty_cell(self, cell: np.ndarray, threshold: int = 30) -> bool:
        avg = float(np.mean(cell)) - self._bg_floor
        if avg >= threshold:
            return False
        gray = np.max(cell, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        ink_ratio = np.count_nonzero(gray > ink_threshold) / max(gray.size, 1)
        return ink_ratio < self.MIN_INK_RATIO

    # ------------------------------------------------------------------
    #  Font-size heuristic
    # ------------------------------------------------------------------
    def is_small_font(self, row: int) -> bool:
        return (row % 2 == 1) and (row != 13)

    # ------------------------------------------------------------------
    #  Cell preprocessing  (for template matching)
    # ------------------------------------------------------------------
    def _preprocess_cell(self, cell: np.ndarray) -> np.ndarray:
        """Convert a colour cell to a clean binary image."""
        gray = np.max(cell, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        _, binary = cv2.threshold(gray, ink_threshold, 255, cv2.THRESH_BINARY)
        # Small morphological close to fill 1-px gaps in the font
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        return binary

    # ------------------------------------------------------------------
    #  EasyOCR image preparation
    # ------------------------------------------------------------------
    def _preprocess_for_easyocr(self, img: np.ndarray,
                                 scale: int = 4) -> np.ndarray:
        """
        Prepare an image strip for EasyOCR.

        Pipeline: max-channel → binary threshold → invert (dark-on-light) →
        upscale → light blur → white padding.
        """
        gray = np.max(img, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        _, binary = cv2.threshold(gray, ink_threshold, 255, cv2.THRESH_BINARY)
        binary = cv2.bitwise_not(binary)  # dark-on-light for CRNN

        upscaled = cv2.resize(
            binary,
            (binary.shape[1] * scale, binary.shape[0] * scale),
            interpolation=cv2.INTER_LINEAR,
        )
        upscaled = cv2.GaussianBlur(upscaled, (3, 3), 0.8)

        pad = 16
        return cv2.copyMakeBorder(
            upscaled, pad, pad, pad, pad,
            cv2.BORDER_CONSTANT, value=255,
        )

    # ------------------------------------------------------------------
    #  OCR fix-ups
    # ------------------------------------------------------------------
    @staticmethod
    def _fix_ocr_char(ch: str) -> str:
        if ch in _OCR_FIXUPS:
            return _OCR_FIXUPS[ch]
        upper = ch.upper()
        if upper in _MCDU_VALID_CHARS:
            return upper
        return upper if upper.isprintable() else " "

    # ------------------------------------------------------------------
    #  EasyOCR — full image
    # ------------------------------------------------------------------
    def _ocr_full_image_easyocr(self) -> Dict[int, list]:
        try:
            scale = 3
            processed = self._preprocess_for_easyocr(self.image, scale)
            pad = 16
            reader = _get_easyocr_reader()
            results = reader.readtext(
                processed, detail=1, paragraph=False,
                allowlist=_EASYOCR_ALLOWLIST,
                width_ths=0.3, text_threshold=0.45, low_text=0.25,
            )

            row_results: Dict[int, list] = {}
            for bbox, text, conf in results:
                if conf < 0.15:
                    continue
                y_center = (sum(p[1] for p in bbox) / 4 - pad) / scale
                row = max(0, min(int(y_center / self.cell_height), self.rows - 1))
                x_left = (min(p[0] for p in bbox) - pad) / scale
                x_right = (max(p[0] for p in bbox) - pad) / scale
                text = text.strip()
                if not text:
                    continue
                n = len(text)
                char_w = (x_right - x_left) / max(n, 1)
                if row not in row_results:
                    row_results[row] = []
                for i, ch in enumerate(text):
                    cx = x_left + char_w * (i + 0.5)
                    row_results[row].append((self._fix_ocr_char(ch), cx))
            return row_results
        except Exception as exc:
            logger.debug("EasyOCR full-image error: %s", exc)
            return {}

    # ------------------------------------------------------------------
    #  EasyOCR — single row
    # ------------------------------------------------------------------
    def _ocr_row_easyocr(self, row_img: np.ndarray,
                          large_font: bool = False) -> list:
        try:
            scale = 3 if large_font else 4
            processed = self._preprocess_for_easyocr(row_img, scale)
            pad = 16
            reader = _get_easyocr_reader()
            results = reader.readtext(
                processed, detail=1, paragraph=False,
                allowlist=_EASYOCR_ALLOWLIST,
                width_ths=0.3, text_threshold=0.45, low_text=0.25,
            )
            chars: list = []
            for bbox, text, conf in results:
                if conf < 0.15:
                    continue
                x_left = (min(p[0] for p in bbox) - pad) / scale
                x_right = (max(p[0] for p in bbox) - pad) / scale
                text = text.strip()
                if not text:
                    continue
                n = len(text)
                char_w = (x_right - x_left) / max(n, 1)
                for i, ch in enumerate(text):
                    cx = x_left + char_w * (i + 0.5)
                    chars.append((self._fix_ocr_char(ch), cx))
            return chars
        except Exception as exc:
            logger.debug("EasyOCR row error: %s", exc)
            return []

    # ------------------------------------------------------------------
    #  Map OCR positions → grid columns
    # ------------------------------------------------------------------
    def _map_positions_to_cells(self, char_positions: list) -> List[Optional[str]]:
        cells: List[Optional[str]] = [None] * self.columns
        dists: List[float] = [float("inf")] * self.columns
        half = self.cell_width / 2.0
        for char, cx in char_positions:
            col = max(0, min(int(cx / self.cell_width), self.columns - 1))
            d = abs(cx - (col * self.cell_width + half))
            if d < dists[col]:
                cells[col] = char
                dists[col] = d
        return cells

    # ------------------------------------------------------------------
    #  Contour-based symbol detection  (improved)
    # ------------------------------------------------------------------
    def _detect_via_contours(self, cell: np.ndarray) -> Optional[str]:
        """Detect symbols that OCR often misreads: . - / < > [ ] ° arrows."""
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

            # Bounding box of all contours
            rects = [cv2.boundingRect(c) for c in contours]
            x_min = min(r[0] for r in rects)
            y_min = min(r[1] for r in rects)
            x_max = max(r[0] + r[2] for r in rects)
            y_max = max(r[1] + r[3] for r in rects)

            glyph_w = x_max - x_min
            glyph_h = y_max - y_min
            if glyph_w < 2 or glyph_h < 2:
                return None

            aspect = glyph_w / max(glyph_h, 1)
            roi = binary[y_min:y_max, x_min:x_max]
            fill = np.count_nonzero(roi) / max(roi.size, 1)
            h, w = roi.shape
            n_contours = len(contours)
            cell_h, cell_w = cell.shape[:2]

            left_half = np.count_nonzero(roi[:, : w // 2])
            right_half = np.count_nonzero(roi[:, w // 2 :])
            top_half = np.count_nonzero(roi[: h // 2, :])
            bot_half = np.count_nonzero(roi[h // 2 :, :])

            # --- dot / period ---
            if (glyph_w < cell_w * 0.35 and glyph_h < cell_h * 0.35
                    and fill > 0.40 and y_min > cell_h * 0.55):
                return "."

            # --- degree symbol ° ---
            if (glyph_w < cell_w * 0.40 and glyph_h < cell_h * 0.40
                    and fill > 0.20 and y_min < cell_h * 0.30
                    and n_contours <= 2):
                # Ring shape: low fill, near top of cell
                if 0.20 < fill < 0.65:
                    return "."  # CDU maps ° via special char

            # --- dash / minus ---
            if aspect > 1.8 and glyph_h < cell_h * 0.30 and fill > 0.35:
                return "-"

            # --- small filled square / box ---
            if (0.6 < aspect < 1.7 and fill > 0.55
                    and cell_h * 0.15 < glyph_h < cell_h * 0.65
                    and cell_w * 0.15 < glyph_w < cell_w * 0.65):
                return "["

            # --- forward slash / ---
            if (0.20 < aspect < 0.65 and 0.08 < fill < 0.35
                    and glyph_h > cell_h * 0.50):
                tl = np.count_nonzero(roi[: h // 2, : w // 2])
                br = np.count_nonzero(roi[h // 2 :, w // 2 :])
                tr = np.count_nonzero(roi[: h // 2, w // 2 :])
                bl = np.count_nonzero(roi[h // 2 :, : w // 2])
                if tr > tl and bl > br:
                    return "/"

            # --- square brackets [ ] ---
            if aspect < 0.70 and glyph_h > cell_h * 0.40 and 0.12 < fill < 0.60:
                top_row = roi[: max(1, h // 4), :]
                bot_row = roi[-max(1, h // 4) :, :]
                has_top = np.count_nonzero(top_row) > top_row.size * 0.20
                has_bot = np.count_nonzero(bot_row) > bot_row.size * 0.20
                if has_top and has_bot:
                    if left_half > right_half * 1.3:
                        return "["
                    if right_half > left_half * 1.3:
                        return "]"
                    glyph_cx = (x_min + x_max) / 2
                    return "[" if glyph_cx < cell_w * 0.40 else "]"

            # --- angle brackets < > ---
            if 0.3 < aspect < 0.85 and fill < 0.40:
                if left_half > right_half * 1.4:
                    return "<"
                if right_half > left_half * 1.4:
                    return ">"

            # --- colon : (two vertically stacked dots) ---
            if (n_contours == 2 and glyph_w < cell_w * 0.35
                    and glyph_h > cell_h * 0.35
                    and 0.15 < fill < 0.50):
                return "."

            # --- bidirectional arrow ↔ ---
            if n_contours >= 2 and 0.8 < aspect < 3.0 and fill < 0.40:
                if 0.5 < (left_half / max(right_half, 1)) < 2.0:
                    return "<>"

            # --- up / down arrow ↑↓ ---
            if n_contours >= 2 and aspect < 0.80 and fill < 0.50:
                if 0.5 < (top_half / max(bot_half, 1)) < 2.0:
                    return "^v"

            return None
        except Exception as exc:
            logger.debug("Contour detection error: %s", exc)
            return None

    # ------------------------------------------------------------------
    #  Main entry point
    # ------------------------------------------------------------------
    def parse_grid(self) -> List:
        """
        Parse the full MCDU grid.

        Returns:
            list of 336 elements, each ``[]`` (empty) or
            ``[char, colour, size]``.
        """
        t0 = time.perf_counter()
        matcher = _get_template_matcher()
        message_data: List = []

        # ── Phase 1: identify empty cells ──────────────────────────────
        row_empty: List[List[bool]] = []
        for row in range(self.rows):
            flags = [self.is_empty_cell(self.extract_cell(row, col))
                     for col in range(self.columns)]
            row_empty.append(flags)

        # Rows that contain at least one non-empty cell
        non_empty_rows: List[int] = []
        row_images: Dict[int, np.ndarray] = {}
        for row in range(self.rows):
            if not all(row_empty[row]):
                non_empty_rows.append(row)
                row_images[row] = self._extract_row_image(row)

        # ── No OCR engine at all: contour-only path ───────────────────
        if not _EASYOCR_AVAILABLE and matcher.template_count == 0:
            for row in range(self.rows):
                for col in range(self.columns):
                    cell = self.extract_cell(row, col)
                    if self.is_empty_cell(cell):
                        message_data.append([])
                        continue
                    char = self._detect_via_contours(cell) or " "
                    color = self.detect_color(cell)
                    size = 1 if self.is_small_font(row) else 0
                    message_data.append([char, color, size])
            elapsed = time.perf_counter() - t0
            logger.debug("parse_grid (contours only): %.0f ms", elapsed * 1000)
            return message_data

        # ── Phase 2: row-level change detection ────────────────────────
        changed_rows: List[int] = []
        cached_ocr: Dict[int, list] = {}

        for row in non_empty_rows:
            rim = row_images[row]
            if row in _prev_row_imgs:
                prev = _prev_row_imgs[row]
                if prev.shape == rim.shape:
                    mse = float(np.mean(
                        (rim.astype(np.float32) - prev.astype(np.float32)) ** 2
                    ))
                    if mse < _ROW_CHANGE_MSE:
                        cached_ocr[row] = _prev_row_ocr.get(row, [])
                        continue
            changed_rows.append(row)

        # ── Phase 3: template matching on changed rows ─────────────────
        template_results: Dict[Tuple[int, int], str] = {}
        unmatched_rows: List[int] = []  # rows needing EasyOCR

        for row in changed_rows:
            all_matched = True
            for col in range(self.columns):
                if row_empty[row][col]:
                    continue
                cell = self.extract_cell(row, col)
                cell_bin = self._preprocess_cell(cell)
                result = matcher.recognize(cell_bin)
                if result:
                    template_results[(row, col)] = result[0]
                else:
                    all_matched = False
            if not all_matched:
                unmatched_rows.append(row)

        # ── Phase 4: EasyOCR for rows that templates couldn't handle ───
        ocr_results: Dict[int, list] = dict(cached_ocr)

        if unmatched_rows and _EASYOCR_AVAILABLE:
            if len(unmatched_rows) >= 8:
                # Full-image OCR (one inference)
                full = self._ocr_full_image_easyocr()
                for row in unmatched_rows:
                    result = full.get(row, [])
                    ocr_results[row] = result
                    _prev_row_imgs[row] = row_images[row].copy()
                    _prev_row_ocr[row] = result
            else:
                for row in unmatched_rows:
                    is_large = not self.is_small_font(row)
                    result = self._ocr_row_easyocr(
                        row_images[row], large_font=is_large,
                    )
                    ocr_results[row] = result
                    _prev_row_imgs[row] = row_images[row].copy()
                    _prev_row_ocr[row] = result

        # Also cache rows that were fully template-matched
        for row in changed_rows:
            if row not in unmatched_rows:
                # Build a synthetic OCR result from templates for caching
                chars = []
                for col in range(self.columns):
                    if (row, col) in template_results:
                        cx = col * self.cell_width + self.cell_width / 2
                        chars.append((template_results[(row, col)], cx))
                ocr_results[row] = chars
                _prev_row_imgs[row] = row_images[row].copy()
                _prev_row_ocr[row] = chars

        n_cached = len(cached_ocr)
        n_template = len(changed_rows) - len(unmatched_rows)
        n_ocr = len(unmatched_rows)
        if n_cached or n_template or n_ocr:
            logger.debug(
                "Recognition: %d template-matched, %d OCR'd, %d cached rows",
                n_template, n_ocr, n_cached,
            )

        # ── Phase 5: assemble output + learn templates ─────────────────
        _learned_this_frame = 0
        for row in range(self.rows):
            if row not in ocr_results and row not in (
                r for r in changed_rows if r not in unmatched_rows
            ):
                # Row was entirely empty or had no content
                if all(row_empty[row]) if row < len(row_empty) else True:
                    message_data.extend([[]] * self.columns)
                    continue

            # Map EasyOCR positions to columns
            raw = ocr_results.get(row, [])
            cell_chars = self._map_positions_to_cells(raw)

            for col in range(self.columns):
                if row_empty[row][col]:
                    message_data.append([])
                    continue

                cell_img = self.extract_cell(row, col)

                # Priority: template > OCR > contour
                char = template_results.get((row, col))

                if not char:
                    char = cell_chars[col]

                if not char or char == " ":
                    contour_char = self._detect_via_contours(cell_img)
                    if contour_char:
                        char = contour_char

                if not char:
                    char = " "

                # Learn from OCR / contour results for future frames
                if char.strip() and (row, col) not in template_results:
                    cell_bin = self._preprocess_cell(cell_img)
                    matcher.learn(char, cell_bin, confidence=0.7)
                    _learned_this_frame += 1

                color = self.detect_color(cell_img)
                size = 1 if self.is_small_font(row) else 0
                message_data.append([char, color, size])

        # Persist templates periodically
        if matcher._dirty:
            matcher.save()

        elapsed = time.perf_counter() - t0
        logger.debug(
            "parse_grid: %.0f ms | %d cells | %d templates | %d learned",
            elapsed * 1000,
            sum(1 for c in message_data if c),
            matcher.template_count,
            _learned_this_frame,
        )
        return message_data
