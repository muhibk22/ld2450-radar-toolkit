"""Identical, timestamp-based trailing windows for offline and live comparison."""
from collections import deque
import numpy as np

SCHEMA = 'radar-active-trailing-2s-10hz-v2'
DURATION = 2.0
STEP = 0.5
MAX_GAP = 0.5
POINTS = 21


def make_window(rows):
    """Rows are [timestamp, x_m, y_m, signed_speed_mps], strictly increasing."""
    a = np.asarray(rows, dtype=np.float64)
    grid = np.linspace(a[-1, 0] - DURATION, a[-1, 0], POINTS)
    xyz = np.column_stack([np.interp(grid, a[:, 0], a[:, c]) for c in (1, 2, 3)])
    velocity = np.clip(np.diff(xyz[:, :2], axis=0) / 0.1, -3.5, 3.5)
    smoothed = np.zeros((POINTS, 2))
    for i in range(1, POINTS):
        smoothed[i] = .3 * velocity[i-1] + .7 * smoothed[i-1]
    return np.column_stack((xyz[:, :2] - xyz[0, :2], smoothed, xyz[:, 2])).astype(np.float32)


class WindowBuffer:
    def __init__(self):
        self.rows = deque()
        self.last_prediction = None

    def reset(self):
        self.rows.clear()
        self.last_prediction = None

    def push(self, timestamp, x_mm, y_mm, speed_mms):
        values = np.array([timestamp, x_mm / 1000, y_mm / 1000, speed_mms / 1000])
        if not np.isfinite(values).all():
            self.reset()
            return None
        if self.rows:
            dt = timestamp - self.rows[-1][0]
            if dt <= 0:
                return None
            if dt > MAX_GAP:
                self.reset()
        self.rows.append(values)
        while len(self.rows) > 2 and self.rows[1][0] <= timestamp - DURATION:
            self.rows.popleft()
        if timestamp - self.rows[0][0] < DURATION - 1e-7:
            return None
        if self.last_prediction is not None and timestamp - self.last_prediction < STEP - 1e-7:
            return None
        self.last_prediction = timestamp
        return make_window(self.rows)


def summary_features(windows):
    """Temporal summaries; input (N, time, 5), output (N, features)."""
    w = np.asarray(windows, dtype=np.float32)
    parts = [w.mean(1), w.std(1), w.min(1), w.max(1), w[:, -1],
             np.quantile(w, .25, axis=1), np.quantile(w, .75, axis=1)]
    for segment in np.array_split(w, 3, axis=1):
        parts.extend([segment.mean(1), segment.std(1)])
    delta = np.diff(w[:, :, :2], axis=1)
    acceleration = np.diff(w[:, :, 2:4], axis=1) / .1
    parts.extend([np.linalg.norm(delta, axis=2).sum(1)[:, None],
                  np.linalg.norm(w[:, -1, :2], axis=1)[:, None],
                  np.abs(acceleration).mean(1), np.abs(acceleration).max(1),
                  (np.abs(w[:, :, 4]) < .15).mean(1)[:, None]])
    return np.column_stack(parts).astype(np.float32)
