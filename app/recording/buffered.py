"""Bounded recording writer: filesystem pauses cannot block live ingestion."""
from dataclasses import replace
import queue
import threading
import time
from .recorder import DataRecorder


class BufferedRecorder:
    def __init__(self):
        self.is_recording = False
        self.current_action_label = '2: Standing / idle'
        self.error = None
        self._jobs = queue.Queue(maxsize=512)
        self._writer = DataRecorder()
        self._closed = False
        self._lock = threading.RLock()
        self._thread = threading.Thread(target=self._run,daemon=True,name='radar-recording')
        self._thread.start()

    def _put(self, job):
        try:
            self._jobs.put_nowait(job)
            return True
        except queue.Full:
            self.error = 'Recording writer is behind; recording stopped. Live tracking continues.'
            self.is_recording = False
            return False

    def set_action_label(self, label):
        with self._lock:
            self.current_action_label = label

    def start_recording(self, path, format_type='csv', metadata=None):
        with self._lock:
            if self._closed:
                raise RuntimeError('Recorder closed')
            self.error = None
            self.is_recording = self._put(('start',(path,format_type,dict(metadata or {}))))

    def record_frame(self, sequence_id, targets, timestamp=None):
        with self._lock:
            if self.is_recording:
                self._put(('frame',(sequence_id,[replace(t) for t in targets],
                                    self.current_action_label,time.time() if timestamp is None else timestamp)))

    def stop_recording(self, save=True):
        with self._lock:
            self.is_recording = False
            self._put(('stop',save))

    def _run(self):
        while True:
            try:
                kind,data = self._jobs.get(timeout=.1)
            except queue.Empty:
                if self._closed or (self.error and not self.is_recording):
                    self._writer.stop_recording()
                if self._closed:
                    return
                continue
            try:
                if kind == 'close':
                    self._writer.stop_recording()
                    return
                if kind == 'start':
                    self._writer.start_recording(*data)
                elif kind == 'stop':
                    self._writer.stop_recording(save=data)
                elif kind == 'frame':
                    sequence,targets,label,timestamp = data
                    self._writer.set_action_label(label)
                    self._writer.record_frame(sequence,targets,timestamp=timestamp)
            except Exception as exc:
                self.error = f'Recording error: {exc}'
                self.is_recording = False
            finally:
                self._jobs.task_done()

    def close(self):
        self.is_recording = False
        self._closed = True
        self._put(('close',None))
        self._thread.join(timeout=2.)
