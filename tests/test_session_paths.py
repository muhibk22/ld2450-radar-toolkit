"""Archiving must not recycle session names that training selections reference."""
from pathlib import Path
import tempfile
import unittest

from app.recording.session_paths import next_session_path
from app.analysis.dataset import load_dataset
from tests.test_dataset_analysis import row, write


class SessionPathTests(unittest.TestCase):
    def test_highest_identifier_across_active_and_archived_recordings(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            raw = project/"data/raw_sessions"
            raw.mkdir(parents=True)
            (raw/"arslan_session05.csv").touch()
            (raw/"arslan_session14.csv").touch()
            archive = project/"archived_data/old/raw_sessions"
            archive.mkdir(parents=True)
            (archive/"arslan_session39.csv").touch()
            (archive/"other_session999.csv").touch()
            self.assertEqual(next_session_path(raw, "arslan").name, "arslan_session40.csv")
            self.assertEqual(next_session_path(raw, "new").name, "new_session01.csv")

    def test_project_scan_skips_archive_but_explicit_archive_review_works(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            write(project/"data/raw_sessions/a_session01.csv", [row(0), row(.1)])
            archive = project/"archived_data/old/raw_sessions"
            write(archive/"b_session01.csv", [row(1, label=5), row(1.1, label=5)])
            slices = project/"data/dataset_windows"
            slices.mkdir()
            (slices/"a_session01_win0_class1.csv").write_text("x_mm,y_mm\n0,1000\n")
            backup = project/"metadata"
            backup.mkdir()
            (backup/"training_session_selection.before.csv").write_text("file,decision\n")
            dataset = load_dataset(project)
            self.assertEqual(len(dataset.sessions), 1)
            self.assertEqual(dataset.issues, [])
            self.assertEqual(len(load_dataset(archive).sessions), 1)


if __name__ == "__main__":
    unittest.main()
