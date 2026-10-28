"""Serial ingestion shares the worker-owned pipeline and freshness policy."""
import threading
import time
from PySide6.QtCore import QThread, Signal
from .serial_reader import SerialReader
from ..streaming import LivePipeline
from ..config import DEFAULT_BAUD_RATE

class SerialWorker(QThread):
    raw_data_received=Signal(bytes)
    connection_changed=Signal(bool,str)
    stats_updated=Signal(dict)

    def __init__(self,port='',baud_rate=DEFAULT_BAUD_RATE,auto_reconnect=True,parent=None,pipeline=None,
                 silence_timeout=3.,frame_timeout=5.):
        super().__init__(parent)
        self.port,self.baud_rate,self.auto_reconnect=port,baud_rate,auto_reconnect
        self.pipeline=pipeline or LivePipeline()
        self.reader=SerialReader(port=port,baud_rate=baud_rate,timeout=.1)
        self.silence_timeout,self.frame_timeout=silence_timeout,frame_timeout
        self._stop_event=threading.Event()
        self.reconnect_count=self.total_bytes_received=0

    def run(self):
        while not self._stop_event.is_set():
            self.pipeline.reset()
            try:
                self.reader.connect()
                self.connection_changed.emit(False,f'Serial {self.port} open - waiting for radar frames')
                last_byte=last_frame=stats_at=time.monotonic()
                healthy=False
                stats_bytes=self.total_bytes_received
                while not self._stop_event.is_set() and self.reader.is_connected:
                    chunk=self.reader.read_available(4096)
                    now=time.monotonic()
                    if chunk:
                        last_byte=now
                        self.total_bytes_received+=len(chunk)
                        if self.pipeline.ingest(chunk,received=now):
                            last_frame=now
                            if not healthy:
                                self.connection_changed.emit(True,f'Serial {self.port} - radar streaming')
                                healthy=True
                        self.raw_data_received.emit(chunk)
                    if now-stats_at >= .5:
                        self.stats_updated.emit(dict(bytes_per_sec=(self.total_bytes_received-stats_bytes)/(now-stats_at),
                            total_bytes=self.total_bytes_received,reconnect_count=self.reconnect_count,
                            byte_age_s=now-last_byte,frame_age_s=now-last_frame,
                            com_port=self.port,baud_rate=self.baud_rate))
                        stats_at,stats_bytes=now,self.total_bytes_received
                    if now-last_byte>=self.silence_timeout or now-last_frame>=self.frame_timeout:
                        raise TimeoutError('Serial radar stream stale; reconnecting')
                    self._stop_event.wait(.002)
            except (RuntimeError,OSError) as exc:
                if not self._stop_event.is_set(): self.connection_changed.emit(False,str(exc))
            finally:
                self.reader.disconnect()
                self.pipeline.reset()
            if not self.auto_reconnect or self._stop_event.is_set(): break
            self.reconnect_count+=1
            self._stop_event.wait(.5)
        self.connection_changed.emit(False,'Disconnected')

    def request_stop(self):
        self._stop_event.set()
        self.requestInterruption()
        self.reader.disconnect()

    def stop(self):
        self.request_stop()
        return self.wait(2000)
