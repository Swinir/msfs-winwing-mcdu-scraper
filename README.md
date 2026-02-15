# MSFS A330 WinWing MCDU Scraper

A production-ready Python application that captures the Microsoft Flight Simulator Airbus A330 MCDU screen and displays it on WinWing CDU hardware via WebSocket.

## Features

- **Real-time Screen Capture**: Captures MCDU display at 30 FPS using MSS library
- **Window-Specific Capture**: NEW! Capture specific windows even when minimized or behind other windows (Windows only)
- **Visual Screen Area Selection**: NEW! Interactive preview to select exact MCDU screen area, excluding borders and UI elements
- **GUI Interface**: NEW! Easy-to-use graphical interface with window selection and log viewing
- **Character Recognition**: Extracts 24x14 character grid with color and font size detection
- **MobiFlight Compatible**: Sends data in exact MobiFlight format to WinWing CDU
- **Dual MCDU Support**: Supports both Captain and Co-Pilot MCDUs simultaneously
- **Robust Connection**: Automatic WebSocket reconnection with configurable retries
- **Configurable**: YAML-based configuration for screen regions and settings

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

### Option A: Download Executable (Easiest - No Python Required!)

**Perfect for users who just want to run the application without installing Python.**

1. **Download** the latest release from [Releases](https://github.com/Swinir/msfs-winwing-mcdu-scraper/releases)
   - Download `MSFS-MCDU-Scraper-Windows.zip`
   
2. **Extract** the ZIP file to a folder

3. **Install Tesseract OCR**
   - Download from: https://github.com/UB-Mannheim/tesseract/wiki
   - Run the installer (default settings are fine)
   
4. **Run the application**
   - Double-click `MSFS-MCDU-Scraper-GUI.exe` (for GUI)
   - Or `MSFS-MCDU-Scraper-CLI.exe` (for command-line)

**That's it!** No Python installation or dependencies needed.

### Option B: Install from Source (For Developers)

**For users who want to modify the code or run from Python.**

#### 1. Clone Repository

```bash
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper
```

#### 2. Create Virtual Environment (Recommended)

```bash
python -m venv venv
venv\Scripts\activate  # On Windows
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Install Tesseract OCR

Download and install Tesseract OCR from:
https://github.com/UB-Mannheim/tesseract/wiki

Add Tesseract to your PATH or update `pytesseract.pytesseract.tesseract_cmd` in `mcdu_parser.py`

#### 5. Configure Application

```bash
copy config.yaml.example config.yaml
```

Edit `config.yaml` with your screen positions (see [Configuration Guide](#configuration-guide) and [Visual Guide](docs/VISUAL_GUIDE.md))

## Quick Start

### Option 1: Using GUI (Recommended for Easy Setup)

1. **Start MSFS** and load the Airbus A330
2. **Pop out MCDU** window (right-click MCDU → "Pop Out")
3. **Start MobiFlight** WinWing MCDU Connector
4. **Run the GUI**:

```bash
# Windows
run_gui.bat

# Linux/Mac
./run_gui.sh
```

5. **In the GUI**:
   - Select "Window Capture" mode
   - Click "Refresh Windows" and select your MCDU pop-out window from the dropdown
   - **[Recommended]** Click "Select Screen Area" to visually crop to exact MCDU screen (excludes borders)
   - Click "Start Scraper"
   - Monitor logs in the GUI

**Benefits of GUI**:
- ✅ No need to manually configure screen coordinates
- ✅ Visual screen area selection with interactive preview
- ✅ Works even when MCDU window is minimized or behind other windows
- ✅ Easy window selection from dropdown
- ✅ Live log viewing
- ✅ Simple start/stop controls

### Option 2: Using Command Line (Original Method)

1. **Start MSFS** and load the Airbus A330
2. **Position MCDU** on screen where it can be captured
3. **Start MobiFlight** WinWing MCDU Connector (should listen on `ws://localhost:8320`)
4. **Run the scraper**:

```bash
cd src
python main.py
```

The application will:
- Connect to WinWing CDU via WebSocket
- Set the font to "AirbusThales"
- Start capturing and displaying MCDU content at 30 FPS

## Frequently Asked Questions (FAQ)

💡 **New to this?** Check out the [Visual Setup Guide](docs/VISUAL_GUIDE.md) for diagrams and step-by-step visuals!

### Can I capture the MCDU even when it's minimized or behind other windows?

**Yes!** With the new **Window Capture mode** (Windows only), you can:

- Capture a specific MCDU pop-out window by its title
- Keep working with other applications while MCDU is minimized
- Have other windows on top of the MCDU without affecting capture
- Use the GUI to easily select the correct window

**How to use Window Capture**:

1. Pop out the MCDU window in MSFS (right-click MCDU → "Pop Out")
2. Run the GUI (`run_gui.bat`)
3. Select "Window Capture" mode
4. Choose your MCDU window from the dropdown
5. Click "Start Scraper"

The MCDU window can now be minimized, behind other windows, or even on a different desktop - the scraper will still capture it!

**Note**: Window capture requires Windows OS and pywin32 library (installed automatically). For screen region capture (original method), see below.

### How does the screen capture work?

The scraper **automatically captures whatever is displayed** at the screen coordinates you specify in `config.yaml`. It uses the MSS (Multi-Screen Screenshots) library to continuously grab a specific rectangular region of your screen at 30 FPS.

**Important**: The scraper doesn't interact with MSFS directly - it simply takes screenshots of a screen region, just like taking a screenshot manually but 30 times per second.

### Do I need to pop out the MCDU to a separate window?

**Short answer**: No, but it's recommended.

You have **two options**:

#### Option 1: Use 2D Panel MCDU (Built-in View)
- Display the MCDU using MSFS's built-in 2D cockpit panel
- Configure `config.yaml` with the coordinates of where the MCDU appears in your cockpit view
- **Pros**: Simple, no extra windows
- **Cons**: Coordinates may change if you adjust camera angles or move the view

#### Option 2: Use Pop-out MCDU Window (Recommended)
- Right-click the MCDU in MSFS and select "Pop Out" to create a separate window
- Position this window consistently (e.g., same spot on secondary monitor)
- Configure `config.yaml` with the pop-out window's coordinates
- **Pros**: Consistent position, easier to calibrate, more reliable
- **Cons**: Requires managing an extra window

**Recommendation**: Use pop-out MCDU for best results and easiest setup.

### Do I need to specify which screen/monitor to use?

**Yes**, you must specify the exact screen coordinates in `config.yaml`. The scraper needs to know:

1. **Which monitor** - Specified by the `left` coordinate (X position)
   - Primary monitor: `left` starts from 0
   - Secondary monitor (right): `left` = primary width (e.g., 1920 for 1080p primary)
   - Secondary monitor (left): `left` = negative value

2. **Where on that monitor** - The exact pixel position and size
   - `top`: Y coordinate (pixels from top of screen)
   - `left`: X coordinate (pixels from left edge, accounting for monitor position)
   - `width`: Width of MCDU region (typically 480 pixels)
   - `height`: Height of MCDU region (typically 280 pixels)

**Example for dual monitors**:
```yaml
# Primary monitor (1920x1080), MCDU in cockpit view
screen_region:
  top: 400
  left: 800
  width: 480
  height: 280

# Secondary monitor (1920x1080), pop-out MCDU at top-left
screen_region:
  top: 0
  left: 1920    # Primary monitor width = 1920
  width: 480
  height: 280
```

### What happens if I configure the wrong coordinates?

If coordinates are wrong, you'll see:
- **Black/blank display** on WinWing CDU (capturing empty space)
- **Wrong content** (capturing different part of screen)
- **Incorrect characters** (partial MCDU capture)

**Solution**: Use the calibration guide ([docs/CALIBRATION.md](docs/CALIBRATION.md)) to find correct coordinates.

### How do I find the correct screen coordinates?

See the detailed [Screen Calibration Guide](docs/CALIBRATION.md) for step-by-step instructions. Quick method:

1. **Display your MCDU** (either 2D panel or pop-out)
2. **Take a screenshot** (Win + Shift + S on Windows)
3. **Open in Paint** or image editor
4. **Hover over top-left corner** of MCDU → note X, Y coordinates
5. **Measure MCDU size** → note width, height
6. **Update config.yaml** with these values
7. **Test**: Run `python demo.py` to verify (or see logs when running)

### Does it work with VR?

**Not directly**. The scraper captures from your flat monitor display, not the VR headset view. 

**Workarounds**:
- Use SteamVR/OpenXR desktop mirror and capture from that
- Use MSFS's "2D Panel Pop-out" feature even while in VR
- Position pop-out MCDU on your monitor while flying in VR

### Can I capture both Captain and Co-Pilot MCDUs?

**Yes!** Enable both in `config.yaml`:

```yaml
mcdu:
  captain:
    enabled: true
    screen_region: { top: 400, left: 800, width: 480, height: 280 }
  
  copilot:
    enabled: true
    screen_region: { top: 400, left: 1400, width: 480, height: 280 }
```

Both MCDUs will be captured and sent to their respective WinWing CDU units simultaneously.

### Why do I need to calibrate screen coordinates?

The MCDU can appear at different positions depending on:
- Your screen resolution (1080p, 1440p, 4K, etc.)
- Number of monitors
- MSFS window mode (fullscreen, windowed, borderless)
- Camera view/angle (for 2D panel)
- Pop-out window position

Because of this variability, **you must tell the scraper exactly where to look** by providing precise pixel coordinates.

## Configuration Guide

### Screen Region Calibration

You need to determine the exact pixel coordinates of your MCDU on screen:

1. **Open MSFS** with A330 and display MCDU
2. **Take a screenshot** (Win + Shift + S)
3. **Open in Paint** or image editor
4. **Note the coordinates**:
   - Move cursor to top-left corner of MCDU → note X, Y
   - Measure width and height of MCDU area

Example `config.yaml`:

```yaml
mcdu:
  captain:
    enabled: true
    screen_region:
      top: 400      # Y coordinate of top-left corner
      left: 800     # X coordinate of top-left corner
      width: 480    # Width of MCDU area
      height: 280   # Height of MCDU area
  
  copilot:
    enabled: false  # Set to true to enable copilot MCDU
    screen_region:
      top: 400
      left: 1400
      width: 480
      height: 280

mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
  copilot_url: "ws://localhost:8320/winwing/cdu-co-pilot"
  font: "AirbusThales"  # Font for Airbus MCDU
  max_retries: 3

performance:
  capture_fps: 30        # Frames per second (10-60)
  enable_caching: true   # Enable character detection caching
```

### Detailed Configuration

See [docs/CALIBRATION.md](docs/CALIBRATION.md) for detailed calibration instructions.

## Project Structure

```
msfs-winwing-mcdu-scraper/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── config.yaml.example          # Example configuration
├── config.yaml                  # Your configuration (git-ignored)
├── src/
│   ├── __init__.py             # Package initialization
│   ├── main.py                 # Application entry point
│   ├── config.py               # Configuration management
│   ├── screen_capture.py       # Screen capture using MSS
│   ├── mcdu_parser.py          # Character extraction and parsing
│   └── mobiflight_client.py    # WebSocket client for WinWing
├── templates/                   # Character templates (future use)
├── tests/                       # Unit tests
└── docs/                        # Documentation
    ├── SETUP.md                # Detailed setup guide
    └── CALIBRATION.md          # Screen calibration guide
```

## How It Works

### Overview

The scraper acts as a "bridge" between MSFS and your WinWing CDU hardware:

1. **Screen Capture**: Takes screenshots of a specific screen region 30 times per second
2. **Image Processing**: Analyzes the captured image to extract MCDU content
3. **Data Transmission**: Sends formatted data to WinWing CDU via WebSocket

**Key Point**: The scraper doesn't interact with MSFS directly - it simply captures and processes whatever is displayed at the configured screen coordinates.

### Step-by-Step Workflow

```
1. You configure screen coordinates in config.yaml
   ↓
2. MSFS displays MCDU (2D panel or pop-out window)
   ↓
3. Scraper captures that screen region (30 FPS)
   ↓
4. Image is analyzed: characters, colors, font sizes extracted
   ↓
5. Data sent to WinWing CDU via WebSocket
   ↓
6. WinWing CDU displays the MCDU content
   ↓
7. Loop repeats 30 times per second
```

### Architecture

```
┌─────────────┐
│    MSFS     │
│  A330 MCDU  │  ← You display this (2D panel or pop-out)
└──────┬──────┘
       │ (Displayed on your screen at configured coordinates)
       ▼
┌─────────────────┐
│  Screen Capture │  ← MSS Library captures this region
│   480x280 px    │     (whatever is at top/left/width/height)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  MCDU Parser    │  ← Analyzes the captured image
│  - OCR (Tesseract)  │     - Detects characters (A, B, 1, 2, etc.)
│  - Color Detection  │     - Detects colors (white, cyan, green, etc.)
│  - Font Size        │     - Detects size (large/small)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ MobiFlight      │  ← Formats and sends via WebSocket
│ JSON Format     │     (to localhost:8320)
│ [char, color, size]
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  WinWing CDU    │  ← Your physical hardware displays it
│   Display       │
└─────────────────┘
```

### Data Format

The application sends data in MobiFlight format:

```json
{
  "Target": "Display",
  "Data": [
    ["A", "w", 0],   // Large white 'A'
    ["B", "c", 1],   // Small cyan 'B'
    [],              // Empty cell
    // ... 333 more cells (336 total)
  ]
}
```

**Color Codes:**
- `w` = white
- `c` = cyan
- `g` = green
- `m` = magenta
- `a` = amber
- `r` = red
- `y` = yellow
- `e` = grey

**Font Sizes:**
- `0` = Large
- `1` = Small

### MCDU Grid Layout

```
Row 0:  Title row (large font)
Row 1:  Label row (small font)
Row 2:  Data row (large font)
Row 3:  Label row (small font)
...
Row 13: Scratchpad (large font)
```

## Troubleshooting

### WebSocket Connection Failed

**Problem**: `WebSocket error: Connection refused`

**Solutions**:
1. Ensure MobiFlight WinWing MCDU Connector is running
2. Check that it's listening on `localhost:8320`
3. Verify firewall isn't blocking the connection

### No Characters Detected

**Problem**: Empty MCDU display on WinWing

**Solutions**:
1. Verify screen region coordinates are correct
2. Check that MCDU is visible in MSFS
3. Ensure Tesseract OCR is installed and in PATH
4. Try adjusting brightness/contrast in MSFS

### Low Frame Rate

**Problem**: Updates are slow or choppy

**Solutions**:
1. Reduce `capture_fps` in config (try 15-20)
2. Close other applications
3. Ensure MSFS is not limiting frame rate
4. Check CPU usage

### Incorrect Colors

**Problem**: Colors appear wrong on WinWing CDU

**Solutions**:
1. Adjust color detection thresholds in `mcdu_parser.py`
2. Check MSFS display settings (brightness, gamma)
3. Ensure HDR is not interfering

## Performance Tuning

### Optimal Settings

For best performance:
- **FPS**: 20-30 (higher uses more CPU)
- **Caching**: Enabled (reduces OCR overhead)
- **Screen Region**: Minimize to exact MCDU area

### System Requirements

- **CPU**: Modern quad-core (i5/Ryzen 5 or better)
- **RAM**: 4GB minimum, 8GB recommended
- **GPU**: Not used (CPU-based capture and OCR)

## Advanced Usage

### Running Both MCDUs

To run both Captain and Co-Pilot MCDUs:

```yaml
mcdu:
  captain:
    enabled: true
    screen_region: { top: 400, left: 800, width: 480, height: 280 }
  
  copilot:
    enabled: true
    screen_region: { top: 400, left: 1400, width: 480, height: 280 }
```

### Custom Fonts

To use a different font (e.g., for Boeing):

```yaml
mobiflight:
  font: "Boeing737"  # Or other MobiFlight-supported font
```

### Logging

Logs are written to:
- **Console**: INFO level and above
- **File**: `mcdu_scraper.log` (all levels)

To change log level, edit `main.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for more detail
    ...
)
```

## Development

### Running Tests

```bash
pytest tests/
```

### Code Structure

- `config.py`: Configuration management
- `screen_capture.py`: Screen grabbing
- `mcdu_parser.py`: Image processing and OCR
- `mobiflight_client.py`: WebSocket communication
- `main.py`: Application orchestration

## Contributing

This is a private repository. For internal contributions:

1. Create a feature branch
2. Make your changes
3. Test thoroughly
4. Submit pull request

## License

Private/Proprietary - All rights reserved

## Support

For issues or questions, please open an issue on GitHub.

## Changelog

### Version 1.0.0 (2024)
- Initial release
- Basic screen capture and character detection
- MobiFlight WebSocket integration
- Captain and Co-Pilot MCDU support
- Configuration management
- Logging and error handling

## Acknowledgments

- MobiFlight project for WebSocket protocol specification
- WinWing for CDU hardware
- Microsoft Flight Simulator team

---

**Note**: This application is designed for personal use with MSFS and WinWing hardware. It is not affiliated with Airbus, Microsoft, or WinWing.