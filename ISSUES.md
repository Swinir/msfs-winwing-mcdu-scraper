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

**Type:** docs · **Severity:** low · **Status:** open

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

## #9 — Migrate the GUI from Tkinter to PySide6

**Type:** feature · **Severity:** n/a · **Status:** open

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
