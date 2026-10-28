"""Worker-owned ingestion and a bounded latest-state handoff to the GUI."""
from collections import deque
from dataclasses import replace
import threading
import time
from .parser.packet_parser import PacketParser
from .parser.packet_decoder import PacketDecoder
from .tracker.tracker import TargetTracker


class LivePipeline:
    def __init__(self, comparison=None, recorder=None, period=.1):
        self.lock = threading.RLock()
        self.parser, self.decoder = PacketParser(), PacketDecoder()
        self.tracker = TargetTracker()
        self.comparison, self.recorder = comparison, recorder
        self.period = period
        self.session = self.frames = self.revision = 0
        self.last_frame = self.last_byte = self.last_sample = None
        self.targets = []
        self.target_seen = {}
        self.clock_anchor = None
        self.packets = deque(maxlen=60)
        self.chunks = deque(maxlen=60)
        self.bytes_pending = self.overwritten_previews = 0

    def reset(self):
        with self.lock:
            self.session += 1
            self.parser, self.decoder = PacketParser(), PacketDecoder()
            self.tracker.reset()
            self.targets = []
            self.target_seen.clear()
            self.clock_anchor = None
            self.packets.clear(); self.chunks.clear()
            self.bytes_pending = 0
            self.last_frame = self.last_byte = self.last_sample = None
            if self.comparison:
                self.comparison.reset_stream()
            self.revision += 1

    def configure(self, settings=None, target=None, set_target=False):
        with self.lock:
            if settings:
                self.tracker.apply_tuning_settings(settings)
            if set_target:
                self.tracker.set_target_lock(target)
                if self.comparison:
                    self.comparison.reset_stream()

    def set_noise_zones(self,records):
        with self.lock:
            removed=self.tracker.set_noise_zones(records)
            self._remove_noise_tracks(removed)

    def mark_noise(self,target_id,radius_mm=300):
        with self.lock:
            if self.last_frame is None or time.monotonic()-self.last_frame>.6:
                raise ValueError('Wait for a fresh radar observation before marking noise')
            zone,removed=self.tracker.mark_noise(target_id,radius_mm)
            self._remove_noise_tracks(removed)
            return zone

    def _remove_noise_tracks(self,removed):
        self.targets=[t for t in self.targets if str(t.id) not in removed]
        for label in removed:
            self.target_seen.pop(label,None)
        if self.comparison and self.comparison.target in removed:
            self.comparison.reset_stream()
        self.revision+=1

    def noise_zones(self):
        with self.lock:
            return [z.to_dict() for z in self.tracker.noise_zones]

    def ingest(self, data, now=None, received=None):
        received = time.monotonic() if received is None else received
        with self.lock:
            if now is None:
                if self.clock_anchor is None:
                    self.clock_anchor = (time.time(),received)
                now = self.clock_anchor[0] + received-self.clock_anchor[1]
            self.last_byte = received
            if len(self.chunks) == self.chunks.maxlen:
                self.bytes_pending -= len(self.chunks[0])
            preview = bytes(data[-16384:])
            self.chunks.append(preview); self.bytes_pending += len(preview)
            while self.bytes_pending > 16384 and len(self.chunks) > 1:
                self.bytes_pending -= len(self.chunks.popleft())
            frames, _ = self.parser.parse_stream(data)
            packets = [self.decoder.decode(f) for f in frames]
            packets = [p for p in packets if p.valid]
            if not packets:
                return 0
            # TCP has no capture timestamps. Reconstruct a short batch at the
            # configured sensor period, anchored to receipt; discard long backlog.
            if len(packets) > 5:
                self.overwritten_previews += len(packets)-5
                packets = packets[-5:]
                self.tracker.reset()
                self.last_sample = None
                if self.comparison:
                    self.comparison.reset_stream()
            start = now - (len(packets)-1)*self.period
            if self.last_sample is not None:
                while packets and start <= self.last_sample:
                    packets.pop(0)
                    start += self.period
                if not packets:
                    self.last_frame = received
                    return len(frames)
            for index, pkt in enumerate(packets):
                timestamp = start + index*self.period
                pkt.timestamp = timestamp
                targets = self.tracker.process(pkt.targets, timestamp=timestamp)
                self.frames += 1
                self.last_sample = timestamp
                self.packets.append(pkt)
                self.targets = [replace(t) for t in targets]
                for target in self.targets:
                    if target.status == 'Active':
                        self.target_seen[str(target.id)] = received
                self._feed_models(timestamp)
                if self.comparison:
                    ensemble = self.comparison.get_ensemble_status()
                    for target in self.targets:
                        if ensemble['applies_to_current_target'] and str(target.id) == ensemble['target']:
                            target.fall_alert = ensemble['fall_alert']
                            target.fall_votes = ensemble['votes']
                            target.fall_prob = ensemble['avg_score']
                            target.fall_alert_stage = ensemble['stage']
                if self.recorder and self.recorder.is_recording:
                    self.recorder.record_frame(self.frames, self.targets, timestamp=timestamp)
            self.last_frame = received
            self.revision += 1
            return len(packets)

    def _feed_models(self, timestamp):
        if not self.comparison:
            return
        candidates = [t for t in self.targets if t.status == 'Active'
                      and self.tracker.tracked_persons.get(str(t.id))
                      and self.tracker.tracked_persons[str(t.id)].confirmed]
        if self.tracker.locked_target_id:
            candidates = [t for t in candidates if str(t.id) == self.tracker.locked_target_id]
        if len(candidates) == 1:
            t = candidates[0]
            person = self.tracker.tracked_persons[str(t.id)]
            x, y = person.model_position  # original 10-sample smoothing, independent of display
            # Validation uses the accepted measurement before visual/model averaging.
            observed_x, observed_y = person.model_window[-1]
            self.comparison.feed(str(t.id), timestamp, x, y, t.speed,
                                 validation_x_mm=observed_x, validation_y_mm=observed_y)
        else:
            self.comparison.tracking_unavailable(timestamp,
                target_absent=not self.tracker.last_eligible_measurements)

    def drain(self, preview=True):
        if not self.lock.acquire(blocking=False):
            return None
        try:
            return self._snapshot(preview)
        finally:
            self.lock.release()

    def _snapshot(self, preview):
        with self.lock:
            now = time.monotonic()
            stale = self.last_frame is None or now-self.last_frame > .6
            result = dict(session=self.session,revision=self.revision,frames=self.frames,
                          targets=[] if stale else [replace(t) for t in self.targets
                              if now-self.target_seen.get(str(t.id),-float('inf')) <= .6],
                          packets=list(self.packets),chunks=list(self.chunks),
                          stats=self.parser.get_statistics(),
                          frame_age_s=None if self.last_frame is None else now-self.last_frame,
                          byte_age_s=None if self.last_byte is None else now-self.last_byte,
                          skipped_preview_frames=self.overwritten_previews)
            result['noise_zones']=[z.to_dict() for z in self.tracker.noise_zones]
            if preview:
                self.packets.clear(); self.chunks.clear(); self.bytes_pending=0
            return result
