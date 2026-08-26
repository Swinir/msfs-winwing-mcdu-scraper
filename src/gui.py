"""
GUI application for MSFS A330 WinWing MCDU Scraper (PySide6).

Provides window selection, screen-area selection, log viewing and control.

Threading model: the capture pipeline is asyncio, so it runs in a worker
thread with its own event loop.  Nothing in that thread touches a widget
directly - log records reach the UI through a Qt signal, which Qt delivers
on the main thread.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Add src to path (handle both normal and PyInstaller frozen execution)
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle: modules are in the same temp directory
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aircraft_profiles import PROFILES, AircraftProfile
from config import Config
from mcdu_parser import set_template_store, _get_template_matcher
from mcdu_parser import _prev_row_imgs, _prev_row_ocr
from mobiflight_client import MobiFlightClient
from pipeline import MCDUPipeline, PipelineSettings
from region_selector import RegionSelectorDialog
from window_capture import WindowCapture, WINDOWS_AVAILABLE

MSFS_KEYWORDS = ('microsoft flight simulator', 'msfs', 'flight simulator',
                 'mcdu', 'airbus')


class _LogEmitter(QObject):
    """Signal carrier for SignalLogHandler.

    Deliberately a plain QObject rather than a base of the handler:
    multiply inheriting from logging.Handler and QObject does not reliably
    register Signals in PySide6, and the failure is silent — records simply
    never arrive.
    """

    record = Signal(str)


class SignalLogHandler(logging.Handler):
    """Forwards log records to the UI thread through a Qt signal.

    Qt widgets may only be touched from the thread that created them, and
    log records arrive from the pipeline's worker thread.  Emitting a queued
    signal hands the record over safely.
    """

    def __init__(self) -> None:
        super().__init__()
        self.emitter = _LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.record.emit(self.format(record))
        except Exception:
            # Report through logging's own channel rather than swallowing it;
            # a silent except here hid this very class being broken.
            self.handleError(record)


@dataclass
class McduSpec:
    """One MCDU to drive: where to capture it and where to send it."""

    name: str
    capture: object
    websocket_uri: str


class ScraperWorker(QObject):
    """Runs one capture pipeline per MCDU on its own thread and event loop."""

    finished = Signal()
    failed = Signal(str)
    connected = Signal(str)

    def __init__(self, config: Config, specs: List[McduSpec],
                 columns: int = 24, rows: int = 14,
                 small_font_rule: str = "labels_small",
                 font: str = "AirbusThales") -> None:
        super().__init__()
        self.config = config
        self.specs = list(specs)
        self.columns = columns
        self.rows = rows
        self.small_font_rule = small_font_rule
        self.font = font
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pipelines: List[MCDUPipeline] = []
        self._stopping = False

    def start(self) -> None:
        """Entry point for the worker thread."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run())
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Scraper thread failed: %s\n%s", exc, traceback.format_exc(),
            )
            self.failed.emit(str(exc))
        finally:
            if self._loop is not None:
                self._loop.close()
                self._loop = None
            self.finished.emit()

    def stop(self) -> None:
        """Ask every pipeline to stop.  Safe to call from the UI thread."""
        self._stopping = True
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        for pipeline in list(self._pipelines):
            loop.call_soon_threadsafe(pipeline.stop)

    async def _drive(self, spec: McduSpec) -> None:
        """Connect one MCDU and run its pipeline until stopped."""
        client = MobiFlightClient(
            websocket_uri=spec.websocket_uri,
            font=self.font,
            max_retries=self.config.get_max_retries(),
        )
        client_task = asyncio.create_task(client.run())
        try:
            await client.connected.wait()
            self.connected.emit(spec.name)

            pipeline = MCDUPipeline(
                name=spec.name,
                capture=spec.capture,
                client=client,
                columns=self.columns,
                rows=self.rows,
                small_font_rule=self.small_font_rule,
                settings=PipelineSettings(
                    fps=self.config.get_capture_fps(),
                    enable_caching=self.config.get_enable_caching(),
                ),
            )
            self._pipelines.append(pipeline)
            # stop() may have been called while we were still connecting.
            if self._stopping:
                return
            await pipeline.run()
        finally:
            client_task.cancel()
            try:
                await client_task
            except asyncio.CancelledError:
                pass
            await client.close()

    async def _run(self) -> None:
        # Each MCDU gets its own pipeline so one does not throttle the other.
        # Its name also namespaces the parser's row caches, so the two must
        # differ -- see the dual-MCDU cache collision in ISSUES.md #1.
        await asyncio.gather(*(self._drive(spec) for spec in self.specs))


