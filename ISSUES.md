# Known Issues

Tracked findings from the 2026-08-25 codebase audit, plus the planned Qt
migration.  Ordered roughly by severity; the "Status" line is updated as
each one is fixed on `fixes/audit-and-qt-migration`.

---

## #1 — Row OCR caches collide when both MCDUs are enabled

**Type:** bug · **Severity:** high · **Status:** FIXED

`_prev_row_imgs` and `_prev_row_ocr` in `src/mcdu_parser.py` are module-level
dicts keyed by row index alone:

```python
_prev_row_imgs: Dict[int, np.ndarray] = {}
_prev_row_ocr: Dict[int, list] = {}
```

`main.py` parses the captain and the co-pilot MCDU in the same process, in the
same loop iteration.  Both write to these dicts under the same keys, so the
captain's row 3 image is compared against the co-pilot's row 3, and whichever
parses second is served the other's cached OCR result.

The advertised dual-MCDU feature cannot produce correct output as written.

**Fix:** scope the caches per capture source (pass a source id into
`MCDUParser`, or move the caches onto an owning object).

---

## #2 — CLI has no crop-region support

**Type:** bug · **Severity:** high · **Status:** FIXED

`main.py` constructs `WindowCapture(window_title=window_title)` with no
`crop_region`, so the **entire window** is handed to `MCDUParser` and carved
into a 24x14 grid.  Unless the pop-out window happens to be pixel-exactly the
MCDU screen, the CLI produces nonsense.

`config.yaml.example` exposes no crop keys, so there is no way to correct it
from configuration either.

**Fix:** add an optional `crop` block per MCDU in config, plumb it through to
`WindowCapture`, and document it.

---

## #3 — CLI and GUI have forked into two different applications

**Type:** refactor · **Severity:** medium · **Status:** FIXED

`gui.py` grew frame-change detection (MSE), temporal stabilisation
(`STABILITY_FRAMES`), and send-only-on-change.  `main.py` has none of it and
blasts a full 336-cell payload at the CDU every frame regardless of whether
anything changed.

The capture -> parse -> stabilise -> send pipeline is duplicated and divergent.

**Fix:** extract the pipeline into a shared module both front ends drive.
This also unblocks #9, since the Qt GUI should not re-implement it a third time.

---

## #4 — Blocking CPU work runs on the asyncio event loop

**Type:** bug · **Severity:** medium · **Status:** FIXED

`parse_grid()` is synchronous OpenCV work, and during warmup roughly 30 seconds
of EasyOCR.  It is called inline from `async` loops in both front ends with no
`run_in_executor` / `asyncio.to_thread` anywhere in `src/`.

In the CLI this stalls the whole event loop, including the WebSocket task.  It
also means the configured FPS is aspirational: `await asyncio.sleep(max(0, ...))`
degrades to a zero-length sleep and the loop free-runs at whatever rate parsing
allows.

**Fix:** offload `parse_grid()` to a thread executor.

---

## #5 — Disambiguation heuristic overrides the templates it taught

**Type:** design · **Severity:** medium · **Status:** FIXED

`_disambiguate_confusables()` runs at learn time *and* again on every emitted
character in phase 5 of `parse_grid()`.  A correctly learned `O` template is
re-tested by the geometry heuristic on every frame and can be flipped to `D`.

Recognition accuracy for `D O 0 A B 8 1 ] I / C G` is therefore permanently
capped by that heuristic; template learning can never correct it.  If the
heuristic is wrong for a given font rendering, there is no recovery path.

**Fix:** trust confirmed template matches.  Apply disambiguation to OCR and
contour results only, not to high-confidence template hits.

---

## #6 — `+` is silently corrupted to `-` before reaching the CDU

**Type:** bug · **Severity:** medium · **Status:** FIXED

`_CDU_CHAR_MAP` in `src/mobiflight_client.py` contains `'+': '-'`.  The MCDU
displays `+` in temperature and vertical-speed fields, so `+15` arrives at the
hardware as `-15` — wrong data rendered as though it were correct.

Inverting a sign is strictly worse than dropping the character.

**Fix:** map `+` to a space (or verify whether AirbusThales can render `+` and
pass it through).

---

