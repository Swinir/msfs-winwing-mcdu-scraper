# MSFS A330 WinWing MCDU Scraper

A production-ready Python application that captures the Microsoft Flight Simulator Airbus A330 MCDU screen and displays it on WinWing CDU hardware via WebSocket.

## Features

- **Real-time Screen Capture**: Captures MCDU display at 30 FPS using MSS library
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

### 1. Clone Repository

```bash
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper
```

### 2. Create Virtual Environment (Recommended)

```bash
python -m venv venv
venv\Scripts\activate  # On Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Tesseract OCR

Download and install Tesseract OCR from:
https://github.com/UB-Mannheim/tesseract/wiki

Add Tesseract to your PATH or update `pytesseract.pytesseract.tesseract_cmd` in `mcdu_parser.py`

### 5. Configure Application

```bash
copy config.yaml.example config.yaml
```

Edit `config.yaml` with your screen positions (see Configuration Guide below)

## Quick Start

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

### Architecture

```
┌─────────────┐
│    MSFS     │
│  A330 MCDU  │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  Screen Capture │  (MSS Library)
│   480x280 px    │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  MCDU Parser    │  (24x14 Grid)
│  - OCR (Tesseract)
│  - Color Detection
│  - Font Size
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ MobiFlight      │  (WebSocket)
│ JSON Format     │
│ [char, color, size]
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  WinWing CDU    │  (Hardware)
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