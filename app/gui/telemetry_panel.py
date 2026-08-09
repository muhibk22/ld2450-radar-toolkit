"""
Decoded Telemetry & Protocol Field Decomposition Panel Widget.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QGroupBox
)
from typing import List, Dict
from ..models.target import Target
from ..models.packet import Packet

class TelemetryPanelWidget(QWidget):
    """
    Decoded Telemetry Table detailing Target 0..2 fields
    alongside an Unknown Byte Inspector for full protocol visibility.
    """

    TARGET_HEADERS = ["Slot", "Valid", "X (mm)", "Y (mm)", "Speed (mm/s)", "Distance (mm)", "Angle (°)"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # 1. Decoded Targets Section
        grp_targets = QGroupBox("Decoded Targets (Target 0, 1, 2)")
        grp_targets.setStyleSheet("QGroupBox { font-weight: bold; color: #F8FAFC; border: 1px solid #334155; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        t_layout = QVBoxLayout(grp_targets)

        self.target_table = QTableWidget(3, len(self.TARGET_HEADERS))
        self.target_table.setHorizontalHeaderLabels(self.TARGET_HEADERS)
        self.target_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.target_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.target_table.setStyleSheet("""
            QTableWidget {
                background-color: #1E293B;
                color: #E2E8F0;
                gridline-color: #334155;
                border: None;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #94A3B8;
                font-weight: bold;
                padding: 4px;
            }
        """)
        t_layout.addWidget(self.target_table)
        layout.addWidget(grp_targets)

        # 2. Protocol Field & Unknown Byte Inspection Section
        grp_unknown = QGroupBox("Unmapped / Protocol Byte Fields")
        grp_unknown.setStyleSheet("QGroupBox { font-weight: bold; color: #F8FAFC; border: 1px solid #334155; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        u_layout = QVBoxLayout(grp_unknown)

        self.unknown_table = QTableWidget(0, 2)
        self.unknown_table.setHorizontalHeaderLabels(["Field Name", "Raw Value (Hex)"])
        self.unknown_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.unknown_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.unknown_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.unknown_table.setStyleSheet("""
            QTableWidget {
                background-color: #1E293B;
                color: #F59E0B;
                font-family: 'Consolas', monospace;
                gridline-color: #334155;
                border: None;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #94A3B8;
                font-weight: bold;
                padding: 4px;
            }
        """)
        u_layout.addWidget(self.unknown_table)
        layout.addWidget(grp_unknown)

        self._init_empty_target_rows()

    def _init_empty_target_rows(self):
        for i in range(3):
            items = [
                QTableWidgetItem(f"Target {i}"),
                QTableWidgetItem("No"),
                QTableWidgetItem("0.0"),
                QTableWidgetItem("0.0"),
                QTableWidgetItem("0.0"),
                QTableWidgetItem("0.0"),
                QTableWidgetItem("0.0"),
            ]
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.target_table.setItem(i, col, item)

    @Slot(object)
    def update_packet(self, pkt: Packet):
        """Refreshes decoded targets and unknown byte table with latest packet data."""
        # Update Target 0, 1, 2
        for i in range(3):
            if i < len(pkt.targets):
                t = pkt.targets[i]
                items = [
                    QTableWidgetItem(str(t.id)),
                    QTableWidgetItem("Yes" if t.valid else "No"),
                    QTableWidgetItem(f"{t.x:.1f}"),
                    QTableWidgetItem(f"{t.y:.1f}"),
                    QTableWidgetItem(f"{t.speed:.1f}"),
                    QTableWidgetItem(f"{t.distance:.1f}"),
                    QTableWidgetItem(f"{t.angle:.1f}"),
                ]
            else:
                items = [QTableWidgetItem(f"Target {i}"), QTableWidgetItem("No"), QTableWidgetItem("0.0"), QTableWidgetItem("0.0"), QTableWidgetItem("0.0"), QTableWidgetItem("0.0"), QTableWidgetItem("0.0")]

            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if t.valid if (i < len(pkt.targets)) else False:
                    item.setForeground(Qt.GlobalColor.green)
                self.target_table.setItem(i, col, item)

        # Update Unknown Bytes Table
        unknown_map = pkt.unknown_bytes
        self.unknown_table.setRowCount(len(unknown_map))
        for row, (field_name, hex_val) in enumerate(unknown_map.items()):
            item_name = QTableWidgetItem(field_name)
            item_val = QTableWidgetItem(hex_val)
            item_val.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.unknown_table.setItem(row, 0, item_name)
            self.unknown_table.setItem(row, 1, item_val)
