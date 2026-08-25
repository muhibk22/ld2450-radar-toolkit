"""
Session Telemetry Data Recorder (CSV & JSON).
"""

import csv
import json
from pathlib import Path
import time
from typing import List
from ..models.target import Target

class DataRecorder:
    """
    Logs live target positions and metrics into CSV or JSON format.
    """

    def __init__(self):
        self.is_recording = False
        self.file_path: Path | None = None
        self._file_handle = None
        self._csv_writer = None
        self._json_frames: List[dict] = []
        self.record_count = 0
        self.format = "csv"  # 'csv' or 'json'
        
        # ML Dataset features
        self.session_metadata = {}
        self.current_action_label = "2: Standing / idle"

    def set_action_label(self, label: str):
        self.current_action_label = label

    def start_recording(self, file_path: str | Path, format_type: str = "csv", metadata: dict = None) -> bool:
        """Starts recording session."""
        self.stop_recording()
        self.file_path = Path(file_path)
        self.format = format_type.lower()
        self.record_count = 0
        self._json_frames.clear()
        
        self.session_metadata = metadata or {
            "volunteer_id": "Unknown",
            "fall_subtype": "None",
            "pace_variant": "Normal"
        }

        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if self.format == "csv":
                self._file_handle = open(self.file_path, mode="w", newline="", encoding="utf-8")
                self._csv_writer = csv.writer(self._file_handle)
                # Write header
                self._csv_writer.writerow([
                    "timestamp", "sequence_id", "target_id", "x_mm", "y_mm",
                    "speed_mms", "distance_mm", "angle_deg", "valid", "status",
                    "volunteer_id", "fall_subtype", "pace_variant", "action_label"
                ])
                self._file_handle.flush()
            self.is_recording = True
            return True
        except Exception as e:
            self.is_recording = False
            raise RuntimeError(f"Could not open recording file: {e}") from e

    def record_frame(self, sequence_id: int, targets: List[Target]):
        """Logs a frame's target set to file."""
        if not self.is_recording:
            return

        now = time.time()
        for t in targets:
            if not t.valid:
                continue

            self.record_count += 1
            if self.format == "csv" and self._csv_writer:
                self._csv_writer.writerow([
                    now, sequence_id, t.id, round(t.x, 2), round(t.y, 2),
                    round(t.speed, 2), round(t.distance, 2), round(t.angle, 2),
                    t.valid, t.status,
                    self.session_metadata.get("volunteer_id", ""),
                    self.session_metadata.get("fall_subtype", ""),
                    self.session_metadata.get("pace_variant", ""),
                    self.current_action_label
                ])
            elif self.format == "json":
                self._json_frames.append({
                    "timestamp": now,
                    "sequence_id": sequence_id,
                    "target": t.to_dict()
                })

        if self.format == "csv" and self._file_handle:
            self._file_handle.flush()

    def stop_recording(self):
        """Stops recording and logs dataset metadata to index."""
        if not self.is_recording:
            return

        self.is_recording = False
        
        if self.format == "csv" and self._file_handle:
            self._file_handle.close()
            self._file_handle = None
            
            # Write to global dataset index
            if hasattr(self, 'session_metadata') and self.file_path:
                index_path = self.file_path.parent / "dataset_index.csv"
                file_exists = index_path.exists()
                try:
                    with open(index_path, mode="a", newline="", encoding="utf-8") as idx_file:
                        idx_writer = csv.writer(idx_file)
                        if not file_exists:
                            idx_writer.writerow(["session_file", "volunteer_id", "fall_subtype", "pace_variant", "timestamp"])
                        idx_writer.writerow([
                            self.file_path.name,
                            self.session_metadata.get("volunteer_id", ""),
                            self.session_metadata.get("fall_subtype", ""),
                            self.session_metadata.get("pace_variant", ""),
                            time.strftime("%Y-%m-%d %H:%M:%S")
                        ])
                except Exception as e:
                    print(f"Failed to write to dataset index: {e}")

        elif self.format == "json" and self.file_path:
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump(self._json_frames, f, indent=2)
            except Exception as e:
                print(f"Failed to save JSON recording: {e}")
