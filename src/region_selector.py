"""
Region selection dialog for visually selecting FMC/MCDU screen area
"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
import numpy as np
from typing import Optional, Tuple


class RegionSelectorDialog:
    """
    Dialog for visually selecting a region within an image
    Allows user to drag and resize a selection box
    """
    
    def __init__(self, parent, image: np.ndarray, initial_region: Optional[Tuple[int, int, int, int]] = None):
        """
        Initialize region selector
        
        Args:
            parent: Parent window
            image: Image as numpy array (RGB)
            initial_region: Optional initial selection (x, y, width, height)
        """
        self.parent = parent
        self.original_image = Image.fromarray(image)
        self.result = None
        
        # Create dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Select FMC Screen Area")
        self.dialog.geometry("900x700")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Scale image to fit display
        self.max_display_width = 850
        self.max_display_height = 550
        self.scale_factor = self._calculate_scale_factor()
        self.display_image = self._scale_image(self.original_image)
        
        # Selection state
        self.selection_start = None
        self.selection_rect = None
        self.is_dragging = False
        self.is_resizing = False
        self.resize_corner = None
        
        # Initialize selection region
        if initial_region:
            x, y, w, h = initial_region
            # Scale initial region to display coordinates
            self.selection_rect = (
                int(x * self.scale_factor),
                int(y * self.scale_factor),
                int((x + w) * self.scale_factor),
                int((y + h) * self.scale_factor)
            )
        else:
            # Default to centered selection (25% of image)
            img_w, img_h = self.display_image.size
            margin_x, margin_y = img_w // 4, img_h // 4
            self.selection_rect = (margin_x, margin_y, img_w - margin_x, img_h - margin_y)
        
        # Create UI
        self._create_widgets()
        
        # Update display
        self._update_canvas()
    
    def _calculate_scale_factor(self) -> float:
        """Calculate scale factor to fit image in display area"""
        img_w, img_h = self.original_image.size
        scale_w = self.max_display_width / img_w
        scale_h = self.max_display_height / img_h
        return min(scale_w, scale_h, 1.0)  # Don't upscale
    
    def _scale_image(self, image: Image.Image) -> Image.Image:
        """Scale image for display"""
        if self.scale_factor < 1.0:
            new_size = (
                int(image.width * self.scale_factor),
                int(image.height * self.scale_factor)
            )
            return image.resize(new_size, Image.Resampling.LANCZOS)
        return image
    
    def _create_widgets(self):
        """Create dialog widgets"""
        # Instructions
        instructions = ttk.Label(
            self.dialog,
            text="Drag to select the FMC screen area. Drag corners to resize. Click OK when done.",
            font=('Arial', 10)
        )
        instructions.pack(pady=10)
        
        # Canvas frame
        canvas_frame = ttk.Frame(self.dialog)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Canvas with scrollbars
        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.display_image.width,
            height=self.display_image.height,
            cursor="crosshair"
        )
        self.canvas.pack()
        
        # Bind mouse events
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)
        
        # Info frame
        info_frame = ttk.Frame(self.dialog)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Coordinates display
        self.coord_label = ttk.Label(info_frame, text="Selection: Not set", font=('Arial', 9))
        self.coord_label.pack(side=tk.LEFT)
        
        # Buttons
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="OK", command=self._on_ok, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Reset", command=self._on_reset, width=15).pack(side=tk.LEFT, padx=5)
    
    def _update_canvas(self):
        """Update canvas with image and selection rectangle"""
        # Create a copy of the display image
        img = self.display_image.copy()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        if self.selection_rect:
            x1, y1, x2, y2 = self.selection_rect
            
            # Draw semi-transparent overlay outside selection
            # Top
            if y1 > 0:
                draw.rectangle([0, 0, img.width, y1], fill=(0, 0, 0, 128))
            # Bottom
            if y2 < img.height:
                draw.rectangle([0, y2, img.width, img.height], fill=(0, 0, 0, 128))
            # Left
            draw.rectangle([0, y1, x1, y2], fill=(0, 0, 0, 128))
            # Right
            draw.rectangle([x2, y1, img.width, y2], fill=(0, 0, 0, 128))
            
            # Draw selection rectangle border
            draw.rectangle([x1, y1, x2, y2], outline='red', width=2)
            
            # Draw corner handles
            handle_size = 8
            for cx, cy in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                draw.rectangle(
                    [cx - handle_size, cy - handle_size, cx + handle_size, cy + handle_size],
                    fill='red',
                    outline='white',
                    width=1
                )
        
        # Update canvas
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        
        # Update coordinates label
        if self.selection_rect:
            x1, y1, x2, y2 = self.selection_rect
            # Convert to original image coordinates
            orig_x1 = int(x1 / self.scale_factor)
            orig_y1 = int(y1 / self.scale_factor)
            orig_w = int((x2 - x1) / self.scale_factor)
            orig_h = int((y2 - y1) / self.scale_factor)
            self.coord_label.config(
                text=f"Selection: X={orig_x1}, Y={orig_y1}, Width={orig_w}, Height={orig_h}"
            )
    
    def _get_corner_at(self, x: int, y: int) -> Optional[str]:
        """Check if click is on a corner handle"""
        if not self.selection_rect:
            return None
        
        x1, y1, x2, y2 = self.selection_rect
        handle_size = 10
        
        corners = {
            'nw': (x1, y1),
            'ne': (x2, y1),
            'sw': (x1, y2),
            'se': (x2, y2)
        }
        
        for corner, (cx, cy) in corners.items():
            if abs(x - cx) <= handle_size and abs(y - cy) <= handle_size:
                return corner
        
        return None
    
    def _is_inside_selection(self, x: int, y: int) -> bool:
        """Check if point is inside selection"""
        if not self.selection_rect:
            return False
        
        x1, y1, x2, y2 = self.selection_rect
        return x1 < x < x2 and y1 < y < y2
    
    def _on_mouse_down(self, event):
        """Handle mouse button press"""
        # Check if clicking on corner
        corner = self._get_corner_at(event.x, event.y)
        if corner:
            self.is_resizing = True
            self.resize_corner = corner
            self.selection_start = (event.x, event.y)
            return
        
        # Check if clicking inside selection
        if self._is_inside_selection(event.x, event.y):
            self.is_dragging = True
            self.selection_start = (event.x, event.y)
            return
        
        # Start new selection
        self.selection_start = (event.x, event.y)
        self.selection_rect = None
    
    def _on_mouse_drag(self, event):
        """Handle mouse drag"""
        if not self.selection_start:
            return
        
        # Constrain to canvas bounds
        x = max(0, min(event.x, self.display_image.width))
        y = max(0, min(event.y, self.display_image.height))
        
        if self.is_resizing and self.resize_corner:
            # Resize selection
            x1, y1, x2, y2 = self.selection_rect
            
            if self.resize_corner == 'nw':
                x1, y1 = x, y
            elif self.resize_corner == 'ne':
                x2, y1 = x, y
            elif self.resize_corner == 'sw':
                x1, y2 = x, y
            elif self.resize_corner == 'se':
                x2, y2 = x, y
            
            # Normalize rectangle first (handle inverted rectangles)
            normalized_x1 = min(x1, x2)
            normalized_y1 = min(y1, y2)
            normalized_x2 = max(x1, x2)
            normalized_y2 = max(y1, y2)
            
            # Ensure valid rectangle (min size 20x20)
            if normalized_x2 - normalized_x1 >= 20 and normalized_y2 - normalized_y1 >= 20:
                self.selection_rect = (normalized_x1, normalized_y1, normalized_x2, normalized_y2)
                self._update_canvas()
        
        elif self.is_dragging:
            # Move selection
            dx = x - self.selection_start[0]
            dy = y - self.selection_start[1]
            
            x1, y1, x2, y2 = self.selection_rect
            width = x2 - x1
            height = y2 - y1
            
            # New position
            new_x1 = x1 + dx
            new_y1 = y1 + dy
            new_x2 = new_x1 + width
            new_y2 = new_y1 + height
            
            # Constrain to canvas
            if new_x1 >= 0 and new_x2 <= self.display_image.width:
                x1, x2 = new_x1, new_x2
            if new_y1 >= 0 and new_y2 <= self.display_image.height:
                y1, y2 = new_y1, new_y2
            
            self.selection_rect = (x1, y1, x2, y2)
            self.selection_start = (x, y)
            self._update_canvas()
        
        else:
            # Draw new selection
            x1, y1 = self.selection_start
            self.selection_rect = (min(x1, x), min(y1, y), max(x1, x), max(y1, y))
            self._update_canvas()
    
    def _on_mouse_up(self, event):
        """Handle mouse button release"""
        self.is_dragging = False
        self.is_resizing = False
        self.resize_corner = None
    
    def _on_mouse_move(self, event):
        """Handle mouse move (for cursor changes)"""
        if self.is_dragging or self.is_resizing:
            return
        
        corner = self._get_corner_at(event.x, event.y)
        if corner:
            # Change cursor for resize
            if corner in ['nw', 'se']:
                self.canvas.config(cursor="nwse-resize")
            else:
                self.canvas.config(cursor="nesw-resize")
        elif self._is_inside_selection(event.x, event.y):
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="crosshair")
    
    def _on_reset(self):
        """Reset selection to default"""
        img_w, img_h = self.display_image.size
        margin_x, margin_y = img_w // 4, img_h // 4
        self.selection_rect = (margin_x, margin_y, img_w - margin_x, img_h - margin_y)
        self._update_canvas()
    
    def _on_ok(self):
        """Accept selection and close"""
        if self.selection_rect:
            x1, y1, x2, y2 = self.selection_rect
            # Convert to original image coordinates
            self.result = (
                int(x1 / self.scale_factor),
                int(y1 / self.scale_factor),
                int((x2 - x1) / self.scale_factor),
                int((y2 - y1) / self.scale_factor)
            )
        self.dialog.destroy()
    
    def _on_cancel(self):
        """Cancel and close"""
        self.result = None
        self.dialog.destroy()
    
    def show(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Show dialog and return selected region
        
        Returns:
            Tuple of (x, y, width, height) or None if cancelled
        """
        self.dialog.wait_window()
        return self.result
