# LD2450 mmWave Radar Tracker Toolkit

A comprehensive desktop application, firmware, and machine learning toolkit for tracking human targets and detecting falls using the **Hi-Link HLK-LD2450 24GHz mmWave Radar**.

This project features a PyQt/PySide6 graphical interface for real-time visualization, a robust physics-based target tracking engine (with Kalman filtering), and a PyTorch LSTM neural network for fall detection.

## Radar workspace

The main window separates **Live radar**, **Calibration**, and **Protocol inspector**
into task views (Ctrl+1/2/3). Use **Connection controls** to connect a sensor and
adjust tracking. This panel hides automatically in smaller windows and can be
reopened with its button or Ctrl+\\. Serial baud detection and network discovery
run in the background; select **Connect** after a device is found.

**Record sessions** (Ctrl+Shift+R), **Analyze dataset** (Ctrl+Shift+D), and
**Fall monitor** are available directly above the workspace. Controls wrap when
space is limited, recording forms scroll, and dataset charts stack vertically.
The dataset window's **Recordings** button shows or hides the session browser.

## Dataset Visualization Studio

Open **Data → Analyze dataset** in the radar tool, or press
**Ctrl+Shift+D**. This offline module uses the existing PySide6, pyqtgraph and
NumPy dependencies and works without connecting a radar or loading an ML model.
It can also run independently from the `tracker app` directory:

```powershell
python -m app.dataset_visualization
python -m app.dataset_visualization "D:\Projects\FYP\dataset"
```

The default directory is `data/raw_sessions`. Choose another collection folder,
or the FYP workspace to combine its session collections. Nested recordings use
the standard `<participant>_session<number>.csv` names; CSVs directly inside the selected folder
may have arbitrary names. Index and training-selection CSVs are metadata and are
not recordings. Dependency and generated-output directories are skipped.

- **Collection overview:** activity balance, participant coverage, position
  density, and radar-speed percentile comparisons across activities.
- **Human playback:** select a recording and target, play at 0.25–4×, scrub
  through its actual timestamps, or jump to the first fall label. The time slider
  stays visible above the scrollable plots. A bright movement trail shows the
  preceding 3 seconds; choose 5, 10, 30 seconds or all movement since the start.
  Scrubbing pauses playback and updates the person, trail and signal cursors together.
  The X, Y and speed graphs have their own scrollable panel, independent of the
  human path. Scroll over a graph to browse the panel, drag to pan time, or use
  Ctrl+wheel to zoom time. Recording gaps remain disconnected. X, Y and
  radar-speed plots share the playback cursor. The stick figure is a fixed
  schematic marker at the measured X/Y location; these recordings do not
  contain skeletal joints, posture, or body height.
- **Session comparison:** overlay two recordings and targets with distinct
  colors and line styles. Align each track to its start or its first manual
  fall-onset label. A track without a fall label is explicitly unavailable for
  fall alignment, rather than being aligned to an invented event.
- **Coverage & quality:** participant/activity coverage, sampling rates,
  per-session recording gaps, coordinate-speed flags, range inconsistencies,
  duplicate/malformed rows, and detailed load errors.

Filters select complete sessions by normalized participant, activity present,
fall subtype, pace, and current training eligibility. A session-name search
also affects all charts and exports. Known participant aliases are merged using
the training script's mapping. Training exclusions are read from the existing
`data/training_session_selection.csv`; all collected sessions remain visible by
default. SHA-256 identifies byte-identical copied files. Sources are read only.
Use **Refresh data** after recording additional sessions; loading runs in a
cancellable background thread and keeps the previous dataset if cancelled.

The redundant static-lying collection is stored separately under
`archived_data/static_lying_2026-10-22/`: 264 raw recordings and their cached
derived slices. Project-wide scans skip `archived_data`; explicitly choose the
archive's `raw_sessions` folder to inspect it. The active `dataset_index.csv`
contains one entry per active recording. The archive retains its own index,
the complete original index, reconciliation details, and a checksummed move
manifest. Historical training exclusions remain recorded. New session numbers
advance beyond both active and archived filenames to avoid recycling old IDs.

Gaps over 0.5 seconds break trajectories and signal lines. Playback displays no
position during a gap. Coordinate-derived speed is computed separately for each
target using actual positive time intervals up to 0.5 seconds; a value above the
project's 3.5 m/s threshold is a review flag. It is distinct from the recorded
radar-speed scalar. Fall-label rows and contiguous label runs are annotation
counts, not verified physical fall-event counts. Elapsed hours sum complete
session spans; observed hours exclude recording gaps.

