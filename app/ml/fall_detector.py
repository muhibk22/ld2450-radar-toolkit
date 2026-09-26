import collections
import time
import os
import numpy as np
import torch
import torch.nn as nn

# Model parameters
HIDDEN_DIM = 64
WINDOW_LEN = 20
PREDICT_EVERY = 5
FALL_PROB_THRESHOLD = 0.5

# Unit conversions for LD2450 to Model space
MM_TO_M = 1 / 1000.0

# Velocity EMA smoothing factor (0 = no smoothing, 1 = no memory)
VELOCITY_EMA_ALPHA = 0.3

# Physics pre-screening thresholds
MIN_SPEED_FOR_FALL = 0.35       # m/s - minimum max speed in window to consider fall
MIN_DISPLACEMENT_FOR_FALL = 0.25 # m - minimum net displacement in window
MIN_VEL_Y_FOR_FALL = 0.4        # m/s - minimum Y-velocity magnitude to consider fall event
APPROACH_RETREAT_RATIO = 3.0     # If |vel_y| / |vel_x| > this ratio, apply penalty


class LSTMAttention(nn.Module):
    def __init__(self, n_features, hidden_dim=HIDDEN_DIM):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden_dim, batch_first=True, bidirectional=True)
        self.attn = nn.Linear(hidden_dim * 2, 1)
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim * 2, 32),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        lstm_out, _ = self.lstm(x)                       
        attn_scores = self.attn(lstm_out).squeeze(-1)     
        attn_weights = torch.softmax(attn_scores, dim=1)  
        context = torch.sum(lstm_out * attn_weights.unsqueeze(-1), dim=1) 
        logits = self.classifier(context).squeeze(-1)     
        return logits

class FallDetector:
    """
    Wraps the PyTorch LSTMAttention model to provide real-time fall detection
    for a continuously tracked target.
    
    Includes:
    - Velocity EMA smoothing to suppress single-frame jitter
    - Physics pre-screening to skip inference when no significant motion detected
    - Approach/retreat penalty to reduce false positives from Y-axis-dominant movement
    """
    def __init__(self, model_dir: str):
        # model_dir now points to app/ml/weights
        self.mean = np.load(os.path.join(model_dir, "feature_mean.npy"))
        self.std = np.load(os.path.join(model_dir, "feature_std.npy"))
        n_features = len(self.mean)
        
        self.device = torch.device("cpu")
        self.model = LSTMAttention(n_features)
        
        weights_path = os.path.join(model_dir, "fall_lstm_baseline.pt")
        self.model.load_state_dict(torch.load(weights_path, map_location=self.device))
        self.model.eval()
        
        self.buffer = collections.deque(maxlen=WINDOW_LEN)
        self.frame_count = 0
        
        self.prev_x = None
        self.prev_y = None
        self.prev_t = None
        
        # EMA-smoothed velocity state
        self._ema_vel_x = 0.0
        self._ema_vel_y = 0.0
        
        self.current_prob = 0.0

    def reset_buffer(self):
        """Clears the sliding window buffer when switching locked targets."""
        self.buffer.clear()
        self.frame_count = 0
        self.prev_x = None
        self.prev_y = None
        self.prev_t = None
        self._ema_vel_x = 0.0
        self._ema_vel_y = 0.0
        self.current_prob = 0.0

    def update(self, x_mm: float, y_mm: float, speed_mms: float) -> float:
        """
        Takes raw millimeter measurements from LD2450, converts to meters,
        computes EMA-smoothed velocity vectors, and runs inference every N frames.
        Returns the latest fall probability (0.0 to 1.0).
        """
        x = x_mm * MM_TO_M
        y = y_mm * MM_TO_M
        speed = speed_mms * MM_TO_M # mm/s to m/s
        now = time.time()
        
        if self.prev_x is not None and self.prev_y is not None and self.prev_t is not None:
            # Clamp dt to [0.07, 0.15] (nominal 10Hz) to prevent socket packet bursts from generating fake velocity spikes
            dt = float(np.clip(now - self.prev_t, 0.07, 0.15))
            # Bound velocity to realistic human kinematics (max 3.5 m/s) to prevent tracking jump glitches from triggering falls
            raw_vx = (x - self.prev_x) / dt
            raw_vy = (y - self.prev_y) / dt
            clamped_vx = float(np.clip(raw_vx, -3.5, 3.5))
            clamped_vy = float(np.clip(raw_vy, -3.5, 3.5))
            
            # EMA smoothing: suppresses single-frame jitter while preserving fall dynamics
            vel_x = VELOCITY_EMA_ALPHA * clamped_vx + (1 - VELOCITY_EMA_ALPHA) * self._ema_vel_x
            vel_y = VELOCITY_EMA_ALPHA * clamped_vy + (1 - VELOCITY_EMA_ALPHA) * self._ema_vel_y
            self._ema_vel_x = vel_x
            self._ema_vel_y = vel_y
        else:
            vel_x, vel_y = 0.0, 0.0
            
        self.prev_x, self.prev_y, self.prev_t = x, y, now
        
        self.buffer.append([x, y, vel_x, vel_y, speed])
        self.frame_count += 1
        
        if len(self.buffer) == WINDOW_LEN and self.frame_count % PREDICT_EVERY == 0:
            arr = np.array(self.buffer, dtype=np.float32)
            
            # ========== PHYSICS PRE-SCREENING GATE ==========
            # Skip expensive LSTM inference when motion patterns clearly cannot be a fall.
            # This eliminates the majority of false positives from stationary/slow movement.
            
            max_speed = float(np.max(np.abs(arr[:, 4])))
            displacement = float(np.hypot(arr[-1, 0] - arr[0, 0], arr[-1, 1] - arr[0, 1]))
            max_abs_vel_y = float(np.max(np.abs(arr[:, 3])))
            max_abs_vel_x = float(np.max(np.abs(arr[:, 2])))
            
            # Gate 1: Stationary / minimal motion → definitely not a fall
            if max_speed < MIN_SPEED_FOR_FALL and displacement < MIN_DISPLACEMENT_FOR_FALL:
                self.current_prob = 0.01
                return self.current_prob
            
            # Gate 2: No significant Y-velocity AND low overall speed → not a fall
            # Falls require a rapid vertical (depth) change which manifests as Y-velocity
            if max_abs_vel_y < MIN_VEL_Y_FOR_FALL and max_speed < 0.5:
                self.current_prob = 0.02
                return self.current_prob

            # Convert absolute x, y into position-invariant relative displacement from window start
            arr[:, 0] = arr[:, 0] - arr[0, 0]
            arr[:, 1] = arr[:, 1] - arr[0, 1]
            
            arr = (arr - self.mean) / self.std
            tensor_in = torch.tensor(arr, dtype=torch.float32).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                logit = self.model(tensor_in)
                raw_prob = torch.sigmoid(logit).item()
            
            # Gate 3: Approach/retreat penalty
            # If movement is predominantly along Y-axis (toward/away from sensor) with minimal
            # X-axis change, this is likely a person walking toward/away rather than falling.
            # The LD2450 conflates approach velocity with downward movement in its 2D projection.
            if max_abs_vel_x > 0.05:  # Avoid division by zero
                y_to_x_ratio = max_abs_vel_y / max_abs_vel_x
                if y_to_x_ratio > APPROACH_RETREAT_RATIO:
                    # Apply penalty: scale probability down by 40%
                    raw_prob *= 0.6
            
            self.current_prob = raw_prob
                
        return self.current_prob
