# Visual Setup Guide

A visual walkthrough of how the MSFS MCDU Scraper works and how to set it up.

## Understanding the System

### What the Scraper Does

```
┌──────────────────────────────────────────────────────┐
│  Your Computer Screen                                 │
│                                                       │
│  ┌─────────────────────┐                            │
│  │  MSFS Window        │                            │
│  │                     │                            │
│  │     ┌──────────┐   │   ← MCDU displayed here    │
│  │     │  MCDU    │   │      (either 2D panel or   │
│  │     │ Display  │   │       pop-out window)      │
│  │     └──────────┘   │                            │
│  │                     │                            │
│  └─────────────────────┘                            │
│                                                       │
└──────────────────────────────────────────────────────┘
         │
         │ Scraper takes screenshots of MCDU area
         │ (whatever is at configured coordinates)
         ▼
┌──────────────────────┐
│  Python Scraper      │
│  - Captures screen   │
│  - Reads characters  │
│  - Detects colors    │
└──────────────────────┘
         │
         │ Sends formatted data via WebSocket
         ▼
┌──────────────────────┐
│  WinWing CDU         │  ← Your physical hardware
│  (Physical Display)  │     shows MCDU content
└──────────────────────┘
```

## Setup Workflow

### Step 1: Display Your MCDU

**Option A: Use 2D Panel (Built-in)**
```
┌────────────────────────────────┐
│  MSFS Cockpit View             │
│                                 │
│   [Instruments]  ┌──────────┐  │
│                  │   MCDU   │  │ ← MCDU in cockpit
│   [Controls]     │  DISPLAY │  │
│                  └──────────┘  │
└────────────────────────────────┘
```

**Option B: Use Pop-Out Window (Recommended)**
```
┌────────────────┐  ┌──────────┐
│  MSFS Window   │  │  MCDU    │ ← Separate window
│                │  │  DISPLAY │    (right-click MCDU
│  [Cockpit]     │  │          │     then "Pop Out")
│                │  └──────────┘
└────────────────┘
```

### Step 2: Find Screen Coordinates

The scraper needs 4 numbers:

```
Screen (1920x1080):
  0,0 ──────────────────────────→ 1920,0
   │                                │
   │    ┌──────────┐               │
   │    │  MCDU    │ ← Need these: │
   │    │  at      │    top: 400   │
   │    │  800,400 │    left: 800  │
   │    │          │    width: 480 │
   │    │  480x280 │    height: 280│
   │    └──────────┘               │
   │                                │
  0,1080 ────────────────────→ 1920,1080
```

**How to find**:
1. Display MCDU on screen
2. Take screenshot (Win + Shift + S)
3. Open in Paint
4. Hover mouse over top-left corner of MCDU
5. Note X,Y coordinates shown in bottom-left of Paint
6. X = `left`, Y = `top`
7. Measure MCDU size for `width` and `height`

### Step 3: Configure

Edit `config.yaml`:
```yaml
mcdu:
  captain:
    enabled: true
    screen_region:
      top: 400      # ← Y position from top
      left: 800     # ← X position from left
      width: 480    # ← MCDU width
      height: 280   # ← MCDU height
```

### Step 4: Run

```
Terminal:
> python src/main.py

Output:
  ✓ Configuration loaded
  ✓ Screen capture initialized at (800, 400, 480x280)
  ✓ Connected to WinWing CDU
  ✓ Capturing at 30 FPS
  
Your WinWing CDU: Now showing MSFS MCDU! 🎉
```

## Multiple Monitor Setup

### Primary + Secondary Monitor

```
┌─────────────────┐  ┌─────────────────┐
│  Primary        │  │  Secondary      │
│  Monitor        │  │  Monitor        │
│  0 → 1920       │  │  1920 → 3840    │
│                 │  │                 │
│  [MSFS]         │  │  ┌──────────┐  │
│                 │  │  │  MCDU    │  │ ← Pop-out here
│                 │  │  │  Pop-out │  │
│                 │  │  └──────────┘  │
└─────────────────┘  └─────────────────┘
     Monitor 0            Monitor 1
```

