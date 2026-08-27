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
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from mcdu_charset import BALLOT_BOX, OCR_ALLOWLIST, RENDERABLE
from mcdu_labels import apply_label_corrections

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  EasyOCR availability
# ---------------------------------------------------------------------------
_EASYOCR_AVAILABLE = False
_easyocr_mod = None
_easyocr_reader = None  # singleton, created lazily

if importlib.util.find_spec("easyocr") is not None:
    _EASYOCR_AVAILABLE = True
else:
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
#  Entry boxes
# ---------------------------------------------------------------------------
#  An Airbus CDU marks every field the crew must fill in with a hollow
#  rectangle, and a cold-start page is mostly made of them: INIT A alone
#  shows 22.  Neither EasyOCR nor the template matcher can name that glyph -
#  a CRNN has no box in its alphabet and picks whichever letter is closest,
#  which a real capture showed reading as "CS S  S S I" and " SSSSSSSI".
#  Worse, those wrong letters were then learned as templates, so the error
#  spread to genuine text.
#
#  The shape is unmistakable, though: ink all the way round the border and
#  none at all inside.  No letter does that - O and D curve away from their
#  corners, so their top and bottom rows do not span the full width.  So it
#  is recognised structurally, ahead of both engines, and cells that match
#  are never offered to the template learner.


#: The characters the geometry pass is trusted to have the last word on.
#: It runs over every cell that has ink, and on the 2831-glyph corpus it
#: named all of these that were present and claimed nothing else - so when
#: it has not named a cell, the cell is not one of these shapes, and any
#: other engine proposing one is contradicted by the pixels rather than
#: merely unconfirmed.
#:
#: The arrows are deliberately absent.  The detector does read them, but
#: the corpus holds a single left arrow and no right one - enough to
#: recognise a shape, nowhere near enough to overrule someone else about
#: it.  On the UNS-1's reverse-video ACCEPT prompt the rule does not fire,
#: and vetoing on that silence deleted an arrow a template had read
#: correctly.
GEOMETRY_OWNED = frozenset(
    [".", ":", "-", "/", "<", ">", "[", "]", "°", BALLOT_BOX]
)

#: Round brackets are deliberately absent, though the CDU draws them as
#: square ones (see SUBSTITUTIONS).  Folding them in caught a few C that
#: EasyOCR had proposed as "(" - and deleted the real parentheses of the
#: ATR's "GPS (UTC)", because a round bracket has no arms and the
#: bracket rule rightly does not fire on one.  The veto only covers
#: shapes the pass actually finds.


def vetoable(char: Optional[str]) -> bool:
    """True when *char* names a shape the geometry pass would have found."""
    return bool(char) and char in GEOMETRY_OWNED


