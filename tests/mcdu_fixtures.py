"""
Synthetic MCDU screen renderer, for testing recognition and region detection.

Real MCDU captures are not something a test suite can carry, and eyeballing
recognition quality does not catch regressions.  This renders a 24x14 page
from known text, so both the parser and the region detector can be scored
against ground truth.

The rendering deliberately mimics the properties that make the real thing
hard: a dark background, coloured glyphs at different brightnesses, alternating
large/small rows, and a surrounding window with chrome that the region
detector has to exclude.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

#: The Airbus entry box - a hollow rectangle marking a field the crew must
#: fill in.  Taken from the charset rather than redeclared, so a fixture
#: cannot end up testing a different character from the one the parser
#: emits.  It is drawn rather than typed: no monospace TTF is guaranteed to
#: carry U+2610, and the real display draws a plain rectangle anyway.
from mcdu_charset import BALLOT_BOX

COLUMNS = 24
ROWS = 14

#: MCDU colour code -> RGB, roughly matching an Airbus display.
COLOR_RGB: Dict[str, Tuple[int, int, int]] = {
    "w": (235, 235, 235),
    "c": (0, 220, 235),
    "g": (0, 230, 60),
    "a": (255, 170, 0),
    "y": (240, 240, 0),
    "m": (240, 0, 240),
    "r": (240, 40, 40),
    "e": (130, 130, 130),
}

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    r"C:\Windows\Fonts\DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)


def find_mono_font() -> Optional[str]:
    """Locate a monospace TTF, or None when the platform has none."""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


@dataclass
class MCDUPage:
    """A page of FMS text plus the colour of each row.

    Carries its own grid dimensions and small-font convention, so fixtures
    can model displays other than the 24x14 airliner CDU (the UNS-1 shows
    fewer rows, all at one size).
    """

    lines: List[str] = field(default_factory=list)
    colors: List[str] = field(default_factory=list)
    columns: int = COLUMNS
    rows: int = ROWS
    small_font_rule: str = "labels_small"

    def padded(self) -> List[str]:
        """Rows padded/truncated to exactly *columns* characters."""
        out = []
        for i in range(self.rows):
            line = self.lines[i] if i < len(self.lines) else ""
            out.append(line[:self.columns].ljust(self.columns))
        return out

    def row_color(self, row: int) -> str:
        if row < len(self.colors) and self.colors[row]:
            return self.colors[row]
        return "w"

    def is_small_row(self, row: int) -> bool:
        if self.small_font_rule == "all_large":
            return False
        return (row % 2 == 1) and (row != self.rows - 1)

    def expected_cells(self) -> List[list]:
        """Ground truth in the parser's output format."""
        cells = []
        for row, line in enumerate(self.padded()):
            color = self.row_color(row)
            size = 1 if self.is_small_row(row) else 0
            for char in line:
                cells.append([] if char == " " else [char, color, size])
        return cells


def flight_plan_page() -> MCDUPage:
    """A representative F-PLN page."""
    return MCDUPage(
        lines=[
            "      F-PLN  LFPG      ",
            "     UTC   SPD/ALT     ",
            "LFPG      1204  ---/---",
            "     N0450  FL350      ",
            "AGOPA     1223   350/  ",
            "     N0450  FL350      ",
            "LORNI     1241   350/  ",
            "     N0450  FL350      ",
            "DIKRO     1302   350/  ",
            "     N0448  FL350      ",
            "KOLON     1318   350/  ",
            "     N0445  FL350      ",
            "EDDF      1349   ---/  ",
            "                       ",
        ],
        colors=["w", "w", "g", "g", "w", "g", "w", "g",
                "w", "g", "w", "g", "w", "w"],
    )


def perf_page() -> MCDUPage:
    """A PERF CLB page: heavy on digits and symbols."""
    return MCDUPage(
        lines=[
            "       CLB              ",
            "ACT MODE                ",
            "     MANAGED            ",
            "CI                      ",
            "30                      ",
            "DERATED CLB             ",
            "[  ]                    ",
            "TRANS ALT     UTC  DIST ",
            "5000          1210  120 ",
            "SEL SPD                 ",
            "300/.78                 ",
            "                        ",
            "<PHASE                  ",
            "                        ",
        ],
        colors=["w", "w", "g", "w", "c", "w", "c", "w",
                "c", "w", "c", "w", "w", "w"],
    )