## #7 — Dead configuration surfaces

**Type:** cleanup · **Severity:** low · **Status:** FIXED

Three config/API surfaces that do nothing:

- `mobiflight.max_retries` — stored, `self.retries` is incremented, but never
  compared against anything.  `run()` reconnects forever regardless.
- `performance.enable_caching` — `Config.get_enable_caching()` has no callers.
- `Config.SPECIAL_CHARS` — no callers.

**Fix:** either honour them or remove them.  Silent no-op settings are worse
than absent ones.

---

## #8 — Documentation is stale and self-contradictory

**Type:** docs · **Severity:** low · **Status:** FIXED

- `docs/` was deleted in 5fd630a, but `README.md` links to
  `docs/CALIBRATION.md` and `docs/VISUAL_GUIDE.md`, and `QUICKSTART.md` links
  to `docs/SETUP.md` and `docs/CALIBRATION.md`.  All are 404s.
- `README.md` still lists `docs/` in its project-structure tree.
- README's Configuration section describes screen-coordinate config
  (`left`/`top`/`width`/`height`) that `config.yaml.example` replaced with
  `window_title`.
- The YAML code fence opened in README's Configuration section is never closed.
- README declares "Private/Proprietary"; `LICENSE` is MIT.

---

## #10 — Test suite reads the user's real template file

**Type:** bug · **Severity:** medium · **Status:** FIXED

`TemplateMatcher.__init__` hard-codes its path to
`templates/mcdu_templates.npz` and loads it eagerly.  Every test that
constructs a bare `TemplateMatcher()` therefore inherits whatever glyphs the
user has learned by actually running the app.

With a populated template file present, four existing tests fail:

```
FAILED tests/test_parser.py::TestTemplateMatcher::test_duplicate_not_stored
FAILED tests/test_parser.py::TestTemplateMatcher::test_low_confidence_not_learned
FAILED tests/test_parser.py::TestTemplateMatcher::test_max_templates_per_char
FAILED tests/test_parser.py::TestTemplateMatcher::test_save_and_load
```

CI only stays green because it runs from a fresh checkout where the file does
not exist.  Anyone who runs the app and then runs the tests sees failures that
have nothing to do with their changes.

`templates/*.npz` is also not in `.gitignore`, so learned templates show up as
untracked noise in `git status`.

**Fix:** let `TemplateMatcher` take an explicit path, default the tests to a
temp directory, and gitignore the artefact.

---

## #11 — Region-selector tests assert nothing about the real code

**Type:** bug · **Severity:** medium · **Status:** FIXED

`tests/test_region_selector.py` imports nothing from `src/`.  Every case
recomputes the arithmetic inline and then asserts the recomputation:

```python
scale_x = original_size[0] / scaled_size[0]
x1_orig = int(scaled_selection[0] * scale_x)
self.assertEqual(x1_orig, 50)
```

That asserts `int(50 * 1.0) == 50`.  Twelve of the suite's cases pass whether
or not `RegionSelectorDialog` is correct — the coordinate transform it claims
to cover could be inverted and the tests would stay green.

**Fix:** extract the selection geometry into a GUI-free module and point the
tests at it.  Doing this alongside #9 also means the maths does not have to be
rewritten for Qt.

---

## #12 — Auto-detect returned a box, not a grid

**Type:** bug · **Severity:** high · **Status:** FIXED

The "Auto Detect" button was unusable in practice.  Two independent causes,
both measured against rendered MCDU pages:

**Chrome broke detection outright.**  With a title bar in the capture — which
every real capture has — detection collapsed.  On the PERF page it returned a
77x43 box in the middle of the screen (IoU 0.02); on another it returned the
entire window (IoU 0.51).  Mean IoU across 18 scenarios was 0.67.

**Even a "good" box was the wrong shape.**  The detector returned the bounding
box of the *text*, but the parser needs the bounds of the *grid*.  On a page
whose right-hand columns are blank, the box stops at the last glyph, and
dividing that strip into 24 columns puts every character in the wrong cell.

Precision requirements turned out to be far tighter than IoU suggests:

| crop error | recognition |
|---|---|
| exact | 100% |
| 1/4 cell shift | 97% |
| 1/2 cell shift | **0%** |
| 5% too wide | 41% |

