# GUI Interface Preview

Visual representation of the MSFS WinWing MCDU Scraper GUI.

## Main Window

```
┌─────────────────────────────────────────────────────────────────┐
│  MSFS WinWing MCDU Scraper                                  [_][□][X]│
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│           MSFS WinWing MCDU Scraper                              │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌─ Capture Mode ──────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  ◉ Window Capture (works when minimized)                │   │
│  │  ○ Screen Region (from config.yaml)                     │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  ┌─ Window Selection ───────────────────────────────────────┐   │
│  │                                                          │   │
│  │  Select MCDU Window:                                     │   │
│  │  [MCDU - Microsoft Flight Simulator   ▼] [Refresh Windows]  │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  ┌─ Control ────────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  Status: Running  [Start Scraper] [Stop Scraper]       │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  ┌─ Logs ───────────────────────────────────────────────────┐   │
│  │┌────────────────────────────────────────────────────────┐│   │
│  ││2024-02-15 10:30:01 - INFO - Configuration loaded      ││   │
│  ││2024-02-15 10:30:02 - INFO - Window capture initialized││   │
│  ││2024-02-15 10:30:03 - INFO - Connecting to MobiFlight  ││   │
│  ││2024-02-15 10:30:04 - INFO - MobiFlight connected      ││   │
│  ││2024-02-15 10:30:04 - INFO - Font set to: AirbusThales ││   │
│  ││2024-02-15 10:30:05 - INFO - Connected to WinWing CDU  ││   │
│  ││2024-02-15 10:30:05 - INFO - Starting capture loop     ││   │
│  ││2024-02-15 10:30:06 - INFO - Capturing at 30 FPS       ││   │
│  ││                                                        ││   │
│  ││                                                        ││▲  │
│  ││                                                        ││█  │
│  ││                                                        ││█  │
│  ││                                                        ││▼  │
│  │└────────────────────────────────────────────────────────┘│   │
│  │                                                          │   │
│  │                      [Clear Logs]                        │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Element Descriptions

### 1. Title Bar
- Application name: "MSFS WinWing MCDU Scraper"
- Standard window controls (minimize, maximize, close)

### 2. Capture Mode Section
Two radio buttons:
- **Window Capture**: Captures specific window by handle (recommended)
- **Screen Region**: Uses coordinates from config.yaml (classic mode)

### 3. Window Selection Section (visible when Window Capture selected)
- **Dropdown**: Shows list of available windows
  - Filters for MSFS-related windows
  - Format: "Window Title (HWND: handle)"
- **Refresh Windows Button**: Updates the window list

### 4. Control Section
- **Status Label**: Shows current state
  - "Status: Stopped" (red text)
  - "Status: Running" (green text)
- **Start Scraper Button**: Begins capturing
  - Enabled when stopped
  - Disabled when running
- **Stop Scraper Button**: Stops capturing
  - Disabled when stopped
  - Enabled when running

### 5. Logs Section
- **Scrollable Text Area**: Displays real-time logs
  - Auto-scrolls to bottom
  - Shows timestamped messages
  - Color-coded by severity (INFO, WARNING, ERROR)
- **Clear Logs Button**: Clears the log display

## Usage Flow Diagram

```
┌─────────────┐
│  Start GUI  │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ Select Capture Mode │
└──────┬──────────────┘
       │
       ├─ Window Capture ─────────┐
       │                          │
       │                          ▼
       │              ┌───────────────────────┐
       │              │ Refresh Windows List  │
       │              └───────────┬───────────┘
       │                          │
       │                          ▼
       │              ┌───────────────────────┐
       │              │ Select MCDU Window    │
       │              └───────────┬───────────┘
       │                          │
       └─ Screen Region ──────────┤
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │   Click Start Scraper │
                      └───────────┬───────────┘
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │   Watch Logs          │
                      │   MCDU Updates on     │
                      │   WinWing Hardware    │
                      └───────────┬───────────┘
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │ Minimize MCDU Window  │
                      │ (if using Window      │
                      │  Capture mode)        │
                      └───────────┬───────────┘
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │ When done:            │
                      │ Click Stop Scraper    │
                      └───────────────────────┘
```

## Screenshots Placeholder

_Note: Actual screenshots would show the GUI in action. Below are descriptions of what you would see:_

### Screenshot 1: Initial State
- Window Capture mode selected
- Window dropdown empty
- Status: Stopped (red)
- Start button enabled, Stop button disabled
- Empty log area

### Screenshot 2: Windows Refreshed
- Dropdown populated with available windows
- MCDU pop-out window visible in list
- "Microsoft Flight Simulator - MCDU" selected
- Ready to start

### Screenshot 3: Running State
- Status: Running (green)
- Start button disabled, Stop button enabled
- Logs showing:
  - Configuration loaded
  - Window capture initialized
  - WebSocket connected
  - Capturing at 30 FPS
  - Frame processing messages

### Screenshot 4: Window Capture Benefits
Two side-by-side images:
- **Left**: MCDU window minimized to taskbar
- **Right**: WinWing CDU showing MCDU content
- **Caption**: "MCDU can be minimized while scraper runs!"

## Advantages Illustrated

```
Traditional Screen Region Capture:
┌────────────────────────────────┐
│                                │
│  ┌──────────┐                 │
│  │  MCDU    │ ← Must be visible│
│  │  Window  │                 │
│  └──────────┘                 │
│                                │
│  Can't minimize or cover!     │
└────────────────────────────────┘

NEW Window Capture:
┌────────────────────────────────┐
│                                │
│  [Other Apps]                 │
│  [Maximized]                  │
│  [MCDU minimized ▼]           │
│                                │
│  ✅ Still captures MCDU!      │
└────────────────────────────────┘
```

## Color Scheme

- **Background**: Light gray (#f0f0f0)
- **Labels**: Dark gray (#333333)
- **Status Running**: Green (#008000)
- **Status Stopped**: Red (#ff0000)
- **Buttons**: System default (Windows: blue, Linux: varies)
- **Log Text**: Black on white background
- **INFO Messages**: Default color
- **WARNING Messages**: Orange/amber
- **ERROR Messages**: Red

## Responsive Behavior

- **Minimum Window Size**: 900x700 pixels
- **Log Area**: Expands to fill available space
- **Resizable**: Yes, all sections scale appropriately
- **Auto-scroll**: Logs automatically scroll to latest entry

## Keyboard Navigation

- **Tab**: Move between controls
- **Space**: Activate focused button
- **Enter**: Activate default button (Start/Stop)
- **Ctrl+C**: Copy from log area

---

**Note**: This is a text-based representation. The actual GUI uses tkinter with native system styling and may appear slightly different depending on your operating system and theme.
