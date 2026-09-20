import os
import glob
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import sys

# Import the model from the app
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.ml.fall_detector import LSTMAttention

MM_TO_M = 1 / 1000.0

class RadarWindowDataset(Dataset):
    def __init__(self, windows, labels):
        self.windows = windows # list of (20, 5) numpy arrays
        self.labels = labels   # list of binary ints (0 or 1)
        
    def __len__(self):
        return len(self.windows)
        
    def __getitem__(self, idx):
        x = torch.tensor(self.windows[idx], dtype=torch.float32)
        y = torch.tensor(self.labels[idx], dtype=torch.float32)
        return x, y

import argparse
import collections
from sklearn.model_selection import train_test_split

def load_raw_windows(input_dir: str, max_samples_per_neg_class: int = 1200):
    csv_files = glob.glob(os.path.join(input_dir, "*.csv"))
    if not csv_files:
        raise ValueError(f"No sliced CSVs found in {input_dir}")
        
    raw_windows = []
    labels = []
    neg_class_counts = collections.defaultdict(int)
    
    for file in csv_files:
        # file name format: *_winXX_classY.csv
        class_str = file.split("_class")[-1].replace(".csv", "")
        try:
            class_id = int(class_str)
        except Exception:
            continue
            
        # Hotkey 6 is dynamic Fall Onset (positive class).
        # Classes 1 (walking), 2 (standing/idle), 3 (sitting), 4 (bending),
        # 5 (controlled lying), 7 (post-fall stillness), 8 (standing back up) are Safe/ADL.
        if class_id == 6:
            label = 1
        else:
            if neg_class_counts[class_id] >= max_samples_per_neg_class:
                continue
            neg_class_counts[class_id] += 1
            label = 0
            
        try:
            # Sliced files have header: x_mm, y_mm, speed_mms, distance_mm, angle_deg
            data = np.loadtxt(file, delimiter=',', skiprows=1)
            if len(data) < 20:
                continue
            x_m = data[:, 0] * MM_TO_M
            y_m = data[:, 1] * MM_TO_M
            speed_m = data[:, 2] * MM_TO_M
        except Exception:
            continue
        
        # Calculate vel_x and vel_y using dt = 0.1 (10fps assumption, identical to live app)
        dt = 0.1
        vel_x = np.zeros_like(x_m)
        vel_y = np.zeros_like(y_m)
        vel_x[1:] = (x_m[1:] - x_m[:-1]) / dt
        vel_y[1:] = (y_m[1:] - y_m[:-1]) / dt
        
        # Position-invariant features: relative displacement within the window
        rel_x = x_m - x_m[0]
        rel_y = y_m - y_m[0]
        
        # Stack into shape (20, 5)
        window = np.column_stack((rel_x, rel_y, vel_x, vel_y, speed_m))
        raw_windows.append(window)
        labels.append(label)
            
    print(f"Loaded {len(raw_windows)} clean windows from disk.")
    pos_count = sum(labels)
    neg_count = len(labels) - pos_count
    print(f"  Positives (Falls): {pos_count} | Negatives (Safe/ADL): {neg_count}")
    return raw_windows, labels

