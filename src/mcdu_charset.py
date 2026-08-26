"""
Single source of truth for the MCDU character set.

Three separate and disagreeing definitions used to exist: a validity set and
an EasyOCR allowlist in the parser, and a renderable set in the WebSocket
client.  They differed on '+', '*', ':' and the degree sign, so the parser
could accept characters the display cannot draw, and could forbid EasyOCR
from proposing ones it can.

The hardware is the authority.  RENDERABLE is what the CDU font can draw;
everything else is derived from it, so widening the display's repertoire is a
one-line change here rather than three edits that can drift apart.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

# ---------------------------------------------------------------------------
#  What the WinWing CDU's AirbusThales font can actually draw.
#  Derived from the official MobiFlight Fenix / FBW / Headwind scripts.
#  Sending anything outside this set can freeze the display.
# ---------------------------------------------------------------------------
BALLOT_BOX = "☐"   # small square marking a selectable field
ARROW_LEFT = "←"
ARROW_RIGHT = "→"
ARROW_UP = "↑"
ARROW_DOWN = "↓"
DELTA = "Δ"        # overfly marker
DEGREE = "°"

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
# '+' is here on the evidence of a real A330 capture, which shows +0.0/+0.0
# on the IDLE/PERF line.  Mapping it to a space lost the sign, and mapping it
# to '-' would have inverted the value.  If the AirbusThales font turns out
# not to carry it, move it back to SUBSTITUTIONS as '+': ' ' rather than
# folding it onto '-'.
PUNCTUATION = " .-+/<>[]()" + DEGREE

RENDERABLE: FrozenSet[str] = frozenset(
    LETTERS + DIGITS + PUNCTUATION
    + BALLOT_BOX + ARROW_LEFT + ARROW_RIGHT + ARROW_UP + ARROW_DOWN + DELTA
)

# ---------------------------------------------------------------------------
#  What EasyOCR is permitted to output.
# ---------------------------------------------------------------------------
#  Restricted to the ASCII subset of RENDERABLE.  A CRNN cannot reliably
#  produce the box-drawing and arrow glyphs, which reach the display through
#  contour detection and the '<'/'>' substitutions instead.  Letting the
#  engine propose characters the CDU cannot draw only invites a wrong guess
#  where a right one was available.
OCR_ALLOWLIST: str = "".join(
    sorted(c for c in RENDERABLE if c.isascii() and c != " ")
) + " "

# ---------------------------------------------------------------------------
#  Substitutions applied on the way to the display.
# ---------------------------------------------------------------------------
#  Anything neither in this table nor in RENDERABLE becomes a space.
SUBSTITUTIONS: Dict[str, str] = {
    "(": "[",
    ")": "]",
    "*": ".",
    ":": ".",
    "_": "-",
    "~": "-",
    "=": "-",
    "|": "1",
    "\\": "/",
    ",": ".",
    ";": ".",
    "{": "[",
    "}": "]",
    "<": ARROW_LEFT,    # line-select prompt on the left side
    ">": ARROW_RIGHT,   # line-select prompt on the right side
}


def sanitise_char(char: str) -> str:
    """Map a single character onto something the CDU can render."""
    if not char:
        return " "
    if len(char) > 1:
        # Multi-character strings can arrive from the contour fallback.
        char = char[0]
    if char in SUBSTITUTIONS:
        return SUBSTITUTIONS[char]
    if char in RENDERABLE:
        return char
    upper = char.upper()
    if upper in SUBSTITUTIONS:
        return SUBSTITUTIONS[upper]
    return upper if upper in RENDERABLE else " "
