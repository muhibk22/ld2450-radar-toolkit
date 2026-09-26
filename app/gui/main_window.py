"""
Main Window for LD2450 Desktop Toolkit (Phase 2 with Dual Serial & Wi-Fi Network Streaming).
"""

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QSplitter, QCheckBox, QTabWidget, QFileDialog, QMessageBox, QSpinBox, QLineEdit
)
import time
from typing import List

from .packet_view import PacketViewWidget
from .telemetry_panel import TelemetryPanelWidget
from .radar_view import RadarViewWidget
from .diagnostics_panel import DiagnosticsPanelWidget
from .target_panel import TargetPanelWidget
from .tuning_panel import TuningPanelWidget
from .fall_monitor import FallMonitorWindow
from .data_collection import DataCollectionWindow

from ..serial.serial_reader import get_available_ports
from ..serial.serial_worker import SerialWorker
from ..net.socket_worker import SocketWorker
from ..parser.packet_parser import PacketParser
from ..parser.packet_decoder import PacketDecoder
from ..tracker.tracker import TargetTracker
from ..recording.recorder import DataRecorder
from ..utils.logger import setup_logger
from ..utils.settings import SettingsManager
from ..config import APP_NAME, DEFAULT_BAUD_RATE

logger = setup_logger("main_window")

