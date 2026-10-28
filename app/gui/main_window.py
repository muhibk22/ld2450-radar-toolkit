"""
Main Window for LD2450 Desktop Toolkit (Phase 2 with Dual Serial & Wi-Fi Network Streaming).
"""

from PySide6.QtCore import QTimer, Slot, QSignalBlocker
from PySide6.QtWidgets import QMainWindow, QMessageBox
from .fall_monitor import FallMonitorWindow
from .data_collection import DataCollectionWindow

from ..serial.serial_reader import get_available_ports
from ..serial.serial_worker import SerialWorker
from ..net.socket_worker import SocketWorker
from ..parser.packet_parser import PacketParser
from ..parser.packet_decoder import PacketDecoder
from ..tracker.tracker import TargetTracker
from ..recording.buffered import BufferedRecorder as DataRecorder
from ..utils.logger import setup_logger
from ..utils.settings import SettingsManager
from ..config import APP_NAME
from ..ml.model_comparison import ModelComparison
from ..streaming import LivePipeline
import time

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
        self.recorder = DataRecorder()
        self.frames_processed = 0
        self.active_worker = None  # SerialWorker or SocketWorker

        self.raw_log_file = None
        self.dataset_studio_window = None
        
        self.fall_monitor_window = FallMonitorWindow(self)
        self.model_comparison = ModelComparison(autoload=False)
        self.pipeline = LivePipeline(self.model_comparison, self.recorder)
        self.tracker = self.pipeline.tracker
        self.pipeline.set_noise_zones(self.settings.get_noise_zones())
        self.parser, self.decoder = self.pipeline.parser, self.pipeline.decoder
        self._stream_session = self.pipeline.session
        self._worker_stats = {}
        self._closing_for_worker = False
        self._render_key = None
        self.fall_monitor_window.comparison_profile_changed.connect(self.model_comparison.select_profile)
        self.fall_monitor_window.validation_warnings_acknowledged.connect(self.model_comparison.acknowledge_warnings)
        self.comparison_timer = QTimer(self)
        self.comparison_timer.setInterval(100)
        self.comparison_timer.timeout.connect(self._poll_model_comparison)
        self.comparison_timer.start()
        
        self.data_collection_window = DataCollectionWindow(self)
        self.data_collection_window.start_recording_req.connect(self._on_start_data_collection)
        self.data_collection_window.stop_recording_req.connect(self._on_stop_data_collection)
        self.data_collection_window.label_changed.connect(self.recorder.set_action_label)

        self._setup_ui()
        self._refresh_noise_zones()
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(33)
        self.render_timer.timeout.connect(self._render_stream)
        self.render_timer.start()

        # Stats refresh timer
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self._on_stats_tick)
        self.stats_timer.start()

        self._refresh_com_ports()

    def _setup_ui(self):
        from .workspace_ui import build_workspace
        build_workspace(self)

    def _open_data_collection(self):
        self.data_collection_window.show()
        self.data_collection_window.raise_()
        self.data_collection_window.activateWindow()

    def _set_controls_visible(self, visible):
        self._adjusting_dock = True
        self.control_dock.setVisible(visible)
        self.controls_button.setChecked(visible)
        self._adjusting_dock = False

    def _toggle_controls_panel(self, *_):
        wanted = not self.control_dock.isVisible()
        self._controls_requested = wanted
        self.workspace_tabs.setCurrentIndex(0)
        self._set_controls_visible(wanted)

    def _controls_visibility_changed(self, visible):
        if not self._adjusting_dock and self.isVisible() and self.workspace_tabs.currentIndex() == 0:
            self._controls_requested = visible
            self.controls_button.setChecked(visible)

    def _workspace_changed(self, index):
        self._set_controls_visible(index == 0 and self._controls_requested and not self._compact_mode)

    def _update_responsive_layout(self):
        compact = self.width() < 1100
        if compact != self._compact_mode:
            self._compact_mode = compact
            self._set_controls_visible(not compact and self._controls_requested and self.workspace_tabs.currentIndex() == 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'control_dock'):
            self._update_responsive_layout()

    def _open_dataset_visualization(self):
        # Load the offline module only when requested; hardware startup stays unchanged.
        if self.dataset_studio_window is None:
            from .dataset_studio import DatasetStudioWindow
            self.dataset_studio_window = DatasetStudioWindow(self)
        self.dataset_studio_window.show()
        self.dataset_studio_window.raise_()
        self.dataset_studio_window.activateWindow()

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
            worker = self.active_worker
            if not worker.stop():
                self.statusBar().showMessage('Waiting for the previous connection to close...',3000)
                return
            self.active_worker = None
            self.pipeline.reset()
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

            self.active_worker = SocketWorker(host=host, port=port, auto_reconnect=auto_recon, pipeline=self.pipeline)
            self.settings.settings.setValue('network/host',host)
            self.settings.settings.setValue('network/port',port)
        else:
            port_name = self.cb_ports.currentText()
            if not port_name or port_name == "No COM Ports":
                QMessageBox.warning(self, "Connection Error", "Please select a valid COM port.")
                return

            baud = int(self.cb_baud.currentText())
            self.settings.set_last_port(port_name)
            self.settings.set_baud_rate(baud)
            self.active_worker = SerialWorker(port=port_name, baud_rate=baud, auto_reconnect=auto_recon, pipeline=self.pipeline)

        self.active_worker.connection_changed.connect(self._update_connection_status)
        self.active_worker.stats_updated.connect(self._receive_worker_stats)
        self.model_comparison.start()
        self.active_worker.start()

        self.btn_connect.setText("Disconnect")
        self.btn_connect.setStyleSheet("background-color: #E11D48; color: white; font-weight: bold;")

    def _on_baud_changed(self, baud_str: str):
        if self.cb_conn_type.currentIndex() == 0 and self.active_worker and self.active_worker.isRunning():
            logger.info(f"Baud rate changed to {baud_str}. Reconnecting...")
            self._toggle_connection()
            QTimer.singleShot(200, self._toggle_connection)

    def _auto_discover_esp32_ip(self):
        self._start_discovery('wifi')

    def _auto_detect_baud(self):
        port = self.cb_ports.currentText()
        if not port or port == 'No COM Ports':
            self.lbl_discovery.setText('Choose a serial port before detecting its baud rate.')
            return
        if self.active_worker and self.active_worker.isRunning():
            self._toggle_connection()
        self._start_discovery('baud', port)

    def _start_discovery(self, mode, port=''):
        if self.discovery_worker is not None:
            return
        from ..net.discovery import HardwareDiscoveryWorker
        self.discovery_worker = HardwareDiscoveryWorker(mode, port, self)
        self.discovery_worker.progress.connect(self.lbl_discovery.setText)
        self.discovery_worker.found.connect(lambda value: self._discovery_found(mode, value))
        self.discovery_worker.failed.connect(self.lbl_discovery.setText)
        self.discovery_worker.finished.connect(self._discovery_finished)
        for control in (self.btn_autobaud, self.btn_discover_ip, self.btn_connect, self.cb_conn_type, self.btn_refresh, self.cb_baud, self.cb_ports):
            control.setEnabled(False)
        self.lbl_discovery.setText('Searching for a radar deviceÃ¢â‚¬Â¦')
        self.discovery_worker.start()

    def _discovery_found(self, mode, value):
        if self._closing_for_discovery:
            return
        if mode == 'wifi':
            self.txt_ip.setText(value)
            self.lbl_discovery.setText(f'Found {value}. Press Connect when ready.')
        else:
            self.cb_baud.blockSignals(True)
            self.cb_baud.setCurrentText(value)
            self.cb_baud.blockSignals(False)
            self.lbl_discovery.setText(f'Detected {value} baud. Press Connect when ready.')

    def _discovery_finished(self):
        worker = self.discovery_worker
        self.discovery_worker = None
        if worker is not None:
            worker.deleteLater()
        for control in (self.btn_autobaud, self.btn_discover_ip, self.btn_connect, self.cb_conn_type, self.btn_refresh, self.cb_baud, self.cb_ports):
            control.setEnabled(True)
        if self._closing_for_discovery:
            QTimer.singleShot(0, self.close)

    @Slot(bool, str)
    def _update_connection_status(self, connected: bool, info: str):
        if self.sender() is not self.active_worker:
            return
        if connected:
            self.lbl_status.setText(f"Status: Connected ({info})")
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold; padding-left: 10px;")
        else:
            self.lbl_status.setText(f"Status: {info}")
            self.lbl_status.setStyleSheet("color: #F43F5E; font-weight: bold; padding-left: 10px;")

    @Slot(dict)
    def _receive_worker_stats(self, stats):
        if self.sender() is self.active_worker:
            self._worker_stats = stats

    @Slot(bytes)
    def _on_raw_serial_data(self, data):
        """Compatibility entry for replay; transports ingest on their own thread."""
        self.pipeline.ingest(data)

    def _render_stream(self):
        snapshot = self.pipeline.drain()
        if snapshot is None:
            return
        self.frames_processed = snapshot['frames']
        if snapshot['session'] != self._stream_session:
            self._stream_session = snapshot['session']
            self.radar_view.trail_manager.clear()
            self.cb_target_lock.setCurrentText('Track All Targets')
        for chunk in snapshot['chunks']:
            self.packet_view.add_raw_chunk(chunk)
        for packet in snapshot['packets']:
            self.packet_view.add_packet(packet)
        if snapshot['packets'] and self.telemetry_panel.isVisible():
            self.telemetry_panel.update_packet(snapshot['packets'][-1])
        targets = snapshot['targets']
        self.radar_view.set_noise_zones(snapshot['noise_zones'])
        ensemble = self.model_comparison.get_ensemble_status()
        votes,score = ensemble['votes'],ensemble['avg_score']
        alert = ensemble['fall_alert']
        stage = ensemble['stage']
        if stage == 'confirmed' and not alert:
            stage = 'normal'
        for t in targets:
            if ensemble['applies_to_current_target'] and str(t.id) == ensemble['target']:
                t.fall_alert,t.fall_votes,t.fall_prob = alert,votes,score
                t.fall_alert_stage = stage
        render_key = (snapshot['session'],snapshot['revision'],bool(targets),alert,votes,stage)
        if render_key != self._render_key:
            self.radar_view.update_targets(targets)
            if self.target_panel.isVisible():
                self.target_panel.update_targets(targets)
            self._render_key = render_key
        if alert:
            self.lbl_fall_alert.setText(f'FALL DETECTED ({votes}/5 models | Score: {score:.2f})')
            self.lbl_fall_alert.setStyleSheet('color: white; background-color: #DC2626; padding: 8px; font-weight: bold;')
            self.lbl_fall_alert.show()
        elif stage == 'pre_alert':
            validation = ensemble['validation']
            self.lbl_fall_alert.setText(f"Checking post-fall motion ({votes}/5 models): "
                                       f"{validation.get('elapsed_s',0):.1f}/{validation.get('observation_seconds',5):.1f}s")
            self.lbl_fall_alert.setStyleSheet('color: #1E293B; background-color: #F59E0B; padding: 8px; font-weight: bold;')
            self.lbl_fall_alert.show()
        elif stage == 'suspected':
            self.lbl_fall_alert.setText(f"SUSPECTED FALL — {ensemble['target']}: "
                                       f"{ensemble['validation']['reason']} ({ensemble['warning_count']} unresolved)")
            self.lbl_fall_alert.setStyleSheet('color: #1E293B; background-color: #F59E0B; padding: 8px; font-weight: bold;')
            self.lbl_fall_alert.show()
        else:
            self.lbl_fall_alert.hide()
        self.fall_monitor_window.update_fall_status(alert,score,stage,votes=votes)
        if self._closing_for_worker and self.active_worker and not self.active_worker.isRunning():
            self.close()

    def _poll_model_comparison(self):
        self.model_comparison.poll()
        self.fall_monitor_window.update_comparison(self.model_comparison.snapshot())

    def _on_stats_tick(self):
        snapshot = self.pipeline.drain(preview=False)
        if snapshot is None:
            return
        self.diagnostics_panel.update_diagnostics({**self._worker_stats,**snapshot['stats'],
            'frame_age_s':snapshot['frame_age_s'],'byte_age_s':snapshot['byte_age_s']})
        if self.recorder.error:
            self.statusBar().showMessage(self.recorder.error)

    def _on_kalman_toggled(self, checked: bool):
        self.settings.set_kalman_enabled(checked)
        self.tuning_panel.cb_mode.setCurrentIndex(2 if checked else 0)
        if checked:
            self.pipeline.configure({"mode":"PHYSICAL_GATE_KALMAN"})
        else:
            self.pipeline.configure({"mode":"PHYSICAL_GATE_AVG"})

    def _apply_tracking_settings(self, settings):
        self.pipeline.configure(settings)
        with QSignalBlocker(self.chk_kalman):
            self.chk_kalman.setChecked(settings['mode'] == 'PHYSICAL_GATE_KALMAN')

    def _on_target_lock_selected(self, target_label: str):
        target_id = None if target_label == "Track All Targets" else target_label
        self.pipeline.configure(target=target_id,set_target=True)
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

    def _refresh_noise_zones(self):
        zones=self.pipeline.noise_zones()
        self.noise_panel.set_zones(zones)
        self.radar_view.set_noise_zones(zones)

    def _set_noise_zones(self,zones):
        self.pipeline.set_noise_zones(zones)
        self.settings.set_noise_zones(self.pipeline.noise_zones())
        self._refresh_noise_zones()
        self._render_key=None

    def _mark_focused_as_noise(self):
        self._mark_noise_target(self.tracker.locked_target_id or '')

    def _mark_noise_target(self,target_id):
        try:
            self.pipeline.mark_noise(target_id,self.noise_panel.radius.value())
        except ValueError as exc:
            self.statusBar().showMessage(str(exc),5000)
            return
        self.settings.set_noise_zones(self.pipeline.noise_zones())
        self._refresh_noise_zones()
        self.radar_view.trail_manager.clear()
        self._render_key=None
        if self.tracker.locked_target_id is None:
            with QSignalBlocker(self.cb_target_lock):
                self.cb_target_lock.setCurrentText('Track All Targets')
            self.radar_view.set_locked_target(None)
        self.statusBar().showMessage('Noise exclusion saved. Manage it under Live radar → Noise exclusions.',6000)

    def _remove_noise_zone(self,zone_id):
        self._set_noise_zones([z for z in self.pipeline.noise_zones() if z['id']!=zone_id])

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
        if self.discovery_worker and self.discovery_worker.isRunning():
            self._closing_for_discovery = True
            self.discovery_worker.requestInterruption()
            self.statusBar().showMessage('Finishing device discovery before closingÃ¢â‚¬Â¦')
            event.ignore()
            return
        if self.dataset_studio_window is not None:
            self.dataset_studio_window.shutdown()
            self.dataset_studio_window.close()
        if self.active_worker and self.active_worker.isRunning():
            self._closing_for_worker = True
            self.active_worker.request_stop()
            event.ignore()
            return
        self.recorder.close()
        if self.raw_log_file:
            try:
                self.raw_log_file.close()
            except Exception:
                pass
        self.render_timer.stop()
        self.stats_timer.stop()
        self.comparison_timer.stop()
        self.model_comparison.close()
        event.accept()
