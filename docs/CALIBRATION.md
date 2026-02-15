# Screen Calibration Guide

This guide will help you accurately calibrate the screen region coordinates for capturing the MCDU display.

## Understanding Screen Capture

**How it works**: The scraper takes continuous screenshots of a specific rectangular area of your screen. It needs to know:
- **Which monitor** to capture from
- **Where on that monitor** the MCDU is located
- **How big** the MCDU area is

**Important**: The scraper doesn't "know" where your MCDU is - you must tell it the exact pixel coordinates.

## 2D Panel vs Pop-Out MCDU

### Using 2D Cockpit Panel
The MCDU is displayed within your normal cockpit view:
- **Pros**: No extra windows to manage
- **Cons**: Position changes if you move camera or adjust view
- **Best for**: Single static camera angle

### Using Pop-Out MCDU (Recommended)
Right-click MCDU → "Pop Out" creates a separate window:
- **Pros**: Consistent position, doesn't move with camera
- **Cons**: Extra window to manage
- **Best for**: Reliability and ease of setup
- **Tip**: Position pop-out window in a consistent spot (e.g., top-left of secondary monitor)

## Why Calibration is Important

The scraper needs to know exactly where your MCDU is displayed on screen to capture it correctly. Wrong coordinates will result in:
- Capturing wrong area
- Black/empty display on WinWing CDU
- Incorrect character detection

## Methods

### Method 1: Using Windows Snipping Tool (Easiest)

1. **Start MSFS** with Airbus A330
2. **Display MCDU** on screen (either 2D panel or pop-out)
3. **Press** `Win + Shift + S` to open Snipping Tool
4. **Select** the MCDU area (try to be precise)
5. **Open** the screenshot in Paint or image editor
6. **Note** the image dimensions (shown in bottom-right)
   - Width and Height are your `width` and `height` values

7. **Find top-left corner**:
   - Take a screenshot of entire screen
   - Open in Paint
   - Hover mouse over top-left corner of MCDU
   - Note coordinates shown in bottom-left (X, Y)
   - X = `left`, Y = `top`

### Method 2: Using PowerToys (More Accurate)

1. **Install PowerToys** from Microsoft Store or GitHub
2. **Enable Screen Ruler** in PowerToys settings
3. **Activate** with `Win + Shift + M`
4. **Measure** the MCDU region:
   - Click top-left corner of MCDU
   - Drag to bottom-right corner
   - Note dimensions and position

### Method 3: Using Python Script

Create a helper script to find coordinates interactively:

```python
# calibration_helper.py
import mss
import numpy as np
from PIL import Image, ImageDraw
import tkinter as tk
from tkinter import messagebox

def capture_screen():
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # Primary monitor
        screenshot = sct.grab(monitor)
        img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
        return img

def on_click(event):
    global clicks
    clicks.append((event.x, event.y))
    print(f"Click {len(clicks)}: ({event.x}, {event.y})")
    
    if len(clicks) == 2:
        x1, y1 = clicks[0]
        x2, y2 = clicks[1]
        
        top = min(y1, y2)
        left = min(x1, x2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        
        config = f"""
Screen Region Configuration:
----------------------------
top: {top}
left: {left}
width: {width}
height: {height}

Copy this to your config.yaml:
----------------------------
screen_region:
  top: {top}
  left: {left}
  width: {width}
  height: {height}
        """
        
        print(config)
        messagebox.showinfo("Calibration Complete", config)
        root.quit()

print("Instructions:")
print("1. Click on the TOP-LEFT corner of the MCDU")
print("2. Click on the BOTTOM-RIGHT corner of the MCDU")
print()

clicks = []

# Capture screen
img = capture_screen()

# Create window
root = tk.Tk()
root.title("MCDU Calibration - Click Top-Left then Bottom-Right")

# Display image
photo = ImageTk.PhotoImage(img)
label = tk.Label(root, image=photo)
label.pack()

# Bind click event
label.bind("<Button-1>", on_click)

root.mainloop()
```

Run it:
```bash
pip install pillow mss
python calibration_helper.py
```

## Testing Your Calibration

### Quick Test

Create a test script:

```python
# test_capture.py
import mss
from PIL import Image

# Your configuration
region = {
    "top": 400,
    "left": 800,
    "width": 480,
    "height": 280
}

with mss.mss() as sct:
    screenshot = sct.grab(region)
    img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
    img.save('test_capture.png')
    print("Screenshot saved as test_capture.png")
    print("Open it and verify it shows only the MCDU")
```