class MainWindow(QMainWindow):
    """
    Protocol Explorer & Tracking Main Window.
    Supports dual communication modes: Serial USB & Wireless Wi-Fi Network Streaming.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - Wireless Wi-Fi & Serial Tracking Edition")
        self.resize(1350, 850)

        self.settings = SettingsManager()
        self.parser = PacketParser()
        self.decoder = PacketDecoder()
        self.tracker = TargetTracker()
        self.recorder = DataRecorder()
        self.frames_processed = 0
        self.active_worker = None  # SerialWorker or SocketWorker

        self.raw_log_file = None
        
        self.fall_monitor_window = FallMonitorWindow(self)
        
        self.data_collection_window = DataCollectionWindow(self)
        self.data_collection_window.start_recording_req.connect(self._on_start_data_collection)
        self.data_collection_window.stop_recording_req.connect(self._on_stop_data_collection)
        self.data_collection_window.label_changed.connect(self.recorder.set_action_label)

        self._setup_ui()

        # Stats refresh timer
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self._on_stats_tick)
        self.stats_timer.start()

        self._refresh_com_ports()

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # 1. Connection & Toolbar Layout
        toolbar = QHBoxLayout()

        # Mode Selector (Serial USB vs Wi-Fi TCP Network)
        toolbar.addWidget(QLabel("Connection:"))
        self.cb_conn_type = QComboBox()
        self.cb_conn_type.addItems(["Serial USB", "Wi-Fi (TCP Network)"])
        self.cb_conn_type.currentIndexChanged.connect(self._on_conn_type_changed)
        toolbar.addWidget(self.cb_conn_type)

        # --- Serial Mode Widgets ---
        self.lbl_com = QLabel("COM:")
        self.cb_ports = QComboBox()
        self.cb_ports.setMinimumWidth(100)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._refresh_com_ports)

        self.lbl_baud = QLabel("Baud:")
        self.cb_baud = QComboBox()
        self.cb_baud.addItems(["115200", "256000", "9600", "19200", "38400", "57600", "460800", "921600"])
        self.cb_baud.setCurrentText("115200")
        self.cb_baud.currentTextChanged.connect(self._on_baud_changed)

        self.btn_autobaud = QPushButton("Auto-Detect")
        self.btn_autobaud.setStyleSheet("background-color: #8B5CF6; color: white;")
        self.btn_autobaud.clicked.connect(self._auto_detect_baud)

        self.serial_widgets = [self.lbl_com, self.cb_ports, self.btn_refresh, self.lbl_baud, self.cb_baud, self.btn_autobaud]
        for w in self.serial_widgets:
            toolbar.addWidget(w)

        # --- Wi-Fi Mode Widgets ---
        self.lbl_ip = QLabel("IP / Host:")
        self.txt_ip = QLineEdit("192.168.100.130")
        self.txt_ip.setMinimumWidth(110)

        self.lbl_wifi_port = QLabel("Port:")
        self.sp_wifi_port = QSpinBox()
        self.sp_wifi_port.setRange(1, 65535)
        self.sp_wifi_port.setValue(8888)

        self.btn_discover_ip = QPushButton("Auto-Find IP")
        self.btn_discover_ip.setStyleSheet("background-color: #8B5CF6; color: white;")
        self.btn_discover_ip.clicked.connect(self._auto_discover_esp32_ip)

        self.wifi_widgets = [self.lbl_ip, self.txt_ip, self.lbl_wifi_port, self.sp_wifi_port, self.btn_discover_ip]
        for w in self.wifi_widgets:
            toolbar.addWidget(w)
            w.hide()  # Default is Serial mode

        # Connect / Reconnect Controls
        self.chk_auto_reconnect = QCheckBox("Auto Reconnect")
        self.chk_auto_reconnect.setChecked(True)
        toolbar.addWidget(self.chk_auto_reconnect)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold;")
        self.btn_connect.clicked.connect(self._toggle_connection)
        toolbar.addWidget(self.btn_connect)

        toolbar.addSpacing(10)

        # Tracking Toolbar Controls
        self.chk_kalman = QCheckBox("Kalman Filter")
        self.chk_kalman.setChecked(self.settings.get_kalman_enabled())
        self.chk_kalman.toggled.connect(self._on_kalman_toggled)
        toolbar.addWidget(self.chk_kalman)

        toolbar.addWidget(QLabel("Trails:"))
        self.sp_trail = QSpinBox()
        self.sp_trail.setRange(10, 500)
        self.sp_trail.setValue(self.settings.get_trail_length())
        self.sp_trail.valueChanged.connect(self._on_trail_length_changed)
        toolbar.addWidget(self.sp_trail)

        self.chk_unit = QCheckBox("Meters")
        self.chk_unit.toggled.connect(self._on_unit_toggled)
        toolbar.addWidget(self.chk_unit)

        # Single Target Focus Lock Controls
        toolbar.addSpacing(10)
        toolbar.addWidget(QLabel("Focus Lock:"))
        self.cb_target_lock = QComboBox()
        self.cb_target_lock.addItems(["Track All Targets", "Person A", "Person B", "Person C"])
        self.cb_target_lock.currentTextChanged.connect(self._on_target_lock_selected)
        toolbar.addWidget(self.cb_target_lock)

        self.btn_unlock_target = QPushButton("Unlock / Track All")
        self.btn_unlock_target.setStyleSheet("background-color: #F59E0B; color: black; font-weight: bold;")
        self.btn_unlock_target.clicked.connect(self._unlock_target_focus)
        toolbar.addWidget(self.btn_unlock_target)

        self.lbl_status = QLabel("Status: Disconnected")
        self.lbl_status.setStyleSheet("color: #F43F5E; font-weight: bold; padding-left: 10px;")
        toolbar.addWidget(self.lbl_status)

        self.lbl_fall_alert = QLabel("")
        self.lbl_fall_alert.setStyleSheet("color: white; background-color: #EF4444; font-weight: bold; padding: 5px; border-radius: 4px; margin-left: 10px;")
        self.lbl_fall_alert.hide()
        toolbar.addWidget(self.lbl_fall_alert)
        
        self.btn_fall_monitor = QPushButton("Fall Monitor")
        self.btn_fall_monitor.setStyleSheet("background-color: #8B5CF6; color: white; font-weight: bold;")
        self.btn_fall_monitor.clicked.connect(self.fall_monitor_window.show)
        toolbar.addWidget(self.btn_fall_monitor)

        self.btn_data_studio = QPushButton("Data Collection Studio")
        self.btn_data_studio.setStyleSheet("background-color: #EF4444; color: white; font-weight: bold;")
        self.btn_data_studio.clicked.connect(self.data_collection_window.show)
        toolbar.addWidget(self.btn_data_studio)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # 2. Main Content Splitter (Left: Raw Inspector & Telemetry Tables, Right: 2D Radar Canvas & Diagnostics)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Tab Widget
        left_tabs = QTabWidget()
        self.packet_view = PacketViewWidget()
        self.telemetry_panel = TelemetryPanelWidget()
        self.target_panel = TargetPanelWidget()
        self.tuning_panel = TuningPanelWidget()
        self.tuning_panel.settings_changed.connect(self.tracker.apply_tuning_settings)

        left_tabs.addTab(self.target_panel, "Persistent Human Telemetry")
        left_tabs.addTab(self.tuning_panel, "Tracker Tuning & Calibration")
        left_tabs.addTab(self.packet_view, "Raw Packet Inspector")
        left_tabs.addTab(self.telemetry_panel, "Decoded Fields & Unknown Bytes")
        main_splitter.addWidget(left_tabs)

        # Right Vertical Layout (Radar View + Diagnostics Panel)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.radar_view = RadarViewWidget()
        self.radar_view.target_clicked.connect(self._on_target_clicked_on_canvas)
        right_layout.addWidget(self.radar_view, stretch=2)

        self.diagnostics_panel = DiagnosticsPanelWidget()
        right_layout.addWidget(self.diagnostics_panel, stretch=1)

        main_splitter.addWidget(right_container)
        main_splitter.setSizes([700, 650])

        main_layout.addWidget(main_splitter, stretch=1)

        # Styling
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QPushButton {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 5px 10px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QComboBox, QSpinBox, QLineEdit {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
                color: #E2E8F0;
            }
            QCheckBox {
                color: #E2E8F0;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                background-color: #0F172A;
            }
            QTabBar::tab {
                background-color: #1E293B;
                color: #94A3B8;
                padding: 8px 16px;
                font-weight: bold;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #0284C7;
                color: white;
            }
        """)

    def _on_conn_type_changed(self, index: int):
        """Switches UI between Serial USB and Wi-Fi TCP mode."""
        if self.active_worker and self.active_worker.isRunning():
            self._toggle_connection()

        if index == 0:  # Serial USB
            for w in self.wifi_widgets:
                w.hide()
            for w in self.serial_widgets:
                w.show()
        else:  # Wi-Fi Network
            for w in self.serial_widgets:
                w.hide()
            for w in self.wifi_widgets:
                w.show()

    def _refresh_com_ports(self):
        self.cb_ports.clear()
        ports = get_available_ports()
        if ports:
            self.cb_ports.addItems(ports)
            last = self.settings.get_last_port()
            if last in ports:
                self.cb_ports.setCurrentText(last)
        else:
            self.cb_ports.addItem("No COM Ports")

    def _toggle_connection(self):
        if self.active_worker and self.active_worker.isRunning():
            self.active_worker.stop()
            self.active_worker = None
            self.btn_connect.setText("Connect")
            self.btn_connect.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold;")
            self._update_connection_status(False, "Disconnected")
            logger.info("Disconnected from server/port.")
            return

        auto_recon = self.chk_auto_reconnect.isChecked()
        is_wifi = (self.cb_conn_type.currentIndex() == 1)

        if is_wifi:
            host = self.txt_ip.text().strip()
            port = self.sp_wifi_port.value()
            if not host:
                QMessageBox.warning(self, "Wi-Fi Connection Error", "Please enter a valid IP address.")
                return

            self.active_worker = SocketWorker(host=host, port=port, auto_reconnect=auto_recon)
        else:
            port_name = self.cb_ports.currentText()
            if not port_name or port_name == "No COM Ports":
                QMessageBox.warning(self, "Connection Error", "Please select a valid COM port.")
                return

            baud = int(self.cb_baud.currentText())
            self.settings.set_last_port(port_name)
            self.settings.set_baud_rate(baud)
            self.active_worker = SerialWorker(port=port_name, baud_rate=baud, auto_reconnect=auto_recon)

        self.active_worker.raw_data_received.connect(self._on_raw_serial_data)
        self.active_worker.connection_changed.connect(self._update_connection_status)
        self.active_worker.stats_updated.connect(self.diagnostics_panel.update_diagnostics)
        self.active_worker.start()

        self.btn_connect.setText("Disconnect")
        self.btn_connect.setStyleSheet("background-color: #E11D48; color: white; font-weight: bold;")

    def _on_baud_changed(self, baud_str: str):
        if self.cb_conn_type.currentIndex() == 0 and self.active_worker and self.active_worker.isRunning():
            logger.info(f"Baud rate changed to {baud_str}. Reconnecting...")
            self._toggle_connection()
            QTimer.singleShot(200, self._toggle_connection)

    def _auto_discover_esp32_ip(self):
        import socket
        logger.info("Broadcasting UDP discovery ping for ESP32 Radar on port 8889...")
        found_ip = None

        try:
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_sock.settimeout(1.0)
            udp_sock.sendto(b"DISCOVER_LD2450", ("<broadcast>", 8889))
            
            data, addr = udp_sock.recvfrom(1024)
            resp = data.decode("utf-8", errors="ignore")
            if "LD2450_IP:" in resp:
                found_ip = resp.split("LD2450_IP:")[1].strip()
            elif addr[0]:
                found_ip = addr[0]
            udp_sock.close()
        except Exception as e:
            logger.debug(f"UDP discovery scan timeout/error: {e}")

        if not found_ip:
            try:
                found_ip = socket.gethostbyname("ld2450.local")
            except Exception:
                pass

        if found_ip:
            self.txt_ip.setText(found_ip)
            QMessageBox.information(self, "Auto-Discovery Success", f"Found ESP32 Radar on local network at {found_ip}!")
        else:
            QMessageBox.warning(self, "Auto-Discovery Notice", "Could not discover ESP32 automatically. Kept last known IP (e.g. 192.168.100.130).")

    def _auto_detect_baud(self):
        port = self.cb_ports.currentText()
        if not port or port == "No COM Ports":
            QMessageBox.warning(self, "Auto-Detect Error", "Please select a valid COM port first.")
            return

        candidate_bauds = ["115200", "256000", "9600", "57600", "460800"]
        logger.info(f"Starting Auto-Baud detection on {port}...")

        if self.active_worker and self.active_worker.isRunning():
            self.active_worker.stop()
            self.active_worker = None

        from ..serial.serial_reader import SerialReader
        found_baud = None

        for baud in candidate_bauds:
            reader = SerialReader(port=port, baud_rate=int(baud), timeout=0.3)
            try:
                if reader.connect():
                    time.sleep(0.15)
                    chunk = reader.read_available(1024)
                    reader.disconnect()
                    if bytes([0xAA, 0xFF]) in chunk or b"Target " in chunk:
                        found_baud = baud
                        break
            except Exception:
                pass

        if found_baud:
            self.cb_baud.setCurrentText(found_baud)
            QMessageBox.information(self, "Auto-Detect Success", f"Found valid LD2450 stream at {found_baud} baud!")
            self._toggle_connection()
        else:
            QMessageBox.warning(self, "Auto-Detect Failed", "Could not detect header at tested rates. Selected 115200.")
            self.cb_baud.setCurrentText("115200")
            self._toggle_connection()

    @Slot(bool, str)
    def _update_connection_status(self, connected: bool, info: str):
        if connected:
            self.lbl_status.setText(f"Status: Connected ({info})")
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold; padding-left: 10px;")
        else:
            self.lbl_status.setText(f"Status: {info}")
            self.lbl_status.setStyleSheet("color: #F43F5E; font-weight: bold; padding-left: 10px;")

    @Slot(bytes)
    def _on_raw_serial_data(self, data: bytes):
        """Processes stream data, updates raw inspector, runs tracker, and updates radar view."""
        self.packet_view.add_raw_chunk(data)
        frames, _ = self.parser.parse_stream(data)
        for f in frames:
            pkt = self.decoder.decode(f)
            self.packet_view.add_packet(pkt)
            self.telemetry_panel.update_packet(pkt)
            
            # Run Target Association & Filtering Engine
            tracked_targets = self.tracker.process(pkt.targets)
            
            self.frames_processed += 1
            if self.recorder.is_recording:
                self.recorder.record_frame(self.frames_processed, tracked_targets)
                
            self.radar_view.update_targets(tracked_targets)
            self.target_panel.update_targets(tracked_targets)
            
            # Check for Fall Alerts on Locked Target
            fall_alert = False
            fall_prob = 0.0
            fall_stage = "normal"
            if self.tracker.locked_target_id:
                for t in tracked_targets:
                    if str(t.id) == self.tracker.locked_target_id:
                        fall_alert = getattr(t, 'fall_alert', False)
                        fall_prob = getattr(t, 'fall_prob', 0.0)
                        fall_stage = getattr(t, 'fall_alert_stage', 'normal')
                        break
            
            if fall_stage == "confirmed":
                self.lbl_fall_alert.setText(f"🚨 FALL CONFIRMED! (Prob: {fall_prob:.2f})")
                self.lbl_fall_alert.show()
            elif fall_stage == "pre_alert":
                self.lbl_fall_alert.setText(f"⚠ POSSIBLE FALL (Prob: {fall_prob:.2f})")
                self.lbl_fall_alert.show()
            else:
                self.lbl_fall_alert.hide()
                
            self.fall_monitor_window.update_fall_status(fall_alert, fall_prob, fall_stage)
            
            # Feed alert history to the monitor
            if hasattr(self.tracker, 'post_fall_validator'):
                self.fall_monitor_window.update_alert_history(
                    self.tracker.post_fall_validator.alert_history
                )

    def _on_stats_tick(self):
        p_stats = self.parser.get_statistics()
        if self.cb_conn_type.currentIndex() == 0:
            conn_info = f"COM: {self.cb_ports.currentText()} @ {self.cb_baud.currentText()}"
        else:
            conn_info = f"Wi-Fi: {self.txt_ip.text()}:{self.sp_wifi_port.value()}"
        combined = {**p_stats, "conn_info": conn_info}
        self.diagnostics_panel.update_diagnostics(combined)

    def _on_kalman_toggled(self, checked: bool):
        self.settings.set_kalman_enabled(checked)
        if checked:
            self.tracker.mode = "PHYSICAL_GATE_KALMAN"
        else:
            self.tracker.mode = "PHYSICAL_GATE_AVG"

    def _on_target_lock_selected(self, target_label: str):
        target_id = None if target_label == "Track All Targets" else target_label
        self.tracker.set_target_lock(target_id)
        self.radar_view.set_locked_target(target_id)
        if target_id:
            logger.info(f"Target Focus Lock ACTIVATED on {target_id}. Ignoring all other targets/noise.")

    def _unlock_target_focus(self):
        self.cb_target_lock.setCurrentText("Track All Targets")
        self._on_target_lock_selected("Track All Targets")
        logger.info("Target Focus Lock DEACTIVATED. Resumed multi-target tracking.")

    def _on_target_clicked_on_canvas(self, target_id: str):
        logger.info(f"Canvas Clicked: Locking focus on target {target_id}")
        if self.cb_target_lock.findText(target_id) == -1:
            self.cb_target_lock.addItem(target_id)
        self.cb_target_lock.setCurrentText(target_id)

    def _on_trail_length_changed(self, val: int):
        self.settings.set_trail_length(val)
        self.radar_view.set_trail_length(val)

    def _on_unit_toggled(self, checked: bool):
        self.radar_view.set_display_unit_meters(checked)

    @Slot(str, dict)
    def _on_start_data_collection(self, filename: str, metadata: dict):
        try:
            self.recorder.start_recording(filename, format_type="csv", metadata=metadata)
            logger.info(f"Started dataset recording to {filename} with metadata: {metadata}")
        except Exception as e:
            logger.error(f"Failed to start dataset recording: {e}")

    @Slot(bool)
    def _on_stop_data_collection(self, save: bool = True):
        self.recorder.stop_recording(save=save)
        if save:
            logger.info("Dataset recording saved to disk and indexed.")
            self.statusBar().showMessage("Dataset recording saved and indexed.", 4000)
        else:
            logger.info("Dataset recording discarded and deleted.")
            self.statusBar().showMessage("Dataset recording discarded (file deleted).", 4000)

    def closeEvent(self, event):
        if self.active_worker:
            self.active_worker.stop()
        if self.raw_log_file:
            try:
                self.raw_log_file.close()
            except Exception:
                pass
        event.accept()
