"""Blocking device discovery isolated from the GUI event loop."""
import socket
import time
from PySide6.QtCore import QThread, Signal

from ..serial.serial_reader import SerialReader


class HardwareDiscoveryWorker(QThread):
    found = Signal(str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, mode, port="", parent=None):
        super().__init__(parent)
        self.mode, self.port = mode, port

    def run(self):
        try:
            value = self._wifi() if self.mode == "wifi" else self._baud()
            if self.isInterruptionRequested():
                return
            if value:
                self.found.emit(value)
            else:
                self.failed.emit("No device found. Check its power and connection, or enter settings manually.")
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))

    def _wifi(self):
        self.progress.emit("Looking for the radar on your local network…")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                connection.settimeout(1.0)
                connection.sendto(b"DISCOVER_LD2450", ("<broadcast>", 8889))
                data, address = connection.recvfrom(1024)
                text = data.decode("utf-8", errors="ignore")
                return text.split("LD2450_IP:", 1)[1].strip() if "LD2450_IP:" in text else address[0]
        except OSError:
            if not self.isInterruptionRequested():
                try:
                    return socket.gethostbyname("ld2450.local")
                except OSError:
                    pass
        return ""

    def _baud(self):
        for baud in (115200, 256000, 9600, 57600, 460800):
            if self.isInterruptionRequested():
                break
            self.progress.emit(f"Checking {self.port} at {baud:,} baud…")
            reader = SerialReader(port=self.port, baud_rate=baud, timeout=.3)
            try:
                if reader.connect():
                    time.sleep(.15)
                    data = reader.read_available(1024)
                    if b"\xaa\xff" in data or b"Target " in data:
                        return str(baud)
            except (RuntimeError, OSError):
                pass
            finally:
                reader.disconnect()
        return ""
