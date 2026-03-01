# MSFS A330 WinWing MCDU Scraper

Captures the MSFS Airbus A330 MCDU display and sends it to WinWing CDU hardware via WebSocket.

## Features

- Screen capture at 30 FPS (MSS library)
- Window capture (minimized/hidden windows supported on Windows)
- Interactive screen area selection GUI
- 24×14 character extraction with color and font size detection
- MobiFlight-compatible data format
- Captain and Co-Pilot MCDU support
- Automatic WebSocket reconnection
- YAML configuration

## Requirements

### Software Requirements

- **Python**: 3.8 or higher
- **Operating System**: Windows (for MSS screen capture)
- **MobiFlight**: WinWing MCDU Connector must be running
- **MSFS 2020/2024**: With default Airbus A330

### Hardware Requirements

- **WinWing CDU**: Captain and/or Co-Pilot CDU hardware
- **Display**: MSFS running on a display where MCDU can be positioned

## Installation

### Executable (Windows)

Download the latest release from [Releases](https://github.com/Swinir/msfs-winwing-mcdu-scraper/releases):
- `MSFS-MCDU-Scraper-GUI.exe` — graphical interface
- `MSFS-MCDU-Scraper-CLI.exe` — command-line

No Python or dependencies needed.

### From Source

1. Clone repository

```bash
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper
```

2. Create virtual environment

```bash
python -m venv venv
venv\Scripts\activate  # On Windows
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Configure application

```bash
copy config.yaml.example config.yaml
```

Edit `config.yaml` with your screen positions (see [Configuration Guide](#configuration-guide) and [Visual Guide](docs/VISUAL_GUIDE.md))

## Quick Start

1. Start MSFS with A330
2. Pop out MCDU window (right-click MCDU → "Pop Out")
3. Start MobiFlight WinWing MCDU Connector
4. Run GUI or CLI:

**GUI**:
```bash
run_gui.bat       # Windows
./run_gui.sh      # Linux/Mac
```

Select "Window Capture", choose your MCDU window, optionally select exact screen area, then click "Start Scraper".

**CLI**:
```bash
cd src && python main.py
```

## FAQ

**Window capture minimized/hidden?**  
Yes (Windows only). Pop out MCDU, select in GUI, start scraper. Window can be minimized or hidden afterward.

**Screen capture vs. window capture?**  
Window capture (recommended) — grabs a specific window. Pop out MCDU and select from dropdown.  
Screen region — grabs fixed screen coordinates (legacy, used if window capture unavailable).

**Do I need to pop out MCDU?**  
Recommended. Pop out provides consistent positioning. 2D panel also works but coordinates may shift with camera angle.

**Screen coordinates for multiple monitors?**  
`left` coordinate accounts for monitor position: primary starts at 0, secondary (right) at primary width (e.g., 1920).

**Wrong coordinates captured?**  
Black display or wrong content. See [Screen Calibration Guide](docs/CALIBRATION.md) or use GUI screen area selector.

**Both Captain and Co-Pilot MCDUs?**  
Enable both in `config.yaml` with separate screen coordinates.

**Works with VR?**  
Not directly. Capture from desktop mirror or pop-out window on monitor.

## Configuration

Edit `config.yaml`:

```yaml
mcdu:
  captain:
    enabled: true
  copilot:
    enabled: false

mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
  copilot_url: "ws://localhost:8320/winwing/cdu-co-pilot"
  font: "AirbusThales"
  max_retries: 3

performance:
  capture_fps: 30
  enable_caching: true

See [docs/CALIBRATION.md](docs/CALIBRATION.md) for screen calibration.

## Project Structure

```
msfs-winwing-mcdu-scraper/
├── src/
│   ├── main.py                 # Entry point (CLI)
│   ├── gui.py                  # GUI application
│   ├── config.py               # Configuration
│   ├── window_capture.py       # Window/screen capture (MSS, GDI)
│   ├── mcdu_parser.py          # OCR, template matching, character extraction
│   ├── mcdu_detector.py        # Auto MCDU region detection
│   ├── region_selector.py      # Interactive region selection GUI
│   ├── mobiflight_client.py    # WebSocket communication
│   └── screen_capture.py       # Legacy screen capture
├── tests/                       # Unit tests
├── templates/                   # Learned character templates (runtime)
├── requirements.txt             # Python dependencies
├── config.yaml.example          # Configuration template
└── docs/
    ├── SETUP.md                # Setup instructions
    ├── CALIBRATION.md          # Screen calibration guide
    └── VISUAL_GUIDE.md         # Visual setup guide
```

## How It Works

1. Screen capture (MSS library) — 30 FPS
2. Image analysis (OCR + contour detection) — extract characters, colors, font sizes
3. WebSocket transmission (MobiFlight JSON format) — send to WinWing CDU
4. Repeat

The scraper doesn't interact with MSFS directly—it captures and processes whatever is displayed on screen.

**Data format** (MobiFlight JSON):
```json
{
  "Target": "Display",
  "Data": [["A", "w", 0], ["B", "c", 1], [], ...]
}
```

Color codes: `w`=white, `c`=cyan, `g`=green, `a`=amber, `r`=red, `y`=yellow, `m`=magenta, `e`=grey  
Font sizes: `0`=large, `1`=small  
Grid: 24 columns × 14 rows (336 cells total)

## Troubleshooting

**WebSocket connection refused**  
Ensure MobiFlight WinWing MCDU Connector is running on `localhost:8320`.

**No characters detected**  
Verify screen coordinates are correct and MCDU is visible in MSFS. Check brightness/contrast settings.

**Low frame rate**  
Reduce `capture_fps` in config (try 15-20) or close other applications.

**Incorrect colors**  
Check MSFS brightness/gamma settings. Ensure HDR is not enabled.

## Performance

Optimal settings: 20-30 FPS, caching enabled, screen region minimized to exact MCDU area.

System requirements: quad-core CPU (i5/Ryzen 5+), 4GB+ RAM. GPU not required.

## Advanced

**Both MCDUs**: Enable both `captain` and `copilot` in config with different display coordinates.

**Custom fonts**: Change `font` setting in config (e.g., `Boeing737`).

**Logging**: Console output at INFO level. File output to `mcdu_scraper.log`. Edit `main.py` to change log level.

## Development

Run tests: `pytest tests/`

Code structure:
- `config.py` — configuration
- `window_capture.py` — window/screen capture
- `mcdu_parser.py` — image processing, OCR, template matching
- `mcdu_detector.py` — automatic MCDU region detection
- `mobiflight_client.py` — WebSocket communication
- `main.py` — entry point

## Changelog

**v1.0** (2024) — Initial release

## License

Private/Proprietary

## Support

Open an issue on GitHub for bugs or questions.