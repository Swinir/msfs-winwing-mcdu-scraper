"""
Selection geometry for the region selector, with no GUI toolkit involved.

The dialog scales the captured window down to fit on screen, so every mouse
coordinate is in *display* space while the crop region the rest of the app
needs is in *original* image space.  Getting that conversion wrong produces a
crop that looks right in the dialog and captures the wrong pixels at runtime.

Keeping the maths here means it can be tested directly, and it survived the
move from Tkinter to Qt unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

#: Smallest selection the user is allowed to make, in display pixels.
MIN_SELECTION = 20

#: How close (display px) the pointer must be to count as grabbing a corner.
CORNER_GRAB_RADIUS = 12

CORNERS = ("nw", "ne", "sw", "se")


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in display coordinates."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def normalised(self) -> "Rect":
        """Return an equivalent rect with x1 <= x2 and y1 <= y2."""
        return Rect(
            min(self.x1, self.x2), min(self.y1, self.y2),
            max(self.x1, self.x2), max(self.y1, self.y2),
        )

    def contains(self, x: int, y: int) -> bool:
        """True when (x, y) is strictly inside the rect."""
        r = self.normalised()
        return r.x1 < x < r.x2 and r.y1 < y < r.y2

    def corner_at(self, x: int, y: int,
                  radius: int = CORNER_GRAB_RADIUS) -> Optional[str]:
        """Which corner handle (x, y) grabs, or None."""
        r = self.normalised()
        positions = {
            "nw": (r.x1, r.y1), "ne": (r.x2, r.y1),
            "sw": (r.x1, r.y2), "se": (r.x2, r.y2),
        }
        for corner, (cx, cy) in positions.items():
            if abs(x - cx) <= radius and abs(y - cy) <= radius:
                return corner
        return None

    def with_corner_at(self, corner: str, x: int, y: int,
                       min_size: int = MIN_SELECTION) -> "Rect":
        """Drag *corner* to (x, y).  Returns self if that would be too small."""
        x1, y1, x2, y2 = self.x1, self.y1, self.x2, self.y2
        if corner == "nw":
            x1, y1 = x, y
        elif corner == "ne":
            x2, y1 = x, y
        elif corner == "sw":
            x1, y2 = x, y
        elif corner == "se":
            x2, y2 = x, y
        else:
            raise ValueError(f"unknown corner {corner!r}, expected one of {CORNERS}")

        candidate = Rect(x1, y1, x2, y2).normalised()
        if candidate.width < min_size or candidate.height < min_size:
            return self
        return candidate

    def moved_by(self, dx: int, dy: int,
                 bounds: Tuple[int, int]) -> "Rect":
        """Translate by (dx, dy), refusing moves that would leave *bounds*.

        Each axis is considered separately, so dragging into the left edge
        still allows vertical movement.
        """
        max_w, max_h = bounds
        r = self.normalised()
        x1, y1, x2, y2 = r.x1, r.y1, r.x2, r.y2

        if 0 <= x1 + dx and x2 + dx <= max_w:
            x1, x2 = x1 + dx, x2 + dx
        if 0 <= y1 + dy and y2 + dy <= max_h:
            y1, y2 = y1 + dy, y2 + dy

        return Rect(x1, y1, x2, y2)


class RegionSelection:
    """Maps between the scaled-down preview and the original capture."""

    def __init__(self, original_size: Tuple[int, int],
                 max_display: Tuple[int, int]) -> None:
        """
        Args:
            original_size: (width, height) of the captured image.
            max_display: (width, height) the preview must fit inside.
        """
        orig_w, orig_h = original_size
        if orig_w <= 0 or orig_h <= 0:
            raise ValueError(f"invalid image size {original_size}")

        max_w, max_h = max_display
        # Never scale up: a small window stays pixel-for-pixel.
        self.scale_factor = min(max_w / orig_w, max_h / orig_h, 1.0)
        self.original_size = (orig_w, orig_h)

    @property
    def display_size(self) -> Tuple[int, int]:
        """Preview dimensions in display pixels."""
        w, h = self.original_size
        if self.scale_factor >= 1.0:
            return (w, h)
        return (int(w * self.scale_factor), int(h * self.scale_factor))

    def to_original(self, rect: Rect) -> Tuple[int, int, int, int]:
        """Convert a display-space rect to an (x, y, width, height) crop."""
        r = rect.normalised()
        return (
            int(r.x1 / self.scale_factor),
            int(r.y1 / self.scale_factor),
            int(r.width / self.scale_factor),
            int(r.height / self.scale_factor),
        )

    def from_original(self, crop: Tuple[int, int, int, int]) -> Rect:
        """Convert an (x, y, width, height) crop to a display-space rect."""
        x, y, w, h = crop
        return Rect(
            int(x * self.scale_factor),
            int(y * self.scale_factor),
            int((x + w) * self.scale_factor),
            int((y + h) * self.scale_factor),
        )

    def default_rect(self, margin: float = 0.20) -> Rect:
        """A centred starting selection covering the middle of the preview."""
        w, h = self.display_size
        mx, my = int(w * margin), int(h * margin)
        return Rect(mx, my, w - mx, h - my)

    def clamp_to_display(self, x: int, y: int) -> Tuple[int, int]:
        """Clamp a pointer position to the preview area."""
        w, h = self.display_size
        return (max(0, min(x, w)), max(0, min(y, h)))

    def cell_size(self, rect: Rect, columns: int,
                  rows: int) -> Tuple[float, float]:
        """Character cell size in original pixels for a given selection.

        Shown in the dialog so the user can sanity-check the crop: cells much
        smaller than the glyphs mean the selection is too tight.
        """
        _, _, w, h = self.to_original(rect)
        return (w / columns, h / rows)