Run and check output:
```bash
python test_capture.py
# Open test_capture.png
```

The image should show:
- ✓ Only the MCDU content
- ✓ No borders or surrounding UI
- ✓ Full MCDU visible (24 columns, 14 rows)
- ✗ Not: Black areas, cut-off text, or other UI elements

## Configuration Examples

### Single Monitor Setup (1920x1080)

MCDU in center:
```yaml
screen_region:
  top: 340       # (1080-280)/2 - some offset
  left: 720      # (1920-480)/2
  width: 480
  height: 280
```

### Dual Monitor Setup

Primary monitor (MSFS):
```yaml
captain:
  screen_region:
    top: 400
    left: 800
    width: 480
    height: 280
```

Secondary monitor (pop-out MCDU):
```yaml
captain:
  screen_region:
    top: 400
    left: 1920    # Primary monitor width + offset
    width: 480
    height: 280
```

### Ultra-wide Monitor (3440x1440)

MCDU on left:
```yaml
screen_region:
  top: 580       # (1440-280)/2
  left: 500
  width: 480
  height: 280
```

MCDU on right:
```yaml
screen_region:
  top: 580
  left: 2460     # 3440 - 480 - 500
  width: 480
  height: 280
```

## Fine-tuning

### If Characters Are Cut Off

The region is too small or offset:

1. **Increase margins**: Add 10-20 pixels to width/height
2. **Adjust offset**: Move top/left by small amounts
3. **Test**: Run test_capture.py after each change

### If Extra UI Elements Appear

The region is too large:

1. **Reduce size**: Decrease width/height by 10-20 pixels
2. **Adjust position**: Fine-tune top/left
3. **Test**: Verify only MCDU is captured

### If MCDU Moves

If MSFS window position changes:

1. **Lock window position**: Keep MSFS maximized or same position
2. **Update config**: Recalibrate if you change window size
3. **Consider**: Using pop-out MCDU for consistent position

## Tips for Best Results

### 1. MCDU Visibility

- Use pop-out MCDU window for easier positioning
- Ensure MCDU is fully visible (not obscured)
- Avoid overlapping windows

### 2. Display Settings

- Use native resolution (no scaling)
- Disable HDR if it causes issues
- Set brightness to comfortable level

### 3. MSFS Settings

- Use borderless windowed or fullscreen
- Consistent window size between sessions
- Lock toolbar positions

### 4. Precision

- Be as precise as possible with coordinates
- Test after calibration
- Re-calibrate if you change monitor setup

## Common Screen Regions

Based on common setups:

### 1920x1080 Fullscreen
```yaml
# MCDU typically appears here in A330
top: 400
left: 800
width: 480
height: 280
```

### 2560x1440 Fullscreen
```yaml
top: 550
left: 1040
width: 480
height: 280
```

### Pop-out Window
```yaml
# Position window at top-left of secondary monitor
top: 0
left: 1920
width: 480
height: 280
```

## Verification Checklist

Before running the main application:

- [ ] Screen capture shows only MCDU
- [ ] All 14 rows visible
- [ ] All 24 columns visible
- [ ] No borders or UI elements
- [ ] Text is clear and readable
- [ ] Colors look correct

If all checks pass, your calibration is correct!

## Troubleshooting

### Black Screen Captured

**Cause**: Wrong monitor selected or incorrect coordinates

**Fix**:
- Verify MCDU is on primary monitor (monitor 1)
- Check coordinates are positive
- Ensure region is within monitor bounds

### Partial MCDU

**Cause**: Region too small or offset

**Fix**:
- Increase width/height
- Adjust top/left to center on MCDU

### Wrong Area Captured

**Cause**: Coordinates swapped or incorrect

**Fix**:
- Verify top = Y coordinate, left = X coordinate
- Check you're using top-left corner, not center
- Re-measure carefully

### Capture Changes After Reboot

**Cause**: MSFS window position changed

**Fix**:
- Always start MSFS in same position
- Use fullscreen or borderless window
- Or use pop-out MCDU at fixed position

## Next Steps

After successful calibration:

1. Test with the main application
2. Verify characters appear on WinWing CDU
3. Check colors are correct
4. Fine-tune if needed

---

**Pro Tip**: Save multiple configurations for different setups (VR, TrackIR, monitors) as separate YAML files and switch between them.