**Export analysis** creates a new timestamped folder with filtered session,
activity and participant CSV summaries, four overview PNG charts, filter
settings, a JSON summary, and the complete scan's source inventory and load
issues. It never overwrites recordings. For model evaluation, keep normalized
participants or whole sessions separate before creating overlapping windows.

---

## Live fall-model comparison

The original detector is retired from live inference; its files in
`app/ml/weights/` are retained as an archive. The five active models are: **XGBoost, MiniROCKET, TCN, GRU,
and a separately retrained LSTM-attention baseline**.

Install the optional comparison dependencies with
`python -m pip install -r requirements-ml.txt`, then start `python -m app.main`.
Connect the radar, **lock a target**, and open **Fall monitor → Compare models**.
The model table shows scores, validation-selected thresholds, availability, and
last detection times. The event timeline shows which models flagged motion and
when, with timing relative to the first flag. Export the timeline as CSV before
closing if you want to retain it; the monitor keeps the latest 200 event groups
plus unresolved suspected-fall warnings.

Four of five model flags create a **suspected fall**, followed by combined motion
validation. During the first 1–1.25 seconds, continuous observed reverse travel
can reject the candidate (at least 0.5 m displacement, an opposing heading, and
sufficient fresh coverage). Later movement is not used as a reversal veto because
it may be recovery after a fall. Up to five seconds are available for sustained
low-motion evidence; fresh low motion can confirm earlier. A stable centroid can
also support confirmation despite a stale radial-speed estimate. After four-model
consensus, 1.5 seconds of target disappearance can confirm if valid radar reports
continue and contain no eligible, non-noise target. This is recorded separately
as `post_fall_disappearance`, not measured stillness. Predicted/Searching output
alone is not enough: communication silence and ambiguous/rejected measurements
still leave a suspected-fall warning.

Communication loss, ambiguous observations or an inconclusive five-second check leaves a persistent
amber **suspected fall** warning. It survives inference resets and reconnects in
the current app session. Review these in **Fall monitor → Compare models** and
use **Acknowledge suspected-fall warnings** to clear the banner while preserving
event history. Suspected events do not increment the confirmed-fall counter.
Exports include the validation outcome, reason, acknowledgement and reversal
measurements. Export before closing; warnings are not stored across app restarts.

Run `python tools/verify_combined_validation.py --actual-models` to reproduce the
supplied-session checks. Activity labels are ignored and all model artifacts are
fingerprinted. Recorded coordinates are already filtered, so rerunning inference
is an integration test rather than an exact raw-UART reproduction. The reversal
thresholds are provisional and need testing on additional independent sessions.

### Ignore a constant noise source

Right-click its radar marker and choose **Mark this target as noise**, or click
the marker, open **Live radar → Noise exclusions**, and select **Mark focused
target as noise**. The default exclusion radius is 300 mm and is adjustable.
Dashed circles show ignored locations. Detections inside them are removed before
clustering, target matching, lost-target searching and model input; recycled
person labels or radar slots do not bypass the exclusion. Detections from a real
person inside the same circle are also ignored, so keep each radius small.

Noise exclusions are saved between app launches and reconnects. Remove individual
circles or clear them in the same tab; clear them if the sensor is moved.
`python tools/verify_combined_validation.py --actual-models --screenshot --out reports/noise_and_disappearance`
replays the supplied session with the current confirmation policy. The session
does not contain raw association results, so that replay explicitly assumes its
non-Active rows represent the healthy-stream disappearance described by the user.

The profile selector offers two evaluation/training protocols:

- **Within-person sessions:** every participant appears in training, validation,
  and testing, but complete recordings stay in exactly one partition. This tests
  new recordings from known people and is the default comparison profile.
- **Unseen participants:** participants are separated across partitions. This
  tests generalization to new people. It remains available as a separate profile.

Randomly splitting overlapping windows is deliberately avoided. Session splits
are stratified by participant and whether a recording has fall labels. Sources,
session assignments, package versions, thresholds, metrics, and test predictions
are saved with each training run under `app/ml/comparison_weights/`. These are
held-out **window** metrics, not verified physical-event recall. Only four
participants have fall labels, so one split is not conclusive evidence of a winner.

Comparison models use fresh `Active` observations, a two-second trailing window
resampled to 10 Hz, and predictions roughly every 0.5 seconds. Gaps over 0.5 seconds
and target changes reset their history. Inference and model loading run outside
the GUI thread; stale results are discarded and inference errors are displayed
per model. Unavailable models are shown individually; live tracking continues even if model dependencies are missing.

