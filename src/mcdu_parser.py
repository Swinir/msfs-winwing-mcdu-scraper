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

from mcdu_charset import OCR_ALLOWLIST, RENDERABLE

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
# The parser accepts exactly what the display can render, and asks EasyOCR
# for exactly that same set.  See mcdu_charset for why the hardware is the
# authority here.
_MCDU_VALID_CHARS = RENDERABLE

# Residual OCR clean-ups for characters the allowlist cannot exclude
# (case, and lookalikes the engine emits despite the allowlist).
_OCR_FIXUPS: Dict[str, str] = {
    "l": "1", "|": "1", "!": "1",
    "o": "O", "{": "[", "}": "]",
    ",": ".", ";": ".",
    "\\": "/",
    "_": "-", "~": "-",
    "\"": " ", "'": " ",
}

_EASYOCR_ALLOWLIST = OCR_ALLOWLIST


# ---------------------------------------------------------------------------
#  Context-based correction for letter/digit confusions
# ---------------------------------------------------------------------------
#
#  This replaces an earlier per-glyph geometry heuristic that inspected
#  stroke continuity to choose between D/O/0, A/B, B/8 and so on.  Measured
#  against rendered MCDU pages that heuristic cost 7.4 percentage points of
#  character accuracy: it relabelled almost every '0' as 'D' and many '8's as
#  'B', and because it also ran inside learn() those wrong labels became
#  permanent templates.
#
#  MCDU fields are strongly typed, which is a far more reliable signal than
#  stroke geometry: "N0450", "FL350" and "1204" are numeric, "LFPG" and
#  "AGOPA" are alphabetic.  A character is judged by the token it sits in.

#: Letter -> digit, applied inside an otherwise numeric token.
#: 'L' is deliberately absent.  L->1 is a rare misread, but L is extremely
#: common in ICAO codes and waypoint names (LFPG, LORNI); treating it as
#: ambiguous robbed those tokens of the evidence needed to repair them.
_TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "I": "1",
             "Z": "2", "S": "5", "G": "6", "B": "8"}

#: Digits that a letter could plausibly be misread as.  Used only to judge
#: whether a token is unambiguously numeric, never to rewrite anything.
_AMBIGUOUS_DIGITS = frozenset("012588".replace("8", "8"))
_AMBIGUOUS_DIGITS = frozenset({"0", "1", "2", "5", "8"})

#: Characters that end a token.  '.' is deliberately absent: it sits inside
#: values like 110.30 and M.78, and splitting there loses the digit evidence
#: that makes the rest of the number correctable.
_NEUTRAL = set(" /-+:[]()<>*☐←→↑↓Δ")


def _map_after_first(token: str, mapping: Dict[str, str]) -> str:
    """Apply *mapping* to every character except the first.

    The leading character of a token carries identity -- B738 is an aircraft
    type, not the number 8738, and G5 is not 65.  Correcting only the
    interior keeps the useful cases (46O -> 460, 4S2 -> 452, FL3SO -> FL350)
    while leaving those identifiers alone.
    """
    if not token:
        return token
    return token[0] + "".join(mapping.get(c, c) for c in token[1:])


def _correct_token(token: str) -> str:
    """Resolve letter/digit confusions within a single token.

    Only acts when the token's *other* characters are unambiguous and agree.
    A token of purely ambiguous characters is left alone -- there is no
    evidence either way, and guessing is what the old heuristic did wrong.
    """
    if len(token) < 2:
        return token

    # Count evidence from characters that cannot be confused.
    digits = sum(1 for c in token
                 if c.isdigit() and c not in _AMBIGUOUS_DIGITS)
    letters = sum(1 for c in token if c.isalpha() and c not in _TO_DIGIT)

    if digits >= 1 and letters == 0:
        return _map_after_first(token, _TO_DIGIT)

    # There is deliberately no digit -> letter direction.  It was tried, and
    # on a real MCDU capture it rewrote the nav database date "22JAN" as
    # "2ZJAN": the J, A and N are unambiguous letters while both 2s are
    # ambiguous, so the token reads as alphabetic.  Dates in DDMMM form are
    # common on these pages, and the repair it was meant to provide
    # (L0RNI -> LORNI) was never observed to be needed.

    # Mixed token.  The MCDU's common shape is a short alphabetic prefix on a
    # numeric body -- N0450 (speed), M.78 (mach), FL350 (level).  When the
    # body is unambiguously numeric, correct it without touching the prefix.
    head_len = 0
    while head_len < len(token) and token[head_len].isalpha():
        head_len += 1
    if 1 <= head_len <= 2 and head_len < len(token):
        head, tail = token[:head_len], token[head_len:]
        tail_digits = sum(1 for c in tail
                          if c.isdigit() and c not in _AMBIGUOUS_DIGITS)
        tail_letters = sum(1 for c in tail if c.isalpha() and c not in _TO_DIGIT)
        if tail_digits >= 1 and tail_letters == 0:
            return head + _map_after_first(tail, _TO_DIGIT)

    return token


