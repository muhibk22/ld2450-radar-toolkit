"""
Post-Fall Confirmation State Machine.

Validates fall alerts from the LSTM by checking whether the target remains
still after the initial detection. This dramatically reduces false positives
from sit-downs, stumbles, and approach/retreat movements.

States:
    NORMAL      → No fall activity
    PRE_ALERT   → LSTM triggered, waiting for stillness confirmation
    CONFIRMED   → Fall confirmed (target stayed still), alert active
    COOLDOWN    → After confirmed fall, prevent duplicate alerts for 30s
"""

import time


# Confirmation window: how long to wait for stillness after LSTM trigger (seconds)
CONFIRM_WINDOW_SECONDS = 3.0

# Speed threshold for "still" during confirmation (mm/s)
STILLNESS_THRESHOLD_MMS = 150.0

# If target moves faster than this during confirmation, cancel the pre-alert (mm/s)
CANCEL_SPEED_MMS = 300.0

# How long to hold a confirmed alert visible (seconds)
CONFIRMED_HOLD_SECONDS = 5.0

# Cooldown between distinct fall events (seconds)
COOLDOWN_SECONDS = 30.0


class PostFallValidator:
    """
    Two-stage fall confirmation:
    
    1. PRE_ALERT: LSTM fires with high probability.
       Start a confirmation window. Monitor target speed.
       
    2. CONFIRMED: During confirmation window, if target speed stays below
       STILLNESS_THRESHOLD_MMS for > 60% of frames → fall confirmed.
       If target speed exceeds CANCEL_SPEED_MMS → false positive, cancel.
       
    3. COOLDOWN: After confirmed fall resolves, prevent re-triggering for 30 seconds.
    """

    def __init__(self):
        self.state = "NORMAL"
        
        # Pre-alert tracking
        self._pre_alert_start: float = 0.0
        self._still_frame_count: int = 0
        self._total_frame_count: int = 0
        
        # Confirmed alert tracking
        self._confirmed_start: float = 0.0
        
        # Cooldown tracking
        self._cooldown_start: float = 0.0
        
        # Alert history for UI display
        self.alert_history: list[dict] = []
    
    def reset(self):
        """Reset state machine (e.g., when switching locked targets)."""
        self.state = "NORMAL"
        self._pre_alert_start = 0.0
        self._still_frame_count = 0
        self._total_frame_count = 0
        self._confirmed_start = 0.0
        self._cooldown_start = 0.0

    def update(self, lstm_triggered: bool, current_speed_mms: float, fall_prob: float) -> str:
        """
        Feed the latest frame's data into the state machine.
        
        Args:
            lstm_triggered: True if the LSTM hysteresis (2 consecutive positives) has fired
            current_speed_mms: Current target speed in mm/s from the tracker
            fall_prob: Raw LSTM fall probability (0.0 - 1.0)
            
        Returns:
            Current state string: "NORMAL", "PRE_ALERT", or "CONFIRMED"
        """
        now = time.time()
        
        if self.state == "NORMAL":
            if lstm_triggered:
                # Transition to PRE_ALERT
                self.state = "PRE_ALERT"
                self._pre_alert_start = now
                self._still_frame_count = 0
                self._total_frame_count = 0
            return self.state
        
        elif self.state == "PRE_ALERT":
            elapsed = now - self._pre_alert_start
            self._total_frame_count += 1
            
            # Track stillness
            if current_speed_mms < STILLNESS_THRESHOLD_MMS:
                self._still_frame_count += 1
            
            # Cancel condition: target moved away quickly (false positive)
            if current_speed_mms > CANCEL_SPEED_MMS and elapsed > 0.5:
                # Target resumed fast movement → this was not a fall
                self._log_event("REJECTED", fall_prob, "Target resumed movement during confirmation")
                self.state = "NORMAL"
                return self.state
            
            # Confirmation condition: enough time passed AND target stayed still
            if elapsed >= CONFIRM_WINDOW_SECONDS:
                stillness_ratio = self._still_frame_count / max(self._total_frame_count, 1)
                if stillness_ratio >= 0.6:
                    # CONFIRMED: target fell and stayed down
                    self.state = "CONFIRMED"
                    self._confirmed_start = now
                    self._log_event("CONFIRMED", fall_prob, f"Stillness ratio: {stillness_ratio:.0%}")
                else:
                    # Not still enough → false positive (e.g., sit-down, stumble)
                    self._log_event("REJECTED", fall_prob, f"Insufficient stillness: {stillness_ratio:.0%}")
                    self.state = "NORMAL"
            
            return self.state
        
        elif self.state == "CONFIRMED":
            elapsed = now - self._confirmed_start
            
            # Hold confirmed alert for CONFIRMED_HOLD_SECONDS
            if elapsed >= CONFIRMED_HOLD_SECONDS:
                self.state = "COOLDOWN"
                self._cooldown_start = now
            
            return self.state
        
        elif self.state == "COOLDOWN":
            elapsed = now - self._cooldown_start
            
            # Prevent re-triggering for COOLDOWN_SECONDS after a confirmed fall
            if elapsed >= COOLDOWN_SECONDS:
                self.state = "NORMAL"
            
            return "NORMAL"  # Show as normal to the UI during cooldown
        
        return self.state
    
    def _log_event(self, event_type: str, probability: float, reason: str):
        """Record an alert event for the history log."""
        self.alert_history.append({
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "type": event_type,
            "probability": round(probability, 4),
            "reason": reason,
        })
        # Keep only the last 50 events
        if len(self.alert_history) > 50:
            self.alert_history = self.alert_history[-50:]
