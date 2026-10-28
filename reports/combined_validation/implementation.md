# Combined fall validation — 29 October 2026

Historical verification of the initial combined policy. The subsequent
noise-exclusion and healthy-stream disappearance update supersedes its treatment
of missing targets; see `../noise_and_disappearance/implementation.md`.

## Runtime behavior

The five existing classifiers, feature transforms, scalers, model thresholds and
artifacts are unchanged. Four model flags still create a candidate. Validation
operates separately on fresh accepted tracking coordinates before display/model
averaging; individual model detections remain visible and export unchanged.

- In the first 1.0–1.25 seconds after consensus, reject only continuous reverse
  travel supported by fresh observations. Defaults require at least 500 mm
  displacement, at least 250 mm approach displacement on at least 0.5 seconds of
  approach history, an opposing heading (cosine <= -0.5), at least 80% interval
  coverage and at least 80% straightness. Interior gaps/held observations do not
  qualify as continuous travel. Radial speed or a heading flip alone cannot reject.
- Allow up to five seconds for low-motion evidence. After one second of settling,
  2.5 seconds of consecutive fresh low motion can confirm early: absolute radial
  speed <= 150 mm/s and planar path speed <= 250 mm/s over a trailing 0.5-second
  interval. Path length prevents oscillating motion from cancelling to zero.
- Late recovery movement does not reject the candidate. If the observation period
  is inconclusive, retain a suspected-fall warning instead of rejecting it.
- Predicted, Searching, missing and ambiguous targets cannot supply stillness.
  More than 0.5 seconds without a fresh accepted target produces a suspected-fall
  tracking-loss warning. Stream resets, reconnects, target/profile changes and
  normal event-history rotation do not silently clear unresolved warnings.
- Warnings remain amber and visible even when the radar canvas is empty. They do
  not increment the confirmed-fall counter. The monitor lists unresolved events
  and provides **Acknowledge suspected-fall warnings**. Acknowledgement preserves
  history and is included in CSV exports. Warnings persist within the current app
  session; export before closing to retain the history.

A recently confirmed event also becomes a reviewable tracking-loss warning if
observations stop during its alert hold, preserving its earlier confirmation
timestamp. Old confirmations do not resurrect indefinitely.

## Recorded-session results

The user identified events 1, 2, 3 and 5 as real falls, event 6 as reverse running,
and event 4 as a three-flag non-consensus event. Activity labels were ignored.

Both logged-flag replay and replay through all five real models produced:

| Event | Votes | Final validation | Why |
|---|---:|---|---|
| 1 | 5/5 | Suspected warning | Tracking lost; fresh stillness unavailable |
| 2 | 5/5 | Suspected warning | Five-second observation inconclusive |
| 3 | 4/5 | Suspected warning | Tracking lost; fresh stillness unavailable |
| 4 | 3/5 | Awaiting votes | Four-model consensus was not reached |
| 5 | 5/5 | Suspected warning | Tracking lost; fresh stillness unavailable |
| 6 | 5/5 | Rejected | Continuous early reverse running |

Event 6 was rejected 1.051 seconds after its fourth flag (about 1.587 seconds
after the first flag). The reversal check observed 1.032 m displacement, heading
cosine -0.965, 100% fresh coverage and 98.3% path straightness.

The four genuine events are retained as warnings, **not claimed as four verified
stillness confirmations**. The synthetic fresh-stillness case separately verifies
that the confirmation branch works. The empty-canvas UI test verifies that a
tracking-loss warning stays visible and can be acknowledged without deleting it.

The recorded coordinates are already tracker/display-filtered. The actual-model
replay reconstructs the existing ten-sample model input from them; it cannot
reproduce the original UART values exactly. Its six event groups and final
outcomes match the logged-flag replay here. This is a development regression on
one supplied session, not independent accuracy or false-alarms-per-hour evidence.
The reversal settings still need broader session-disjoint evaluation.

## Verification

- 54 targeted tests pass with clean exits: 17 validator, 21 comparison/UI,
  one recorded-session regression, 11 live-stream recovery and four workspace UI.
- All five actual models load and run on the recorded session without inference
  errors. A fingerprint audit verifies 114 unchanged model/source input files,
  including all available weight-directory files and both supplied CSVs.
- The real-UI localhost smoke test reconnects after heartbeat-only input. Receiver
  frames advance from 17 to 25 while the GUI is deliberately paused; all five
  models produce scores. This is a software/local-network check, not a hardware
  endurance test.
- Compile checks and `git diff --check` pass (Git emits an existing line-ending
  notice for pyproject.toml). No firmware change or device flash is needed for
  this validation update. Restart the toolkit to load the new Python logic.
- The unrelated offline dataset-studio suite with its previously documented Qt
  teardown problem was not included in these targeted runs.

## Artifacts and reproduction

- `recorded_flags_replay.json`: injected original flags plus observed tracking,
  including warning persistence and acknowledgement checks.
- `actual_models_replay.json`: real five-model inference replay and event states.
- `recorded_validation_monitor.png`: real monitor rendering of the actual-model
  replay, including retained warnings and rejected event 6.
- `unchanged_inputs_before.json` and `unchanged_inputs_verified.json`: input audit.
- `*_tests.txt` and `live_smoke/`: test outputs and live-recovery evidence.

```powershell
python tools/verify_combined_validation.py --actual-models --screenshot
python -m unittest discover -s tests -p test_post_consensus_validation.py -v
python -m unittest discover -s tests -p test_model_comparison.py -v
python -m unittest discover -s tests -p test_recorded_combined_validation.py -v
python -m unittest discover -s tests -p test_live_streaming.py -v
python -m unittest discover -s tests -p test_workspace_ui.py -v
python tools/verify_streaming_recovery.py --out reports/combined_validation/live_smoke
```
