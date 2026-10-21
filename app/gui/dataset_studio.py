"""Offline Dataset Visualization Studio: collection, playback, comparison, audit."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..analysis.dataset import (
    LABELS, MAX_GAP, Dataset, LoadCancelled, alignment_offset, collection_summary,
    default_data_directory, export_summary, load_dataset, sample_index,
)
from .dataset_plots import BACKGROUND, COLORS, FOREGROUND, HumanMarker, bars, chart, overview_plots
from .responsive import AdaptiveGrid, FlowLayout, ScrollPanelWheelFilter, labeled_control, scroll_page

STYLE = """
QWidget { background:#0f172a; color:#e2e8f0; font-family:'Segoe UI'; }
QPushButton, QComboBox, QLineEdit { background:#1e293b; border:1px solid #475569;
    border-radius:4px; padding:6px; }
QPushButton:hover { background:#334155; }
QPushButton:disabled { color:#64748b; }
QTabBar::tab { padding:9px 16px; background:#1e293b; }
QTabBar::tab:selected { background:#0369a1; }
QHeaderView::section { background:#1e293b; padding:6px; border:0; }
QTableWidget { gridline-color:#334155; alternate-background-color:#172238; }
QTableWidget::item:selected { background:#075985; }
QProgressBar { border:1px solid #475569; text-align:center; }
QProgressBar::chunk { background:#0284c7; }
QToolTip { background:#1e293b; color:#f8fafc; border:1px solid #64748b; }
"""


class DatasetLoader(QThread):
    progress = Signal(int, int, str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        try:
            result = load_dataset(self.directory, self.progress.emit, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.loaded.emit(result)
        except LoadCancelled:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


class NumberItem(QTableWidgetItem):
    def __init__(self, value, precision=0):
        super().__init__(f"{value:,.{precision}f}")
        self.setData(Qt.ItemDataRole.UserRole, value)

    def __lt__(self, other):
        return self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)


def table(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    result.setAlternatingRowColors(True)
    result.verticalHeader().hide()
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    result.horizontalHeader().setStretchLastSection(True)
    return result


def panel():
    widget = QWidget()
    return widget, QVBoxLayout(widget)


class DatasetStudioWindow(QMainWindow):
    def __init__(self, parent=None, directory=None, autoload=True):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Radar Dataset Visualization Studio")
        self.resize(1480, 940)
        self.setMinimumSize(760, 620)
        self.setStyleSheet(STYLE)
        self.dataset: Dataset | None = None
        self.sessions = []
        self.loader = None
        self.track = None
        self.playing = False
        self.playhead = 0.0
        self._closing = False
        self._filter_pending = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self._setup_ui(directory or default_data_directory())
        if autoload:
            QTimer.singleShot(0, self.refresh)

    def _setup_ui(self, directory):
        central, layout = panel()
        self.setCentralWidget(central)
        heading_row = QHBoxLayout()
        heading = QLabel("Dataset analysis")
        heading.setStyleSheet("font-size:22px; font-weight:600;")
        heading_row.addWidget(heading, 1)
        self.browser_toggle = QPushButton("Recordings")
        self.browser_toggle.setCheckable(True)
        self.browser_toggle.setChecked(True)
        self.browser_toggle.setToolTip("Show or hide the recording list")
        self.browser_toggle.toggled.connect(self._toggle_browser)
        heading_row.addWidget(self.browser_toggle)
        layout.addLayout(heading_row)
        self._browser_requested = True
        self._browser_compact = None
        folder = QHBoxLayout()
        folder.addWidget(QLabel("Data directory"))
        self.directory = QLineEdit(str(directory))
        self.directory.returnPressed.connect(self.refresh)
        folder.addWidget(self.directory, 1)
        self.browse = QPushButton("Choose folder")
        self.browse.clicked.connect(self._browse)
        self.refresh_button = QPushButton("Refresh data")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Export analysis")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)
        for control in (self.browse, self.refresh_button, self.export_button):
            folder.addWidget(control)
        layout.addLayout(folder)

        self.filters = []
        filter_container = QWidget()
        filters = FlowLayout(filter_container, spacing=12)
        for title in ("Participant", "Activity present", "Fall subtype", "Pace", "Training selection"):
            field, field_layout = panel()
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            field.setMinimumWidth(155)
            field.setMaximumWidth(210)
            field_layout.addWidget(QLabel(title))
            control = QComboBox()
            control.setMinimumContentsLength(13)
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            control.addItem("All", None)
            control.currentIndexChanged.connect(self.apply_filters)
            field_layout.addWidget(control)
            filters.addWidget(field)
            self.filters.append(control)
        self.filters[-1].clear()
        for text, value in (("All collected", "all"), ("Training eligible", "eligible"),
                            ("Excluded from training", "excluded")):
            self.filters[-1].addItem(text, value)
        self.clear_filters = QPushButton("Clear filters")
        self.clear_filters.clicked.connect(self._clear_filters)
        filters.addWidget(self.clear_filters)
        layout.addWidget(filter_container)
        note = QLabel("Activity filters select complete sessions containing that label. All charts below use these session filters.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QLabel("Choose a directory of collected radar session CSVs.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color:#7dd3fc; padding:6px 0;")
        layout.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        browser, browser_layout = panel()
        self.browser_container = browser
        browser.setMinimumWidth(220)
        browser.setMaximumWidth(420)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(QLabel("Sessions · select one for human playback"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a session or participant")
        self.search.textChanged.connect(self.apply_filters)
        browser_layout.addWidget(self.search)
        self.session_table = table(["Session", "Person", "Rows", "Seconds", "Fall rows"])
        self.session_table.setSortingEnabled(True)
        self.session_table.itemSelectionChanged.connect(self._session_selected)
        browser_layout.addWidget(self.session_table)
        split.addWidget(browser)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._tab_changed)
        split.addWidget(self.tabs)
        split.setSizes([300, 1180])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self._setup_overview()
        self._setup_playback()
        self._setup_comparison()
        self._setup_quality()
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        self.cancel = QPushButton("Cancel loading")
        self.cancel.hide()
        self.cancel.clicked.connect(self._cancel_load)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel)
        layout.addLayout(progress_row)
        self.statusBar().showMessage("Offline analysis. Source recordings are read only.")

    def _setup_overview(self):
        widget, layout = panel()
        self.overview_note = QLabel()
        self.overview_note.setWordWrap(True)
        layout.addWidget(self.overview_note)
        self.overview = [
            chart("Activity balance", "Action label", "Observations (thousands)"),
            chart("Participant coverage", "Normalized participant ID", "Observations (thousands)"),
            chart("Position density · log(1 + count)", "Lateral X (m)", "Forward Y (m)"),
            chart("Speed · median, IQR, 5th–95th percentile", "Action label", "Absolute radar speed (m/s)"),
        ]
        self.overview_grid = AdaptiveGrid(self.overview, minimum_column_width=460)
        layout.addWidget(self.overview_grid, 1)
        self.tabs.addTab(scroll_page(widget), "Overview")

    def _setup_playback(self):
        page, controls = panel()
        controls.setContentsMargins(8, 8, 8, 8)
        widget, layout = panel()
        options = FlowLayout()
        self.target = QComboBox()
        self.target.setMinimumContentsLength(13)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.currentIndexChanged.connect(self._target_changed)
        options.addWidget(labeled_control("Target", self.target))
        self.play = QPushButton("Play")
        self.play.clicked.connect(self._toggle_play)
        options.addWidget(self.play)
        self.speed = QComboBox()
        for rate in (.25, .5, 1, 2, 4):
            self.speed.addItem(f"{rate:g}×", rate)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(self._speed_changed)
        options.addWidget(labeled_control("Playback rate", self.speed))
        self.jump_fall = QPushButton("First fall label")
        self.jump_fall.clicked.connect(self._jump_to_fall)
        options.addWidget(self.jump_fall)
        self.trail_span = QComboBox()
        for seconds in (3, 5, 10, 30):
            self.trail_span.addItem(f"{seconds} s", seconds)
        self.trail_span.addItem("Since start", None)
        self.trail_span.setToolTip("Highlight the movement leading up to the selected time")
        self.trail_span.currentIndexChanged.connect(self._update_movement_trail)
        options.addWidget(labeled_control("Movement trail", self.trail_span))
        controls.addLayout(options)
        scrub = QHBoxLayout()
        scrub.addWidget(QLabel("Time"))
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 10000)
        self.seek.setPageStep(100)
        self.seek.setAccessibleName("Playback time")
        self.seek.setToolTip("Drag to move through the recording; dragging pauses playback")
        self.seek.setStyleSheet("""
            QSlider::groove:horizontal { height:6px; background:#334155; border-radius:3px; }
            QSlider::sub-page:horizontal { background:#0284c7; border-radius:3px; }
            QSlider::handle:horizontal { width:16px; margin:-5px 0; border-radius:8px;
                background:#38bdf8; border:1px solid #bae6fd; }
        """)
        self.seek.sliderPressed.connect(self._pause)
        self.seek.valueChanged.connect(self._seek)
        scrub.addWidget(self.seek, 1)
        self.playback_clock = QLabel("0.00 / 0.00 s")
        scrub.addWidget(self.playback_clock)
        controls.addLayout(scrub)
        self.readout = QLabel("No recording loaded")
        self.readout.setWordWrap(True)
        controls.addWidget(self.readout)
        self.play_title = QLabel("Select a session from the list.")
        self.play_title.setWordWrap(True)
        layout.addWidget(self.play_title)
        schematic = QLabel("The stick figure is a fixed schematic marker at the measured position. No joints, posture or body height are recorded. Shading denotes manual fall labels.")
        schematic.setWordWrap(True)
        layout.addWidget(schematic)
        self.activity_legend = QLabel()
        self.activity_legend.setWordWrap(True)
        layout.addWidget(self.activity_legend)
        self.path_plot = chart("Human path · room plane", "Lateral X (m)", "Forward Y (m)")
        self.path_plot.setAspectLocked(True)
        self.path_plot.setMinimumHeight(350)
        signals_widget, signals_layout = panel()
        signals_layout.setContentsMargins(0, 0, 0, 0)
        signals_layout.addWidget(QLabel("X, Y and speed · scroll to inspect"))
        self.signals = [chart("X position", "Time from session start (s)", "X (m)"),
                        chart("Y position", "Time from session start (s)", "Y (m)"),
                        chart("Recorded speed magnitude", "Time from session start (s)", "|Speed| (m/s)")]
        for i, plot in enumerate(self.signals):
            plot.setMinimumHeight(200)
            plot.setMouseEnabled(x=True, y=False)
            plot.setToolTip("Scroll to browse graphs. Drag to pan time; Ctrl+wheel zooms time.")
            signals_layout.addWidget(plot, 1)
            if i:
                plot.setXLink(self.signals[0])
        self.signal_scroll = scroll_page(signals_widget)
        self.signal_scroll.setMinimumHeight(350)
        self.signal_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.signal_scroll.setStyleSheet("QScrollArea { border:1px solid #334155; border-radius:4px; }")
        self.signal_wheel = ScrollPanelWheelFilter(self.signal_scroll, [plot.viewport() for plot in self.signals])
        self.playback_grid = AdaptiveGrid([self.path_plot, self.signal_scroll], minimum_column_width=420)
        layout.addWidget(self.playback_grid, 1)
        controls.addWidget(scroll_page(widget), 1)
        self.tabs.addTab(page, "Playback")

    def _setup_comparison(self):
        widget, layout = panel()
        self.compare_sessions, self.compare_targets = [], []
        for name in ("A", "B"):
            row = FlowLayout()
            session = QComboBox()
            session.setMinimumContentsLength(18)
            session.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            target = QComboBox()
            self.compare_sessions.append(session)
            self.compare_targets.append(target)
            side = len(self.compare_sessions)-1
            session.currentIndexChanged.connect(lambda _, side=side: self._compare_session_changed(side))
            target.currentIndexChanged.connect(self._draw_comparison)
            row.addWidget(labeled_control(f"Recording {name}", session))
            row.addWidget(labeled_control("Target", target))
            layout.addLayout(row)
        align = FlowLayout()
        self.alignment = QComboBox()
        self.alignment.addItem("Each target track start", "start")
        self.alignment.addItem("First fall-onset label (t = 0)", "fall")
        self.alignment.setMinimumContentsLength(20)
        self.alignment.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.alignment.currentIndexChanged.connect(self._draw_comparison)
        align.addWidget(labeled_control("Time alignment", self.alignment))
        layout.addLayout(align)
        self.compare_note = QLabel("Select two recordings to compare. A = cyan solid; B = orange dashed.")
        self.compare_note.setWordWrap(True)
        layout.addWidget(self.compare_note)
        self.comparison = [chart("A / B trajectories", "Lateral X (m)", "Forward Y (m)"),
                           chart("A / B speed", "Aligned time (s)", "Absolute radar speed (m/s)"),
                           chart("A / B lateral position", "Aligned time (s)", "X (m)"),
                           chart("A / B forward position", "Aligned time (s)", "Y (m)")]
        self.comparison[0].setAspectLocked(True)
        for i, plot in enumerate(self.comparison):
            plot.addLegend(offset=(8, 8))
            if i > 1:
                plot.setXLink(self.comparison[1])
        self.comparison_grid = AdaptiveGrid(self.comparison, minimum_column_width=460)
        layout.addWidget(self.comparison_grid, 1)
        self.tabs.addTab(scroll_page(widget), "Compare")

    def _setup_quality(self):
        widget, layout = panel()
        self.quality_note = QLabel()
        self.quality_note.setWordWrap(True)
        layout.addWidget(self.quality_note)
        self.coverage = chart("Participant × activity · log(1 + rows)", "Action label", "Participant")
        self.rates = chart("Session sampling rates", "Median frame rate (Hz)", "Sessions")
        self.quality_grid = AdaptiveGrid([self.coverage, self.rates], minimum_column_width=460)
        layout.addWidget(self.quality_grid, 1)
        self.audit = table(["Session", "Gaps >0.5s", "Steps >3.5m/s", "Range mismatch >0.1m", "Duplicate rows", "Bad rows", "Invalid rows", "Backwards", "Same-time", "Training"])
        self.audit.setSortingEnabled(True)
        layout.addWidget(self.audit, 1)
        self.issues = table(["Skipped / unreadable file", "Reason"])
        self.issues.setMaximumHeight(130)
        self.issues.hide()
        layout.addWidget(self.issues)
        self.tabs.addTab(scroll_page(widget), "Data quality")

    def _set_browser_visible(self, visible):
        self.browser_container.setVisible(visible)
        self.browser_toggle.blockSignals(True)
        self.browser_toggle.setChecked(visible)
        self.browser_toggle.blockSignals(False)

    def _toggle_browser(self, visible):
        self._browser_requested = visible
        if hasattr(self, "browser_container"):
            self._set_browser_visible(visible)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "browser_container"):
            compact = event.size().width() < 1100
            if compact != self._browser_compact:
                self._browser_compact = compact
                self._set_browser_visible(not compact and self._browser_requested)

    def _clear_filters(self):
        self._filter_pending = True
        for control in self.filters:
            control.setCurrentIndex(0)
        self.search.clear()
        self._filter_pending = False
        self.apply_filters()

    def _browse(self):
        value = QFileDialog.getExistingDirectory(self, "Choose radar dataset directory", self.directory.text())
        if value:
            self.directory.setText(value)
            self.refresh()

    def refresh(self):
        if self.loader and self.loader.isRunning():
            return
        self._pause()
        directory = Path(self.directory.text().strip()).expanduser()
        if not directory.is_dir():
            self.statusBar().showMessage(f"Directory does not exist: {directory}")
            return
        self._closing = False
        self.loader = DatasetLoader(directory, self)
        self.loader.progress.connect(self._load_progress)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._load_failed)
        self.loader.finished.connect(self._load_finished)
        for control in (self.refresh_button, self.browse, self.directory, self.export_button):
            control.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel.show()
        self.statusBar().showMessage("Scanning session files…")
        self.loader.start()

    def _load_progress(self, value, total, name):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(value)
        self.statusBar().showMessage(f"Loading {value:,} / {total:,}: {name}")

    def _cancel_load(self):
        if self.loader:
            self.loader.requestInterruption()
            self.statusBar().showMessage("Cancelling load; keeping the previous dataset.")

    def _load_failed(self, error):
        self.statusBar().showMessage(f"Could not load dataset: {error}")
        QMessageBox.warning(self, "Dataset loading failed", error)

    def _load_finished(self):
        interrupted = self.loader.isInterruptionRequested()
        for control in (self.refresh_button, self.browse, self.directory):
            control.setEnabled(True)
        self.export_button.setEnabled(bool(self.sessions))
        self.progress.hide()
        self.cancel.hide()
        self.loader.deleteLater()
        self.loader = None
        if interrupted:
            self.statusBar().showMessage("Load cancelled. Previous dataset retained.")
        if self._closing:
            self.close()

    def _loaded(self, dataset):
        self.dataset = dataset
        self._filter_pending = True
        for control, values in zip(self.filters[:4], [
            sorted({s.person for s in dataset.sessions}),
            sorted({code for s in dataset.sessions for code in s.counts}),
            sorted({s.subtype for s in dataset.sessions}), sorted({s.pace for s in dataset.sessions}),
        ]):
            previous = control.currentData()
            control.blockSignals(True)
            control.clear()
            control.addItem("All", None)
            for value in values:
                control.addItem(f"{value}: {LABELS.get(value, 'Unknown')}" if isinstance(value, int) else value, value)
            match = control.findData(previous)
            control.setCurrentIndex(max(0, match))
            control.blockSignals(False)
        self._filter_pending = False
        self.apply_filters()
        copies = sum(bool(i['duplicate_of']) for i in dataset.inventory)
        self.statusBar().showMessage(f"Loaded {len(dataset.sessions):,} sessions. {copies} exact file copies excluded; {len(dataset.issues)} files skipped.")

    def apply_filters(self, *_):
        if self._filter_pending or self.dataset is None:
            return
        self._pause()
        old = self._selected_session()
        selected_path = old.path if old else None
        params = [f.currentData() for f in self.filters]
        query = self.search.text().strip().casefold()
        self.sessions = [s for s in self.dataset.filtered(*params)
                         if not query or query in f"{s.path.name} {s.person}".casefold()]
        self.session_table.blockSignals(True)
        self.session_table.setSortingEnabled(False)
        self.session_table.setRowCount(len(self.sessions))
        for row, session in enumerate(self.sessions):
            item = QTableWidgetItem(session.path.name)
            item.setToolTip(str(session.path))
            item.setData(Qt.ItemDataRole.UserRole, session)
            self.session_table.setItem(row, 0, item)
            self.session_table.setItem(row, 1, QTableWidgetItem(session.person))
            for col, value in ((2, session.rows), (3, session.duration), (4, session.counts[6])):
                self.session_table.setItem(row, col, NumberItem(value, 1 if col == 3 else 0))
        self.session_table.setSortingEnabled(True)
        self.session_table.blockSignals(False)
        # Combo data holds session objects; no assumptions about duplicate filenames.
        for combo in self.compare_sessions:
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for s in self.sessions:
                combo.addItem(f"{s.path.name} · {s.person} · {s.path.parent.name}", s)
            if previous:
                index = next((i for i, s in enumerate(self.sessions) if s.path == previous.path), 0)
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if len(self.sessions) > 1 and self.compare_sessions[0].currentIndex() == self.compare_sessions[1].currentIndex():
            self.compare_sessions[1].blockSignals(True)
            self.compare_sessions[1].setCurrentIndex(1 if self.compare_sessions[0].currentIndex() != 1 else 0)
            self.compare_sessions[1].blockSignals(False)
        for i in range(2):
            self._compare_session_changed(i)
        for row in range(self.session_table.rowCount()):
            s = self.session_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if s.path == selected_path or (selected_path is None and row == 0):
                self.session_table.selectRow(row)
                break
        if self.sessions and not self.session_table.selectedItems():
            self.session_table.selectRow(0)
        # Rebind even when selection stays in the same row: Refresh replaces
        # session objects and may include newly appended recording samples.
        self._set_session(self._selected_session())
        total = collection_summary(self.sessions)
        self.summary.setText(f"{total['sessions']:,} sessions   ·   {total['rows']:,} observations   ·   "
                             f"{total['participants']} participants   ·   {total['elapsed_hours']:.2f} elapsed hours   ·   "
                             f"Fall onset: {total['fall_percent']:.2f}% of rows, {total['fall_participants']} participants")
        self.overview_note.setText("Fall-label rows count samples, not physical events. Participant aliases follow the training script. "
                                   f"{sum(s.excluded for s in self.sessions)} selected recordings are excluded by the existing training selection file.")
        self.export_button.setEnabled(bool(self.sessions) and self.loader is None)
        # Only the current aggregate tab is drawn; the others update on selection.
        self._aggregate_dirty = {0, 3}
        self._tab_changed(self.tabs.currentIndex())

    def _selected_session(self):
        selected = self.session_table.selectedItems()
        return self.session_table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole) if selected else None

    def _session_selected(self):
        self._set_session(self._selected_session())

    def _set_session(self, session):
        self._pause()
        self.current_session = session
        self.target.blockSignals(True)
        self.target.clear()
        if session:
            for track in session.tracks:
                self.target.addItem(f"{track.target} ({len(track.values):,} rows)", track)
            self.play_title.setText(f"{session.path.name} · {session.person} · {session.subtype} · {session.pace}")
        else:
            self.play_title.setText("No sessions match the current filters.")
        self.target.blockSignals(False)
        self._target_changed()

    def _target_changed(self, *_):
        self._pause()
        self.track = self.target.currentData()
        self.path_plot.clear()
        for plot in self.signals:
            plot.clear()
        self.play.setEnabled(self.track is not None)
        self.seek.setEnabled(self.track is not None)
        self.trail_span.setEnabled(self.track is not None)
        self.jump_fall.setEnabled(self.track is not None and bool(np.any(self.track.labels == 6)))
        if self.track is None:
            self.readout.setText("No recording selected")
            self.playback_clock.setText("0.00 / 0.00 s")
            self.seek.blockSignals(True)
            self.seek.setValue(0)
            self.seek.blockSignals(False)
            self.activity_legend.clear()
            return
        track = self.track
        self.activity_legend.setText(" &nbsp; ".join(
            f'<span style="color:{COLORS.get(int(code), COLORS[-1])}">{int(code)}: {LABELS.get(int(code), "Unknown")}</span>'
            for code in np.unique(track.labels)))
        self._trail_times, x = track.segments(1)
        _, y = track.segments(2)
        self._trail_x, self._trail_y = x, y
        self.path_plot.plot(x, y, pen=pg.mkPen("#64748b", width=1), connect="finite")
        for code in np.unique(track.labels):
            points = track.values[track.labels == code]
            context = self.path_plot.plot(points[:, 1], points[:, 2], pen=None, symbol="o", symbolSize=4,
                                          symbolBrush=COLORS.get(int(code), COLORS[-1]), symbolPen=None)
            context.setOpacity(.35)
        self.movement_trail = self.path_plot.plot(pen=pg.mkPen(COLORS[1], width=3), connect="finite")
        self.movement_trail.setZValue(5)
        self.human = HumanMarker()
        self.path_plot.addItem(self.human, ignoreBounds=True)
        self.cursors = []
        self.start_time = self.current_session.start
        for column, plot in enumerate(self.signals, 1):
            t, values = track.segments(column, self.start_time)
            plot.plot(t, np.abs(values) if column == 3 else values,
                      pen=pg.mkPen(COLORS[1], width=1.5), connect="finite")
            self._fall_regions(plot, track, self.start_time)
            cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(FOREGROUND, width=1))
            plot.addItem(cursor, ignoreBounds=True)
            self.cursors.append(cursor)
            plot.autoRange()
        self.path_plot.autoRange()
        self.playhead = float(track.values[0, 0] - self.start_time)
        self._update_playhead()

    @staticmethod
    def _fall_regions(plot, track, offset):
        labels = track.labels
        start = None
        for i in range(len(labels)):
            if start is not None and (labels[i] != 6 or track.dt[i] > MAX_GAP):
                end = track.values[i-1, 0]
                # Extend only to the next frame if that interval is contiguous.
                if track.dt[i] <= MAX_GAP:
                    end = track.values[i, 0]
                region = pg.LinearRegionItem([start-offset, end-offset], movable=False,
                                              brush=pg.mkBrush(251, 113, 133, 30), pen=pg.mkPen(251, 113, 133, 80))
                region.setZValue(-5)
                plot.addItem(region)
                start = None
            if labels[i] == 6 and start is None:
                start = track.values[i, 0]
        if start is not None:
            region = pg.LinearRegionItem([start-offset, track.values[-1, 0]-offset], movable=False,
                                          brush=pg.mkBrush(251, 113, 133, 30), pen=pg.mkPen(251, 113, 133, 80))
            region.setZValue(-5)
            plot.addItem(region)

    def _pause(self):
        self.playing = False
        self.timer.stop()
        if hasattr(self, "play"):
            self.play.setText("Play")

    def _toggle_play(self):
        if not self.track:
            return
        if self.playing:
            self._pause()
            return
        if self.playhead >= self.track.values[-1, 0] - self.start_time:
            self.playhead = float(self.track.values[0, 0] - self.start_time)
        self.playing = True
        self.play.setText("Pause")
        self.last_tick = time.monotonic()
        self.timer.start()

    def _speed_changed(self, *_):
        if self.playing:
            self._tick()

    def _tick(self):
        if not self.playing or self.track is None:
            return
        now = time.monotonic()
        self.playhead += (now-self.last_tick)*float(self.speed.currentData())
        self.last_tick = now
        end = float(self.track.values[-1, 0]-self.start_time)
        if self.playhead >= end:
            self.playhead = end
            self._pause()
        self._update_playhead()

    def _seek(self, value):
        if self.track is None:
            return
        self._pause()
        start = float(self.track.values[0, 0]-self.start_time)
        duration = float(self.track.values[-1, 0]-self.track.values[0, 0])
        self.playhead = start + value/10000*duration
        self._update_playhead()

    def _jump_to_fall(self):
        if self.track is None:
            return
        offset = alignment_offset(self.track, "fall")
        if offset is not None:
            self._pause()
            self.playhead = offset-self.start_time
            self._update_playhead()

    def _update_playhead(self):
        track = self.track
        if track is None:
            return
        duration = float(track.values[-1, 0]-track.values[0, 0])
        self.seek.blockSignals(True)
        self.seek.setValue(round(10000*(self.playhead+self.start_time-track.values[0, 0])/duration) if duration else 0)
        self.seek.blockSignals(False)
        end = float(track.values[-1, 0]-self.start_time)
        self.playback_clock.setText(f"{self.playhead:.2f} / {end:.2f} s")
        self._update_movement_trail()
        for cursor in self.cursors:
            cursor.setValue(self.playhead)
        index = sample_index(track, self.playhead+self.start_time)
        if index is None:
            self.human.hide()
            self.readout.setText(f"t = {self.playhead:.2f} s · Recording gap: no observed position")
        else:
            _, x, y, speed, code, _ = track.values[index]
            self.human.locate(x, y, int(code))
            self.readout.setText(f"t = {self.playhead:.2f} s · {int(code)}: {LABELS.get(int(code), 'Unknown')} · "
                                 f"X {x:.3f} m · Y {y:.3f} m · |radar speed| {abs(speed):.2f} m/s")

    def _update_movement_trail(self, *_):
        if self.track is None:
            return
        now = self.playhead+self.start_time
        span = self.trail_span.currentData()
        start = now-span if span is not None else self.track.values[0, 0]
        indices = np.flatnonzero((self._trail_times >= start) & (self._trail_times <= now))
        if not len(indices):
            self.movement_trail.setData([], [])
            return
        # Preserve the NaNs between selected observations so gaps stay disconnected.
        section = slice(indices[0], indices[-1]+1)
        self.movement_trail.setData(self._trail_x[section], self._trail_y[section], connect="finite")

    def _compare_session_changed(self, side):
        if not hasattr(self, "alignment"):
            return
        session = self.compare_sessions[side].currentData()
        combo = self.compare_targets[side]
        combo.blockSignals(True)
        combo.clear()
        if session:
            for track in session.tracks:
                combo.addItem(track.target, track)
        combo.blockSignals(False)
        self._draw_comparison()

    def _draw_comparison(self, *_):
        if not hasattr(self, "comparison"):
            return
        for plot in self.comparison:
            plot.clear()
            if plot.plotItem.legend:
                plot.plotItem.legend.clear()
        messages = []
        for side, (color, style) in enumerate(((COLORS[1], Qt.PenStyle.SolidLine), (COLORS[8], Qt.PenStyle.DashLine))):
            track = self.compare_targets[side].currentData()
            session = self.compare_sessions[side].currentData()
            if track is None or session is None:
                continue
            name = f"{'AB'[side]}: {session.path.name} / {track.target}"
            offset = alignment_offset(track, self.alignment.currentData())
            if offset is None:
                messages.append(f"{'AB'[side]} has no fall-onset label; cannot align it to a fall.")
                continue
            pen = pg.mkPen(color, width=2, style=style)
            _, x = track.segments(1)
            _, y = track.segments(2)
            self.comparison[0].plot(x, y, pen=pen, connect="finite", name=name)
            for plot, col in zip(self.comparison[1:], (3, 1, 2)):
                t, values = track.segments(col, offset)
                plot.plot(t, np.abs(values) if col == 3 else values, pen=pen, connect="finite", name=name)
            messages.append(f"{'AB'[side]}: {len(track.values):,} rows; {track.fall_runs} fall-label runs")
        self.compare_note.setText("A = cyan solid; B = orange dashed. " + " · ".join(messages))
        for plot in self.comparison:
            plot.autoRange()

    def _tab_changed(self, index):
        if index != 1:
            self._pause()
        if not hasattr(self, "_aggregate_dirty") or index not in self._aggregate_dirty:
            return
        if index == 0:
            overview_plots(self.overview, self.sessions)
        elif index == 3:
            self._draw_quality()
        self._aggregate_dirty.discard(index)

    def _draw_quality(self):
        self.audit.setSortingEnabled(False)
        self.audit.setRowCount(len(self.sessions))
        gap_count = speed_count = range_count = 0
        for i, session in enumerate(self.sessions):
            record = session.summary()
            self.audit.setItem(i, 0, QTableWidgetItem(session.path.name))
            self.audit.item(i, 0).setToolTip(str(session.path))
            for col, field in enumerate(("gaps_over_05s", "coordinate_speed_flags", "range_residual_flags",
                                         "duplicate_rows", "bad_rows", "invalid_rows", "backwards", "zero_track_intervals"), 1):
                self.audit.setItem(i, col, NumberItem(record[field]))
            self.audit.setItem(i, 9, QTableWidgetItem("Excluded" if session.excluded else "Eligible"))
            gap_count += session.gaps
            speed_count += session.speed_flags
            range_count += session.range_flags
        self.audit.setSortingEnabled(True)
        self.quality_note.setText(f"{gap_count:,} session gaps >0.5 s · {speed_count:,} track steps >3.5 m/s · "
                                  f"{range_count:,} range residuals >0.1 m. These flags retain the source measurements. "
                                  "Range may differ because X/Y and distance use different filtering. Load issues below cover the complete directory.")
        self.coverage.clear()
        self.rates.clear()
        people = sorted({s.person for s in self.sessions})
        codes = sorted({c for s in self.sessions for c in s.counts})
        if people and codes:
            matrix = np.asarray([[sum(s.counts[c] for s in self.sessions if s.person == p) for p in people] for c in codes])
            item = pg.ImageItem(np.log1p(matrix), axisOrder="col-major")
            item.setLookupTable(pg.colormap.get("viridis").getLookupTable())
            item.setRect(-.5, -.5, len(codes), len(people))
            self.coverage.addItem(item)
            self.coverage.getAxis("bottom").setTicks([[(i, str(c)) for i, c in enumerate(codes)]])
            self.coverage.getAxis("left").setTicks([list(enumerate(people))])
            self.coverage.autoRange()
            rates = [s.hz for s in self.sessions]
            # Near-identical floating-point rates need a padded range; otherwise
            # NumPy cannot represent distinct bin edges for small filtered cohorts.
            low, high = min(rates), max(rates)
            pad = max(.05, (high-low)*.05)
            values, edges = np.histogram(rates, bins=30, range=(low-pad, high+pad))
            self.rates.addItem(pg.BarGraphItem(x=(edges[1:]+edges[:-1])/2, height=values,
                                              width=np.diff(edges)*.95, brush=COLORS[1], pen=None))
            self.rates.autoRange()
        issues = self.dataset.issues if self.dataset else []
        self.issues.setRowCount(len(issues))
        for i, issue in enumerate(issues):
            self.issues.setItem(i, 0, QTableWidgetItem(issue["source"]))
            self.issues.setItem(i, 1, QTableWidgetItem(issue["issue"]))
        self.issues.setVisible(bool(issues))

    def _export(self):
        if not self.dataset or not self.sessions:
            return
        destination = QFileDialog.getExistingDirectory(self, "Export analysis into a new timestamped folder", str(self.dataset.directory.parent))
        if not destination:
            return
        try:
            output = self.export_to(Path(destination))
            self.statusBar().showMessage(f"Exported filtered summaries and overview charts: {output}")
            QMessageBox.information(self, "Analysis exported", f"Summaries and four overview PNG plots saved to:\n{output}")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def export_to(self, destination):
        """Shared by the export action and UI integration checks."""
        from pyqtgraph.exporters import ImageExporter
        output = export_summary(self.dataset, self.sessions, destination)
        overview_plots(self.overview, self.sessions)
        self._aggregate_dirty.discard(0)
        for name, plot in zip(("activity_balance", "participant_coverage", "position_density", "speed_distribution"), self.overview):
            exporter = ImageExporter(plot.plotItem)
            exporter.parameters()["width"] = 1400
            exporter.export(str(output/f"{name}.png"))
        filters = dict(zip(("participant", "activity_present", "fall_subtype", "pace", "training_selection"),
                           [f.currentData() for f in self.filters]))
        filters["session_search"] = self.search.text()
        (output/"filters.json").write_text(json.dumps(filters, indent=2), encoding="utf-8")
        return output

    def shutdown(self):
        self._closing = True
        self._pause()
        if self.loader and self.loader.isRunning():
            self.loader.requestInterruption()
            self.loader.wait()

    def closeEvent(self, event):
        self._pause()
        if self.loader and self.loader.isRunning():
            self._closing = True
            self.loader.requestInterruption()
            self.hide()
            event.ignore()
        else:
            event.accept()
