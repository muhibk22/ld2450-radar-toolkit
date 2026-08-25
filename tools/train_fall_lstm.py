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

def load_and_preprocess(input_dir: str):
    csv_files = glob.glob(os.path.join(input_dir, "*.csv"))
    if not csv_files:
        raise ValueError(f"No sliced CSVs found in {input_dir}")
        
    raw_windows = []
    labels = []
    
    for file in csv_files:
        # file name format: *_winXX_classY.csv
        class_str = file.split("_class")[-1].replace(".csv", "")
        try:
            class_id = int(class_str)
        except:
            continue
            
        # Map to binary (1 = Fall, 0 = Safe)
        # Hotkeys: 6 (Onset) and 7 (Post-fall) are Falls.
        if class_id in [6, 7]:
            label = 1
        else:
            label = 0
            
        df = pd.read_csv(file)
        if len(df) < 20:
            continue
            
        # Feature Engineering: 
        # App uses: x (m), y (m), vel_x (m/s), vel_y (m/s), speed (m/s)
        x_m = df['x_mm'].values * MM_TO_M
        y_m = df['y_mm'].values * MM_TO_M
        speed_m = df['speed_mms'].values * MM_TO_M
        
        # Calculate vel_x and vel_y using dt = 0.1 (10fps assumption, similar to live app)
        dt = 0.1
        vel_x = np.zeros_like(x_m)
        vel_y = np.zeros_like(y_m)
        vel_x[1:] = (x_m[1:] - x_m[:-1]) / dt
        vel_y[1:] = (y_m[1:] - y_m[:-1]) / dt
        
        # Stack into shape (20, 5)
        window = np.column_stack((x_m, y_m, vel_x, vel_y, speed_m))
        
        # Data Augmentation (slight noise to prevent overfitting on tiny dataset)
        # We will add 3 noisy variations of each window
        raw_windows.append(window)
        labels.append(label)
        
        # Augment Fall classes more heavily to balance if needed, or just augment everything
        for _ in range(3):
            noise = np.random.normal(0, 0.05, window.shape) # 5cm/s noise
            aug_window = window + noise
            raw_windows.append(aug_window)
            labels.append(label)
            
    print(f"Loaded {len(raw_windows)} total windows (including augmentations).")
    
    # Calculate dataset mean and std for normalization
    all_data = np.vstack(raw_windows)
    mean = np.mean(all_data, axis=0)
    std = np.std(all_data, axis=0)
    
    # Prevent div by zero
    std[std == 0] = 1e-6
    
    # Normalize windows
    norm_windows = [(w - mean) / std for w in raw_windows]
    
    return norm_windows, labels, mean, std

def train():
    input_dir = "dataset_windows"
    weights_dir = os.path.join(os.path.dirname(__file__), "..", "app", "ml", "weights")
    os.makedirs(weights_dir, exist_ok=True)
    
    print("Loading data...")
    windows, labels, mean, std = load_and_preprocess(input_dir)
    
    # Save standard scalers for the live app!
    np.save(os.path.join(weights_dir, "feature_mean.npy"), mean)
    np.save(os.path.join(weights_dir, "feature_std.npy"), std)
    print("Saved feature_mean.npy and feature_std.npy")
    
    # Split 80/20 manually
    from sklearn.model_selection import train_test_split
    X_train, X_val, y_train, y_val = train_test_split(windows, labels, test_size=0.2, random_state=42, stratify=labels)
    
    train_dataset = RadarWindowDataset(X_train, y_train)
    val_dataset = RadarWindowDataset(X_val, y_val)
    
    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)
    
    print(f"Training on {len(train_dataset)} windows, Validating on {len(val_dataset)} windows.")
    
    model = LSTMAttention(n_features=5) # 5 Features! Fixes the 148 bug.
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    
    epochs = 20
    best_val_loss = float('inf')
    
    print("Starting Training Loop...")
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
            
        train_loss /= len(train_loader.dataset)
        
        # Validation
        model.eval()
        val_loss = 0.0
        correct = 0
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                logits = model(batch_x)
                loss = criterion(logits, batch_y)
                val_loss += loss.item() * batch_x.size(0)
                
                probs = torch.sigmoid(logits)
                preds = (probs >= 0.5).float()
                correct += (preds == batch_y).sum().item()
                
        val_loss /= len(val_loader.dataset)
        val_acc = correct / len(val_loader.dataset)
        
        print(f"Epoch {epoch+1:02d}/{epochs} - Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | Val Acc: {val_acc:.4f}")
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            weights_path = os.path.join(weights_dir, "fall_lstm_baseline.pt")
            torch.save(model.state_dict(), weights_path)
            
    print(f"\nTraining Complete! Best model saved to: {weights_path}")

if __name__ == "__main__":
    train()
