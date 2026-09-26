"""
Separate window for monitoring Fall Detection state, alert history, and statistics.
Supports two-stage alerts: PRE_ALERT (yellow) and CONFIRMED (red).
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QFrame,
    QTextEdit, QSplitter
)
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtCore import QUrl
import os

class FallMonitorWindow(QWidget):
    """
    A dedicated floating window to display live fall detection state, 
    two-stage alert visualization (pre-alert + confirmed), alert history, and fall counts.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fall Detection Monitor")
        self.resize(450, 500)
        
        # We want it to be a floating tool window if parent is set
        if parent:
            self.setWindowFlags(Qt.WindowType.Tool)

        self.fall_count = 0
        self.is_falling = False
        self._current_stage = "normal"
        
        # Debounce logic so one fall event doesn't increment count 20 times per second
        self.cooldown_frames = 0
        
        # Sound alert (optional)
        self._sound_enabled = True
        self._sound_effect = None
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("AI Fall Monitor")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Current State (supports NORMAL / PRE-ALERT / CONFIRMED)
        self.lbl_state = QLabel("NORMAL")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setFont(QFont("Segoe UI", 22, QFont.Weight.ExtraBold))
        self.lbl_state.setMinimumHeight(60)
        self._set_state_style("normal")
        layout.addWidget(self.lbl_state)
        
        # Probability Bar
        prob_layout = QVBoxLayout()
        prob_label = QLabel("Live Fall Probability:")
        prob_label.setFont(QFont("Segoe UI", 10))
        self.bar_prob = QProgressBar()
        self.bar_prob.setRange(0, 100)
        self.bar_prob.setValue(0)
        self.bar_prob.setTextVisible(True)
        self.bar_prob.setStyleSheet("""
            QProgressBar {
                border: 2px solid #334155;
                border-radius: 5px;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                width: 10px;
            }
        """)
        prob_layout.addWidget(prob_label)
        prob_layout.addWidget(self.bar_prob)
        layout.addLayout(prob_layout)
        
        # Fall Count
        count_layout = QHBoxLayout()
        lbl_count_title = QLabel("Confirmed Falls:")
        lbl_count_title.setFont(QFont("Segoe UI", 14))
        self.lbl_count_val = QLabel("0")
        self.lbl_count_val.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.lbl_count_val.setStyleSheet("color: #F43F5E;")
        count_layout.addWidget(lbl_count_title)
        count_layout.addWidget(self.lbl_count_val)
        layout.addLayout(count_layout)
        
        # Alert History Log
        history_label = QLabel("Alert History:")
        history_label.setFont(QFont("Segoe UI", 10))
        layout.addWidget(history_label)
        
        self.txt_history = QTextEdit()
        self.txt_history.setReadOnly(True)
        self.txt_history.setMaximumHeight(150)
        self.txt_history.setFont(QFont("Consolas", 9))
        self.txt_history.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        layout.addWidget(self.txt_history)
        
        # Control Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_reset = QPushButton("Reset Count")
        self.btn_reset.setStyleSheet("background-color: #334155; color: white; padding: 8px; font-weight: bold;")
        self.btn_reset.clicked.connect(self.reset_count)
        btn_layout.addWidget(self.btn_reset)
        
        self.btn_sound = QPushButton("🔔 Sound: ON")
        self.btn_sound.setStyleSheet("background-color: #334155; color: white; padding: 8px; font-weight: bold;")
        self.btn_sound.clicked.connect(self._toggle_sound)
        btn_layout.addWidget(self.btn_sound)
        
        layout.addLayout(btn_layout)
        
        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Segoe UI';
            }
        """)

    def _set_state_style(self, stage: str):
        """Update the state label appearance based on alert stage."""
        if stage == "confirmed":
            self.lbl_state.setText("🚨 FALL CONFIRMED 🚨")
            self.lbl_state.setStyleSheet(
                "color: white; background-color: #DC2626; border-radius: 10px; padding: 10px;"
                "border: 3px solid #FCA5A5;"
            )
        elif stage == "pre_alert":
            self.lbl_state.setText("⚠ POSSIBLE FALL ⚠")
            self.lbl_state.setStyleSheet(
                "color: #1E293B; background-color: #F59E0B; border-radius: 10px; padding: 10px;"
                "border: 3px solid #FCD34D;"
            )
        else:
            self.lbl_state.setText("NORMAL")
            self.lbl_state.setStyleSheet(
                "color: #10B981; background-color: #064E3B; border-radius: 10px; padding: 10px;"
            )

    def _toggle_sound(self):
        self._sound_enabled = not self._sound_enabled
        if self._sound_enabled:
            self.btn_sound.setText("🔔 Sound: ON")
        else:
            self.btn_sound.setText("🔕 Sound: OFF")

    def reset_count(self):
        self.fall_count = 0
        self.lbl_count_val.setText("0")
        self.cooldown_frames = 0

    def update_alert_history(self, history: list[dict]):
        """Update the alert history log from PostFallValidator's history."""
        if not history:
            return
        
        lines = []
        for event in reversed(history[-10:]):  # Show last 10 events
            time_str = event.get("time", "??:??:??")
            event_type = event.get("type", "UNKNOWN")
            prob = event.get("probability", 0)
            reason = event.get("reason", "")
            
            if event_type == "CONFIRMED":
                prefix = "🔴"
            else:
                prefix = "🟡"
            
            lines.append(f"{prefix} [{time_str}] {event_type} (p={prob:.2f}) - {reason}")
        
        self.txt_history.setPlainText("\n".join(lines))

    @Slot(bool, float, str)
    def update_fall_status(self, is_falling: bool, probability: float, stage: str = "normal"):
        """Updates the monitor with the latest prediction and alert stage."""
        # Decrease cooldown
        if self.cooldown_frames > 0:
            self.cooldown_frames -= 1
            
        prob_pct = int(probability * 100)
        self.bar_prob.setValue(prob_pct)
        
        # Color the probability bar based on severity
        if prob_pct > 75:
            self.bar_prob.setStyleSheet("""
                QProgressBar { border: 2px solid #334155; border-radius: 5px; text-align: center; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #EF4444; }
            """)
        elif prob_pct > 30:
            self.bar_prob.setStyleSheet("""
                QProgressBar { border: 2px solid #334155; border-radius: 5px; text-align: center; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #F59E0B; }
            """)
        else:
            self.bar_prob.setStyleSheet("""
                QProgressBar { border: 2px solid #334155; border-radius: 5px; text-align: center; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #10B981; }
            """)

        # Update state display based on alert stage
        if stage != self._current_stage:
            self._set_state_style(stage)
            self._current_stage = stage

        # Track confirmed falls
        if stage == "confirmed":
            if not self.is_falling and self.cooldown_frames == 0:
                self.fall_count += 1
                self.lbl_count_val.setText(str(self.fall_count))
                self.cooldown_frames = 100  # ~5 seconds at 20fps before counting another
            self.is_falling = True
        else:
            self.is_falling = False
