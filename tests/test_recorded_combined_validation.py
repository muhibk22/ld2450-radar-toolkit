"""User-labelled event regression. Activity labels are deliberately unused."""
from pathlib import Path
import unittest
from tools.verify_combined_validation import load, logged_flag_replay

ROOT=Path(__file__).resolve().parents[1]
SESSION=ROOT/'data/raw_sessions/active_session_session01.csv'
FLAGS=ROOT/'fall_model_detections2.csv'


@unittest.skipUnless(SESSION.exists() and FLAGS.exists(),'Local recorded-session fixtures are unavailable')
class RecordedCombinedValidationTests(unittest.TestCase):
    def test_four_real_candidates_retained_and_running_reversal_rejected(self):
        result=logged_flag_replay(load(SESSION),load(FLAGS))
        for event in ('1','2','3','5'):
            self.assertEqual(result['outcomes'][event]['validation']['state'],'confirmed')
        false_positive=result['outcomes']['6']['validation']
        self.assertEqual(false_positive['state'],'rejected')
        self.assertLessEqual(false_positive['resolved_at']-false_positive['started_at'],1.25)
        self.assertTrue(result['reset_kept_warnings'])
        self.assertTrue(result['acknowledgement_cleared_warnings'])


if __name__=='__main__':unittest.main()
