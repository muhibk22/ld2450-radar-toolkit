"""
High-Performance TCP Socket Worker for Wireless Wi-Fi Communication with ESP32.
"""

from PySide6.QtCore import QThread, Signal, Slot
import socket
import time
from ..utils.logger import setup_logger

logger = setup_logger("socket_worker")

class SocketWorker(QThread):
    """
    Asynchronous TCP Client Worker Thread streaming raw radar packets over Wi-Fi network.
    Emits identical signals as SerialWorker for seamless UI/Tracker integration.
    """
    raw_data_received = Signal(bytes)
    connection_changed = Signal(bool, str)
    stats_updated = Signal(dict)

    def __init__(self, host: str = "192.168.100.130", port: int = 8888, auto_reconnect: bool = True):
        super().__init__()
        self.host = host
        self.port = port
        self.auto_reconnect = auto_reconnect
        self._running = False
        self._socket: socket.socket | None = None

        self.bytes_received = 0
        self.packets_received = 0
        self.start_time = time.time()

    def run(self):
        self._running = True
        self.start_time = time.time()
        logger.info(f"Starting TCP Socket worker for {self.host}:{self.port}")

        while self._running:
            try:
                # Resolve host first
                ip_addr = socket.gethostbyname(self.host)
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(3.0)
                self.connection_changed.emit(False, f"Connecting to {self.host} ({ip_addr}:{self.port})...")
                
                self._socket.connect((ip_addr, self.port))
                self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # Disable Nagle buffering
                self._socket.settimeout(0.5)
                logger.info(f"Successfully connected to Wi-Fi ESP32 at {self.host}:{self.port} (TCP_NODELAY enabled)")
                self.connection_changed.emit(True, f"Wi-Fi Connected ({self.host}:{self.port})")

                while self._running:
                    try:
                        chunk = self._socket.recv(2048)
                        if not chunk:
                            logger.warning("Wi-Fi connection closed by ESP32 server.")
                            break
                        
                        self.bytes_received += len(chunk)
                        self.packets_received += 1
                        self.raw_data_received.emit(chunk)
                        self._emit_stats()

                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self._running:
                            logger.warning(f"Wi-Fi read error: {e}")
                        break

            except Exception as err:
                if self._running:
                    logger.warning(f"Could not connect to {self.host}:{self.port}: {err}")
                    self.connection_changed.emit(False, f"Connection Failed: {err}")
            finally:
                self._close_socket()

            if self.auto_reconnect and self._running:
                time.sleep(1.5)
            else:
                break

        self.connection_changed.emit(False, "Disconnected")
        logger.info("TCP Socket worker stopped.")

    def write_bytes(self, data: bytes) -> bool:
        """Sends data back over Wi-Fi socket to ESP32."""
        if self._socket:
            try:
                self._socket.sendall(data)
                return True
            except Exception as e:
                logger.error(f"Failed to send data over Wi-Fi: {e}")
        return False

    def _emit_stats(self):
        elapsed = max(0.1, time.time() - self.start_time)
        stats = {
            "bytes_received": self.bytes_received,
            "packets_received": self.packets_received,
            "throughput_bps": (self.bytes_received * 8) / elapsed,
            "elapsed_seconds": elapsed,
            "host": self.host,
            "port": self.port,
            "connection_type": "Wi-Fi TCP"
        }
        self.stats_updated.emit(stats)

    def _close_socket(self):
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def stop(self):
        """Stops thread execution cleanly."""
        self._running = False
        self._close_socket()
        self.wait(1000)
