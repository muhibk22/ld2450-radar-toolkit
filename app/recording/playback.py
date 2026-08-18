"""
Session Playback Engine for Replaying Recorded Telemetry Logs.
"""

import csv
import json
from pathlib import Path
import time
from typing import List, Dict, Callable
from ..models.target import Target

class PlaybackEngine:
    """
    Parses recorded CSV/JSON files and simulates live target updates.
    """

    def __init__(self):
        self.is_playing = False
        self.current_frame_index = 0
        self.playback_speed = 1.0  # 1x, 2x, 0.5x
        # Grouped frames: list of (timestamp, sequence_id, List[Target])
        self.frames: List[tuple[float, int, List[Target]]] = []
        self._on_frame_callback: Callable[[int, List[Target]], None] | None = None

    def load_file(self, file_path: str | Path) -> bool:
        """Loads and parses a recorded telemetry log."""
        path = Path(file_path)
        if not path.exists():
            return False

        self.frames.clear()
        self.current_frame_index = 0
        self.is_playing = False

        if path.suffix.lower() == ".csv":
            self._load_csv(path)
        elif path.suffix.lower() == ".json":
            self._load_json(path)
        return len(self.frames) > 0

    def _load_csv(self, path: Path):
        grouped: Dict[int, tuple[float, List[Target]]] = {}
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seq_id = int(row.get("sequence_id", 0))
                ts = float(row.get("timestamp", 0.0))
                target = Target(
                    id=row.get("target_id", "Target"),
                    raw_id=0,
                    x=float(row.get("x_mm", 0.0)),
                    y=float(row.get("y_mm", 0.0)),
                    speed=float(row.get("speed_mms", 0.0)),
                    distance=float(row.get("distance_mm", 0.0)),
                    angle=float(row.get("angle_deg", 0.0)),
                    valid=row.get("valid", "True").lower() == "true",
                    status=row.get("status", "Active")
                )
                if seq_id not in grouped:
                    grouped[seq_id] = (ts, [])
                grouped[seq_id][1].append(target)

        for seq_id in sorted(grouped.keys()):
            ts, targets = grouped[seq_id]
            self.frames.append((ts, seq_id, targets))

    def _load_json(self, path: Path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        grouped: Dict[int, tuple[float, List[Target]]] = {}
        for entry in data:
            seq_id = entry.get("sequence_id", 0)
            ts = entry.get("timestamp", 0.0)
            tdata = entry.get("target", {})
            target = Target(
                id=tdata.get("id", "Target"),
                raw_id=tdata.get("raw_id", 0),
                x=tdata.get("x", 0.0),
                y=tdata.get("y", 0.0),
                speed=tdata.get("speed", 0.0),
                distance=tdata.get("distance", 0.0),
                angle=tdata.get("angle", 0.0),
                valid=tdata.get("valid", True),
                status=tdata.get("status", "Active")
            )
            if seq_id not in grouped:
                grouped[seq_id] = (ts, [])
            grouped[seq_id][1].append(target)

        for seq_id in sorted(grouped.keys()):
            ts, targets = grouped[seq_id]
            self.frames.append((ts, seq_id, targets))

    @property
    def total_frames(self) -> int:
        return len(self.frames)

    def step_next(self) -> tuple[int, List[Target]] | None:
        """Advances playback by one frame."""
        if self.current_frame_index >= len(self.frames):
            self.is_playing = False
            return None

        _, seq_id, targets = self.frames[self.current_frame_index]
        self.current_frame_index += 1
        return seq_id, targets

    def seek_frame(self, index: int):
        """Seeks to a specific frame index."""
        self.current_frame_index = min(max(0, index), len(self.frames) - 1)
