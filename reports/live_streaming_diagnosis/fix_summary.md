# Streaming reliability fix — 28 October 2026

## Implemented

- TCP and serial workers now ingest, frame, decode and track data independently of the GUI. Bounded snapshots replace queued per-packet GUI processing. The GUI renders the latest state at up to 30 Hz and avoids repeating unchanged plots.
- TCP reconnects after 3 seconds without bytes, or 5 seconds without valid radar reports. Boot/status announcements do not satisfy radar freshness. Both deadlines use monotonic time. Reconnect waits and socket operations can be interrupted; worker ownership is retained until termination.
- Reconnect resets partial frames, identities, model windows and pending results. Stale callbacks from an old worker are ignored. Positions disappear after 0.6 seconds without fresh target observations, even if status messages or empty radar reports continue.
- Short coalesced batches use nominal 10 Hz spacing anchored to receipt. More than five buffered frames are reduced to the newest five, restarting track/model state. The raw protocol has no sensor capture timestamp; this is an explicit reconstruction policy rather than a measured end-to-end latency claim.
- Visual averaging defaults to two samples instead of ten (50 ms versus 450 ms nominal filter delay at 10 Hz). Kalman process/measurement noise and initialization are retuned for human movement in millimetres. The five-model input path retains a separate ten-sample position history and its existing feature transform, scalers, thresholds and weights.
- Calibration fields now match applied defaults, and the Kalman checkbox follows the calibration mode. Health displays measured last-frame age instead of the fixed `<1 ms` label. Bandwidth/reconnect counters use the fields actually supplied by the worker.
- Recording uses a bounded background writer, preserving capture timestamps and activity labels. Recording errors or a slow disk do not block live ingestion.
- The legacy deployed LSTM is removed from live inference, monitoring and voting. XGBoost, MiniROCKET, TCN, GRU and the newer retrained LSTM remain active. The existing absolute four-vote requirement is retained as **four of five**. Historical legacy weight files remain available as archives; no model files were deleted or retrained.

## Firmware

The matching OmniSense source is updated in the neighboring project:

`D:/FYP/Omnisense-/firmware/esp32_omnisense_firmware/esp32_omnisense_firmware.ino`

Its adjacent `RadarStream.h` is identical to the toolkit's `firmware/RadarStream.h`.
The toolkit Wi-Fi and USB sketches are also updated.

The standalone Wi-Fi bridge now contains the `RadarStream` implementation inline
and has no `RadarStream.h` or `env.h` dependency. Configure `STA_SSID` and
`STA_PASS` in the `.ino` before uploading. A build from a folder containing only
that sketch passes for ESP32-S3 with USB CDC: 894,753 bytes flash and 48,368 bytes
global RAM; see `wifi_single_file_compile.txt`. The separate helper remains for
the OmniSense sketch and host tests.

TCP fanout uses one non-blocking send per client per loop, independent bounded output queues, checked partial writes, and a 250 ms in-flight deadline. A partial frame is completed before another frame or notice can be sent. Slow clients are disconnected individually. A newest frame waiting more than 500 ms is discarded rather than replayed as current. The UART framer recognizes full reports across read boundaries. OmniSense baud switching on transient silence is removed; configured 256000 baud remains stable. Existing MQTT worker isolation, credentials/defaults and saved configuration handling are retained. USB streaming drains data when the host is absent instead of blocking UART on USB writes; USB CDC debug writes also have a zero blocking timeout.

No physical device upload was performed. Flash the matching sketch and its helper to apply the board-side changes. Wi-Fi reconfiguration/scanning can still intentionally interrupt the radio; reconnect logic handles recovery rather than claiming uninterrupted connectivity during those operations.

## Verification

- Eleven live-stream regression tests pass with clean process exit: silent-open TCP recovery, heartbeat-only recovery, interruptible stop, stop-before-start, coalesced timing, bounded backlog, state reset, stale-track clearing, legacy removal/filter separation, buffered recording and concurrent serial disconnect safety.
- Fourteen comparison tests, five tracker tests and four workspace UI tests pass in their isolated runs.
- All 45 test assertions in the combined run pass. The pre-existing native Windows/Qt teardown crash still occurs in the offline dataset-studio test process, also seen before these changes. Its output is retained instead of reporting the combined command as a clean success.
- Real-UI localhost smoke test loads all five trained models, receives a heartbeat-only stall, reconnects once, and processes 90 frames. During a deliberately blocked GUI, receiver frames advance from 16 to 25. Every active model produces a score, and no legacy model is registered. See `end_to_end_after_fix.json` and `five_model_monitor.png`.
- Shared firmware framing/queue tests compile and pass using host C++: split-frame recovery, partial-write preservation, per-client independence, stale-frame dropping and control-message ordering.
- All three final sketches compile for ESP32-S3 with USB CDC using Arduino ESP32 core 3.3.12 (OmniSense also uses PubSubClient 2.8.0). OmniSense: 939,621 bytes flash / 49,344 bytes global RAM. Standalone Wi-Fi bridge: 894,737 / 48,368 bytes. USB bridge: 306,402 / 22,400 bytes. Build output is in `firmware_compile.txt`, `wifi_bridge_compile.txt` and `usb_bridge_compile.txt`.
- Archived original artifacts still match the original audit hashes. All newer binary/scaler/classifier artifacts are retained untouched; their fingerprints are recorded in `model_artifacts_after_fix.json`.

Hardware Wi-Fi endurance, physical tracking responsiveness, and upload/boot behavior require the flashed board. The software/local-network checks do not substitute for that test.

## Reproduce software checks

```powershell
python -m unittest discover -s tests -p test_live_streaming.py -v
python -m unittest discover -s tests -p test_model_comparison.py -v
python tools/verify_streaming_recovery.py
g++ -std=c++11 tests/firmware_stream_test.cpp -o "$env:TEMP/ld2450_firmware_stream_test.exe"
& "$env:TEMP/ld2450_firmware_stream_test.exe"
```

The firmware build toolchain was placed in the Codex temporary cache, not in the project or the user's Arduino installation. Only ESP32-S3 build dependencies were installed, and downloaded archives were checksum-verified.
