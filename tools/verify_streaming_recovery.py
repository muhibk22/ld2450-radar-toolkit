"""End-to-end localhost smoke test with the actual UI and five trained models."""
import json
import argparse
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QFontDatabase
from app.gui.main_window import MainWindow
from app.net.socket_worker import SocketWorker
from tests.test_live_streaming import Peer,until


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'reports/live_streaming_diagnosis')
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    if not QFontDatabase.families() and os.name=='nt':
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        app.setFont(QFont('Segoe UI',10))
    peer=Peer(heartbeat=True)
    with patch('app.gui.main_window.get_available_ports',return_value=[]):
        window=MainWindow()
    worker=SocketWorker('127.0.0.1',peer.port,True,pipeline=window.pipeline,
                        silence_timeout=.25,frame_timeout=.4,retry_delay=.05)
    try:
        window.model_comparison.start()
        window.model_comparison.loading.result(timeout=90)
        window._poll_model_comparison()
        window.active_worker=worker
        worker.connection_changed.connect(window._update_connection_status)
        worker.stats_updated.connect(window._receive_worker_stats)
        window.show()
        worker.start()
        end=time.monotonic()+1.2
        while time.monotonic()<end:
            app.processEvents();time.sleep(.005)
        before=window.pipeline.frames
        time.sleep(.4)  # simulate a slow GUI export: receiver must keep advancing
        during=window.pipeline.frames
        end=time.monotonic()+3
        while time.monotonic()<end:
            app.processEvents();time.sleep(.005)
        snapshot=window.model_comparison.snapshot()
        result=dict(accepted_connections=len(peer.clients),reconnect_count=worker.reconnect_count,
                    frames_before_gui_pause=before,frames_after_gui_pause=during,
                    gui_processed_frames=window.frames_processed,receiver_frames=window.pipeline.frames,
                    models=list(window.model_comparison.models),rows=list(snapshot['rows']),
                    scores={k:v['score'] for k,v in snapshot['rows'].items()})
        assert result['accepted_connections']>=2,result
        assert during>before,result
        assert len(result['models'])==5 and 'legacy' not in result['rows'],result
        assert all(score is not None for score in result['scores'].values()),result
        out=args.out
        out.mkdir(parents=True,exist_ok=True)
        (out/'end_to_end_after_fix.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        window.fall_monitor_window.show()
        app.processEvents()
        window.fall_monitor_window.grab().save(str(out/'five_model_monitor.png'))
        print(json.dumps(result,indent=2))
    finally:
        worker.stop();peer.close();window.close();app.processEvents()


if __name__=='__main__':main()