Detection now locks onto the character pitch and phase-aligns the grid to it.
Mean IoU 0.67 -> 0.99, and recognition through the detected crop 4.5% -> 100%.

---

## #13 — The parser resampled every capture

**Type:** bug · **Severity:** high · **Status:** FIXED

`MCDUParser` resized each frame so the grid divided evenly into whole pixels.
Crop sizes are almost never exact multiples, so nearly every frame went
through `cv2.resize`, and INTER_AREA blurs thin glyph strokes.

Worse, the blur depended on the crop size, so templates learned at one size
stopped matching at another.  A crop one pixel wider than the one templates
were learned from took recognition from 100% to 51% — which made the whole
system hostage to exact crop dimensions.

Cells are now partitioned with rounded fractional edges: no interpolation,
and cell sizes differ by at most a pixel.

---

## #14 — Context correction rewrote nav database dates

**Type:** bug · **Severity:** medium · **Status:** FIXED

Validating against a real MCDU capture caught a false positive in the
letter/digit context correction added for #12: `22JAN` came back as `2ZJAN`.

`J`, `A` and `N` are unambiguous letters while both `2`s are ambiguous, so
the token read as alphabetic and the digit-to-letter direction fired.  Dates
in DDMMM form appear on every nav database page, so this was not an edge case.

The digit-to-letter direction is removed.  Its intended benefit — repairing a
waypoint like `L0RNI` to `LORNI` — was never observed on real data, while the
harm was.  The letter-to-digit direction is kept: it repairs the numeric
fields OCR actually struggles with (`46O` -> `460`, `FL3SO` -> `FL350`) and
requires unambiguous digits with no unambiguous letters present.

---

## #15 — '+' is dropped on the way to the display

**Type:** bug · **Severity:** medium · **Status:** FIXED

The real capture shows `+0.0/+0.0` on the IDLE/PERF line, confirming that `+`
appears on genuine A330 MCDU pages.

`mcdu_charset.RENDERABLE` does not include it, so `sanitise_display_data`
replaces it with a space and the CDU shows ` 0.0/ 0.0`.  The sign is lost.

The renderable set is described as deriving from the official MobiFlight
Fenix / FBW / Headwind scripts, with a warning that an unsupported glyph can
freeze the display, so `+` was not added on suspicion alone.  But an MCDU
font that could not draw `+` would be unable to render standard pages, which
is strong circumstantial evidence it is supported.

`+` has been added to `PUNCTUATION`, so it now passes through to the display
and appears in the EasyOCR allowlist.

Checked against MobiFlight's source afterwards, which settles it: there is no
allowlist on their side.  `WinCtrlCduController.ConvertAndSendCduData` does

```csharp
byteList.AddRange(Encoding.UTF8.GetBytes(new char[] { currentChar }));
```

so every character is UTF-8 encoded and forwarded to the device unvalidated,
and the reference `headwind_a33_winwing_cdu.py` filters nothing either.  The
earlier "can freeze the display" warning has no basis in the implementation.

---

## #16 — Colour codes were wrong and incomplete

**Type:** bug · **Severity:** low · **Status:** FIXED

Checked `Config.COLORS` against MobiFlight's own `FormatTable`:

| code | MobiFlight | we had |
|---|---|---|
| `o` | Blue | "brown/blue" |
| `k` | Khaki | *missing* |

Also worth knowing: a code outside that table is rendered **grey** by the
device, not white.

The parser never emits `o` or `k`, so nothing was being sent wrongly — the
documented table was simply inaccurate.  Distinguishing khaki from amber and
yellow reliably would need a capture containing it.

---

## #17 — The display protocol has a fourth field we ignore

**Type:** enhancement · **Severity:** low · **Status:** FIXED

`GetFormatBytes` in MobiFlight reads an optional fourth element per cell:

```csharp
var isInverted = item.Count() > 3 ? item[3].Value<bool>() : false;
```

so a cell can be sent as `[char, colour, size, inverted]` to get reverse
video, which the MCDU uses for some scratchpad messages.  We only ever send
three elements, which is valid and backwards compatible, but inverted cells
currently reach the CDU as ordinary ones.

