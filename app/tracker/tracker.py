"""
Target Tracker with Target Focus Lock, Physics Acceleration Gate, Outlier Rejection, and Rolling Averaging.
Includes ghost suppression, target persistence, and post-fall confirmation logic.
"""

from collections import deque
import math
import time
from typing import Dict, List, Tuple, Optional
from ..models.target import Target
from .kalman import KalmanFilter2D
from .noise import NoiseZone, load_zones
import os

# Minimum frames before a target is considered "confirmed" (not a ghost)
MIN_CONFIRM_FRAMES = 2
PROXIMITY_MERGE_THRESHOLD_MM = 1000.0

class TrackedPerson:
    """
    Represents a persistent human entity with physics acceleration validation and rolling averaging.
    """

    def __init__(self, label: str, initial_target: Target, window_size: int = 2, timestamp=None):
        self.label = label
        self.first_seen = time.time() if timestamp is None else timestamp
        self.last_seen = self.first_seen
        self.frames_visible = 1
        self.missed_frames = 0
        self.last_velocity_mms = initial_target.speed

        # Target persistence: not confirmed until seen for MIN_CONFIRM_FRAMES
        self.confirmed = False

        # Temporary search radius expansion (for lock handoff during falls)
        self._expanded_radius_frames = 0

        # Rolling N-packet position window
        self.pos_window: deque[Tuple[float, float]] = deque(maxlen=window_size)
        self.pos_window.append((initial_target.x, initial_target.y))
        self.model_window = deque([(initial_target.x, initial_target.y)], maxlen=10)

        # Kalman Filter instance
        self.kalman = KalmanFilter2D()
        self.kalman.init_state(initial_target.x, initial_target.y)

        self.current_target = initial_target
        self.current_target.id = label

    def set_window_size(self, size: int):
        """Updates rolling window length N."""
        if self.pos_window.maxlen != size:
            new_deque = deque(self.pos_window, maxlen=size)
            self.pos_window = new_deque

    def validate_and_update(self, target: Target, mode: str, max_jump_mm: float, max_speed_mms: float, max_accel_mms2: float = 12000.0, timestamp=None) -> bool:
        """
        Validates whether incoming measurement is physically possible based on displacement and acceleration.
        Returns True if accepted, False if rejected outlier.
        """
        now = time.time() if timestamp is None else timestamp
        dt = max(0.01, now - self.last_seen)

        last_x, last_y = self.pos_window[-1] if self.pos_window else (self.current_target.x, self.current_target.y)
        dist_jump = math.hypot(target.x - last_x, target.y - last_y)
        calc_speed = dist_jump / dt
        calc_accel = abs(calc_speed - self.last_velocity_mms) / dt

        # Physics Validation Checks:
        # Scale allowed jump with dt so re-acquired targets after brief signal gaps are not rejected
        allowed_jump = max(max_jump_mm * 2, max_jump_mm + max_speed_mms * dt)
        is_jump_outlier = (calc_speed > max_speed_mms * 1.5) or (dist_jump > allowed_jump)
        is_accel_outlier = (calc_accel > max_accel_mms2) and (dt < 0.2)

        if "PHYSICAL_GATE" in mode and (is_jump_outlier or is_accel_outlier):
            # Reject multipath / physical noise spike
            return False

        # Measurement Accepted
        self.last_seen = now
        self.frames_visible += 1
        self.missed_frames = 0
        self.last_velocity_mms = calc_speed

        # Mark as confirmed once persistence threshold is met
        if not self.confirmed and self.frames_visible >= MIN_CONFIRM_FRAMES:
            self.confirmed = True

        # Decay expanded radius counter
        if self._expanded_radius_frames > 0:
            self._expanded_radius_frames -= 1

        # Fix "Stationary Lag": Flush historical positions if target reappears after being still/lost
        if dt > 0.4:
            self.pos_window.clear()
            self.model_window.clear()
            self.kalman.init_state(target.x, target.y)

        self.pos_window.append((target.x, target.y))
        self.model_window.append((target.x, target.y))

        if mode == "PHYSICAL_GATE_KALMAN":
            self.kalman.set_dt(dt)
            self.kalman.predict()
            self.kalman.update(target.x, target.y)
            kx, ky = self.kalman.position
            target.x = kx
            target.y = ky
        elif mode in ("PHYSICAL_GATE_AVG", "ROLLING_AVG"):
            # Compute Rolling Centroid Average
            avg_x = sum(p[0] for p in self.pos_window) / len(self.pos_window)
            avg_y = sum(p[1] for p in self.pos_window) / len(self.pos_window)
            target.x = avg_x
            target.y = avg_y

        target.distance = math.hypot(target.x, target.y)
        target.angle = math.degrees(math.atan2(target.x, target.y))
        target.id = self.label
        target.first_seen_time = self.first_seen
        target.last_seen_time = self.last_seen
        target.frames_visible = self.frames_visible
        target.status = "Active"
        target.valid = True
        self.current_target = target
        return True

    @property
    def model_position(self):
        return tuple(sum(p[i] for p in self.model_window)/len(self.model_window) for i in (0,1))

    def predict_missing(self, mode: str, is_locked: bool = False) -> Target:
        """
        Anti-Blink Hold Buffer: Smoothly holds target position active during temporary signal drops.
        """
        self.missed_frames += 1

        # If locked or missing for multiple frames, hold position to prevent runaway Kalman drift
        if is_locked and self.missed_frames > 15:
            self.current_target.status = "Searching"
        elif self.missed_frames > 15:
            self.current_target.status = "Hold"
        else:
            if mode == "PHYSICAL_GATE_KALMAN":
                self.kalman.predict()
                kx, ky = self.kalman.position
                self.current_target.x = kx
                self.current_target.y = ky
            self.current_target.status = "Predicted"

        self.current_target.valid = True
        return self.current_target

