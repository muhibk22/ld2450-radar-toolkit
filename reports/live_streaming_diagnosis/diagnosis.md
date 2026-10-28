# Live streaming freeze and tracking lag diagnosis

Investigation date: 28 October 2026. Scope: the current, modified toolkit working tree, its two bridge sketches, and the OmniSense firmware referenced by the repository's maintenance tools. The user confirmed that the unfiltered raw-byte display also stops during the incident. Application/firmware behavior was not changed during this investigation; the additions are a reproduction utility and this evidence bundle.

## Finding and confidence

There are two separate problems: failure to recover a stalled stream, and processing that delays or rejects otherwise valid motion.

**Confirmed:** the toolkit can keep a stalled TCP connection marked Connected indefinitely. Its receive timeout is only a polling interval; the exception handler immediately retries the same socket. There is no byte-silence deadline, valid-radar-frame deadline, last-frame age, or reconnect trigger for an open connection that stops producing measurements. Localhost reproduction confirms no reconnect after the peer stops sending radar data, both with and without continued status announcements. Restarting the app recreates the connection and clears parser/tracker/UI state, so it can recover this failure mode.

**Strong firmware-side candidate, not an incident capture:** the OmniSense firmware performs blocking-capable writes to four TCP clients sequentially inside the same loop that drains radar UART. A stalled client can therefore delay every client's stream and UART reads. The return values are ignored, and there is no independent bounded sender per client. Closing the toolkit connection on restart can release that particular blocked peer. This is a concrete source of global pauses, but this investigation did not observe the device stalled in that call on hardware.

**Confirmed:** averaging, Kalman tuning, and processing-clock motion gates add latency and can freeze the displayed position even while valid frames arrive. They cannot by themselves make the independent socket stop receiving bytes, although GUI work can delay when incoming bytes become visible.

No running toolkit TCP session was available during the investigation. Consequently, it would be inaccurate to claim that a specific Wi-Fi loss, client write, UART interruption, or firmware baud switch has been proven to be the first cause of the user's last incident. The recovery defect and tracking defects were reproduced; their presence does not identify the original physical/network interruption without receiver-side timing from that incident.

## 1. A socket timeout never makes this connection unhealthy

`app/net/socket_worker.py:48` configures a 0.5-second timeout. At line 64 the handler is simply `except socket.timeout: continue`. Only EOF or a socket exception reaches the reconnect path. A device that stays connected but stops forwarding radar bytes never enters that path. TCP keepalive is not configured either; keepalive would help detect an unreachable peer, but would not prove that radar measurements are fresh.

Measured with the real SocketWorker against a localhost peer:

| Fixture | New connections | Received chunks | Parsed radar frames | Status after 2.2 seconds without new radar frames |
|---|---:|---:|---:|---|
| One radar frame, then complete silence | 1 | 1 | 1 | Connected; worker still running |
| One radar frame, then status announcements | 1 | 9 | 1 | Connected; worker still running |

The second fixture demonstrates why a byte-only heartbeat is insufficient: `OMNISENSE_BOOT` proves some transport activity, not fresh location measurements. The code has no later finite silence limit, so waiting longer does not introduce a recovery branch.

## 2. The firmware behind the boot messages has a shared blocking path

The simple toolkit sketch does not emit `OMNISENSE_BOOT`. The neighboring source at `D:/FYP/Omnisense-/firmware/esp32_omnisense_firmware/esp32_omnisense_firmware.ino` does, including the five-second interval seen in the earlier supplied logs. That identifies a matching source implementation, not the exact flashed build.

Relevant paths in that firmware:

- `serviceTcpClients()` at line 145 accepts up to four clients and writes boot announcements at lines 155/171.
- The main loop calls that function before reading radar UART, at line 709.
- UART is drained at line 714, followed by sequential `tcpClients[i].write(rxBuffer, readLen)` at line 732.
- There is no per-client bounded queue, slow-client deadline policy, or short-write recovery in these loops.
- Auto-baud switches UART between 256000 and 115200 after eight seconds without seeing `AA FF` in an individual read chunk, at lines 754–761. Header detection does not carry a trailing `AA` into the next chunk and does not validate a complete frame. A temporary interruption or fragmented header recognition can therefore cause additional periods at the wrong baud. This is a conditional secondary interruption mechanism, not evidence that baud switching caused the last incident.

`setNoDelay(true)` disables Nagle buffering; it does not turn `write()` into a bounded non-blocking operation. Espressif's [NetworkClient implementation](https://github.com/espressif/arduino-esp32/blob/master/libraries/Network/src/NetworkClient.cpp) contains send/select/retry handling. Exact delays depend on the core version and socket state; the installed firmware's build version was not available, so no specific blocking duration is asserted here.

MQTT is already moved to a separate FreeRTOS worker with a one-frame queue in this OmniSense source (`mqttWorker`, line 90; task creation, line 632). Blaming MQTT reconnects in the main loop would be incorrect for this source. Other conditional main-loop blockers remain: serial configuration scans, AP web requests/scanning, and explicit configuration/reset delays. They require those operations to be invoked and are not proven active during ordinary streaming.

