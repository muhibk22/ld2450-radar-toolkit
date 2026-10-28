"""Train isolated fall challengers; never writes to the legacy weights folders.

python tools/train_comparison_models.py --epochs 25
Participant-disjoint train/validation/test split, shared streaming preprocessing.
Thresholds/checkpoints use validation only; test windows retain natural balance.
"""
import argparse
import collections
import csv
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import random
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.analysis.dataset import load_dataset
from app.ml.comparison_features import SCHEMA, WindowBuffer, DURATION, POINTS, summary_features
from app.ml.comparison_models import neural_model, ArtifactModel

PEOPLE = {
    'train': ['abdullah', 'zain', 'arslan', 'hafsa', 'aiman'],
    'validation': ['muhib', 'zoya'],
    'test': ['shahmeer', 'shazia'],
}
NAMES = {'xgboost': 'XGBoost', 'minirocket': 'MiniROCKET', 'tcn': 'TCN', 'gru': 'GRU', 'lstm': 'LSTM (retrained)'}


def session_split(sessions,seed):
    """Assign whole sessions within (participant, fall-presence) strata."""
    rng = random.Random(seed)
    groups = collections.defaultdict(list)
    assignments = {}
    for session in sessions:
        if not session.excluded:
            groups[(session.person, bool(session.counts[6]))].append(session.path.name)
    for _,names in sorted(groups.items()):
        names.sort()
        rng.shuffle(names)
        n = max(1,round(len(names)*.15)) if len(names) >= 3 else 0
        assignments.update({name:'validation' for name in names[:n]})
        assignments.update({name:'test' for name in names[n:2*n]})
        assignments.update({name:'train' for name in names[2*n:]})
    return assignments


def metrics(y, p, threshold):
    from sklearn.metrics import average_precision_score, precision_score, recall_score, f1_score, confusion_matrix
    pred = p >= threshold
    return dict(pr_auc=float(average_precision_score(y, p)),
                precision=float(precision_score(y, pred, zero_division=0)),
                recall=float(recall_score(y, pred, zero_division=0)),
                f1=float(f1_score(y, pred, zero_division=0)),
                confusion_matrix_tn_fp_fn_tp=confusion_matrix(y, pred, labels=[0, 1]).ravel().tolist())


def threshold_for(y, p):
    from sklearn.metrics import precision_recall_curve
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2*precision[:-1]*recall[:-1]/np.maximum(precision[:-1]+recall[:-1], 1e-9)
    return float(thresholds[int(np.argmax(f1))])


def dataset_windows(out, protocol='participants', seed=42):
    ds = load_dataset(ROOT / 'data' / 'raw_sessions')
    if ds.issues:
        raise ValueError(f'Dataset load errors: {ds.issues}')
    known = {p for group in PEOPLE.values() for p in group}
    if protocol == 'participants' and {s.person for s in ds.sessions} - known:
        raise ValueError('New participants found; explicitly update PEOPLE split before training')
    assignments = {}
    if protocol == 'sessions':
        # Split original recordings BEFORE windowing, stratified by person and
        # whether that session contains positive labels. Never split a fall's windows.
        assignments = session_split(ds.sessions,seed)
    windows, labels, splits, sources, ends, activities = [], [], [], [], [], []
    ambiguous = collections.Counter()
    skipped_status = 0
    for session in ds.sessions:
        if session.excluded:
            continue
        split = assignments[session.path.name] if protocol == 'sessions' else next(k for k,v in PEOPLE.items() if session.person in v)
        assignments[session.path.name] = split
        with session.path.open(newline='',encoding='utf-8-sig') as handle:
            active = {(float(row['timestamp']),row['target_id']) for row in csv.DictReader(handle)
                      if row.get('status','Active') == 'Active'}
        for track in session.tracks:
            values = track.values[np.array([(float(row[0]),track.target) in active for row in track.values])]
            skipped_status += len(track.values)-len(values)
            buffer = WindowBuffer()
            for row in values:
                t,x,y,s = row[:4]
                w = buffer.push(t, x*1000, y*1000, s*1000)
                if w is None:
                    continue
                grid = np.linspace(t-DURATION, t, POINTS)
                indices = np.searchsorted(values[:,0], grid, side='right')-1
                labs = values[indices,4].astype(int)
                falls = int(np.sum(labs == 6))
                if 0 < falls < 5 or np.any((labs < 1) | (labs > 8)):
                    ambiguous[split] += 1
                    continue
                windows.append(w)
                labels.append(int(falls >= 5))
                splits.append(split)
                sources.append(session.path.name)
                ends.append(t)
                activities.append(int(labs[-1]))
    (out/'dataset_inventory.json').write_text(json.dumps(ds.inventory,indent=2),encoding='utf-8')
    (out/'split.json').write_text(json.dumps(dict(protocol=protocol,
        people={k:sorted({s.person for s in ds.sessions if assignments.get(s.path.name)==k}) for k in PEOPLE},
        session_assignments=assignments, sessions=len(ds.sessions),
        excluded_nonactive_rows=skipped_status,
        ambiguous_windows_excluded=dict(ambiguous), label_rule='Numeric action code 6; >=5 of 21 resampled points positive, zero negative. Retains source labels including known description conflicts.',
        windows_by_split=dict(collections.Counter(splits))),indent=2),encoding='utf-8')
    return np.array(windows), np.array(labels), np.array(splits), np.array(sources), np.array(ends), np.array(activities)


