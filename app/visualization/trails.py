"""
Motion Trail History Manager.
"""

from collections import deque
from typing import Dict, List, Tuple
from ..config import DEFAULT_TRAIL_LENGTH, TRAIL_HISTORY_MAX_FRAMES

class MotionTrailManager:
    """
    Maintains a rolling ring-buffer history of (X, Y) coordinate points for active targets.
    """

    def __init__(self, max_history_length: int = DEFAULT_TRAIL_LENGTH):
        self.max_history_length = min(max(1, max_history_length), TRAIL_HISTORY_MAX_FRAMES)
        self.histories: Dict[str, deque[Tuple[float, float]]] = {}

    def set_max_length(self, length: int):
        """Updates maximum trail points stored per target."""
        self.max_history_length = min(max(1, length), TRAIL_HISTORY_MAX_FRAMES)
        for d in self.histories.values():
            while len(d) > self.max_history_length:
                d.popleft()

    def add_point(self, target_id: str | int, x: float, y: float):
        """Appends a new position sample to the target's trajectory."""
        key = str(target_id)
        if key not in self.histories:
            self.histories[key] = deque(maxlen=self.max_history_length)
        self.histories[key].append((x, y))

    def get_trail(self, target_id: str | int) -> List[Tuple[float, float]]:
        """Returns list of (x, y) tuples from oldest to newest."""
        key = str(target_id)
        return list(self.histories.get(key, []))

    def clear(self):
        """Clears all stored history."""
        self.histories.clear()
