"""Interruptible TCP ingestion with byte and valid-frame freshness watchdogs."""
import socket
import threading
import time
from PySide6.QtCore import QThread, Signal
from ..streaming import LivePipeline
from ..utils.logger import setup_logger
logger = setup_logger('socket_worker')

class SocketWorker(QThread):
    raw_data_received = Signal(bytes)
    connection_changed = Signal(bool, str)
    stats_updated = Signal(dict)

    def __init__(self, host='192.168.100.130', port=8888, auto_reconnect=True,
                 pipeline=None, silence_timeout=3., frame_timeout=5., retry_delay=.5):
        super().__init__()
        self.host,self.port,self.auto_reconnect=host,port,auto_reconnect
        self.pipeline = pipeline or LivePipeline()
        self.silence_timeout,self.frame_timeout,self.retry_delay=silence_timeout,frame_timeout,retry_delay
        self._stop_event = threading.Event()
        self._socket = None
        self._socket_lock = threading.Lock()
        self.bytes_received = self.packets_received = self.reconnect_count = 0
        self._stats_at = time.monotonic()
        self._stats_bytes = 0

    def run(self):
        attempts = 0
        while not self._stop_event.is_set():
            try:
                self.pipeline.reset()
                self.connection_changed.emit(False,f'Connecting to {self.host}:{self.port}...')
                sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                with self._socket_lock:
                    self._socket=sock
                sock.settimeout(1.)
                if self._stop_event.is_set():
                    break
                sock.connect((self.host,self.port))
                sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)
                sock.settimeout(.1)
                attempts = 0
                self.connection_changed.emit(False,f'Wi-Fi socket open at {self.host}:{self.port} - waiting for radar frames')
                last_byte=last_frame=time.monotonic()
                healthy=False
                while not self._stop_event.is_set():
                    try:
                        chunk=sock.recv(4096)
                        if not chunk:
                            raise ConnectionError('ESP32 closed the stream')
                        last_byte=time.monotonic()
                        self.bytes_received += len(chunk)
                        self.packets_received += 1
                        count=self.pipeline.ingest(chunk,received=last_byte)
                        if count:
                            last_frame=time.monotonic()
                            if not healthy:
                                healthy=True
                                self.connection_changed.emit(True,f'Wi-Fi {self.host}:{self.port} - radar streaming')
                        self.raw_data_received.emit(chunk)
                    except socket.timeout:
                        pass
                    now=time.monotonic()
                    self._emit_stats(now,last_byte,last_frame)
                    if now-last_byte >= self.silence_timeout:
                        raise TimeoutError('No incoming bytes; reconnecting')
                    if now-last_frame >= self.frame_timeout:
                        raise TimeoutError('No valid radar frames (status messages do not count); reconnecting')
            except (OSError,RuntimeError) as exc:
                if not self._stop_event.is_set():
                    logger.warning('%s',exc)
                    self.connection_changed.emit(False,str(exc))
            finally:
                self._close_socket()
                self.pipeline.reset()
            if not self.auto_reconnect or self._stop_event.is_set():
                break
            self.reconnect_count += 1
            attempts += 1
            self._stop_event.wait(min(3.,self.retry_delay*2**min(attempts-1,3)))
        self.connection_changed.emit(False,'Disconnected')

    def _emit_stats(self, now, last_byte, last_frame):
        elapsed=now-self._stats_at
        if elapsed < .5:
            return
        self.stats_updated.emit(dict(bytes_per_sec=round((self.bytes_received-self._stats_bytes)/elapsed,1),
            total_bytes=self.bytes_received,reconnect_count=self.reconnect_count,
            byte_age_s=now-last_byte,frame_age_s=now-last_frame,connection_type='Wi-Fi TCP',
            host=self.host,port=self.port))
        self._stats_at,self._stats_bytes=now,self.bytes_received

    def _close_socket(self):
        with self._socket_lock:
            sock,self._socket=self._socket,None
        if sock:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            sock.close()

    def write_bytes(self,data):
        with self._socket_lock:
            sock=self._socket
        if not sock:
            return False
        try:
            sock.sendall(data)
            return True
        except OSError:
            return False

    def request_stop(self):
        self._stop_event.set()
        self.requestInterruption()
        self._close_socket()

    def stop(self):
        self.request_stop()
        return self.wait(2000)
