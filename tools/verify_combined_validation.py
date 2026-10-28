"""Replay logged flags and optionally all five unchanged models on the recording.

Activity labels are ignored. Tracker CSV coordinates are already filtered, so
rerunning models is an integration check, not exact raw-UART reproduction.
"""
import argparse
from collections import deque
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.ml.model_comparison import ModelComparison


def load(path):
    with path.open(newline='',encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def logged_flag_replay(rows,flags):
    service=ModelComparison(autoload=False)
    service.started=True  # Logged flags replace inference in this isolated replay.
    ordered=sorted(flags,key=lambda r:float(r['detection_timestamp']))
    cursor=0
    mapping={}
    timeline=[]
    clock=0
    try:
        # Merge observations and flag timestamps in true chronological order.
        stream=[(float(r['timestamp']),0,r) for r in rows]
        stream += [(float(r['detection_timestamp']),1,r) for r in ordered]
        for clock,kind,row in sorted(stream,key=lambda item:(item[0],item[1])):
            with patch('app.ml.model_comparison.time.time',return_value=clock):
                if kind==0:
                    if row['status']=='Active' and row['valid'].lower()=='true':
                        service.feed(row['target_id'],clock,float(row['x_mm']),float(row['y_mm']),float(row['speed_mms']))
                    else:
                        service.tracking_unavailable(clock,target_absent=True)
                else:
                    # A flag can arrive just before its recorder row, or just
                    # after a gap reset; this event still belongs to its target.
                    if service.target != row['target']:
                        service._invalidate(row['target'],'Recorded flag target restored')
                    event=service._record(row['model'],clock,float(row['score']))
                    mapping[int(row['event'])]=event['id']
                    cursor+=1
                service.poll(clock)
                status=service.get_ensemble_status(clock)
                point=(status['stage'],tuple(w['event_id'] for w in status['warnings']))
                if not timeline or point != timeline[-1]['signature']:
                    timeline.append(dict(timestamp=clock,signature=point,stage=status['stage'],
                                         warning_event_ids=list(point[1])))
        with patch('app.ml.model_comparison.time.time',return_value=clock):
            snapshot=service.snapshot()
        by_id={e['id']:e for e in snapshot['events']}
        outcomes={str(source):dict(runtime_event_id=target,validation=by_id[target]['validation'],
                                  votes=len(by_id[target]['detections'])) for source,target in mapping.items()}
        for event_id in (1,2,3,5):
            assert outcomes[str(event_id)]['validation']['state']=='confirmed',outcomes
        assert outcomes['6']['validation']['state']=='rejected',outcomes['6']
        assert outcomes['4']['votes']==3 and outcomes['4']['validation']['state']=='awaiting_votes',outcomes['4']
        warnings_before=service.get_ensemble_status(clock)['warning_count']
        service.reset_stream()
        assert service.get_ensemble_status(clock+100)['warning_count']==warnings_before
        with patch('app.ml.model_comparison.time.time',return_value=clock+100):
            service.acknowledge_warnings()
        assert service.get_ensemble_status(clock+100)['warning_count']==0
        return dict(mode='recorded model flags plus recorded tracking observations',labels_ignored=True,
                    absence_assumption='Non-Active rows in this user-described fall recording are replayed as healthy reports with no eligible target; raw UART/association evidence was not recorded',
                    flags_replayed=cursor,outcomes=outcomes,timeline=timeline,snapshot=snapshot,
                    reset_kept_warnings=True,acknowledgement_cleared_warnings=True)
    finally:
        service.close()


def actual_model_replay(rows):
    service=ModelComparison()
    samples=deque(maxlen=10)
    previous=None
    try:
        service.loading.result(timeout=120)
        clock=float(rows[0]['timestamp'])
        with patch('app.ml.model_comparison.time.time',return_value=clock):
            service.poll(clock)
        assert len(service.models)==5,service.rows
        for row in rows:
            clock=float(row['timestamp'])
            with patch('app.ml.model_comparison.time.time',return_value=clock):
                if row['status']=='Active' and row['valid'].lower()=='true':
                    x,y,speed=(float(row[k]) for k in ('x_mm','y_mm','speed_mms'))
                    if previous is None or clock-previous>.4:
                        samples.clear()
                        samples.append((x,y))
                    samples.append((x,y))
                    service.feed(row['target_id'],clock,
                                 sum(p[0] for p in samples)/len(samples),sum(p[1] for p in samples)/len(samples),speed,
                                 validation_x_mm=x,validation_y_mm=y)
                    previous=clock
                else:
                    service.tracking_unavailable(clock,target_absent=True)
                if service.future is not None:
                    service.future.result(timeout=30)
                service.poll(clock)
        with patch('app.ml.model_comparison.time.time',return_value=clock):
            snapshot=service.snapshot()
        assert all(row['status']!='Error' for row in service.rows.values()),service.rows
        return dict(mode='unchanged models; reconstructed ten-sample smoothing over recorded filtered positions',
                    labels_ignored=True,loaded_models=list(service.models),snapshot=snapshot,
                    caveat='Scores/flag times can differ from the live export because original accepted UART coordinates were not recorded')
    finally:
        service.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-models',action='store_true')
    parser.add_argument('--screenshot',action='store_true')
    parser.add_argument('--out',type=Path,default=ROOT/'reports/combined_validation')
    args=parser.parse_args()
    out=args.out
    out.mkdir(parents=True,exist_ok=True)
    session=ROOT/'data/raw_sessions/active_session_session01.csv'
    flags=ROOT/'fall_model_detections2.csv'
    rows=load(session)
    result=logged_flag_replay(rows,load(flags))
    (out/'recorded_flags_replay.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Logged flag replay outcomes:')
    for key,event in result['outcomes'].items():
        validation=event['validation']
        print(key,event['votes'],validation['state'],validation['reason'])
    if args.actual_models:
        actual=actual_model_replay(rows)
        indexed={e['id']:e for e in actual['snapshot']['events']}
        assert all(indexed[i]['validation']['state']=='confirmed' for i in (1,2,3,5)),indexed
        assert indexed[6]['validation']['state']=='rejected',indexed[6]
        (out/'actual_models_replay.json').write_text(json.dumps(actual,indent=2)+'\n',encoding='utf-8')
        print('Actual models loaded:',actual['loaded_models'])
        print('Actual replay events:',[(e['id'],e['validation']['state']) for e in actual['snapshot']['events']])
    if args.screenshot:
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont,QFontDatabase
        from PySide6.QtCore import QCoreApplication,QEvent
        from app.gui.fall_monitor import FallMonitorWindow
        app=QApplication.instance() or QApplication([])
        if not QFontDatabase.families() and os.name=='nt':
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
            app.setFont(QFont('Segoe UI',10))
        window=FallMonitorWindow()
        display=actual['snapshot'] if args.actual_models else result['snapshot']
        window.update_comparison(display)
        status=display['ensemble']
        window.update_fall_status(status['fall_alert'],status['avg_score'],status['stage'],status['votes'])
        window.resize(1400,850)
        window.show()
        app.processEvents()
        window.grab().save(str(out/'recorded_validation_monitor.png'))
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
    fingerprints=json.loads((ROOT/'reports/combined_validation/unchanged_inputs_before.json').read_text())
    changed=[p for p,h in fingerprints.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    assert not changed,changed
    (out/'unchanged_inputs_verified.json').write_text(json.dumps(dict(files_checked=len(fingerprints),unchanged=True),indent=2)+'\n')
    print('Model/source fingerprints unchanged:',len(fingerprints))


if __name__=='__main__':main()
