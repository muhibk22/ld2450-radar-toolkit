"""
Fall LSTM training, v2.

Differences from tools/train_fall_lstm.py (which is left unchanged):
  * Reads raw sessions directly and honours data/training_session_selection.csv,
    so static lying-down recordings can be excluded without touching the files.
  * Features are computed exactly as the live OmniSense fall engine computes them:
    velocity from real timestamps (dt clamped to [0.07, 0.15] s, |v| <= 3.5 m/s)
    with EMA smoothing (alpha 0.3), then x/y made relative to the window start.
  * Windows step 5 frames (the live inference rate). A window is a fall if it holds
    >= 5 "Fall onset" frames, safe if it holds none; ambiguous windows are skipped.
  * Only windows that pass the live physics gates are used, since those are the only
    windows the model ever sees in production.
  * Negatives are sampled at random per class instead of first-come in file order.
  * Checkpoint selection uses a session-level split, and whole people can be held out
    (--holdout) for honest cross-person testing.
  * Never writes to app/ml/weights/. Output goes to --out.

--recipe old reproduces the original script's data handling for comparison.
"""
import argparse
import collections
import csv
import glob
import json
import os
import random
import sys

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.ml.fall_detector import LSTMAttention

ROOT = os.path.join(os.path.dirname(__file__), "..")
SESSIONS_DIR = os.path.join(ROOT, "data", "raw_sessions")
SELECTION_CSV = os.path.join(ROOT, "data", "training_session_selection.csv")

WINDOW = 20
FALL_LABEL = "6"

# Several people were recorded under more than one volunteer ID.
PERSON_ALIASES = {
    "arslanazad": "arslan", "arslan azad": "arslan",
    "zoya_dif": "zoya", "zoyaazad": "zoya",
    "shazia_dif": "shazia",
}


def person_of(path):
    prefix = os.path.basename(path).rsplit("_session", 1)[0].strip().lower()
    return PERSON_ALIASES.get(prefix, prefix)


