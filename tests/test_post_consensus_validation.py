"""Behavioral edge cases; synthetic traces are not independent accuracy estimates."""
import unittest
import math
from app.ml.ensemble_validation import PostConsensusValidator, ValidationConfig


class PostConsensusValidationTests(unittest.TestCase):
    def trace(self,motion,seconds=5):
        validator=PostConsensusValidator(1000)
        for i in range(-15,round(seconds*10)+1):
            validator.observe(1000+i/10,*motion(i/10))
        return validator

    def test_landing_then_stillness_confirms_with_fresh_evidence(self):
        validator=self.trace(lambda t:(min(t,1)*1000,2000,800 if t<.8 else 0))
        self.assertEqual(validator.state,'confirmed')
        self.assertGreaterEqual(validator.confirmed_at,1003.5)
        self.assertLessEqual(validator.confirmed_at,1005)

    def test_reversal_with_continued_travel_is_rejected_early(self):
        validator=self.trace(lambda t:(1200*t if t<0 else -1200*t,2000,1200))
        self.assertEqual(validator.state,'rejected')
        self.assertLessEqual(validator.resolved_at-1000,1.25)
        self.assertGreaterEqual(validator.reversal['coverage'],.8)

    def test_negative_radial_speed_alone_cannot_reject(self):
        validator=self.trace(lambda t:(0,2000,-1200))
        self.assertEqual(validator.state,'confirmed')
        self.assertEqual(validator.confirmation_basis,'stable_centroid')

    def test_healthy_reported_disappearance_can_confirm_after_consensus(self):
        validator=PostConsensusValidator(1000)
        validator.observe(1000,0,2000,1200)
        for i in range(1,18):validator.observe(1000+i/10,fresh=False,target_absent=True)
        self.assertEqual(validator.state,'confirmed')
        self.assertEqual(validator.confirmation_basis,'post_fall_disappearance')

    def test_report_outage_during_disappearance_cannot_confirm(self):
        validator=PostConsensusValidator(1000)
        validator.observe(1000,0,2000,0)
        validator.observe(1000.1,fresh=False,target_absent=True)
        validator.observe(1000.2,fresh=False,target_absent=True)
        validator.check_freshness(1001)
        self.assertEqual(validator.state,'suspected')
        self.assertIsNone(validator.confirmed_at)

    def test_resuming_reports_after_gap_cannot_fake_continuous_absence(self):
        validator=PostConsensusValidator(1000)
        validator.observe(1000,0,2000,0)
        validator.observe(1000.1,fresh=False,target_absent=True)
        validator.observe(1001,fresh=False,target_absent=True)
        self.assertEqual(validator.state,'suspected')

    def test_continued_straight_running_is_not_a_reversal(self):
        validator=self.trace(lambda t:(1200*t,2000,1200))
        self.assertEqual(validator.state,'suspected')

    def test_tangential_reversal_uses_position_even_when_radial_is_zero(self):
        validator=self.trace(lambda t:(1500*t if t<0 else -1500*t,2000,0))
        self.assertEqual(validator.state,'rejected')

    def test_tiny_heading_reversal_does_not_reject(self):
        validator=self.trace(lambda t:(1000*t if t<0 else -15*t,2000,0))
        self.assertEqual(validator.state,'confirmed')

    def test_late_recovery_reversal_does_not_reject_a_fall(self):
        validator=self.trace(lambda t:(1000*t if t<0 else 0 if t<3 else -1000*(t-3),2000,0))
        self.assertNotEqual(validator.state,'rejected')

    def test_unsettled_motion_keeps_suspected_warning(self):
        validator=self.trace(lambda t:(400*t,2000,0))
        self.assertEqual(validator.state,'suspected')
        self.assertEqual(validator.warning_kind,'low_motion_unverified')

    def test_one_noisy_position_does_not_reject(self):
        validator=self.trace(lambda t:(1000 if t==1.7 else 0,2000,1200 if t==1.7 else 0))
        self.assertEqual(validator.state,'confirmed')

    def test_periodic_motion_does_not_cancel_to_false_stillness(self):
        validator=self.trace(lambda t:(100*math.sin(4*math.pi*t),2000,0))
        self.assertEqual(validator.state,'suspected')
        self.assertGreater(validator.max_planar,250)

    def test_missing_frames_keep_warning_and_never_confirm_stillness(self):
        validator=self.trace(lambda t:(0,2000,0),seconds=2)
        validator.observe(1002.1,fresh=False)
        validator.check_freshness(1002.6)
        self.assertEqual(validator.state,'suspected')
        self.assertEqual(validator.warning_kind,'tracking_lost')
        validator.observe(1010,0,2000,0)
        self.assertIsNone(validator.confirmed_at)

    def test_missing_sample_cannot_supply_continuous_reversal_evidence(self):
        validator=PostConsensusValidator(1000)
        for i in range(-15,14):
            t=i/10
            if i==5:
                validator.observe(1000+t,fresh=False)
            else:
                validator.observe(1000+t,1200*t if t<0 else -1200*t,2000,0)
        self.assertEqual(validator.state,'validating')

    def test_wall_clock_alone_keeps_suspected_warning(self):
        validator=PostConsensusValidator(1000)
        validator.check_freshness(1005)
        self.assertEqual(validator.state,'suspected')

    def test_duplicate_samples_cannot_advance_evidence(self):
        validator=PostConsensusValidator(1000)
        for _ in range(500):validator.observe(1000,0,2000,0)
        self.assertEqual(validator.state,'validating')
        self.assertEqual(validator.snapshot()['still_seconds'],0)

    def test_rejection_does_not_turn_into_a_fall_when_runner_stops(self):
        validator=self.trace(lambda t:(1200*t if t<0 else -1200*t,2000,0),seconds=2)
        for i in range(21,101):validator.observe(1000+i/10,-2400,2000,0)
        self.assertEqual(validator.state,'rejected')

    def test_invalid_motion_retains_uncertainty(self):
        validator=PostConsensusValidator(1000)
        validator.observe(1000,float('nan'),2000,0)
        self.assertEqual(validator.state,'suspected')

    def test_configuration_must_allow_enough_stillness(self):
        with self.assertRaises(ValueError):ValidationConfig(observation_seconds=2)


if __name__=='__main__':unittest.main()
