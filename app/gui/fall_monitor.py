"""
Separate window for monitoring Fall Detection state and statistics.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QFrame
)
from PySide6.QtGui import QFont

class FallMonitorWindow(QWidget):
    """
    A dedicated floating window to display live fall detection state and fall counts.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fall Detection Monitor")
        self.resize(400, 300)
        
        # We want it to be a floating tool window if parent is set
        if parent:
            self.setWindowFlags(Qt.WindowType.Tool)

        self.fall_count = 0
        self.is_falling = False
        
        # Debounce logic so one fall event doesn't increment count 20 times per second
        self.cooldown_frames = 0
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("AI Fall Monitor")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Current State
        self.lbl_state = QLabel("NORMAL")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setFont(QFont("Segoe UI", 24, QFont.Weight.ExtraBold))
        self.lbl_state.setStyleSheet("color: #10B981; background-color: #064E3B; border-radius: 10px; padding: 10px;")
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
                background-color: #F59E0B;
                width: 10px;
            }
        """)
        prob_layout.addWidget(prob_label)
        prob_layout.addWidget(self.bar_prob)
        layout.addLayout(prob_layout)
        
        # Fall Count
        count_layout = QHBoxLayout()
        lbl_count_title = QLabel("Total Falls Detected:")
        lbl_count_title.setFont(QFont("Segoe UI", 14))
        self.lbl_count_val = QLabel("0")
        self.lbl_count_val.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.lbl_count_val.setStyleSheet("color: #F43F5E;")
        count_layout.addWidget(lbl_count_title)
        count_layout.addWidget(self.lbl_count_val)
        layout.addLayout(count_layout)
        
        layout.addStretch()
        
        # Reset Button
        self.btn_reset = QPushButton("Reset Fall Count")
        self.btn_reset.setStyleSheet("background-color: #334155; color: white; padding: 10px; font-weight: bold;")
        self.btn_reset.clicked.connect(self.reset_count)
        layout.addWidget(self.btn_reset)
        
        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Segoe UI';
            }
        """)

    def reset_count(self):
        self.fall_count = 0
        self.lbl_count_val.setText("0")
        self.cooldown_frames = 0

    @Slot(bool, float)
    def update_fall_status(self, is_falling: bool, probability: float):
        """Updates the monitor with the latest prediction."""
        # Decrease cooldown
        if self.cooldown_frames > 0:
            self.cooldown_frames -= 1
            
        prob_pct = int(probability * 100)
        self.bar_prob.setValue(prob_pct)
        
        if prob_pct > 75:
            self.bar_prob.setStyleSheet("QProgressBar::chunk { background-color: #EF4444; }")
        elif prob_pct > 30:
            self.bar_prob.setStyleSheet("QProgressBar::chunk { background-color: #F59E0B; }")
        else:
            self.bar_prob.setStyleSheet("QProgressBar::chunk { background-color: #10B981; }")

        if is_falling:
            self.lbl_state.setText("⚠ FALL DETECTED ⚠")
            self.lbl_state.setStyleSheet("color: white; background-color: #EF4444; border-radius: 10px; padding: 10px;")
            
            # Increment count only if not in cooldown (e.g. 60 frames = 3 seconds)
            if not self.is_falling and self.cooldown_frames == 0:
                self.fall_count += 1
                self.lbl_count_val.setText(str(self.fall_count))
                self.cooldown_frames = 60  # Require 3 seconds before counting another fall
                
            self.is_falling = True
        else:
            self.lbl_state.setText("NORMAL")
            self.lbl_state.setStyleSheet("color: #10B981; background-color: #064E3B; border-radius: 10px; padding: 10px;")
            self.is_falling = False
