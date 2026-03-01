"""
Region selection dialog for visually selecting FMC/MCDU screen area.

Includes an **Auto Detect** button that uses ``mcdu_detector`` to find
the MCDU text grid automatically.
"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
import numpy as np
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class RegionSelectorDialog:
    """
    Dialog for visually selecting the MCDU text area within a captured window.
    Shows a 24x14 grid overlay so the user can verify cell alignment.
    The parser handles any selection size via cv2.resize — no snapping needed.
    """

    GRID_COLS = 24
    GRID_ROWS = 14

    def __init__(self, parent, image: np.ndarray, initial_region: Optional[Tuple[int, int, int, int]] = None):
        self.parent = parent
        self.original_image = Image.fromarray(image)
        self.result = None
        self.show_grid = True

        # Create dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Select FMC Screen Area")
        self.dialog.geometry("900x700")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Scale image to fit display area
        self.max_display_width = 850
        self.max_display_height = 550
        self.scale_factor = self._calculate_scale_factor()
        self.display_image = self._scale_image(self.original_image)

        # Selection state (display coordinates: x1, y1, x2, y2)
        self.selection_start = None
        self.selection_rect = None
        self.is_dragging = False
        self.is_resizing = False
        self.resize_corner = None

        # Initialize selection region
        if initial_region:
            x, y, w, h = initial_region
            self.selection_rect = (
                int(x * self.scale_factor),
                int(y * self.scale_factor),
                int((x + w) * self.scale_factor),
                int((y + h) * self.scale_factor),
            )
        else:
            # Default: centered 60% of the image
            img_w, img_h = self.display_image.size
            mx = int(img_w * 0.20)
            my = int(img_h * 0.20)
            self.selection_rect = (mx, my, img_w - mx, img_h - my)

        # Build UI
        self._create_widgets()
        self._update_canvas()

    # ------------------------------------------------------------------
    # Scaling helpers
    # ------------------------------------------------------------------
    def _calculate_scale_factor(self) -> float:
        img_w, img_h = self.original_image.size
        scale_w = self.max_display_width / img_w
        scale_h = self.max_display_height / img_h
        return min(scale_w, scale_h, 1.0)

    def _scale_image(self, image: Image.Image) -> Image.Image:
        if self.scale_factor < 1.0:
            new_size = (
                int(image.width * self.scale_factor),
                int(image.height * self.scale_factor),
            )
            return image.resize(new_size, Image.Resampling.LANCZOS)
        return image

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _create_widgets(self):
        instructions = ttk.Label(
            self.dialog,
            text=(
                "Drag corners to tightly frame the MCDU text (exclude title bar & borders).\n"
                "The cyan grid shows where the 24x14 character cells will be."
            ),
            font=("Arial", 10),
            justify="center",
        )
        instructions.pack(pady=10)

        canvas_frame = ttk.Frame(self.dialog)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.display_image.width,
            height=self.display_image.height,
            cursor="crosshair",
        )
        self.canvas.pack()

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)

        info_frame = ttk.Frame(self.dialog)
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        self.coord_label = ttk.Label(info_frame, text="Selection: Not set", font=("Arial", 9))
        self.coord_label.pack(side=tk.LEFT)

        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(pady=10)

        ttk.Button(button_frame, text="Auto Detect", command=self._on_auto_detect, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="OK", command=self._on_ok, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Reset", command=self._on_reset, width=15).pack(side=tk.LEFT, padx=5)

        self.grid_var = tk.BooleanVar(value=self.show_grid)
        ttk.Checkbutton(
            button_frame,
            text="Show 24x14 grid",
            variable=self.grid_var,
            command=self._toggle_grid,
        ).pack(side=tk.LEFT, padx=10)

    # ------------------------------------------------------------------
    # Canvas rendering
    # ------------------------------------------------------------------
    def _update_canvas(self):
        img = self.display_image.copy()
        draw = ImageDraw.Draw(img, "RGBA")

        if self.selection_rect:
            x1, y1, x2, y2 = self._int_rect()

            # Dim area outside selection
            if y1 > 0:
                draw.rectangle([0, 0, img.width, y1], fill=(0, 0, 0, 128))
            if y2 < img.height:
                draw.rectangle([0, y2, img.width, img.height], fill=(0, 0, 0, 128))
            draw.rectangle([0, y1, x1, y2], fill=(0, 0, 0, 128))
            draw.rectangle([x2, y1, img.width, y2], fill=(0, 0, 0, 128))

            # Border
            draw.rectangle([x1, y1, x2, y2], outline="red", width=2)

            # Grid overlay
            if self.show_grid:
                sel_w = x2 - x1
                sel_h = y2 - y1
                if sel_w > 20 and sel_h > 20:
                    for c in range(1, self.GRID_COLS):
                        gx = x1 + int(c * sel_w / self.GRID_COLS)
                        draw.line([(gx, y1), (gx, y2)], fill=(0, 255, 255, 80), width=1)
                    for r in range(1, self.GRID_ROWS):
                        gy = y1 + int(r * sel_h / self.GRID_ROWS)
                        draw.line([(x1, gy), (x2, gy)], fill=(0, 255, 255, 80), width=1)

            # Corner handles
            hs = 8
            for cx, cy in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                draw.rectangle([cx - hs, cy - hs, cx + hs, cy + hs], fill="red", outline="white", width=1)

        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # Update label with selection info and cell size
        if self.selection_rect:
            x1, y1, x2, y2 = self.selection_rect
            ow = int((x2 - x1) / self.scale_factor)
            oh = int((y2 - y1) / self.scale_factor)
            ox = int(x1 / self.scale_factor)
            oy = int(y1 / self.scale_factor)
            cell_w = ow / self.GRID_COLS
            cell_h = oh / self.GRID_ROWS
            self.coord_label.config(
                text=(
                    f"X={ox}  Y={oy}  W={ow}  H={oh}  |  "
                    f"Cell: {cell_w:.1f} x {cell_h:.1f} px"
                )
            )

    def _int_rect(self):
        x1, y1, x2, y2 = self.selection_rect
        return int(x1), int(y1), int(x2), int(y2)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------
    def _get_corner_at(self, x: int, y: int) -> Optional[str]:
        if not self.selection_rect:
            return None
        x1, y1, x2, y2 = self._int_rect()
        hs = 12
        corners = {"nw": (x1, y1), "ne": (x2, y1), "sw": (x1, y2), "se": (x2, y2)}
        for corner, (cx, cy) in corners.items():
            if abs(x - cx) <= hs and abs(y - cy) <= hs:
                return corner
        return None

    def _is_inside_selection(self, x: int, y: int) -> bool:
        if not self.selection_rect:
            return False
        x1, y1, x2, y2 = self._int_rect()
        return x1 < x < x2 and y1 < y < y2

    def _on_mouse_down(self, event):
        corner = self._get_corner_at(event.x, event.y)
        if corner:
            self.is_resizing = True
            self.resize_corner = corner
            self.selection_start = (event.x, event.y)
            return
        if self._is_inside_selection(event.x, event.y):
            self.is_dragging = True
            self.selection_start = (event.x, event.y)
            return
        self.selection_start = (event.x, event.y)
        self.selection_rect = None

    def _on_mouse_drag(self, event):
        if not self.selection_start:
            return
        x = max(0, min(event.x, self.display_image.width))
        y = max(0, min(event.y, self.display_image.height))

        if self.is_resizing and self.resize_corner:
            x1, y1, x2, y2 = self.selection_rect
            if self.resize_corner == "nw":
                x1, y1 = x, y
            elif self.resize_corner == "ne":
                x2, y1 = x, y
            elif self.resize_corner == "sw":
                x1, y2 = x, y
            elif self.resize_corner == "se":
                x2, y2 = x, y
            nx1, ny1 = min(x1, x2), min(y1, y2)
            nx2, ny2 = max(x1, x2), max(y1, y2)
            if nx2 - nx1 >= 20 and ny2 - ny1 >= 20:
                self.selection_rect = (nx1, ny1, nx2, ny2)
                self._update_canvas()

        elif self.is_dragging:
            dx = x - self.selection_start[0]
            dy = y - self.selection_start[1]
            x1, y1, x2, y2 = self.selection_rect
            w, h = x2 - x1, y2 - y1
            nx1, ny1 = x1 + dx, y1 + dy
            nx2, ny2 = nx1 + w, ny1 + h
            if 0 <= nx1 and nx2 <= self.display_image.width:
                x1, x2 = nx1, nx2
            if 0 <= ny1 and ny2 <= self.display_image.height:
                y1, y2 = ny1, ny2
            self.selection_rect = (x1, y1, x2, y2)
            self.selection_start = (x, y)
            self._update_canvas()

        else:
            sx, sy = self.selection_start
            self.selection_rect = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))
            self._update_canvas()

    def _on_mouse_up(self, event):
        self.is_dragging = False
        self.is_resizing = False
        self.resize_corner = None

    def _on_mouse_move(self, event):
        if self.is_dragging or self.is_resizing:
            return
        corner = self._get_corner_at(event.x, event.y)
        if corner:
            self.canvas.config(cursor="top_left_corner" if corner in ("nw", "se") else "top_right_corner")
        elif self._is_inside_selection(event.x, event.y):
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="crosshair")

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------
    def _toggle_grid(self):
        self.show_grid = self.grid_var.get()
        self._update_canvas()

    def _on_reset(self):
        img_w, img_h = self.display_image.size
        mx = int(img_w * 0.20)
        my = int(img_h * 0.20)
        self.selection_rect = (mx, my, img_w - mx, img_h - my)
        self._update_canvas()

    def _on_auto_detect(self):
        """Run automatic MCDU region detection on the captured image."""
        try:
            from mcdu_detector import detect_mcdu_region
        except ImportError:
            logger.warning("mcdu_detector module not available")
            return

        img_array = np.array(self.original_image)
        result = detect_mcdu_region(img_array, self.GRID_COLS, self.GRID_ROWS)

        if result is None:
            # Show message in the coord label
            self.coord_label.config(
                text="Auto-detect failed — no MCDU region found.  "
                     "Adjust manually.",
                foreground="red",
            )
            logger.info("Auto-detect did not find an MCDU region")
            return

        x, y, w, h = result
        # Convert original-image coords → display coords
        self.selection_rect = (
            int(x * self.scale_factor),
            int(y * self.scale_factor),
            int((x + w) * self.scale_factor),
            int((y + h) * self.scale_factor),
        )
        self._update_canvas()
        self.coord_label.config(foreground="green")
        logger.info("Auto-detect set region: x=%d y=%d w=%d h=%d", x, y, w, h)

    def _on_ok(self):
        if self.selection_rect:
            x1, y1, x2, y2 = self.selection_rect
            self.result = (
                int(x1 / self.scale_factor),
                int(y1 / self.scale_factor),
                int((x2 - x1) / self.scale_factor),
                int((y2 - y1) / self.scale_factor),
            )
        self.dialog.destroy()

    def _on_cancel(self):
        self.result = None
        self.dialog.destroy()

    def show(self) -> Optional[Tuple[int, int, int, int]]:
        self.dialog.wait_window()
        return self.result
