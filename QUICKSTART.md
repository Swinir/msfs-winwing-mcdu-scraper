# Quick Start Guide

Get up and running with the MSFS A330 WinWing MCDU Scraper in 5 minutes!

## NEW: GUI Mode (Easiest!) 🎉

**The simplest way to use this scraper** - no configuration files needed!

### What's New?

- **Window Capture**: Select MCDU window from dropdown - works even when minimized!
- **GUI Interface**: Easy point-and-click interface with live logs
- **No Coordinates**: No need to manually configure screen positions
- **Works Behind Windows**: Keep MCDU minimized or behind other applications

### 2-Minute Quick Start with GUI

1. **Pop out MCDU** in MSFS (right-click → "Pop Out")
2. **Start MobiFlight** WinWing MCDU Connector
3. **Run GUI**: Double-click `run_gui.bat` (Windows)
4. **Select Window** from dropdown (look for "MCDU" or "Flight Simulator")
5. **Click "Start Scraper"** → Done!

Your MCDU window can now be minimized or behind other windows - it will still work! 🎉

---

## How Does This Work?

**Simple explanation**: This application captures your MSFS MCDU display and sends the content to your WinWing CDU hardware.

### Two Capture Methods

**NEW - Window Capture** (Recommended):
1. You select the MCDU window from a dropdown
2. The scraper captures that specific window 30 times per second
3. Works even when window is minimized or behind other windows
4. It sends this information to your WinWing CDU via network connection
5. Your physical WinWing CDU displays exactly what MSFS shows

**Original - Screen Region Capture**:
1. You tell the scraper where your MCDU is on screen (coordinates in config.yaml)
2. The scraper captures that screen area 30 times per second
3. It reads the characters, colors, and detects what's displayed
4. It sends this information to your WinWing CDU via network connection
5. Your physical WinWing CDU displays exactly what MSFS shows

## 2D Panel vs Pop-Out MCDU

You can capture the MCDU in two ways:

### Option 1: 2D Cockpit Panel (Simple)
- Just display the MCDU in your normal cockpit view
- Configure where it appears on your screen
- May shift if you move the camera

### Option 2: Pop-Out Window (Recommended ⭐)
- Right-click MCDU in MSFS → "Pop Out"
- Position window consistently (same spot each time)
- More reliable, easier to configure

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] Python 3.8+ installed
- [ ] Tesseract OCR installed and in PATH
- [ ] MSFS 2020/2024 with Airbus A330
- [ ] WinWing CDU hardware
- [ ] MobiFlight WinWing MCDU Connector installed

## 5-Minute Setup

### Step 1: Install (2 minutes)

```bash
# Clone repository
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure (2 minutes)

```bash
# Copy example config
copy config.yaml.example config.yaml

# Edit config.yaml with your screen coordinates
notepad config.yaml
```

Minimal configuration:
```yaml
mcdu:
  captain:
    enabled: true
    screen_region:
      top: 400      # Change these!
      left: 800
      width: 480
      height: 280
```

**Need help finding coordinates?** See [docs/CALIBRATION.md](docs/CALIBRATION.md)

### Step 3: Run (1 minute)

```bash
# Start MobiFlight WinWing MCDU Connector first!

# Then run scraper
cd src
python main.py
```

## Expected Output

You should see:
```
============================================================
MSFS A330 WinWing MCDU Scraper
============================================================
... Configuration loaded successfully
... Initializing Captain MCDU...
... MobiFlight connected at ws://localhost:8320/winwing/cdu-captain
... Font set to: AirbusThales
... Starting main capture loop...
... Main loop running at 30 FPS
```

Your WinWing CDU should now display the MCDU content from MSFS!

## Quick Troubleshooting

### "No config.yaml found"
→ Copy `config.yaml.example` to `config.yaml`

### "WebSocket error: Connection refused"
→ Start MobiFlight WinWing MCDU Connector first

### "TesseractNotFoundError"
→ Install Tesseract OCR and add to PATH

### "Module not found" errors
→ Activate virtual environment and run `pip install -r requirements.txt`

### Black/empty display on WinWing
→ Check screen coordinates in config.yaml (see CALIBRATION.md)

## Next Steps

Once running:

1. **Fine-tune coordinates**: Adjust screen region for perfect capture
2. **Adjust FPS**: Lower if CPU usage is high
3. **Enable co-pilot**: Set `copilot.enabled: true` if needed
4. **Check logs**: Review `mcdu_scraper.log` for issues

## Alternative: Using Scripts

### Windows
```bash
run.bat
```

### Linux/Mac
```bash
./run.sh
```

## Demo Mode

Test without MSFS/WinWing:
```bash
python demo.py
```

## Help & Support

- **Full Documentation**: See [README.md](README.md)
- **Setup Guide**: See [docs/SETUP.md](docs/SETUP.md)
- **Calibration**: See [docs/CALIBRATION.md](docs/CALIBRATION.md)
- **Issues**: Open an issue on GitHub

## Configuration Reference

### Minimum Config
```yaml
mcdu:
  captain:
    enabled: true
    screen_region:
      top: 400
      left: 800
      width: 480
      height: 280
```

### Dual MCDU Config
```yaml
mcdu:
  captain:
    enabled: true
    screen_region: { top: 400, left: 800, width: 480, height: 280 }
  
  copilot:
    enabled: true
    screen_region: { top: 400, left: 1400, width: 480, height: 280 }
```

### Performance Tuning
```yaml
performance:
  capture_fps: 20        # Lower for better CPU usage
  enable_caching: true   # Keep enabled for speed
```

## Common Screen Coordinates

### 1920x1080 Fullscreen
```yaml
screen_region:
  top: 400
  left: 800
  width: 480
  height: 280
```

### 2560x1440 Fullscreen
```yaml
screen_region:
  top: 550
  left: 1040
  width: 480
  height: 280
```

### Pop-out Window (Secondary Monitor)
```yaml
screen_region:
  top: 0
  left: 1920    # Primary monitor width
  width: 480
  height: 280
```

---

**Ready to fly!** 🛫

Your MCDU scraper should now be running and displaying on your WinWing CDU.
