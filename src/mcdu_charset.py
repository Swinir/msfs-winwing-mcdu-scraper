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
#  What the WinWing CDU's AirbusThales font is expected to draw.
#
#  Checked against MobiFlight's own source.  There is no allowlist on their
#  side: WinCtrlCduController.ConvertAndSendCduData does
#
#      byteList.AddRange(Encoding.UTF8.GetBytes(new char[] { currentChar }));
#
#  so whatever character it receives is UTF-8 encoded and forwarded to the
#  device unvalidated, and the reference headwind_a33_winwing_cdu.py script
#  filters nothing either -- its REPLACED_CHARS table only translates the
#  conventions its data source uses (for example '_' for an entry box) into
#  the matching glyphs.
#
#  So an earlier warning here that an unsupported character "can freeze the
#  display" has no basis in the implementation.  The real limit is which
#  glyphs the font file carries, and those .dat files are encrypted, so this
#  set stays the conservative one that reference integrations are known to
#  emit.  Widening it is a question of what the font has, not of protocol
#  safety.
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
# '+' is here on two pieces of evidence: a real A330 capture showing
# +0.0/+0.0 on the IDLE/PERF line, and MobiFlight passing every character
# through unfiltered (see above), exactly as the reference A330 script does.
# Mapping it to a space lost the sign; mapping it to '-' would invert it.
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
