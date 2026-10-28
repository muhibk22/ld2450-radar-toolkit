"""Timing, inference isolation, and model event attribution regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from concurrent.futures import Future
from pathlib import Path
import tempfile
import csv
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
from app.ml.comparison_features import WindowBuffer, make_window
from app.ml.model_comparison import ModelComparison, DetectionState


class InlineExecutor:
    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **kwargs):
        pass


class ConstantModel:
    info = {'threshold':.7}
    def __init__(self,score=.9):
        self.score = score
    def predict(self,windows):
        return np.full(len(windows),self.score)


class ComparisonTests(unittest.TestCase):
    def service(self,models=None):
        with patch.object(ModelComparison,'_load',return_value=(models or {'tcn':ConstantModel(),'gru':ConstantModel(.1)},{})):
            service = ModelComparison(executor=InlineExecutor())
        self.addCleanup(service.close)
        return service

    def feed(self,service,timestamp,target='A',**kwargs):
        with patch('app.ml.model_comparison.time.time',return_value=timestamp):
            service.feed(target,timestamp,100,1500,200,**kwargs)
            service.poll(timestamp)

    def test_streaming_window_matches_direct_interpolation_and_resets_on_gap(self):
        buffer = WindowBuffer()
        rows = []
        outputs = []
        for t in np.arange(0,3,.08):
            rows.append([t,t*.5,2.,-.2])
            result = buffer.push(t,t*500,2000,-200)
            if result is not None:
                outputs.append(result)
                np.testing.assert_allclose(result,make_window(rows),atol=1e-6)
        self.assertGreater(len(outputs),0)
        self.assertIsNone(buffer.push(4,0,2000,0))
        self.assertEqual(len(buffer.rows),1)
        self.assertIsNone(buffer.push(4,0,2000,0))
        self.assertEqual(len(buffer.rows),1)

    def test_two_fresh_predictions_and_event_attribution(self):
        service = self.service()
        for i in range(26):
            self.feed(service,1000+i*.1)
        self.assertEqual(len(service.events),1)
        event = service.events[0]
        self.assertEqual(set(event['detections']),{'tcn'})
        self.assertAlmostEqual(event['timestamp'],1002.5)
        # Re-polling cached output must not produce a second event.
        for _ in range(10):
            service.poll(1002.5)
        self.assertEqual(len(service.events),1)
        self.assertNotIn('legacy',service.rows)

    def test_target_switch_discards_inflight_result(self):
        service = self.service()
        self.feed(service,1000)
        old_generation = service.generation
        pending = Future()
        service.future = pending
        self.feed(service,1000.1,target='B')
        pending.set_result((old_generation,'A',1000,{'tcn':dict(score=.99)},1.))
        service.poll(1000.2)
        self.assertEqual(service.events,[])
        self.assertIsNone(service.rows['tcn']['score'])
        self.assertEqual(service.target,'B')

    def test_stale_result_cannot_trigger(self):
        service = self.service()
        self.feed(service,1000)
        service.states['tcn'].positives = 1
        pending = Future()
        service.future = pending
        pending.set_result((service.generation,'A',999,{'tcn':dict(score=.99)},1.))
        service.poll(1000.1)
        self.assertEqual(service.events,[])
        self.assertEqual(service.states['tcn'].positives,0)

    def test_missing_artifacts_show_unavailable_without_false_votes(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ModelComparison(base=directory,executor=InlineExecutor())
            self.addCleanup(service.close)
            self.feed(service,1000)
            self.assertEqual(service.rows['tcn']['status'],'Unavailable')
            self.assertEqual(service.events,[])

    def test_gap_clears_hysteresis_and_stale_scores(self):
        service = self.service()
        for i in range(21):
            self.feed(service,1000+i*.1)
        self.assertEqual(service.states['tcn'].positives,1)
        service.poll(1003)
        self.assertIsNone(service.target)
        self.assertIsNone(service.rows['tcn']['score'])
        self.feed(service,1003.1)
        self.assertEqual(service.states['tcn'].positives,0)
        self.assertEqual(service.events,[])

    def test_positive_run_is_not_counted_repeatedly(self):
        state = DetectionState()
        self.assertFalse(state.update(0,True))
        self.assertTrue(state.update(.5,True))
        self.assertFalse(state.update(20,True))
        self.assertFalse(state.update(21,False))
        self.assertFalse(state.update(21.5,False))
        self.assertFalse(state.update(22,True))
        self.assertTrue(state.update(22.5,True))

    def test_error_in_one_model_does_not_hide_others(self):
        class Broken(ConstantModel):
            def predict(self,windows):
                raise RuntimeError('broken artifact')
        service = self.service({'tcn':ConstantModel(),'gru':Broken()})
        for i in range(26):
            self.feed(service,1000+i*.1)
        self.assertEqual(service.rows['gru']['status'],'Error')
        self.assertEqual(set(service.events[0]['detections']),{'tcn'})

    def test_whole_session_split_represents_every_person_without_overlap(self):
        from tools.train_comparison_models import session_split
        sessions = [SimpleNamespace(person=person,path=Path(f'{person}_session{i}.csv'),
                    counts={6:int(i<5)},excluded=False) for person in ('A','B','C') for i in range(10)]
        assignment = session_split(sessions,42)
        self.assertEqual(assignment,session_split(list(reversed(sessions)),42))
        self.assertEqual(len(assignment),len(sessions))
        for person in ('A','B','C'):
            self.assertEqual({assignment[s.path.name] for s in sessions if s.person==person},
                             {'train','validation','test'})

    def test_delayed_model_result_joins_earlier_legacy_event(self):
        service = self.service()
        self.feed(service,1000)
        service._record('gru',1000,.9)
        service._record('tcn',999.9,.9)
        self.assertEqual(len(service.events),1)
        self.assertEqual(service.events[0]['timestamp'],999.9)
        self.assertEqual(set(service.events[0]['detections']),{'gru','tcn'})

    def test_profile_change_invalidates_old_result_and_preserves_attributed_history(self):
        service = self.service()
        self.feed(service,1000)
        service._record('gru',1000,.9)
        old_profile = service.events[0]['profile']
        generation = service.generation
        pending = Future()
        service.future = pending
        with patch.object(service,'_load',return_value=({'tcn':ConstantModel()},{})):
            service.select_profile(service.base/'alternate'/'manifest.json')
        pending.set_result((generation,'A',1000,{'tcn':dict(score=.99)},1.))
        service.poll(1000.2)
        self.assertEqual(len(service.events),1)
        self.assertEqual(service.events[0]['profile'],old_profile)
        self.assertIsNone(service.rows['tcn']['score'])

    def test_all_five_votes_stay_pending_until_fresh_stillness(self):
        from app.ml.model_comparison import MODEL_NAMES
        service = self.service({k:ConstantModel() for k in MODEL_NAMES})
        for i in range(61):
            timestamp = 1000+i*.1
            with patch('app.ml.model_comparison.time.time',return_value=timestamp):
                service.feed('A',timestamp,100,2000,0)
                service.poll(timestamp)
            status = service.get_ensemble_status(timestamp)
            if 25 <= i < 60:
                self.assertEqual(status['stage'],'pre_alert')
                self.assertFalse(status['fall_alert'])
        self.assertTrue(status['fall_alert'])
        self.assertEqual(status['validation']['confirmed_at'],1006.0)
        self.assertEqual(len(service.events[0]['detections']),5)
        self.assertTrue(all(d['stage']=='detected' for d in service.events[0]['detections'].values()))
        self.assertTrue(service.get_ensemble_status(1008.1)['fall_alert'])
        self.assertFalse(service.get_ensemble_status(1012)['fall_alert'])

    def test_raw_reversal_rejects_all_votes_even_with_frozen_smoothed_input(self):
        from app.ml.model_comparison import MODEL_NAMES
        service = self.service({k:ConstantModel() for k in MODEL_NAMES})
        for i in range(90):
            timestamp = 1000+i*.1
            with patch('app.ml.model_comparison.time.time',return_value=timestamp):
                raw_x=i*150 if i<25 else 3750-(i-25)*150
                service.feed('A',timestamp,100,2000,0,validation_x_mm=raw_x,validation_y_mm=2000)
                service.poll(timestamp)
        status = service.get_ensemble_status(timestamp)
        self.assertEqual(status['votes'],5)
        self.assertFalse(status['fall_alert'])
        self.assertEqual(status['stage'],'rejected')
        self.assertIn('reverse running',service.events[0]['validation']['reason'])

    def test_pending_validation_interrupted_by_gap_switch_and_reset(self):
        from app.ml.model_comparison import MODEL_NAMES
        for interruption in ('gap','switch','reset'):
            with self.subTest(interruption=interruption):
                service = self.service({k:ConstantModel() for k in MODEL_NAMES})
                for i in range(30):
                    self.feed(service,1000+i*.1)
                self.assertEqual(service.events[0]['validation']['state'],'validating')
                if interruption == 'gap':
                    service.poll(1003.5)
                elif interruption == 'switch':
                    self.feed(service,1003,target='B')
                else:
                    service.reset_stream()
                self.assertEqual(service.events[0]['validation']['state'],'suspected')
                self.assertFalse(service.get_ensemble_status(1003.5)['fall_alert'])
                self.assertEqual(service.get_ensemble_status(2000)['warning_count'],1)
                service.reset_stream()
                self.assertEqual(service.get_ensemble_status(2001)['stage'],'suspected')
                service.acknowledge_warnings(service.events[0]['id'])
                self.assertEqual(service.get_ensemble_status(2001)['warning_count'],0)

    def test_live_pipeline_passes_accepted_position_for_validation(self):
        from app.ml.model_comparison import MODEL_NAMES
        from app.streaming import LivePipeline
        from tests.test_live_streaming import frame
        service = self.service({k:ConstantModel() for k in MODEL_NAMES})
        pipeline = LivePipeline(service)
        # Short runs in each direction: signed coordinate encoding follows LD2450.
        for i in range(55):
            timestamp = 1000+i*.1
            x = 1000+100*i if i < 25 else 3500-100*(i-25)
            with patch('app.ml.model_comparison.time.time',return_value=timestamp):
                pipeline.ingest(frame(x),now=timestamp,received=timestamp)
                service.poll(timestamp)
        self.assertTrue(service.events)
        self.assertEqual(service.events[0]['validation']['state'],'rejected')
        self.assertGreater(service.events[0]['validation']['max_planar_speed_mms'],700)
        self.assertFalse(service.get_ensemble_status(timestamp)['fall_alert'])

    def test_recent_confirmation_survives_target_loss_during_alert_hold(self):
        from app.ml.model_comparison import MODEL_NAMES
        service=self.service({k:ConstantModel() for k in MODEL_NAMES})
        for i in range(61):
            timestamp=1000+i*.1
            with patch('app.ml.model_comparison.time.time',return_value=timestamp):
                service.feed('A',timestamp,0,2000,0)
                service.poll(timestamp)
        self.assertTrue(service.get_ensemble_status(timestamp)['fall_alert'])
        service.poll(timestamp+1)
        self.assertEqual(service.get_ensemble_status(timestamp+1)['stage'],'confirmed')
        self.assertEqual(service.events[0]['validation']['confirmed_at'],1006)

    def test_unresolved_warning_survives_normal_history_rotation(self):
        service=self.service()
        self.feed(service,1000)
        for key in ('xgboost','minirocket','tcn','gru'):
            service._record(key,1000,.99)
        service.poll(1001)
        original=service.events[0]['id']
        for i in range(205):
            service.target='A'
            service._record('tcn',1010+i*9,.9)
        self.assertIn(original,[e['id'] for e in service.events])
        self.assertEqual(service.get_ensemble_status(4000)['warning_count'],1)


class ComparisonUITests(unittest.TestCase):
    def test_tracking_loss_banner_survives_empty_canvas_and_acknowledges(self):
        from PySide6.QtWidgets import QApplication
        from app.gui.main_window import MainWindow
        app=QApplication.instance() or QApplication([])
        with patch('app.gui.main_window.get_available_ports',return_value=[]):
            window=MainWindow()
        try:
            service=window.model_comparison
            service.started=True
            with patch('app.ml.model_comparison.time.time',return_value=1000):
                service.feed('Person A',1000,0,2000,0)
                for key in ('xgboost','minirocket','tcn','gru'):
                    service._record(key,1000,.99)
            service.poll(1001)
            window._render_stream()
            window.fall_monitor_window.update_comparison(service.snapshot())
            self.assertFalse(window.lbl_fall_alert.isHidden())
            self.assertIn('SUSPECTED FALL',window.lbl_fall_alert.text())
            self.assertIn('Tracking lost',window.lbl_fall_alert.text())
            self.assertEqual(window.fall_monitor_window.fall_count,0)
            self.assertTrue(window.fall_monitor_window.btn_acknowledge.isEnabled())
            window.fall_monitor_window.btn_acknowledge.click()
            window._render_stream()
            window.fall_monitor_window.update_comparison(service.snapshot())
            self.assertTrue(window.lbl_fall_alert.isHidden())
            self.assertFalse(window.fall_monitor_window.btn_acknowledge.isEnabled())
            self.assertIsNotNone(service.events[0]['acknowledged_at'])
        finally:
            window.close()
            window.deleteLater()
            from PySide6.QtCore import QCoreApplication,QEvent
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()

    def test_table_and_export_keep_model_identity(self):
        from PySide6.QtWidgets import QApplication
        from app.gui.fall_monitor import FallMonitorWindow
        app = QApplication.instance() or QApplication([])
        with patch.object(ModelComparison,'_load',return_value=({},{})):
            service = ModelComparison(executor=InlineExecutor())
        window = FallMonitorWindow()
        try:
            with patch('app.ml.model_comparison.time.time',return_value=1000):
                service.feed('A',1000)
                service._record('xgboost',1000,.8)
            window.update_comparison(service.snapshot())
            self.assertEqual(window.comparison_table.rowCount(),5)
            self.assertEqual(window.event_table.rowCount(),1)
            self.assertNotEqual(window.event_table.item(0,3).text(),'—')
            self.assertEqual(window.event_table.item(0,4).text(),'—')
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory)/'events.csv')
                with patch('app.gui.fall_monitor.QFileDialog.getSaveFileName',return_value=(path,'CSV')):
                    window._export_comparison()
                self.assertIn('xgboost',Path(path).read_text(encoding='utf-8'))
                with open(path,newline='',encoding='utf-8') as handle:
                    exported = list(csv.DictReader(handle))
                self.assertEqual(exported[0]['validation_state'],'awaiting_votes')
                self.assertIn('validation_reason',exported[0])
        finally:
            service.close()
            window.close()
            window.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()

    def test_four_of_five_models_required_for_fall_alert(self):
        """Enforces that fall alerts are strictly suppressed unless at least 4/5 models detect it."""
        from app.ml.model_comparison import MODEL_NAMES
        models = {k: ConstantModel(0.9) for k in MODEL_NAMES}
        with patch.object(ModelComparison, '_load', return_value=(models, {})):
            service = ModelComparison(executor=InlineExecutor())
        try:
            timestamp = 1000.0
            # Feed target
            with patch('app.ml.model_comparison.time.time', return_value=timestamp):
                service.feed('A', timestamp, 100, 1500, 200)
                service._record('gru', timestamp, .9)
                service.poll(timestamp)

            # 1. Only one model has detected so far.
            status1 = service.get_ensemble_status(timestamp)
            self.assertEqual(status1['votes'], 1)
            self.assertFalse(status1['fall_alert'], "1/5 models must NOT trigger a fall alert!")

            # 2. Add second model detection
            service._record('xgboost', timestamp, 0.95)
            status2 = service.get_ensemble_status(timestamp)
            self.assertEqual(status2['votes'], 2)
            self.assertFalse(status2['fall_alert'], "2/5 models must NOT trigger a fall alert!")

            # 3. Add third model detection
            service._record('tcn', timestamp, 0.92)
            status3 = service.get_ensemble_status(timestamp)
            self.assertEqual(status3['votes'], 3)
            self.assertFalse(status3['fall_alert'], "3/5 models must NOT trigger a fall alert!")

            # 4. Add fourth model detection -> Reaches 4/5 consensus!
            service._record('minirocket', timestamp, 0.99)
            status4 = service.get_ensemble_status(timestamp)
            self.assertEqual(status4['votes'], 4)
            self.assertFalse(status4['fall_alert'], "Consensus must wait for post-fall validation")
            self.assertEqual(status4['stage'], 'pre_alert')
        finally:
            service.close()

    def test_fall_monitor_ui_suppresses_alert_without_four_votes(self):
        """Verifies that the Fall Monitor Window suppresses alerts when votes < 4."""
        from PySide6.QtWidgets import QApplication
        from app.gui.fall_monitor import FallMonitorWindow
        app = QApplication.instance() or QApplication([])
        window = FallMonitorWindow()
        try:
            # Stage confirmed but votes = 3 (< 4) -> MUST NOT count as a fall!
            window.update_fall_status(is_falling=True, probability=0.95, stage="confirmed", votes=3)
            self.assertEqual(window.fall_count, 0, "Fall count must NOT increment when votes < 4!")
            self.assertFalse(window.is_falling)
            self.assertIn("3/5", window.lbl_state.text())

            window.update_fall_status(is_falling=False,probability=.99,stage='pre_alert',votes=5)
            self.assertEqual(window.fall_count,0)
            self.assertIn('CHECKING',window.lbl_state.text())
            window.update_fall_status(is_falling=False,probability=.99,stage='rejected',votes=5)
            self.assertEqual(window.fall_count,0)
            self.assertIn('REJECTED',window.lbl_state.text())

            # Now votes = 4 (>= 4) -> MUST trigger confirmed fall alert!
            window.update_fall_status(is_falling=True, probability=0.95, stage="confirmed", votes=4)
            self.assertEqual(window.fall_count, 1, "Fall count MUST increment when 4/5 models agree!")
            self.assertTrue(window.is_falling)
            self.assertIn("FALL CONFIRMED", window.lbl_state.text())
        finally:
            window.close()
            window.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


if __name__ == '__main__':
    unittest.main()

