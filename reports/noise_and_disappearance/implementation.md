# Fall disappearance confirmation and noise exclusions — 29 October 2026

## What changed

Four-model consensus remains required. The five trained models, preprocessing,
scalers, thresholds and weights are unchanged. Early reverse-running rejection
is unchanged. The confirmation layer now accepts three explicitly recorded bases:

1. `fresh_low_motion`: the existing sustained low-motion evidence.
2. `stable_centroid`: a fresh centroid remains within a 100 mm stability region,
   with planar path speed at most 100 mm/s, for 2.5 seconds after settling. This
   tolerates a contradictory/stale radial-speed estimate while retaining actual
   positional evidence. The stability anchor resets if it drifts outside the
   region, so slow travel does not accumulate as stationary evidence.
3. `post_fall_disappearance`: after model consensus, at least 1.5 seconds of
   continuing valid radar reports contain no eligible non-noise target. This
   supports the user's reported stationary/below-range disappearance behavior.
   It is inferred disappearance after a model event, not measured stillness or
   an independent measurement of lying posture.

Production code determines reported absence from the raw decoded candidates
after explicit noise/spatial validity filtering and before association. Predicted
output alone does not qualify. Ambiguous observations, a rejected but still
present raw target, connection resets and stopped packets still leave a suspected
warning. A gap in radar reports cannot supply continuous disappearance evidence.
Confirmed alerts remain visible for their hold period even when the canvas is
empty; subsequent loss does not erase the earlier confirmation. CSV exports
include confirmation basis, absence duration and stationary duration.

## Marking constant noise

Right-click a target marker and choose **Mark this target as noise**. Alternatively,
click it to focus it, then use **Live radar → Noise exclusions → Mark focused
target as noise**. The default circle radius is 300 mm; the panel allows 50–1500 mm.

The exclusion stores a location/radius, not a recycled person label or radar slot.
It removes matching raw detections before clustering and all identity-association
paths, including expanded lost/locked-target searches, dormant reacquisition and
RAW display mode. Marking a target removes its stale track. If it was focused,
focus is cleared; marking another noise track does not reset the real person's
validation. Excluded sources do not enter model input or recording targets.

Dashed circles and noise labels show ignored areas. The same panel removes an
individual circle or clears all circles. Exclusions persist in app settings
through reconnects, stream resets and app launches. Keep circles small: every
detection inside is excluded, including a real person. Clear them when moving
the radar to a different position or room.

## Replay results

Activity labels were ignored. Both the recorded-flag replay and replay through
the five unchanged actual models produced:

| Event | Votes | Outcome | Confirmation/rejection basis | Time after consensus |
|---|---:|---|---|---:|
| 1 | 5/5 | Confirmed | Healthy-stream disappearance | 2.399 s |
| 2 | 5/5 | Confirmed | Stable centroid | 3.644 s |
| 3 | 4/5 | Confirmed | Healthy-stream disappearance | 1.701 s |
| 4 | 3/5 | Awaiting votes | No four-model consensus | — |
| 5 | 5/5 | Confirmed | Healthy-stream disappearance | 2.407 s |
| 6 | 5/5 | Rejected | Early continuous reverse running | 1.051 s |

The supplied CSV contains processed coordinates and Predicted/Searching status,
not raw UART or association diagnostics. For this replay, non-Active rows are
explicitly treated as healthy reports with no eligible target, consistent with
the disappearance cause described by the user. They cannot independently prove
that cause. The live pipeline uses actual eligible decoded detections instead.
This is a development regression on the supplied session, not independent
general-accuracy or false-alert-rate evidence. Physical fall and noise tests on
the sensor are still needed.

## Verification

All 71 targeted tests pass in isolated processes: 20 validator, 21 comparison/UI,
six noise tracker/integration, three noise UI, one recorded-session, 11 streaming,
five original tracker and four workspace UI tests. Tests include:

- The marked source changes radar slots during 70 missed frames without taking
  over the locked person's identity; the real person is reacquired correctly.
- Noise is removed before proximity merging in every tracking mode.
- A fall can confirm on continuing empty/only-ignored-noise reports without the
  ghost moving the lost person's position.
- Stream silence, interrupted absence and generic missing/ambiguous observations
  cannot be used as disappearance confirmation.
- Click-to-mark, right-click menu, saved settings, removal, units scaling, stale
  selection refusal and a confirmed alert on an empty radar canvas work.

The actual-UI localhost recovery check passes with all five models. Reception
advances from 15 to 23 frames during a deliberate GUI pause and reconnects after
heartbeat-only input. No physical device was opened or flashed.

The fingerprint audit verifies 114 unchanged files, including all available
weight-directory artifacts/metadata and both supplied CSVs. Compile checks and
`git diff --check` pass; Git emits its existing pyproject.toml line-ending notice.

## Reproduce and inspect

```powershell
python tools/verify_combined_validation.py --actual-models --screenshot --out reports/noise_and_disappearance
python -m unittest discover -s tests -p test_noise_exclusions.py -v
python -m unittest discover -s tests -p test_noise_ui.py -v
python -m unittest discover -s tests -p test_post_consensus_validation.py -v
python -m unittest discover -s tests -p test_recorded_combined_validation.py -v
python tools/verify_streaming_recovery.py --out reports/noise_and_disappearance/live_smoke
```

The JSON replays, unchanged-input audit, test logs and monitor preview are in this
folder. `noise_exclusions.png` is an offscreen synthetic UI preview generated
with isolated temporary settings; it did not save fake exclusions to user settings.

Restart the toolkit to load these Python/UI changes. No model retraining or
firmware upload is required.
