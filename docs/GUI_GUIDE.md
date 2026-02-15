# GUI User Guide

Complete guide for using the MSFS WinWing MCDU Scraper GUI application.

## Overview

The GUI provides an easy-to-use interface for:
- Selecting MCDU windows without manual coordinate configuration
- Capturing windows even when minimized or behind other applications
- Viewing real-time logs
- Starting and stopping the scraper with one click

## Starting the GUI

### Windows
```bash
run_gui.bat
```

### Linux/Mac
```bash
./run_gui.sh
```

Or directly:
```bash
cd src
python gui.py
```

## GUI Interface

### Capture Mode Selection

**Window Capture (Recommended)**
- Captures a specific window by its handle
- Works even when window is minimized or behind other windows
- No need to configure screen coordinates
- Windows-only feature (requires pywin32)

**Screen Region**
- Uses coordinates from config.yaml
- Original capture method
- Works on all platforms
- Requires manual coordinate configuration

### Window Selection (Window Capture Mode)

1. **Select Window Capture** mode
2. Click **"Refresh Windows"** to populate the dropdown
3. **Select your MCDU window** from the list
   - Look for MCDU pop-out window title
   - May include "MCDU", "Microsoft Flight Simulator", etc.
4. **[Optional] Click "Select Screen Area"** to crop to exact MCDU screen
   - Opens a preview dialog showing the captured window
   - Drag the selection box to frame just the MCDU screen (exclude borders/title bar)
   - Resize by dragging corner handles
   - Click OK to save the selection
   - The crop coordinates will be displayed in green
5. Click **"Start Scraper"**

**Tips**:
- Pop out MCDU in MSFS first (right-click MCDU → "Pop Out")
- The window list shows visible windows with titles
- MSFS-related windows are shown first
- Click "Refresh Windows" if you don't see your window
- Use "Select Screen Area" to exclude window borders and UI elements from capture

### Screen Area Selection (NEW)

The **"Select Screen Area"** button allows you to visually define which part of the captured window contains the actual MCDU screen, excluding borders, title bars, and other UI elements.

**How to use**:
1. Select a window from the dropdown
2. Click "Select Screen Area"
3. A preview window opens showing the captured window
4. **Drag** to move the selection box
5. **Drag corners** to resize the selection
6. The selected area is highlighted; non-selected areas are darkened
7. Current coordinates are shown at the bottom
8. Click **OK** to save, **Cancel** to discard, or **Reset** to start over

**Benefits**:
- Precisely frame the MCDU screen within the pop-out window
- Exclude window borders and decorations
- Exclude any UI elements outside the actual MCDU display
- Visual feedback makes it easy to get exact positioning
- Coordinates are automatically saved and used when scraper starts

**Example use case**: If your MCDU pop-out window is 500x300 pixels but the actual MCDU screen is only 480x280 pixels (with 10px borders), use "Select Screen Area" to crop to just the 480x280 screen portion.

### Control Panel

**Status Display**
- Shows current state: "Stopped" (red) or "Running" (green)

**Start Scraper Button**
- Begins capturing and sending data to WinWing CDU
- Disabled when scraper is running

**Stop Scraper Button**
- Stops the scraper gracefully
- Disabled when scraper is stopped

### Log Viewer

**Features**:
- Real-time log display
- Auto-scroll to latest messages
- Shows all application events, errors, and status updates

**Controls**:
- **Clear Logs** button: Clears the log display
- Scroll bar: Navigate through log history

**Log Levels**:
- INFO: Normal operational messages
- WARNING: Non-critical issues
- ERROR: Errors that need attention

## Step-by-Step Usage

### First Time Setup

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start MSFS**
   - Load Airbus A330
   - Pop out MCDU window (right-click MCDU → "Pop Out")

3. **Start MobiFlight**
   - Ensure WinWing MCDU Connector is running
   - Should be listening on ws://localhost:8320

4. **Launch GUI**
   ```bash
   run_gui.bat  # Windows
   ```

5. **Configure Capture**
   - Select "Window Capture" mode
   - Click "Refresh Windows"
   - Select MCDU pop-out window from dropdown
   - **[Recommended]** Click "Select Screen Area" to crop to exact MCDU screen
     - Drag selection box to frame the MCDU screen
     - Exclude window borders and title bar
     - Click OK to save

6. **Start Scraper**
   - Click "Start Scraper"
   - Watch logs for confirmation
   - Check WinWing CDU displays MCDU content

### Daily Use

1. Start MSFS and pop out MCDU
2. Start MobiFlight
3. Run GUI: `run_gui.bat`
4. Select MCDU window
5. **[Optional]** Adjust screen area if needed
6. Click "Start Scraper"
7. Minimize or hide MCDU window as needed
7. When done, click "Stop Scraper"

## Advantages of Window Capture

### vs Screen Region Capture

| Feature | Window Capture | Screen Region |
|---------|---------------|---------------|
| **Setup Complexity** | Easy - select from dropdown | Manual coordinate configuration |
| **Works When Minimized** | ✅ Yes | ❌ No |
| **Works Behind Windows** | ✅ Yes | ❌ No |
| **Multi-Monitor** | ✅ Automatic | Manual calculation needed |
| **Window Movement** | ✅ Follows window | ❌ Must reconfigure |
| **Platform** | Windows only | All platforms |

