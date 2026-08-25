# Quick Start Guide

Get the MSFS A330 WinWing MCDU Scraper running in about five minutes.

## What it does

MSFS draws the A330 MCDU on screen.  This app screenshots that window, reads
the 24x14 character grid back out of the pixels, and forwards it to MobiFlight,
which drives your physical WinWing CDU display.

It does not talk to the simulator directly — it reads whatever is on screen.

## Before you start

- [ ] Windows 10/11
- [ ] MSFS 2020/2024 with the default Airbus A330
- [ ] WinWing CDU hardware
- [ ] MobiFlight **WinWing MCDU Connector** installed and running
- [ ] Python 3.9-3.13 — only if running from source (the `.exe` needs nothing)

## Fastest path: the GUI

The GUI needs no configuration file for the capture area — you select it
visually.

1. **Pop out the MCDU** in MSFS: right-click the MCDU → "Pop Out".
2. **Start MobiFlight** WinWing MCDU Connector.
3. **Run the GUI**: double-click `MSFS-MCDU-Scraper-GUI.exe`, or `run_gui.bat`
   from source.
4. **Select your window** from the dropdown (look for "Flight Simulator" or
   "MCDU"). Tick "Show all windows" if it is not listed.
5. **Click "Select Screen Area"**, then "Auto Detect" — or drag a box around
   just the MCDU screen. The 24x14 grid overlay shows how the characters will
   be carved up; the boundaries should sit between characters, not through them.
6. **Click "Start Scraper"**.

The first run spends roughly 30 seconds learning glyph shapes ("Template
warmup" in the log). After that, recognition runs from the learned templates
and is fast. The learned glyphs are saved, so this happens once.

Once running, the MCDU window may be minimised or behind other windows,
provided capture landed on the GDI or WGC backend (the log says which).

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

## Using the CLI

The CLI has no window picker, so it needs `config.yaml`:

```bash
copy config.yaml.example config.yaml
```

A minimal working configuration:

```yaml
mcdu:
  captain:
    enabled: true
    # Substring of the pop-out window's title, matched case-insensitively.
    window_title: "Microsoft Flight Simulator"
    # Which part of that window holds the MCDU screen.
    crop:
      x: 120
      y: 80
      width: 480
      height: 280

mobiflight:
  captain_url: "ws://localhost:8320/winwing/cdu-captain"
  font: "AirbusThales"

performance:
  capture_fps: 30
```

**The `crop` block matters.** Without it the entire window is carved into the
24x14 grid, which only produces sensible output if the window happens to be
exactly the MCDU screen. The CLI warns when no crop is configured.

Easiest way to find the numbers: run the GUI once, use "Select Screen Area",
and copy the `X`, `Y`, `W`, `H` values it reports into the `crop` block.

Then:

```bash
cd src && python main.py
```

Expected output:

```
============================================================
MSFS A330 WinWing MCDU Scraper
============================================================
... Configuration loaded successfully
... Initializing Captain MCDU...
... Captain MCDU crop region: x=120, y=80, w=480, h=280
... MobiFlight connected at ws://localhost:8320/winwing/cdu-captain
... Font set to: AirbusThales
... Starting capture pipelines...
... Captain pipeline running at 30 FPS
```

## Both MCDUs

Enable each one with its own window and crop:

```yaml
mcdu:
  captain:
    enabled: true
    window_title: "Microsoft Flight Simulator"
    crop: { x: 120, y: 80, width: 480, height: 280 }

  copilot:
    enabled: true
    window_title: "Microsoft Flight Simulator (1)"
    crop: { x: 120, y: 80, width: 480, height: 280 }
```

Each runs its own capture pipeline concurrently.

## Troubleshooting

**"No config.yaml found"**
Copy `config.yaml.example` to `config.yaml`. Only the CLI needs this.

**"WebSocket connection closed" / connection refused**
Start the MobiFlight WinWing MCDU Connector first. It listens on
`localhost:8320`. The scraper keeps retrying, backing off as failures repeat.

**Blank or garbled CDU display**
Almost always the capture area. Use the GUI's "Select Screen Area" and check
the grid overlay lines up with the characters. For the CLI, check `crop`.

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
- Check `mcdu_scraper.log` when something misbehaves
- Report problems on [GitHub](https://github.com/Swinir/msfs-winwing-mcdu-scraper/issues)