Now implemented. A reverse-video cell is mostly at foreground brightness
where an ordinary one is mostly background, and the threshold between the
two is measured rather than guessed: across 929 cells from six real
captures, ordinary cells reach at most 40.9% fill and inverted ones start
at 47.8%, so the cut sits at 44%.

The brightness reference comes from each image's own 99th percentile, so a
dim display is judged on its own terms rather than against a fixed level.

Inverted cells are flipped before glyph extraction, so a reverse-video `A`
matches the same learned template as an ordinary one instead of being
learned separately as a filled block with a hole in it. `detect_color`
needed no change: it medians the *bright* pixels, which in an inverted cell
are the block rather than the glyph, so it already reports the block colour.

The fourth element is sent only when set, so ordinary cells stay
three-element exactly as every other integration sends them — verified by
re-parsing the A330 capture and confirming its payload is unchanged.

Found on the Working Title UNS-1 capture, whose ACCEPT prompt is reverse
video; detection is exact on both UNS-1 captures and has no false positives
on the other four.

---

## #18 — '<' and '>' were folded onto the arrows

**Type:** bug · **Severity:** medium · **Status:** FIXED

`_CDU_CHAR_MAP` mapped `<` to ← and `>` to →, described as "MCDU arrow
indicator".  The MCDU draws chevrons and arrows as *different* glyphs, and
both appear on the same page.  Enlarging the two cells from the real capture:

- `R06C00` — a true left arrow: shaft plus a solid triangular head
- `R12C23` — a plain chevron: two strokes, no shaft, no head

So `STATUS/XLOAD>` was reaching the CDU as `STATUS/XLOAD→`.

MobiFlight's reference `headwind_a33_winwing_cdu.py` agrees: its
`REPLACED_CHARS` maps `{` and `}` onto the arrows and leaves `<` and `>`
untouched.  Its braces are how *its data source* encodes an arrow, which is a
different question from what a rendered glyph looks like — our input is OCR
of pixels, so a chevron on screen is a chevron.

Both characters are already renderable, so they now pass through unchanged.

---

## #19 — EasyOCR cannot produce the arrow glyphs

**Type:** limitation · **Severity:** low · **Status:** OPEN

`OCR_ALLOWLIST` is the ASCII subset of the renderable set, so ← → ↑ ↓ ☐ and Δ
are not available to EasyOCR — a CRNN will not reliably produce them anyway.
During warmup an arrow cell can therefore only come back as `<` or `>`, and
that wrong label is what gets learned as a template.

Consequence: on a first run against a page containing arrows, they display as
chevrons.  Low harm — the glyphs are visually close — but wrong.

Fixing #18 removed the accidental cover for this: mapping every `<` to ← used
to make arrows come out right, at the cost of corrupting genuine chevrons.

**Possible fix:** teach the contour detector to recognise arrows.  Measured on
the real capture, the discriminator looks clean — the fraction of glyph rows
spanning more than 75% of the width is 0.20 for the arrow and 0.00 for both
the chevron and `/`, because only the arrow has a shaft.

**Why it is not implemented:** `E`, `T`, `F`, `H` and `+` all have horizontal
strokes that would score similarly, and there is exactly one arrow available
to fit against.  A false positive here gets learned as a template and
permanently corrupts that glyph, which is the failure mode of #5.  This needs
captures containing several arrows before it is worth attempting.

---

## #20 — CLI dropped; dual MCDU moved into the GUI

**Type:** refactor · **Severity:** n/a · **Status:** DONE

The command-line front end is gone — `src/main.py`, `run.bat`, `run.sh` and
its PyInstaller spec.  One front end, one code path.

Dual-MCDU support only existed in the CLI, so it moved into the GUI rather
than disappearing.  It sits under a collapsed **Advanced** disclosure and a
separate tick box, since almost everyone runs a single CDU and it should not
be one stray click away.

Consequences worth knowing:

- `ScraperWorker` now drives a list of MCDUs, one pipeline and one WebSocket
  client each, gathered concurrently.  Its `connected` signal carries the
  MCDU name.
