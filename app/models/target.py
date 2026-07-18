"""
Target Data Model for LD2450 Desktop Toolkit.
"""

from dataclasses import dataclass, field
import math
import time

@dataclass
class Target:
    """
    Represents a detected or tracked radar target.
    
    Coordinates:
    - x: horizontal position in mm (-X left, +X right)
    - y: depth/distance in mm (+Y ahead)
    - speed: velocity in mm/s
    - distance: euclidean distance in mm
    - angle: direction angle in degrees
    """
    id: str                # e.g., "Person A", "Target 0"
    raw_id: int            # Raw slot 0, 1, 2
    x: float = 0.0         # mm
    y: float = 0.0         # mm
    speed: float = 0.0     # mm/s
    distance: float = 0.0  # mm
    angle: float = 0.0     # degrees
    valid: bool = True
    status: str = "Active"
    distance_resolution: float = 0.0
    
    # Fall Detection AI metadata
    fall_prob: float = 0.0
    fall_alert: bool = False

    # Tracking statistics & hysteresis metadata
    first_seen_time: float = field(default_factory=time.time)
    last_seen_time: float = field(default_factory=time.time)
    frames_visible: int = 1

    def __post_init__(self):
        if self.distance == 0.0 and (self.x != 0 or self.y != 0):
            self.distance = math.hypot(self.x, self.y)
        if self.angle == 0.0 and (self.x != 0 or self.y != 0):
            self.angle = math.degrees(math.atan2(self.x, self.y))

    @property
    def tracking_time(self) -> float:
        """Duration in seconds target has been tracked."""
        return max(0.0, time.time() - self.first_seen_time)
        
    def to_dict(self) -> dict:
        """Serializes the target into a dictionary for JSON recording."""
        return {
            "id": self.id,
            "raw_id": self.raw_id,
            "x": self.x,
            "y": self.y,
            "speed": self.speed,
            "distance": self.distance,
            "angle": self.angle,
            "valid": self.valid,
            "status": self.status,
            "distance_resolution": self.distance_resolution,
            "fall_prob": self.fall_prob,
            "fall_alert": self.fall_alert,
            "tracking_time": self.tracking_time
        }
