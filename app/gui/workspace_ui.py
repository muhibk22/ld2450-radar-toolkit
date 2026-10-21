"""Task-oriented, responsive shell for the existing live radar controllers."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)
from .responsive import FlowLayout, scroll_page
from .packet_view import PacketViewWidget
from .telemetry_panel import TelemetryPanelWidget
from .radar_view import RadarViewWidget
from .diagnostics_panel import DiagnosticsPanelWidget
from .target_panel import TargetPanelWidget
from .tuning_panel import TuningPanelWidget

WORKSPACE_STYLE = """
QWidget { background:#0f172a; color:#e2e8f0; font-family:'Segoe UI'; }
QLabel#workspaceTitle { font-size:22px; font-weight:600; }
QLabel#workspaceSubtitle { color:#94a3b8; }
QPushButton, QComboBox, QSpinBox, QLineEdit { background:#1e293b; border:1px solid #475569;
    border-radius:5px; padding:6px 9px; min-height:20px; }
QPushButton:hover { background:#334155; border-color:#64748b; }
QPushButton:checked { background:#075985; border-color:#38bdf8; }
QPushButton:disabled { color:#64748b; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border-color:#38bdf8; }
QTabWidget::pane { border:1px solid #334155; }
QTabBar::tab { background:#1e293b; color:#94a3b8; padding:9px 15px; }
QTabBar::tab:selected { background:#075985; color:#f8fafc; }
QGroupBox { border:1px solid #334155; border-radius:6px; margin-top:14px; padding-top:10px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; color:#cbd5e1; }
QDockWidget::title { background:#1e293b; padding:8px; }
QMenuBar { background:#0f172a; }
QMenuBar::item:selected, QMenu::item:selected { background:#075985; }
QMenu { background:#1e293b; border:1px solid #475569; padding:5px; }
QMenu::item { padding:7px 24px; }
QSplitter::handle { background:#26354b; }
QScrollArea { border:0; }
QToolTip { background:#1e293b; color:#f8fafc; border:1px solid #64748b; padding:4px; }
"""


def build_workspace(w):
    w.setWindowTitle("LD2450 · Radar workspace")
    w.setMinimumSize(760, 620)
    w.setStyleSheet(WORKSPACE_STYLE)
    w.data_collection_window.setStyleSheet(WORKSPACE_STYLE)
    w._compact_mode = None
    w._controls_requested = True
    w._adjusting_dock = False
    w.discovery_worker = None
    w._closing_for_discovery = False
    central = QWidget()
    layout = QVBoxLayout(central)
    layout.setContentsMargins(14, 12, 14, 8)
    layout.setSpacing(10)
    w.setCentralWidget(central)
    header = QHBoxLayout()
    title = QWidget()
    title_layout = QVBoxLayout(title)
    title_layout.setContentsMargins(0, 0, 0, 0)
    heading = QLabel("Radar workspace")
    heading.setObjectName("workspaceTitle")
    subtitle = QLabel("Live tracking, recording and dataset analysis")
    subtitle.setObjectName("workspaceSubtitle")
    title_layout.addWidget(heading)
    title_layout.addWidget(subtitle)
    header.addWidget(title, 1)
    w.lbl_status = QLabel("Disconnected")
    w.lbl_status.setWordWrap(True)
    w.lbl_status.setMinimumWidth(0)
    w.lbl_status.setMaximumWidth(350)
    w.lbl_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    w.lbl_status.setStyleSheet("color:#fda4af; padding:6px;")
    header.addWidget(w.lbl_status, 1)
    layout.addLayout(header)

    actions = QWidget()
    flow = FlowLayout(actions)
    w.controls_button = QPushButton("Connection controls")
    w.controls_button.setCheckable(True)
    w.controls_button.setToolTip("Show or hide connection and tracking controls (Ctrl+\\)")
    w.controls_button.clicked.connect(w._toggle_controls_panel)
    w.btn_data_studio = QPushButton("Record sessions")
    w.btn_data_studio.clicked.connect(w._open_data_collection)
    w.btn_analyze_dataset = QPushButton("Analyze dataset")
    w.btn_analyze_dataset.clicked.connect(w._open_dataset_visualization)
    w.btn_fall_monitor = QPushButton("Fall monitor")
    w.btn_fall_monitor.clicked.connect(w.fall_monitor_window.show)
    for control in (w.controls_button, w.btn_data_studio, w.btn_analyze_dataset, w.btn_fall_monitor):
        flow.addWidget(control)
    layout.addWidget(actions)
    w.lbl_fall_alert = QLabel()
    w.lbl_fall_alert.setWordWrap(True)
    w.lbl_fall_alert.setStyleSheet("background:#991b1b; color:#fff; padding:10px; border-radius:5px;")
    w.lbl_fall_alert.hide()
    layout.addWidget(w.lbl_fall_alert)

    w.workspace_tabs = QTabWidget()
    w.workspace_tabs.setDocumentMode(True)
    live = QWidget()
    live_layout = QVBoxLayout(live)
    hint = QLabel("Connect a sensor, then select a person on the radar to focus tracking. Lock a person before recording.")
    hint.setWordWrap(True)
    hint.setStyleSheet("color:#94a3b8;")
    live_layout.addWidget(hint)
    w.live_splitter = QSplitter(Qt.Orientation.Vertical)
    w.radar_view = RadarViewWidget()
    w.radar_view.target_clicked.connect(w._on_target_clicked_on_canvas)
    w.live_splitter.addWidget(w.radar_view)
    details = QTabWidget()
    w.target_panel = TargetPanelWidget()
    w.diagnostics_panel = DiagnosticsPanelWidget()
    details.addTab(w.target_panel, "Tracked people")
    details.addTab(w.diagnostics_panel, "Connection health")
    w.live_splitter.addWidget(details)
    w.live_splitter.setChildrenCollapsible(False)
    w.live_splitter.setSizes([530, 180])
    live_layout.addWidget(w.live_splitter, 1)
    w.workspace_tabs.addTab(live, "Live radar")

    w.tuning_panel = TuningPanelWidget()
    w.tuning_panel.settings_changed.connect(w.tracker.apply_tuning_settings)
    w.tuning_panel.f_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    w.tuning_panel.cb_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    w.tuning_panel.cb_mode.setMinimumContentsLength(24)
    w.workspace_tabs.addTab(scroll_page(w.tuning_panel), "Calibration")
    protocol = QTabWidget()
    w.packet_view = PacketViewWidget()
    w.telemetry_panel = TelemetryPanelWidget()
    protocol.addTab(w.packet_view, "Raw packets")
    protocol.addTab(w.telemetry_panel, "Decoded fields")
    w.workspace_tabs.addTab(protocol, "Protocol inspector")
    layout.addWidget(w.workspace_tabs, 1)

    _build_controls(w)
    _build_menus(w)
    w.workspace_tabs.currentChanged.connect(w._workspace_changed)
    w.statusBar().showMessage("Ready. Open Connection controls to connect a sensor.")


def _build_controls(w):
    w.control_dock = QDockWidget("Connection controls", w)
    w.control_dock.setObjectName("connectionTrackingDock")
    w.control_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
    w.control_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
    content = QWidget()
    content.setMinimumWidth(225)
    content.setMaximumWidth(320)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(10, 10, 10, 10)
    connection = QGroupBox("1 · Connect a sensor")
    connection_layout = QVBoxLayout(connection)
    w.cb_conn_type = QComboBox()
    w.cb_conn_type.addItems(["Serial USB", "Wi-Fi (TCP)"])
    w.cb_conn_type.currentIndexChanged.connect(w._on_conn_type_changed)
    connection_layout.addWidget(QLabel("Connection type"))
    connection_layout.addWidget(w.cb_conn_type)
    serial = QWidget()
    form = QFormLayout(serial)
    form.setContentsMargins(0, 4, 0, 4)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    w.cb_ports = QComboBox()
    w.cb_ports.setMinimumContentsLength(12)
    w.btn_refresh = QPushButton("Refresh ports")
    w.btn_refresh.clicked.connect(w._refresh_com_ports)
    form.addRow("Serial port", w.cb_ports)
    form.addRow(w.btn_refresh)
    w.cb_baud = QComboBox()
    w.cb_baud.addItems(["115200", "256000", "9600", "19200", "38400", "57600", "460800", "921600"])
    w.cb_baud.setCurrentText("115200")
    w.cb_baud.currentTextChanged.connect(w._on_baud_changed)
    form.addRow("Baud rate", w.cb_baud)
    w.btn_autobaud = QPushButton("Detect baud rate")
    w.btn_autobaud.clicked.connect(w._auto_detect_baud)
    form.addRow(w.btn_autobaud)
    connection_layout.addWidget(serial)
    wifi = QWidget()
    form = QFormLayout(wifi)
    form.setContentsMargins(0, 4, 0, 4)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    w.txt_ip = QLineEdit("192.168.100.130")
    w.sp_wifi_port = QSpinBox()
    w.sp_wifi_port.setRange(1, 65535)
    w.sp_wifi_port.setValue(8888)
    w.btn_discover_ip = QPushButton("Find radar on network")
    w.btn_discover_ip.clicked.connect(w._auto_discover_esp32_ip)
    form.addRow("IP address / hostname", w.txt_ip)
    form.addRow("TCP port", w.sp_wifi_port)
    form.addRow(w.btn_discover_ip)
    connection_layout.addWidget(wifi)
    wifi.hide()
    w.serial_widgets, w.wifi_widgets = [serial], [wifi]
    w.lbl_discovery = QLabel()
    w.lbl_discovery.setWordWrap(True)
    w.lbl_discovery.setStyleSheet("color:#7dd3fc;")
    connection_layout.addWidget(w.lbl_discovery)
    w.chk_auto_reconnect = QCheckBox("Reconnect automatically")
    w.chk_auto_reconnect.setChecked(True)
    connection_layout.addWidget(w.chk_auto_reconnect)
    w.btn_connect = QPushButton("Connect")
    w.btn_connect.setStyleSheet("background:#0284c7; color:white; font-weight:600;")
    w.btn_connect.clicked.connect(w._toggle_connection)
    connection_layout.addWidget(w.btn_connect)
    layout.addWidget(connection)

    tracking = QGroupBox("2 · Focus and display")
    form = QFormLayout(tracking)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    w.cb_target_lock = QComboBox()
    w.cb_target_lock.addItems(["Track All Targets", "Person A", "Person B", "Person C"])
    w.cb_target_lock.currentTextChanged.connect(w._on_target_lock_selected)
    form.addRow("Person to follow", w.cb_target_lock)
    w.btn_unlock_target = QPushButton("Track everyone")
    w.btn_unlock_target.clicked.connect(w._unlock_target_focus)
    form.addRow(w.btn_unlock_target)
    w.chk_kalman = QCheckBox("Smooth positions (Kalman)")
    w.chk_kalman.setChecked(w.settings.get_kalman_enabled())
    w.chk_kalman.toggled.connect(w._on_kalman_toggled)
    form.addRow(w.chk_kalman)
    w.chk_unit = QCheckBox("Show distances in meters")
    w.chk_unit.toggled.connect(w._on_unit_toggled)
    form.addRow(w.chk_unit)
    w.sp_trail = QSpinBox()
    w.sp_trail.setRange(10, 500)
    w.sp_trail.setValue(w.settings.get_trail_length())
    w.sp_trail.valueChanged.connect(w._on_trail_length_changed)
    form.addRow("Trail length (points)", w.sp_trail)
    layout.addWidget(tracking)
    layout.addStretch()
    area = scroll_page(content)
    area.setMinimumWidth(245)
    w.control_dock.setWidget(area)
    w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, w.control_dock)
    w.control_dock.visibilityChanged.connect(w._controls_visibility_changed)


def _build_menus(w):
    workspace = w.menuBar().addMenu("Workspace")
    for i, title in enumerate(("Live radar", "Calibration", "Protocol inspector")):
        action = QAction(title, w)
        action.setShortcut(QKeySequence(f"Ctrl+{i+1}"))
        action.triggered.connect(lambda _, index=i: w.workspace_tabs.setCurrentIndex(index))
        workspace.addAction(action)
    data = w.menuBar().addMenu("Data")
    w.record_sessions_action = QAction("Record sessions", w)
    w.record_sessions_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
    w.record_sessions_action.triggered.connect(w._open_data_collection)
    data.addAction(w.record_sessions_action)
    w.dataset_visualization_action = QAction("Analyze dataset", w)
    w.dataset_visualization_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
    w.dataset_visualization_action.triggered.connect(w._open_dataset_visualization)
    data.addAction(w.dataset_visualization_action)
    view = w.menuBar().addMenu("View")
    controls = QAction("Connection controls", w)
    controls.setShortcut(QKeySequence("Ctrl+\\"))
    controls.triggered.connect(w._toggle_controls_panel)
    view.addAction(controls)
    monitor = view.addAction("Fall monitor")
    monitor.triggered.connect(w.fall_monitor_window.show)