def alpha_numeric_page() -> MCDUPage:
    """Dense page exercising the confusable pairs: O/0, I/1, B/8, S/5, Z/2."""
    return MCDUPage(
        lines=[
            "ABCDEFGHIJKLMNOPQRSTUVWX",
            "YZ0123456789.-/          ",
            "OOO000III111BBB888SSS555",
            "ZZZ222DDD000GGGCCCQQQOOO",
            "LFPG EDDF KJFK EGLL LEMD",
            "N0450 M.78 FL350 -56°C  ",
            "RWY 26R ILS 110.30      ",
            "GS 452 TAS 460 HDG 271  ",
            "[  ]<-> 1234/5678       ",
            "5000FT  250KT  V/S -1800",
            "TOD 12:34  DIST 120NM   ",
            "BRG 271 TRK 268 DA 4.2° ",
            "<RETURN        CONFIRM>*",
            "                        ",
        ],
        colors=["w", "w", "g", "c", "w", "g", "a", "w",
                "c", "w", "g", "w", "w", "w"],
    )




def airbus_init_page() -> MCDUPage:
    """A320/A330 INIT A, the page a cold start actually opens on.

    Two thirds of its content is amber entry boxes.  Recognising those as
    letters is what a real capture showed the parser doing, so this page is
    the fixture that keeps it honest.
    """
    box = BALLOT_BOX
    return MCDUPage(
        lines=[
            "          INIT       1/2",
            " CO RTE          FROM/TO",
            box * 10 + "     " + box * 4 + "/" + box * 4,
            "ALTN/CO RTE     INIT    ",
            "----/----        REQUEST",
            "FLT NBR                 ",
            box * 8 + "       IRS INIT>",
            "                        ",
            "                        ",
            "COST INDEX              ",
            "20                 WIND>",
            "CRZ FL/TEMP        TROPO",
            "-----/---3         36090",
            "                        ",
        ],
        colors=["w", "w", "a", "w", "a", "w", "a", "w",
                "w", "w", "c", "w", "c", "w"],
    )


def uns1_page() -> MCDUPage:
    """A UNS-1 style FMS page: fewer rows, all one size, green phosphor."""
    return MCDUPage(
        lines=[
            "  NAV      APPR   1/2   ",
            "FR KBOS   121.5  NM 42.1",
            "TO ENE    HDG 042  D 12 ",
            "NX SCUPP  ETE 00:14     ",
            "GS 285 KT  XTK L 0.2    ",
            "BRG 041  TAS 290        ",
            "FL180  FUEL 1842        ",
            "SXTK 0.0  MSA 3100      ",
            "WIND 270/45             ",
            "POS N42 21.7 W071 00.4  ",
            "←ACCEPT   FMC VER  2.2.3",
        ],
        colors=["g"] * 11,
        columns=24,
        rows=11,
        small_font_rule="all_large",
    )


ALL_PAGES = {
    "flight_plan": flight_plan_page,
    "perf": perf_page,
    "alpha_numeric": alpha_numeric_page,
    "airbus_init": airbus_init_page,
}


def _draw_entry_box(draw, col: int, row: int, cell_w: int, cell_h: int,
                    small: bool, rgb) -> None:
    """Draw one hollow entry box, centred in its cell.

    Proportions taken from a real Airbus capture: roughly 60% of the cell
    wide, 55% tall, one pixel of stroke at typical pop-out sizes.
    """
    bw = max(4, int(cell_w * 0.60))
    bh = max(4, int(cell_h * (0.42 if small else 0.55)))
    x = col * cell_w + (cell_w - bw) // 2
    y = row * cell_h + (cell_h - bh) // 2
    stroke = 2 if min(bw, bh) >= 12 else 1
    draw.rectangle([x, y, x + bw - 1, y + bh - 1], outline=rgb, width=stroke)