- The window and crop are chosen in the GUI, so they are not configuration
  any more.  `mcdu.*` is gone from `config.yaml.example`, along with the
  getters that read it — `get_crop_region`, `get_captain_window_title`,
  `get_copilot_window_title`, `get_captain_enabled`, `get_copilot_enabled`.
  Keeping them would have recreated the dead-setting problem of #7.  An old
  config file with a stale `mcdu:` section still loads; the section is
  ignored.
- The crop *validation* added in #2 went with it.  Crop values now come from
  the region selector, which cannot produce an invalid one.
- Starting with both MCDUs pointed at the same window is refused.

**Not verified:** the co-pilot path has been exercised only with fake
captures and a fake client.  Two real pop-out windows and a second CDU would
confirm it.

---

## #21 — Aircraft profiles: support other FMS families

**Type:** feature · **Severity:** n/a · **Status:** DONE (awaiting real captures)

The scraper is aircraft-agnostic — it OCRs pixels and learns glyphs at
runtime — so supporting other aircraft meant profiles, not per-plane code.
What actually varies between FMS families:

- grid dimensions,
- the font the WinWing hardware loads,
- whether label rows render small,
- and the template store (Boeing glyphs must never match Airbus templates).

`src/aircraft_profiles.py` ships four: Airbus MCDU (24x14, AirbusThales —
the legacy store, so existing learned templates keep working), Boeing CDU
(24x14, Boeing), UNS-1 (24x10, all-large, experimental), and Custom (grid
set under Advanced → Override grid size).  Grids smaller than the hardware
24x14 are padded top-left before sending; `set_template_store()` switches
stores atomically, saving the outgoing one.

**Review of the proposed aircraft list** (originally from Gemini):

- *Dropped — wrong premise:* iniBuilds A350 has no MCDU at all (KCCU +
  MFD pages); TFDi MD-11, Maddog X, iniBuilds A300/A340, Fenix, FBW and
  PMDG all have **native MobiFlight scripts** already, so scraping them is
  redundant.
- *Kept:* default/iniBuilds Airbus suite, LatinVFR/Horizon (default-based
  avionics → Airbus profile); ATR 42/72-600 (Thales FMS 220, added on
  request → its own profile: same 24x14 Thales layout, separate template
  store because the ATR renders glyphs differently); default 747-8/787, C-17, E-7, GNLU910 →
  Boeing profile; Black Square + Just Flight UNS-1 fleet → UNS-1 profile;
  GNS-XLS and other unknowns → Custom.
- *Unverified:* the E-7 Wedgetail's presence/CDU in MSFS 2024.

**Open, pending real pop-out captures:**

- UNS-1 grid dimensions are a best guess (24x10). Measured on synthetic
  24x10 pages: detection IoU 0.99, recognition 100% through the detected
  crop — but the real UNS-1 CRT may differ in rows, aspect and glyph style.
- Padding alignment is top-left; whether UNS-1 rows should instead align to
  the hardware's line-select keys needs hardware-in-hand judgement.
- Boeing profile is untested against a real 747/787/C-17 pop-out.

---

## #22 — Auto Detect does not handle UNS-1 displays

**Type:** limitation · **Severity:** medium · **Status:** FIXED

