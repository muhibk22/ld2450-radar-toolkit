"""Small neural challengers and artifact inference. No changes to legacy weights."""
import json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from .fall_detector import LSTMAttention
from .comparison_features import SCHEMA, summary_features


class CausalBlock(nn.Module):
    def __init__(self, inputs, outputs, dilation):
        super().__init__()
        self.padding = 2 * dilation
        self.conv = nn.Conv1d(inputs, outputs, 3, dilation=dilation, padding=self.padding)
        self.skip = nn.Conv1d(inputs, outputs, 1) if inputs != outputs else nn.Identity()
        self.dropout = nn.Dropout(.15)

    def forward(self, x):
        y = self.conv(x)[:, :, :-self.padding]
        return torch.relu(self.dropout(y) + self.skip(x))


class SmallTCN(nn.Module):
    def __init__(self):
        super().__init__()
        self.blocks = nn.Sequential(CausalBlock(5, 24, 1), CausalBlock(24, 24, 2), CausalBlock(24, 24, 4))
        self.head = nn.Linear(48, 1)

    def forward(self, x):
        z = self.blocks(x.transpose(1, 2))
        return self.head(torch.cat((z.mean(2), z[:, :, -1]), dim=1)).squeeze(-1)


class SmallGRU(nn.Module):
    def __init__(self):
        super().__init__()
        self.gru = nn.GRU(5, 32, batch_first=True)
        self.head = nn.Sequential(nn.Linear(64, 24), nn.ReLU(), nn.Dropout(.2), nn.Linear(24, 1))

    def forward(self, x):
        z, _ = self.gru(x)
        return self.head(torch.cat((z.mean(1), z[:, -1]), dim=1)).squeeze(-1)


def neural_model(kind):
    return {'lstm': lambda: LSTMAttention(5), 'tcn': SmallTCN, 'gru': SmallGRU}[kind]()


class ArtifactModel:
    def __init__(self, directory):
        directory = Path(directory)
        self.info = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
        if self.info['feature_schema'] != SCHEMA:
            raise ValueError('Unsupported comparison feature schema')
        self.kind = self.info['kind']
        if self.kind in ('lstm', 'tcn', 'gru'):
            self.model = neural_model(self.kind)
            self.model.load_state_dict(torch.load(directory / 'model.pt', map_location='cpu', weights_only=True))
            self.model.eval()
            scaling = np.load(directory / 'scaler.npz')
            self.mean, self.std = scaling['mean'], scaling['std']
        elif self.kind == 'xgboost':
            from xgboost import XGBClassifier
            self.model = XGBClassifier(n_jobs=1)
            self.model.load_model(directory / 'model.ubj')
        elif self.kind == 'minirocket':
            # Only load locally trained, trusted artifacts: joblib uses pickle.
            import joblib
            bundle = joblib.load(directory / 'model.joblib')
            self.transform, self.model = bundle['transform'], bundle['classifier']
            self.transform.n_jobs = 1
        else:
            raise ValueError(f'Unknown model kind: {self.kind}')

    def predict(self, windows):
        w = np.asarray(windows, dtype=np.float32)
        if self.kind in ('lstm', 'tcn', 'gru'):
            with torch.inference_mode():
                result = torch.sigmoid(self.model(torch.from_numpy((w-self.mean)/self.std))).numpy()
        elif self.kind == 'xgboost':
            result = self.model.predict_proba(summary_features(w))[:, 1]
        else:
            result = self.model.predict_proba(self.transform.transform(w.transpose(0, 2, 1).copy()))[:, 1]
        if not np.isfinite(result).all():
            raise ValueError('Model returned a nonfinite score')
        return result
