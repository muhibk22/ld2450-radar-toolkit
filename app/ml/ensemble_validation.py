"""Model-backed confirmation from low motion or disappearance on a healthy stream."""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ValidationConfig:
    observation_seconds: float = 5.0
    settling_seconds: float = 1.0
    still_seconds: float = 2.5
    disappearance_seconds: float = 1.5
    stationary_planar_mms: float = 100.0
    stationary_extent_mm: float = 100.0
    still_radial_mms: float = 150.0
    still_planar_mms: float = 250.0
    position_window_seconds: float = 0.5
    max_gap_seconds: float = 0.5
    confirmed_hold_seconds: float = 5.0
    approach_window_seconds: float = 1.5
    approach_end_before_seconds: float = 0.3
    reversal_earliest_seconds: float = 1.0
    reversal_deadline_seconds: float = 1.25
    reversal_distance_mm: float = 500.0
    reversal_min_approach_mm: float = 250.0
    reversal_heading_cosine: float = -0.5
    reversal_min_coverage: float = 0.8
    reversal_min_straightness: float = 0.8
    reversal_max_sample_gap: float = 0.25

    def __post_init__(self):
        for key,value in self.__dict__.items():
            if not math.isfinite(value) or (key != 'reversal_heading_cosine' and value <= 0):
                raise ValueError('Validation settings must be finite and positive')
        if self.settling_seconds+self.still_seconds > self.observation_seconds:
            raise ValueError('Observation must allow settling plus sustained stillness')
        if not -1 <= self.reversal_heading_cosine < 0:
            raise ValueError('Reversal heading must oppose the approach')
        if not (0 < self.reversal_min_coverage <= 1 and 0 < self.reversal_min_straightness <= 1):
            raise ValueError('Coverage and straightness must be fractions')
        if not self.reversal_earliest_seconds <= self.reversal_deadline_seconds < self.observation_seconds:
            raise ValueError('Reversal rejection must precede the observation deadline')
        if self.approach_end_before_seconds >= self.approach_window_seconds:
            raise ValueError('Approach history must precede the candidate')
        if not self.reversal_deadline_seconds < self.disappearance_seconds <= self.observation_seconds:
            raise ValueError('Disappearance confirmation must follow the reversal check and fit within observation')


def distance(a,b):
    return math.hypot(a[1]-b[1],a[2]-b[2])


