# Fall detection dataset and model assessment

Audit date: 23 October 2026. Scope: README, all active recordings in `data/raw_sessions`, training selection, archive documentation, training scripts, model artifacts, and live inference/confirmation code. This is a measured dataset audit and research-based model proposal, not a trained comparison of replacement models. No recordings, live code, or weights were changed.

## Recommendation

Benchmark **XGBoost on temporal summary features**, **multivariate MiniROCKET with a linear classifier**, and a **small causal temporal convolutional network (TCN)** against the existing BiLSTM-attention architecture. XGBoost is the first practical baseline; the TCN is my preferred neural challenger. These are hypotheses about fit to this dataset, not evidence that any already beats the LSTM.

Fix evaluation and timing first. Only four people contribute positive labels, and several live rules can suppress detections independently of the neural network. Architecture alone cannot resolve those limitations.

## What the project actually measures

The application receives LD2450 target reports through ESP32/serial or TCP, associates and filters targets, then records tracked target telemetry. Despite the directory name `raw_sessions`, these CSVs are downstream of the tracker; they are not raw RF samples.

The informative sensor channels are X, Y and signed radar speed. Velocity is derived from coordinates. Distance/angle are geometrically related to position, not separate body-posture measurements. There are no skeletal joints, vertical body height, point clouds, range-Doppler maps, or micro-Doppler spectrograms in these recordings. Consequently, point-cloud networks and spectrogram CNNs cannot be applied as described in papers that require those inputs. Y is depth in the radar plane; it is not measured human height.

## Measured active dataset

| Quantity | Result |
|---|---:|
| Active sessions | 435 |
| Normalized participants | 9 |
| Usable rows | 387,922 |
| Observed time, excluding gaps over 0.5 s | 9.485 hours |
| Sum of complete session spans | 9.537 hours |
| Code-6 rows | 6,166 (1.589%) |
| Code-6 contiguous runs, split at gaps | 269 |
| Participants with code-6 labels | 4 |
| Sessions with code-6 labels | 97 |
| Active excluded sessions | 0 |
| Byte-identical duplicate recordings / malformed rows | 0 / 0 |

These runs are annotation runs, **not verified physical fall events**. Five code-6 rows actually say `6: Post-fall stillness`, all in `abdullah_session05.csv`. Thus 6,161 rows explicitly say `6: Fall onset`. Three additional rows say `2: Post-fall stillness`. Current training uses numeric prefixes, so audit the label vocabulary before deciding whether these are onset examples. Class 4 is recorded as kneeling, although the legacy trainer's comment calls it bending.

| Activity code | Rows |
|---|---:|
| 1 Walking | 125,400 |
| 2 Standing / idle, including 3 conflicting descriptions | 59,862 |
| 3 Controlled sitting down | 53,790 |
| 4 Controlled kneeling down | 6,033 |
| 5 Controlled lying down | 114,010 |
| 6 Fall onset code, including 5 conflicting descriptions | 6,166 |
| 7 Post-fall stillness | 10,071 |
| 8 Recovery | 12,590 |

Positive coverage is Abdullah: 75 runs / 1,375 rows; Muhib: 56 / 1,144; Shahmeer: 37 / 1,080; Zain: 101 / 2,567. The other five participants have no positive labels. Hafsa supplies 53,502 of 53,790 sitting rows; Arslan supplies 5,822 of 6,033 kneeling rows. Activity and participant are strongly confounded. Many overlapping windows do not compensate for the small number of independent fall participants.

Fall-bearing session subtype metadata: 71 Forward, 7 Backward, 9 Sideways, 10 None. These are session counts, not verified subtype event counts. Backward and sideways coverage deserve particular attention.

The archive documentation records another 264 static-lying recordings and 14,364 derived slices. They remain separate from this active audit. Retain them as a separate static-negative stress test if useful, without allowing their volume to dominate training or treating already-lying samples as fall transitions.

## Timing and quality

Median session sampling rate is 11.58 Hz; session medians range from 10.67 to 44.43 Hz. Rates describe recorded observations, not necessarily independent sensor refreshes. Inspect packet batching and repeated states before interpreting high-rate recordings as additional information.

