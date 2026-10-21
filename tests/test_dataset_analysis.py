"""Dataset semantics: duplicates, track isolation, gaps, labels and exports."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.analysis.dataset import (
    LoadCancelled, alignment_offset, collection_summary, export_summary,
    load_dataset, read_session, sample_index,
)

FIELDS = ["timestamp", "target_id", "x_mm", "y_mm", "speed_mms", "distance_mm",
          "valid", "volunteer_id", "fall_subtype", "pace_variant", "action_label"]


def row(t, target="A", x=0, label=1, **extras):
    value = dict(timestamp=t, target_id=target, x_mm=x, y_mm=1000,
                 speed_mms=-240, distance_mm=1000, valid=True, volunteer_id="person",
                 fall_subtype="Forward", pace_variant="Normal", action_label=f"{label}: test")
    value.update(extras)
    return value


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class DatasetAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_copies_excluded_and_filename_collisions_retained(self):
        first = self.root/"one/arslanazad_session01.csv"
        write(first, [row(0), row(.1)])
        copy = self.root/"two/copy_session01.csv"
        copy.parent.mkdir()
        copy.write_bytes(first.read_bytes())
        write(self.root/"two/arslanazad_session01.csv", [row(2), row(2.1)])
        dataset = load_dataset(self.root)
        self.assertEqual(len(dataset.sessions), 2)
        self.assertEqual({s.person for s in dataset.sessions}, {"arslan"})
        self.assertEqual(sum(bool(i["duplicate_of"]) for i in dataset.inventory), 1)
        self.assertEqual(collection_summary(dataset.sessions)["rows"], 4)

    def test_derivatives_and_fall_runs_are_isolated_by_track(self):
        path = self.root/"p_session01.csv"
        write(path, [row(0, "A", 0, 6), row(0, "B", 9000, 1),
                     row(.1, "A", 100, 6), row(.1, "B", 9100, 1),
                     row(1, "A", 2000, 6), row(1.1, "A", 2100, 2)])
        session = load_dataset(self.root).sessions[0]
        a, b = session.tracks
        self.assertAlmostEqual(a.derived_speed[1], 1)
        self.assertAlmostEqual(b.derived_speed[1], 1)
        self.assertTrue(np.isnan(a.derived_speed[2]))
        self.assertEqual(session.gaps, 1)
        self.assertEqual(session.fall_runs, 2)
        self.assertIsNone(sample_index(a, .5))
        self.assertEqual(sample_index(a, .1), 1)
        self.assertEqual(sample_index(a, 1), 2)
        self.assertIsNone(sample_index(a, 2))
        x, y = a.segments(1)
        self.assertEqual(np.isnan(x).sum(), 1)
        self.assertEqual(np.isnan(y).sum(), 1)
        self.assertEqual(len(x), len(a.values)+1)
        self.assertAlmostEqual(session.observed_seconds, .2)

    def test_bad_rows_copies_duplicates_unknown_labels_and_sorting(self):
        path = self.root/"sample.csv"
        rows = [row(.2), row(.1), row(.1), row(.3, valid=False),
                row(.4, x_mm="NaN"), row(.5, action_label="unlabelled")]
        write(path, rows)
        session = read_session(path, path.read_bytes())
        self.assertEqual(session.rows, 3)
        self.assertEqual(session.duplicate_rows, 1)
        self.assertEqual(session.bad_rows, 1)
        self.assertEqual(session.invalid_rows, 1)
        self.assertEqual(session.backwards, 1)
        self.assertEqual(session.counts[-1], 1)
        self.assertEqual(session.tracks[0].values[0, 0], .1)
        self.assertIsNone(alignment_offset(session.tracks[0], "fall"))

    def test_training_selection_and_filters_resolve_actual_source_path(self):
        raw = self.root/"data/raw_sessions"
        write(raw/"zoyaazad_session01.csv", [row(0, label=6), row(.1, label=6)])
        write(raw/"zoya_session02.csv", [row(1, label=5), row(1.1, label=5)])
        (raw.parent/"training_session_selection.csv").write_text(
            "# collection audit\nfile,decision\nzoya_session02.csv,exclude\n", encoding="utf-8")
        dataset = load_dataset(raw)
        self.assertEqual(len(dataset.filtered(person="zoya")), 2)
        self.assertEqual(len(dataset.filtered(activity=6, training="eligible")), 1)
        self.assertEqual(len(dataset.filtered(training="excluded")), 1)
        self.assertEqual(len(dataset.filtered(activity=6, training="excluded")), 0)
        self.assertEqual(alignment_offset(dataset.filtered(activity=6)[0].tracks[0], "fall"), 0)

    def test_skipped_schemas_cancellation_empty_folder_and_exports(self):
        self.assertFalse(load_dataset(self.root).sessions)
        write(self.root/"p_session01.csv", [row(0), row(.1)])
        (self.root/"bad_session01.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
        (self.root/"dataset_index.csv").write_text("metadata", encoding="utf-8")
        before = (self.root/"p_session01.csv").read_bytes()
        dataset = load_dataset(self.root)
        self.assertEqual(len(dataset.issues), 1)
        with self.assertRaises(LoadCancelled):
            load_dataset(self.root, cancelled=lambda: True)
        output = export_summary(dataset, dataset.sessions, self.root/"exports")
        output2 = export_summary(dataset, dataset.sessions, self.root/"exports")
        self.assertNotEqual(output, output2)
        summary = json.loads((output/"summary.json").read_text())
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["skipped_files"], 1)
        self.assertEqual((self.root/"p_session01.csv").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
