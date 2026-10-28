"""
Unit Test Suite for LD2450 Target Focus Lock, Acceleration Gate, and Axis Orientation.
"""

import unittest
from app.models.target import Target
from app.tracker.tracker import TargetTracker
from app.parser.packet_decoder import PacketDecoder

class TestTargetFocusLockAndPhysicsValidations(unittest.TestCase):

    def test_target_focus_lock_filtering(self):
        tracker = TargetTracker()

        # 1. Process 2 valid raw targets (Person A and Person B)
        t_a = Target(id="raw0", raw_id=0, x=500.0, y=1500.0, speed=0.0, valid=True, distance_resolution=100.0)
        t_b = Target(id="raw1", raw_id=1, x=-1200.0, y=2500.0, speed=0.0, valid=True, distance_resolution=100.0)

        results_unlocked = tracker.process([t_a, t_b])
        self.assertEqual(len(results_unlocked), 2)
        person_ids = [t.id for t in results_unlocked]
        self.assertIn("Person A", person_ids)
        self.assertIn("Person B", person_ids)

        # 2. Lock Focus onto Person A
        tracker.set_target_lock("Person A")
        results_locked = tracker.process([t_a, t_b])

        # MUST return ONLY Person A and ignore Person B!
        self.assertEqual(len(results_locked), 1)
        self.assertEqual(results_locked[0].id, "Person A")

    def test_physics_acceleration_gate_rejection(self):
        tracker = TargetTracker()
        tracker.apply_tuning_settings({
            "mode": "PHYSICAL_GATE_AVG",
            "window_size": 10,
            "max_speed_mms": 4000.0,
            "max_jump_mm": 500.0,
            "hold_frames": 10
        })

        t0 = Target(id="raw0", raw_id=0, x=500.0, y=1500.0, speed=0.0, valid=True, distance_resolution=100.0)
        tracker.process([t0])

        # Sudden impossible 15000 mm/s² acceleration spike in next frame
        t_spike = Target(id="raw0", raw_id=0, x=2500.0, y=1500.0, speed=0.0, valid=True, distance_resolution=100.0)
        res = tracker.process([t_spike])

        # MUST REJECT acceleration spike! Person A's position should not jump to the spike.
        person_a_results = [t for t in res if t.id == "Person A"]
        self.assertEqual(len(person_a_results), 1)
        self.assertLess(person_a_results[0].x, 1500.0)

    def test_axis_orientation_decoding(self):
        decoder = PacketDecoder()

        # Test positive X (+X Right) and negative X (-X Left)
        val_pos = decoder._decode_ld2450_int16(0x0078)  # +120 mm
        val_neg = decoder._decode_ld2450_int16(0x8078)  # -120 mm

        self.assertEqual(val_pos, 120.0)
        self.assertEqual(val_neg, -120.0)

    def test_proximity_clustering_merges_close_targets(self):
        tracker = TargetTracker()
        # Two raw detections 250mm apart (e.g. torso and arm/reflection)
        t_arm = Target(id="raw0", raw_id=0, x=500.0, y=1500.0, speed=0.0, valid=True, distance_resolution=100.0)
        t_torso = Target(id="raw1", raw_id=1, x=650.0, y=1600.0, speed=0.0, valid=True, distance_resolution=100.0)

        results = tracker.process([t_arm, t_torso])
        # MUST merge into a single entity (Person A) and NOT spawn Person B!
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "Person A")

    def test_track_persistence_across_dropouts(self):
        tracker = TargetTracker()
        t0 = Target(id="raw0", raw_id=0, x=500.0, y=1500.0, speed=0.0, valid=True, distance_resolution=100.0)

        # Initial track
        res1 = tracker.process([t0])
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0].id, "Person A")

        # Simulate sensor dropout for 20 frames (empty target list)
        for _ in range(20):
            tracker.process([])

        # Reappearance nearby
        t_reappear = Target(id="raw0", raw_id=0, x=700.0, y=1700.0, speed=0.0, valid=True, distance_resolution=100.0)
        res2 = tracker.process([t_reappear])

        # Must retain Person A and not cycle to Person B!
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0].id, "Person A")

if __name__ == "__main__":
    unittest.main()