Current 20-row windows have median duration 1.689 seconds, interquartile range 1.669–1.705 seconds, and extremes 0.307–6.428 seconds. They do not consistently represent two seconds. Across track intervals, 14.47% are below the trainer's 0.07-second clamp, and 1.47% exceed its 0.15-second clamp. Clamping therefore changes the implied derivatives for a nontrivial fraction of observations.

There are 201 session gaps over 0.5 seconds, seven zero-duration track intervals, and 738 coordinate-speed flags above 3.5 m/s. The existing window construction includes 650 windows crossing a gap, including 31 positive windows, before filtering. Split tracks at gaps and target changes; use timestamp-based fixed-duration windows with an explicit resampling/missingness policy.

There are 59,917 range residual flags: recorded distance differs by over 0.1 m from the norm of recorded X/Y. Tracker smoothing or different update paths could explain some; this is not proof of sensor corruption. Prefer recomputing consistent geometric features until that discrepancy is understood. All active sessions have a single target ID, so the trainer's failure to separate targets is a future-data issue rather than a measured current mixing problem.

## Current model and deployment findings

The model is a bidirectional LSTM, hidden size 64 per direction, with attention pooling and a small classifier. Inputs are 20 rows of relative X/Y, smoothed derived X/Y velocity, and radar speed. It evaluates every five incoming frames. Bidirectionality within an already-observed trailing window does not itself require future samples beyond the prediction time.

The v2 metadata reports 356 training-candidate sessions, 9,474 training windows, 1,463 validation windows, 223 validation positives, and best validation F1 0.8554. It holds out sessions, **not people**, with an empty holdout list. The current dataset has 435 sessions; the stored score is not an evaluation of today's entire collection. The script's holdout option excludes people from training but does not itself evaluate them.

SHA-256 confirms that all three files in live `app/ml/weights` match archived v1 artifacts exactly. All three differ from `weights_v2`. The application loads `weights`, so the saved v2 score does not describe the deployed checkpoint.

The v2 trainer discards windows failing motion gates. Of 1,805 windows with at least five code-6 rows, only 1,636 pass: **169 (9.36%) are rejected before classification**. This is a window-level label statistic, not an event-level miss rate. Gated validation hides this loss. Evaluate the full stream as well as the classifier alone.

Further live behavior needs separate evaluation:

- Validation thresholds logits at probability 0.5, while the tracker triggers at 0.70 and then applies temporal confirmation.
- The approach/retreat rule multiplies probability by 0.6. Any window receiving that penalty cannot reach the 0.70 trigger even if its unpenalized probability is 1. This is effectively a veto for that window, potentially including depth-dominant falls.
- The tracker counts consecutive frames even when the detector returns a cached probability between five-frame inference updates. Two positive frame counts need not mean two independent predictions.
- Post-fall stillness compares signed speed directly with positive thresholds. There are 94,205 negative-speed rows; a large negative speed satisfies the current stillness comparison and evades the positive cancellation threshold. Use magnitude for stillness logic and test both directions.
- Training uses recorded timestamps; live inference uses processing wall-clock time. Share a timestamp-aware preprocessing implementation and explicitly handle gaps/bursts.
- Confirmation requires stillness after a trigger. Report its delay and sensitivity loss for falls followed by movement or recovery; stillness alone cannot establish a fallen posture from this sensor.

## Models worth testing

| Priority | Candidate | Why it fits this dataset | Proposed experiment |
|---|---|---|---|
| 1 | XGBoost; Random Forest as a simpler comparator | Small independent sample count and low-dimensional trajectories favor testing structured motion summaries before larger networks | Per-channel quantiles, dispersion, peaks, displacement, path length, acceleration summaries, direction changes, and early/middle/late motion differences |
| 2 | Multivariate MiniROCKET + ridge/logistic classifier | Convolutional transforms offer a fast way to compare temporal shapes without training a recurrent feature extractor | Fixed-duration resampled multichannel windows; fit transforms and linear classifier inside each training fold |
| 3 | Small causal TCN / 1D CNN | Local acceleration and deceleration patterns plus longer motion context are plausible useful signals | Three modest residual blocks, 16–32 channels, dilations 1/2/4; compare 2-second and 4-second trailing inputs |
| 4 | Compact GRU | Useful recurrent capacity/latency ablation against the existing BiLSTM | One 32–64-unit layer under identical preprocessing and folds |
| 5 | Small InceptionTime-style model | Multiple convolution widths can capture falls occurring at different speeds | Secondary experiment after the simpler models; constrain capacity and tuning budget |

