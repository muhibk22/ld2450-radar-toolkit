"""Responsive workspace navigation and non-blocking hardware discovery."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import time
import traceback
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QScrollArea
from app.gui.main_window import MainWindow
from app.net.discovery import HardwareDiscoveryWorker


class WorkspaceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families() and os.name == 'nt':
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
            cls.app.setFont(QFont('Segoe UI', 10))

    def setUp(self):
        self.errors = []
        hook = sys.excepthook
        sys.excepthook = lambda *args: self.errors.append(''.join(traceback.format_exception(*args)))
        self.addCleanup(setattr, sys, 'excepthook', hook)
        with patch('app.gui.main_window.get_available_ports', return_value=['COM_TEST']):
            self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window.discovery_worker:
            self.window.discovery_worker.requestInterruption()
            self.window.discovery_worker.wait()
            self.app.processEvents()
        self.window.close()
        self.window.data_collection_window.close()
        self.app.processEvents()
        self.assertFalse(self.errors)

    def test_controls_and_navigation_fit_compact_and_wide_windows(self):
        w = self.window
        w.resize(1400, 900)
        self.app.processEvents()
        self.assertTrue(w.control_dock.isVisible())
        w.resize(1000, 720)
        self.app.processEvents()
        self.assertFalse(w.control_dock.isVisible())
        w.resize(760, 620)
        self.app.processEvents()
        self.assertLessEqual(w.width(), 760)
        for control in (w.controls_button, w.btn_data_studio, w.btn_analyze_dataset, w.btn_fall_monitor):
            position = control.mapTo(w, QPoint())
            self.assertGreaterEqual(position.x(), 0)
            self.assertLessEqual(position.x()+control.width(), w.width())
        w.controls_button.click()
        self.assertTrue(w.control_dock.isVisible())
        w.cb_conn_type.setCurrentIndex(1)
        self.assertTrue(w.wifi_widgets[0].isVisible())
        self.assertFalse(w.serial_widgets[0].isVisible())
        w.workspace_tabs.setCurrentIndex(1)
        self.assertFalse(w.control_dock.isVisible())
        self.assertEqual(w.workspace_tabs.tabText(2), 'Protocol inspector')
        w._on_target_clicked_on_canvas('Person A')
        self.assertEqual(w.tracker.locked_target_id, 'Person A')
        w._unlock_target_focus()
        self.assertIsNone(w.tracker.locked_target_id)
        w.btn_data_studio.click()
        self.assertTrue(w.data_collection_window.isVisible())
        record = w.data_collection_window
        record.resize(560, 540)
        self.app.processEvents()
        area = record.findChild(QScrollArea)
        area.ensureWidgetVisible(record.buttons['8'])
        self.app.processEvents()
        bottom = record.buttons['8'].mapTo(area.viewport(), QPoint())
        self.assertGreaterEqual(bottom.y(), 0)
        self.assertLessEqual(bottom.y()+record.buttons['8'].height(), area.viewport().height())
        button_position = record.btn_record.mapTo(record, QPoint())
        self.assertLessEqual(button_position.y()+record.btn_record.height(), record.height())
        self.assertTrue(record.btn_record.isVisible())

    def test_discovery_keeps_the_event_loop_alive_and_does_not_auto_connect(self):
        beats = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(time.monotonic()))
        def find(_):
            time.sleep(.2)
            return '192.0.2.1'
        with patch.object(HardwareDiscoveryWorker, '_wifi', find):
            timer.start()
            self.window._start_discovery('wifi')
            deadline = time.monotonic()+3
            while self.window.discovery_worker and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            timer.stop()
        self.assertIsNone(self.window.discovery_worker)
        self.assertGreater(len(beats), 3)
        self.assertEqual(self.window.txt_ip.text(), '192.0.2.1')
        self.assertTrue(self.window.btn_connect.isEnabled())
        self.assertIsNone(self.window.active_worker)

    def test_baud_probe_always_closes_a_successful_port(self):
        reader = Mock()
        reader.connect.return_value = True
        reader.read_available.return_value = b'\xaa\xff\x03'
        with patch('app.net.discovery.SerialReader', return_value=reader), patch('app.net.discovery.time.sleep'):
            worker = HardwareDiscoveryWorker('baud', 'COM_TEST')
            self.assertEqual(worker._baud(), '115200')
        reader.disconnect.assert_called_once()

    def test_close_during_discovery_waits_without_freezing(self):
        def find(_):
            time.sleep(.15)
            return '192.0.2.1'
        with patch.object(HardwareDiscoveryWorker, '_wifi', find):
            self.window._start_discovery('wifi')
            self.assertFalse(self.window.close())
            self.assertTrue(self.window.isVisible())
            deadline = time.monotonic()+3
            while self.window.isVisible() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.window.discovery_worker)
