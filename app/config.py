"""
Global configuration constants and configuration management for LD2450 Desktop Toolkit.
"""

from dataclasses import dataclass
from typing import Tuple

APP_NAME = "LD2450 Desktop Toolkit"
APP_VERSION = "1.0.0"

# Serial Communication Defaults
DEFAULT_BAUD_RATE = 256000
SERIAL_TIMEOUT_SEC = 1.0
BUFFER_SIZE_BYTES = 4096

# Packet Specifications (LD2450 protocol)
FRAME_HEADER = bytes([0xAA, 0xFF, 0x03, 0x00])
FRAME_FOOTER = bytes([0x55, 0xCC])
EXPECTED_FRAME_LEN = 30  # 4-byte header + 24-byte target payload (3 * 8B) + 2-byte footer

# Maximum simultaneous targets reported by LD2450 hardware
MAX_TARGETS = 3

# UI & Rendering Defaults
DEFAULT_FPS = 60
UI_REFRESH_INTERVAL_MS = int(1000 / DEFAULT_FPS)

# Radar Bounds (millimeters)
DEFAULT_RADAR_MAX_X = 6000     # -6000mm to +6000mm (+/- 6m horizontal)
DEFAULT_RADAR_MAX_Y = 8000     # 0 to 8000mm (8m depth)
TRAIL_HISTORY_MAX_FRAMES = 500
DEFAULT_TRAIL_LENGTH = 50

# Color Palette (Dark Theme / Glassmorphism UI)
COLOR_BACKGROUND = "#0F172A"   # Deep Navy / Slate
COLOR_GRID = "#334155"         # Slate Grid
COLOR_RADAR_ORIGIN = "#64748B" # Gray
TARGET_COLORS: list[str] = [
    "#38BDF8",  # Person A / Target 0: Sky Blue
    "#F43F5E",  # Person B / Target 1: Rose Pink
    "#10B981",  # Person C / Target 2: Emerald Green
    "#F59E0B",  # Target 3+: Amber
    "#8B5CF6",  # Target 4+: Purple
]

@dataclass
class AppConfig:
    baud_rate: int = DEFAULT_BAUD_RATE
    port: str = ""
    trail_length: int = DEFAULT_TRAIL_LENGTH
    max_x_mm: float = DEFAULT_RADAR_MAX_X
    max_y_mm: float = DEFAULT_RADAR_MAX_Y
    display_unit_meters: bool = False
    kalman_enabled: bool = True
