# Quick Start Guide

Get the MSFS WinWing CDU Scraper running in about five minutes.

## What it does

MSFS draws the aircraft's FMS display on screen.  This app screenshots that window, reads
the 24x14 character grid back out of the pixels, and forwards it to MobiFlight,
which drives your physical WinWing CDU display.

It does not talk to the simulator directly — it reads whatever is on screen.

## Before you start

- [ ] Windows 10/11
- [ ] MSFS 2020/2024 with an aircraft whose FMS has a pop-out window
- [ ] WinWing CDU hardware
- [ ] MobiFlight **WinWing MCDU Connector** installed and running
- [ ] Python 3.9-3.13 — only if running from source (the `.exe` needs nothing)

## Fastest path: the GUI

The GUI needs no configuration file for the capture area — you select it
visually.

1. **Pop out the MCDU** in MSFS: right-click the MCDU → "Pop Out".
2. **Start MobiFlight** WinWing MCDU Connector.
3. **Run the GUI**: double-click `MSFS-CDU-Scraper-GUI.exe`, or `run_gui.bat`
   from source.
4. **Select your window** from the dropdown (look for "Flight Simulator" or
   "MCDU"). Tick "Show all windows" if it is not listed.
   Then pick your **Aircraft** profile — Airbus MCDU, Boeing CDU, UNS-1, or
   a custom grid. The profile sets the grid overlay and the hardware font.
5. **Click "Select Screen Area"**, then "Auto Detect" — or drag a box around
   just the MCDU screen. The 24x14 grid overlay shows how the characters will
   be carved up; the boundaries should sit between characters, not through them.
6. **Click "Start Scraper"**.

The first run spends roughly 30 seconds learning glyph shapes ("Template
warmup" in the log). After that, recognition runs from the learned templates
and is fast. The learned glyphs are saved, so this happens once.

Once running, the MCDU window can sit behind other windows — it does not
need to be pinned on top. Minimising it works only on the WGC backend. The
log reports which backend was chosen; if it says mss, the window must stay
visible and uncovered, which usually means `windows-capture` is missing.

## From source

```bash
git clone https://github.com/Swinir/msfs-winwing-mcdu-scraper.git
cd msfs-winwing-mcdu-scraper

python -m venv venv
venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

Then run the GUI:

```bash
run_gui.bat
```

## A second MCDU

Under **Advanced**, tick "Co-Pilot MCDU (second CDU)". It is tucked away
because almost everyone runs a single CDU.

Pick a second pop-out window and give it its own screen area. The two MCDUs
run as independent capture pipelines, so neither slows the other down, and
the co-pilot output goes to `copilot_url` from `config.yaml`.

The two must be different windows — the app refuses to start if both are set
to the same one.

## Configuration

`config.yaml` is optional; the defaults work. It covers only where output
goes and how hard to work:

```yaml
mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
  copilot_url: "ws://localhost:8320/winwing/cdu-co-pilot"
  font: "AirbusThales"

performance:
  capture_fps: 30
```

Which window to capture and which part of it to crop are chosen in the GUI.

## Troubleshooting

**"WebSocket connection closed" / connection refused**
Start the MobiFlight WinWing MCDU Connector first. It listens on
`localhost:8320`. The scraper keeps retrying, backing off as failures repeat.

**Blank or garbled CDU display**
Almost always the capture area. Use "Select Screen Area" and check that the
grid overlay lines up with the characters — the boundaries should fall
between them, not through them.

**"Captured image is nearly all black"**
The capture backend is not seeing the window content. Try running MSFS in
Windowed or Borderless mode, and keep the window visible — the log says which
backend is in use, and only GDI and WGC work for hidden windows.

**Wrong characters**
Let the warmup finish. If glyphs stay wrong, use "Delete Templates" in the GUI
and restart the scraper to relearn from scratch.

**Low frame rate**
Lower `capture_fps` to 15-20, and keep `enable_caching: true`.

**"Module not found"**
Activate the virtual environment and re-run
`pip install -r requirements.txt`.

## Next steps

- Full documentation: [README.md](README.md)
- Check `cdu_scraper.log` when something misbehaves
- Report problems on [GitHub](https://github.com/Swinir/msfs-winwing-mcdu-scraper/issues)