def train_neural(kind, x, y, xv, yv, folder, epochs, seed):
    from sklearn.metrics import average_precision_score
    torch.manual_seed(seed)
    mean = x.reshape(-1,5).mean(0)
    std = np.maximum(x.reshape(-1,5).std(0), 1e-6)
    xt = torch.from_numpy((x-mean)/std)
    vt = torch.from_numpy((xv-mean)/std)
    loader = DataLoader(TensorDataset(xt,torch.tensor(y,dtype=torch.float32)),batch_size=128,shuffle=True)
    model = neural_model(kind)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(float((y==0).sum()/max(y.sum(),1))))
    opt = torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001)
    best, stale, history = -1, 0, []
    for epoch in range(epochs):
        model.train()
        losses = []
        for bx,by in loader:
            opt.zero_grad()
            loss = loss_fn(model(bx), by)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.)
            opt.step()
            losses.append(float(loss.detach()))
        model.eval()
        with torch.inference_mode():
            p = np.concatenate([torch.sigmoid(model(b)).numpy() for b in vt.split(512)])
        ap = float(average_precision_score(yv,p))
        history.append(dict(epoch=epoch+1,train_loss=float(np.mean(losses)),validation_pr_auc=ap))
        print(f'{kind} epoch {epoch+1}: val PR-AUC {ap:.4f}',flush=True)
        if ap > best + .0001:
            best, stale = ap, 0
            torch.save(model.state_dict(),folder/'model.pt')
        else:
            stale += 1
        if stale >= 7:
            break
    np.savez(folder/'scaler.npz',mean=mean,std=std)
    (folder/'learning_curve.json').write_text(json.dumps(history,indent=2),encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--epochs',type=int,default=25)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--negative-cap',type=int,default=2000,help='Training negatives per activity only')
    parser.add_argument('--split',choices=['participants','sessions'],default='participants',
                        help='Unseen people, or whole sessions held out within each person')
    parser.add_argument('--no-publish',action='store_true',help='Save run without changing the default live profile')
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(2)
    base = ROOT/'app'/'ml'/'comparison_weights'
    run = datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+args.split
    out = base/run
    out.mkdir(parents=True,exist_ok=False)
    print(f'Run: {out}',flush=True)
    X,y,split,sources,ends,activities = dataset_windows(out,args.split,args.seed)
    train = np.flatnonzero(split=='train')
    rng = np.random.default_rng(args.seed)
    selected = [train[y[train]==1]]
    for a in np.unique(activities[train]):
        group = train[(y[train]==0)&(activities[train]==a)]
        selected.append(rng.permutation(group)[:args.negative_cap])
    train = np.concatenate(selected)
    rng.shuffle(train)
    val,test = np.flatnonzero(split=='validation'),np.flatnonzero(split=='test')
    assert not (set(sources[train]) & set(sources[val]) or set(sources[train]) & set(sources[test]))
    print('Windows:', {k: (int((split==k).sum()),int(y[split==k].sum())) for k in PEOPLE},flush=True)
    print(f'Training after negative cap: {len(train)} / positives {y[train].sum()}',flush=True)
    results, manifest = {}, []
    versions = {p:importlib.metadata.version(p) for p in ['torch','numpy','scikit-learn','xgboost','aeon','numba','joblib']}
    for kind in NAMES:
        folder = out/kind
        folder.mkdir()
        started = time.perf_counter()
        print(f'Training {kind}',flush=True)
        if kind == 'xgboost':
            from xgboost import XGBClassifier
            model = XGBClassifier(n_estimators=500,max_depth=4,learning_rate=.04,subsample=.85,
                colsample_bytree=.85,reg_lambda=3,min_child_weight=5,n_jobs=2,random_state=args.seed,
                scale_pos_weight=float((y[train]==0).sum()/y[train].sum()),
                eval_metric='aucpr',early_stopping_rounds=40)
            model.fit(summary_features(X[train]), y[train], eval_set=[(summary_features(X[val]),y[val])],verbose=False)
            model.save_model(folder/'model.ubj')
        elif kind == 'minirocket':
            from aeon.transformations.collection.convolution_based import MiniRocket
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            from sklearn.linear_model import LogisticRegression
            import joblib
            transform = MiniRocket(n_kernels=2016,n_jobs=2,random_state=args.seed)
            z = transform.fit_transform(X[train].transpose(0,2,1).copy())
            model = make_pipeline(StandardScaler(),LogisticRegression(C=.1,class_weight='balanced',max_iter=1000,random_state=args.seed))
            model.fit(z,y[train])
            joblib.dump(dict(transform=transform,classifier=model),folder/'model.joblib')
        else:
            train_neural(kind,X[train],y[train],X[val],y[val],folder,args.epochs,args.seed)
        info = dict(kind=kind,name=NAMES[kind],feature_schema=SCHEMA,threshold=.5,versions=versions,protocol=args.split,
                    seed=args.seed,train_windows=len(train),validation_windows=len(val),test_windows=len(test),
                    threshold_method='Maximum window F1 on validation partition only',
                    training_seconds=round(time.perf_counter()-started,2))
        (folder/'metadata.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
        loaded = ArtifactModel(folder)
        pv = np.concatenate([loaded.predict(b) for b in np.array_split(X[val], max(1,len(val)//512))])
        threshold = threshold_for(y[val],pv)
        pt = np.concatenate([loaded.predict(b) for b in np.array_split(X[test], max(1,len(test)//512))])
        loaded.predict(X[test[:1]])
        timings = []
        for _ in range(20):
            tick=time.perf_counter(); loaded.predict(X[test[:1]]); timings.append((time.perf_counter()-tick)*1000)
        info.update(threshold=threshold,validation=metrics(y[val],pv,threshold),test=metrics(y[test],pt,threshold),
                    single_window_latency_ms_median=float(np.median(timings)),single_window_latency_ms_p95=float(np.percentile(timings,95)))
        (folder/'metadata.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
        np.savez_compressed(folder/'test_predictions.npz',score=pt,label=y[test],session=sources[test],timestamp=ends[test])
        results[kind] = info
        manifest.append(dict(id=kind,name=NAMES[kind],path=f'{run}/{kind}'))
        print(json.dumps(info),flush=True)
    (out/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    candidate = base/'manifest.pending.json'
    descriptor = dict(schema=1,run=run,protocol=args.split,created_utc=datetime.now(timezone.utc).isoformat(),
        feature_schema=SCHEMA,models=manifest,split=json.loads((out/'split.json').read_text(encoding='utf-8'))['people'])
    (out/'manifest.json').write_text(json.dumps(descriptor,indent=2),encoding='utf-8')
    if not args.no_publish:
        candidate.write_text(json.dumps(descriptor,indent=2),encoding='utf-8')
        candidate.replace(base/'manifest.json')
        print(f'Published comparison manifest: {base / "manifest.json"}',flush=True)
    else:
        print(f'Saved alternate profile: {out / "manifest.json"}',flush=True)


if __name__ == '__main__':
    main()
