# LD2450 mmWave Radar Tracker Toolkit

A comprehensive desktop application, firmware, and machine learning toolkit for tracking human targets and detecting falls using the **Hi-Link HLK-LD2450 24GHz mmWave Radar**.

This project features a PyQt/PySide6 graphical interface for real-time visualization, a robust physics-based target tracking engine (with Kalman filtering), and a PyTorch LSTM neural network for fall detection.

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
