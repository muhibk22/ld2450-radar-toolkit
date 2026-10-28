"""Read-only dataset/model audit; writes summaries under reports/fall_detection_audit.

Run from the repository root: python tools/audit_fall_dataset.py
Label runs are annotations, not verified physical fall events.
"""
import collections
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.analysis.dataset import load_dataset, collection_summary
from tools.train_fall_lstm_v2 import engine_features, passes_gates, load_session


def main():
    out = ROOT / 'reports' / 'fall_detection_audit'
    out.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset(ROOT / 'data' / 'raw_sessions')
    sessions = dataset.sessions
    summary = collection_summary(sessions)
    summary['issues'] = dataset.issues
    summary['duplicate_files'] = sum(bool(i['duplicate_of']) for i in dataset.inventory)
    summary['quality'] = {k: sum(s.summary()[k] for s in sessions) for k in
                          ['gaps_over_05s', 'coordinate_speed_flags', 'range_residual_flags',
                           'duplicate_rows', 'bad_rows', 'invalid_rows', 'backwards', 'zero_track_intervals']}
    summary['multi_target_sessions'] = sum(len(s.tracks) > 1 for s in sessions)
    summary['active_excluded_sessions'] = sum(s.excluded for s in sessions)
    summary['session_hz_percentiles_0_25_50_75_100'] = np.percentile([s.hz for s in sessions], [0,25,50,75,100]).tolist()
    summary['people'] = {p: collection_summary([s for s in sessions if s.person == p])
                         for p in sorted({s.person for s in sessions})}
    summary['fall_subtypes'] = dict(collections.Counter(s.subtype for s in sessions if s.counts[6]))
    counts = collections.Counter()
    spans, intervals, runs = [], [], []
    per_session = []
    raw_labels = collections.Counter()
    negative_speed_rows = 0
    for s in sessions:
        with s.path.open(newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                raw_labels[row['action_label']] += 1
                negative_speed_rows += float(row['speed_mms']) < 0
        for track in s.tracks:
            intervals.extend(track.dt[np.isfinite(track.dt)].tolist())
            mask = track.labels == 6
            starts = np.flatnonzero(mask & (~np.r_[False, mask[:-1]] | (track.dt > .5)))
            for start in starts:
                end = start
                while end + 1 < len(mask) and mask[end+1] and 0 < track.dt[end+1] <= .5:
                    end += 1
                runs.append(float(track.values[end,0] - track.values[start,0]))
        t,x,y,v,labels = load_session(str(s.path))
        features = engine_features(t,x,y,v)
        local = collections.Counter()
        for start in range(0, len(t)-19, 5):
            window = features[start:start+20]
            nfall = int(np.sum(labels[start:start+20] == '6'))
            category = 'positive' if nfall >= 5 else 'negative' if nfall == 0 else 'ambiguous'
            local[category] += 1
            if passes_gates(window):
                local[category+'_passing_gates'] += 1
            if np.any(np.diff(t[start:start+20]) > .5):
                local[category+'_crossing_gaps'] += 1
            spans.append(float(t[start+19]-t[start]))
        counts.update(local)
        per_session.append(dict(s.summary(), **local))
    summary['legacy_window_audit_before_negative_caps'] = dict(counts)
    summary['raw_action_labels'] = dict(raw_labels)
    summary['negative_radar_speed_rows'] = negative_speed_rows
    summary['window_span_seconds_percentiles_0_25_50_75_95_100'] = np.percentile(spans,[0,25,50,75,95,100]).tolist()
    summary['fall_run_span_seconds_percentiles_0_25_50_75_95_100'] = np.percentile(runs,[0,25,50,75,95,100]).tolist()
    dt = np.array(intervals)
    summary['track_intervals_fraction_below_007'] = float(np.mean(dt < .07))
    summary['track_intervals_fraction_above_015'] = float(np.mean(dt > .15))
    summary['weights_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ['weights','weights_v2','weights_archive/v1_baseline']
        for p in (ROOT/'app'/'ml'/folder).glob('*') if p.suffix in {'.pt','.npy'}}
    (out/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    keys = list(dict.fromkeys(k for s in per_session for k in s))
    with (out/'sessions.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, restval=0)
        writer.writeheader()
        writer.writerows(per_session)
    (out/'inventory.json').write_text(json.dumps(dataset.inventory,indent=2),encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
