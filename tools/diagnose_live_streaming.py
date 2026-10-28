"""Read-only live-path reproductions using localhost and synthetic radar frames.

Does not connect to, reset, or send commands to the physical ESP32/radar.
Writes measured evidence to reports/live_streaming_diagnosis/reproductions.json.
"""
import json
import argparse
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QCoreApplication, Qt
from app.net.socket_worker import SocketWorker
from app.models.target import Target
from app.parser.packet_parser import PacketParser
from app.parser.packet_decoder import PacketDecoder
from app.tracker.tracker import TargetTracker, TrackedPerson


def frame(x=0,y=2000,speed=100):
    # Use source decoder's convention for this transport/tracker reproduction.
    signed = lambda v: abs(v) | (0x8000 if v < 0 else 0)
    return bytes.fromhex('AA FF 03 00')+struct.pack('<HHHH',signed(x),signed(y),signed(speed),360)+bytes(16)+bytes.fromhex('55 CC')


def silent_connection(heartbeat=False):
    server = socket.socket()
    server.bind(('127.0.0.1',0))
    server.listen(3)
    server.settimeout(.1)
    halt,ready = threading.Event(),threading.Event()
    accepted = []
    def peer():
        client = None
        try:
            client,_ = server.accept()
            accepted.append(time.monotonic())
            client.sendall(frame())
            ready.set()
            start = time.monotonic()
            while not halt.wait(.1):
                if heartbeat and time.monotonic()-start > .5:
                    client.sendall(b'\nOMNISENSE_BOOT:{"bootId":"constant","nodeId":"node_1"}\n')
                try:
                    extra,_ = server.accept()
                    accepted.append(time.monotonic())
                    extra.close()
                except socket.timeout:
                    pass
        finally:
            if client:
                client.close()
    thread = threading.Thread(target=peer,daemon=True)
    thread.start()
    worker = SocketWorker('127.0.0.1',server.getsockname()[1],True)
    statuses,chunks = [],[]
    parser = PacketParser()
    worker.connection_changed.connect(lambda connected,info:statuses.append((connected,info)),Qt.ConnectionType.DirectConnection)
    def received(data):
        chunks.append((time.monotonic(),len(data)))
        parser.parse_stream(data)
    worker.raw_data_received.connect(received,Qt.ConnectionType.DirectConnection)
    worker.start()
    if not ready.wait(3):
        raise RuntimeError('Localhost fixture did not connect')
    time.sleep(2.2)
    result = dict(accepted_connections=len(accepted),receive_chunks=len(chunks),parsed_frames=parser.total_packets_received,
                  last_status=list(statuses[-1]),running_after_2s_without_radar_frames=worker.isRunning())
    worker.stop()
    worker.wait(4000)
    halt.set()
    thread.join(2)
    server.close()
    return result


def stop_during_reconnect():
    server = socket.socket()
    server.bind(('127.0.0.1',0))
    port = server.getsockname()[1]
    server.close()
    worker = SocketWorker('127.0.0.1',port,True)
    failed = threading.Event()
    worker.connection_changed.connect(lambda ok,info: failed.set() if 'Connection Failed:' in info else None,Qt.ConnectionType.DirectConnection)
    worker.start()
    if not failed.wait(4):
        worker.stop(); worker.wait(4000)
        raise RuntimeError('Expected a refused localhost connection')
    time.sleep(.03)
    tick=time.monotonic()
    worker.stop()
    result=dict(stop_return_seconds=time.monotonic()-tick,is_running_after_stop_returns=worker.isRunning())
    worker.wait(4000)
    return result


def tracker_clock(times):
    tracker=TargetTracker()
    tracker.window_size=1
    results=[]
    for i,timestamp in enumerate(times):
        with patch('app.tracker.tracker.time.time',return_value=timestamp):
            targets=tracker.process([Target('Target 0',0,x=100*i,y=2000,speed=1000,distance_resolution=360)],timestamp=timestamp)
        results.append(dict(input_x=100*i,output_x=targets[0].x,status=targets[0].status))
    return results