This ranking is my inference from the local data and the methods' designs. Published benchmark results do not establish superiority on LD2450 falls. A large Transformer, graph/skeleton network, or raw-radar imaging network is not my first choice for these inputs and this participant count.

Feature safeguards: do not feed participant names, filenames, labels, session-level fall subtype, or recording timestamps as predictive features. Use physical time for derivatives, robust smoothing, and missingness flags. Compute acceleration only after resolving timing and tracking jumps. If augmenting motion, transform coordinates and recompute derivatives consistently; the current velocity-only scaling does not preserve that relationship. Apply augmentation before training-fold normalization.

A later extension is a phase classifier for ADL / onset / post-fall / recovery, followed by a temporal state model. Existing labels make this worth exploring, but reliable event boundaries and label cleanup are prerequisites. Keep an immediate candidate alert distinct from delayed stillness confirmation.

## Fair comparison protocol

1. Freeze a checksummed dataset version and resolve the conflicting action descriptions. Review annotation timing against the original recording protocol; do not automatically equate each label run with one fall.
2. Split normalized participants before windowing. Use four outer folds, each holding out one fall-bearing participant; assign the five ADL-only participants to held-out folds too, so negative-person generalization is tested. Make inner validation participant-disjoint, including a fall-bearing person. With so few positive people, report each fold and uncertainty explicitly.
3. Segment tracks at gaps/identity changes and compare fixed trailing durations. Fit scalers, MiniROCKET transforms, feature selection, augmentation, and thresholds exclusively using training/inner-validation data. Never balance or cap the final evaluation stream.
4. Retrain the current LSTM and each challenger on identical folds. Keep a separate diagnostic comparison to the deployed v1 pipeline; current-data replay of old weights is not an independent test when training membership is unknown.
5. Report PR-AUC and precision/recall/F1 for windows, but make verified event recall, false alerts per observed non-fall hour, detection latency, and duplicate alerts the operational metrics. Define event matching and excluded gaps in advance. Report participant/subtype/activity breakdowns and confidence intervals at participant/session level rather than treating overlapping windows as independent.
6. Evaluate classifier alone, classifier plus motion gates, and the full confirmation pipeline. Sweep thresholds on validation data to compare at the same false-alert budget. Measure CPU inference latency and memory on the target device.
7. Collect an independent continuous-session test: mixed daily activities, varied radar-relative directions/distances, and difficult negatives performed by the same people who supply falls. Add more independently recorded fall participants and backward/sideways examples. Collect room/mounting metadata to test setup changes.

## Sources and reproducibility

Primary research/author sources supporting the candidate methods:

- [XGBoost paper](https://arxiv.org/abs/1603.02754): gradient-boosted tree method.
- [MiniROCKET paper](https://arxiv.org/abs/2012.08791) and [author implementation, including multivariate extension](https://github.com/angus924/minirocket).
- [TCN comparison paper](https://arxiv.org/abs/1803.01271): convolutional versus recurrent sequence modeling.
- [InceptionTime paper](https://arxiv.org/abs/1909.04939): multiscale convolutional time-series classification.

Local evidence: `README.md`, `app/analysis/dataset.py`, `tools/train_fall_lstm.py`, `tools/train_fall_lstm_v2.py`, `app/ml/weights_v2/training_info.json`, `app/ml/fall_detector.py`, `app/ml/post_fall_validator.py`, `app/tracker/tracker.py`, and recording code.

Reproduce the dataset audit with `python tools/audit_fall_dataset.py`. Outputs beside this report: `summary.json`, `sessions.csv`, and checksummed `inventory.json`. These contain measured counts and the exact active-file inventory. Replacement models have not been trained in this assessment.