**Config for MCDU on secondary monitor**:
```yaml
screen_region:
  top: 0          # Top of secondary monitor
  left: 1920      # Primary width (1920) + offset
  width: 480
  height: 280
```

## Common Scenarios

### Scenario 1: Fullscreen MSFS, 2D Panel MCDU
```yaml
# MCDU visible in center-right of cockpit view
screen_region:
  top: 400
  left: 800
  width: 480
  height: 280
```

### Scenario 2: Pop-Out MCDU on Same Monitor
```yaml
# Pop-out window positioned at specific location
screen_region:
  top: 100
  left: 1400
  width: 480
  height: 280
```

### Scenario 3: Pop-Out MCDU on Second Monitor
```yaml
# Second monitor (1920x1080), MCDU at top-left
screen_region:
  top: 0
  left: 1920    # First monitor width
  width: 480
  height: 280
```

### Scenario 4: Both Captain and Co-Pilot MCDUs
```yaml
# Two pop-out windows side by side
mcdu:
  captain:
    enabled: true
    screen_region:
      top: 100
      left: 1920    # Second monitor
      width: 480
      height: 280
  
  copilot:
    enabled: true
    screen_region:
      top: 100
      left: 2420    # 1920 + 500 (spacing)
      width: 480
      height: 280
```

## Troubleshooting Visuals

### Problem: Black Screen on WinWing CDU

**What's happening**:
```
Configured:                  Actually capturing:
┌──────────┐                ┌──────────┐
│  MCDU    │                │ (black   │
│  should  │  ✗             │  empty   │
│  be here │                │  space)  │
└──────────┘                └──────────┘
```

**Why**: Wrong coordinates - capturing empty screen area

**Fix**: Recalibrate coordinates to match MCDU position

### Problem: Partial MCDU Captured

**What's happening**:
```
MCDU on screen:            Capture region:
┌──────────────┐           ┌─────────┐
│  TITLE       │           │ TITLE   │
│  DATA FIELD  │           │ DATA F← │ (cut off)
│  MORE DATA   │           └─────────┘
└──────────────┘
```

**Why**: Region too small or offset

**Fix**: Adjust width/height to cover full MCDU

### Problem: Extra Content Captured

**What's happening**:
```
MCDU on screen:            Capture region:
┌──────────┐               ┌────────────────┐
│  MCDU    │               │  MCDU + extra  │
│  DISPLAY │               │  DISPLAY [btn] │
└──────────┘               └────────────────┘
```

**Why**: Region too large

**Fix**: Reduce width/height to exact MCDU size

## Best Practices

### ✅ DO

1. **Use pop-out MCDU** for consistency
2. **Position pop-out at same spot** every time
3. **Test with simple MCDU page** first (like MENU)
4. **Save your config** once calibrated
5. **Keep MSFS window/resolution** consistent

### ❌ DON'T

1. **Don't move MCDU** while scraper is running
2. **Don't change MSFS resolution** without recalibrating
3. **Don't use 2D panel** if camera moves frequently
4. **Don't overlap MCDU** with other windows
5. **Don't use HDR** if it causes color issues

## Quick Reference

**Minimum working config**:
```yaml
mcdu:
  captain:
    enabled: true
    screen_region: { top: 400, left: 800, width: 480, height: 280 }

mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
```

**Finding coordinates** (Windows):
1. Win + Shift + S (screenshot)
2. Open in Paint
3. Hover mouse = see X,Y coordinates
4. X = left, Y = top

**Test your setup**:
```bash
python demo.py  # Test without hardware
python validate.py  # Validate configuration
```

---

**Still confused?** Check the FAQ in [README.md](../README.md) or open an issue on GitHub!
