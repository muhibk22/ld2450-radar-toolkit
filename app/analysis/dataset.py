"""Read-only CSV dataset loading and analysis, independent of Qt and ML models.

X/Y are radar-plane coordinates, never skeletal joints or body height. Each
derivative and label run is computed separately for a session and target.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

LABELS = {
    -1: "Unknown / unlabelled", 1: "Walking", 2: "Standing / idle",
    3: "Sitting down (controlled)", 4: "Kneeling down (controlled)",
    5: "Lying down (controlled)", 6: "Fall onset", 7: "Post-fall stillness",
    8: "Recovery / standing back up",
}
ALIASES = {"arslanazad": "arslan", "arslan azad": "arslan",
           "zoya_dif": "zoya", "zoyaazad": "zoya", "shazia_dif": "shazia"}
MAX_GAP = 0.5
SPEED_REVIEW = 3.5


def default_data_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "raw_sessions"


def person_id(value: str) -> str:
    value = value.strip().lower()
    return ALIASES.get(value, value) or "unknown"


class LoadCancelled(Exception):
    """Loading was cancelled between files."""


@dataclass
class Track:
    target: str
    # Columns: Unix timestamp, lateral X m, forward Y m, signed radar speed m/s,
    # action code, recorded range m (NaN if absent).
    values: np.ndarray
    dt: np.ndarray = field(init=False)
    derived_speed: np.ndarray = field(init=False)

    def __post_init__(self):
        self.values = self.values[np.argsort(self.values[:, 0], kind="stable")]
        self.dt = np.r_[np.nan, np.diff(self.values[:, 0])]
        self.derived_speed = np.full(len(self.values), np.nan)
        good = (self.dt > 0) & (self.dt <= MAX_GAP)
        step = np.r_[np.nan, np.hypot(np.diff(self.values[:, 1]), np.diff(self.values[:, 2]))]
        np.divide(step, self.dt, out=self.derived_speed, where=good)

    @property
    def labels(self):
        return self.values[:, 4].astype(int)

    @property
    def fall_runs(self) -> int:
        fall = self.labels == 6
        adjacent = (self.dt > 0) & (self.dt <= MAX_GAP)
        return int(np.count_nonzero(fall & (~np.r_[False, fall[:-1]] | ~adjacent)))

    def segments(self, column: int, offset: float = 0):
        """Plot arrays with NaNs separating gaps; retains both gap endpoints."""
        times, values = [], []
        for i, row in enumerate(self.values):
            if i and self.dt[i] > MAX_GAP:
                times.append(np.nan)
                values.append(np.nan)
            times.append(float(row[0] - offset))
            values.append(float(row[column]))
        return np.asarray(times), np.asarray(values)


@dataclass
class Session:
    path: Path
    person: str
    subtype: str
    pace: str
    tracks: list[Track]
    excluded: bool = False
    duplicate_rows: int = 0
    bad_rows: int = 0
    invalid_rows: int = 0
    backwards: int = 0
    counts: Counter = field(init=False)
    start: float = field(init=False)
    end: float = field(init=False)
    observed_seconds: float = field(init=False)
    hz: float = field(init=False)
    gaps: int = field(init=False)

    def __post_init__(self):
        times = np.unique(np.concatenate([t.values[:, 0] for t in self.tracks]))
        self.start, self.end = float(times[0]), float(times[-1])
        dt = np.diff(times)
        good = dt[(dt > 0) & (dt <= MAX_GAP)]
        self.observed_seconds = float(good.sum())
        self.hz = float(1 / np.median(good)) if len(good) else 0.0
        self.gaps = int(np.count_nonzero(dt > MAX_GAP))
        self.counts = Counter()
        for track in self.tracks:
            codes, counts = np.unique(track.labels, return_counts=True)
            self.counts.update({int(c): int(n) for c, n in zip(codes, counts)})

    @property
    def rows(self):
        return sum(len(t.values) for t in self.tracks)

    @property
    def duration(self):
        return self.end - self.start

    @property
    def fall_runs(self):
        return sum(t.fall_runs for t in self.tracks)

    @property
    def speed_flags(self):
        return sum(int(np.count_nonzero(t.derived_speed > SPEED_REVIEW)) for t in self.tracks)

    @property
    def range_flags(self):
        return sum(int(np.count_nonzero(np.abs(np.hypot(t.values[:, 1], t.values[:, 2]) - t.values[:, 5]) > .1)) for t in self.tracks)

    def summary(self):
        return dict(source=str(self.path), person=self.person, subtype=self.subtype, pace=self.pace,
                    rows=self.rows, targets=len(self.tracks), elapsed_seconds=self.duration,
                    observed_seconds=self.observed_seconds, median_hz=self.hz,
                    fall_rows=self.counts[6], fall_label_runs=self.fall_runs,
                    training_excluded=self.excluded, gaps_over_05s=self.gaps,
                    coordinate_speed_flags=self.speed_flags, range_residual_flags=self.range_flags,
                    duplicate_rows=self.duplicate_rows, bad_rows=self.bad_rows,
                    invalid_rows=self.invalid_rows, backwards=self.backwards,
                    zero_track_intervals=sum(int(np.count_nonzero(t.dt == 0)) for t in self.tracks))


@dataclass
class Dataset:
    directory: Path
    sessions: list[Session]
    inventory: list[dict]
    issues: list[dict]

    def filtered(self, person=None, activity=None, subtype=None, pace=None, training="all"):
        return [s for s in self.sessions
                if (person is None or s.person == person)
                and (activity is None or s.counts[activity] > 0)
                and (subtype is None or s.subtype == subtype)
                and (pace is None or s.pace == pace)
                and (training == "all" or s.excluded == (training == "excluded"))]


def training_exclusions(directory: Path, selection_files=()) -> set[Path]:
    """Resolve selection entries against their sibling raw_sessions directory."""
    files = set(selection_files)
    files.add(directory / "training_session_selection.csv")
    files.add(directory.parent / "training_session_selection.csv")
    excluded = set()
    for path in sorted(files):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
                if row.get("decision", "").strip().lower() == "exclude" and row.get("file"):
                    excluded.add((path.parent / "raw_sessions" / row["file"]).resolve())
    return excluded


def read_session(path: Path, payload: bytes, excluded=False) -> Session:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    required = {"timestamp", "target_id", "x_mm", "y_mm", "speed_mms", "action_label"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    tracks, seen, volunteers = {}, set(), Counter()
    subtypes, paces = set(), set()
    duplicate = bad = invalid = backwards = 0
    previous = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            bad += 1
            continue
        fingerprint = tuple(row.values())
        if fingerprint in seen:
            duplicate += 1
            continue
        seen.add(fingerprint)
        if row.get("valid", "true").strip().lower() not in {"true", "1"}:
            invalid += 1
            continue
        try:
            t, x, y, speed = [float(row[c]) for c in ("timestamp", "x_mm", "y_mm", "speed_mms")]
            if not all(math.isfinite(v) for v in (t, x, y, speed)):
                raise ValueError("Nonfinite required number")
            if not row["target_id"].strip():
                raise ValueError("Empty target")
        except (TypeError, ValueError):
            bad += 1
            continue
        code = row["action_label"].partition(":")[0].strip()
        label = int(code) if code.isdigit() else -1
        try:
            distance = float(row.get("distance_mm", "")) / 1000
            if not math.isfinite(distance):
                distance = np.nan
        except (TypeError, ValueError):
            distance = np.nan
        target = row["target_id"].strip()
        if target in previous and t < previous[target]:
            backwards += 1
        previous[target] = t
        tracks.setdefault(target, []).append((t, x/1000, y/1000, speed/1000, label, distance))
        volunteer = row.get("volunteer_id", "").strip()
        if volunteer:
            volunteers[volunteer] += 1
        subtypes.add(row.get("fall_subtype", "None").strip() or "None")
        paces.add(row.get("pace_variant", "Unknown").strip() or "Unknown")
    if not tracks:
        raise ValueError(f"No usable observations ({bad} malformed, {invalid} invalid)")
    # Session filenames are the authoritative IDs used by the existing training code.
    prefix, separator, _ = path.stem.rpartition("_session")
    person = prefix if separator else (volunteers.most_common(1)[0][0] if volunteers else path.stem)
    return Session(path.resolve(), person_id(person), ", ".join(sorted(subtypes)), ", ".join(sorted(paces)),
                   [Track(target, np.asarray(values, dtype=float)) for target, values in tracks.items()],
                   excluded, duplicate, bad, invalid, backwards)


def load_dataset(directory: Path, progress: Callable | None = None,
                 cancelled: Callable[[], bool] | None = None) -> Dataset:
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Dataset directory does not exist: {directory}")
    # Prune dependency/build directories when selecting a project or workspace root.
    files, selections = [], []
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "output", "tmp", "archived_data", "dataset_windows"}
    for folder, dirs, names in os.walk(directory):
        if cancelled and cancelled():
            raise LoadCancelled()
        dirs[:] = sorted(d for d in dirs if d not in ignored)
        for name in sorted(names):
            path = Path(folder) / name
            if name == "training_session_selection.csv":
                selections.append(path)
            elif name.lower().endswith(".csv") and name != "dataset_index.csv":
                if re.search(r"_session\d+\.csv$", name, re.IGNORECASE) or Path(folder) == directory:
                    files.append(path)
    exclusions = training_exclusions(directory, selections)
    sessions, inventory, issues, seen = [], [], [], {}
    for i, path in enumerate(files):
        if cancelled and cancelled():
            raise LoadCancelled()
        if progress:
            progress(i, len(files), path.name)
        try:
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            entry = dict(source=str(path), sha256=digest, duplicate_of=seen.get(digest, ""))
            inventory.append(entry)
            if digest in seen:
                continue
            # Failed reads do not shadow a usable copy later in the scan.
            session = read_session(path, payload, path.resolve() in exclusions)
            seen[digest] = str(path)
            sessions.append(session)
        except (OSError, ValueError, csv.Error) as exc:
            issues.append(dict(source=str(path), issue=str(exc)))
    if progress:
        progress(len(files), len(files), "Complete")
    return Dataset(directory, sessions, inventory, issues)


def collection_summary(sessions: list[Session]) -> dict:
    counts = Counter()
    for session in sessions:
        counts.update(session.counts)
    people = sorted({s.person for s in sessions})
    rows = sum(counts.values())
    return dict(sessions=len(sessions), rows=rows, participants=len(people),
                elapsed_hours=sum(s.duration for s in sessions)/3600,
                observed_hours=sum(s.observed_seconds for s in sessions)/3600,
                fall_rows=counts[6], fall_percent=100*counts[6]/rows if rows else 0,
                fall_participants=len({s.person for s in sessions if s.counts[6]}),
                fall_label_runs=sum(s.fall_runs for s in sessions),
                counts=dict(sorted(counts.items())))


def alignment_offset(track: Track, mode: str) -> float | None:
    if mode == "fall":
        indices = np.flatnonzero(track.labels == 6)
        return float(track.values[indices[0], 0]) if len(indices) else None
    return float(track.values[0, 0])


def sample_index(track: Track, timestamp: float) -> int | None:
    """Hold last measured sample; show no position during a recording gap."""
    times = track.values[:, 0]
    i = int(np.searchsorted(times, timestamp, side="right")-1)
    if i < 0 or timestamp > times[-1]:
        return None
    if i+1 < len(times) and times[i+1]-times[i] > MAX_GAP and timestamp > times[i]:
        return None
    return i


def export_summary(dataset: Dataset, sessions: list[Session], destination: Path) -> Path:
    """Export a uniquely named snapshot without overwriting source recordings."""
    output = Path(destination) / ("radar-analysis-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    output.mkdir(parents=True, exist_ok=False)

    def write(name, rows, fields):
        with (output/name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    records = [s.summary() for s in sessions]
    write("sessions.csv", records, list(records[0]) if records else list(Session.__annotations__))
    summary = collection_summary(sessions)
    activities = [dict(code=code, activity=LABELS.get(code, f"Activity {code}"), rows=count,
                       percent_rows=100*count/summary['rows'] if summary['rows'] else 0)
                  for code, count in summary["counts"].items()]
    write("activities.csv", activities, ["code", "activity", "rows", "percent_rows"])
    participants = []
    for person in sorted({s.person for s in sessions}):
        subset = [s for s in sessions if s.person == person]
        participants.append(dict(person=person, sessions=len(subset), rows=sum(s.rows for s in subset),
                                 fall_rows=sum(s.counts[6] for s in subset)))
    write("participants.csv", participants, ["person", "sessions", "rows", "fall_rows"])
    write("source_inventory.csv", dataset.inventory, ["source", "sha256", "duplicate_of"])
    write("load_issues.csv", dataset.issues, ["source", "issue"])
    summary.update(source_directory=str(dataset.directory),
                   scanned_files=len(dataset.inventory), exact_file_copies_excluded=sum(bool(i['duplicate_of']) for i in dataset.inventory),
                   skipped_files=len(dataset.issues),
                   note="Charts and session summaries use the current session filters. Inventory and load issues cover the complete directory scan. Fall label runs are annotation segments, not verified fall events. The stick figure is schematic; X/Y are measured radar-plane positions.",
                   aliases=ALIASES, max_gap_seconds=MAX_GAP, coordinate_speed_review_mps=SPEED_REVIEW)
    (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return output
