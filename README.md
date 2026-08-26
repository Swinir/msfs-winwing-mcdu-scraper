# MSFS WinWing MCDU Scraper

Captures an aircraft's FMS display (MCDU / CDU / UNS-1) from its MSFS pop-out
window and sends it to WinWing CDU hardware via WebSocket.

## Features

- Window capture with automatic backend selection (GDI, Windows Graphics
  Capture, or screen region) — no need to keep the window on top
- Interactive screen-area selection with a 24x14 grid overlay and auto-detect
- Character recognition by learned glyph templates, with EasyOCR bootstrap and
  contour fallback for symbols
- Per-cell colour and font-size detection
- MobiFlight-compatible data format
- Aircraft profiles: Airbus MCDU, Boeing CDU, UNS-1, or a custom grid —
  glyphs are learned at runtime, so new fonts teach themselves
- Optional second MCDU (co-pilot), each on its own capture pipeline
- Automatic WebSocket reconnection with backoff
- YAML configuration

## Requirements

### Software

- **Operating System**: Windows 10/11
- **MobiFlight**: WinWing MCDU Connector must be running
- **MSFS 2020/2024**: with an aircraft whose FMS has a pop-out window
- **Python**: 3.9-3.13 (only when running from source; PySide6 sets the range)

### Hardware

- **WinWing CDU**: Captain and/or Co-Pilot hardware
- **Display**: MSFS running on a display where the MCDU can be positioned

## Installation

### Executable (Windows)