class PostConsensusValidator:
    """Reject only early observed reverse travel; otherwise retain uncertainty.

    A suspected result is persistent until acknowledgement, not a confirmed fall.
    """
    def __init__(self, started_at, config=None):
        self.config = config or ValidationConfig()
        self.started_at = started_at
        self.state = 'validating'
        self.reason = 'Checking early reverse travel and fresh low-motion evidence'
        self.warning_kind = ''
        self.confirmed_at = self.resolved_at = None
        self.last_observed = self.first_observed = self.last_input = None
        self.still_since = None
        self.stationary_since = self.stationary_anchor = None
        self.stationary_duration = 0.0
        self.still_duration = self.observed_duration = 0.0
        self.max_radial = self.max_planar = 0.0
        self.absent_since = None
        self.absence_duration = 0.0
        self.confirmation_basis = ''
        self.reversal = {}
        self.samples = deque(maxlen=256)

    def interrupt(self, timestamp, reason, kind='tracking_lost'):
        if self.state == 'validating':
            self.state,self.reason = 'suspected',reason
            self.warning_kind,self.resolved_at = kind,timestamp
            self.still_since = None
            self.still_duration = 0.0

    def _confirm(self,timestamp,basis,reason):
        self.state,self.confirmed_at,self.resolved_at='confirmed',timestamp,timestamp
        self.confirmation_basis,self.reason=basis,reason

    def check_freshness(self, now):
        if self.state != 'validating':
            return
        reference = self.started_at if self.last_observed is None else self.last_observed
        healthy_absence=(self.absent_since is not None and self.last_input is not None
                         and now-self.last_input <= self.config.reversal_max_sample_gap+1e-7)
        if now-reference > self.config.max_gap_seconds+1e-7 and not healthy_absence:
            self.interrupt(now,'Suspected fall: tracking lost; no fresh stillness evidence')
        elif now-self.started_at > self.config.observation_seconds+1e-7:
            self.interrupt(now,'Suspected fall: observation ended without sustained low-motion evidence',
                           'low_motion_unverified')

    def _check_reversal(self, timestamp):
        c = self.config
        elapsed = timestamp-self.started_at
        if not c.reversal_earliest_seconds-1e-7 <= elapsed <= c.reversal_deadline_seconds+1e-7:
            return
        pre = [s for s in self.samples if s[4] and self.started_at-c.approach_window_seconds <= s[0]
               <= self.started_at-c.approach_end_before_seconds]
        post = [s for s in self.samples if s[0] >= self.started_at]
        fresh = [s for s in post if s[4]]
        if len(pre)<2 or len(fresh)<2 or pre[-1][0]-pre[0][0] < .5:
            return
        coverage = sum(b[0]-a[0] for a,b in zip(post,post[1:])
                       if a[4] and b[4] and b[0]-a[0] <= c.reversal_max_sample_gap)/elapsed
        pairs = [(a,b) for a,b in zip(post,post[1:]) if a[4] and b[4]
                 and b[0]-a[0] <= c.reversal_max_sample_gap]
        path = sum(distance(a,b) for a,b in pairs)
        shift,approach = distance(fresh[0],fresh[-1]),distance(pre[0],pre[-1])
        heading = (((pre[-1][1]-pre[0][1])*(fresh[-1][1]-fresh[0][1])+
                    (pre[-1][2]-pre[0][2])*(fresh[-1][2]-fresh[0][2]))/(shift*approach)
                   if shift and approach else 1.0)
        straightness = min(1.0,shift/path) if path else 0.0
        continuous = all(a[4] and b[4] and b[0]-a[0] <= c.reversal_max_sample_gap
                         for a,b in zip(post,post[1:]))
        pre_continuous = all(b[0]-a[0] <= c.reversal_max_sample_gap for a,b in zip(pre,pre[1:]))
        self.reversal = dict(elapsed_s=elapsed,coverage=min(1.0,coverage),displacement_mm=shift,
                             approach_displacement_mm=approach,heading_cosine=heading,
                             straightness=straightness,continuous=continuous)
        if (continuous and pre_continuous and coverage >= c.reversal_min_coverage
                and shift >= c.reversal_distance_mm and approach >= c.reversal_min_approach_mm
                and heading <= c.reversal_heading_cosine and straightness >= c.reversal_min_straightness):
            self.state,self.resolved_at = 'rejected',timestamp
            self.reason = 'Continuous early reverse running after consensus'

    def observe(self, timestamp, x_mm=None, y_mm=None, radial_mms=None, fresh=True,target_absent=False):
        if self.state != 'validating' or (self.last_input is not None and timestamp <= self.last_input):
            return
        if not math.isfinite(timestamp):
            self.interrupt(self.started_at,'Suspected fall: invalid observation timestamp','invalid_observation')
            return
        if fresh and not all(v is not None and math.isfinite(v) for v in (x_mm,y_mm,radial_mms)):
            self.interrupt(timestamp,'Suspected fall: invalid motion observation','invalid_observation')
            return
        if (not fresh and target_absent and self.last_input is not None and self.last_input>=self.started_at
                and timestamp-self.last_input>self.config.max_gap_seconds+1e-7):
            self.interrupt(timestamp,'Suspected fall: radar report stream was interrupted')
            return
        if timestamp >= self.started_at and not (not fresh and target_absent):
            self.check_freshness(timestamp)
            if self.state != 'validating':
                return
        previous = self.samples[-1] if self.samples else None
        self.samples.append((timestamp,x_mm,y_mm,radial_mms,fresh))
        self.last_input = timestamp
        if not fresh:
            self.still_since = None
            self.stationary_since = self.stationary_anchor = None
            self.stationary_duration=0.0
            self.still_duration = 0.0
            if target_absent and timestamp >= self.started_at:
                if self.absent_since is None or previous is None or timestamp-previous[0]>self.config.reversal_max_sample_gap:
                    self.absent_since=timestamp
                self.absence_duration=timestamp-self.absent_since
                if self.absence_duration >= self.config.disappearance_seconds-1e-7:
                    self._confirm(timestamp,'post_fall_disappearance',
                                  'Model-backed fall: target disappeared while valid radar reports continued')
                elif timestamp-self.started_at >= self.config.observation_seconds:
                    self.interrupt(timestamp,'Suspected fall: disappearance observation was inconclusive','low_motion_unverified')
            else:
                self.absent_since=None
                self.absence_duration=0.0
            return
        self.absent_since=None
        self.absence_duration=0.0
        self.last_observed = timestamp
        if timestamp < self.started_at:
            return
        if self.first_observed is None:
            self.first_observed = timestamp
        if previous and previous[4] and timestamp-previous[0] <= self.config.reversal_max_sample_gap:
            self.observed_duration += max(0.0,timestamp-max(previous[0],self.started_at))
        self.max_radial = max(self.max_radial,abs(radial_mms))
        self._check_reversal(timestamp)
        if self.state != 'validating':
            return
        recent = [s for s in self.samples if timestamp-self.config.position_window_seconds <= s[0] <= timestamp]
        continuous = (len(recent)>1 and all(s[4] for s in recent) and
                      all(b[0]-a[0] <= self.config.reversal_max_sample_gap for a,b in zip(recent,recent[1:])))
        duration = timestamp-recent[0][0]
        # Path length prevents a back-and-forth motion from cancelling to zero.
        planar = (sum(distance(a,b) for a,b in zip(recent,recent[1:]))/duration
                  if continuous and duration>=.25 else None)
        if planar is not None:
            self.max_planar = max(self.max_planar,planar)
        elapsed = timestamp-self.started_at
        extent=max((distance(recent[0],s) for s in recent),default=0) if continuous else float('inf')
        stationary=(elapsed >= self.config.settling_seconds-1e-7 and planar is not None and planar<=self.config.stationary_planar_mms
                    and extent<=self.config.stationary_extent_mm)
        if stationary:
            point=(timestamp,x_mm,y_mm)
            if self.stationary_anchor is None or distance(self.stationary_anchor,point)>self.config.stationary_extent_mm:
                self.stationary_anchor=point
                self.stationary_since=timestamp
            self.stationary_duration=timestamp-self.stationary_since
        else:
            self.stationary_since=self.stationary_anchor=None
            self.stationary_duration=0.0
        still = (elapsed >= self.config.settling_seconds-1e-7 and planar is not None and
                 abs(radial_mms) <= self.config.still_radial_mms and planar <= self.config.still_planar_mms)
        if still and self.still_since is None:
            self.still_since = timestamp
        elif not still:
            self.still_since = None
        self.still_duration = timestamp-self.still_since if self.still_since is not None else 0.0
        if self.still_duration >= self.config.still_seconds-1e-7 and elapsed > self.config.reversal_deadline_seconds:
            self._confirm(timestamp,'fresh_low_motion','Fresh observations show sustained low motion after consensus')
        elif self.stationary_duration >= self.config.still_seconds-1e-7 and elapsed > self.config.reversal_deadline_seconds:
            self._confirm(timestamp,'stable_centroid','Model-backed fall: centroid remained stationary despite the radial-speed estimate')
        elif elapsed >= self.config.observation_seconds-1e-7:
            self.interrupt(timestamp,'Suspected fall: observation ended without sustained low-motion evidence',
                           'low_motion_unverified')

    def snapshot(self):
        last = self.last_observed if self.last_observed is not None else self.started_at
        return dict(state=self.state,reason=self.reason,warning_kind=self.warning_kind,
                    started_at=self.started_at,confirmed_at=self.confirmed_at,resolved_at=self.resolved_at,
                    observation_seconds=self.config.observation_seconds,
                    elapsed_s=max(0.0,last-self.started_at),observed_seconds=self.observed_duration,
                    still_seconds=self.still_duration,reversal=dict(self.reversal),
                    absence_seconds=self.absence_duration,confirmation_basis=self.confirmation_basis,
                    stationary_seconds=self.stationary_duration,
                    max_radial_speed_mms=self.max_radial,max_planar_speed_mms=self.max_planar)
