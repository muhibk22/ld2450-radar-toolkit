"""
Coordinate transforms and color palette utilities for Radar View.
"""

import math
from typing import Tuple
from ..config import TARGET_COLORS

class CoordinateConverter:
    """Utility functions for mm/m unit conversion and polar/Cartesian transforms."""

    @staticmethod
    def cartesian_to_polar(x: float, y: float) -> Tuple[float, float]:
        dist = math.hypot(x, y)
        angle = math.degrees(math.atan2(x, y))
        return dist, angle

    @staticmethod
    def polar_to_cartesian(distance: float, angle_deg: float) -> Tuple[float, float]:
        rad = math.radians(angle_deg)
        x = distance * math.sin(rad)
        y = distance * math.cos(rad)
        return x, y

    @staticmethod
    def mm_to_m(val_mm: float) -> float:
        return val_mm / 1000.0

def get_target_color(target_id: str | int) -> str:
    """Returns a deterministic, vibrant HEX color code for target ID."""
    name = str(target_id).upper()
    if "PERSON A" in name or "TARGET 0" in name:
        return TARGET_COLORS[0]
    elif "PERSON B" in name or "TARGET 1" in name:
        return TARGET_COLORS[1]
    elif "PERSON C" in name or "TARGET 2" in name:
        return TARGET_COLORS[2]
    elif "PERSON D" in name or "TARGET 3" in name:
        return TARGET_COLORS[3]

    if isinstance(target_id, int):
        idx = target_id % len(TARGET_COLORS)
    else:
        digits = [c for c in name if c.isdigit()]
        if digits:
            idx = int(digits[0]) % len(TARGET_COLORS)
        else:
            idx = sum(ord(c) for c in name) % len(TARGET_COLORS)
    return TARGET_COLORS[idx]
