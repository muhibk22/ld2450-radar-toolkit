"""Align model flags with recorded tracking telemetry, ignoring activity labels.

This is a descriptive case study, not an independent accuracy evaluation.
Only analysis artifacts are written; runtime code and model weights are untouched.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.ml.ensemble_validation import PostConsensusValidator


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def intervals(mask, timestamps):
    result = []
    start = None
    for i, selected in enumerate(mask):
        if selected and start is None:
            start = i
        if start is not None and (not selected or i == len(mask)-1):
            end = i if not selected else i+1
            result.append((start,end))
            start = None
    return result


def features(t, xy, radial, active, anchor, horizon):
    idx = np.flatnonzero((t >= anchor) & (t < anchor+horizon))
    pre = np.flatnonzero(active & (t >= anchor-1.5) & (t <= anchor-.3))
    post = idx[active[idx]]
    result = dict(horizon_s=horizon,rows=len(idx),active_rows=len(post))
    if len(idx) < 2:
        return result
    result['recorded_position_shift_m'] = float(np.linalg.norm(xy[idx[-1]]-xy[idx[0]])/1000)
    result['active_row_fraction'] = float(active[idx].mean())
    # Integrate only adjacent fresh rows, clipped to the requested interval.
    covered = 0.0
    for i in range(max(1,idx[0]),min(len(t),idx[-1]+2)):
        if active[i-1] and active[i] and t[i]-t[i-1] <= .25:
            covered += max(0.0,min(t[i],anchor+horizon)-max(t[i-1],anchor))
    result['fresh_interval_fraction'] = min(1.0,covered/horizon)
    if len(post) > 1:
        direction = xy[post[-1]]-xy[post[0]]
        result['fresh_endpoint_shift_m'] = float(np.linalg.norm(direction)/1000)
        result['abs_radial_median_mps'] = float(np.median(abs(radial[post]))/1000)
        result['abs_radial_p95_mps'] = float(np.percentile(abs(radial[post]),95)/1000)
        if len(pre) > 1:
            approach = xy[pre[-1]]-xy[pre[0]]
            denom = np.linalg.norm(approach)*np.linalg.norm(direction)
            result['pre_post_heading_cosine'] = float(np.dot(approach,direction)/denom) if denom > 1 else None
            result['pre_post_heading_degrees'] = float(np.degrees(np.arccos(np.clip(result['pre_post_heading_cosine'],-1,1)))) if denom > 1 else None
    return result


def replay_validation(t, xy, radial, active, anchor):
    validator = PostConsensusValidator(anchor)
    idx = np.flatnonzero((t >= anchor-.5) & (t <= anchor+6))
    for i in idx:
        if active[i]:
            validator.observe(t[i],*xy[i],radial[i])
        else:
            validator.observe(t[i],fresh=False)
    result = validator.snapshot()
    result['resolution_delay_s'] = result['resolved_at']-anchor if result['resolved_at'] else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,default=ROOT/'data/raw_sessions/active_session_session01.csv')
    parser.add_argument('--detections',type=Path,default=ROOT/'fall_model_detections2.csv')
    parser.add_argument('--out',type=Path,default=ROOT/'reports/recorded_fall_case_study_current')
    args = parser.parse_args()
    rows, detections = read_csv(args.session), read_csv(args.detections)
    targets = {r['target_id'] for r in rows}
    if len(targets) != 1:
        raise ValueError('This case-study script expects a single recorded target')
    t = np.array([float(r['timestamp']) for r in rows])
    xy = np.array([[float(r['x_mm']),float(r['y_mm'])] for r in rows])
    radial = np.array([float(r['speed_mms']) for r in rows])
    active = np.array([r['status']=='Active' and r['valid'].lower()=='true' for r in rows])
    if not np.isfinite(np.column_stack((t,xy,radial))).all() or not (np.diff(t)>0).all():
        raise ValueError('Non-finite or unordered recording')
    groups = defaultdict(list)
    for detection in detections:
        groups[int(detection['event'])].append(detection)
    # Ground truth comes exclusively from the user's explicit event mapping.
    truth = {1:'real fall',2:'real fall',3:'real fall',4:'unconfirmed; ground truth unspecified',
             5:'real fall',6:'running reversal (false positive)'}
    events = []
    for key, group in sorted(groups.items()):
        flags = sorted(float(r['detection_timestamp']) for r in group)
        consensus = flags[3] if len(flags)>=4 else None
        anchor = consensus if consensus is not None else flags[0]
        event = dict(id=key,truth=truth.get(key,'unspecified'),votes=len(group),
                     models=[r['model'] for r in group],first_flag=flags[0],consensus_at=consensus,
                     anchor=anchor,anchor_seconds_into_recording=anchor-t[0],
                     local_time=datetime.fromtimestamp(anchor,ZoneInfo('Asia/Karachi')).strftime('%H:%M:%S.%f')[:-3],
                     min_flag_score=min(float(r['score']) for r in group),
                     max_flag_score=max(float(r['score']) for r in group),
                     detection_spread_s=flags[-1]-flags[0],
                     post_windows=[features(t,xy,radial,active,anchor,h) for h in (.75,1.,1.25,1.5,3.,5.)])
        if consensus is not None:
            event['current_validator_replay'] = replay_validation(t,xy,radial,active,anchor)
        events.append(event)
    # This transparent exploratory grid is evaluated on the same cases used to
    # propose it. It must not be reported as held-out performance.
    sensitivity = []
    labelled = [e for e in events if e['consensus_at'] is not None]
    for horizon in (.75,1.,1.25,1.5):
        for distance in (.3,.5,.7):
            rejected=[]
            for event in labelled:
                f=next(f for f in event['post_windows'] if f['horizon_s']==horizon)
                if (f.get('fresh_interval_fraction',0)>=.8 and
                    f.get('fresh_endpoint_shift_m',0)>=distance and
                    f.get('pre_post_heading_cosine',1) is not None and
                    f.get('pre_post_heading_cosine',1)<=-.5):
                    rejected.append(event['id'])
            sensitivity.append(dict(horizon_s=horizon,displacement_threshold_m=distance,
                                    min_fresh_interval_fraction=.8,heading_cosine_max=-.5,
                                    rejected_event_ids=rejected))
    gaps = []
    for first,end in intervals(~active,t):
        prev=max(0,first-1); following=min(len(t)-1,end)
        gaps.append(dict(start_s=float(t[first]-t[0]),end_s=float(t[end-1]-t[0]),
                         duration_between_fresh_rows_s=float(t[following]-t[prev]),rows=end-first))
    summary = dict(sources={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (args.session,args.detections)},
                   labels_ignored=True,ground_truth_source='User-confirmed event IDs; no activity labels read',
                   rows=len(rows),duration_s=float(t[-1]-t[0]),targets=list(targets),
                   status_counts=dict(Counter(r['status'] for r in rows)),
                   sample_period_median_s=float(np.median(np.diff(t))),
                   largest_recorded_sample_gap_s=float(np.diff(t).max()),
                   sequence_gaps=int(sum(np.diff([int(r['sequence_id']) for r in rows])!=1)),
                   inactive_intervals=gaps,events=events,reversal_veto_sensitivity=sensitivity)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'analysis.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    plot(t,xy,radial,active,events,args.out)
    write_report(summary,args.out)
    for event in events:
        f=next(f for f in event['post_windows'] if f['horizon_s']==1)
        print(json.dumps(dict(event=event['id'],votes=event['votes'],truth=event['truth'],
                              post_1s=f,validation=event.get('current_validator_replay'))))
    print('Sensitivity:',json.dumps(sensitivity))


def plot(t,xy,radial,active,events,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,2,figsize=(13,11),sharex=True,sharey=True)
    for ax,event in zip(axes.flat,events):
        anchor=event['anchor']; x=t-anchor
        idx=np.flatnonzero((x>=-2)&(x<=4))
        base=xy[idx[np.argmin(abs(x[idx]))]]
        depth=(xy[:,1]-base[1])/1000
        measured=np.where(active,depth,np.nan)
        ax.plot(x[idx],depth[idx],color='#94a3b8',ls=':',lw=1,label='Held/predicted display position')
        ax.plot(x[idx],measured[idx],color='#2563eb',lw=2,label='Fresh observed depth')
        for start,end in intervals(~active[idx],t[idx]):
            ax.axvspan(x[idx[start]],x[idx[min(end,len(idx)-1)]],color='#cbd5e1',alpha=.5)
        ax.axvline(0,color='#334155',ls='--',lw=1)
        ax.axvspan(0,1,color='#fbbf24',alpha=.15)
        ax.axhline(0,color='#94a3b8',lw=.7)
        title=f"Event {event['id']}: {event['votes']}/5 flags; "
        title+='FALSE POSITIVE' if event['id']==6 else 'real fall' if event['id'] in (1,2,3,5) else 'unconfirmed / unspecified'
        ax.set_title(title,color='#b91c1c' if event['id']==6 else '#0f172a',fontsize=11)
        ax.set_xlim(-2,4);ax.grid(alpha=.2)
        ax.set_ylabel('Depth change from event anchor (m)')
        ax.set_xlabel('Seconds from fourth model flag (event 4: first flag)')
    handles,labels=axes[0,0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',ncol=2,bbox_to_anchor=(.5,.005))
    fig.suptitle('Recorded motion after model flags\nShaded grey: no fresh accepted target; yellow: first post-consensus second',fontsize=14)
    fig.tight_layout(rect=(0,.04,1,.94))
    fig.savefig(out/'event_motion.png',dpi=160)
    plt.close(fig)


def write_report(summary,out):
    lines=['# Recorded fall and running-reversal case study','',
           '28 October 2026. Activity labels were ignored. Ground truth is the user-confirmed mapping: '
           'events 1, 2, 3 and 5 are real falls; event 6 is a running reversal. Event 4 has three model flags and unspecified ground truth.','',
           '## Data and alignment','',
           f"The recording contains {summary['rows']:,} tracker-output rows over {summary['duration_s']:.2f} seconds for Person A. "
           f"Median interval is {summary['sample_period_median_s']:.3f} s; largest recorded gap is {summary['largest_recorded_sample_gap_s']:.3f} s. "
           f"There are {summary['sequence_gaps']} sequence discontinuities. Status counts: {summary['status_counts']}.",
           '',
           'This is processed tracking telemetry, not UART packets. The recorder writes tracked coordinates and includes held/predicted targets. '
           'Only `Active` and valid rows count as fresh target observations. A non-active row cannot distinguish sensor loss, association failure or physical-gate rejection without the underlying UART capture. '
           'The detection export has only model flags (`stage=detected`) and empty confirmation timestamps, so it does not demonstrate that post-fall validation ran.',
           '',
           'Each alert is anchored at its fourth model flag, not its first flag or an assumed physical impact time. '
           'Event 4 has no four-vote consensus and is anchored at its first flag for plotting only.',
           '',
           '## Measured first second after consensus','',
           '| Event | User ground truth | Flags | Karachi time | Recorded position shift | Fresh rows | Fresh interval coverage | Heading change |',
           '|---|---|---:|---|---:|---:|---:|---:|']
    for event in summary['events']:
        f=next(f for f in event['post_windows'] if f['horizon_s']==1)
        lines.append(f"| {event['id']} | {event['truth']} | {event['votes']}/5 | {event['local_time']} | "
                     f"{f['recorded_position_shift_m']:.3f} m | {f['active_rows']}/{f['rows']} | {f['fresh_interval_fraction']:.0%} | "
                     f"{f.get('pre_post_heading_degrees',float('nan')):.0f} degrees |")
    lines += ['',
              'Position shift uses the first and last recorded rows in that second. Where tracking is predicted/held, '
              'a small displayed shift is not proof of physical stillness. Fresh interval coverage integrates time only between adjacent valid Active observations no more than 0.25 s apart.',
              '',
              'Event 6 has a 164-degree pre/post heading change and about 0.93 m recorded travel. '
              'Event 5 also reverses its small residual direction (172 degrees), but shifts only 0.016 m. '
              'A reversal-only veto would therefore be unsafe even within these examples. '
              'In event 5, fresh rows continue to report 0.88 m/s radial speed despite only 0.016 m recorded position shift in one second. '
              'This discrepancy also argues against a hard speed-only veto. The files cannot establish whether sensor estimates, tracking/filtering or another upstream effect explains it.',
              '',
              '## Replay of the current combined validator','',
              'The current combined validator was replayed on Active rows, with explicit missing-observation markers on other rows. '
              'Coordinates in this recording have already been display-filtered; this is not an exact replay of raw accepted coordinates. '
              'The earlier five-second draft results remain archived under reports/recorded_fall_case_study; '
              'the current implementation retains suspected warnings instead of requiring every true fall to pass stillness.',
              '',
              '| Event | Outcome | Delay from consensus | Reason |','|---|---|---:|---|']
    for event in summary['events']:
        result=event.get('current_validator_replay')
        if result:
            lines.append(f"| {event['id']} | {result['state']} | {result['resolution_delay_s']:.2f} s | {result['reason']} |")
    lines += ['',
              '## Combined behavior and limits','',
              'Use model consensus as an immediate suspected-fall signal. Add a short check for positive evidence of '
              'continued reverse running: substantial displacement on continuous fresh observations, with a heading opposed '
              'to the approach. An exploratory starting point is a 1.0–1.25 s observation, at least 0.5 m measured travel, '
              'at least 80% fresh interval coverage, and heading cosine <= -0.5 (at least 120 degrees). '
              'Check sustained travel across the interval rather than one extreme packet. Do not use a radial-speed sign change alone.',
              '',
              'At a 1.0-second horizon, 0.5 m fresh-endpoint displacement, 80% fresh interval coverage and a heading cosine <= -0.5, '
              'the exploratory veto selects only event 6. None of the four user-confirmed real events is vetoed. '
              'This is a proposed local separation, not proof that those falls can all be confirmed from the available sensor channels.',
              '',
              'Keep post-fall low motion as supporting evidence, not a required universal gate. If the target becomes Predicted/Searching, '
              'retain a visible suspected-fall / tracking-lost outcome and do not silently clear it or call the repeated position confirmed stillness. '
              'A real person who gets up promptly should not be rejected solely for later movement.',
              '',
              'The parameter grid in analysis.json uses the same supplied events to suggest thresholds. It is not held-out validation. '
              'Collect more direction reversals, abrupt stops, sitting, jumping and different genuine falls; tune and evaluate on separate '
              'whole sessions before production use. Retraining with these hard negatives is a better long-term correction to all five models '
              'than raising their score thresholds or requiring all five votes.',
              '',
              'All five models flag event 6, so unanimity does not remove it; event 3 has only four flags, so unanimity would remove a real alert. '
              'The files contain no body height or posture channel, so this analysis cannot verify that someone is lying down.',
              '',
              'This analysis command changes no model, threshold or runtime source. Combined validation now has a logged-flag '
              'and actual-model integration replay in tools/verify_combined_validation.py. This recording remains development '
              'evidence, not an independent estimate of general performance.',
              '',
              '## Reproduce','',
              '`python tools/analyze_recorded_falls.py`','',
              'Source SHA-256 fingerprints and numerical results are in analysis.json. The original CSVs remain unchanged.']
    (out/'analysis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
