# Setup Guide

This guide provides detailed instructions for setting up the MSFS A330 WinWing MCDU Scraper.

## Prerequisites

### 1. Python Installation

1. Download Python 3.8 or higher from [python.org](https://www.python.org/downloads/)
2. During installation, check "Add Python to PATH"
3. Verify installation:
   ```bash
   python --version
   ```

### 2. MobiFlight WinWing MCDU Connector

1. Download MobiFlight from [mobiflight.com](https://www.mobiflight.com/)
2. Install and configure for WinWing CDU
3. Ensure it's set to listen on `localhost:8320`
4. Start the connector before running the scraper

## Installation

### Step 1: Clone Repository

```bash
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper
```

### Step 2: Create Virtual Environment

Creating a virtual environment isolates dependencies:

```bash
# Create virtual environment
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Linux/Mac
source venv/bin/activate
```

### Step 3: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:
- `mss` - Screen capture library
- `numpy` - Array processing
- `opencv-python` - Image processing
- `Pillow` - Image handling
- `websockets` - WebSocket client
- `PyYAML` - Configuration parsing

### Step 4: Create Configuration

```bash
copy config.yaml.example config.yaml
```

Edit `config.yaml` with your settings (see next section).

## Configuration

### Basic Configuration

Minimum required configuration:

```yaml
mcdu:
  captain:
    enabled: true
    screen_region:
      top: 400      # Replace with your values
      left: 800
      width: 480
      height: 280

mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
  font: "AirbusThales"
```

### Finding Screen Coordinates

See [CALIBRATION.md](CALIBRATION.md) for detailed instructions.

## Running the Application

### First Run

1. Start MSFS and load Airbus A330
2. Display the MCDU on screen
3. Start MobiFlight WinWing MCDU Connector
4. Run the scraper:

```bash
cd src
python main.py
```

### Expected Output

```
============================================================
MSFS A330 WinWing MCDU Scraper
============================================================
2024-01-01 12:00:00 - config - INFO - Configuration loaded from config.yaml
2024-01-01 12:00:00 - config - INFO - Configuration validation passed
2024-01-01 12:00:00 - main - INFO - Configuration loaded successfully
2024-01-01 12:00:00 - main - INFO - Initializing Captain MCDU...
2024-01-01 12:00:00 - screen_capture - INFO - Screen capture initialized for region: top=400, left=800, width=480, height=280
2024-01-01 12:00:00 - mobiflight_client - INFO - MobiFlightClient initialized for ws://localhost:8320/winwing/cdu-captain
2024-01-01 12:00:00 - main - INFO - Waiting for WebSocket connections...
2024-01-01 12:00:00 - mobiflight_client - INFO - Connecting to MobiFlight at ws://localhost:8320/winwing/cdu-captain
2024-01-01 12:00:00 - mobiflight_client - INFO - MobiFlight connected at ws://localhost:8320/winwing/cdu-captain
2024-01-01 12:00:00 - mobiflight_client - INFO - Font set to: AirbusThales
2024-01-01 12:00:01 - main - INFO - Captain MCDU WebSocket ready
2024-01-01 12:00:01 - main - INFO - Starting main capture loop...
2024-01-01 12:00:01 - main - INFO - Main loop running at 30 FPS
```

### Stopping the Application

Press `Ctrl+C` to gracefully shut down:

```
^C2024-01-01 12:05:00 - main - INFO - Received keyboard interrupt, shutting down...
2024-01-01 12:05:00 - main - INFO - Stopping MCDU scraper...
2024-01-01 12:05:00 - mobiflight_client - INFO - WebSocket closed for ws://localhost:8320/winwing/cdu-captain
2024-01-01 12:05:00 - main - INFO - Captain MCDU client closed
2024-01-01 12:05:00 - screen_capture - INFO - Screen capture session closed
2024-01-01 12:05:00 - main - INFO - Captain MCDU screen capture closed
2024-01-01 12:05:00 - main - INFO - MCDU scraper stopped
```

## Troubleshooting Setup

### Python Not Found

**Error**: `'python' is not recognized as an internal or external command`

**Solution**:
1. Reinstall Python with "Add to PATH" checked
2. Or manually add Python to PATH
3. Restart terminal

### MSS Installation Failed

**Error**: `Failed to build mss` or similar

**Solution**:
1. Update pip: `pip install --upgrade pip`
2. Install Visual C++ Build Tools
3. Try: `pip install mss --no-cache-dir`

### WebSocket Connection Failed

**Error**: `WebSocket error: Connection refused`

**Solution**:
1. Ensure MobiFlight is running
2. Check it's on port 8320
3. Verify firewall settings
4. Try: `telnet localhost 8320`

### Config File Not Found

**Error**: `No config.yaml found`

**Solution**:
1. Copy `config.yaml.example` to `config.yaml`
2. Or create config.yaml with minimum configuration

## Advanced Setup

### Running as Windows Service

To run the scraper automatically on startup:

1. Install NSSM (Non-Sucking Service Manager)
2. Create service:
   ```bash
   nssm install MCDUScraper "C:\path\to\venv\Scripts\python.exe" "C:\path\to\src\main.py"
   ```

### Multiple Configurations

To run different profiles:

```bash
python main.py --config config-high-fps.yaml
python main.py --config config-dual-mcdu.yaml
```

(Note: Requires adding argument parsing to main.py)

### Performance Optimization

For better performance:

1. **Reduce FPS**: Set to 20 instead of 30
2. **Dedicated CPU cores**: Use process affinity
3. **High priority**: Run with elevated priority
4. **Disable logging**: Set level to WARNING

## Next Steps

After setup:

1. [Calibrate screen regions](CALIBRATION.md)
2. Test with simple MCDU page
3. Adjust color thresholds if needed
4. Fine-tune FPS for your system

## Getting Help

If you encounter issues:

1. Check logs in `mcdu_scraper.log`
2. Enable DEBUG logging in main.py
3. Verify all prerequisites are met
4. Open an issue on GitHub with logs
