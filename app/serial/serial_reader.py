"""
Low-level serial port connection and port enumeration wrapper.
"""

from typing import List
import serial
import serial.tools.list_ports
from ..config import DEFAULT_BAUD_RATE, SERIAL_TIMEOUT_SEC

def get_available_ports() -> List[str]:
    """Returns a list of active serial COM port names."""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in sorted(ports)]

class SerialReader:
    """Manages low-level PySerial lifecycle."""
    
    def __init__(self, port: str = "", baud_rate: int = DEFAULT_BAUD_RATE, timeout: float = SERIAL_TIMEOUT_SEC):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._ser: serial.Serial | None = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect(self, port: str | None = None, baud_rate: int | None = None) -> bool:
        """Establishes connection to serial port."""
        if port:
            self.port = port
        if baud_rate:
            self.baud_rate = baud_rate

        self.disconnect()

        try:
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout
            )
            return self._ser.is_open
        except (serial.SerialException, OSError) as e:
            self._ser = None
            raise RuntimeError(f"Failed to open port {self.port}: {e}") from e

    def disconnect(self):
        """Closes serial connection safely."""
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def read_available(self, size: int = 4096) -> bytes:
        """Reads available bytes from port buffer."""
        if not self.is_connected or not self._ser:
            return b""
        try:
            in_waiting = self._ser.in_waiting
            bytes_to_read = min(max(in_waiting, 1), size)
            return self._ser.read(bytes_to_read)
        except (serial.SerialException, OSError):
            self.disconnect()
            return b""
