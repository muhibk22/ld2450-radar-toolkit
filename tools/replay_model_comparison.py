"""Exercise the actual comparison worker on a held-out recording without a radar.

Produces an event JSON and optional offscreen monitor screenshot. Timestamps are
replayed, not wall-clock arrival times. This is an integration check, not an
independent accuracy estimate or a substitute for a live hardware test.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.ml.model_comparison import ModelComparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',help='Session filename, default: a fall-bearing held-out session')
    parser.add_argument('--screenshot',action='store_true')
    args = parser.parse_args()
    base = ROOT/'app'/'ml'/'comparison_weights'
    manifest = json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    split = json.loads((base/manifest['run']/'split.json').read_text(encoding='utf-8'))
    if args.session:
        path = ROOT/'data'/'raw_sessions'/args.session
    else:
        path = next(ROOT/'data'/'raw_sessions'/name for name,part in split['session_assignments'].items()
                    if part=='test' and '6: Fall onset' in (ROOT/'data'/'raw_sessions'/name).read_text())
    service = ModelComparison()
    try:
        service.loading.result(timeout=120)
        with path.open(newline='',encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            timestamp = float(row['timestamp'])
            x,y,speed = [float(row[k]) for k in ('x_mm','y_mm','speed_mms')]
            with patch('time.time',return_value=timestamp):
                if row['status']=='Active':
                    service.feed(row['target_id'],timestamp,x,y,speed)
                if service.future is not None:
                    service.future.result(timeout=30)
                service.poll(timestamp)
        out = ROOT/'reports'/'model_comparison'
        out.mkdir(parents=True,exist_ok=True)
        snapshot = service.snapshot()
        (out/'replay.json').write_text(json.dumps(dict(session=path.name,**snapshot),indent=2),encoding='utf-8')
        print(json.dumps(dict(session=path.name,loaded_models=list(service.models),events=service.events),indent=2))
        if len(service.models)!=5:
            raise RuntimeError(f'Expected all five trained models: {service.rows}')
        if args.screenshot:
            os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QFont, QFontDatabase
            from PySide6.QtCore import QCoreApplication, QEvent
            from app.gui.fall_monitor import FallMonitorWindow
            app = QApplication.instance() or QApplication([])
            if not QFontDatabase.families() and os.name == 'nt':
                QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
                app.setFont(QFont('Segoe UI',10))
            window = FallMonitorWindow()
            window.setWindowTitle(f'Recorded-session replay: {path.name}')
            window.update_comparison(snapshot)
            window.resize(1100,720)
            window.show()
            app.processEvents()
            window.grab().save(str(out/'monitor_replay.png'))
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
    finally:
        service.close()


if __name__ == '__main__':
    main()
