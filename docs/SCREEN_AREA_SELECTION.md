# Screen Area Selection Feature

Visual guide for the FMC/MCDU Screen Area Selection feature.

## Overview

The Screen Area Selection feature allows you to visually define which part of a captured window contains the actual MCDU screen, excluding borders, title bars, and other UI elements.

## When to Use

- **MCDU pop-out windows** include window borders and title bars
- You want to capture **only the MCDU screen**, not window decorations
- You need **precise control** over what gets captured
- Window size may vary between sessions

## Visual Example

### Before Screen Area Selection

```
┌─────────────────────────────────────────────┐
│  MCDU - Microsoft Flight Simulator    [_][□][X]│ ← Title bar (not needed)
├─────────────────────────────────────────────┤
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ ← Border
│░░  ┌───────────────────────────────┐  ░░│
│░░  │                               │  ░░│ ← Borders (not needed)
│░░  │     MCDU SCREEN CONTENT      │  ░░│
│░░  │     (This is what we want)   │  ░░│
│░░  │                               │  ░░│
│░░  └───────────────────────────────┘  ░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
└─────────────────────────────────────────────┘

Captures ENTIRE window (500x300 pixels)
Including: title bar, borders, decorations
```

### After Screen Area Selection

```
┌─────────────────────────────────────────────┐
│  MCDU - Microsoft Flight Simulator    [_][□][X]│
├─────────────────────────────────────────────┤
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← Darkened (excluded)
│▓▓  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  ▓▓│
│▓▓  ┃                             ┃  ▓▓│ ← RED SELECTION BOX
│▓▓  ┃     MCDU SCREEN CONTENT    ┃  ▓▓│
│▓▓  ┃     (Selected for capture) ┃  ▓▓│
│▓▓  ┃                             ┃  ▓▓│
│▓▓  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛  ▓▓│
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
└─────────────────────────────────────────────┘

Captures ONLY selected area (480x280 pixels)
Excludes: title bar, borders, decorations
```

## Selection Dialog Interface

```
┌──────────────────────────────────────────────────────────────┐
│  Select FMC Screen Area                              [_][□][X]│
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  Drag to select the FMC screen area. Drag corners to         │
│  resize. Click OK when done.                                  │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────┐  │
│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │
│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │
│  │▓▓  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  ▓▓│  │
│  │▓▓  ┃ ■                                       ┃  ▓▓│  │
│  │▓▓  ┃                                         ┃  ▓▓│  │
│  │▓▓  ┃          MCDU SCREEN                   ┃  ▓▓│  │
│  │▓▓  ┃          PREVIEW                        ┃  ▓▓│  │
│  │▓▓  ┃                                         ┃  ▓▓│  │
│  │▓▓  ┃                                       ■ ┃  ▓▓│  │
│  │▓▓  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛  ▓▓│  │
│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │
│  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                │
│  Selection: X=20, Y=30, Width=460, Height=240                │
│                                                                │
│  [   OK   ]  [  Cancel  ]  [  Reset  ]                       │
│                                                                │
└──────────────────────────────────────────────────────────────┘

Legend:
  ▓ = Semi-transparent dark overlay (excluded area)
  ━ = Red selection border
  ■ = Red corner handles (drag to resize)
```

## Interactive Elements

### Selection Box
- **Red border** shows the selected area
- **Drag anywhere inside** to move the selection
- **Drag corner handles (■)** to resize
- **Real-time coordinate display** at bottom

### Overlay
- **Dark semi-transparent** overlay outside selection
- Makes it easy to see what will be excluded
- Selected area remains clear and visible

### Cursor Changes
- **Crosshair** (✛) - Default, ready to select
- **Move** (✥) - When hovering inside selection
- **Resize** (⤡⤢) - When hovering over corners

## Usage Workflow