The toolkit's own simpler Wi-Fi bridge has a single-client policy: accepting another connection closes the existing client. The matching OmniSense firmware supports four clients, so the simple sketch's one-client policy must not be assumed to apply to the device producing those announcements.

## 3. GUI delivery and transport health are not independently measured

The socket thread emits byte chunks, but `MainWindow._on_raw_serial_data()` (`app/gui/main_window.py:251`) runs parsing, decoding, telemetry rebuilding, tracking, legacy model inference, optional recording, radar updates, target table updates, and fall-monitor changes on the GUI thread. Cross-thread signals queue delivery to that thread, as described in [Qt's threading documentation](https://doc.qt.io/qt-6/threads-qobject.html).

This means a raw-display freeze alone does not prove that `recv()` stopped. The receiver could still be reading while the GUI falls behind. There is no independent receiver timestamp/backlog metric to distinguish these cases. The input signal queue has no explicit size/age bound or latest-frame policy.

An offscreen benchmark using the actual window and all five loaded challengers processed 150 frames on each view:

| View | Callback plus paint median | 95th percentile | Maximum |
|---|---:|---:|---:|
| Live radar | 16.7 ms | 30.8 ms | 50.5 ms |
| Packet inspector | 6.7 ms | 26.9 ms | 46.5 ms |

At a nominal ten frames per second, these measurements fit within the 100 ms frame interval. They do not reproduce a permanent GUI stall under ordinary synthetic input. They also are not a long-duration test, a real Wi-Fi capture, or a bound on peak backlog during bursts, recording, offline chart exports, or OS scheduling pauses.

The legacy model still executes synchronously in `TargetTracker.process()`. A separate measurement found warm legacy forward passes around 1.2 ms, with initial calls around 4.8–6.1 ms. The five challengers execute in a background worker with one active and one replaceable pending window. The measurements do not support claiming that six-model computation alone is the demonstrated source of the persistent freeze.

## 4. The default average adds a measurable delay

`app/tracker/tracker.py:155` defaults to a ten-packet rolling average; lines 107–112 apply it. For a constant-speed trajectory, a ten-sample average is centered 4.5 samples in the past. At 10 Hz that is approximately 450 ms of deliberate lag, even with perfect transport.

Synthetic motion at 1 m/s and 10 Hz produced an input X of 2000 mm while the displayed average was 1550 mm: a 450 mm offset, equivalent to 450 ms at that speed. This alone explains a substantial part of the responsiveness difference the user sees versus another viewer.

The Kalman option is also sluggish with current initialization/noise values. Under the same ramp, the synthetic position after one second was 1000 mm but the filter reported about 266 mm; after two seconds it reported about 1180 mm for an input of 2000 mm. These are results for this trajectory and initialization, not a fixed universal latency.

## 5. Burst delivery causes legitimate motion to be rejected

`TrackedPerson.validate_and_update()` uses `time.time()` at GUI processing time, with a 10 ms minimum dt (`app/tracker/tracker.py:61`). The parser can return many frames for one socket chunk, and the GUI immediately processes them in a loop. Their processing times do not preserve the sensor's sample intervals.

Measured reproduction with averaging disabled to isolate the gate:

- Ten positions from 0 to 900 mm, sampled 100 ms apart: all ten accepted, ending at 900 mm.
- The same positions handled 1 ms apart as a buffered batch: nine updates rejected, ending at 0 mm with status Predicted.

Thus transient buffering can be converted into an apparent location freeze by the toolkit itself. Both coordinate speed and acceleration gates are affected. The association loop consumes the raw index before validation, so a rejected sample does not become a replacement track in that frame.

## 6. Reconnecting inside the app is not equivalent to restarting it

`SocketWorker.stop()` waits only 1000 ms (`app/net/socket_worker.py:125`), but the reconnect loop sleeps for 1500 ms (line 79), and connection attempts can also outlast that wait. A refused-connection reproduction showed `stop()` returning after 1.000 seconds while `isRunning()` was still true. `MainWindow._toggle_connection()` then clears its worker reference without checking that return state. This is a shutdown/lifecycle defect and can make repeated Connect/Disconnect attempts unreliable.

Disconnect/reconnect does not reset the parser, tracker, model state or focus in `MainWindow`; those objects are created only in the window constructor. Restarting the app clears all of them. Already queued callbacks also have no connection-generation check, so data/status from an old worker can reach the same receiver. A restart can therefore appear more effective than the in-app reconnect operation for several separate reasons.

## 7. Connection-health numbers currently hide the distinction

- `DiagnosticsPanelWidget` initializes latency to the literal `< 1 ms`; neither live worker supplies `latency_ms`. That displayed value is not measured latency.
- TCP stats emit `throughput_bps` and `bytes_received`, while the panel expects `bytes_per_sec`. TCP reconnect counts are not supplied to the displayed reconnect field.
- TCP `packets_received` counts calls returning chunks, not radar frames. One frame can span multiple chunks, and one chunk can contain multiple frames.
- Parser packets/sec is recalculated only while `parse_stream()` is invoked. The one-second GUI stats timer merely reads the cached value, so stopping all input need not promptly make the displayed frame rate zero.
- No last-received-byte age, last-valid-frame age, received-to-rendered delay, pending callback count, or per-client firmware send duration is recorded persistently.

The existing diagnostics cannot establish the first failing stage after the fact.

## Other reviewed logic relevant to location

| Component | Assessment |
|---|---|
| Binary framing | 100 valid frames split into individual bytes all parsed: zero corrupt frames and zero leftover bytes. TCP fragmentation itself is handled. No permanent parser lock was reproduced with this valid input. Mixed ASCII/binary mode and config-response handling still have separate edge cases. |
| Decoder limits | Coordinate/depth/speed validity checks can suppress a target while packets continue. They cannot stop reception. |
| Proximity clustering | Detections within 1 m are merged before even the RAW branch. Two nearby people or changing reflected points can move the centroid. RAW is not a complete tracker bypass, and a Person A lock does not match raw Target 0 IDs. |
| Persistence/focus | Locked tracks can be retained indefinitely and shown as Searching at the last position. Expiry is driven by processed frames, not an independent time-based stale-track sweep. With no incoming frames, the last plot remains until another action. |
| Calibration controls | The Kalman checkbox is initialized before its toggled connection and is not applied to the tracker at startup. Calibration fields show 4000 mm/s, 500 mm jump, and 15 hold frames, while tracker defaults are 6000, 1500 and 30. Applying the displayed defaults therefore changes behavior despite their appearing to be the initial state. |
| Ensemble integration | The current working tree feeds ModelComparison both from the tracker and again from MainWindow for a locked target. The second feed passes aggregate fall fields rather than the dedicated legacy fields. This duplicates input/state work and contaminates comparison semantics; it is not a demonstrated cause of socket silence. Tracker-side feeding also includes predicted/held targets. |
| Packet inspector | Current buffers are capped, flush at about 8 Hz, and skip rendering when hidden. Pause/visibility can intentionally stop the display. An unbounded raw-text document is not present in this working tree. |
| Rendering/telemetry | Plots and multiple tables still update per decoded frame, including hidden telemetry. This adds GUI work and amplifies a burst, but nominal synthetic throughput passed. |
| Recording | CSV writes and a flush occur on the GUI thread every frame. JSON accumulates in memory. Disk stalls/large sessions can add delay when recording is enabled; they are conditional, not a demonstrated explanation for ordinary idle streaming. |
| Serial worker | Its one-second read timeout affects USB mode, not the Wi-Fi worker. It also lacks a radar-frame freshness policy. |
| Discovery/settings | Discovery only runs when requested. It does not periodically disconnect an active stream. The IP default is a fixed value, not a live DHCP lookup. |
| Offline studio/export | Dataset reads use a worker; UI chart generation/exports can block the GUI when invoked. Offline playback is not the live packet source. |
| Maintenance scripts | Firmware/backend patch scripts and probe scripts are not imported by the live application. Their embedded old source snippets are not evidence that those snippets are running. |

## Correction order

1. Add independent monotonic last-byte and last-valid-frame ages, updated at the receiver/decoder boundary. Expose them separately from Connected state and persist transitions.
2. Add silence recovery for a stale stream, with distinct handling for transport silence and heartbeat-only/no-radar data. Reconnect with bounded retry/backoff rather than waiting forever on the same socket. Avoid resetting a working radar merely because the GUI is late.
3. Make worker stop interruptible and keep ownership until termination. Reset connection-scoped parser/tracker/model state deliberately and reject old-generation callbacks.
4. Move parsing/tracking/inference out of the GUI callback and render a current snapshot at a bounded rate. Preserve capture/receive timestamps; reconstruct timing for buffered sensor frames only with an explicit, documented policy.
5. Replace shared blocking TCP fanout in the matching ESP32 firmware with independent bounded per-client send handling, a slow-client policy and checked write results. Validate frames across UART chunks; avoid unnecessary baud probing after transient interruptions.
6. Use substantially lighter display smoothing and measured filter tuning, with the controls reflecting the settings actually applied. Keep visual smoothing separate from model feature preprocessing so a display fix does not silently invalidate trained inputs.
7. Feed comparison models once per fresh observation and correct the health metrics. Verify with a sustained hardware test including Wi-Fi interruption, a slow second client, burst delivery and reconnects.

## Evidence and reproduction

- `reproductions.json`: measured silent-peer, heartbeat-only, shutdown race, timing gate, filtering and byte-fragmentation experiments.
- `gui_benchmark.json`: actual-window offscreen benchmark, including all loaded challengers.
- `inference_benchmark.json`: current-process legacy forward timings.
- `source_inventory.json`: paths and SHA-256 hashes of toolkit source plus the matching neighboring firmware used for this assessment.

Commands from the toolkit root:

```powershell
python tools/diagnose_live_streaming.py
python tools/diagnose_live_streaming.py --gui
python tools/diagnose_live_streaming.py --inference
```

All network reproductions connect exclusively to localhost. No physical radar connection, firmware flashing, application setting change, or model replacement was performed.
