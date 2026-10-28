# Recorded fall and running-reversal case study

28 October 2026. Activity labels were ignored. Ground truth is the user-confirmed mapping: events 1, 2, 3 and 5 are real falls; event 6 is a running reversal. Event 4 has three model flags and unspecified ground truth.

## Data and alignment

The recording contains 1,507 tracker-output rows over 134.01 seconds for Person A. Median interval is 0.090 s; largest recorded gap is 0.203 s. There are 0 sequence discontinuities. Status counts: {'Active': 1332, 'Predicted': 90, 'Searching': 85}.

This is processed tracking telemetry, not UART packets. The recorder writes tracked coordinates and includes held/predicted targets. Only `Active` and valid rows count as fresh target observations. A non-active row cannot distinguish sensor loss, association failure or physical-gate rejection without the underlying UART capture. The detection export has only model flags (`stage=detected`) and empty confirmation timestamps, so it does not demonstrate that post-fall validation ran.

Each alert is anchored at its fourth model flag, not its first flag or an assumed physical impact time. Event 4 has no four-vote consensus and is anchored at its first flag for plotting only.

## Measured first second after consensus

| Event | User ground truth | Flags | Karachi time | Recorded position shift | Fresh rows | Fresh interval coverage | Heading change |
|---|---|---:|---|---:|---:|---:|---:|
| 1 | real fall | 5/5 | 23:42:13.487 | 0.281 m | 7/13 | 40% | 22 degrees |
| 2 | real fall | 5/5 | 23:42:28.888 | 0.301 m | 12/12 | 100% | 9 degrees |
| 3 | real fall | 4/5 | 23:42:57.177 | 0.012 m | 2/12 | 12% | 1 degrees |
| 4 | unconfirmed; ground truth unspecified | 3/5 | 23:43:18.004 | 0.070 m | 7/12 | 53% | 13 degrees |
| 5 | real fall | 5/5 | 23:43:28.949 | 0.016 m | 10/12 | 82% | 172 degrees |
| 6 | running reversal (false positive) | 5/5 | 23:43:40.082 | 0.927 m | 12/12 | 100% | 164 degrees |

Position shift uses the first and last recorded rows in that second. Where tracking is predicted/held, a small displayed shift is not proof of physical stillness. Fresh interval coverage integrates time only between adjacent valid Active observations no more than 0.25 s apart.

Event 6 has a 164-degree pre/post heading change and about 0.93 m recorded travel. Event 5 also reverses its small residual direction (172 degrees), but shifts only 0.016 m. A reversal-only veto would therefore be unsafe even within these examples. In event 5, fresh rows continue to report 0.88 m/s radial speed despite only 0.016 m recorded position shift in one second. This discrepancy also argues against a hard speed-only veto. The files cannot establish whether sensor estimates, tracking/filtering or another upstream effect explains it.

## Replay of the provisional five-second stillness validator

The current local draft was replayed on Active rows only, with freshness checks on other rows. Coordinates in this recording have already been display-filtered; this is not an exact replay of raw accepted coordinates. Nevertheless, the missing observations and continued recovery movement directly contradict a mandatory five-second stillness gate.

| Event | Outcome | Delay from consensus | Reason |
|---|---|---:|---|
| 1 | unverified | 1.17 s | Fresh target observations stopped; stillness cannot be verified |
| 2 | rejected | 5.08 s | Insufficient sustained low motion during observation |
| 3 | unverified | 0.63 s | Fresh target observations stopped; stillness cannot be verified |
| 5 | unverified | 1.35 s | Fresh target observations stopped; stillness cannot be verified |
| 6 | rejected | 1.86 s | Sustained fast movement after consensus |

## Best-supported next change

Use model consensus as an immediate suspected-fall signal. Add a short check for positive evidence of continued reverse running: substantial displacement on continuous fresh observations, with a heading opposed to the approach. An exploratory starting point is a 1.0–1.25 s observation, at least 0.5 m measured travel, at least 80% fresh interval coverage, and heading cosine <= -0.5 (at least 120 degrees). Check sustained travel across the interval rather than one extreme packet. Do not use a radial-speed sign change alone.

At a 1.0-second horizon, 0.5 m fresh-endpoint displacement, 80% fresh interval coverage and a heading cosine <= -0.5, the exploratory veto selects only event 6. None of the four user-confirmed real events is vetoed. This is a proposed local separation, not proof that those falls can all be confirmed from the available sensor channels.

Keep post-fall low motion as supporting evidence, not a required universal gate. If the target becomes Predicted/Searching, retain a visible suspected-fall / tracking-lost outcome and do not silently clear it or call the repeated position confirmed stillness. A real person who gets up promptly should not be rejected solely for later movement.

The parameter grid in analysis.json uses the same supplied events to suggest thresholds. It is not held-out validation. Collect more direction reversals, abrupt stops, sitting, jumping and different genuine falls; tune and evaluate on separate whole sessions before production use. Retraining with these hard negatives is a better long-term correction to all five models than raising their score thresholds or requiring all five votes.

All five models flag event 6, so unanimity does not remove it; event 3 has only four flags, so unanimity would remove a real alert. The files contain no body height or posture channel, so this analysis cannot verify that someone is lying down.

No model, threshold or runtime source was changed by this analysis. The five-second draft already in the working tree should not be treated as a validated fix for this recording.

## Reproduce

`python tools/analyze_recorded_falls.py`

Source SHA-256 fingerprints and numerical results are in analysis.json. The original CSVs remain unchanged.