Two real UNS-1 captures (Working Title, and Just Flight's BAe 146) showed
that the pitch detector built for airliner CDUs does not transfer:

**The grid is 24x11, not 24x10.** Both captures agree: ten lines of text and
one blank. The profile was corrected from the original guess.

**A UNS-1 is only approximately a uniform grid.** An Airbus CDU is a true
lattice — all 12 text bands of the A330 capture fit inside their cells. On
the UNS-1 the body rows are evenly spaced (WT 28.4px ±6%, JF 25.5px ±0%) but
the title and bottom lines sit off that lattice, separated by 36-62px where
the body pitch is 25-28. No uniform grid holds every row: the best fit
manages 6/10 (WT) and 9/10 (JF).

**Its rows touch.** The WT display has large glyphs with tight leading, so
five text rows merge into one 141px ink band. Row detection assumes a gap
between lines, which holds for a CDU and not here.

**What was wrong.** Three separate faults, found by measuring rather than
by tuning:

1. *Merged rows were never split.* `_split_touching_rows` had been written
   during the first attempt but was lost in a revert and never committed, so
   the WT capture's five touching rows stayed a single 141px band and
   nothing downstream could recover them.
2. *A 9px stub of window chrome survived the ink mask* and, sitting above
   every real row, forced the grid origin ten pixels high — putting a
   boundary through every row below it.  It needs two signals to reject
   safely: touching the chrome boundary is not enough, because the ATR's
   title row begins exactly there; being much shorter than a normal row is
   not enough either, because the ATR draws a 3px dashed separator.  A band
   that is *both* is chrome.
3. *The grid was never checked against the text.* The lattice fit produced a
   plausible pitch and phase and stopped.

**The fix that stuck.** Rather than tune estimators until every capture
happened to pass — the mistake of the first attempt, which made things worse
overall — the detector now *scores* candidate grids and keeps the best.
`_refine_grid` and `_refine_columns` search a small neighbourhood of the
estimate, ranked by how many text rows and glyphs sit wholly inside a cell.
Because the starting estimate is the baseline they are scored against, they
cannot regress a display that already worked.

**Results.** All five previously-working captures detect unchanged.  On the
UNS-1 captures every text row now lands in a cell of its own, and the
detector scores *better than the hand-picked crops* that were recorded when
this issue was opened: WT 5 rows uncut against 3, JF 9 against 1.  The tests
were switched to exercise Auto Detect rather than those crops.  Detection
takes about 35ms.

**What has not changed.** These displays are still only approximately
uniform grids — the title and bottom lines sit off the body lattice, so some
band is always clipped however well the grid is placed.  Detection now works
despite that rather than because it was solved, and
`test_a_uniform_grid_still_cannot_hold_every_row` keeps that on the record.

---

## #23 — ATR, Avro GNLU and Starship captures: measurements and fixes

**Type:** feature/bug · **Severity:** n/a · **Status:** DONE (Starship out of scope)

Three more aircraft measured from real pop-out captures.

**ATR 42/72-600 (FMS 220)** — a true 24x14 Thales grid; the existing `atr`
profile was already right.  Result on the INIT page through the auto-detected
crop: 336/336 occupancy, 147/147 recognition, `+01H00` cyan intact.  Getting
there surfaced three detector bugs, each with a one-capture reproduction:

- *Dark chrome passed the ink filter.* The old rule assumed window chrome is
  light; chrome rows are now identified by elevated background and flattened
  before the ink pass (mask-after ate the title row flush beneath them).
- *Chrome bled into the top of row 0.* The lattice may legally start a few px
  inside the title bar (glyphs sit top-of-cell); the crop is now clamped to
  the chrome boundary when the trim is under a third of a cell.
- *A 1px edge run and a sparse frame band skewed the fit.* Glyph runs now
  need >=2px width; near-empty wide bands are rejected as frame debris.

**Just Flight Avro RJ (GNLU)** — renders **25 columns**, one more than the
hardware.  Also re-confirmed the adjacent-spacings pitch bias from #22, fixed
this time by refining over whole-line spans (glyphs are centred in cells, so
first-to-last run distance is an exact cell multiple).  New `avro_gnlu`
profile (25x14, own template store); rows are squeezed onto the 24-column
hardware by dropping blank cells - trailing, then leading, then from the
widest interior gap - so `<` and `>` line-select prompts at both edges
survive.  Losing *something* on full rows is unavoidable; those truncate
right.

**Black Square Starship (FMS-850)** — measured at roughly 50 columns, about
twice the hardware's width, and **not supported**.  It was mis-filed as
UNS-1 in the original aircraft list; the other Black Square aircraft use the
Working Title UNS-1 and are covered by that profile.  A test pins the
measurement so the claim gets revisited if a future capture measures
narrower.

---

## #24 — Fokker 70/100: row pitch broken by label/value spacing

**Type:** bug · **Severity:** medium · **Status:** FIXED

The Just Flight Fokker 70/100 capture detected with its rows compressed —
pitch 19.6px against a true 21.7 — so neighbouring rows bled into one
another and read identically.

Cause: on this FMC a label row sits closer to its value row than a uniform
pitch implies, because the small font's glyphs are centred differently
within their cell.  Centre-to-centre gaps therefore alternate 26px and 17px,
and choosing the pitch by the most common gap picks one of the two rather
than their 21.7px average.

Several estimators were tried against all seven captures.  Each one that
fixed the Fokker broke something else: the median of gaps got the Fokker
right but pushed the ATR from 23.6 to 25.8; total-span-over-total-cells got
six of seven within 2.7% but the Avro 12% wrong, because two of its bands
are split spuriously and contribute sub-cell gaps.

Rather than tune a threshold until every capture happened to pass — the
mistake made in #22 — the detector now computes **both** candidate pitches
and keeps whichever puts more text rows wholly inside a cell.  That decides
per capture against the thing that actually matters, and cannot regress a
display the existing estimator already handles.  Verified: all six earlier
captures detect byte-identically, and the Fokker now gets 21.71.

The Fokker profile itself (24x14, `labels_small`, green monochrome) reads
its page back at 336/336 occupancy and 119/119 characters, slashed zeros
included.  Its column count is the 24-column CDU convention rather than a
measurement: the pages captured so far use only about 17 columns, so the
display's true width cannot be read off them.

---

## #25 — A cold start on a real MCDU read as garbage

**Type:** bug · **Severity:** high · **Status:** FIXED

A session against an Airbus INIT page came back as `CS S  S S I    D J /C J`,
`C0 T INNEX` and ` SSSSSSSI`, and got worse the longer it ran.  Every test
passed throughout, because every recognition test taught the template
matcher from ground truth first and so never exercised the path a user
actually takes: an empty store, EasyOCR warmup, and whatever comes out.

Measured on that path — detect the region, parse from an empty store, score
against the transcription — the three captures with ground truth read 90.8%,
93.9% and 78.2%.  Five separate causes, each measured before and after:

**Entry boxes were read as letters.**  Two thirds of a cold-start Airbus page
is the hollow square that marks a field the crew must fill in.  EasyOCR has
no box in its alphabet, so it named the nearest letter; those letters were
then learned as templates and spread into genuine text.  The shape is
unmistakable — ink all the way round the border and none inside — so it is
now recognised structurally, ahead of both engines.  26 of 26 found across
four cell sizes, and no letter, digit or symbol mistaken for one.

**The geometry detector was wrong more often than right.**  An audit of the
symbol detector over 2831 labelled glyphs found it fired 260 times and was
wrong 113: `L` and `C` read as brackets, and `L`, `E`, `F`, `5` and `I` read
as degree signs, because the tests asked only how big a glyph was and where
it sat.  Rewritten around what actually separates each pair — a bracket's
square corners and full-height stem, a degree sign's ring, a chevron's
per-row ink profile — it now names 427 and claims nothing else.  Being
reliable, its answer was promoted ahead of both engines rather than used as
a last resort, and any other engine proposing a shape it examined and
rejected is overruled.  That is what had put a bracket inside `ACTIVE` and
`CONSUMPTION`.

**Characters were dropped when two rounded to the same column.**  A
character's position comes from dividing an OCR word's bounding box evenly,
so a box a few per cent narrow accumulates error along the word until two
characters claim one cell — and the loser was discarded, leaving a hole.
That is what turned `+0.0/+0.0` into `+0. 0I+.0`.  Assignment is now by
dynamic programming: order is preserved, characters may only land on cells
that hold ink, and one may be dropped only when OCR returned more characters
than there are cells to put them in.

**Warmup ran the same OCR call twenty-five times.**  Five rounds over three
scales, plus a row pass that looped over two scales and then ignored the
variable.  The calls are deterministic and do not consult the template
store, so rounds two to five recomputed round one exactly — and the
"consensus" they fed counted one reading five times, which is how a single
wrong reading cleared a two-vote bar on its own.  Now one pass per genuinely
different view, eight in all: a third of the work, and agreement between
views that means something.  A real session spent 145s here.  One of the
eight thickens the strokes before the CRNN sees them, which is worth 1.7
points on the Fokker's one-pixel CRT font and nothing on the Airbus - the
point of a view is to be different, not better.

**Learning got looser exactly where the evidence got thinner.**  `learn()`
committed straight to the store once warmup was over, on the reasoning that
the character set was by then mostly covered.  A warmup vote is one of six
passes over the same pixels; a later one is a single unverified guess.  The
session's store grew 80 → 90 → 122 → 126 templates while it ran and read
worse with every one.  Consensus now applies after warmup too, and at a
higher bar.

The veto is scoped to what the pass reliably finds, and two real captures
drew that line.  The arrows were dropped from it because the corpus holds
one left arrow and no right one: the rule does not fire on the UNS-1's
reverse-video ACCEPT prompt, and vetoing on that silence deleted an arrow a
template had read correctly.  Round brackets were dropped for the same
reason - folding them onto square ones caught a few `C` that EasyOCR had
proposed as `(`, and deleted the real parentheses of the ATR's `GPS (UTC)`.

The row cache was storing the wrong thing.  An unchanged row is served from
`_prev_row_ocr` on every later frame, and that held the raw OCR reading -
but the geometry pass and the template matcher both feed the assembled grid
without passing through it, so a row lost its dashes, slashes and entry
boxes the moment it went quiet.  It now caches what the row displayed.

Two further changes, both measured rather than reasoned:

- `_disambiguate_confusables` had been reinstated at three points including
  `learn()`, undoing #5.  Against the real captures it corrupted 14 of 419
  correct characters — `1`→`]` six times, `O`/`0`→`D` eight.  Two of its
  branches (`N`/`H`, `S`/`5`) had never been reachable, and enabling them
  cost another 30.  Scoped back to raw OCR proposals, with the `D`/`O` test
  rebuilt on corner squareness and the `]`/`1` test deleted, the damage is 1
  in 419 and it still repairs 97 of 126 injected pair errors.
- Cells whose glyphs are the same shape now have to read as the same
  character.  A page draws each character from one bitmap, so this is
  evidence from the page itself rather than a dictionary of expected text,
  and it holds for any aircraft.  Grouping at 0.93 NCC over the corpus
  produced 538 groups covering 2283 glyphs with one impure group.

Cold-start accuracy on the three captures with ground truth: **90.8% → 99.3%
(A330), 93.9% → 100% (ATR), 78.2% → 93.3% (Fokker)**.  Warmup 80s → 35s.

The store format version is bumped, so a store written by the old learner is
discarded on first run rather than asking anyone to find and delete it.

`tests/test_geometry_recognition.py` scores the geometry pass over every
labelled glyph the project has and pins the assignment behaviour.  The
thresholds were fitted to that same corpus, so the score is not
out-of-sample; what it does guarantee is that the pass never trades a letter
for a symbol, which is the failure that made the old version dangerous.

---

## #26 — The stabiliser promoted the jitter it exists to suppress

**Type:** bug · **Severity:** medium · **Status:** FIXED

`DisplayStabiliser` had been rewritten to promote whichever value occurred
most often in a sliding window of five frames.  Three sightings out of five
describes alternating noise as well as it describes a settled value, so a
cell flickering `0 O 0 O O` promoted the `O` — the exact flicker on the
physical CDU the class was written to prevent.  It also broke promotion at
`stability_frames=1`, and with it the reverse-video flag change.

**Fix:** restored the consecutive-run rule — a new value must be seen
`stability_frames` times in a row, and any sighting of the displayed value
resets the count.  `tests/test_stabiliser.py` now records why the windowed
version was rejected.

---

## #9 — Migrate the GUI from Tkinter to PySide6

**Type:** feature · **Severity:** n/a · **Status:** FIXED

Replace the Tkinter front end with Qt (PySide6, LGPL — compatible with the MIT
licence and with shipping a PyInstaller `.exe`).

Scope:

- `src/gui.py` — main window: window picker, controls, log pane.
- `src/region_selector.py` — the crop/region selection dialog with its 24x14
  grid overlay and drag-resize handles.
- Replace the `queue` + `root.after(100, ...)` log pump with Qt signals.
- Replace the manual background thread + `asyncio.new_event_loop()` with a
  `QThread` worker, or keep the thread and marshal via signals.
- Update both PyInstaller specs, `requirements.txt`, and the CI workflow's
  hidden imports.

Depends on #3 — extract the shared pipeline first so the Qt GUI drives the same
code path as the CLI rather than duplicating it a third time.