def _correct_row_context(text: str) -> str:
    """Apply :func:`_correct_token` to every whitespace-separated token."""
    out = []
    token = []
    for char in text:
        if char in _NEUTRAL:
            if token:
                out.append(_correct_token("".join(token)))
                token = []
            out.append(char)
        else:
            token.append(char)
    if token:
        out.append(_correct_token("".join(token)))
    return "".join(out)


# ---------------------------------------------------------------------------
#  Row-level OCR cache  (persists across MCDUParser instances)
#
#  Keyed by ``(source_id, row)``.  The captain and co-pilot MCDUs are parsed
#  in the same process, so keying by row alone made them overwrite each
#  other's entries — each display would be served the other's cached OCR.
# ---------------------------------------------------------------------------
_prev_row_imgs: Dict[Tuple[str, int], np.ndarray] = {}
_prev_row_ocr: Dict[Tuple[str, int], list] = {}
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
    MATCH_THRESHOLD = 0.85     # min NCC score to accept
    MAX_TEMPLATES = 5          # max variants stored per character
    CONSENSUS_MIN = 2          # min votes to promote a candidate template

    #: Bumped whenever the normalisation changes shape-compatibility.
    #: Templates saved under an older format are discarded on load rather
    #: than silently compared against glyphs normalised a different way.
    FORMAT_VERSION = 2

    #: Where learned glyphs are persisted when no explicit path is given.
    DEFAULT_TEMPLATE_PATH = (
        Path(__file__).resolve().parent.parent / "templates" / "mcdu_templates.npz"
    )

    def __init__(self, template_path: Optional[Path] = None) -> None:
        """
        Args:
            template_path: Where to load/save learned glyphs.  Defaults to
                ``DEFAULT_TEMPLATE_PATH``.  Tests must pass a temp path —
                otherwise they inherit whatever the user learned by running
                the app, and their results depend on the host machine.
        """
        self._hash_cache: Dict[bytes, str] = {}
        self._templates: Dict[str, List[np.ndarray]] = {}
        self._candidates: Dict[bytes, Dict[str, int]] = {}
        self._dirty = False
        self._warmup_complete = False
        self._template_path = Path(
            template_path if template_path is not None
            else self.DEFAULT_TEMPLATE_PATH
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
            # Templates are disambiguated once, at learn() time, so the
            # label attached to a matched template is already correct.
            # Re-running the geometry heuristic here would let it overrule
            # what was learned — and it would be inconsistent with the
            # hash-cache path above, which returns the stored label as-is.
            self._hash_cache[key] = best_char
            return (best_char, best_score)

        return None

    # ----- learning ------------------------------------------------------

    def learn(self, char: str, cell_binary: np.ndarray,
              confidence: float = 1.0) -> None:
        """Record a confirmed character template (consensus-based).

        During warmup (before ``_warmup_complete``), each glyph shape
        accumulates votes.  A template is only promoted once the same
        character reaches ``CONSENSUS_MIN`` votes with a clear majority.
        After warmup, new characters are accepted directly (the bulk of
        the character set is already safely templated).
        """
        if confidence < 0.60 or not char or not char.strip():
            return
        char = char.upper()
        if len(char) != 1:
            return

        glyph = self._extract_glyph(cell_binary)
        if glyph is None:
            return

        norm = self._normalize(glyph)
        key = norm.tobytes()

        # Already known — skip
        if key in self._hash_cache:
            return

        # ---- post-warmup: direct learning for truly new glyphs ----
        if self._warmup_complete:
            self._commit_template(char, norm)
            return

        # ---- warmup: candidate voting ----
        if key not in self._candidates:
            self._candidates[key] = {}
        votes = self._candidates[key]
        votes[char] = votes.get(char, 0) + 1

        best_char = max(votes, key=votes.get)
        total = sum(votes.values())
        if (votes[best_char] >= self.CONSENSUS_MIN
                and votes[best_char] > total * 0.6):
            self._commit_template(best_char, norm)
            del self._candidates[key]
            logger.debug(
                "Promoted '%s' (%d/%d votes, %d total templates)",
                best_char, votes[best_char], total, self.template_count,
            )

    def _commit_template(self, char: str, norm: np.ndarray) -> None:
        """Directly commit a normalised glyph as a template."""
        key = norm.tobytes()
        self._hash_cache[key] = char

        if char not in self._templates:
            self._templates[char] = []

        for existing in self._templates[char]:
            if self._ncc(norm, existing) > 0.95:
                return

        if len(self._templates[char]) >= self.MAX_TEMPLATES:
            return

        self._templates[char].append(norm)
        self._dirty = True

    # ----- persistence ---------------------------------------------------

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self._template_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"__format__": np.array([self.FORMAT_VERSION])}
            for char, templates in self._templates.items():
                # Use hex-encoded UTF-8 to handle multi-character keys
                # (e.g. "<>" from OCR) as well as single characters.
                hex_key = char.encode("utf-8").hex()
                for i, tmpl in enumerate(templates):
                    data[f"h{hex_key}_{i}"] = tmpl
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

            stored_format = int(data["__format__"][0]) if "__format__" in data.files else 1
            if stored_format != self.FORMAT_VERSION:
                logger.warning(
                    "Discarding templates from %s: saved in format v%d, this "
                    "build normalises glyphs differently (v%d). They will be "
                    "relearned on the next warmup.",
                    self._template_path, stored_format, self.FORMAT_VERSION,
                )
                return

            for key in data.files:
                if key == "__format__":
                    continue
                prefix = key.split("_")[0]
                if prefix.startswith("h"):
                    # New format: hex-encoded UTF-8
                    char = bytes.fromhex(prefix[1:]).decode("utf-8")
                else:
                    # Legacy format: cXXXX (single Unicode codepoint)
                    char = chr(int(prefix[1:], 16))
                if char not in self._templates:
                    self._templates[char] = []
                self._templates[char].append(data[key])
            if self.template_count > 0:
                self._warmup_complete = True
            logger.info(
                "Loaded %d templates for %d characters",
                self.template_count, len(self._templates),
            )
        except Exception as exc:
            logger.warning("Failed to load templates: %s", exc)

    # ----- helpers -------------------------------------------------------

    def _normalize(self, glyph: np.ndarray) -> np.ndarray:
        """Scale a glyph into NORM_SIZE, preserving its aspect ratio.

        Stretching each glyph to fill the box destroyed the one feature that
        separates the thin symbols: a dash, a period, an underscore and a
        solid block all became the same all-white rectangle and matched each
        other with NCC 1.0.  Scaling by the smaller factor and centring the
        result on a blank canvas keeps them distinct.
        """
        target_w, target_h = self.NORM_SIZE
        h, w = glyph.shape[:2]
        if w < 1 or h < 1:
            return np.zeros((target_h, target_w), dtype=np.uint8)

        scale = min(target_w / w, target_h / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(glyph, (new_w, new_h), interpolation=cv2.INTER_AREA)

        canvas = np.zeros((target_h, target_w), dtype=np.uint8)
        y0 = (target_h - new_h) // 2
        x0 = (target_w - new_w) // 2
        canvas[y0:y0 + new_h, x0:x0 + new_w] = resized

        _, binary = cv2.threshold(canvas, 127, 255, cv2.THRESH_BINARY)
        return binary

    @staticmethod
    def _extract_glyph(binary: np.ndarray) -> Optional[np.ndarray]:
        coords = cv2.findNonZero(binary)
        if coords is None:
            return None
        x, y, w, h = cv2.boundingRect(coords)
        # A hyphen renders as few as 6x1 px in a 20x24 cell.  Requiring 2px
        # in both axes silently discarded every dash on the display.
        if w < 1 or h < 1:
            return None
        # 1-px padding so glyphs at slightly different positions within
        # the cell normalise to a consistent shape after resize.
        H, W = binary.shape
        pad = 1
        return binary[max(0, y - pad) : min(H, y + h + pad),
                      max(0, x - pad) : min(W, x + w + pad)]

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

    def reset(self) -> None:
        """Wipe all in-memory templates and candidates."""
        self._hash_cache.clear()
        self._templates.clear()
        self._candidates.clear()
        self._warmup_complete = False
        self._dirty = False
        logger.info("Template matcher reset — all templates cleared")


# Active matcher.  One store is live at a time: glyphs learned from one
# font must never be matched against another, so switching aircraft profile
# switches the store (see set_template_store).
_template_matcher: Optional[TemplateMatcher] = None
_template_store_path: Optional[Path] = None


def _get_template_matcher() -> TemplateMatcher:
    global _template_matcher
    if _template_matcher is None:
        _template_matcher = TemplateMatcher(template_path=_template_store_path)
    return _template_matcher


def set_template_store(path) -> None:
    """Make *path* the active learned-glyph store.

    Saves the outgoing store first, and clears the row-level OCR caches:
    cached results were produced by the old store's glyphs.
    A no-op when *path* is already active.
    """
    global _template_matcher, _template_store_path
    path = Path(path)
    if _template_matcher is not None and _template_store_path == path:
        return
    if _template_matcher is not None:
        _template_matcher.save()
    _template_store_path = path
    _template_matcher = TemplateMatcher(template_path=path)
    _prev_row_imgs.clear()
    _prev_row_ocr.clear()
    logger.info("Template store switched to %s (%d templates)",
                path.name, _template_matcher.template_count)


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

    #: A cell whose pixels are mostly at foreground brightness is reverse
    #: video: a coloured block with a dark glyph cut out of it.  The MCDU
    #: uses it for scratchpad messages, and the UNS-1 for its ACCEPT prompt.
    #: Measured over 929 cells from six real captures, ordinary cells reach
    #: at most 40.9% and inverted ones start at 47.8%, so this sits between
    #: them with roughly three points of margin either side.
    INVERTED_FILL_RATIO = 0.44

    def __init__(self, image: np.ndarray,
                 columns: int = 24, rows: int = 14,
                 source_id: str = "default",
                 small_font_rule: str = "labels_small") -> None:
        self.columns = columns
        self.rows = rows
        # How rows map to the hardware's large/small font:
        # "labels_small" (Airbus/Boeing: odd label rows small, last row
        # large) or "all_large" (UNS-1 style CRTs).
        self.small_font_rule = small_font_rule
        # Namespaces the row-level OCR caches.  Every capture source
        # (captain, co-pilot, ...) must pass a distinct id, otherwise they
        # share cache entries and serve each other stale rows.
        self.source_id = source_id

        # Partition the image into cells with fractional boundaries instead
        # of resampling it to an exact multiple of the grid.
        #
        # The old code resized the capture so every cell was a whole number
        # of pixels.  Crop sizes are almost never exact multiples, so nearly
        # every frame went through cv2.resize, and INTER_AREA blurs thin
        # glyph strokes.  Worse, the blur depends on the crop size: a crop
        # one pixel wider than another resamples differently, so templates
        # learned at one size stopped matching at the other.  Measured on a
        # rendered page, a single pixel of extra width took recognition from
        # 100% to 51%.
        #
        # Rounded edges give cells that differ by at most a pixel and cost no
        # interpolation at all.
        self.image = image
        height, width = image.shape[:2]

        self._col_edges = [round(c * width / columns) for c in range(columns + 1)]
        self._row_edges = [round(r * height / rows) for r in range(rows + 1)]

        # Kept as floats for OCR position mapping, which works in continuous
        # coordinates rather than whole cells.
        self.cell_width = width / columns
        self.cell_height = height / rows

        # Per-image background floor (for adaptive thresholding)
        max_ch = np.max(image, axis=2)
        self._bg_floor = int(np.percentile(max_ch, 5))

        # Midpoint between background and glyph brightness, used to tell a
        # reverse-video cell from an ordinary one.  Taken from the image
        # rather than fixed, so a dim display is judged on its own terms.
        peak = float(np.percentile(max_ch, 99))
        self._mid_level = self._bg_floor + 0.5 * (peak - self._bg_floor)

        logger.debug(
            "MCDUParser: %dx%d grid, image %dx%d, "
            "cell %.2fx%.2f px, bg_floor=%d",
            rows, columns, width, height,
            self.cell_width, self.cell_height, self._bg_floor,
        )

    # ------------------------------------------------------------------
    #  Cell / row extraction
    # ------------------------------------------------------------------
    def extract_cell(self, row: int, col: int) -> np.ndarray:
        return self.image[
            self._row_edges[row]:self._row_edges[row + 1],
            self._col_edges[col]:self._col_edges[col + 1],
        ]

    def _extract_row_image(self, row: int) -> np.ndarray:
        return self.image[self._row_edges[row]:self._row_edges[row + 1], :]

    # ------------------------------------------------------------------
    #  Colour detection
    # ------------------------------------------------------------------
    def detect_color(self, cell: np.ndarray) -> str:
        gray = np.max(cell, axis=2)
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        bright_mask = gray > ink_threshold
        if not np.any(bright_mask):
            return "w"

        bright_pixels = cell[bright_mask]
        # Median is more robust to stray noise/outlier pixels than mean.
        r = int(np.median(bright_pixels[:, 0]))
        g = int(np.median(bright_pixels[:, 1]))
        b = int(np.median(bright_pixels[:, 2]))

        # Convert to HSV (cell images are RGB from PIL/MSS/WGC).
        # HSV hue cleanly separates MCDU colours independent of display
        # brightness or gamma settings.
        pixel_rgb = np.array([[[r, g, b]]], dtype=np.uint8)
        hsv = cv2.cvtColor(pixel_rgb, cv2.COLOR_RGB2HSV)[0, 0]
        h_val = int(hsv[0])   # 0–180 in OpenCV scale
        s_val = int(hsv[1])   # 0–255
        v_val = int(hsv[2])   # 0–255

        # White / near-white: low saturation, high value
        if s_val < 50 and v_val > 150:
            return "w"
        # Cyan  hue ≈ 90° (OpenCV 90)
        if 80 <= h_val <= 105 and s_val > 80:
            return "c"
        # Green hue ≈ 60°
        if 50 <= h_val <= 82 and s_val > 80:
            return "g"
        # Yellow hue ≈ 30°, high saturation (checked before amber)
        if 22 <= h_val <= 42 and s_val > 150:
            return "y"
        # Amber  hue ≈ 15-25° (orange-amber)
        if 8 <= h_val <= 28 and s_val > 80:
            return "a"
        # Red    hue near 0° or 180°
        if (h_val <= 12 or h_val >= 165) and s_val > 80:
            return "r"
        # Magenta hue ≈ 150°
        if 130 <= h_val <= 165 and s_val > 80:
            return "m"
        # Grey: low saturation, moderate value
        if s_val < 80 and 40 <= v_val <= 200:
            return "e"
        return "w"

    # ------------------------------------------------------------------
    #  Reverse video
    # ------------------------------------------------------------------
    def is_inverted_cell(self, cell: np.ndarray) -> bool:
        """True when the cell is a coloured block with a dark glyph in it.

        MobiFlight's display protocol carries this as an optional fourth
        element per cell, ``[char, colour, size, inverted]``, and the CDU
        renders it as reverse video.
        """
        gray = np.max(cell, axis=2)
        return float(np.mean(gray > self._mid_level)) > self.INVERTED_FILL_RATIO

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
        if self.small_font_rule == "all_large":
            return False
        # Label rows sit on odd indices; the last row is the scratchpad and
        # always renders large.  (Generalises the old "row != 13".)
        return (row % 2 == 1) and (row != self.rows - 1)

    # ------------------------------------------------------------------
    #  Cell preprocessing  (for template matching)
    # ------------------------------------------------------------------
    def _preprocess_cell(self, cell: np.ndarray) -> np.ndarray:
        """Convert a colour cell to a clean binary image.

        A reverse-video cell is flipped first, so the glyph reads as ink and
        matches the same learned template as its normal-video twin.  Without
        that, every inverted character would be learned separately as a
        filled block with a hole in it.
        """
        gray = np.max(cell, axis=2)
        if self.is_inverted_cell(cell):
            gray = 255 - gray
        # Per-cell Otsu finds the optimal ink/background split.
        # It degrades when the cell is near-empty (low variance → very low
        # threshold that passes noise).  Guard: only accept Otsu values in
        # the range [half the fixed threshold, 220].
        ink_threshold = self.INK_THRESHOLD + self._bg_floor
        otsu_val, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        if otsu_val < ink_threshold * 0.5 or otsu_val > 220:
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

        Pipeline: max-channel → CLAHE (local contrast normalisation) →
        midpoint binary threshold → invert (dark-on-light) →
        upscale (cubic) → white padding.

        CLAHE normalises brightness across the strip so dim rows (grey,
        low-contrast amber) get the same ink/background separation as
        bright rows, without blurring thin strokes (CLAHE is not a blur).
        """
        gray = np.max(img, axis=2)
        # CLAHE: pushes background → 0, text → 255 independently per tile.
        # clipLimit=2.0 prevents over-amplifying noise in empty regions.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        # After CLAHE a fixed midpoint threshold cleanly separates ink/bg.
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        binary = cv2.bitwise_not(binary)  # dark-on-light for CRNN

        upscaled = cv2.resize(
            binary,
            (binary.shape[1] * scale, binary.shape[0] * scale),
            interpolation=cv2.INTER_CUBIC,
        )

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
    def _ocr_full_image_easyocr(self, scale: int = 3) -> Dict[int, list]:
        try:
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
        """Detect symbols that OCR often misreads: . - / < > [ ] ° arrows.

        IMPORTANT: This detector must be very conservative — a false
        positive here gets learned by the template matcher and will
        permanently corrupt recognition for that glyph shape.  Only
        return a character when the geometric evidence is unambiguous.
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

            # Bounding box of all contours
            rects = [cv2.boundingRect(c) for c in contours]
            x_min = min(r[0] for r in rects)
            y_min = min(r[1] for r in rects)
            x_max = max(r[0] + r[2] for r in rects)
            y_max = max(r[1] + r[3] for r in rects)

            glyph_w = x_max - x_min
            glyph_h = y_max - y_min
            # Dashes are legitimately 1px tall; see _extract_glyph.
            if glyph_w < 1 or glyph_h < 1:
                return None

            aspect = glyph_w / max(glyph_h, 1)
            roi = binary[y_min:y_max, x_min:x_max]
            fill = np.count_nonzero(roi) / max(roi.size, 1)
            h, w = roi.shape
            n_contours = len(contours)
            cell_h, cell_w = cell.shape[:2]

            # --- dot / period ---
            if (glyph_w < cell_w * 0.35 and glyph_h < cell_h * 0.35
                    and fill > 0.40 and y_min > cell_h * 0.55):
                return "."

            # --- degree symbol ° ---
            # A degree symbol is a small circular glyph in the *upper*
            # portion of the cell (above the text baseline).  A period is
            # always near the *bottom*.  They share a similar shape so
            # vertical position is the key discriminator.
            if (glyph_w < cell_w * 0.40 and glyph_h < cell_h * 0.40
                    and fill > 0.20 and y_min < cell_h * 0.30
                    and n_contours <= 2):
                if 0.20 < fill < 0.65:
                    return "°"

            # --- dash / minus ---
            if aspect > 2.0 and glyph_h < cell_h * 0.25 and fill > 0.40:
                return "-"

            # --- forward slash / ---
            if (0.20 < aspect < 0.50 and 0.08 < fill < 0.25
                    and glyph_h > cell_h * 0.55):
                tl = np.count_nonzero(roi[: h // 2, : w // 2])
                br = np.count_nonzero(roi[h // 2 :, w // 2 :])
                tr = np.count_nonzero(roi[: h // 2, w // 2 :])
                bl = np.count_nonzero(roi[h // 2 :, : w // 2])
                diag = tr + bl
                anti = tl + br + 1
                if diag > anti * 2.5 and tr > tl * 1.5 and bl > br * 1.5:
                    return "/"

            # --- square brackets [ ] ---
            # A bracket is OPEN on one side: the middle rows of the open
            # side must have very little ink.  Letters like T, A, B, D
            # have ink across the full width or in the centre, so they
            # fail this check.
            if (aspect < 0.65 and glyph_h > cell_h * 0.40
                    and 0.10 < fill < 0.50 and glyph_w < cell_w * 0.70):
                # Check top and bottom bars
                top_row = roi[: max(1, h // 5), :]
                bot_row = roi[-max(1, h // 5) :, :]
                has_top = np.count_nonzero(top_row) > top_row.size * 0.20
                has_bot = np.count_nonzero(bot_row) > bot_row.size * 0.20
                if has_top and has_bot:
                    # Key distinction: bracket must be OPEN on one side.
                    # Check the middle third of the glyph height.
                    mid_start = h // 3
                    mid_end = 2 * h // 3
                    mid_band = roi[mid_start:mid_end, :]
                    # Left and right edges of the middle band
                    mid_left = mid_band[:, : max(1, w // 3)]
                    mid_right = mid_band[:, -max(1, w // 3) :]
                    mid_center = mid_band[:, w // 4 : 3 * w // 4]
                    left_fill = np.count_nonzero(mid_left) / max(mid_left.size, 1)
                    right_fill = np.count_nonzero(mid_right) / max(mid_right.size, 1)
                    center_fill = np.count_nonzero(mid_center) / max(mid_center.size, 1)

                    # A '[' has ink on the left, empty on the right middle.
                    # A ']' has ink on the right, empty on the left middle.
                    # Letters like T, A, D have significant ink in the centre
                    # of the middle band — reject those.
                    if center_fill > 0.25:
                        pass  # Not a bracket — has ink in the middle (letter)
                    elif left_fill > 0.40 and right_fill < 0.15:
                        return "["
                    elif right_fill > 0.40 and left_fill < 0.15:
                        return "]"

            # --- colon : (two vertically stacked dots) ---
            if (n_contours == 2 and glyph_w < cell_w * 0.35
                    and glyph_h > cell_h * 0.35
                    and 0.15 < fill < 0.50):
                return "."

            return None
        except Exception as exc:
            logger.debug("Contour detection error: %s", exc)
            return None

    # ------------------------------------------------------------------
    #  Context corrections
    # ------------------------------------------------------------------
    def _apply_context_corrections(self, message_data: List) -> None:
        """Fix letter/digit confusions in place, one row at a time.

        Applied after assembly so each character is judged against the token
        it ends up in rather than in isolation.
        """
        for row in range(self.rows):
            base = row * self.columns
            cells = message_data[base:base + self.columns]
            if len(cells) < self.columns:
                break
            text = "".join(c[0] if c else " " for c in cells)
            corrected = _correct_row_context(text)
            if corrected == text:
                continue
            for i, char in enumerate(corrected):
                if cells[i] and cells[i][0] != char:
                    cells[i][0] = char

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
                    if self.is_inverted_cell(cell):
                        message_data.append([char, color, size, True])
                    else:
                        message_data.append([char, color, size])
            elapsed = time.perf_counter() - t0
            logger.debug("parse_grid (contours only): %.0f ms", elapsed * 1000)
            return message_data

        # ── Phase 2: row-level change detection ────────────────────────
        changed_rows: List[int] = []
        cached_ocr: Dict[int, list] = {}

        for row in non_empty_rows:
            rim = row_images[row]
            cache_key = (self.source_id, row)
            if cache_key in _prev_row_imgs:
                prev = _prev_row_imgs[cache_key]
                if prev.shape == rim.shape:
                    mse = float(np.mean(
                        (rim.astype(np.float32) - prev.astype(np.float32)) ** 2
                    ))
                    if mse < _ROW_CHANGE_MSE:
                        cached_ocr[row] = _prev_row_ocr.get(cache_key, [])
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
            _is_warmup = not matcher._warmup_complete

            if _is_warmup and len(unmatched_rows) >= 4:
                # ── Extended multi-scale warmup OCR ─────────────────
                # Run multiple rounds of full-image + row-level OCR at
                # different scales.  Each result feeds the consensus-based
                # template learner.  The first run takes ~30 s but produces
                # reliable templates for instant (<1 ms) matching afterwards.
                WARMUP_ROUNDS = 10
                warmup_scales = [2, 3, 4, 5, 6]
                logger.info(
                    "Template warmup — %d rounds × %d scales on %d rows "
                    "(this may take ~30 s) …",
                    WARMUP_ROUNDS, len(warmup_scales), len(unmatched_rows),
                )

                # Accumulate per-cell votes across ALL rounds
                cell_all_votes: Dict[Tuple[int, int], Dict[str, int]] = {}

                _stable_rounds = 0  # consecutive rounds with no new templates
                for rnd in range(WARMUP_ROUNDS):
                    _prev_count = matcher.template_count
                    for ws in warmup_scales:
                        # Full-image OCR at this scale
                        full = self._ocr_full_image_easyocr(scale=ws)
                        for row in unmatched_rows:
                            result = full.get(row, [])
                            cells = self._map_positions_to_cells(result)
                            for col in range(self.columns):
                                ch = cells[col]
                                if ch and ch.strip():
                                    k = (row, col)
                                    if k not in cell_all_votes:
                                        cell_all_votes[k] = {}
                                    cell_all_votes[k][ch] = (
                                        cell_all_votes[k].get(ch, 0) + 1
                                    )
                                    cell_bin = self._preprocess_cell(
                                        self.extract_cell(row, col),
                                    )
                                    matcher.learn(ch, cell_bin, confidence=0.8)

                    # Also do row-level OCR (different pre-processing path)
                    for row in unmatched_rows:
                        for ws2 in (3, 4, 5):
                            is_large = not self.is_small_font(row)
                            result = self._ocr_row_easyocr(
                                row_images[row], large_font=is_large,
                            )
                            cells = self._map_positions_to_cells(result)
                            for col in range(self.columns):
                                ch = cells[col]
                                if ch and ch.strip():
                                    k = (row, col)
                                    if k not in cell_all_votes:
                                        cell_all_votes[k] = {}
                                    cell_all_votes[k][ch] = (
                                        cell_all_votes[k].get(ch, 0) + 1
                                    )
                                    cell_bin = self._preprocess_cell(
                                        self.extract_cell(row, col),
                                    )
                                    matcher.learn(ch, cell_bin, confidence=0.8)

                    logger.info(
                        "  Warmup round %d/%d done — %d templates so far",
                        rnd + 1, WARMUP_ROUNDS, matcher.template_count,
                    )
                    # Stop early when templates have stabilised (no new
                    # glyphs learned for 2 consecutive rounds).
                    if matcher.template_count - _prev_count <= 2:
                        _stable_rounds += 1
                        if _stable_rounds >= 2:
                            logger.info(
                                "  Warmup converged after %d rounds "
                                "(templates stable at %d).",
                                rnd + 1, matcher.template_count,
                            )
                            break
                    else:
                        _stable_rounds = 0

                # Build display results via majority vote across ALL rounds
                for row in unmatched_rows:
                    row_chars: list = []
                    for col in range(self.columns):
                        if row_empty[row][col]:
                            continue
                        votes = cell_all_votes.get((row, col), {})
                        if votes:
                            best = max(votes, key=votes.get)
                            cx = col * self.cell_width + self.cell_width / 2
                            row_chars.append((best, cx))
                    ocr_results[row] = row_chars
                    _prev_row_imgs[(self.source_id, row)] = row_images[row].copy()
                    _prev_row_ocr[(self.source_id, row)] = row_chars

                matcher._warmup_complete = True
                logger.info(
                    "Warmup done — %d templates for %d characters",
                    matcher.template_count, len(matcher._templates),
                )

            elif len(unmatched_rows) >= 8:
                # Full-image OCR (one inference)
                full = self._ocr_full_image_easyocr()
                for row in unmatched_rows:
                    result = full.get(row, [])
                    ocr_results[row] = result
                    _prev_row_imgs[(self.source_id, row)] = row_images[row].copy()
                    _prev_row_ocr[(self.source_id, row)] = result
            else:
                for row in unmatched_rows:
                    is_large = not self.is_small_font(row)
                    result = self._ocr_row_easyocr(
                        row_images[row], large_font=is_large,
                    )
                    ocr_results[row] = result
                    _prev_row_imgs[(self.source_id, row)] = row_images[row].copy()
                    _prev_row_ocr[(self.source_id, row)] = result

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
                _prev_row_imgs[(self.source_id, row)] = row_images[row].copy()
                _prev_row_ocr[(self.source_id, row)] = chars

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
                _from_ocr = False  # track source for learning

                if not char:
                    char = cell_chars[col]
                    if char and char.strip():
                        _from_ocr = True

                if not char or char == " ":
                    contour_char = self._detect_via_contours(cell_img)
                    if contour_char:
                        char = contour_char
                        _from_ocr = False  # contour — don't learn

                if not char:
                    char = " "

                # Learn ONLY from EasyOCR results (not contour fallbacks).
                # Contour detection is intentionally conservative for
                # symbols only; learning from it causes letters like T, A, B
                # to be mislearned as brackets.
                if (char.strip() and _from_ocr
                        and not matcher._warmup_complete
                        and (row, col) not in template_results):
                    cell_bin = self._preprocess_cell(cell_img)
                    matcher.learn(char, cell_bin, confidence=0.7)
                    _learned_this_frame += 1

                color = self.detect_color(cell_img)
                size = 1 if self.is_small_font(row) else 0
                # detect_color already reports the block's colour for an
                # inverted cell: it medians the *bright* pixels, which are
                # the background there rather than the glyph.
                if self.is_inverted_cell(cell_img):
                    message_data.append([char, color, size, True])
                else:
                    message_data.append([char, color, size])

        # Resolve letter/digit confusions using each row's own token structure.
        self._apply_context_corrections(message_data)

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