A comparison detection requires two successive fresh predictions above its
threshold. It is a **model flag**, not a confirmed physical fall. The live ensemble requires four of the five active models to flag the event.
The older deployed LSTM is excluded from inference and voting; the newer retrained
LSTM remains active. Flags within eight seconds for the same target
and profile are grouped for inspection; this grouping is not ground truth.
The comparison observes the locked target; it does not independently monitor
all radar targets in Track All mode. Scores are not calibrated probabilities.

To reproduce training without overwriting original weights:

```powershell
python tools/train_comparison_models.py --split sessions --epochs 25
python tools/train_comparison_models.py --split participants --epochs 25 --no-publish
```

Each command creates a new run directory. The first publishes the default live
comparison manifest after all five models finish; `--no-publish` preserves that
default while saving another selectable profile. Restart the app to discover new
profiles. Only load trusted local artifacts, since MiniROCKET serialization uses
joblib. Model descriptions and measured results are in
`reports/model_comparison/results.md`.

Replay a held-out recording through the five-model comparison worker without a sensor:

```powershell
python tools/replay_model_comparison.py --screenshot
```

This writes an event JSON and an offscreen monitor preview under
`reports/model_comparison/`. It is a software integration check, not a hardware
validation or an independent evaluation of the archived original weights.

---

## Streaming reliability and firmware update

Live TCP/USB ingestion, parsing and tracking run outside the GUI thread. The UI
renders the newest state at up to 30 Hz and never replays a growing event backlog.
Display smoothing defaults to two samples (~50 ms at 10 Hz); model inputs retain
the original ten-sample position smoothing and the existing feature transform.
A short batch of coalesced frames is spaced at the configured 10 Hz nominal sensor
period; the raw LD2450 protocol carries no capture timestamps. Backlogs longer
than five frames are discarded and model windows restart.

With automatic reconnect enabled, three seconds with no bytes or five seconds
with no valid radar frames closes and reconnects the stream. Boot/status messages
cannot keep stale location data marked healthy. Receiver freshness uses monotonic
time. Connection resets clear frame fragments, target IDs and model windows;
positions disappear after 0.6 seconds without fresh observations. Connection health
shows measured frame age rather than a fixed latency estimate.

CSV/JSON recording uses a bounded background writer. If storage falls behind, the
app reports the recording error instead of blocking tracking. Event and raw-packet
previews are bounded independently of the stream parser.

**Restart the toolkit to apply the Python changes.** The ESP32 also needs the updated
firmware uploaded before board-side fixes take effect. For the device emitting
`OMNISENSE_BOOT`, the updated sketch is
`D:/FYP/Omnisense-/firmware/esp32_omnisense_firmware/esp32_omnisense_firmware.ino`
with its adjacent `RadarStream.h`. The toolkit's own Wi-Fi bridge has the same
helper inlined in `firmware/esp32_ld2450_wifi_bridge.ino`, so that sketch requires
no local headers. Set `STA_SSID` and `STA_PASS` in the sketch before uploading
(or enable `USE_AP_MODE`). Open it in its own Arduino sketch folder, separate
from the USB bridge sketch. Both forward complete 30-byte reports, track
partial writes, keep only a bounded newest frame per client, and disconnect a
client whose in-flight send takes 250 ms. TCP writes are non-blocking; a slow
client cannot stall UART. The OmniSense firmware retains its configured UART baud
rather than flipping baud after a temporary stream gap. Its MQTT worker and
saved Wi-Fi configuration are preserved.

These sketches target Arduino ESP32 core 3.x. The OmniSense sketch additionally
requires PubSubClient. The USB bridge drops bytes when its host is absent instead
of blocking. Firmware changes do not take effect on the physical device until
flashed; a software replay does not establish Wi-Fi/hardware performance.

---

## 📁 Project Structure

Below is a detailed breakdown of every folder and file in this repository and its purpose.

### Root Directory
- **`README.md`**: This documentation file.
- **`requirements.txt`**: Python dependencies required to run the desktop application (e.g., PySide6, PyTorch, numpy).
- **`pyproject.toml`**: Python project metadata and build system configuration.

### `firmware/` (Hardware Code)
Contains the C++/Arduino code flashed onto the microcontroller attached to the radar.
- **`esp32_ld2450_wifi_bridge.ino`**: The ESP32 firmware that reads the LD2450's serial UART data and wirelessly streams it over your local Wi-Fi network via a TCP socket. This allows the sensor to be mounted anywhere in the room without a USB cable attached to the PC.