def render_mcdu(
    page: MCDUPage,
    cell_size: Tuple[int, int] = (20, 24),
    background: Tuple[int, int, int] = (6, 10, 14),
    font_path: Optional[str] = None,
    noise: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Render *page* as an RGB image of exactly COLUMNS x ROWS cells.

    Args:
        page: The text and colours to draw.
        cell_size: (width, height) of one character cell in pixels.
        background: Screen background colour.
        noise: Standard deviation of Gaussian noise, simulating capture grain.
        seed: Seed for the noise.

    Returns:
        RGB uint8 array of shape (ROWS*cell_h, COLUMNS*cell_w, 3).
    """
    font_path = font_path or find_mono_font()
    if font_path is None:
        raise RuntimeError("no monospace font available for rendering")

    cell_w, cell_h = cell_size
    width, height = page.columns * cell_w, page.rows * cell_h
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    # Small rows render at ~78% height, as on the real display.
    large = ImageFont.truetype(font_path, int(cell_h * 0.82))
    small = ImageFont.truetype(font_path, int(cell_h * 0.64))

    for row, line in enumerate(page.padded()):
        font = small if page.is_small_row(row) else large
        rgb = COLOR_RGB[page.row_color(row)]
        for col, char in enumerate(line):
            if char == " ":
                continue
            if char == BALLOT_BOX:
                _draw_entry_box(draw, col, row, cell_w, cell_h,
                                page.is_small_row(row), rgb)
                continue
            # Centre each glyph in its cell, as a fixed-pitch display does.
            box = draw.textbbox((0, 0), char, font=font)
            gw, gh = box[2] - box[0], box[3] - box[1]
            x = col * cell_w + (cell_w - gw) // 2 - box[0]
            y = row * cell_h + (cell_h - gh) // 2 - box[1]
            draw.text((x, y), char, font=font, fill=rgb)

    array = np.array(image, dtype=np.uint8)

    if noise > 0:
        rng = np.random.default_rng(seed)
        noisy = array.astype(np.float32) + rng.normal(0, noise, array.shape)
        array = np.clip(noisy, 0, 255).astype(np.uint8)

    return array


def embed_in_window(
    screen: np.ndarray,
    margin: Tuple[int, int, int, int] = (60, 90, 60, 40),
    chrome: bool = True,
    window_bg: Tuple[int, int, int] = (30, 30, 34),
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """Place a rendered MCDU screen inside a larger window image.

    This is what the region detector actually has to cope with: the capture
    contains a title bar, bezel and surrounding chrome, and the detector must
    return only the text area.

    Args:
        screen: The rendered MCDU screen.
        margin: (left, top, right, bottom) padding in pixels.
        chrome: Draw a title bar and bezel outline.

    Returns:
        (window_image, (x, y, width, height)) where the tuple is the true
        location of *screen* inside the returned image.
    """
    left, top, right, bottom = margin
    sh, sw = screen.shape[:2]
    height, width = sh + top + bottom, sw + left + right

    window = np.zeros((height, width, 3), dtype=np.uint8)
    window[:, :] = window_bg

    if chrome:
        # Title bar: a bright band the detector must not mistake for text.
        window[0:28, :] = (70, 70, 78)
        for i in range(6):
            x0 = 12 + i * 60
            window[8:20, x0:x0 + 44] = (200, 200, 205)
        # Bezel just outside the screen area.
        window[top - 6:top - 2, left - 6:left + sw + 6] = (90, 90, 95)
        window[top + sh + 2:top + sh + 6, left - 6:left + sw + 6] = (90, 90, 95)

    window[top:top + sh, left:left + sw] = screen
    return window, (left, top, sw, sh)


def grid_accuracy(expected: List[list], actual: List[list]) -> Dict[str, float]:
    """Score a parsed grid against ground truth.

    Returns a dict with character accuracy over non-empty ground-truth cells,
    an occupancy score, and the raw counts.
    """
    total = correct = 0
    occupancy_correct = 0
    confusions: Dict[str, int] = {}

    for i, want in enumerate(expected):
        got = actual[i] if i < len(actual) else []
        want_empty, got_empty = (not want), (not got)
        if want_empty == got_empty:
            occupancy_correct += 1
        if want_empty:
            continue
        total += 1
        if got and got[0] == want[0]:
            correct += 1
        else:
            key = f"{want[0]}->{got[0] if got else '_'}"
            confusions[key] = confusions.get(key, 0) + 1

    return {
        "char_accuracy": correct / total if total else 0.0,
        "occupancy_accuracy": occupancy_correct / len(expected) if expected else 0.0,
        "total": total,
        "correct": correct,
        "confusions": confusions,
    }


def region_iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    """Intersection-over-union of two (x, y, w, h) boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0