class TargetTracker:
    """
    Data Association & Filtering Engine with Target Focus Lock Mode.
    Assumes targets do not cross paths, merges close-proximity detections,
    and maintains long-lived identity persistence across radar dropouts.
    """
    PERSON_NAMES = ["Person A", "Person B", "Person C", "Person D", "Person E"]

    def __init__(self):
        self.mode = "PHYSICAL_GATE_AVG"
        self.window_size = 2
        self.max_speed_mms = 6000.0  # Increased to 6m/s (allows fast movement/running)
        self.max_jump_mm = 1500.0    # Increased base jump allowance
        self.max_accel_mms2 = 80000.0  # 80 m/sÂ² max acceleration threshold
        self.max_missed_frames = 30  # Active prediction hold (~1.5 to 2.0 seconds)
        self.dormant_max_frames = 150 # Dormant memory for Re-ID (~8 to 10 seconds)
        self.proximity_threshold_mm = PROXIMITY_MERGE_THRESHOLD_MM
        self.distance_threshold_mm = 1500.0

        # Focus Lock Target ID (None = Track All, e.g. "Person A" = Lock to Person A)
        self.locked_target_id: Optional[str] = None
        self.tracked_persons: Dict[str, TrackedPerson] = {}
        self._next_name_idx = 0
        self.noise_zones = []
        self.last_eligible_measurements = []
        self.noise_filtered_count = 0

    def reset(self):
        """Clear connection-scoped identities; settings remain applied."""
        self.tracked_persons.clear()
        self.locked_target_id = None
        self._next_name_idx = 0
        self.last_eligible_measurements = []
        self.noise_filtered_count = 0

    def is_noise(self,x,y):
        return any(zone.contains(x,y) for zone in self.noise_zones)

    def set_noise_zones(self,records):
        self.noise_zones=load_zones(records)
        removed=set()
        for label,person in list(self.tracked_persons.items()):
            x,y=person.model_window[-1]
            if self.is_noise(x,y):
                removed.add(label)
                del self.tracked_persons[label]
        if self.locked_target_id in removed:
            self.locked_target_id=None
        return removed

    def mark_noise(self,target_id,radius_mm=300):
        person=self.tracked_persons.get(target_id)
        if person is None or person.current_target.status != 'Active':
            raise ValueError('Select a currently observed target to mark as noise')
        x,y=person.model_window[-1]
        zone=NoiseZone.create(x,y,radius_mm)
        removed=self.set_noise_zones([z.to_dict() for z in self.noise_zones]+[zone.to_dict()])
        return zone,removed

    def set_target_lock(self, target_id: Optional[str]):
        """Sets target focus lock. If set, tracker processes ONLY this target."""
        self.locked_target_id = target_id if target_id and target_id != "Track All Targets" else None

    def apply_tuning_settings(self, settings: dict):
        """Updates live filter settings from UI Tuning Panel."""
        self.mode = settings.get("mode", self.mode)
        self.window_size = settings.get("window_size", self.window_size)
        self.max_speed_mms = float(settings.get("max_speed_mms", self.max_speed_mms))
        self.max_jump_mm = float(settings.get("max_jump_mm", self.max_jump_mm))
        self.max_missed_frames = settings.get("hold_frames", self.max_missed_frames)

        for person in self.tracked_persons.values():
            person.set_window_size(self.window_size)

    def _allocate_label(self) -> str:
        """Recycles labels so Person A is always reused if free."""
        used_labels = {p.label for p in self.tracked_persons.values()}
        for name in self.PERSON_NAMES:
            if name not in used_labels:
                return name
        idx = 1
        while True:
            candidate = f"Person {idx}"
            if candidate not in used_labels:
                return candidate
            idx += 1

    @staticmethod
    def _cluster_raw_targets(raw_targets: List[Target], proximity_mm: float) -> List[Target]:
        """
        Clusters raw radar detections within close proximity (< proximity_mm) into single targets.
        Prevents multiple reflections (e.g. torso + limbs) from spawning multiple separate people.
        """
        if len(raw_targets) <= 1:
            return raw_targets

        n = len(raw_targets)
        parent = list(range(n))

        def find(i: int) -> int:
            if parent[i] == i:
                return i
            parent[i] = find(parent[i])
            return parent[i]

        def union(i: int, j: int):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                parent[root_i] = root_j

        for i in range(n):
            for j in range(i + 1, n):
                dist = math.hypot(raw_targets[i].x - raw_targets[j].x, raw_targets[i].y - raw_targets[j].y)
                if dist <= proximity_mm:
                    union(i, j)

        clusters: Dict[int, List[Target]] = {}
        for i in range(n):
            root = find(i)
            clusters.setdefault(root, []).append(raw_targets[i])

        merged: List[Target] = []
        for group in clusters.values():
            if len(group) == 1:
                merged.append(group[0])
            else:
                total_w = sum(max(1.0, float(t.distance_resolution)) for t in group)
                avg_x = sum(t.x * max(1.0, float(t.distance_resolution)) for t in group) / total_w
                avg_y = sum(t.y * max(1.0, float(t.distance_resolution)) for t in group) / total_w
                avg_speed = sum(t.speed * max(1.0, float(t.distance_resolution)) for t in group) / total_w
                max_res = max(float(t.distance_resolution) for t in group)
                primary = max(group, key=lambda t: float(t.distance_resolution))

                merged_target = Target(
                    id=primary.id,
                    raw_id=primary.raw_id,
                    x=avg_x,
                    y=avg_y,
                    speed=avg_speed,
                    distance_resolution=max_res,
                    valid=True,
                    status=primary.status,
                    first_seen_time=primary.first_seen_time,
                    last_seen_time=time.time(),
                    frames_visible=primary.frames_visible
                )
                merged.append(merged_target)

        return merged

    def process(self, raw_targets: List[Target], timestamp=None) -> List[Target]:
        """
        Processes raw radar targets through Spatial FOV Gate, Proximity Clustering,
        Physical Validation Layer, and Target Focus Lock.
        """
        # Spatial Gate: Y must be > 0 and coordinates finite
        valid_raw = [
            t for t in raw_targets
            if t.valid and t.y > 0 and math.isfinite(t.x) and math.isfinite(t.y)
        ]
        eligible=[t for t in valid_raw if not self.is_noise(t.x,t.y)]
        self.noise_filtered_count += len(valid_raw)-len(eligible)
        self.last_eligible_measurements=eligible
        valid_raw=eligible

        # 1. Proximity Merge: cluster raw detections within close proximity (< proximity_threshold_mm)
        # Prevents multi-reflection / limb returns from being tracked as multiple people
        clustered_raw = valid_raw if self.mode == "RAW" else self._cluster_raw_targets(valid_raw, self.proximity_threshold_mm)

        matched_persons = set()
        matched_raw_indices = set()
        result_targets: List[Target] = []

        # 2. Match active tracked persons with nearest incoming raw target
        # Prioritize locked target first, then active confirmed persons (sorted by freshness)
        active_items = list(self.tracked_persons.items())
        if self.locked_target_id:
            active_items.sort(key=lambda item: 0 if item[0] == self.locked_target_id else (1 + item[1].missed_frames))
        else:
            active_items.sort(key=lambda item: item[1].missed_frames)

        for person_label, person in active_items:
            best_dist = float("inf")
            best_raw_idx = -1
            is_locked = (self.locked_target_id == person_label)

            # Association radius:
            # Under "no two targets crossing path" assumption, allow generous association radius
            if is_locked and person.missed_frames > 50:
                assoc_limit = 6000.0
            elif is_locked and person._expanded_radius_frames > 0:
                assoc_limit = min(4500.0, max(2500.0, person.last_velocity_mms * 2.5))
            elif person.missed_frames > 0:
                # Re-acquisition: expand radius with missed frames (up to 5m)
                assoc_limit = min(5000.0, max(2500.0, 2000.0 + person.missed_frames * 100.0))
            else:
                # Active tracking: allow 1500mm min so sudden steps from standstill don't break track
                assoc_limit = min(3500.0, max(1500.0, person.last_velocity_mms * 1.5))

            curr_target = person.current_target
            for idx, raw in enumerate(clustered_raw):
                if idx in matched_raw_indices:
                    continue
                dist = math.hypot(raw.x - curr_target.x, raw.y - curr_target.y)
                if dist < best_dist and dist < assoc_limit:
                    best_dist = dist
                    best_raw_idx = idx

            if best_raw_idx != -1:
                matched_raw_indices.add(best_raw_idx)
                matched_persons.add(person_label)

                if is_locked and best_dist > 800.0:
                    person._expanded_radius_frames = 10

                accepted = person.validate_and_update(
                    clustered_raw[best_raw_idx],
                    mode=self.mode,
                    max_jump_mm=self.max_jump_mm,
                    max_speed_mms=self.max_speed_mms,
                    max_accel_mms2=self.max_accel_mms2, timestamp=timestamp
                )
                if not accepted:
                    result_targets.append(person.predict_missing(self.mode, is_locked))
                else:
                    result_targets.append(person.current_target)

                # Proximity Absorption: Any remaining raw target within close proximity
                # of this tracked person is part of the same human. Absorb it so no new person is spawned.
                for other_idx, other_raw in enumerate(clustered_raw):
                    if other_idx not in matched_raw_indices:
                        dist_to_p = math.hypot(other_raw.x - person.current_target.x, other_raw.y - person.current_target.y)
                        if dist_to_p <= self.proximity_threshold_mm:
                            matched_raw_indices.add(other_idx)

        # 3. Handle unmatched tracked persons
        for person_label, person in list(self.tracked_persons.items()):
            if person_label not in matched_persons:
                is_locked = (self.locked_target_id == person_label)

                if is_locked:
                    result_targets.append(person.predict_missing(self.mode, is_locked=True))
                elif person.missed_frames < self.max_missed_frames:
                    # Active hold window: display predicted / held target
                    result_targets.append(person.predict_missing(self.mode, is_locked=False))
                elif person.missed_frames < self.dormant_max_frames:
                    # Dormant memory: increment missed frames, hold last state in memory for Re-ID
                    person.predict_missing(self.mode, is_locked=False)
                    person.current_target.status = "Searching"
                else:
                    # Exceeded dormant timeout: safely delete
                    del self.tracked_persons[person_label]

        # 4. Handle remaining unmatched raw targets
        # Under "no two targets crossing path" assumption:
        # Check if an existing dormant/searching person can re-acquire this detection
        for idx, raw in enumerate(clustered_raw):
            if idx in matched_raw_indices:
                continue

            # First: check if within close proximity to ANY currently tracked person
            too_close = False
            for p in self.tracked_persons.values():
                d = math.hypot(raw.x - p.current_target.x, raw.y - p.current_target.y)
                if d <= self.proximity_threshold_mm:
                    too_close = True
                    break
            if too_close:
                matched_raw_indices.add(idx)
                continue

            # Second: Re-acquire dormant/lost person if available
            reacquired_person = None
            best_reacquire_dist = float("inf")
            for person_label, person in self.tracked_persons.items():
                if person_label not in matched_persons and person.missed_frames >= self.max_missed_frames:
                    d = math.hypot(raw.x - person.current_target.x, raw.y - person.current_target.y)
                    if d < 4500.0 and d < best_reacquire_dist:
                        best_reacquire_dist = d
                        reacquired_person = person

            if reacquired_person is not None:
                matched_raw_indices.add(idx)
                matched_persons.add(reacquired_person.label)
                reacquired_person.validate_and_update(
                    raw, self.mode, self.max_jump_mm, self.max_speed_mms, self.max_accel_mms2, timestamp=timestamp
                )
                result_targets.append(reacquired_person.current_target)
                continue

            # Third: If locked target is lost/searching, re-bind to the locked ID
            if (self.locked_target_id and self.locked_target_id in self.tracked_persons
                    and self.tracked_persons[self.locked_target_id].missed_frames > 15):
                label = self.locked_target_id
                locked_p = self.tracked_persons[label]
                locked_p.validate_and_update(
                    raw, self.mode, self.max_jump_mm, self.max_speed_mms, self.max_accel_mms2, timestamp=timestamp
                )
                result_targets.append(locked_p.current_target)
                matched_raw_indices.add(idx)
                continue

            # Reject boundary phantom noise at extreme radar FOV edges
            if abs(raw.x) > 5500 or raw.y > 6500 or raw.y < 150:
                continue

            # Allocate new person with recycled label (prefers Person A)
            label = self._allocate_label()
            new_person = TrackedPerson(label, raw, window_size=self.window_size, timestamp=timestamp)
            new_person.validate_and_update(
                raw, self.mode, self.max_jump_mm, self.max_speed_mms, self.max_accel_mms2, timestamp=timestamp
            )
            self.tracked_persons[label] = new_person
            result_targets.append(new_person.current_target)
            matched_raw_indices.add(idx)

        if self.locked_target_id:
            return [t for t in result_targets if str(t.id) == self.locked_target_id]
        return result_targets
