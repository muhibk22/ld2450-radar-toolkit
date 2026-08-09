"""
Target Information Panel Widget displaying persistent target telemetry tables.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel
)
from typing import List
from ..models.target import Target

class TargetPanelWidget(QWidget):
    """
    Live Telemetry Panel detailing current persistent target entities.
    """

    HEADERS = ["Person ID", "Status", "X (mm)", "Y (mm)", "Speed (mm/s)", "Distance (mm)", "Angle (°)", "Time (s)"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        title = QLabel("Persistent Human Tracking Telemetry")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #F8FAFC;")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1E293B;
                color: #E2E8F0;
                gridline-color: #334155;
                border: 1px solid #334155;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #94A3B8;
                font-weight: bold;
                padding: 4px;
            }
        """)

        layout.addWidget(self.table)

    @Slot(list)
    def update_targets(self, targets: List[Target]):
        """Refreshes telemetry table rows with persistent target metrics."""
        valid_targets = [t for t in targets if t.valid]
        self.table.setRowCount(len(valid_targets))

        for row, t in enumerate(valid_targets):
            items = [
                QTableWidgetItem(str(t.id)),
                QTableWidgetItem(str(t.status)),
                QTableWidgetItem(f"{t.x:.1f}"),
                QTableWidgetItem(f"{t.y:.1f}"),
                QTableWidgetItem(f"{t.speed:.1f}"),
                QTableWidgetItem(f"{t.distance:.1f}"),
                QTableWidgetItem(f"{t.angle:.1f}"),
                QTableWidgetItem(f"{t.tracking_time:.1f}"),
            ]
            
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if t.status == "Active":
                    item.setForeground(Qt.GlobalColor.green)
                elif t.status == "Predicted":
                    item.setForeground(Qt.GlobalColor.yellow)
                self.table.setItem(row, col, item)
