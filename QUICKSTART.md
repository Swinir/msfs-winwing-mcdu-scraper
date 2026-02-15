# Quick Start Guide

Get up and running with the MSFS A330 WinWing MCDU Scraper in 5 minutes!

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