class MCDUScraperWindow(QMainWindow):
    """Main window: window picker, controls and log pane."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MSFS WinWing MCDU Scraper")
        self.resize(960, 720)

        self.running = False
        self.window_list: list = []
        # Per-MCDU capture state, keyed by name.  'captain' is always
        # present; 'copilot' only when the user opts in.
        self.captures: dict = {}
        self.crop_regions: dict = {"captain": None, "copilot": None}
        self.worker: Optional[ScraperWorker] = None
        self.thread: Optional[QThread] = None

        self._build_ui()
        self._setup_logging()

        try:
            self.config = Config()
            self.log("Configuration loaded successfully")
        except Exception as exc:
            self.log(f"Warning: Could not load config: {exc}", "WARNING")
            self.config = None

        if WINDOWS_AVAILABLE:
            self.refresh_windows()
        else:
            self.log("Window capture not available "
                     "(Windows only, or pywin32 not installed)", "WARNING")
            self.window_combo.setEnabled(False)

    # ------------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel("MSFS WinWing MCDU Scraper")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(self._build_window_group())
        layout.addWidget(self._build_advanced_section())
        layout.addWidget(self._build_control_group())
        layout.addWidget(self._build_log_group(), stretch=1)

    def _build_window_group(self) -> QGroupBox:
        group = QGroupBox("Window Selection")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("Select MCDU Window:"), 0, 0)

        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(420)
        grid.addWidget(self.window_combo, 0, 1)

        refresh = QPushButton("Refresh Windows")
        refresh.clicked.connect(self.refresh_windows)
        grid.addWidget(refresh, 0, 2)

        self.show_all_checkbox = QCheckBox("Show all windows")
        self.show_all_checkbox.toggled.connect(self.refresh_windows)
        grid.addWidget(self.show_all_checkbox, 0, 3)

        self.select_area_button = QPushButton("Select Screen Area")
        self.select_area_button.clicked.connect(
            lambda: self.select_screen_area("captain"))
        grid.addWidget(self.select_area_button, 1, 1)

        self.crop_info_label = QLabel("No crop region set")
        grid.addWidget(self.crop_info_label, 1, 2, 1, 2)

        grid.addWidget(QLabel("Aircraft:"), 2, 0)
        self.profile_combo = QComboBox()
        for profile in PROFILES.values():
            self.profile_combo.addItem(profile.label, profile.id)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        grid.addWidget(self.profile_combo, 2, 1)

        grid.setColumnStretch(1, 1)
        return group

    def _build_advanced_section(self) -> QWidget:
        """Second-MCDU controls, kept out of the way.

        Almost everyone drives a single CDU, so the co-pilot side stays
        hidden behind a collapsed disclosure rather than sitting on the main
        surface where it invites a stray click.
        """
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setAutoRaise(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        outer.addWidget(self.advanced_toggle, alignment=Qt.AlignLeft)

        self.copilot_group = QGroupBox("Co-Pilot MCDU (second CDU)")
        self.copilot_group.setCheckable(True)
        self.copilot_group.setChecked(False)
        self.copilot_group.toggled.connect(self._toggle_copilot)
        self.copilot_group.setVisible(False)

        grid = QGridLayout(self.copilot_group)
        grid.addWidget(QLabel("Select Co-Pilot Window:"), 0, 0)

        self.copilot_window_combo = QComboBox()
        self.copilot_window_combo.setMinimumWidth(420)
        grid.addWidget(self.copilot_window_combo, 0, 1)

        self.copilot_select_area_button = QPushButton("Select Screen Area")
        self.copilot_select_area_button.clicked.connect(
            lambda: self.select_screen_area("copilot"))
        grid.addWidget(self.copilot_select_area_button, 1, 1)

        self.copilot_crop_info_label = QLabel("No crop region set")
        grid.addWidget(self.copilot_crop_info_label, 1, 2)

        grid.setColumnStretch(1, 1)
        outer.addWidget(self.copilot_group)

        # Grid override: for FMS types whose dimensions we do not know yet
        # (GNS-XLS, ...) or when a built-in profile's guess is wrong.
        self.grid_override_group = QGroupBox("Override grid size")
        self.grid_override_group.setCheckable(True)
        self.grid_override_group.setChecked(False)
        self.grid_override_group.setVisible(False)

        override_row = QHBoxLayout(self.grid_override_group)
        override_row.addWidget(QLabel("Columns:"))
        self.grid_cols_spin = QSpinBox()
        self.grid_cols_spin.setRange(8, 40)
        self.grid_cols_spin.setValue(24)
        override_row.addWidget(self.grid_cols_spin)
        override_row.addWidget(QLabel("Rows:"))
        self.grid_rows_spin = QSpinBox()
        self.grid_rows_spin.setRange(4, 20)
        self.grid_rows_spin.setValue(14)
        override_row.addWidget(self.grid_rows_spin)
        override_row.addStretch()
        outer.addWidget(self.grid_override_group)
        return container

    def _toggle_advanced(self, shown: bool) -> None:
        self.advanced_toggle.setArrowType(
            Qt.DownArrow if shown else Qt.RightArrow)
        self.copilot_group.setVisible(shown)
        self.grid_override_group.setVisible(shown)

    def _on_profile_changed(self) -> None:
        profile = self._current_profile()
        # Seed the override spinboxes with the profile's grid so overriding
        # starts from the right numbers.
        self.grid_cols_spin.setValue(profile.columns)
        self.grid_rows_spin.setValue(profile.rows)
        columns, rows = self._current_grid()
        self.log(f"Aircraft profile: {profile.label} "
                 f"({columns}x{rows}, font {profile.font})")
        if profile.notes:
            self.log(profile.notes)

    def _toggle_copilot(self, enabled: bool) -> None:
        if enabled and not self.copilot_window_combo.count():
            self.refresh_windows()
        if enabled:
            self.log("Co-Pilot MCDU enabled - select its window and screen area")

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("Control")
        row = QHBoxLayout(group)

        self.status_label = QLabel("Status: Stopped")
        self.status_label.setStyleSheet("font-weight: bold;")
        row.addWidget(self.status_label)
        row.addStretch()

        self.start_button = QPushButton("Start Scraper")
        self.start_button.clicked.connect(self.start_scraper)
        row.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Scraper")
        self.stop_button.clicked.connect(self.stop_scraper)
        self.stop_button.setEnabled(False)
        row.addWidget(self.stop_button)

        self.delete_templates_button = QPushButton("Delete Templates")
        self.delete_templates_button.clicked.connect(self.delete_templates)
        row.addWidget(self.delete_templates_button)

        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Logs")
        layout = QVBoxLayout(group)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        # Bounded history: at 30 FPS an unbounded pane grows without limit.
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self.log_view)

        clear = QPushButton("Clear Logs")
        clear.clicked.connect(self.log_view.clear)
        layout.addWidget(clear)

        return group

    def _setup_logging(self) -> None:
        handler = SignalLogHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        handler.emitter.record.connect(self._append_log)

        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        self._log_handler = handler

    # ------------------------------------------------------------------
    #  Logging
    # ------------------------------------------------------------------
    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        self.log_view.moveCursor(QTextCursor.End)

    def log(self, message: str, level: str = "INFO") -> None:
        """Log through the standard logging machinery."""
        logging.getLogger("gui").log(
            getattr(logging, level, logging.INFO), message,
        )

    # ------------------------------------------------------------------
    #  Window selection
    # ------------------------------------------------------------------
    def refresh_windows(self) -> None:
        if not WINDOWS_AVAILABLE:
            self.log("Window capture not available on this platform", "WARNING")
            return

        try:
            windows = WindowCapture.list_windows()

            if self.show_all_checkbox.isChecked():
                filtered = windows
            else:
                filtered = [
                    (hwnd, title) for hwnd, title in windows
                    if any(k in title.lower() for k in MSFS_KEYWORDS)
                    or len(title) < 50
                ]
                if not filtered:
                    filtered = windows[:20]

            self.window_list = filtered
            labels = [f"{title} (HWND: {hwnd})" for hwnd, title in filtered]
            for combo in self._window_combos():
                current = combo.currentIndex()
                combo.clear()
                combo.addItems(labels)
                if 0 <= current < len(labels):
                    combo.setCurrentIndex(current)
            self.log(f"Found {len(windows)} windows, showing {len(filtered)}")
        except Exception as exc:
            self.log(f"Error refreshing windows: {exc}", "ERROR")

    def _window_combos(self) -> List[QComboBox]:
        combos = [self.window_combo]
        if getattr(self, "copilot_window_combo", None) is not None:
            combos.append(self.copilot_window_combo)
        return combos

    def _combo_for(self, mcdu: str) -> QComboBox:
        return (self.copilot_window_combo if mcdu == "copilot"
                else self.window_combo)

    def _selected_window(self, mcdu: str = "captain") -> Optional[tuple]:
        index = self._combo_for(mcdu).currentIndex()
        if index < 0 or index >= len(self.window_list):
            return None
        return self.window_list[index]

    def _current_profile(self) -> AircraftProfile:
        return PROFILES[self.profile_combo.currentData()]

    def _current_grid(self) -> tuple:
        if self.grid_override_group.isChecked():
            return (self.grid_cols_spin.value(), self.grid_rows_spin.value())
        profile = self._current_profile()
        return (profile.columns, profile.rows)

    def _copilot_enabled(self) -> bool:
        return (getattr(self, "copilot_group", None) is not None
                and self.copilot_group.isChecked())

    def _enabled_mcdus(self) -> List[str]:
        return ["captain"] + (["copilot"] if self._copilot_enabled() else [])

    def _crop_label_for(self, mcdu: str) -> QLabel:
        return (self.copilot_crop_info_label if mcdu == "copilot"
                else self.crop_info_label)

    def select_screen_area(self, mcdu: str = "captain") -> None:
        if not WINDOWS_AVAILABLE:
            QMessageBox.critical(self, "Error",
                                 "Window capture not available on this platform")
            return

        selected = self._selected_window(mcdu)
        if selected is None:
            QMessageBox.critical(
                self, "Error", f"Please select a window for the {mcdu} MCDU first")
            return

        hwnd, title = selected
        try:
            self.log(f"[{mcdu}] Capturing preview from: {title}")
            temp_capture = WindowCapture(window_handle=hwnd)
            try:
                preview = temp_capture.capture()
            finally:
                temp_capture.close()

            dialog = RegionSelectorDialog(self, preview,
                                          self.crop_regions.get(mcdu),
                                          grid_size=self._current_grid())
            result = dialog.show()

            label = self._crop_label_for(mcdu)
            if result:
                self.crop_regions[mcdu] = result
                x, y, w, h = result
                label.setText(f"Crop: X={x}, Y={y}, W={w}, H={h}")
                label.setStyleSheet("color: green;")
                self.log(f"[{mcdu}] Screen area selected: "
                         f"X={x}, Y={y}, W={w}, H={h}")
            else:
                self.log(f"[{mcdu}] Screen area selection cancelled")

        except Exception as exc:
            self.log(f"[{mcdu}] Error selecting screen area: {exc}", "ERROR")
            QMessageBox.critical(self, "Error", f"Failed to capture window: {exc}")

    # ------------------------------------------------------------------
    #  Start / stop
    # ------------------------------------------------------------------
    def _url_for(self, mcdu: str) -> str:
        return (self.config.get_copilot_url() if mcdu == "copilot"
                else self.config.get_captain_url())

    def _build_specs(self) -> Optional[List[McduSpec]]:
        """Open a capture per enabled MCDU.  None if anything is unusable."""
        specs: List[McduSpec] = []
        for mcdu in self._enabled_mcdus():
            selected = self._selected_window(mcdu)
            if selected is None:
                QMessageBox.critical(
                    self, "Error",
                    f"Please select a window for the {mcdu} MCDU")
                return None

            hwnd, title = selected
            crop = self.crop_regions.get(mcdu)
            self.log(f"[{mcdu}] Starting with window: {title}")
            capture = WindowCapture(window_handle=hwnd, crop_region=crop)
            self.captures[mcdu] = capture

            if crop:
                x, y, w, h = crop
                self.log(f"[{mcdu}] Using crop region: "
                         f"X={x}, Y={y}, W={w}, H={h}")
            else:
                self.log(
                    f"[{mcdu}] No crop region set - the whole window will be "
                    f"carved into the 24x14 grid. Use 'Select Screen Area' if "
                    f"the output looks wrong.", "WARNING",
                )

            specs.append(McduSpec(name=mcdu, capture=capture,
                                  websocket_uri=self._url_for(mcdu)))
        return specs

    def start_scraper(self) -> None:
        if self.running:
            return

        if not self.config:
            QMessageBox.critical(self, "Error",
                                 "Configuration not loaded. Please check config.yaml")
            return
        if not WINDOWS_AVAILABLE:
            QMessageBox.critical(self, "Error",
                                 "Window capture not available. Please install pywin32.")
            return

        if (self._copilot_enabled()
                and self._selected_window("captain")
                == self._selected_window("copilot")):
            QMessageBox.critical(
                self, "Error",
                "The captain and co-pilot MCDUs are set to the same window. "
                "Pop out a second MCDU and pick it for the co-pilot.")
            return

        try:
            specs = self._build_specs()
        except Exception as exc:
            self.log(f"Error starting scraper: {exc}", "ERROR")
            QMessageBox.critical(self, "Error", f"Failed to start scraper: {exc}")
            self._release_captures()
            return
        if specs is None:
            self._release_captures()
            return

        profile = self._current_profile()
        columns, rows = self._current_grid()
        # Glyphs learned from one font must not be matched against another:
        # each profile has its own template store.
        set_template_store(profile.template_path())
        font = self.config.get_font() or profile.font
        self.log(f"Profile {profile.id}: grid {columns}x{rows}, font {font}")

        self.worker = ScraperWorker(
            self.config, specs,
            columns=columns, rows=rows,
            small_font_rule=profile.small_font_rule, font=font,
        )
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.connected.connect(
            lambda name: self.log(f"[{name}] Connected to WinWing CDU")
        )
        self.worker.failed.connect(self._on_worker_failed)
        self.worker.finished.connect(self._on_worker_finished)
        self.thread.start()

        self.running = True
        self._set_inputs_enabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText(
            f"Status: Running ({len(specs)} MCDU{'s' if len(specs) > 1 else ''})")
        self.status_label.setStyleSheet("font-weight: bold; color: green;")

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Freeze the selection controls while a capture is running."""
        for widget in (self.window_combo, self.select_area_button,
                       self.copilot_group, self.show_all_checkbox,
                       self.profile_combo, self.grid_override_group):
            widget.setEnabled(enabled)

    def _release_captures(self) -> None:
        for mcdu, capture in list(self.captures.items()):
            try:
                capture.close()
            except Exception as exc:
                self.log(f"[{mcdu}] Error closing capture: {exc}", "WARNING")
        self.captures.clear()

    def stop_scraper(self) -> None:
        if not self.running:
            return
        self.log("Stopping scraper...")
        self.stop_button.setEnabled(False)
        if self.worker:
            self.worker.stop()

    def _on_worker_failed(self, message: str) -> None:
        self.log(f"Scraper error: {message}", "ERROR")

    def _on_worker_finished(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait(5000)
            self.thread = None
        self.worker = None

        self._release_captures()

        self.running = False
        self._set_inputs_enabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")
        self.log("Scraper stopped")

    # ------------------------------------------------------------------
    #  Templates
    # ------------------------------------------------------------------
    def delete_templates(self) -> None:
        """Delete learned OCR templates so they are rebuilt on next start."""
        if self.running:
            QMessageBox.warning(
                self, "Scraper Running",
                "Please stop the scraper before deleting templates.",
            )
            return

        profile = self._current_profile()
        template_path = profile.template_path()
        self.log(f"Deleting templates for profile '{profile.id}' "
                 f"({template_path.name})")
        if template_path.exists():
            try:
                template_path.unlink()
                self.log("Templates deleted.")
            except Exception as exc:
                self.log(f"Error deleting templates: {exc}", "ERROR")
                QMessageBox.critical(self, "Error",
                                     f"Failed to delete templates: {exc}")
                return
        else:
            self.log("No template file on disk.")

        # Reset the in-memory state so the next start triggers a full
        # warmup with fresh learning for this profile.
        try:
            set_template_store(template_path)
            _get_template_matcher().reset()
            _prev_row_imgs.clear()
            _prev_row_ocr.clear()
            self.log(
                "In-memory templates and row caches cleared. "
                "Start the scraper to trigger a fresh warmup."
            )
        except Exception as exc:
            self.log(f"Error resetting in-memory state: {exc}", "ERROR")

    # ------------------------------------------------------------------
    #  Shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:          # noqa: N802 (Qt naming)
        if self.running:
            answer = QMessageBox.question(
                self, "Quit", "Scraper is running. Do you want to quit?",
                QMessageBox.Ok | QMessageBox.Cancel,
            )
            if answer != QMessageBox.Ok:
                event.ignore()
                return
            self.stop_scraper()
            if self.thread:
                self.thread.wait(5000)

        logging.getLogger().removeHandler(self._log_handler)
        event.accept()


def main() -> int:
    """Main entry point for the GUI."""
    app = QApplication(sys.argv)
    window = MCDUScraperWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
