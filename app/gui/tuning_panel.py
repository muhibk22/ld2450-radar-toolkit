"""
Tracker Parameter Tuning & Calibration Panel Widget.
Provides dynamic field visibility per mode, explicit Apply Settings button,
and QSpinBox arrow button styling.
"""

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QSpinBox,
    QLabel, QGroupBox, QPushButton, QMessageBox
)

class TuningPanelWidget(QWidget):
    """
    Interactive tuning panel for configuring sensor filtering modes and physical limits.
    """
    settings_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # 1. Mode Explanation Box
        grp_explain = QGroupBox("Physical Mode & Filtering Explanation")
        grp_explain.setStyleSheet("QGroupBox { font-weight: bold; color: #F8FAFC; border: 1px solid #334155; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        e_layout = QVBoxLayout(grp_explain)
        
        self.lbl_explanation = QLabel()
        self.lbl_explanation.setWordWrap(True)
        self.lbl_explanation.setStyleSheet("color: #94A3B8; font-size: 11px; line-height: 1.3;")
        e_layout.addWidget(self.lbl_explanation)
        layout.addWidget(grp_explain)

        # 2. Control Form Group
        grp_controls = QGroupBox("Filter Controls & Physical Thresholds")
        grp_controls.setStyleSheet("QGroupBox { font-weight: bold; color: #F8FAFC; border: 1px solid #334155; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        self.f_layout = QFormLayout(grp_controls)

        # Mode Selector
        self.cb_mode = QComboBox()
        self.cb_mode.addItems([
            "Physical Gate + Rolling Average (Recommended)",
            "Rolling Average (N packets)",
            "Physical Gate + Kalman Filter",
            "Raw Hardware (No Filtering)"
        ])
        self.cb_mode.setCurrentIndex(0)
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self.f_layout.addRow("Filtering Mode:", self.cb_mode)

        # Rolling Window Size (N)
        self.lbl_window = QLabel("Rolling Window (N):")
        self.sp_window = QSpinBox()
        self.sp_window.setRange(1, 30)
        self.sp_window.setValue(10)
        self.sp_window.setSuffix(" packets")
        self.f_layout.addRow(self.lbl_window, self.sp_window)

        # Max Physical Speed Gate
        self.lbl_max_speed = QLabel("Max Physical Speed:")
        self.sp_max_speed = QSpinBox()
        self.sp_max_speed.setRange(500, 15000)
        self.sp_max_speed.setSingleStep(500)
        self.sp_max_speed.setValue(4000)
        self.sp_max_speed.setSuffix(" mm/s")
        self.f_layout.addRow(self.lbl_max_speed, self.sp_max_speed)

        # Max Frame Jump Threshold
        self.lbl_max_jump = QLabel("Max Frame Jump:")
        self.sp_max_jump = QSpinBox()
        self.sp_max_jump.setRange(50, 3000)
        self.sp_max_jump.setSingleStep(50)
        self.sp_max_jump.setValue(500)
        self.sp_max_jump.setSuffix(" mm")
        self.f_layout.addRow(self.lbl_max_jump, self.sp_max_jump)

        # Anti-Blink Hold Duration
        self.lbl_hold = QLabel("Anti-Blink Hold:")
        self.sp_hold = QSpinBox()
        self.sp_hold.setRange(0, 50)
        self.sp_hold.setValue(15)
        self.sp_hold.setSuffix(" frames")
        self.f_layout.addRow(self.lbl_hold, self.sp_hold)

        layout.addWidget(grp_controls)

        # Action Buttons Layout (Apply Settings & Reset Defaults)
        btn_layout = QHBoxLayout()

        self.btn_apply = QPushButton("Apply Settings")
        self.btn_apply.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 7px;")
        self.btn_apply.clicked.connect(self.apply_settings)
        btn_layout.addWidget(self.btn_apply)

        btn_reset = QPushButton("Reset Defaults")
        btn_reset.setStyleSheet("background-color: #334155; color: white; padding: 7px;")
        btn_reset.clicked.connect(self.reset_defaults)
        btn_layout.addWidget(btn_reset)

        layout.addLayout(btn_layout)
        layout.addStretch()

        # Custom SpinBox QSS styling for up/down arrow buttons
        self.setStyleSheet("""
            QFormLayout, QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QComboBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
                color: #E2E8F0;
            }
            QSpinBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding-right: 20px;
                color: #E2E8F0;
                height: 26px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                width: 16px;
                background-color: #334155;
                border: 1px solid #475569;
            }
            QSpinBox::up-button {
                subcontrol-position: top right;
            }
            QSpinBox::down-button {
                subcontrol-position: bottom right;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #0284C7;
            }
        """)

        # Initialize field visibility based on default mode
        self._on_mode_changed(0)

    def _on_mode_changed(self, index: int):
        """Dynamically shows/hides control fields relevant to the selected mode."""
        if index == 0:  # Physical Gate + Rolling Average
            self.lbl_window.show()
            self.sp_window.show()
            self.lbl_max_speed.show()
            self.sp_max_speed.show()
            self.lbl_max_jump.show()
            self.sp_max_jump.show()
            self.lbl_hold.show()
            self.sp_hold.show()
            self.lbl_explanation.setText(
                "<b>Physical Gate + Rolling Average:</b> Evaluates incoming measurements. "
                "Discards any frame jump > Max Frame Jump (outlier rejection), then averages the last N validated packets. "
                "Eliminates erratic jumps and thermal noise."
            )
        elif index == 1:  # Rolling Average (N packets)
            self.lbl_window.show()
            self.sp_window.show()
            self.lbl_max_speed.hide()
            self.sp_max_speed.hide()
            self.lbl_max_jump.hide()
            self.sp_max_jump.hide()
            self.lbl_hold.show()
            self.sp_hold.show()
            self.lbl_explanation.setText(
                "<b>Rolling Average:</b> Computes coordinates as the centroid of the last N packets. "
                "Smooths position, but does not reject single-frame outlier jumps."
            )
        elif index == 2:  # Physical Gate + Kalman Filter
            self.lbl_window.hide()
            self.sp_window.hide()
            self.lbl_max_speed.show()
            self.sp_max_speed.show()
            self.lbl_max_jump.show()
            self.sp_max_jump.show()
            self.lbl_hold.show()
            self.sp_hold.show()
            self.lbl_explanation.setText(
                "<b>Physical Gate + Kalman Filter:</b> Rejects physical speed outliers first, "
                "then applies 2D state space Kalman filtering (position & velocity smoothing)."
            )
        elif index == 3:  # Raw Hardware
            self.lbl_window.hide()
            self.sp_window.hide()
            self.lbl_max_speed.hide()
            self.sp_max_speed.hide()
            self.lbl_max_jump.hide()
            self.sp_max_jump.hide()
            self.lbl_hold.hide()
            self.sp_hold.hide()
            self.lbl_explanation.setText(
                "<b>Raw Hardware:</b> Directly displays raw un-filtered radar target coordinates. "
                "Shows raw hardware noise and jitter without filtering."
            )

    def apply_settings(self):
        """Emits currently configured settings to the TargetTracker."""
        settings = self.get_settings()
        self.settings_changed.emit(settings)
        QMessageBox.information(self, "Settings Applied", f"Successfully applied tracking mode: {self.cb_mode.currentText()}")

    def reset_defaults(self):
        """Resets controls to default values and applies them."""
        self.cb_mode.setCurrentIndex(0)
        self.sp_window.setValue(10)
        self.sp_max_speed.setValue(4000)
        self.sp_max_jump.setValue(500)
        self.sp_hold.setValue(15)
        self.apply_settings()

    def get_settings(self) -> dict:
        mode_idx = self.cb_mode.currentIndex()
        mode_keys = ["PHYSICAL_GATE_AVG", "ROLLING_AVG", "PHYSICAL_GATE_KALMAN", "RAW"]
        return {
            "mode": mode_keys[mode_idx],
            "window_size": self.sp_window.value(),
            "max_speed_mms": self.sp_max_speed.value(),
            "max_jump_mm": self.sp_max_jump.value(),
            "hold_frames": self.sp_hold.value(),
        }
