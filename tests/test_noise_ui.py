"""Noise selection, saved exclusions and lost-target confirmation UI regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PySide6.QtCore import QSettings,Qt,QPointF,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QPushButton
from app.gui.main_window import MainWindow
from app.utils.settings import SettingsManager
from tests.test_live_streaming import frame


class NoiseUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.settings=SettingsManager()
        self.settings.settings=QSettings(str(Path(self.folder.name)/'settings.ini'),QSettings.Format.IniFormat)
        with patch('app.gui.main_window.SettingsManager',return_value=self.settings),patch('app.gui.main_window.get_available_ports',return_value=[]):
            self.window=MainWindow()
        self.window.model_comparison.started=True

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.folder.cleanup()

    def test_click_mark_remove_and_saved_zone(self):
        w=self.window
        w.pipeline.ingest(frame(2500))
        w._on_target_clicked_on_canvas('Person A')
        w.noise_panel.mark_button.click()
        self.assertEqual(len(self.settings.get_noise_zones()),1)
        self.assertEqual(w.noise_panel.sources.count(),1)
        self.assertEqual(len(w.radar_view.noise_items),2)
        w.radar_view.set_display_unit_meters(True)
        curve_x,_=w.radar_view.noise_items[0].getData()
        self.assertAlmostEqual(max(curve_x),2.8,places=2)
        w.radar_view.set_display_unit_meters(False)
        self.assertFalse(w.tracker.tracked_persons)
        w.pipeline.reset()
        w.pipeline.ingest(frame(2500))
        self.assertFalse(w.tracker.tracked_persons)
        w.noise_panel.sources.setCurrentRow(0)
        remove=next(b for b in w.noise_panel.findChildren(QPushButton) if b.text()=='Remove selected exclusion')
        remove.click()
        self.assertEqual(self.settings.get_noise_zones(),[])
        self.assertFalse(w.radar_view.noise_items)
        w.pipeline.ingest(frame(2500))
        self.assertIn('Person A',w.tracker.tracked_persons)

    def test_right_click_offers_noise_action_without_left_click_lock(self):
        w=self.window
        w.pipeline.ingest(frame(2500))
        point=Mock()
        point.data.return_value={'tid':'Person A'}
        event=Mock()
        event.button.return_value=Qt.MouseButton.RightButton
        event.pos.return_value=QPointF(0,0)
        with patch.object(w.radar_view.scatter_item,'pointsAt',return_value=[point]),patch('app.gui.radar_view.QMenu') as menu:
            menu.return_value.exec.return_value=menu.return_value.addAction.return_value
            w.radar_view.scatter_item.mouseClickEvent(event)
        self.assertEqual(len(self.settings.get_noise_zones()),1)
        self.assertIsNone(w.tracker.locked_target_id)
        event.accept.assert_called()

    def test_model_backed_disappearance_confirms_on_empty_canvas(self):
        w=self.window
        service=w.model_comparison
        with patch('app.ml.model_comparison.time.time',return_value=1000):
            service.feed('Person A',1000,0,2000,0)
            for key in ('xgboost','minirocket','tcn','gru'):service._record(key,1000,.99)
        for i in range(1,18):
            timestamp=1000+i/10
            with patch('app.ml.model_comparison.time.time',return_value=timestamp):
                service.tracking_unavailable(timestamp,target_absent=True)
                service.poll(timestamp)
        with patch('app.ml.model_comparison.time.time',return_value=1001.7):w._render_stream()
        self.assertFalse(w.lbl_fall_alert.isHidden())
        self.assertIn('FALL DETECTED',w.lbl_fall_alert.text())
        self.assertEqual(w.fall_monitor_window.fall_count,1)


if __name__=='__main__':unittest.main()
