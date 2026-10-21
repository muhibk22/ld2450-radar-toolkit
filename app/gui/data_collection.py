from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QFont
from ..recording.session_paths import next_session_path
from .responsive import AdaptiveGrid, scroll_page
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QGridLayout, QGroupBox, QMessageBox, QFileDialog
)

class DataCollectionWindow(QWidget):
    """
    Session recording with activity hotkeys and participant metadata.
    """
    
    # Signals to communicate with MainWindow/Recorder
    start_recording_req = Signal(str, dict) # filename, metadata dict
    stop_recording_req = Signal(bool) # True = save, False = discard
    label_changed = Signal(str) # The new active label

    HOTKEYS = {
        "1": "Walking",
        "2": "Standing / idle",
        "3": "Sitting down (controlled)",
        "4": "Kneeling down (controlled)",
        "5": "Lying down (controlled)",
        "6": "Fall onset",
        "7": "Post-fall stillness",
        "8": "Recovery / standing back up"
    }

    def __init__(self, main_window_ref):
        super().__init__()
        self.main_window = main_window_ref
        self.is_recording = False
        self.current_label = "2: Standing / idle" # Default Baseline
        
        self.setWindowTitle("Record sessions")
        self.resize(720, 780)
        self.setMinimumSize(560, 540)
        
        self._setup_ui()
        self._setup_shortcuts()
        
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        content = QWidget()
        layout = QVBoxLayout(content)
        outer.addWidget(scroll_page(content), 1)
        
        # --- Layer 2: Metadata ---
        meta_group = QGroupBox("Session details")
        meta_layout = QGridLayout()
        
        meta_layout.addWidget(QLabel("Volunteer ID:"), 0, 0)
        self.val_volunteer = QLineEdit("V1")
        meta_layout.addWidget(self.val_volunteer, 0, 1)
        
        meta_layout.addWidget(QLabel("Fall Subtype:"), 1, 0)
        self.val_fall = QComboBox()
        self.val_fall.addItems(["None", "Forward", "Backward", "Sideways", "From-Sit", "From-Kneel"])
        meta_layout.addWidget(self.val_fall, 1, 1)
        
        meta_layout.addWidget(QLabel("Pace Variant:"), 2, 0)
        self.val_pace = QComboBox()
        self.val_pace.addItems(["Normal", "Slow", "Rushed"])
        meta_layout.addWidget(self.val_pace, 2, 1)
        
        meta_group.setLayout(meta_layout)
        layout.addWidget(meta_group)
        
        # --- Current State Display ---
        state_group = QGroupBox("Current activity")
        state_layout = QVBoxLayout()
        self.lbl_current_action = QLabel(self.current_label)
        self.lbl_current_action.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_current_action.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.lbl_current_action.setWordWrap(True)
        self.lbl_current_action.setMinimumWidth(0)
        self.lbl_current_action.setStyleSheet("color: #3B82F6;")
        state_layout.addWidget(self.lbl_current_action)
        state_group.setLayout(state_layout)
        layout.addWidget(state_group)
        
        # --- Layer 1: Hotkeys ---
        hotkey_group = QGroupBox("Activity labels · keyboard 1–8")
        hotkey_layout = QVBoxLayout(hotkey_group)
        hotkey_buttons = []
        self.buttons = {}
        for key, desc in self.HOTKEYS.items():
            btn = QPushButton(f"[{key}] {desc}")
            btn.setCheckable(True)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda checked, k=key: self._on_hotkey_pressed(k))
            self.buttons[key] = btn
            hotkey_buttons.append(btn)
                
        # Set default active
        self.buttons["2"].setChecked(True)
        hotkey_layout.addWidget(AdaptiveGrid(hotkey_buttons, minimum_column_width=265))
        layout.addWidget(hotkey_group)
        
        # --- Start/Stop Controls ---
        self.btn_record = QPushButton("● Start Session")
        self.btn_record.setMinimumHeight(50)
        self.btn_record.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.btn_record.setStyleSheet("background-color: #EF4444; color: white;")
        self.btn_record.clicked.connect(self._toggle_recording)
        outer.addWidget(self.btn_record)

    def _setup_shortcuts(self):
        for key in self.HOTKEYS.keys():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda k=key: self._on_hotkey_pressed(k))

    def _on_hotkey_pressed(self, key: str):
        # Update UI
        for k, btn in self.buttons.items():
            btn.setChecked(k == key)
            
        self.current_label = f"{key}: {self.HOTKEYS[key]}"
        self.lbl_current_action.setText(self.current_label)
        
        # Change style based on danger
        if key in ["6", "7"]:
            self.lbl_current_action.setStyleSheet("color: #EF4444;") # Red for fall
        else:
            self.lbl_current_action.setStyleSheet("color: #3B82F6;") # Blue for ADL
            
        self.label_changed.emit(self.current_label)

    def _toggle_recording(self):
        if not self.is_recording:
            # Check if tracker is locked
            if not self.main_window.tracker.locked_target_id:
                QMessageBox.warning(self, "Safety Check", "You MUST lock onto a target in the main window before starting data collection!")
                return
                
            volunteer = self.val_volunteer.text().strip().lower().replace(" ", "")
            if not volunteer:
                volunteer = "volunteer01"
                
            # Include archived IDs so curation never causes session-name reuse.
            base_dir = Path.cwd() / "data" / "raw_sessions"
            base_dir.mkdir(parents=True, exist_ok=True)
            default_filename = str(next_session_path(base_dir, volunteer))
                
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Dataset Session", default_filename, "CSV Files (*.csv)"
            )
            
            if filename:
                metadata = {
                    "volunteer_id": self.val_volunteer.text(),
                    "fall_subtype": self.val_fall.currentText(),
                    "pace_variant": self.val_pace.currentText(),
                }
                
                # Emit initial label so recorder has it
                self.label_changed.emit(self.current_label)
                self.start_recording_req.emit(filename, metadata)
                
                self.is_recording = True
                self.btn_record.setText("⏹ Stop Session")
                self.btn_record.setStyleSheet("background-color: #10B981; color: white;")
                
                # Disable metadata inputs during recording
                self.val_volunteer.setEnabled(False)
                self.val_fall.setEnabled(False)
                self.val_pace.setEnabled(False)
        else:
            # Prompt user to Save or Discard the session
            box = QMessageBox(self)
            box.setWindowTitle("Session Finished")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("Session recording stopped.")
            frame_count = getattr(self.main_window.recorder, 'record_count', 0)
            box.setInformativeText(f"Recorded {frame_count} frames.\n\nDo you want to SAVE this session or DISCARD it?")
            btn_save = box.addButton("Save Session", QMessageBox.ButtonRole.AcceptRole)
            btn_discard = box.addButton("Discard Session", QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = box.addButton("Cancel (Keep Recording)", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_save)
            
            box.exec()
            clicked = box.clickedButton()
            
            if clicked == btn_cancel:
                # Cancelled: Keep recording active
                return

            save_session = (clicked == btn_save)
            self.stop_recording_req.emit(save_session)
            self.is_recording = False
            self.btn_record.setText("● Start Session")
            self.btn_record.setStyleSheet("background-color: #EF4444; color: white;")
            
            self.val_volunteer.setEnabled(True)
            self.val_fall.setEnabled(True)
            self.val_pace.setEnabled(True)
            
            if save_session:
                QMessageBox.information(self, "Saved", "Session successfully saved and recorded in dataset index.")
            else:
                QMessageBox.information(self, "Discarded", "Session discarded. File has been deleted.")

    def closeEvent(self, event):
        if self.is_recording:
            box = QMessageBox(self)
            box.setWindowTitle("Recording in Progress")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("A dataset session is currently recording.")
            box.setInformativeText("Do you want to save the session, discard it, or cancel?")
            btn_save = box.addButton("Save & Close", QMessageBox.ButtonRole.AcceptRole)
            btn_discard = box.addButton("Discard & Close", QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_save)
            
            box.exec()
            clicked = box.clickedButton()
            if clicked == btn_cancel:
                event.ignore()
                return

            save_session = (clicked == btn_save)
            self.stop_recording_req.emit(save_session)
            self.is_recording = False
            self.btn_record.setText("● Start Session")
            self.btn_record.setStyleSheet("background-color: #EF4444; color: white;")
            self.val_volunteer.setEnabled(True)
            self.val_fall.setEnabled(True)
            self.val_pace.setEnabled(True)

        event.accept()

