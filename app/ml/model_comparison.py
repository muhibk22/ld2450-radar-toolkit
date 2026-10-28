"""Non-blocking five-model comparison; legacy deployed LSTM is retired.

Only fresh model outputs advance detection hysteresis. All trained challengers
share a trailing window; target changes/gaps invalidate in-flight predictions.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
import copy
import threading
from functools import wraps
from collections import deque

import numpy as np
from .comparison_features import WindowBuffer
from .ensemble_validation import PostConsensusValidator, ValidationConfig

MODEL_NAMES = {'xgboost': 'XGBoost', 'minirocket': 'MiniROCKET', 'tcn': 'TCN',
               'gru': 'GRU', 'lstm': 'LSTM (retrained)'}


def synchronized(method):
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with self.lock:
            return method(self,*args,**kwargs)
    return wrapped


@dataclass
class DetectionState:
    positives: int = 0
    negatives: int = 0
    armed: bool = True
    last_detection: float = -float('inf')

    def update(self, timestamp, positive):
        if positive:
            self.positives += 1
            self.negatives = 0
            if self.positives >= 2 and self.armed:
                self.armed = False
                self.last_detection = timestamp
                return True
        else:
            self.positives = 0
            self.negatives += 1
            if self.negatives >= 2 and timestamp - self.last_detection >= 5:
                self.armed = True
        return False


class ModelComparison:
    def __init__(self, base=None, executor=None, autoload=True, validation_config=None):
        self.lock = threading.RLock()
        self.base = Path(base) if base else Path(__file__).parent/'comparison_weights'
        self.manifest_path = self.base/'manifest.json'
        self.profile = self._profile_label(self.manifest_path)
        self.executor = executor or ThreadPoolExecutor(max_workers=1,thread_name_prefix='fall-comparison')
        self.models = {}
        self.rows = {}
        self.rows.update({k:dict(name=v,score=None,threshold=None,status='Loading',last_detection=None) for k,v in MODEL_NAMES.items()})
        self.events = []
        self.event_sequence = 0
        self.revision = 0
        self.target = None
        self.generation = 0
        self.buffer = WindowBuffer()
        self.states = {}
        self.last_sample = None
        self.last_report = None
        self.pending = None
        self.future = None
        self.loading = None
        self.started = False
        self.closed = False
        self.skipped_windows = 0
        self.last_latency_ms = None
        self.validation_config = validation_config or ValidationConfig()
        self.motion_samples = deque(maxlen=128)
        self.validator = self.validation_event = None
        self.message = 'Loading comparison models in the background'
        if autoload:
            self.start()
        else:
            self.message = 'Lock a target to load and compare models'

    @synchronized
    def start(self):
        if not self.started and not self.closed:
            self.started = True
            self.loading = self.executor.submit(self._load,self.manifest_path)

    @staticmethod
    def _profile_label(path):
        try:
            info = json.loads(Path(path).read_text(encoding='utf-8'))
            protocol = info.get('protocol','participants')
            label = 'Within-person sessions' if protocol == 'sessions' else 'Unseen participants'
            return f"{label} ({info['run']})"
        except (OSError,ValueError,KeyError):
            return 'Default comparison models'

    @synchronized
    def select_profile(self, manifest_path):
        path = Path(manifest_path).resolve()
        if not path.is_relative_to(self.base.resolve()):
            raise ValueError('Profile must be inside comparison_weights')
        self.manifest_path = path
        self.profile = self._profile_label(path)
        self._invalidate(None,'Loading selected model profile')
        self.models = {}
        for key in MODEL_NAMES:
            self.rows[key].update(status='Loading',threshold=None,score=None,last_detection=None)
            self.rows[key].pop('error',None)
        self.started = False
        self.start()

    def _load(self, manifest_path=None):
        import torch
        from .comparison_models import ArtifactModel
        torch.set_num_threads(1)
        models, errors = {}, {}
        try:
            manifest = json.loads((manifest_path or self.manifest_path).read_text(encoding='utf-8'))
            if manifest.get('schema') != 1:
                raise ValueError('Unsupported comparison manifest')
        except Exception as exc:
            return {}, {k:str(exc) for k in MODEL_NAMES}
        entries = {entry['id']:entry for entry in manifest['models']}
        for key in MODEL_NAMES:
            try:
                directory = (self.base/entries[key]['path']).resolve()
                if not directory.is_relative_to(self.base.resolve()):
                    raise ValueError('Artifact path escapes comparison directory')
                model = ArtifactModel(directory)
                model.predict(np.zeros((1,21,5),dtype=np.float32))  # warm numba/torch off UI thread
                models[key] = model
            except Exception as exc:
                errors[key] = str(exc)
        return models, errors

    def _invalidate(self, target, message, kind='context_changed', timestamp=None):
        if self.validator:
            self.validator.interrupt(time.time() if timestamp is None else timestamp, 'Suspected fall: '+message, kind)
            self._publish_validation()
        self.validator = self.validation_event = None
        self.motion_samples.clear()
        self.target = target
        self.generation += 1
        self.buffer.reset()
        self.states = {k:DetectionState() for k in self.models}
        self.pending = None
        self.last_sample = None
        self.last_report = None
        self.message = message
        for key,row in self.rows.items():
            row['score'] = None
            if key in self.models:
                row['status'] = 'Warming up' if target else 'Waiting for target'
        self.revision += 1

    @synchronized
    def feed(self, target, timestamp, x_mm=0, y_mm=0, speed_mms=0,
             validation_x_mm=None, validation_y_mm=None):
        if self.closed:
            return
        self.poll()
        if target != self.target:
            self._invalidate(target, 'Collecting 2 seconds of motion' if target else 'Lock a confirmed target to compare models')
        if target is None:
            return
        self.start()
        if self.last_sample is not None and timestamp <= self.last_sample:
            return
        if self.last_sample is not None and timestamp-self.last_sample > .5:
            self._invalidate(target, 'Recording gap: collecting a new window', 'tracking_lost')
        self.last_sample = timestamp
        self.last_report = timestamp
        observation = (timestamp, x_mm if validation_x_mm is None else validation_x_mm,
                       y_mm if validation_y_mm is None else validation_y_mm, speed_mms, True,False)
        self.motion_samples.append(observation)
        if self.validator:
            self.validator.observe(*observation)
            self._publish_validation()
        window = self.buffer.push(timestamp,x_mm,y_mm,speed_mms)
        if window is not None and self.models:
            if self.pending is not None:
                self.skipped_windows += 1
            self.pending = (self.generation, target, timestamp, window)
            self._dispatch()
        self.revision += 1

    @synchronized
    def tracking_unavailable(self, timestamp,target_absent=False):
        """Only a valid report with no eligible raw target may set target_absent.

        Held/ambiguous data contributes no stillness. True reported absence can
        support the separate post-consensus disappearance confirmation path.
        """
        observation = (timestamp,None,None,None,False,target_absent)
        if not self.closed and (not self.motion_samples or timestamp > self.motion_samples[-1][0]):
            self.last_report=timestamp
            self.motion_samples.append(observation)
            if self.validator:
                self.validator.observe(*observation)
                self._publish_validation()

    @synchronized
    def acknowledge_warnings(self, event_id=None):
        """Explicit review clears warnings without deleting their history."""
        for event in self.events:
            if (event_id is None or event['id'] == event_id) and event.get('validation',{}).get('state') == 'suspected':
                event['acknowledged_at'] = time.time()
                self.revision += 1

    def _record(self, key, timestamp, score, stage='detected'):
        event = next((e for e in reversed(self.events) if e['generation']==self.generation
                      and e['target']==self.target and abs(timestamp-e['timestamp']) <= 8),None)
        if event is None:
            self.event_sequence += 1
            event = dict(id=self.event_sequence,target=self.target,generation=self.generation,
                         timestamp=timestamp,profile=self.profile,detections={},acknowledged_at=None,
                         validation=dict(state='awaiting_votes',reason='Requires four model votes',
                                         confirmed_at=None))
            self.events.append(event)
            # Reviewable warnings must not disappear when ordinary history rotates.
            self.events = [e for i,e in enumerate(self.events) if i >= len(self.events)-200 or
                           (e.get('validation',{}).get('state') == 'suspected' and e.get('acknowledged_at') is None)]
        if key not in event['detections']:
            event['timestamp'] = min(event['timestamp'],timestamp)
            event['detections'][key] = dict(timestamp=timestamp,score=score,stage=stage,processed_at=time.time())
            self.rows[key]['last_detection'] = timestamp
        if len(event['detections']) >= 4 and event['validation']['state'] == 'awaiting_votes':
            # Window-end timestamps, not GUI/poll arrival times, start validation.
            consensus_at = sorted(d['timestamp'] for d in event['detections'].values())[3]
            self.validator = PostConsensusValidator(consensus_at, self.validation_config)
            self.validation_event = event
            for observation in self.motion_samples:
                if observation[0] >= consensus_at-self.validation_config.approach_window_seconds:
                    self.validator.observe(*observation)
            self._publish_validation()
        self.revision += 1
        return event

    def _publish_validation(self):
        if self.validator and self.validation_event is not None:
            snapshot = self.validator.snapshot()
            if self.validation_event['validation'] != snapshot:
                self.validation_event['validation'] = snapshot
                self.revision += 1

    def _predict(self, item, models):
        generation,target,timestamp,window = item
        started = time.perf_counter()
        results = {}
        for key,model in models.items():
            try:
                results[key] = dict(score=float(model.predict(window[None])[0]))
            except Exception as exc:
                results[key] = dict(error=str(exc))
        return generation,target,timestamp,results,(time.perf_counter()-started)*1000

    def _dispatch(self):
        if self.future is None and self.pending is not None and not self.closed:
            item, self.pending = self.pending, None
            self.future = self.executor.submit(self._predict,item,dict(self.models))

    @synchronized
    def poll(self, now=None):
        if self.closed:
            return
        now = time.time() if now is None else now
        if self.loading is not None and self.loading.done():
            try:
                self.models,errors = self.loading.result()
            except Exception as exc:
                self.models,errors = {},{k:str(exc) for k in MODEL_NAMES}
            self.loading = None
            for key,model in self.models.items():
                self.rows[key].update(threshold=model.info['threshold'],status='Warming up' if self.target else 'Waiting for target')
            for key,error in errors.items():
                self.rows[key].update(status='Unavailable',error=error)
            self.states = {k:DetectionState() for k in self.models}
            self.message = f'{len(self.models)}/{len(MODEL_NAMES)} comparison models loaded. Lock a target to compare.'
            self.revision += 1
        if self.future is not None and self.future.done():
            try:
                generation,target,timestamp,results,latency = self.future.result()
                if generation == self.generation and target == self.target and now-timestamp <= 1.0:
                    self.last_latency_ms = latency
                    for key,result in results.items():
                        row = self.rows[key]
                        if 'error' in result:
                            row.update(score=None,status='Error',error=result['error'])
                            self.states[key] = DetectionState()
                            continue
                        score = result['score']
                        positive = score >= row['threshold']
                        detected = self.states[key].update(timestamp,positive)
                        row.update(score=score,status='Above threshold' if positive else 'Below threshold')
                        if detected:
                            self._record(key,timestamp,score)
                            row['status'] = 'Detected'
                    self.message = f'Target {target} | comparison inference {latency:.1f} ms | skipped windows {self.skipped_windows}'
                    self.revision += 1
                elif generation == self.generation:
                    self.states = {k:DetectionState() for k in self.models}
                    self.message = 'Inference delayed: discarded a stale result'
                    for key in self.models:
                        self.rows[key].update(score=None,status='Delayed')
                    self.revision += 1
            except Exception as exc:
                self.message = f'Comparison worker error: {exc}'
                self.revision += 1
            self.future = None
        if self.target is not None and self.last_sample is not None and now-self.last_sample > .5:
            healthy_absence=(self.validator is not None and self.validator.absent_since is not None
                             and self.last_report is not None and now-self.last_report <= .25)
            if not healthy_absence:
                self._invalidate(None,'Tracking lost; no fresh target observations', 'tracking_lost',timestamp=now)
        if self.validator:
            self.validator.check_freshness(now)
            self._publish_validation()
        self._dispatch()

    @synchronized
    def get_ensemble_status(self, now=None):
        """Warnings survive inference resets and target loss until reviewed."""
        now = time.time() if now is None else now
        warnings = [e for e in self.events if e.get('validation',{}).get('state') == 'suspected'
                    and e.get('acknowledged_at') is None]
        current = next((e for e in reversed(self.events)
                        if ((e.get('generation') == self.generation and e.get('target') == self.target
                             and e['timestamp'] <= now <= e['timestamp']+10)
                            or (e.get('validation',{}).get('state') == 'confirmed'
                                and 0 <= now-e['validation']['confirmed_at'] <= self.validation_config.confirmed_hold_seconds))
                        and not e.get('acknowledged_at')),None)
        active = current
        # An old warning must not hide a new validating/confirmed candidate.
        validation = current.get('validation',{}) if current else {}
        live_confirmation = (current is not None and validation.get('state') == 'confirmed'
                             and now-(validation.get('confirmed_at') or 0) <= self.validation_config.confirmed_hold_seconds)
        if warnings and not (validation.get('state') == 'validating' or live_confirmation):
            active = warnings[-1]
        brief_warnings = [dict(event_id=e['id'],target=e['target'],timestamp=e['timestamp'],
                               reason=e['validation']['reason'],warning_kind=e['validation'].get('warning_kind',''))
                          for e in warnings]
        result = dict(fall_alert=False,suspected=False,stage='normal',votes=0,required_votes=4,
                      total_models=len(MODEL_NAMES),voting_models=[],avg_score=0.0,max_score=0.0,
                      event_id=None,event_timestamp=None,elapsed_s=0.0,validation={},target=None,
                      applies_to_current_target=False,warnings=brief_warnings,warning_count=len(warnings))
        if active is None:
            return result
        detections = {k:v for k,v in active['detections'].items() if k in MODEL_NAMES}
        scores = [d['score'] for d in detections.values()]
        validation = active.get('validation',{})
        matches = active['generation'] == self.generation and active['target'] == self.target
        fresh = matches and self.last_sample is not None and now-self.last_sample <= self.validation_config.max_gap_seconds
        confirmed_at = validation.get('confirmed_at')
        alert = (len(detections)>=4 and validation.get('state') == 'confirmed'
                 and confirmed_at is not None and now-confirmed_at <= self.validation_config.confirmed_hold_seconds)
        stage = validation.get('state','normal')
        if stage == 'validating':
            stage = 'pre_alert'
        elif stage == 'confirmed' and not alert:
            stage = 'normal'
        elif stage == 'awaiting_votes':
            stage = 'normal'
        result.update(fall_alert=alert,suspected=stage in ('pre_alert','suspected'),stage=stage,
                      votes=len(detections),voting_models=list(detections),
                      avg_score=float(np.mean(scores)) if scores else 0.0,
                      max_score=max(scores) if scores else 0.0,event_id=active['id'],
                      event_timestamp=active['timestamp'],elapsed_s=now-active['timestamp'],
                      validation=copy.deepcopy(validation),target=active['target'],
                      applies_to_current_target=matches)
        return result

    @synchronized
    def reset_stream(self):
        self._invalidate(None, 'Waiting for fresh radar observations')

    @synchronized
    def snapshot(self):
        return copy.deepcopy(dict(rows=self.rows, events=self.events, message=self.message,
            revision=self.revision, profile=self.profile, ensemble=self.get_ensemble_status()))

    @synchronized
    def close(self):
        self.closed = True
        self.pending = None
        self.executor.shutdown(wait=False,cancel_futures=True)


def time_label(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3] if timestamp is not None else '\u2014'