### `tests/` (Unit Testing)
- **`test_ld2450.py`**: Automated unit tests to verify that the byte-parsing and tracking logic work correctly against raw mock hex data.

---

### `app/` (Desktop Application Source Code)
This is the core Python application directory.

#### App Entry Point
- **`main.py`**: The main entry point. Run `python -m app.main` to start the application. It initializes the Qt Application and spawns the MainWindow.
- **`config.py`**: Contains global configuration constants, default baud rates, and UI styling parameters.

#### `app/gui/` (User Interface)
Contains all PySide6 (Qt) widgets and windows.
- **`main_window.py`**: The primary window that glues all panels, toolbars, and layout constraints together.
- **`radar_view.py`**: The 2D top-down canvas that visually renders the room, targets, trails, and velocity vectors.
- **`packet_view.py`**: A debugging panel that displays the raw hexadecimal byte streams received from the radar.
- **`target_panel.py`**: A sidebar listing all actively tracked targets and their real-time coordinates/speed.
- **`telemetry_panel.py`**: A dashboard showing live metrics like distance, angle, and data resolution.
- **`diagnostics_panel.py`**: Shows system health (FPS, CPU/RAM usage, packet drop rate).
- **`tuning_panel.py`**: Provides sliders to tune the physics engine live (e.g., max speed, jump thresholds).
- **`fall_monitor.py`**: A dedicated floating window that displays the AI's real-time fall probability and a counter of total falls detected.

#### `app/ml/` (Machine Learning & AI)
Handles the PyTorch neural network integration for fall detection.
- **`fall_detector.py`**: The `LSTMAttention` model class. It collects 20 frames of tracking data and feeds it into the PyTorch model to calculate a "fall probability" (0.0 to 1.0).
- **`weights/`**: Directory containing the trained AI artifacts:
  - `fall_lstm_baseline.pt`: The trained PyTorch model weights.
  - `feature_mean.npy` & `feature_std.npy`: Numpy scalers used to normalize live data before feeding it to the AI.

#### `app/models/` (Data Structures)
Defines the memory structures used to pass data around the app.
- **`packet.py`**: Represents a single decoded frame from the radar.
- **`target.py`**: The `Target` dataclass representing a single human (stores X, Y, speed, and calculated fall alerts).

#### `app/net/` & `app/serial/` (Communications)
Handles getting data from the sensor to the PC.
- **`net/socket_worker.py`**: A background thread that connects to the ESP32 over Wi-Fi (TCP) to receive data wirelessly.
- **`serial/serial_worker.py`**: A background thread that connects directly to the sensor via a USB-to-TTL cable (COM port).
- **`serial/serial_reader.py`**: A utility function to scan the PC for available COM ports.

#### `app/parser/` (Byte Decoding)
Converts raw electrical bytes into meaningful numbers.
- **`packet_parser.py`**: Scans the incoming continuous byte stream to find the specific "Header" and "Footer" bytes that define a single LD2450 frame.
- **`packet_decoder.py`**: Translates the valid hex bytes into X (mm), Y (mm), and Speed (mm/s) values based on Hi-Link's protocol datasheet.

#### `app/recording/` (Data Collection)
- **`recorder.py`**: Captures live target tracking data and saves it to a `.csv` file. Useful for creating datasets to fine-tune the Fall Detection AI.
- **`playback.py`**: Utility to replay old `.csv` files as if they were live data.

#### `app/tracker/` (Physics Engine & Filtering)
The brains behind the target tracking, designed to fix hardware ghosts and multipath errors.
- **`tracker.py`**: The core tracking engine. It associates incoming radar points to existing people, rejects impossible movements (e.g., jumping 3 meters in 0.1 seconds), handles Target Focus Lock, and acts as the gatekeeper before data reaches the UI.
- **`kalman.py`**: A 2D Constant-Velocity Kalman Filter. It mathematically smooths out coordinate jitter and predicts where a target should be if the sensor temporarily loses them.

#### `app/utils/` & `app/visualization/` (Helpers)
- **`utils/logger.py`**: Configures the colored terminal output for debugging.
- **`utils/settings.py`**: Manages saving/loading user preferences (like window size) using QSettings.
- **`visualization/renderer.py`**: Contains the raw PyQt painter functions used to draw the circles and grids on the radar canvas.
- **`visualization/trails.py`**: Manages the fading memory of where a target was recently to draw "comet trails" behind moving people.