def is_entry_box(binary: np.ndarray, cell_h: int, cell_w: int) -> bool:
    """True when *binary* holds a hollow rectangle rather than a character.

    Args:
        binary: One preprocessed cell, ink as 255.
        cell_h: Height of the cell the glyph came from.
        cell_w: Width of the cell the glyph came from.
    """
    coords = cv2.findNonZero(binary)
    if coords is None:
        return False
    x, y, w, h = cv2.boundingRect(coords)

    # Big enough to be a box rather than a dash, dot or degree sign, and
    # roughly as tall as it is wide.  A real box fills a little over half
    # the cell each way.
    if h < max(4, cell_h * 0.28) or w < max(4, cell_w * 0.28):
        return False
    if not 0.35 <= w / h <= 1.9:
        return False

    glyph = binary[y:y + h, x:x + w]
    band = lambda a: float(np.count_nonzero(a)) / max(a.size, 1)
    edge_h = max(1, h // 8)
    edge_w = max(1, w // 8)

    # Every border must be continuous: measured per row/column rather than
    # as a fill ratio, so a two-pixel stroke in an eight-pixel band still
    # scores 1.0.
    top = float(np.count_nonzero(glyph[:edge_h].any(axis=0))) / w
    bottom = float(np.count_nonzero(glyph[-edge_h:].any(axis=0))) / w
    left = float(np.count_nonzero(glyph[:, :edge_w].any(axis=1))) / h
    right = float(np.count_nonzero(glyph[:, -edge_w:].any(axis=1))) / h
    if min(top, bottom, left, right) < 0.80:
        return False

    # ...and the middle must be empty.  This is what rejects 0, 8, B and D,
    # every one of which puts ink through the centre of the glyph.
    inner = glyph[h // 4:h - h // 4, w // 4:w - w // 4]
    return inner.size > 0 and band(inner) <= 0.12


# ---------------------------------------------------------------------------
#  Structural disambiguation for commonly confused character pairs
# ---------------------------------------------------------------------------

def _disambiguate_confusables(cell_binary: np.ndarray, char: str) -> str:
    """Correct EasyOCR / template confusions using glyph geometry.

    EasyOCR confuses D/O, A/B, B/8 and I// because at cell resolution
    those glyphs share an outline.  Each test below looks at the one
    structural feature that actually separates the pair.

    Every rule here is measured against the real captures before it is
    kept.  Tests for N/H and S/5 used to sit below these, unreachable
    because the guard above never listed those characters; making them
    reachable turned 18 correct N into H and 12 correct S into 5, so they
    were deleted rather than repaired.

    Applied only to characters EasyOCR proposed.  It is deliberately not
    applied to template matches or to learned labels: a template already
    is evidence from these pixels, and letting a heuristic relabel it on
    the way into the store made every later frame worse.

    A ']' vs '1' test used to live here too and was removed - measured
    against the real captures it corrupted six genuine '1's to buy one
    repair, and the contour detector already tells brackets apart by
    their arms.
    """
    if char not in ('D', 'O', '0', 'A', 'B', '8', 'I', '/'):
        return char

    coords = cv2.findNonZero(cell_binary)
    if coords is None:
        return char
    x, y, bw, bh = cv2.boundingRect(coords)
    if bw < 3 or bh < 3:
        return char
    glyph = cell_binary[y : y + bh, x : x + bw]
    h, w = glyph.shape

    # ------------------------------------------------------------------
    #  D vs O  (and 0)
    # ------------------------------------------------------------------
    if char in ('D', 'O', '0'):
        # D has square corners on the left and a stem that runs the whole
        # height; O and 0 curve away from both left corners.  Thresholds
        # measured over 340 D/O/0 glyphs from the real captures and the
        # rendered pages: 87 of 87 D correct, 1 of 253 O/0 misread.  The
        # previous test (left-strip fill alone) turned real O and 0 into D
        # on eight of the real capture's glyphs.
        left_cols = max(2, w // 6)
        left_rows = np.any(glyph[:, :left_cols] > 0, axis=1)
        left_continuity = float(np.count_nonzero(left_rows)) / h
        corner = max(1, min(w, h) // 4)
        fill = lambda a: float(np.count_nonzero(a)) / max(a.size, 1)
        top_left = fill(glyph[:corner, :corner])
        bottom_left = fill(glyph[-corner:, :corner])

        if min(top_left, bottom_left) >= 0.60 and left_continuity >= 0.94:
            return 'D'
        if char == 'D':
            return 'O'
        # An O or a 0 without square corners is left as OCR read it: the
        # two are told apart by context, not by shape.

    # ------------------------------------------------------------------
    #  A vs B
    # ------------------------------------------------------------------
    if char in ('A', 'B'):
        top_quarter = glyph[: h // 4, :]
        bot_quarter = glyph[3 * h // 4 :, :]
        top_ink_cols = np.any(top_quarter > 0, axis=0)
        bot_ink_cols = np.any(bot_quarter > 0, axis=0)
        top_span = float(np.count_nonzero(top_ink_cols)) / max(w, 1)
        bot_span = float(np.count_nonzero(bot_ink_cols)) / max(w, 1)

        if top_span < bot_span * 0.78:
            return 'A'
        elif char == 'A' and top_span > bot_span * 0.88:
            return 'B'

    # ------------------------------------------------------------------
    #  B vs 8
    # ------------------------------------------------------------------
    if char in ('B', '8'):
        # B has a solid vertical bar on the left (like D).
        # 8 has curves on both sides — the left edge has gaps at the
        # waist and near corners.
        left_cols = max(2, w // 5)
        left_strip = glyph[:, :left_cols]
        rows_with_ink = np.any(left_strip > 0, axis=1)
        left_continuity = float(np.count_nonzero(rows_with_ink)) / h
        left_fill = float(np.count_nonzero(left_strip)) / max(left_strip.size, 1)

        if left_continuity > 0.85 and left_fill > 0.45:
            return 'B'
        elif char == 'B':
            return '8'

    # ------------------------------------------------------------------
    #  I vs / (and 1)
    # ------------------------------------------------------------------
    if char in ('I', '/'):
        # / has a strong diagonal: top-right ink, bottom-left ink.
        # I is vertically symmetric: ink centred on every row.
        if h > 3 and w > 3:
            tr = np.count_nonzero(glyph[: h // 2, w // 2 :])
            bl = np.count_nonzero(glyph[h // 2 :, : w // 2])
            tl = np.count_nonzero(glyph[: h // 2, : w // 2])
            br = np.count_nonzero(glyph[h // 2 :, w // 2 :])
            diag_score = (tr + bl) / max(tl + br + 1, 1)
            if diag_score > 2.0:
                return '/'
            else:
                return 'I'

    return char



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
    # common on these pages.
    #
    # A narrower version - rewrite only a digit sitting between two letters,
    # which would have repaired S0FTWARE, B4SE and PRD6RAM and did no damage
    # to any ground truth in the test data - was rejected for the same kind
    # of reason: that shape is exactly how procedures and airways are named.
    # BOKN2A and SITET1B are ordinary F-PLN entries, and turning them into
    # BOKNZA and SITETIB would corrupt a clearance while looking plausible.
    # A wrong character the crew can see is better than a wrong waypoint.

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


def row_empty_to_occupied(flags: List[bool]) -> List[bool]:
    """Invert a row of empty-cell flags into ink flags."""
    return [not flag for flag in flags]


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
    global _easyocr_mod, _easyocr_reader, _EASYOCR_AVAILABLE
    if _easyocr_reader is not None:
        return _easyocr_reader

    try:
        import easyocr as _easyocr_mod
    except ImportError:
        _EASYOCR_AVAILABLE = False
        logger.info("EasyOCR could not be loaded; using contour fallback")
        return None

    use_gpu = False
    gpu_info = "CPU"

    try:
        import torch
        import warnings
        # Suppress noisy PyTorch quantization and dataloader warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="torch.ao.nn.quantized")
        warnings.filterwarnings("ignore", category=UserWarning, module="torch.utils.data.dataloader")

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

        # One binary per cell per frame.  _preprocess_cell runs Otsu and a
        # morphological close, and the same cell is wanted by the box test,
        # the template matcher and the learner; without this it ran three
        # times over.
        self._bin_cache: Dict[Tuple[int, int], np.ndarray] = {}

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

    def cell_binary(self, row: int, col: int) -> np.ndarray:
        """The preprocessed binary for one cell, computed once per frame."""
        key = (row, col)
        binary = self._bin_cache.get(key)
        if binary is None:
            binary = self._preprocess_cell(self.extract_cell(row, col))
            self._bin_cache[key] = binary
        return binary

    def _is_entry_box(self, cell: np.ndarray) -> bool:
        """True when this cell holds an entry box rather than a character."""
        h, w = cell.shape[:2]
        if h < 5 or w < 4:
            return False
        return is_entry_box(self._preprocess_cell(cell), h, w)

    # ------------------------------------------------------------------
    #  EasyOCR image preparation
    # ------------------------------------------------------------------
    def _preprocess_for_easyocr(self, img: np.ndarray,
                                 scale: int = 4,
                                 thicken: bool = False) -> np.ndarray:
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
        if thicken:
            # One pass of dilation on the ink.  A CRT FMS - the Fokker
            # and the Avro - draws strokes a pixel wide, and a CRNN
            # trained on printed text reads those as broken.  This is
            # not better than the plain view, it is *different*: warmup
            # runs both and keeps what they agree on.
            binary = cv2.dilate(
                binary, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
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
    def _ocr_full_image_easyocr(self, scale: int = 3,
                                thicken: bool = False) -> Dict[int, list]:
        try:
            processed = self._preprocess_for_easyocr(
                self.image, scale, thicken)
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
                          large_font: bool = False,
                          scale: Optional[int] = None,
                          thicken: bool = False) -> list:
        """OCR one row strip.

        Args:
            row_img: The strip to read.
            large_font: Whether the row renders at full height; sets the
                default upscale factor, since a label row needs more of
                one to reach the CRNN's working size.
            scale: Explicit upscale factor, overriding *large_font*.
                Warmup varies this deliberately: it is the one knob that
                actually changes what the engine reads.
        """
        try:
            if scale is None:
                scale = 3 if large_font else 4
            processed = self._preprocess_for_easyocr(row_img, scale, thicken)
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
    #: What it costs the assignment below to leave one OCR character
    #: unplaced, as a fraction of a cell width.  It has to exceed the
    #: displacement of an ordinary crowded placement, or real characters
    #: get dropped in favour of a tidier fit; it has to stay well under the
    #: cost of shifting a whole run along, or a hallucinated character
    #: drags its neighbours with it instead of being discarded.
    SKIP_COST = 1.5

    #: How far a character may be moved from where OCR saw it, in cells.
    #: Beyond this the placement is not evidence of anything.
    MAX_SHIFT = 2.0

    def _map_positions_to_cells(
        self, char_positions: list,
        occupied: Optional[List[bool]] = None,
    ) -> List[Optional[str]]:
        """Assign one row of OCR output to grid columns, in order.

        The obvious mapping - round each character to the nearest column -
        loses one of any two that land on the same column, and the display
        then shows a hole in the middle of a word.  On the A330 capture it
        turned "+0.0/+0.0" into "+0. 0I+.0" and "19FEB-19MAR" into
        "19EB--1 9MB": in both, a character was not misread, it was thrown
        away because a neighbour had claimed its column.

        So the characters are assigned by dynamic programming instead,
        under two constraints the naive mapping ignores.  They keep their
        left-to-right order, because OCR output within a row is ordered and
        a mapping that reorders it is certainly wrong.  And - when the
        caller says which cells hold ink - they may only land on a cell
        that has some, which is far stronger evidence of where a character
        sits than the OCR engine's own estimate of its x position.

        Dropping a character is still allowed, at SKIP_COST, so that a
        spurious one is discarded rather than pushing a whole run sideways.

        Args:
            char_positions: ``(char, centre_x)`` pairs from an OCR pass.
            occupied: Per-column ink flags, or None to allow every column.

        Returns:
            One entry per column: the character assigned to it, or None.
        """
        cells: List[Optional[str]] = [None] * self.columns
        chars = sorted(
            (cp for cp in char_positions if cp[0] and str(cp[0]).strip()),
            key=lambda cp: cp[1],
        )
        if not chars:
            return cells

        columns = [c for c in range(self.columns)
                   if occupied is None or occupied[c]]
        if not columns:
            return cells

        n, m = len(chars), len(columns)

        # Dropping a character leaves a cell that Phase 1 measured ink in
        # with nothing in it, which is a known error rather than a cautious
        # one.  So it is only on the table when OCR has returned more
        # characters than there are cells to hold them.  Without that rule a
        # word read at a slightly short pitch - the usual case, since the
        # pitch comes from dividing a bounding box evenly - is cheapest to
        # fix by dropping one letter and sliding the rest along, which is
        # how SOFTWARE came back as SOFTARE.
        skip = self.cell_width * self.SKIP_COST if n > m else float("inf")
        placement = self._assign_in_order(chars, columns, skip)
        if placement is None:
            # MAX_SHIFT left no complete assignment.  Allow dropping after
            # all: some of these characters belong to no cell on this row.
            placement = self._assign_in_order(
                chars, columns, self.cell_width * self.SKIP_COST)
        if placement is None:
            return cells

        for char, column in placement:
            cells[column] = char
        return cells

    def _assign_in_order(self, chars: list, columns: List[int],
                         skip: float):
        """Cheapest order-preserving assignment of *chars* onto *columns*.

        Args:
            chars: ``(char, centre_x)`` pairs, sorted by centre_x.
            columns: Column indices that may receive a character.
            skip: Cost of leaving one character unplaced; ``inf`` forbids it.

        Returns:
            A list of ``(char, column)`` pairs, or None when no assignment
            is possible within :attr:`MAX_SHIFT`.
        """
        half = self.cell_width / 2.0
        centres = [c * self.cell_width + half for c in columns]
        reach = self.MAX_SHIFT * self.cell_width
        n, m = len(chars), len(columns)
        inf = float("inf")

        # cost[i][j]: characters 0..i-1 resolved against columns 0..j-1.
        # Each character is placed on one column or skipped, each column
        # takes at most one character, and order is preserved throughout.
        cost = [[inf] * (m + 1) for _ in range(n + 1)]
        back = [[0] * (m + 1) for _ in range(n + 1)]
        for j in range(m + 1):
            cost[0][j] = 0.0
        for i in range(1, n + 1):
            cost[i][0] = i * skip
            back[i][0] = 2
        for i in range(1, n + 1):
            cx = chars[i - 1][1]
            for j in range(1, m + 1):
                best, move = cost[i][j - 1], 0             # column unused
                shift = abs(cx - centres[j - 1])
                if shift <= reach and cost[i - 1][j - 1] < inf:
                    placed = cost[i - 1][j - 1] + shift
                    if placed < best:
                        best, move = placed, 1             # place it here
                if cost[i - 1][j] < inf:
                    skipped = cost[i - 1][j] + skip
                    if skipped < best:
                        best, move = skipped, 2            # drop it
                cost[i][j], back[i][j] = best, move

        if cost[n][m] == inf:
            return None

        out = []
        i, j = n, m
        while i > 0 and j > 0:
            move = back[i][j]
            if move == 0:
                j -= 1
            elif move == 1:
                out.append((chars[i - 1][0], columns[j - 1]))
                i -= 1
                j -= 1
            else:
                i -= 1
        return out

    # ------------------------------------------------------------------
    #  Contour-based symbol detection  (improved)
    # ------------------------------------------------------------------
    def _detect_via_contours(self, cell: np.ndarray) -> Optional[str]:
        """Name the glyphs OCR has no good answer for.

        Covers ``. : - / < > [ ] ° ← →``.  A CRNN is trained on words, and
        these are the characters it has the least to go on for; the MCDU
        meanwhile uses them constantly, for line-select prompts and for
        every dashed or empty field.  So they are decided from geometry
        instead.

        Every threshold below is measured over the glyphs in tests/data and
        the rendered pages, and every rule is checked both ways: it has to
        claim the character it is for, and refuse the letters that look like
        it.  That matters more here than anywhere else in the parser,
        because a wrong answer from this function used to be handed to the
        template learner and become permanent.  An audit over 260 firings
        found 113 of them wrong - L and C read as brackets, and L, E, F, 5
        and I read as degree signs, because the old tests asked only how
        big a glyph was and where it sat.
        """
        try:
            gray = np.max(cell, axis=2)
            if self.is_inverted_cell(cell):
                # Reverse video: the glyph is the dark part.  Without this
                # the tests below run over the surrounding block instead,
                # and since their answer now outranks both engines, the
                # UNS-1's inverted ACCEPT prompt lost its arrow.
                gray = 255 - gray
            ink_threshold = self.INK_THRESHOLD + self._bg_floor
            _, binary = cv2.threshold(gray, ink_threshold, 255,
                                      cv2.THRESH_BINARY)
            contours, hierarchy = cv2.findContours(
                binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE,
            )
            if not contours:
                return None

            coords = cv2.findNonZero(binary)
            if coords is None:
                return None
            gx, gy, glyph_w, glyph_h = cv2.boundingRect(coords)
            # Dashes are legitimately 1px tall; see _extract_glyph.
            if glyph_w < 1 or glyph_h < 1:
                return None

            cell_h, cell_w = cell.shape[:2]
            roi = binary[gy:gy + glyph_h, gx:gx + glyph_w]
            h, w = roi.shape

            aspect = glyph_w / max(glyph_h, 1)
            rel_h = glyph_h / max(cell_h, 1)
            top_at = gy / max(cell_h, 1)
            holes = (0 if hierarchy is None
                     else int(np.count_nonzero(hierarchy[0][:, 3] >= 0)))

            def fill(a) -> float:
                return float(np.count_nonzero(a)) / max(a.size, 1)

            def col_span(a) -> float:
                return float(np.count_nonzero(a.any(axis=0))) / max(a.shape[1], 1)

            def row_span(a) -> float:
                return float(np.count_nonzero(a.any(axis=1))) / max(a.shape[0], 1)

            # Per-row position of the first and last ink pixel, as a
            # fraction of the glyph width.  This is what tells a wedge from
            # a letter: '<' has ink at the very left of its middle rows and
            # nowhere near the left at its top and bottom, and no letter in
            # the corpus does both.
            ink_rows = roi > 0
            has_ink = ink_rows.any(axis=1)
            span = max(w - 1, 1)
            lead = np.where(has_ink, ink_rows.argmax(axis=1), w - 1) / span
            trail = np.where(
                has_ink, (w - 1) - ink_rows[:, ::-1].argmax(axis=1), 0) / span
            band = max(1, h // 5)
            lead_mid = float(lead[h // 2])
            trail_mid = float(trail[h // 2])
            lead_ends = min(float(lead[:band].mean()), float(lead[-band:].mean()))
            trail_ends = max(float(trail[:band].mean()), float(trail[-band:].mean()))

            corner = max(1, min(w, h) // 4)
            top_left = fill(roi[:corner, :corner])
            bottom_left = fill(roi[-corner:, :corner])
            top_right = fill(roi[:corner, -corner:])
            bottom_right = fill(roi[-corner:, -corner:])
            side = max(1, w // 4)
            left_stem = row_span(roi[:, :side])
            right_stem = row_span(roi[:, -side:])

            # --- degree sign and full stop -------------------------------
            # No letter in the corpus measures under 39% of the cell
            # height; these two never reach 32%.  Height alone keeps L, E,
            # F, 5 and I out, which the old size-and-position test did not.
            # Between the pair: a degree sign is a ring near the cap line,
            # a full stop is solid and sits on the baseline.
            if rel_h <= 0.32 and 0.45 <= aspect <= 1.9:
                if holes >= 1 and top_at < 0.36:
                    return "°"
                if holes == 0 and fill(roi) > 0.45 and top_at >= 0.36:
                    return "."

            # --- colon ---------------------------------------------------
            # Two small blobs stacked in a narrow column.  Of the 2831
            # labelled glyphs, the five colons are the only ones that
            # match, so this needs no further qualification.  Times on
            # the ATR are written 16H39:10, and the colon reaches the
            # CDU as a full stop - the font has no colon - but it has to
            # be read before it can be translated.
            if (len(contours) == 2 and aspect < 0.55
                    and 0.20 < rel_h < 0.55
                    and glyph_w < cell_w * 0.45):
                return ":"

            # --- dash / minus --------------------------------------------
            if aspect > 2.0 and rel_h < 0.25 and fill(roi) > 0.40:
                return "-"

            # --- square brackets [ ] -------------------------------------
            # Narrow and tall, square in all four corners, one side a
            # full-height stem and the other open.  The old test asked only
            # for a top bar, a bottom bar and an empty middle, which also
            # describes L, C, E, F, J and '>'.
            if (aspect <= 0.46 and rel_h >= 0.62
                    and 0.20 < fill(roi) <= 0.68):
                # Both arms reach right across the glyph.  A narrow '1'
                # with serifs is otherwise a fair match: the one in the
                # corpus that got through covered two thirds.
                arm = max(1, h // 6)
                if (col_span(roi[:arm]) >= 0.90
                        and col_span(roi[-arm:]) >= 0.90):
                    if left_stem >= 0.92 and right_stem <= 0.55:
                        return "["
                    if right_stem >= 0.92 and left_stem <= 0.55:
                        return "]"

            # --- forward slash -------------------------------------------
            if (0.25 <= aspect <= 0.95 and rel_h >= 0.42
                    and 0.06 < fill(roi) < 0.38):
                tl = np.count_nonzero(roi[:h // 2, :w // 2])
                br = np.count_nonzero(roi[h // 2:, w // 2:])
                tr = np.count_nonzero(roi[:h // 2, w // 2:])
                bl = np.count_nonzero(roi[h // 2:, :w // 2])
                # A '7' is also a diagonal; what it has and a slash has
                # not is a bar across the top.
                top_bar = col_span(roi[:max(1, h // 6)])
                if (tr + bl > (tl + br + 1) * 2.5
                        and tr > tl * 1.5 and bl > br * 1.5
                        and top_bar <= 0.55):
                    return "/"

            # --- chevrons and arrows -------------------------------------
            # The line-select prompts, and the only glyphs on the page that
            # are pure wedges.  Read off the per-row ink profile: '<' puts
            # ink at the extreme left of every middle row and keeps well
            # clear of the left at its top and bottom.  Over 2831 labelled
            # glyphs the closest letter is C, whose top and bottom rows
            # reach within half the glyph width where a chevron's stay
            # beyond 68%; '4' comes closer still and is excluded by its
            # counter, since no chevron or arrow encloses one.
            #
            # An arrow is a chevron with a shaft, so its middle row reaches
            # the far side as well.  That alone also describes '+', which
            # is why the head has to show: the third of the glyph under the
            # arrowhead carries appreciably more ink than the third under
            # the tail, while a plus sign is symmetric about its centre.
            if (0.45 <= aspect <= 1.40 and 0.28 <= rel_h <= 0.72
                    and holes == 0):
                third = max(1, w // 3)
                left_mass = np.count_nonzero(roi[:, :third])
                right_mass = np.count_nonzero(roi[:, -third:])
                if (lead_mid <= 0.05 and lead_ends >= 0.68
                        and left_stem <= 0.40 and trail_mid < 0.95):
                    return "<"
                if (trail_mid >= 0.95 and trail_ends <= 0.35
                        and right_stem <= 0.40):
                    return ">"
                if lead_mid <= 0.05 and trail_mid >= 0.95:
                    if (0.15 <= lead_ends <= 0.45 and trail_ends <= 0.60
                            and left_mass >= right_mass * 1.35):
                        return "←"
                    if (lead_ends >= 0.55 and trail_ends >= 0.80
                            and right_mass >= left_mass * 1.35):
                        return "→"

            return None
        except Exception as exc:
            logger.debug("Contour detection error: %s", exc)
            return None

    # ------------------------------------------------------------------
    #  Same shape, same character
    # ------------------------------------------------------------------
    #: How alike two normalised glyphs must be to count as the same shape.
    #: High enough that only rendering noise separates them - distinct
    #: characters in these fonts do not correlate this well.
    SAME_GLYPH_NCC = 0.93

    def _unify_identical_glyphs(self, message_data: List,
                                fixed: set) -> int:
        """Make cells that hold the same shape read as the same character.

        A page draws each character from one bitmap, so two cells whose
        glyphs are pixel-for-pixel alike cannot be different characters.
        Recognition does not know that: it decides each cell on its own, so
        the same M can come back as M eight times and as B twice, purely on
        which OCR pass happened to cover it.

        This groups the frame's glyphs by shape and gives each group the
        character most of its members were given.  It is evidence from the
        page itself, so unlike a dictionary of expected labels it holds for
        any aircraft, any page and any language on the display.

        Args:
            message_data: The assembled grid, corrected in place.
            fixed: Cell indices settled by geometry, which vote but are
                never overruled.

        Returns:
            How many characters were changed.
        """
        matcher = _get_template_matcher()
        indices: List[int] = []
        glyphs: List[np.ndarray] = []
        for row in range(self.rows):
            for col in range(self.columns):
                idx = row * self.columns + col
                cell = message_data[idx] if idx < len(message_data) else None
                if not cell or not cell[0] or not cell[0].strip():
                    continue
                glyph = matcher._extract_glyph(self.cell_binary(row, col))
                if glyph is None:
                    continue
                indices.append(idx)
                glyphs.append(matcher._normalize(glyph).astype(np.float32).ravel())

        if len(indices) < 2:
            return 0

        # One matmul rather than a pairwise loop: the frame can hold 300
        # glyphs, and this runs on every frame that is not served from the
        # row cache.
        matrix = np.vstack(glyphs)
        matrix -= matrix.mean(axis=1, keepdims=True)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        matrix /= norms[:, None]
        similarity = matrix @ matrix.T

        # Single-linkage groups over "alike enough to be the same glyph".
        n = len(indices)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        alike = np.argwhere(similarity >= self.SAME_GLYPH_NCC)
        for i, j in alike:
            if i < j:
                ri, rj = find(int(i)), find(int(j))
                if ri != rj:
                    parent[ri] = rj

        groups: Dict[int, List[int]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)

        changed = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            votes: Dict[str, int] = {}
            for i in members:
                char = message_data[indices[i]][0]
                votes[char] = votes.get(char, 0) + 1
            ranked = sorted(votes.items(), key=lambda kv: -kv[1])
            if len(ranked) < 2 or ranked[0][1] == ranked[1][1]:
                continue                # unanimous, or no majority to apply
            winner = ranked[0][0]
            for i in members:
                idx = indices[i]
                if idx in fixed:
                    continue
                if message_data[idx][0] != winner:
                    message_data[idx][0] = winner
                    changed += 1
        if changed:
            logger.debug("Shape agreement corrected %d characters", changed)
        return changed

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

        # ── Phase 1: identify empty cells ───────────────────────
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
                    char = (BALLOT_BOX if self._is_entry_box(cell)
                            else self._detect_via_contours(cell) or " ")
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
        # ── Phase 2b: what geometry alone can settle ──────────────
        #
        # Entry boxes and the punctuation glyphs are decided here, ahead
        # of both recognition engines.  Both are at their worst on
        # exactly these characters - a CRNN has no box in its alphabet at
        # all, and reads a dash, a slash or a chevron as whichever letter
        # is nearest - while the shapes themselves are unmistakable.
        # Scored over 2831 labelled glyphs from the real captures and the
        # rendered pages, these tests named all 422 that were present and
        # claimed no letter, a better record than either engine manages
        # on them, so their answer stands first.  Matching cells are also
        # kept away from the template learner: a made-up letter for an
        # entry box used to be learned, and then to spread into genuine
        # text.
        #
        # It runs after change detection rather than before it because a
        # row that has not changed is served from the cache regardless,
        # and the pass costs upwards of 40 ms on a large pop-out.
        structural: Dict[Tuple[int, int], str] = {}
        geometry_rows = set(changed_rows)
        for row in changed_rows:
            for col in range(self.columns):
                if row_empty[row][col]:
                    continue
                cell = self.extract_cell(row, col)
                if self._is_entry_box(cell):
                    structural[(row, col)] = BALLOT_BOX
                else:
                    found = self._detect_via_contours(cell)
                    if found:
                        structural[(row, col)] = found

        # ── Phase 3: template and OCR on what is left ──────────────
        template_results: Dict[Tuple[int, int], str] = {}
        unmatched_rows: List[int] = []  # rows needing EasyOCR

        for row in changed_rows:
            all_matched = True
            for col in range(self.columns):
                if row_empty[row][col]:
                    continue
                if (row, col) in structural:
                    template_results[(row, col)] = structural[(row, col)]
                    continue
                result = matcher.recognize(self.cell_binary(row, col))
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
                # Force EasyOCR initialisation and downloads BEFORE starting the warmup
                _get_easyocr_reader()
                
                # ── One OCR pass per genuinely different view ──────
                #
                # This used to run five rounds of the same calls.  They are
                # deterministic and do not consult the template store, so
                # rounds two to five recomputed round one exactly - five
                # times the work, for a consensus that counted one reading
                # five times over.  That defeated the vote it was there to
                # take: a single wrong reading, repeated, cleared the
                # two-vote bar on its own.  (The row pass was worse still,
                # looping over two scales and then ignoring the variable.)
                #
                # What actually varies a reading is the view: how far the
                # strip is upscaled before the CRNN sees it, and whether it
                # sees the whole page or a single row.  Each view runs once
                # and votes once, so agreement between them means what it
                # says.  Six views also cost a third of what the old
                # twenty-five did - a real session spent 145 s here.
                view_scales = (3, 4, 5)
                logger.info(
                    "Template warmup — %d views over %d rows "
                    "(around half a minute; once per display) …",
                    len(view_scales) * 2 + 2, len(unmatched_rows),
                )

                cell_all_votes: Dict[Tuple[int, int], Dict[str, int]] = {}

                def _cast_votes(row: int, result: list) -> None:
                    """Record one view's reading of one row."""
                    cells = self._map_positions_to_cells(
                        result, row_empty_to_occupied(row_empty[row]))
                    for col in range(self.columns):
                        ch = cells[col]
                        if not ch or not ch.strip():
                            continue
                        # Settled by geometry, or contradicted by it.
                        if (row, col) in structural or vetoable(ch):
                            continue
                        votes = cell_all_votes.setdefault((row, col), {})
                        votes[ch] = votes.get(ch, 0) + 1
                        matcher.learn(ch, self.cell_binary(row, col),
                                      confidence=0.8)

                def _read_page(scale: int, thicken: bool = False) -> None:
                    reading = self._ocr_full_image_easyocr(scale, thicken)
                    for row in unmatched_rows:
                        _cast_votes(row, reading.get(row, []))

                def _read_rows(scale: int, thicken: bool = False) -> None:
                    for row in unmatched_rows:
                        _cast_votes(row, self._ocr_row_easyocr(
                            row_images[row],
                            large_font=not self.is_small_font(row),
                            scale=scale, thicken=thicken,
                        ))

                for scale in view_scales:
                    _read_page(scale)
                    logger.info("  Warmup: whole page at x%d — %d templates",
                                scale, matcher.template_count)

                for scale in view_scales:
                    _read_rows(scale)
                    logger.info("  Warmup: row by row at x%d — %d templates",
                                scale, matcher.template_count)

                # Two more with the strokes thickened, for the CRT panels
                # whose glyphs are a pixel wide and read as broken.  Worth
                # 1.7 points on the Fokker and nothing on the Airbus, which
                # is what a view is for: not better, different.
                _read_page(4, thicken=True)
                _read_rows(4, thicken=True)
                logger.info("  Warmup: thickened strokes — %d templates",
                            matcher.template_count)

                # Settle each cell on the character most views agreed on.
                for row in unmatched_rows:
                    row_chars: list = []
                    for col in range(self.columns):
                        if row_empty[row][col]:
                            continue
                        if (row, col) in structural:
                            cx = col * self.cell_width + self.cell_width / 2
                            row_chars.append((structural[(row, col)], cx))
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
        changed = set(changed_rows)
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
            cell_chars = self._map_positions_to_cells(
                raw, row_empty_to_occupied(row_empty[row]))

            emitted: list = []
            for col in range(self.columns):
                if row_empty[row][col]:
                    message_data.append([])
                    continue

                cell_img = self.extract_cell(row, col)

                # Priority: geometry and templates (both in
                # template_results by now) ahead of EasyOCR.
                char = template_results.get((row, col))
                _from_ocr = False  # track source for learning

                if not char:
                    char = cell_chars[col]
                    if char and char.strip():
                        _from_ocr = True

                # Geometry looked at this cell and did not call it a
                # dash, a slash, a bracket or anything else it decides,
                # so proposing one is not a second opinion - it is an
                # answer these pixels rule out, whoever is offering it.
                # This is where the I of CONSUMPTION and the I of
                # ACTIVE picked up brackets.
                #
                # Only for rows geometry actually looked at: an unchanged
                # row is served from the cache, which already holds its
                # dashes and slashes from when it was last read.
                if (row in geometry_rows and vetoable(char)
                        and (row, col) not in structural):
                    char, _from_ocr = None, False

                if not char or not char.strip():
                    # The cell has ink - Phase 1 established that - and
                    # nothing has named it.  Rather than send a hole to
                    # the CDU, take the store's closest glyph if it is
                    # anywhere near.
                    guess = matcher.best_match(
                        self.cell_binary(row, col),
                        exclude=(GEOMETRY_OWNED if row in geometry_rows
                                 else None),
                    )
                    if guess and guess[1] >= matcher.FALLBACK_THRESHOLD:
                        char = guess[0]

                if not char:
                    char = " "

                # Geometry breaks the ties EasyOCR cannot, but only on
                # what EasyOCR proposed.  A template match already came
                # from these pixels and a contour match is structural
                # to begin with; overruling either with a rule of thumb
                # cost accuracy when this ran over every character.
                if _from_ocr and char.strip():
                    char = _disambiguate_confusables(
                        self.cell_binary(row, col), char)

                # Learn from EasyOCR only.  A template match has nothing
                # new to teach, the geometry pass deliberately keeps its
                # cells out of the store, and the fallback above is a guess
                # made *from* the store - learning from it would let the
                # store confirm itself.
                if (char.strip() and _from_ocr
                        and (row, col) not in template_results):
                    matcher.learn(char, self.cell_binary(row, col),
                                  confidence=0.7)
                    _learned_this_frame += 1

                if char.strip():
                    emitted.append(
                        (char,
                         col * self.cell_width + self.cell_width / 2))

                color = self.detect_color(cell_img)
                size = 1 if self.is_small_font(row) else 0
                # detect_color already reports the block's colour for an
                # inverted cell: it medians the *bright* pixels, which are
                # the background there rather than the glyph.
                if self.is_inverted_cell(cell_img):
                    message_data.append([char, color, size, True])
                else:
                    message_data.append([char, color, size])

            # Cache what this row *displayed*, not what OCR proposed for
            # it.  The two differ: the geometry pass and the template
            # matcher both feed the assembly above without going through
            # ocr_results, so storing the raw OCR reading meant a row
            # lost every dash, slash and entry box the moment it stopped
            # changing and started being served from this cache.
            if row in changed:
                _prev_row_imgs[(self.source_id, row)] = row_images[row].copy()
                _prev_row_ocr[(self.source_id, row)] = emitted

        # Cells drawn from the same bitmap must read the same way.
        # Anything geometry named is exempt: by the veto above, an owned
        # character reaches this point only from the geometry pass or
        # from a cached row it had already settled.
        self._unify_identical_glyphs(
            message_data,
            {i for i, cell in enumerate(message_data)
             if cell and vetoable(cell[0])},
        )

        # Resolve letter/digit confusions using each row's own token structure.
        self._apply_context_corrections(message_data)

        # Fix known fixed labels using the page-type dictionary.
        apply_label_corrections(
            message_data, self.columns, self.rows, self.small_font_rule,
        )

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
