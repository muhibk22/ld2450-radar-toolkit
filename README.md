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
