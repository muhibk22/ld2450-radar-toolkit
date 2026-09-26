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
from ..ml.fall_detector import FallDetector
from ..ml.post_fall_validator import PostFallValidator
import os

# Minimum frames before a target is considered "confirmed" (not a ghost)
MIN_CONFIRM_FRAMES = 3

class TrackedPerson:
    """
    Represents a persistent human entity with physics acceleration validation and rolling averaging.
    """

    def __init__(self, label: str, initial_target: Target, window_size: int = 10):
        self.label = label
        self.first_seen = time.time()
        self.last_seen = time.time()
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

    def validate_and_update(self, target: Target, mode: str, max_jump_mm: float, max_speed_mms: float, max_accel_mms2: float = 12000.0) -> bool:
        """
        Validates whether incoming measurement is physically possible based on displacement and acceleration.
        Returns True if accepted, False if rejected outlier.
        """
        now = time.time()
        dt = max(0.01, now - self.last_seen)

        last_x, last_y = self.pos_window[-1] if self.pos_window else (self.current_target.x, self.current_target.y)
        dist_jump = math.hypot(target.x - last_x, target.y - last_y)
        calc_speed = dist_jump / dt
        calc_accel = abs(calc_speed - self.last_velocity_mms) / dt

        # 1. Physics Validation Checks (Displacement, Speed, and Acceleration limits)
        # We rely on calc_speed rather than absolute dist_jump so that targets lost for 
        # several seconds are allowed to travel further distances without being rejected.
        is_jump_outlier = (calc_speed > max_speed_mms) or (dist_jump > max_jump_mm * 2)
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
        if dt > 0.5:
            self.pos_window.clear()

        self.pos_window.append((target.x, target.y))

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

        target.id = self.label
        target.first_seen_time = self.first_seen
        target.last_seen_time = self.last_seen
        target.frames_visible = self.frames_visible
        target.status = "Active"
        target.valid = True
        self.current_target = target
        return True

    def predict_missing(self, mode: str, is_locked: bool = False) -> Target:
        """
        Anti-Blink Hold Buffer: Smoothly holds target position active during temporary signal drops.
        """
        self.missed_frames += 1
        
        # FOCUS LOCK ENHANCEMENT & RE-ID: 
        # If locked and lost for a while, enter "Searching" mode to prevent drift but keep alive
        if is_locked and self.missed_frames > 15:
            self.current_target.status = "Searching"
            # Do NOT update x/y with Kalman. Hold last known valid position.
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
    """
    PERSON_NAMES = ["Person A", "Person B", "Person C", "Person D", "Person E"]

    def __init__(self):
        self.mode = "PHYSICAL_GATE_AVG"
        self.window_size = 10
        self.max_speed_mms = 6000.0  # Increased to 6m/s (allows fast movement/running)
        self.max_jump_mm = 1500.0    # Increased base jump allowance
        self.max_accel_mms2 = 80000.0  # 80 m/s² max acceleration threshold
        self.max_missed_frames = 15
        self.distance_threshold_mm = 1200.0

        # Focus Lock Target ID (None = Track All, e.g. "Person A" = Lock to Person A)
        self.locked_target_id: Optional[str] = None

        self.tracked_persons: Dict[str, TrackedPerson] = {}
        self._next_name_idx = 0
        
        # Initialize Fall Detection AI (using relative path to weights directory)
        model_dir = os.path.join(os.path.dirname(__file__), "..", "ml", "weights")
        try:
            self.fall_detector = FallDetector(model_dir=model_dir)
            self._last_locked_target = None
            self._fall_consecutive_count = 0
            self._fall_latch_frames = 0
        except Exception as e:
            print(f"Warning: FallDetector failed to load: {e}")
            self.fall_detector = None
            self._last_locked_target = None
            self._fall_consecutive_count = 0
            self._fall_latch_frames = 0
        
        # Post-fall confirmation state machine (Phase 3)
        self.post_fall_validator = PostFallValidator()

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
        if self._next_name_idx < len(self.PERSON_NAMES):
            name = self.PERSON_NAMES[self._next_name_idx]
            self._next_name_idx += 1
            return name
        name = f"Person {self._next_name_idx + 1}"
        self._next_name_idx += 1
        return name

    def process(self, raw_targets: List[Target]) -> List[Target]:
        """
        Processes raw radar targets through Spatial FOV Gate, Physical Validation Layer, and Target Focus Lock.
        """
        # Spatial Gate: Y must be > 0 (Depth ahead in front of radar)
        valid_raw = [t for t in raw_targets if t.valid and t.y > 0]
        matched_persons = set()
        matched_raw_indices = set()
        result_targets: List[Target] = []

        # If RAW mode, bypass filtering
        if self.mode == "RAW":
            if self.locked_target_id:
                return [t for t in valid_raw if str(t.id) == self.locked_target_id]
            return valid_raw

        # 1. Match active tracked persons with nearest incoming raw target
        # Priority Association: Process Locked Target first so it doesn't lose its point to a crossing target
        active_persons = list(self.tracked_persons.items())
        if self.locked_target_id:
            active_persons.sort(key=lambda item: 0 if item[0] == self.locked_target_id else 1)

        for person_label, person in active_persons:
            best_dist = float("inf")
            best_raw_idx = -1
            
            is_locked = (self.locked_target_id == person_label)

            # DYNAMIC ASSOCIATION RADIUS & RE-ID
            if is_locked and person.missed_frames > 50:
                # RE-ID MODE: Expand radius to 6000mm to snap back to the person if they re-enter
                assoc_limit = 6000.0
            elif is_locked and person._expanded_radius_frames > 0:
                # GRACEFUL LOCK HANDOFF: Temporarily expanded radius during rapid motion (e.g., falls)
                # This prevents the locked target from being lost during a genuine fall
                assoc_limit = min(4500.0, max(2000.0, person.last_velocity_mms * 2.5))
            else:
                # Activity-Aware Radius: 600mm min (stationary) up to 3000mm (moving fast)
                assoc_limit = min(3000.0, max(600.0, person.last_velocity_mms * 1.5))

            curr_target = person.current_target
            for idx, raw in enumerate(valid_raw):
                if idx in matched_raw_indices:
                    continue
                dist = math.hypot(raw.x - curr_target.x, raw.y - curr_target.y)
                if dist < best_dist and dist < assoc_limit:
                    best_dist = dist
                    best_raw_idx = idx

            if best_raw_idx != -1:
                matched_raw_indices.add(best_raw_idx)
                matched_persons.add(person_label)
                
                # If this is a large displacement for the locked target, activate expanded radius
                # so the next frame also has a wider search (graceful handoff during falls)
                if is_locked and best_dist > 800.0:
                    person._expanded_radius_frames = 10  # Keep expanded for ~1 second
                
                accepted = person.validate_and_update(
                    valid_raw[best_raw_idx],
                    mode=self.mode,
                    max_jump_mm=self.max_jump_mm,
                    max_speed_mms=self.max_speed_mms,
                    max_accel_mms2=self.max_accel_mms2
                )
                if not accepted:
                    result_targets.append(person.predict_missing(self.mode, is_locked))
                else:
                    result_targets.append(person.current_target)

        # 2. Handle unmatched active tracked persons (Anti-Blink Hold Buffer)
        for person_label, person in list(self.tracked_persons.items()):
            if person_label not in matched_persons:
                is_locked = (self.locked_target_id == person_label)
                
                # GHOST REJECTION: Unconfirmed targets (< MIN_CONFIRM_FRAMES visible) expire after 2 missed frames
                # This prevents transient 1-2 frame ghost points from polluting tracking
                # FOCUS LOCK ENHANCEMENT: Never expire the actively locked target
                if is_locked:
                    max_hold = float('inf')
                elif not person.confirmed:
                    max_hold = 2  # Transient ghost: expire quickly
                else:
                    max_hold = self.max_missed_frames

                if person.missed_frames < max_hold:
                    result_targets.append(person.predict_missing(self.mode, is_locked))
                else:
                    del self.tracked_persons[person_label]

        # 3. Create new TrackedPerson for unmatched raw targets (with Ghost Rejection)
        for idx, raw in enumerate(valid_raw):
            if idx not in matched_raw_indices:
                # PROXIMITY GHOST REJECTION (enhanced)
                is_ghost = False
                if self.locked_target_id and self.locked_target_id in self.tracked_persons:
                    locked_person = self.tracked_persons[self.locked_target_id]
                    # If locked target is actively tracked (not lost)
                    if locked_person.missed_frames < 15:
                        dist_to_locked = math.hypot(raw.x - locked_person.current_target.x, raw.y - locked_person.current_target.y)
                        if dist_to_locked < 1000.0:
                            is_ghost = True # Target spawned too close to locked person, likely a multipath ghost
                
                # Additional ghost check: reject points that appear at extreme sensor boundaries
                # (LD2450 commonly generates phantom returns at FOV edges)
                if abs(raw.x) > 5500 or raw.y > 5500 or raw.y < 100:
                    is_ghost = True
                
                if not is_ghost:
                    # RE-ID: If Locked target is currently "Lost", assign this new target to the Locked ID!
                    if self.locked_target_id and self.locked_target_id in self.tracked_persons and self.tracked_persons[self.locked_target_id].missed_frames > 15:
                        label = self.locked_target_id
                        new_person = TrackedPerson(label, raw, window_size=self.window_size)
                        self.tracked_persons[label] = new_person
                        result_targets.append(new_person.current_target)
                    else:
                        label = self._allocate_label()
                        new_person = TrackedPerson(label, raw, window_size=self.window_size)
                        new_person.validate_and_update(raw, self.mode, self.max_jump_mm, self.max_speed_mms, self.max_accel_mms2)
                        self.tracked_persons[label] = new_person
                        result_targets.append(new_person.current_target)

        # 4. Target Focus Lock Filtering & Fall Detection
        if self.locked_target_id:
            filtered = [t for t in result_targets if str(t.id) == self.locked_target_id]
            
            # Fall Detection Pipeline (only on confirmed targets to avoid ghost-triggered false alarms)
            if self.fall_detector and filtered:
                locked_target = filtered[0]
                locked_person = self.tracked_persons.get(self.locked_target_id)
                
                # Only feed confirmed targets to the fall detector
                # Unconfirmed targets (< MIN_CONFIRM_FRAMES visible) are likely ghosts
                if locked_person and not locked_person.confirmed:
                    locked_target.fall_prob = 0.0
                    locked_target.fall_alert = False
                    return filtered
                
                # Reset buffer if we locked onto a new target
                if self._last_locked_target != self.locked_target_id:
                    self.fall_detector.reset_buffer()
                    self.post_fall_validator.reset()
                    self._last_locked_target = self.locked_target_id
                    self._fall_consecutive_count = 0
                    self._fall_latch_frames = 0
                
                # Run inference
                prob = self.fall_detector.update(
                    x_mm=locked_target.x,
                    y_mm=locked_target.y,
                    speed_mms=locked_target.speed
                )
                
                # Attach metadata to target object
                locked_target.fall_prob = prob
                
                # Hysteresis confirmation: require probability >= 0.70
                # Confirmed after 2 positive detections, then forward to post-fall validator
                FALL_THRESHOLD = 0.70
                if prob >= FALL_THRESHOLD:
                    self._fall_consecutive_count += 1
                else:
                    self._fall_consecutive_count = max(0, self._fall_consecutive_count - 1)
                
                lstm_triggered = self._fall_consecutive_count >= 2
                
                # Post-fall confirmation state machine (Phase 3)
                # Feeds LSTM trigger + current speed into the validator
                fall_state = self.post_fall_validator.update(
                    lstm_triggered=lstm_triggered,
                    current_speed_mms=locked_target.speed,
                    fall_prob=prob
                )
                
                # Map validator state to target alert flags
                if fall_state == "CONFIRMED":
                    locked_target.fall_alert = True
                    locked_target.fall_alert_stage = "confirmed"
                elif fall_state == "PRE_ALERT":
                    locked_target.fall_alert = True
                    locked_target.fall_alert_stage = "pre_alert"
                else:
                    locked_target.fall_alert = False
                    locked_target.fall_alert_stage = "normal"
                
            return filtered

        return result_targets