def train(input_dir: str | None = None, epochs: int = 25, batch_size: int = 64, lr: float = 0.001):
    if input_dir is None:
        input_dir = "data/dataset_windows" if os.path.exists("data/dataset_windows") else "dataset_windows"
        
    weights_dir = os.path.join(os.path.dirname(__file__), "..", "app", "ml", "weights")
    os.makedirs(weights_dir, exist_ok=True)
    
    print(f"Loading data from: {input_dir}")
    windows, labels = load_raw_windows(input_dir)
    
    # Stratified split 80% train / 20% val BEFORE augmentation to prevent data leakage
    X_train_orig, X_val, y_train_orig, y_val = train_test_split(
        windows, labels, test_size=0.2, random_state=42, stratify=labels
    )
    
    # Calculate normalization parameters on training set
    all_train_data = np.vstack(list(X_train_orig))
    mean = np.mean(all_train_data, axis=0)
    std = np.std(all_train_data, axis=0)
    std[std == 0] = 1e-6
    
    # Save standard scalers for the live app!
    np.save(os.path.join(weights_dir, "feature_mean.npy"), mean)
    np.save(os.path.join(weights_dir, "feature_std.npy"), std)
    print("Saved feature_mean.npy and feature_std.npy")
    print(f"  Scalers - Mean: {mean.round(4)}, Std: {std.round(4)}")
    
    # Normalize training and validation sets
    X_train_norm = [(w - mean) / std for w in X_train_orig]
    X_val_norm = [(w - mean) / std for w in X_val]
    
    # Targeted Training Augmentation for Fall windows
    X_train_aug = []
    y_train_aug = []
    for w, lab in zip(X_train_norm, y_train_orig):
        X_train_aug.append(w)
        y_train_aug.append(lab)
        if lab == 1:
            # 1. Lateral flip (symmetric left-right reflection)
            w_flip = w.copy()
            w_flip[:, 0] = -w_flip[:, 0]  # rel_x
            w_flip[:, 2] = -w_flip[:, 2]  # vel_x
            X_train_aug.append(w_flip)
            y_train_aug.append(1)

            # 2. Gaussian noise jitter on original
            noise1 = np.random.normal(0, 0.03, w.shape)
            X_train_aug.append(w + noise1)
            y_train_aug.append(1)

            # 3. Gaussian noise jitter on flipped
            noise2 = np.random.normal(0, 0.03, w.shape)
            X_train_aug.append(w_flip + noise2)
            y_train_aug.append(1)

            # 4. Slight velocity scalings
            w_scale1 = w.copy()
            w_scale1[:, 2:] *= 0.9
            X_train_aug.append(w_scale1)
            y_train_aug.append(1)

            w_scale2 = w.copy()
            w_scale2[:, 2:] *= 1.1
            X_train_aug.append(w_scale2)
            y_train_aug.append(1)
                
    train_pos = sum(y_train_aug)
    train_neg = len(y_train_aug) - train_pos
    val_pos = sum(y_val)
    val_neg = len(y_val) - val_pos
    
    print(f"Training set: {len(X_train_aug)} windows (Pos: {train_pos}, Neg: {train_neg})")
    print(f"Validation set (pure real): {len(X_val_norm)} windows (Pos: {val_pos}, Neg: {val_neg})")
    
    train_dataset = RadarWindowDataset(X_train_aug, y_train_aug)
    val_dataset = RadarWindowDataset(X_val_norm, y_val)
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    
    # Calibrated loss weight capped between 1.0 and 3.0 to prevent hyper-sensitivity
    raw_ratio = train_neg / max(train_pos, 1)
    capped_pos_weight = float(np.clip(raw_ratio, 1.0, 3.0))
    pos_weight = torch.tensor([capped_pos_weight], dtype=torch.float32)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    print(f"Loss pos_weight set to: {capped_pos_weight:.2f} (raw ratio was {raw_ratio:.2f})")
    
    model = LSTMAttention(n_features=5)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    
    best_val_f1 = -1.0
    best_val_loss = float('inf')
    best_weights_path = os.path.join(weights_dir, "fall_lstm_baseline.pt")
    
    print("\nStarting Training Loop...")
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for batch_x, batch_y in train_loader:
            optimizer.zero_grad()
            logits = model(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * batch_x.size(0)
            
        train_loss /= len(train_dataset)
        
        # Validation
        model.eval()
        val_loss = 0.0
        tp, fp, tn, fn = 0, 0, 0, 0
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                logits = model(batch_x)
                loss = criterion(logits, batch_y)
                val_loss += loss.item() * batch_x.size(0)
                
                probs = torch.sigmoid(logits)
                preds = (probs >= 0.5).float()
                
                tp += ((preds == 1) & (batch_y == 1)).sum().item()
                fp += ((preds == 1) & (batch_y == 0)).sum().item()
                tn += ((preds == 0) & (batch_y == 0)).sum().item()
                fn += ((preds == 0) & (batch_y == 1)).sum().item()
                
        val_loss /= len(val_dataset)
        val_acc = (tp + tn) / max(tp + tn + fp + fn, 1)
        val_precision = tp / max(tp + fp, 1e-8)
        val_recall = tp / max(tp + fn, 1e-8)
        val_f1 = 2 * val_precision * val_recall / max(val_precision + val_recall, 1e-8)
        
        print(f"Epoch {epoch+1:02d}/{epochs:02d} | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
              f"Acc: {val_acc:.4f} | Prec: {val_precision:.4f} | Rec: {val_recall:.4f} | F1: {val_f1:.4f}")
        
        # Save model if F1 improves, or if tied and loss improves
        if val_f1 > best_val_f1 or (abs(val_f1 - best_val_f1) < 1e-4 and val_loss < best_val_loss):
            best_val_f1 = val_f1
            best_val_loss = val_loss
            torch.save(model.state_dict(), best_weights_path)
            print(f"  --> Saved new best model checkpoint (F1: {val_f1:.4f}, Loss: {val_loss:.4f})")
            
    print(f"\nTraining Complete! Best Val F1: {best_val_f1:.4f}")
    print(f"Model weights saved to: {best_weights_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Fall LSTM Attention model.")
    parser.add_argument("--input", type=str, default=None, help="Path to sliced windows directory")
    parser.add_argument("--epochs", type=int, default=25, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    args = parser.parse_args()
    
    train(input_dir=args.input, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)