def excluded_sessions():
    if not os.path.exists(SELECTION_CSV):
        return set()
    with open(SELECTION_CSV, encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {r["file"] for r in rows if r["decision"] == "exclude"}


def load_session(path):
    """Returns (timestamps, x_m, y_m, speed_mps, labels) sorted by time."""
    rows = []
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((float(r["timestamp"]), float(r["x_mm"]) / 1000, float(r["y_mm"]) / 1000,
                             float(r["speed_mms"]) / 1000, (r.get("action_label") or "").split(":")[0].strip()))
            except (TypeError, ValueError, KeyError):
                continue
    rows.sort(key=lambda r: r[0])
    if not rows:
        return None
    t, x, y, s, lab = zip(*rows)
    return np.array(t), np.array(x), np.array(y), np.array(s), np.array(lab)


def engine_features(t, x, y, s):
    """Per-frame [x, y, vel_x, vel_y, speed], identical to the live fall engine."""
    out = np.zeros((len(t), 5), dtype=np.float32)
    ema_vx = ema_vy = 0.0
    for i in range(len(t)):
        if i > 0:
            dt = float(np.clip(t[i] - t[i - 1], 0.07, 0.15))
            vx = float(np.clip((x[i] - x[i - 1]) / dt, -3.5, 3.5))
            vy = float(np.clip((y[i] - y[i - 1]) / dt, -3.5, 3.5))
            ema_vx = 0.3 * vx + 0.7 * ema_vx
            ema_vy = 0.3 * vy + 0.7 * ema_vy
        out[i] = (x[i], y[i], ema_vx, ema_vy, s[i])
    return out


def old_features(x, y, s):
    """Original script: raw differences with an assumed dt of 0.1 s, no smoothing."""
    vx = np.zeros_like(x); vy = np.zeros_like(y)
    vx[1:] = (x[1:] - x[:-1]) / 0.1
    vy[1:] = (y[1:] - y[:-1]) / 0.1
    return np.column_stack((x, y, vx, vy, s)).astype(np.float32)


def passes_gates(w):
    """The live engine's physics pre-screening (window in absolute or relative coords)."""
    max_speed = float(np.max(np.abs(w[:, 4])))
    displacement = float(np.hypot(w[-1, 0] - w[0, 0], w[-1, 1] - w[0, 1]))
    max_vy = float(np.max(np.abs(w[:, 3])))
    if max_speed < 0.35 and displacement < 0.25:
        return False
    if max_vy < 0.4 and max_speed < 0.5:
        return False
    return True


def relative(w):
    w = w.copy()
    w[:, 0] -= w[0, 0]
    w[:, 1] -= w[0, 1]
    return w


def build_windows(files, recipe, neg_cap, seed):
    """Returns list of (window, label, session_file)."""
    rng = random.Random(seed)
    pos, neg_by_class = [], collections.defaultdict(list)
    for path in files:
        sess = load_session(path)
        if sess is None or len(sess[0]) < WINDOW:
            continue
        t, x, y, s, lab = sess
        name = os.path.basename(path)
        if recipe == "old":
            feats = old_features(x, y, s)
            for start in range(0, len(t) - WINDOW + 1, 10):
                w = feats[start:start + WINDOW]
                cls = lab[start + WINDOW - 1]
                item = (relative(w), int(cls == FALL_LABEL), name, start)
                (pos if cls == FALL_LABEL else neg_by_class[cls]).append(item)
        else:
            feats = engine_features(t, x, y, s)
            for start in range(0, len(t) - WINDOW + 1, 5):
                w = feats[start:start + WINDOW]
                n_fall = int(np.sum(lab[start:start + WINDOW] == FALL_LABEL))
                if 0 < n_fall < 5 or not passes_gates(w):
                    continue
                item = (relative(w), int(n_fall >= 5), name, start)
                (pos if n_fall >= 5 else neg_by_class[lab[start + WINDOW - 1]]).append(item)

    negs = []
    for cls, items in neg_by_class.items():
        if recipe == "old":
            # Original behaviour: first 1200 windows per class in file-name order.
            items.sort(key=lambda it: f"{os.path.splitext(it[2])[0]}_win{it[3]}_class{cls}.csv")
            negs += items[:1200]
        else:
            rng.shuffle(items)
            negs += items[:neg_cap]
    return [(w, l, n) for w, l, n, _ in pos + negs]


def augment(windows, labels):
    xs, ys = [], []
    for w, lab in zip(windows, labels):
        xs.append(w); ys.append(lab)
        if lab == 1:
            flip = w.copy(); flip[:, 0] *= -1; flip[:, 2] *= -1
            s1 = w.copy(); s1[:, 2:] *= 0.9
            s2 = w.copy(); s2[:, 2:] *= 1.1
            xs += [flip, w + np.random.normal(0, 0.03, w.shape), flip + np.random.normal(0, 0.03, w.shape), s1, s2]
            ys += [1] * 5
    return xs, ys


def train(recipe, holdout, out_dir, epochs, neg_cap, seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    excluded = excluded_sessions() if recipe == "new" else set()
    files = sorted(f for f in glob.glob(os.path.join(SESSIONS_DIR, "*_session*.csv"))
                   if person_of(f) not in holdout and os.path.basename(f) not in excluded)
    items = build_windows(files, recipe, neg_cap, seed)

    if recipe == "old":
        # Original: random stratified window-level 80/20 split (overlapping windows can leak).
        tr, va = [], []
        for label in (0, 1):
            group = [it for it in items if it[1] == label]
            random.Random(seed).shuffle(group)
            cut = int(len(group) * 0.2)
            va += group[:cut]
            tr += group[cut:]
    else:
        sessions = sorted({n for _, _, n in items})
        random.Random(seed).shuffle(sessions)
        val_sessions = set(sessions[: max(1, len(sessions) // 7)])
        tr = [it for it in items if it[2] not in val_sessions]
        va = [it for it in items if it[2] in val_sessions]

    train_w = [w for w, _, _ in tr]
    mean = np.vstack(train_w).mean(axis=0)
    std = np.vstack(train_w).std(axis=0)
    std[std == 0] = 1e-6
    xs, ys = augment([(w - mean) / std for w in train_w], [l for _, l, _ in tr])
    xv = np.array([(w - mean) / std for w, _, _ in va], dtype=np.float32)
    yv = np.array([l for _, l, _ in va], dtype=np.float32)

    n_pos = sum(ys)
    pos_weight = float(np.clip((len(ys) - n_pos) / max(n_pos, 1), 1.0, 3.0))
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight]))
    model = LSTMAttention(n_features=5)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loader = DataLoader(TensorDataset(torch.tensor(np.array(xs, dtype=np.float32)), torch.tensor(ys, dtype=torch.float32)),
                        batch_size=64, shuffle=True)

    os.makedirs(out_dir, exist_ok=True)
    best = (-1.0, float("inf"))
    best_epoch = 0
    for epoch in range(epochs):
        model.train()
        for bx, by in loader:
            optimizer.zero_grad()
            loss = criterion(model(bx), by)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            logits = model(torch.tensor(xv))
            val_loss = float(criterion(logits, torch.tensor(yv)))
            pred = (torch.sigmoid(logits) >= 0.5).numpy()
        tp = int(((pred == 1) & (yv == 1)).sum()); fp = int(((pred == 1) & (yv == 0)).sum())
        fn = int(((pred == 0) & (yv == 1)).sum())
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if f1 > best[0] or (abs(f1 - best[0]) < 1e-4 and val_loss < best[1]):
            best, best_epoch = (f1, val_loss), epoch + 1
            torch.save(model.state_dict(), os.path.join(out_dir, "fall_lstm_baseline.pt"))
        print(f"epoch {epoch + 1:02d} val_loss {val_loss:.4f} F1 {f1:.3f} (tp {tp} fp {fp} fn {fn})", flush=True)

    np.save(os.path.join(out_dir, "feature_mean.npy"), mean)
    np.save(os.path.join(out_dir, "feature_std.npy"), std)
    info = {
        "recipe": recipe, "holdout_people": sorted(holdout), "seed": seed, "epochs": epochs,
        "training_sessions": len(files), "excluded_sessions": len(excluded),
        "train_windows": len(tr), "train_fall_windows": int(sum(l for _, l, _ in tr)),
        "val_windows": len(va), "val_fall_windows": int(yv.sum()),
        "best_epoch": best_epoch, "best_val_f1": round(best[0], 4),
        "feature_mean": mean.round(4).tolist(), "feature_std": std.round(4).tolist(),
    }
    with open(os.path.join(out_dir, "training_info.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recipe", choices=["new", "old"], default="new")
    p.add_argument("--holdout", default="", help="Comma-separated people to leave out (for testing)")
    p.add_argument("--out", required=True, help="Output folder for weights (never app/ml/weights)")
    p.add_argument("--epochs", type=int, default=25)
    p.add_argument("--neg-cap", type=int, default=3000, help="Max safe windows per action class")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    if os.path.abspath(a.out) == os.path.abspath(os.path.join(ROOT, "app", "ml", "weights")):
        sys.exit("Refusing to overwrite the live weights folder; choose another --out.")
    train(a.recipe, {h.strip().lower() for h in a.holdout.split(",") if h.strip()}, a.out, a.epochs, a.neg_cap, a.seed)
