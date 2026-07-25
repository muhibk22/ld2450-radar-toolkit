"""
QThread Serial Worker with Auto-Reconnect for LD2450 Protocol Explorer.
"""

from PySide6.QtCore import QThread, Signal
import time
from .serial_reader import SerialReader
from ..config import DEFAULT_BAUD_RATE
from ..utils.logger import setup_logger

logger = setup_logger("serial_worker")

class SerialWorker(QThread):
    """
    Background QThread serial stream worker with connection status reporting and auto-reconnect.
    """
    raw_data_received = Signal(bytes)
    connection_changed = Signal(bool, str)  # (connected, info_or_error)
    stats_updated = Signal(dict)

    def __init__(self, port: str = "", baud_rate: int = DEFAULT_BAUD_RATE, auto_reconnect: bool = True, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud_rate = baud_rate
        self.auto_reconnect = auto_reconnect
        self.reader = SerialReader(port=port, baud_rate=baud_rate)
        
        self._running = False
        self.reconnect_count = 0
        self.total_bytes_received = 0
        self._last_stats_time = time.time()
        self._interval_bytes = 0

    def set_connection(self, port: str, baud_rate: int, auto_reconnect: bool):
        self.port = port
        self.baud_rate = baud_rate
        self.auto_reconnect = auto_reconnect

    def stop(self):
        """Stops worker loop."""
        self._running = False
        self.wait(1000)

    def run(self):
        """Thread worker loop."""
        self._running = True
        logger.info(f"Starting serial worker for {self.port} at {self.baud_rate} baud")

        if not self._connect():
            if not self.auto_reconnect:
                self._running = False
                return

        self._last_stats_time = time.time()
        self._interval_bytes = 0

        while self._running:
            if not self.reader.is_connected:
                if self.auto_reconnect and self._running:
                    logger.warning(f"Connection lost. Attempting auto-reconnect #{self.reconnect_count + 1}...")
                    self.reconnect_count += 1
                    self.connection_changed.emit(False, f"Reconnecting (#{self.reconnect_count})...")
                    self.msleep(1000)
                    if self._connect():
                        logger.info("Auto-reconnect successful.")
                        continue
                    else:
                        continue
                else:
                    self.connection_changed.emit(False, "Disconnected")
                    break

            chunk = self.reader.read_available(2048)
            if chunk:
                self.raw_data_received.emit(chunk)
                self.total_bytes_received += len(chunk)
                self._interval_bytes += len(chunk)

            # Emit bandwidth stats every second
            now = time.time()
            elapsed = now - self._last_stats_time
            if elapsed >= 1.0:
                bytes_per_sec = self._interval_bytes / elapsed
                self.stats_updated.emit({
                    "bytes_per_sec": round(bytes_per_sec, 1),
                    "total_bytes": self.total_bytes_received,
                    "reconnect_count": self.reconnect_count
                })
                self._interval_bytes = 0
                self._last_stats_time = now

            self.msleep(5)

        self.reader.disconnect()
        logger.info("Serial worker stopped.")
        self.connection_changed.emit(False, "Disconnected")

    def _connect(self) -> bool:
        try:
            connected = self.reader.connect(self.port, self.baud_rate)
            if connected:
                self.connection_changed.emit(True, f"Connected to {self.port}")
                logger.info(f"Successfully connected to {self.port}")
            return connected
        except Exception as e:
            logger.error(f"Connection failed to {self.port}: {e}")
            self.connection_changed.emit(False, str(e))
            return False
