"""
Region selection dialog for visually selecting the FMC/MCDU screen area.

Built on PySide6.  Shows a 24x14 grid overlay so the user can verify that cell
boundaries fall between characters rather than through them, and offers an
Auto Detect button backed by mcdu_detector.

All selection maths lives in region_geometry so it can be tested without a
running Qt application.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from region_geometry import Rect, RegionSelection

logger = logging.getLogger(__name__)


def numpy_to_qpixmap(image: np.ndarray) -> QPixmap:
    """Convert an RGB numpy array to a QPixmap.

    The QImage is copied because it does not take ownership of the numpy
    buffer, and the array may be freed while the pixmap is still on screen.
    """
    array = np.ascontiguousarray(image[:, :, :3])
    height, width, _ = array.shape
    qimage = QImage(array.data, width, height, 3 * width, QImage.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


class _SelectionCanvas(QWidget):
    """Displays the capture preview and handles the selection interaction."""

    GRID_COLS = 24
    GRID_ROWS = 14

    def __init__(self, pixmap: QPixmap, selection: RegionSelection,
                 rect: Rect, parent=None) -> None:
        super().__init__(parent)
        self.selection = selection
        self.rect_ = rect
        self.show_grid = True

        width, height = selection.display_size
        self._pixmap = pixmap.scaled(
            width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.setFixedSize(width, height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

        self._drag_origin: Optional[Tuple[int, int]] = None
        self._resize_corner: Optional[str] = None
        self._is_moving = False
        self._on_change = None

    def set_rect(self, rect: Rect) -> None:
        self.rect_ = rect
        self.update()
        if self._on_change:
            self._on_change(rect)

    def set_change_handler(self, handler) -> None:
        self._on_change = handler

    def set_grid_visible(self, visible: bool) -> None:
        self.show_grid = visible
        self.update()

    # ------------------------------------------------------------------
    #  Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:      # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)

        r = self.rect_.normalised()
        width, height = self.selection.display_size

        # Dim everything outside the selection.
        shade = QColor(0, 0, 0, 128)
        painter.fillRect(QRect(0, 0, width, r.y1), shade)
        painter.fillRect(QRect(0, r.y2, width, height - r.y2), shade)
        painter.fillRect(QRect(0, r.y1, r.x1, r.height), shade)
        painter.fillRect(QRect(r.x2, r.y1, width - r.x2, r.height), shade)

        # Character grid, so cell boundaries can be checked against glyphs.
        if self.show_grid and r.width > 20 and r.height > 20:
            painter.setPen(QPen(QColor(0, 255, 255, 90), 1))
            for c in range(1, self.GRID_COLS):
                gx = r.x1 + int(c * r.width / self.GRID_COLS)
                painter.drawLine(gx, r.y1, gx, r.y2)
            for row in range(1, self.GRID_ROWS):
                gy = r.y1 + int(row * r.height / self.GRID_ROWS)
                painter.drawLine(r.x1, gy, r.x2, gy)

        painter.setPen(QPen(QColor(255, 0, 0), 2))
        painter.drawRect(QRect(r.x1, r.y1, r.width, r.height))

        # Corner handles.
        handle = 8
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QColor(255, 0, 0))
        for cx, cy in ((r.x1, r.y1), (r.x2, r.y1), (r.x1, r.y2), (r.x2, r.y2)):
            painter.drawRect(QRect(cx - handle, cy - handle,
                                   handle * 2, handle * 2))
        painter.end()

    # ------------------------------------------------------------------
    #  Mouse interaction
    # ------------------------------------------------------------------
    @staticmethod
    def _pos(event) -> Tuple[int, int]:
        point: QPoint = event.position().toPoint()
        return point.x(), point.y()

    def mousePressEvent(self, event) -> None:     # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x, y = self._pos(event)

        corner = self.rect_.corner_at(x, y)
        if corner:
            self._resize_corner = corner
            self._drag_origin = (x, y)
            return

        if self.rect_.contains(x, y):
            self._is_moving = True
            self._drag_origin = (x, y)
            return

        # Start a brand-new selection.
        self._drag_origin = (x, y)
        self.set_rect(Rect(x, y, x, y))

    def mouseMoveEvent(self, event) -> None:      # noqa: N802
        x, y = self.selection.clamp_to_display(*self._pos(event))

        if self._drag_origin is None:
            self._update_cursor(x, y)
            return

        if self._resize_corner:
            self.set_rect(self.rect_.with_corner_at(self._resize_corner, x, y))
        elif self._is_moving:
            ox, oy = self._drag_origin
            self.set_rect(self.rect_.moved_by(
                x - ox, y - oy, self.selection.display_size,
            ))
            self._drag_origin = (x, y)
        else:
            ox, oy = self._drag_origin
            self.set_rect(Rect(ox, oy, x, y).normalised())

    def mouseReleaseEvent(self, event) -> None:   # noqa: N802
        self._drag_origin = None
        self._resize_corner = None
        self._is_moving = False

    def _update_cursor(self, x: int, y: int) -> None:
        corner = self.rect_.corner_at(x, y)
        if corner in ("nw", "se"):
            self.setCursor(Qt.SizeFDiagCursor)
        elif corner in ("ne", "sw"):
            self.setCursor(Qt.SizeBDiagCursor)
        elif self.rect_.contains(x, y):
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.CrossCursor)


class RegionSelectorDialog(QDialog):
    """Modal dialog returning an (x, y, width, height) crop, or None."""

    GRID_COLS = 24
    GRID_ROWS = 14

    MAX_DISPLAY_WIDTH = 850
    MAX_DISPLAY_HEIGHT = 550

    def __init__(self, parent, image: np.ndarray,
                 initial_region: Optional[Tuple[int, int, int, int]] = None):
        super().__init__(parent)
        self.setWindowTitle("Select FMC Screen Area")
        self.setModal(True)

        self.original_image = image
        self.result_region: Optional[Tuple[int, int, int, int]] = None

        height, width = image.shape[:2]
        self.selection = RegionSelection(
            (width, height),
            (self.MAX_DISPLAY_WIDTH, self.MAX_DISPLAY_HEIGHT),
        )

        rect = (self.selection.from_original(initial_region)
                if initial_region else self.selection.default_rect())

        self.canvas = _SelectionCanvas(
            numpy_to_qpixmap(image), self.selection, rect, self,
        )
        self.canvas.set_change_handler(self._on_rect_changed)

        self._build_ui()
        self._on_rect_changed(rect)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        instructions = QLabel(
            "Drag corners to tightly frame the MCDU text "
            "(exclude title bar and borders).\n"
            "The cyan grid shows where the 24x14 character cells will fall."
        )
        instructions.setAlignment(Qt.AlignCenter)
        layout.addWidget(instructions)

        canvas_row = QHBoxLayout()
        canvas_row.addStretch()
        canvas_row.addWidget(self.canvas)
        canvas_row.addStretch()
        layout.addLayout(canvas_row)

        self.coord_label = QLabel("Selection: Not set")
        layout.addWidget(self.coord_label)

        buttons = QHBoxLayout()
        for text, slot in (
            ("Auto Detect", self._on_auto_detect),
            ("Reset", self._on_reset),
            ("Cancel", self.reject),
            ("OK", self._on_ok),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)

        self.grid_checkbox = QCheckBox("Show 24x14 grid")
        self.grid_checkbox.setChecked(True)
        self.grid_checkbox.toggled.connect(self.canvas.set_grid_visible)
        buttons.addWidget(self.grid_checkbox)
        buttons.addStretch()

        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    #  Actions
    # ------------------------------------------------------------------
    def _on_rect_changed(self, rect: Rect) -> None:
        x, y, w, h = self.selection.to_original(rect)
        cell_w, cell_h = self.selection.cell_size(
            rect, self.GRID_COLS, self.GRID_ROWS,
        )
        self.coord_label.setText(
            f"X={x}  Y={y}  W={w}  H={h}  |  "
            f"Cell: {cell_w:.1f} x {cell_h:.1f} px"
        )
        self.coord_label.setStyleSheet("")

    def _on_reset(self) -> None:
        self.canvas.set_rect(self.selection.default_rect())

    def _on_auto_detect(self) -> None:
        """Run automatic MCDU region detection on the captured image."""
        try:
            from mcdu_detector import detect_mcdu_region
        except ImportError:
            logger.warning("mcdu_detector module not available")
            return

        result = detect_mcdu_region(
            self.original_image, self.GRID_COLS, self.GRID_ROWS,
        )
        if result is None:
            self.coord_label.setText(
                "Auto-detect failed - no MCDU region found. Adjust manually."
            )
            self.coord_label.setStyleSheet("color: red;")
            logger.info("Auto-detect did not find an MCDU region")
            return

        x, y, w, h = result
        self.canvas.set_rect(self.selection.from_original(result))
        self.coord_label.setStyleSheet("color: green;")
        logger.info("Auto-detect set region: x=%d y=%d w=%d h=%d", x, y, w, h)

    def _on_ok(self) -> None:
        self.result_region = self.selection.to_original(self.canvas.rect_)
        self.accept()

    def show(self) -> Optional[Tuple[int, int, int, int]]:
        """Run the dialog modally and return the chosen crop, or None."""
        if self.exec() == QDialog.Accepted:
            return self.result_region
        return None