### Use Cases

**Perfect for Window Capture**:
- You want to minimize MCDU to save screen space
- You work with multiple applications during flight
- You don't want to manually configure coordinates
- You move MCDU window between sessions

**Use Screen Region When**:
- You're not on Windows
- You prefer using 2D panel MCDU (not pop-out)
- You have a fixed monitor setup that never changes

## Troubleshooting

### GUI Won't Start

**Problem**: Error about tkinter not found

**Solution**:
```bash
# Windows
pip install tk

# Linux
sudo apt-get install python3-tk
```

### Window Capture Not Available

**Problem**: "Window capture not available" message

**Solution**:
```bash
pip install pywin32
```

**Note**: Window capture only works on Windows

### Can't Find MCDU Window

**Problem**: MCDU window not in dropdown

**Solutions**:
1. Ensure MCDU is popped out in MSFS (right-click → "Pop Out")
2. Click "Refresh Windows" button
3. Look for window with "MCDU" or "Flight Simulator" in title
4. Check all dropdown entries - might not have "MCDU" in title

### Black/Empty Display on WinWing

**Problem**: WinWing CDU shows nothing or black screen

**Solutions**:
1. Check MobiFlight is running
2. Verify correct window is selected
3. Check logs for connection errors
4. Ensure MCDU is actually displayed in MSFS
5. Try stopping and restarting scraper

### Connection Refused Error

**Problem**: "Connection refused" in logs

**Solutions**:
1. Start MobiFlight WinWing MCDU Connector
2. Verify it's listening on localhost:8320
3. Check Windows Firewall isn't blocking connection

### Scraper Crashes

**Problem**: Scraper stops unexpectedly

**Solutions**:
1. Check logs for error messages
2. Verify MCDU window still exists
3. Ensure MSFS hasn't closed the pop-out
4. Check if window handle became invalid
5. Restart scraper

### Screen Area Selection Not Working

**Problem**: "Select Screen Area" button doesn't work or shows error

**Solutions**:
1. Ensure a window is selected in the dropdown first
2. Make sure the selected window still exists
3. Try refreshing the window list
4. Check if the window is accessible (not protected/system window)

### Wrong Content After Screen Area Selection

**Problem**: After selecting screen area, wrong content is shown on WinWing CDU

**Solutions**:
1. Re-open "Select Screen Area" and verify the selection
2. Make sure the selection box frames the MCDU screen properly
3. Exclude window borders, title bars, and decorations
4. Check that the crop coordinates shown are correct
5. Try resetting and selecting again

### Screen Area Selection Preview is Blank

**Problem**: Preview window shows blank or black image

**Solutions**:
1. Verify the selected window is actually visible
2. Some windows may be protected from screen capture
3. Try a different window or use Screen Region mode instead
4. Check Windows permissions for screen capture

## Advanced Features

### Using Config File with GUI

The GUI can use `config.yaml` for:
- WebSocket URLs
- Font settings
- FPS configuration
- Co-Pilot MCDU settings (future)

When using "Screen Region" mode, coordinates come from config.yaml.

### Running Multiple MCDUs

Currently, the GUI supports Captain MCDU. For Co-Pilot:
1. Use command-line mode with full config
2. Or run two GUI instances (requires code modification)

### Keyboard Shortcuts

None currently implemented. Future enhancement opportunity.

## Tips and Best Practices

### 1. Pop-Out Window Management

- Keep MCDU pop-out in consistent location
- Don't close pop-out during flight - minimize instead
- If you move window, scraper continues to work (Window Capture mode)

### 2. Screen Area Selection

- **Always use "Select Screen Area"** when first setting up
- Frame only the MCDU screen itself, not borders or title bar
- Check the preview carefully before clicking OK
- Save your configuration if you'll use the same window size again
- If window size changes, re-select the screen area

### 3. Performance

- Default 30 FPS is recommended
- Lower FPS in config if CPU usage is high
- Window capture has similar performance to screen capture

### 3. Logging

- Check logs regularly for errors
- Clear logs periodically for better performance
- Save logs if reporting issues (copy/paste from log viewer)

### 4. Workflow Integration

Example workflow:
```
1. Start MSFS → Load A330
2. Start MobiFlight
3. Start MCDU Scraper GUI
4. Pop out MCDU in MSFS
5. Select window in GUI
6. Start scraper
7. Minimize MCDU window
8. Focus on other applications while flying
9. MCDU continues to update on WinWing hardware
```

## Future Enhancements

Potential future features:
- [ ] Save/load window configurations
- [ ] Dual MCDU support in GUI
- [ ] Auto-detect MCDU windows on startup
- [ ] System tray integration
- [ ] Hotkey support
- [ ] Configuration editor built into GUI
- [ ] Screenshot capability
- [ ] Connection status indicator with details

## Getting Help

If you encounter issues:

1. **Check Logs** in GUI log viewer
2. **Review FAQ** in README.md
3. **Check Documentation** in docs/ folder
4. **Open Issue** on GitHub with:
   - Log output
   - Steps to reproduce
   - Windows version
   - Python version
   - Screenshot of GUI if relevant

---

**Pro Tip**: Use Window Capture mode with minimized MCDU window for the best experience - full screen space for your work while WinWing CDU shows MCDU content!
