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
        
        self.current_prob = 0.0

    def reset_buffer(self):
        """Clears the sliding window buffer when switching locked targets."""
        self.buffer.clear()
        self.frame_count = 0
        self.prev_x = None
        self.prev_y = None
        self.prev_t = None
        self.current_prob = 0.0

    def update(self, x_mm: float, y_mm: float, speed_mms: float) -> float:
        """
        Takes raw millimeter measurements from LD2450, converts to meters,
        computes velocity vectors, and runs inference every N frames.
        Returns the latest fall probability (0.0 to 1.0).
        """
        x = x_mm * MM_TO_M
        y = y_mm * MM_TO_M
        speed = speed_mms * MM_TO_M # mm/s to m/s
        now = time.time()
        
        if self.prev_x is not None:
            dt = max(now - self.prev_t, 1e-3)
            vel_x = (x - self.prev_x) / dt
            vel_y = (y - self.prev_y) / dt
        else:
            vel_x, vel_y = 0.0, 0.0
            
        self.prev_x, self.prev_y, self.prev_t = x, y, now
        
        self.buffer.append([x, y, vel_x, vel_y, speed])
        self.frame_count += 1
        
        if len(self.buffer) == WINDOW_LEN and self.frame_count % PREDICT_EVERY == 0:
            arr = np.array(self.buffer, dtype=np.float32)
            arr = (arr - self.mean) / self.std
            tensor_in = torch.tensor(arr, dtype=torch.float32).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                logit = self.model(tensor_in)
                self.current_prob = torch.sigmoid(logit).item()
                
        return self.current_prob