def smoothing(mode):
    with patch('app.tracker.tracker.time.time',return_value=1000):
        person=TrackedPerson('A',Target('Target 0',0,x=0,y=2000),10)
    result=[]
    for i in range(1,31):
        with patch('app.tracker.tracker.time.time',return_value=1000+i*.1):
            target=Target('Target 0',0,x=i*100,y=2000,speed=1000)
            person.validate_and_update(target,mode,1500,6000,80000)
        if i in (5,10,20,30):
            result.append(dict(seconds=i*.1,input_x=i*100,output_x=target.x,lag_mm=i*100-target.x))
    return result


def parser_fragmentation():
    parser=PacketParser()
    packets=[]
    stream=frame()*100
    for byte in stream:
        packets.extend(parser.parse_stream(bytes([byte]))[0])
    return dict(sent_frames=100,parsed_frames=len(packets),corrupt=parser.corrupt_packets,remaining_bytes=len(parser.buffer))


def gui_cost():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase,QFont
    from app.gui.main_window import MainWindow
    import numpy as np
    app=QApplication.instance() or QApplication([])
    if not QFontDatabase.families() and os.name=='nt':
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        app.setFont(QFont('Segoe UI',10))
    with patch('app.gui.main_window.get_available_ports',return_value=[]):
        window=MainWindow()
    try:
        window.model_comparison.start()
        window.model_comparison.loading.result(timeout=90)
        window._poll_model_comparison()
        window.show()
        app.processEvents()
        results={}
        for label,index in [('live_radar',0),('raw_packet_inspector',2)]:
            window.workspace_tabs.setCurrentIndex(index)
            app.processEvents()
            durations=[]
            for i in range(150):
                start=time.perf_counter()
                window._on_raw_serial_data(frame(x=10*(i%50),speed=100))
                app.processEvents()
                durations.append((time.perf_counter()-start)*1000)
            results[label]=dict(frames=150,callback_and_paint_ms_median=float(np.median(durations)),
                                callback_and_paint_ms_p95=float(np.percentile(durations,95)),
                                maximum_ms=max(durations),last_processed=window.frames_processed)
        results['loaded_comparison_models']=list(window.model_comparison.models)
        return results
    finally:
        window.close()


def inference_cost():
    import numpy as np
    from app.ml.model_comparison import ModelComparison
    service=ModelComparison()
    try:
        service.loading.result(timeout=90)
        service.poll()
        values=[]
        for _ in range(6):
            tick=time.perf_counter()
            service._predict((0,'probe',time.time(),np.zeros((21,5),dtype=np.float32)),service.models)
            values.append((time.perf_counter()-tick)*1000)
        return dict(five_model_inference_ms=values,loaded_challengers=list(service.models))
    finally:
        service.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true',help='Benchmark actual window in an offscreen process')
    parser.add_argument('--inference',action='store_true',help='Measure legacy model on caller thread')
    args=parser.parse_args()
    destination=ROOT/'reports'/'live_streaming_diagnosis'
    destination.mkdir(parents=True,exist_ok=True)
    if args.gui or args.inference:
        result=gui_cost() if args.gui else inference_cost()
        filename='gui_benchmark.json' if args.gui else 'inference_benchmark.json'
        (destination/filename).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        return
    app=QCoreApplication.instance() or QCoreApplication([])
    results=dict(
        silent_tcp=silent_connection(),
        heartbeat_only_tcp=silent_connection(True),
        reconnect_stop_race=stop_during_reconnect(),
        normally_spaced_frames=tracker_clock([1000+i*.1 for i in range(10)]),
        same_frames_delivered_in_one_chunk=tracker_clock([1000+i*.001 for i in range(10)]),
        rolling_average=smoothing('PHYSICAL_GATE_AVG'),
        kalman=smoothing('PHYSICAL_GATE_KALMAN'),
        parser_byte_fragmentation=parser_fragmentation())
    (destination/'reproductions_after_fix.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
