"""
The learned-glyph store.

Recognition on a fixed-pitch display does not need an OCR engine once it
has seen the font.  Every glyph is normalised to a fixed size and kept, and
a later cell is named by finding the closest one - a hash lookup when the
shape is identical, normalised cross-correlation when it is not.  EasyOCR
is only the bootstrap: it teaches this store during warmup and is then
asked about whatever the store cannot name.

Two rules here were learned the hard way and are worth knowing before
changing anything:

* A stored label is never second-guessed.  Re-testing a template match
  against a geometric rule of thumb caps accuracy at the accuracy of that
  rule and makes learning pointless, because the correction is re-applied
  on every frame (ISSUES.md #5).

* A glyph is only stored once more than one independent reading agrees on
  it, *including* after warmup.  Committing a single unverified guess was
  once thought safe on the grounds that the character set was by then
  mostly covered; a real session grew its store from 80 to 126 templates
  while it ran and read worse with every one (ISSUES.md #25).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


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
    FALLBACK_THRESHOLD = 0.70  # ...and to accept as a last resort
    MAX_TEMPLATES = 5          # max variants stored per character
    CONSENSUS_MIN = 2          # min votes to promote a candidate template
    LATE_CONSENSUS_MIN = 3     # ...and after warmup, when evidence is thinner

    #: Bumped whenever the normalisation changes shape-compatibility, or
    #: whenever what a stored label means changes.  Templates saved under an
    #: older format are discarded on load rather than silently compared
    #: against glyphs normalised a different way.
    #:
    #: Version 4 is the second kind.  Stores written before it were built by
    #: a learner that relabelled glyphs on the way in and, once warmup was
    #: over, committed a single unverified guess straight to disk - a real
    #: session grew one from 80 to 126 templates while it ran, and read
    #: worse with every one.  Those labels cannot be trusted, so every store
    #: is rebuilt on first run rather than asking anyone to find and delete
    #: the file.
    FORMAT_VERSION = 4

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
            # No geometry heuristic here.  A template match is evidence from
            # the pixels of a glyph already confirmed by consensus; running
            # _disambiguate_confusables over it would let a rule of thumb
            # overrule that, and it would disagree with the hash-cache path
            # above, which returns the stored label untouched.
            self._hash_cache[key] = best_char
            return (best_char, best_score)

        return None

    def best_match(self, cell_binary: np.ndarray,
                   exclude: Optional[frozenset] = None,
                   ) -> Optional[Tuple[str, float]]:
        """The closest template regardless of MATCH_THRESHOLD.

        Used only as a last resort, for a cell that plainly holds ink
        but that neither engine would name.  Leaving such a cell blank
        throws away what the store already knows about the glyph, and a
        hole in the middle of a word reads worse on the CDU than a
        plausible letter does.  Never learned from.

        Args:
            cell_binary: The preprocessed cell.
            exclude: Characters this cell cannot hold.  The caller knows
                that when geometry has already ruled a shape out - and
                the store may well hold a template mislabelled as that
                very shape, which is what put a bracket inside
                CONSUMPTION.  Skipping it leaves the next best answer
                rather than no answer.
        """
        glyph = self._extract_glyph(cell_binary)
        if glyph is None:
            return None
        norm = self._normalize(glyph)
        cached = self._hash_cache.get(norm.tobytes())
        if cached is not None and not (exclude and cached in exclude):
            return (cached, 1.0)
        best_char, best_score = None, 0.0
        for char, templates in self._templates.items():
            if exclude and char in exclude:
                continue
            for tmpl in templates:
                score = self._ncc(norm, tmpl)
                if score > best_score:
                    best_score, best_char = score, char
        if best_char is None:
            return None
        return (best_char, best_score)

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

        # ---- candidate voting ----
        #
        # This applies after warmup as well.  It used to commit a glyph
        # straight to the store once warmup was over, on the reasoning that
        # the character set was by then mostly covered - but that is exactly
        # backwards.  A warmup vote is one of fifteen passes over the same
        # pixels; a later one is a single unverified guess, so it needs more
        # corroboration, not less.  A real session showed the cost: the
        # store grew 80 -> 90 -> 122 -> 126 templates while it ran, and the
        # display got steadily worse as wrong glyphs were matched and
        # re-matched from the cache.  Templates are permanent, so an
        # unconfirmed one is not a small mistake.
        if key not in self._candidates:
            self._candidates[key] = {}
        votes = self._candidates[key]
        votes[char] = votes.get(char, 0) + 1

        needed = (self.CONSENSUS_MIN if not self._warmup_complete
                  else self.LATE_CONSENSUS_MIN)
        best_char = max(votes, key=votes.get)
        total = sum(votes.values())
        if (votes[best_char] >= needed
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


def set_store(path) -> bool:
    """Make *path* the active learned-glyph store.

    Saves the outgoing store first.  Glyphs learned from one font must never
    be matched against another, so each aircraft profile gets its own file
    and switching profile switches the store.

    Returns:
        True if the active store changed.  The caller uses this to discard
        anything derived from the old one - the parser's row-level OCR cache
        holds readings produced by the old store's glyphs, and serving those
        after a switch would show the previous aircraft's font decisions.
    """
    global _template_matcher, _template_store_path
    path = Path(path)
    if _template_matcher is not None and _template_store_path == path:
        return False
    if _template_matcher is not None:
        _template_matcher.save()
    _template_store_path = path
    _template_matcher = TemplateMatcher(template_path=path)
    logger.info("Template store switched to %s (%d templates)",
                path.name, _template_matcher.template_count)
    return True
