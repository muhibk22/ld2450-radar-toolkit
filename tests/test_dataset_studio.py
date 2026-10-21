"""Offscreen UI checks for offline studio behavior and analysis export."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import sys
import traceback
import unittest
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea

from app.analysis.dataset import load_dataset
from app.gui.dataset_studio import DatasetStudioWindow
from tests.test_dataset_analysis import row, write


class DatasetStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families() and os.name == 'nt':
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
            cls.app.setFont(QFont('Segoe UI', 10))

    def setUp(self):
        self.qt_errors = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda *args: self.qt_errors.append("".join(traceback.format_exception(*args)))
        self.addCleanup(setattr, sys, "excepthook", previous_hook)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root/"a_session01.csv", [row(0), row(.1, x=100, label=6), row(1, x=200, label=6), row(1.1, label=7)])
        write(self.root/"b_session01.csv", [row(0), row(.1, x=50)])
        self.window = DatasetStudioWindow(directory=self.root, autoload=False)
        self.window.show()
        self.app.processEvents()
        self.window._loaded(load_dataset(self.root))

    def tearDown(self):
        self.window.shutdown()
        self.window.close()
        self.app.processEvents()
        self.assertEqual(self.qt_errors, [])

    def test_playback_gap_fall_alignment_filter_and_empty_state(self):
        self.assertEqual(self.window.session_table.rowCount(), 2)
        for i in range(4):
            self.window.tabs.setCurrentIndex(i)
            self.app.processEvents()
        self.window.tabs.setCurrentIndex(1)
        self.window._set_session(self.window.sessions[0])
        self.window._jump_to_fall()
        self.assertAlmostEqual(self.window.playhead, .1)
        self.window.playhead = .5
        self.window._update_playhead()
        self.assertFalse(self.window.human.isVisible())
        self.assertIn("gap", self.window.readout.text())
        self.window.alignment.setCurrentIndex(1)
        self.assertIn("no fall-onset label", self.window.compare_note.text())
        self.window.search.setText("no matching session")
        self.assertEqual(self.window.session_table.rowCount(), 0)
        self.assertFalse(self.window.play.isEnabled())
        self.assertFalse(self.window.export_button.isEnabled())
        self.window.search.clear()
        self.assertEqual(self.window.session_table.rowCount(), 2)

    def test_export_and_background_load_finish(self):
        output = self.window.export_to(self.root/"exports")
        self.assertEqual(len(list(output.glob("*.png"))), 4)
        self.assertTrue((output/"filters.json").exists())
        # Refresh must replace the selected track even if its table row stays selected.
        selected = self.window.current_session.path
        old_track = self.window.track
        write(selected, [row(0), row(.1), row(.2)])
        self.window.refresh()
        deadline = time.monotonic()+15
        while self.window.loader is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(self.window.loader)
        self.assertEqual(len(self.window.sessions), 2)
        self.assertEqual(self.window.current_session.path, selected)
        self.assertEqual(len(self.window.track.values), 3)
        self.assertIsNot(self.window.track, old_track)

    def test_compact_charts_browser_and_filter_reset(self):
        w = self.window
        w.resize(1480, 940)
        for _ in range(3):
            self.app.processEvents()
        self.assertTrue(w.browser_container.isVisible())
        self.assertEqual(w.overview_grid.columns, 2)
        w.resize(760, 620)
        for _ in range(3):
            self.app.processEvents()
        self.assertLessEqual(w.width(), 760)
        self.assertFalse(w.browser_container.isVisible())
        for index, grid in enumerate((w.overview_grid, w.playback_grid, w.comparison_grid, w.quality_grid)):
            w.tabs.setCurrentIndex(index)
            for _ in range(3):
                self.app.processEvents()
            self.assertEqual(grid.columns, 1)
            for first, second in zip(grid.widgets, grid.widgets[1:]):
                self.assertLessEqual(first.geometry().bottom(), second.geometry().top())
            page = w.tabs.widget(index)
            if index == 1:
                playback = page
                page = page.findChild(QScrollArea)
                page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
                self.assertTrue(playback.rect().contains(w.seek.mapTo(playback, QPoint())))
                self.assertTrue(playback.rect().contains(w.seek.mapTo(playback, QPoint(w.seek.width()-1, w.seek.height()-1))))
            self.assertGreater(page.verticalScrollBar().maximum(), 0)
            self.assertLessEqual(page.widget().width(), page.viewport().width())
        w.browser_toggle.click()
        self.assertTrue(w.browser_container.isVisible())
        w.search.setText('no matching session')
        self.assertEqual(w.session_table.rowCount(), 0)
        w._clear_filters()
        self.assertEqual(w.session_table.rowCount(), 2)
        self.assertTrue(all(control.currentIndex() == 0 for control in w.filters))

    def test_scrubber_updates_human_cursors_and_recent_trail_without_bridging_gaps(self):
        write(self.root/'a_session01.csv', [
            row(i/4, x=i*250, label=6 if i == 8 else 1)
            for i in range(33) if not 16 <= i < 20
        ])
        w = self.window
        w._loaded(load_dataset(self.root))
        w.tabs.setCurrentIndex(1)
        w._set_session(next(s for s in w.sessions if s.path.name == 'a_session01.csv'))
        w._toggle_play()
        w.seek.setValue(10000)
        self.assertFalse(w.playing)
        self.assertAlmostEqual(w.playhead, 8)
        self.assertAlmostEqual(w.human.pos().x(), 8)
        self.assertTrue(all(cursor.value() == 8 for cursor in w.cursors))
        x, _ = w.movement_trail.getData()
        self.assertAlmostEqual(np.nanmin(x), 5)
        self.assertAlmostEqual(np.nanmax(x), 8)
        self.assertIn('8.00 / 8.00 s', w.playback_clock.text())
        w.seek.setValue(6250)
        x, _ = w.movement_trail.getData()
        self.assertTrue(np.any(np.isnan(x)))
        self.assertAlmostEqual(np.nanmin(x), 2)
        self.assertAlmostEqual(np.nanmax(x), 5)
        w.seek.setValue(5000)
        self.assertFalse(w.human.isVisible())
        self.assertIn('gap', w.readout.text())
        w.trail_span.setCurrentIndex(4)
        x, _ = w.movement_trail.getData()
        self.assertAlmostEqual(np.nanmin(x), 0)
        self.assertLessEqual(np.nanmax(x), 4)
        w._jump_to_fall()
        self.assertAlmostEqual(w.playhead, 2)
        self.assertAlmostEqual(w.human.pos().x(), 2)
        w.search.setText('no matching session')
        self.assertFalse(w.seek.isEnabled())
        self.assertFalse(w.trail_span.isEnabled())
        self.assertEqual(w.playback_clock.text(), '0.00 / 0.00 s')

    def test_signal_panel_scroll_does_not_move_path_or_playhead(self):
        w = self.window
        w.resize(1480, 940)
        w.tabs.setCurrentIndex(1)
        for _ in range(4):
            self.app.processEvents()
        outer = w.tabs.widget(1).findChild(QScrollArea)
        outer_position = outer.verticalScrollBar().value()
        path_position = w.path_plot.geometry()
        playhead = w.playhead
        bar = w.signal_scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        viewport = w.signals[0].viewport()
        center = viewport.rect().center()
        event = QWheelEvent(QPointF(center), QPointF(viewport.mapToGlobal(center)),
                            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(viewport, event)
        self.app.processEvents()
        self.assertGreater(bar.value(), 0)
        bar.setValue(bar.maximum())
        self.app.sendEvent(viewport, event)
        self.app.processEvents()
        self.assertEqual(outer.verticalScrollBar().value(), outer_position)
        self.assertEqual(w.path_plot.geometry(), path_position)
        self.assertEqual(w.playhead, playhead)
        self.assertTrue(w.seek.isVisible())


if __name__ == "__main__":
    unittest.main()
