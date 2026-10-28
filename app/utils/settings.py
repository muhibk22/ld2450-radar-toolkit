"""
QSettings wrapper for persistent application settings.
"""

from PySide6.QtCore import QSettings
import json
from ..tracker.noise import load_zones
from ..config import APP_NAME, DEFAULT_BAUD_RATE, DEFAULT_TRAIL_LENGTH, DEFAULT_RADAR_MAX_X, DEFAULT_RADAR_MAX_Y

class SettingsManager:
    """Manages reading and writing application preferences via QSettings."""
    
    def __init__(self):
        self.settings = QSettings("HLK-LD2450", APP_NAME)

    def get_last_port(self) -> str:
        return str(self.settings.value("serial/last_port", ""))

    def set_last_port(self, port: str):
        self.settings.setValue("serial/last_port", port)

    def get_baud_rate(self) -> int:
        return int(self.settings.value("serial/baud_rate", DEFAULT_BAUD_RATE))

    def set_baud_rate(self, baud: int):
        self.settings.setValue("serial/baud_rate", baud)

    def get_trail_length(self) -> int:
        return int(self.settings.value("visualization/trail_length", DEFAULT_TRAIL_LENGTH))

    def set_trail_length(self, length: int):
        self.settings.setValue("visualization/trail_length", length)

    def get_kalman_enabled(self) -> bool:
        return bool(self.settings.value("tracker/kalman_enabled", True, type=bool))

    def set_kalman_enabled(self, enabled: bool):
        self.settings.setValue("tracker/kalman_enabled", enabled)

    def get_noise_zones(self):
        try:
            records=json.loads(str(self.settings.value('tracker/noise_zones','[]')))
        except (ValueError,TypeError):
            records=[]
        return [z.to_dict() for z in load_zones(records)]

    def set_noise_zones(self,records):
        self.settings.setValue('tracker/noise_zones',json.dumps([z.to_dict() for z in load_zones(records)]))
        self.settings.sync()