```
Step 1: Click "Select Screen Area" button
         ↓
Step 2: Preview window opens with full window capture
         ↓
Step 3: Drag selection box to frame MCDU screen
         │
         ├─→ Drag inside box to move position
         └─→ Drag corners to resize
         ↓
Step 4: Verify coordinates at bottom
         ↓
Step 5: Click OK to save
         ↓
Step 6: Crop region displayed in main GUI (green text)
         ↓
Step 7: Start scraper - only selected area is captured!
```

## Main GUI Integration

### Before Selection

```
┌─ Window Selection ──────────────────────────────────┐
│                                                      │
│ Select MCDU Window:                                  │
│ [MCDU - Microsoft Flight Simulator  ▼] [Refresh]   │
│                                                      │
│                    [Select Screen Area]              │
│ No crop region set                                   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### After Selection

```
┌─ Window Selection ──────────────────────────────────┐
│                                                      │
│ Select MCDU Window:                                  │
│ [MCDU - Microsoft Flight Simulator  ▼] [Refresh]   │
│                                                      │
│                    [Select Screen Area]              │
│ Crop: X=20, Y=30, W=460, H=240  ✓                  │
│       └─ Green text indicates active crop           │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## Common Use Cases

### Use Case 1: Remove Window Borders

**Problem**: MCDU pop-out window has 10-pixel borders on all sides

**Solution**:
1. Open "Select Screen Area"
2. Adjust selection to exclude borders
3. Result: Clean MCDU screen capture without decorations

**Before**: 500x300 window → **After**: 480x280 screen

### Use Case 2: Multiple MCDU Sizes

**Problem**: Sometimes pop-out is large, sometimes small

**Solution**:
1. Select screen area for current window size
2. If window size changes, re-select
3. Each selection saves the crop for that configuration

### Use Case 3: Exclude Title Bar

**Problem**: Title bar interferes with capture

**Solution**:
1. Select area starting below title bar
2. Frame only the MCDU display portion
3. Title bar is automatically excluded

## Tips and Best Practices

### ✅ DO

- **Use this feature** for all window-based captures
- **Frame precisely** - align selection with MCDU screen edges
- **Check the preview** - verify selection looks correct
- **Save coordinates** - note them for future reference
- **Re-select if needed** - window size changes require new selection

### ❌ DON'T

- Don't include window borders in selection
- Don't include title bar
- Don't rush - take time to align precisely
- Don't forget to click OK to save
- Don't select outside the window bounds

## Keyboard Shortcuts (Future)

Currently not implemented, but planned:
- **Arrow keys** - Move selection by 1 pixel
- **Shift+Arrow** - Resize by 1 pixel
- **Ctrl+A** - Select all
- **Escape** - Cancel
- **Enter** - Accept

## Technical Details

### Coordinates

Selection coordinates are relative to the captured window:
- **X**: Pixels from left edge of window
- **Y**: Pixels from top edge of window
- **Width**: Width of selection in pixels
- **Height**: Height of selection in pixels

### Image Scaling

Large images are automatically scaled to fit the preview dialog:
- Scale factor shown in logs
- Coordinates always in original image space
- No quality loss - scaling is for preview only

### Validation

- Selection must be at least 20x20 pixels
- Selection constrained to window bounds
- Invalid selections are prevented automatically

## Troubleshooting

### Selection Too Small
- Minimum size is 20x20 pixels
- Increase selection size if needed

### Can't See Selection Clearly
- The overlay may be too dark
- Selected area is always highlighted
- Look for red border and corner handles

### Coordinates Not Updating
- Make sure you clicked OK, not Cancel
- Check main GUI for green crop info text
- Try selecting again if needed

## Future Enhancements

Possible future improvements:
- [ ] Save/load selection presets
- [ ] Auto-detect MCDU screen boundaries
- [ ] Grid overlay for precise alignment
- [ ] Zoom in/out for fine-tuning
- [ ] Aspect ratio lock
- [ ] Multiple selection profiles

---

**This feature makes it easy to capture exactly what you need - just the MCDU screen, nothing else!**
