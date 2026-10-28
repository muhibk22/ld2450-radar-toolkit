"""Live-path regression tests; all sockets stay on localhost."""
import csv
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from app.net.socket_worker import SocketWorker
from app.streaming import LivePipeline
from app.tracker.tracker import TargetTracker
from app.models.target import Target
from app.recording.buffered import BufferedRecorder


def frame(x=0):
    return b'\xaa\xff\x03\x00'+struct.pack('<HHHH',x,2000,0,360)+bytes(16)+b'\x55\xcc'


def until(predicate, timeout=4):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate(): return True
        time.sleep(.01)
    return False


class Peer:
    def __init__(self, heartbeat=False):
        self.halt=threading.Event()
        self.socket=socket.socket()
        self.socket.bind(('127.0.0.1',0)); self.socket.listen(4); self.socket.settimeout(.1)
        self.port=self.socket.getsockname()[1]
        self.clients=[]
        self.heartbeat=heartbeat
        self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start()

    def run(self):
        while not self.halt.is_set():
            try: client,_=self.socket.accept()
            except socket.timeout: continue
            except OSError: break
            self.clients.append(client)
            index=len(self.clients)
            threading.Thread(target=self.send,args=(client,index),daemon=True).start()

    def send(self,client,index):
        try:
            client.sendall(frame())
            while not self.halt.wait(.04):
                if index>1: client.sendall(frame())
                elif self.heartbeat: client.sendall(b'\nOMNISENSE_BOOT:{}\n')
        except OSError: pass

    def close(self):
        self.halt.set(); self.socket.close()
        for c in self.clients: c.close()
        self.thread.join(1)


class LiveStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QCoreApplication.instance() or QCoreApplication([])

    def reconnect(self, heartbeat):
        peer=Peer(heartbeat)
        worker=SocketWorker('127.0.0.1',peer.port,True,silence_timeout=.25,frame_timeout=.35,retry_delay=.03)
        try:
            worker.start()
            self.assertTrue(until(lambda:len(peer.clients)>=2))
            self.assertTrue(until(lambda:worker.pipeline.frames>=4))
            self.assertGreaterEqual(worker.reconnect_count,1)
            # No GUI event processing above: bytes/frames advance independently.
        finally:
            self.assertTrue(worker.stop())
            self.assertFalse(worker.isRunning())
            peer.close()

    def test_silent_open_connection_recovers_without_restart(self):
        self.reconnect(False)

    def test_heartbeats_without_radar_frames_trigger_reconnect(self):
        self.reconnect(True)

    def test_stop_during_retry_is_interruptible(self):
        listener=socket.socket(); listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]; listener.close()
        worker=SocketWorker('127.0.0.1',port,True,retry_delay=3)
        worker.start()
        self.assertTrue(until(lambda:worker.reconnect_count>0))
        tick=time.monotonic()
        self.assertTrue(worker.stop())
        self.assertLess(time.monotonic()-tick,.5)

    def test_stop_before_start_does_not_resurrect_worker(self):
        worker=SocketWorker('127.0.0.1',1)
        worker.request_stop(); worker.start()
        self.assertTrue(worker.wait(1000))
        self.assertEqual(worker.bytes_received,0)

    def test_coalesced_frames_preserve_motion_interval(self):
        pipeline=LivePipeline()
        pipeline.ingest(frame(0),now=1000)
        pipeline.ingest(b''.join(frame(x) for x in (100,200,300,400)),now=1000.4)
        target=pipeline.targets[0]
        self.assertEqual(target.status,'Active')
        self.assertAlmostEqual(target.x,350)  # two-point visual average
        # Preserve the original track's duplicated initialization sample in the
        # model-only history; display smoothing remains independent.
        self.assertAlmostEqual(pipeline.tracker.tracked_persons['Person A'].model_position[0],1000/6)

    def test_backlog_is_bounded_and_not_replayed(self):
        pipeline=LivePipeline()
        for i in range(200): pipeline.ingest(frame(i),now=1000+i*.1)
        preview=pipeline.drain()
        self.assertEqual(pipeline.frames,200)
        self.assertLessEqual(len(preview['packets']),60)
        self.assertLessEqual(len(preview['chunks']),60)
        pipeline.ingest(frame()*30,now=1021)
        self.assertEqual(pipeline.frames,205)
        self.assertEqual(pipeline.overwritten_previews,25)

    def test_reconnect_resets_partial_frame_and_identity(self):
        pipeline=LivePipeline()
        pipeline.ingest(frame()[:12],now=1000)
        generation=pipeline.session
        pipeline.reset()
        pipeline.ingest(frame(400),now=1001)
        self.assertGreater(pipeline.session,generation)
        self.assertEqual(len(pipeline.targets),1)
        self.assertEqual(pipeline.targets[0].x,400)

    def test_stale_track_disappears_without_new_frames(self):
        pipeline=LivePipeline()
        pipeline.ingest(frame(),received=time.monotonic()-.8)
        self.assertEqual(pipeline.drain()['targets'],[])

    def test_no_legacy_model_loaded_and_display_filter_is_independent(self):
        tracker=TargetTracker()
        self.assertFalse(hasattr(tracker,'fall_detector'))
        for i in range(20):
            tracker.process([Target('raw0',0,x=i*100,y=2000)],timestamp=1000+i*.1)
        person=tracker.tracked_persons['Person A']
        self.assertEqual(person.current_target.x,1850)
        self.assertEqual(person.model_position[0],1450)

    def test_recording_writer_preserves_labels_and_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder=BufferedRecorder()
            path=Path(directory)/'a_session01.csv'
            recorder.start_recording(path)
            recorder.set_action_label('6: Fall onset')
            recorder.record_frame(1,[Target('A',0,y=2000)])
            recorder.set_action_label('2: Standing / idle')
            recorder.record_frame(2,[Target('A',0,y=2000)])
            recorder.stop_recording(); recorder.close()
            self.assertIsNone(recorder.error)
            with path.open(newline='') as handle: rows=list(csv.DictReader(handle))
            self.assertEqual([r['action_label'] for r in rows],['6: Fall onset','2: Standing / idle'])

    def test_serial_disconnect_cannot_replace_port_mid_read(self):
        from app.serial.serial_reader import SerialReader
        reader=SerialReader()
        class Port:
            is_open=True
            @property
            def in_waiting(self):
                reader._ser=None  # simulate concurrent request_stop()
                return 3
            def read(self,count): return b'abc'[:count]
        reader._ser=Port()
        self.assertEqual(reader.read_available(),b'abc')


if __name__=='__main__': unittest.main()