Download the latest release from
[Releases](https://github.com/Swinir/msfs-winwing-mcdu-scraper/releases):

`MSFS-MCDU-Scraper-GUI.exe` — no Python or dependencies needed.

### From source

```bash
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper

python -m venv venv
venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

Optionally copy `config.yaml.example` to `config.yaml` to change the
WebSocket URLs, font or frame rate — the defaults work as-is:

```bash
copy config.yaml.example config.yaml
```

## Quick Start

1. Start MSFS with the A330
2. Pop out the MCDU window (right-click the MCDU → "Pop Out")
3. Start the MobiFlight WinWing MCDU Connector
4. Run the GUI

```bash
run_gui.bat       # Windows
./run_gui.sh      # Linux/Mac
```

Select your MCDU window, click "Select Screen Area" to mark the MCDU display,
then "Start Scraper".

See [QUICKSTART.md](QUICKSTART.md) for a step-by-step walkthrough.

## Supported aircraft

The scraper never talks to the aircraft — it reads pixels — so it works with
any FMS whose pop-out shows a character grid. Pick the matching profile in
the **Aircraft** dropdown:

| Profile | Grid | Font | Covers |
|---|---|---|---|
| Airbus MCDU | 24x14 | AirbusThales | Default/iniBuilds A320neo, A321, A330 (MSFS 2020/2024); LatinVFR & Horizon Sim Airbuses; Headwind A330-900 without SimBridge |
| ATR MCDU | 24x14 | AirbusThales | ATR 42-600 / 72-600 (Thales FMS 220, MSFS 2020 Expert Series & 2024) |
| Boeing CDU | 24x14 | Boeing | Default 747-8 and 787; C-17, E-7 (MSFS 2024); GNLU910-style FMS |
| UNS-1 (experimental) | 24x10* | Boeing | Black Square fleet (TBM 850, Dukes, King Air, Starship); Just Flight BAe 146 / F28 UNS-1 |
| Custom grid | you choose | AirbusThales | Anything else (GNS-XLS, CMA-900, …) — set the grid under Advanced |

*The UNS-1 grid size is a best guess pending real captures; correct it under
**Advanced → Override grid size** if rows land in the wrong cells.

Grids smaller than the hardware's 24x14 are padded top-left. Each profile
keeps its own learned-glyph store, so switching aircraft never corrupts
another family's templates — the first run on a new family redoes the
~30s warmup once.

Before scraping, check MobiFlight itself: it ships **native scripts** for
Fenix, FlyByWire, PMDG 737/777, iniBuilds A300/A340, TFDi MD-11, Maddog X
and others. Those read sim data directly and need no OCR — this scraper is
for aircraft with *no* such integration.

## Configuration

Everything about *what* to capture — the window and the crop region — is
chosen in the GUI. `config.yaml` only covers where the result goes and how
hard to work, and the defaults work unchanged:

```yaml
mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
  copilot_url: "ws://localhost:8320/winwing/cdu-co-pilot"
  # Optional font override - normally the aircraft profile picks the font.
  # font: "AirbusThales"
  # Failures tolerated at the base retry delay before backing off.
  max_retries: 3

performance:
  capture_fps: 30
  # Reuse the previous parse when a frame barely changed.
  enable_caching: true
```

### The crop region

This is what most often decides whether the output is readable. Without it
the **whole window** is carved into the 24x14 character grid, so the parse
only makes sense if the window is exactly the MCDU display.

Click "Select Screen Area", then "Auto Detect". The overlay shows where the
character cells will fall — the boundaries should sit between characters, not
through them.

### A second MCDU

Under **Advanced**, tick "Co-Pilot MCDU (second CDU)" to drive two units at
once. It is collapsed by default because almost everyone runs a single CDU.
Pick a second pop-out window and its own screen area; the two run as
independent pipelines and go to `copilot_url`.

## FAQ

**Does the MCDU window need to be pinned on top?**
No. Measured behaviour of the three backends:

| backend | occluded | minimised |
|---|---|---|
| GDI | captures correctly | black frame |
| WGC | captures correctly | captures correctly |
| mss | captures whatever is **on top** | black frame |

The log says which backend is in use. Only mss reads screen pixels, so only
mss cares what covers the window — and mss is the last resort, reached when
the other two fail. MSFS renders with DirectX, which usually defeats GDI, so
`windows-capture` (the WGC backend) is what keeps you off mss. It is a
required dependency for that reason; without it you are on mss and the window
must stay visible and uncovered.

**Do I need to pop out the MCDU?**
Recommended. A pop-out gives consistent positioning. The 2D panel works too,
but the crop region shifts with the camera angle.

**Both Captain and Co-Pilot?**
Enable both in `config.yaml`, each with its own `window_title` and `crop`.
They run as independent pipelines.

**Does it work with VR?**
Not directly. Capture from the desktop mirror or a pop-out window on a monitor.

**Why is the first run slow?**
It spends roughly 30 seconds learning glyph templates from EasyOCR. Afterwards
recognition uses those templates and is fast. They are saved to `templates/`,
so it happens once. The GUI's "Delete Templates" button forces a relearn.

## How It Works

1. **Capture** — grab the MCDU window. Backends are probed on the first frame:
   GDI (`PrintWindow`) → Windows Graphics Capture → mss (Desktop Duplication).
2. **Parse** — split the image into a 24x14 grid and identify each cell:
   learned templates first, then EasyOCR, then contour heuristics for symbols.
   Colour and font size come from per-cell pixel analysis.
3. **Stabilise** — a cell only changes once its new value has held for several
   consecutive frames, which stops OCR jitter reaching the hardware.
4. **Send** — forward the grid over WebSocket in MobiFlight's JSON format, but
   only when it actually changed.

The scraper never talks to MSFS directly — it processes whatever is on screen.

**Data format** (MobiFlight JSON):

```json
{
  "Target": "Display",
  "Data": [["A", "w", 0], ["B", "c", 1], [], "..."]
}
```

Colour codes: `w`=white, `c`=cyan, `g`=green, `a`=amber, `r`=red, `y`=yellow,
`m`=magenta, `e`=grey
Font sizes: `0`=large, `1`=small
Grid: 24 columns x 14 rows (336 cells)

## Project Structure

```
msfs-winwing-mcdu-scraper/
├── src/
│   ├── gui.py                  # Application entry point
│   ├── pipeline.py             # Shared capture/parse/stabilise/send loop
│   ├── config.py               # Configuration
│   ├── window_capture.py       # Window capture (GDI, WGC, mss)
│   ├── mcdu_parser.py          # Templates, OCR, character extraction
│   ├── mcdu_detector.py        # Automatic MCDU region detection
│   ├── region_selector.py      # Interactive region selection dialog
│   ├── mobiflight_client.py    # WebSocket communication
│   └── screen_capture.py       # Legacy fixed-region screen capture
├── tests/                      # Unit tests
├── templates/                  # Learned glyph templates (runtime)
├── requirements.txt            # Python dependencies
├── config.yaml.example         # Annotated configuration template
├── ISSUES.md                   # Known issues and their status
└── QUICKSTART.md               # Step-by-step setup guide
```

## Troubleshooting

**WebSocket connection refused**
Ensure the MobiFlight WinWing MCDU Connector is running on `localhost:8320`.
The client keeps retrying and backs off as failures repeat.

**No characters detected**
Check the crop region first — this is nearly always the cause. Use the GUI's
grid overlay to confirm cell boundaries fall between characters.

**"Captured image is nearly all black"**
The backend is not seeing window content. Try Windowed or Borderless mode and
keep the window visible.

**Wrong characters**
Let the warmup finish. If glyphs remain wrong, use "Delete Templates" and
restart so they are relearned.

**Low frame rate**
Reduce `capture_fps` to 15-20 and keep `enable_caching: true`.

**Incorrect colours**
Check MSFS brightness/gamma. Ensure HDR is not enabled.

## Performance

Sensible settings: 20-30 FPS, caching enabled, crop region trimmed to the MCDU
display only.

Rough requirements: quad-core CPU (i5/Ryzen 5 or better), 4 GB RAM. No GPU
needed — template matching is CPU-only. A CUDA GPU speeds up the one-time
EasyOCR warmup if PyTorch finds one.

## Development

Run the tests:

```bash
pytest tests/
```

Known issues and their current status are tracked in [ISSUES.md](ISSUES.md).

## License

MIT — see [LICENSE](LICENSE).

## Support

Open an issue on GitHub for bugs or questions.
