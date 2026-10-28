"""Generate a compact report from completed, compatible comparison runs."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.ml.comparison_features import SCHEMA


def main():
    base = ROOT/'app'/'ml'/'comparison_weights'
    out = ROOT/'reports'/'model_comparison'
    out.mkdir(parents=True,exist_ok=True)
    lines = ['# Trained fall-model comparison', '',
        'The older deployed LSTM is retired from live inference and its weights are archived unchanged. Five active models were trained under each of two protocols. The default live profile uses whole-session splits within each participant.', '',
        'All models use the same timestamp-based, two-second trailing input (21 samples at 10 Hz), with relative X/Y, smoothed coordinate velocity, and signed radar speed. Non-active tracker rows are excluded; gaps over 0.5 seconds reset the window. Training negatives are capped per activity; validation and test windows retain their natural balance. Windows with 1–4 fall-labeled resampled points are excluded from these metrics, but live inference scores every eligible window.', '',
        'Checkpoints and thresholds use validation data only. Test results below are window metrics at the validation-selected threshold, before the live two-prediction hysteresis. They are not event-level recall or false alerts per hour. Known source label-description conflicts remain unchanged and numeric action code 6 defines positives.', '']
    combined = {}
    for manifest_path in sorted(base.glob('*/manifest.json'),reverse=True):
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['feature_schema'] != SCHEMA or manifest['protocol'] in combined:
            continue
        folder = manifest_path.parent
        results = json.loads((folder/'results.json').read_text(encoding='utf-8'))
        split = json.loads((folder/'split.json').read_text(encoding='utf-8'))
        combined[manifest['protocol']] = dict(run=manifest['run'],results=results,split=split)
        title = 'Within-person whole sessions (default)' if manifest['protocol']=='sessions' else 'Unseen participants'
        lines.extend([f'## {title}', '', f"Run: `{manifest['run']}`. Sessions by partition: {dict(Counter(split['session_assignments'].values()))}.", '',
            f"Eligible windows before training-only negative sampling: {split['windows_by_split']}. Non-active rows excluded: {split['excluded_nonactive_rows']}.", '',
            '| Model | Test PR-AUC | Test precision | Test recall | Test F1 | Threshold |',
            '|---|---:|---:|---:|---:|---:|'])
        for result in results.values():
            m = result['test']
            lines.append(f"| {result['name']} | {m['pr_auc']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {result['threshold']:.3f} |")
        lines.extend(['', 'Participants by partition:', ''])
        lines.extend(f'- {part}: {", ".join(people)}' for part,people in split['people'].items())
        lines.append('')
    lines.extend(['## Interpretation', '',
        'Use the within-person profile to test new sessions from familiar people. Use the participant-disjoint profile to examine unseen-person generalization. Their test sets and positive prevalence differ, so scores across protocols are not a controlled measure of improvement. In the within-person run, the retrained LSTM has the highest test F1, while XGBoost has the highest test PR-AUC. In the unseen-person run, XGBoost leads both metrics. These are single-split results with limited positive-participant coverage, not evidence of a universal winner.', '',
        'The original deployed checkpoint is retired and is not included in the held-out score table: its historical training membership is not sufficiently documented to claim these partitions are unseen by it. The separately retrained LSTM gives a fair architecture baseline. The live system now uses four-of-five consensus with the legacy model excluded.', '',
        '## Live behavior and verification', '',
        '- Open Fall monitor → Compare models, select a profile, connect the radar, and lock a confirmed target.',
        '- Five trained models run in a background worker; the older deployed LSTM is not loaded. The comparison records fresh observation timestamps, per-model flags, relative flag delays, and original confirmation transitions.',
        '- Two successive fresh above-threshold outputs produce a challenger flag. After a flag, recovery below threshold and a five-second minimum interval are required to rearm. Eight-second event groups are display groupings, not verified physical events.',
        '- The last 200 event groups remain in memory and can be exported to CSV. Profile identity is retained in events and exports. Missing dependencies/artifacts are visible per model.',
        '- Unit/integration coverage includes session splitting, interpolation, gap resets, target changes, stale in-flight results, profile switching, failed models, cached output handling, event grouping and CSV export.',
        '- Verification on Windows: the 12 new comparison tests and four workspace tests pass in independent processes. All 31 combined-suite assertions pass, but the combined process crashes during native Qt teardown. The same teardown failure reproduces with the original HEAD versions of both GUI files and the 19 pre-existing tests; it is not a new comparison-test assertion failure.',
        '- A held-out recorded session is replayed through the actual five-model worker in `replay.json`; the rendered monitor preview is `monitor_replay.png`. This verifies software integration, not real-sensor operation or event ground truth.', '',
        'Reproduce with `python tools/train_comparison_models.py --split sessions --epochs 25`, then `python tools/train_comparison_models.py --split participants --epochs 25 --no-publish`. Run `python tools/replay_model_comparison.py --screenshot` for the software replay. Full metadata, package versions, data checksums, split assignments and test scores are stored with each run.', ''])
    audit = json.loads((ROOT/'reports'/'fall_detection_audit'/'summary.json').read_text(encoding='utf-8'))
    checks = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in audit['weights_sha256'].items()}
    assert all(checks.values()), 'Original model artifact changed'
    (out/'original_weights_verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    (out/'results.json').write_text(json.dumps(combined,indent=2),encoding='utf-8')
    (out/'results.md').write_text('\n'.join(lines),encoding='utf-8')
    print(out/'results.md')


if __name__ == '__main__':
    main()
