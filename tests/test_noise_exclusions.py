"""Noise is excluded before clustering and every identity search path."""
import tempfile
import time
from pathlib import Path
import unittest
import struct
from unittest.mock import patch
from PySide6.QtCore import QSettings
from app.models.target import Target
from app.tracker.tracker import TargetTracker
from app.streaming import LivePipeline
from app.utils.settings import SettingsManager
from app.ml.model_comparison import ModelComparison


def target(x,y=2000,slot=0):
    return Target(f'raw{slot}',slot,x=x,y=y,distance_resolution=360)


class NoiseExclusionTests(unittest.TestCase):
    def test_marked_source_cannot_capture_a_lost_locked_person(self):
        tracker=TargetTracker()
        tracker.process([target(0),target(2500,slot=1)],timestamp=1000)
        tracker.mark_noise('Person B',300)
        tracker.set_target_lock('Person A')
        for i in range(70):
            out=tracker.process([target(2500,slot=i%3)],timestamp=1000+(i+1)*.1)
            self.assertTrue(all(t.status!='Active' for t in out))
            self.assertEqual(tracker.tracked_persons['Person A'].model_window[-1],(0,2000))
        out=tracker.process([target(100),target(2500,slot=2)],timestamp=1007.2)
        self.assertEqual(out[0].id,'Person A')
        self.assertEqual(out[0].status,'Active')
        self.assertLess(out[0].x,500)

    def test_exclusion_precedes_merging_and_applies_in_raw_mode(self):
        for mode in ('RAW','ROLLING_AVG','PHYSICAL_GATE_AVG','PHYSICAL_GATE_KALMAN'):
            tracker=TargetTracker()
            tracker.mode=mode
            tracker.set_noise_zones([dict(id='noise',x_mm=700,y_mm=2000,radius_mm=200)])
            out=tracker.process([target(0),target(700,slot=1)],timestamp=1000)
            self.assertEqual(len(out),1)
            self.assertAlmostEqual(out[0].x,0)
            self.assertEqual(tracker.noise_filtered_count,1)

    def test_clear_and_reset_preserve_expected_exclusion_behavior(self):
        tracker=TargetTracker()
        tracker.process([target(1000)],timestamp=1000)
        tracker.mark_noise('Person A',250)
        tracker.reset()
        self.assertFalse(tracker.process([target(1000,slot=2)],timestamp=1001))
        tracker.set_noise_zones([])
        self.assertEqual(len(tracker.process([target(1000)],timestamp=1002)),1)

    def test_noise_settings_round_trip_uses_position_not_person_label(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=SettingsManager()
            path=str(Path(folder)/'test.ini')
            settings.settings=QSettings(path,QSettings.Format.IniFormat)
            records=[dict(id='fan',x_mm=1000,y_mm=2500,radius_mm=300)]
            settings.set_noise_zones(records)
            settings.settings=QSettings(path,QSettings.Format.IniFormat)
            self.assertEqual(settings.get_noise_zones(),records)
            settings.settings.setValue('tracker/noise_zones','invalid')
            self.assertEqual(settings.get_noise_zones(),[])

    def test_pipeline_rejects_marking_a_stale_target(self):
        pipeline=LivePipeline()
        pipeline.tracker.process([target(0)])
        pipeline.last_frame=time.monotonic()-2
        with self.assertRaises(ValueError):pipeline.mark_noise('Person A')

    def test_only_ignored_noise_remains_after_fall_without_identity_takeover(self):
        def packet(xs):
            chunks=[struct.pack('<HHHH',x,2000,0,360) for x in xs]
            return b'\xaa\xff\x03\x00'+b''.join(chunks)+bytes(8*(3-len(chunks)))+b'\x55\xcc'
        comparison=ModelComparison(autoload=False)
        comparison.started=True
        pipeline=LivePipeline(comparison)
        try:
            with patch('app.ml.model_comparison.time.time',return_value=1000):
                pipeline.ingest(packet([0,2500]),now=1000)
                comparison.feed('Person A',1000,0,2000,0)
                for key in ('xgboost','minirocket','tcn','gru'):comparison._record(key,1000,.99)
            pipeline.mark_noise('Person B',300)
            pipeline.configure(target='Person A',set_target=True)
            # Locking is an explicit context change: establish the candidate on this context.
            with patch('app.ml.model_comparison.time.time',return_value=1000):
                comparison.feed('Person A',1000,0,2000,0)
                for key in ('xgboost','minirocket','tcn','gru'):comparison._record(key,1000,.99)
            for i in range(1,21):
                timestamp=1000+i*.1
                with patch('app.ml.model_comparison.time.time',return_value=timestamp):
                    pipeline.ingest(packet([2500]),now=timestamp)
                    comparison.poll(timestamp)
            status=comparison.get_ensemble_status(1002)
            self.assertTrue(status['fall_alert'])
            self.assertEqual(status['validation']['confirmation_basis'],'post_fall_disappearance')
            self.assertEqual(pipeline.tracker.tracked_persons['Person A'].model_window[-1],(0,2000))
        finally:
            comparison.close()


if __name__=='__main__':unittest.main()
