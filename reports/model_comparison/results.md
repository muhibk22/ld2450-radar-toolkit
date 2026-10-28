# Trained fall-model comparison

The older deployed LSTM is retired from live inference and its weights are archived unchanged. Five active models were trained under each of two protocols. The default live profile uses whole-session splits within each participant.

All models use the same timestamp-based, two-second trailing input (21 samples at 10 Hz), with relative X/Y, smoothed coordinate velocity, and signed radar speed. Non-active tracker rows are excluded; gaps over 0.5 seconds reset the window. Training negatives are capped per activity; validation and test windows retain their natural balance. Windows with 1–4 fall-labeled resampled points are excluded from these metrics, but live inference scores every eligible window.

Checkpoints and thresholds use validation data only. Test results below are window metrics at the validation-selected threshold, before the live two-prediction hysteresis. They are not event-level recall or false alerts per hour. Known source label-description conflicts remain unchanged and numeric action code 6 defines positives.

## Within-person whole sessions (default)

Run: `20261023_130253_sessions`. Sessions by partition: {'validation': 64, 'test': 64, 'train': 307}.

Eligible windows before training-only negative sampling: {'train': 40618, 'test': 8420, 'validation': 9446}. Non-active rows excluded: 11676.

| Model | Test PR-AUC | Test precision | Test recall | Test F1 | Threshold |
|---|---:|---:|---:|---:|---:|
| XGBoost | 0.810 | 0.772 | 0.727 | 0.749 | 0.901 |
| MiniROCKET | 0.760 | 0.819 | 0.675 | 0.740 | 0.986 |
| TCN | 0.743 | 0.693 | 0.734 | 0.713 | 0.866 |
| GRU | 0.798 | 0.828 | 0.656 | 0.732 | 0.964 |
| LSTM (retrained) | 0.766 | 0.767 | 0.747 | 0.757 | 0.925 |

Participants by partition:

- train: abdullah, aiman, arslan, hafsa, muhib, shahmeer, shazia, zain, zoya
- validation: abdullah, aiman, arslan, hafsa, muhib, shahmeer, shazia, zain, zoya
- test: abdullah, aiman, arslan, hafsa, muhib, shahmeer, shazia, zain, zoya

## Unseen participants

Run: `20261023_130253_participants`. Sessions by partition: {'train': 348, 'validation': 49, 'test': 38}.

Eligible windows before training-only negative sampling: {'train': 49642, 'validation': 5428, 'test': 3414}. Non-active rows excluded: 11676.

| Model | Test PR-AUC | Test precision | Test recall | Test F1 | Threshold |
|---|---:|---:|---:|---:|---:|
| XGBoost | 0.878 | 0.934 | 0.676 | 0.784 | 0.889 |
| MiniROCKET | 0.793 | 0.910 | 0.557 | 0.691 | 0.979 |
| TCN | 0.831 | 0.920 | 0.502 | 0.650 | 0.938 |
| GRU | 0.867 | 0.942 | 0.644 | 0.765 | 0.938 |
| LSTM (retrained) | 0.853 | 0.912 | 0.617 | 0.736 | 0.936 |

Participants by partition:

- train: abdullah, aiman, arslan, hafsa, zain
- validation: muhib, zoya
- test: shahmeer, shazia

## Interpretation

Use the within-person profile to test new sessions from familiar people. Use the participant-disjoint profile to examine unseen-person generalization. Their test sets and positive prevalence differ, so scores across protocols are not a controlled measure of improvement. In the within-person run, the retrained LSTM has the highest test F1, while XGBoost has the highest test PR-AUC. In the unseen-person run, XGBoost leads both metrics. These are single-split results with limited positive-participant coverage, not evidence of a universal winner.

The original deployed checkpoint is retired and is not included in the held-out score table: its historical training membership is not sufficiently documented to claim these partitions are unseen by it. The separately retrained LSTM gives a fair architecture baseline. The live system now uses four-of-five consensus with the legacy model excluded.

## Live behavior and verification

- Open Fall monitor → Compare models, select a profile, connect the radar, and lock a confirmed target.
- Five trained models run in a background worker; the older deployed LSTM is not loaded. The comparison records fresh observation timestamps, per-model flags, relative flag delays, and original confirmation transitions.
- Two successive fresh above-threshold outputs produce a challenger flag. After a flag, recovery below threshold and a five-second minimum interval are required to rearm. Eight-second event groups are display groupings, not verified physical events.
- The last 200 event groups remain in memory and can be exported to CSV. Profile identity is retained in events and exports. Missing dependencies/artifacts are visible per model.
- Unit/integration coverage includes session splitting, interpolation, gap resets, target changes, stale in-flight results, profile switching, failed models, cached output handling, event grouping and CSV export.
- Verification on Windows: the 12 new comparison tests and four workspace tests pass in independent processes. All 31 combined-suite assertions pass, but the combined process crashes during native Qt teardown. The same teardown failure reproduces with the original HEAD versions of both GUI files and the 19 pre-existing tests; it is not a new comparison-test assertion failure.
- A held-out recorded session is replayed through the actual five-model worker in `replay.json`; the rendered monitor preview is `monitor_replay.png`. This verifies software integration, not real-sensor operation or event ground truth.

Reproduce with `python tools/train_comparison_models.py --split sessions --epochs 25`, then `python tools/train_comparison_models.py --split participants --epochs 25 --no-publish`. Run `python tools/replay_model_comparison.py --screenshot` for the software replay. Full metadata, package versions, data checksums, split assignments and test scores are stored with each run.
