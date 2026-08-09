"""
Live Diagnostics Panel displaying bandwidth, packet rate, errors, and serial state.
"""

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QGroupBox

class DiagnosticsPanelWidget(QWidget):
    """
    Live protocol diagnostic panel displaying operational metrics.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        grp = QGroupBox("Live Protocol & Hardware Diagnostics")
        grp.setStyleSheet("QGroupBox { font-weight: bold; color: #F8FAFC; border: 1px solid #334155; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        g_layout = QGridLayout(grp)

        self.lbl_packets_sec = QLabel("0.0 /s")
        self.lbl_bytes_sec = QLabel("0.0 B/s")
        self.lbl_latency = QLabel("< 1 ms")
        self.lbl_dropped = QLabel("0")
        self.lbl_corrupt = QLabel("0")
        self.lbl_reconnects = QLabel("0")
        self.lbl_com = QLabel("None")
        self.lbl_baud = QLabel("256000")

        metrics_def = [
            ("Packets / Sec:", self.lbl_packets_sec, 0, 0),
            ("Bytes / Sec:", self.lbl_bytes_sec, 0, 2),
            ("Average Latency:", self.lbl_latency, 1, 0),
            ("Dropped Bytes:", self.lbl_dropped, 1, 2),
            ("Corrupt Packets:", self.lbl_corrupt, 2, 0),
            ("Reconnect Count:", self.lbl_reconnects, 2, 2),
            ("Current COM:", self.lbl_com, 3, 0),
            ("Current Baud:", self.lbl_baud, 3, 2),
        ]

        for title, lbl, r, c in metrics_def:
            t_lbl = QLabel(title)
            t_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: bold;")
            lbl.setStyleSheet("color: #38BDF8; font-size: 12px; font-family: 'Consolas', monospace;")
            g_layout.addWidget(t_lbl, r, c)
            g_layout.addWidget(lbl, r, c + 1)

        layout.addWidget(grp)

    @Slot(dict)
    def update_diagnostics(self, stats: dict):
        """Updates diagnostic counters."""
        if "packets_per_sec" in stats:
            self.lbl_packets_sec.setText(f"{stats['packets_per_sec']} /s")
        if "bytes_per_sec" in stats:
            self.lbl_bytes_sec.setText(f"{stats['bytes_per_sec']} B/s")
        if "latency_ms" in stats:
            self.lbl_latency.setText(f"{stats['latency_ms']} ms")
        if "dropped_packets" in stats:
            self.lbl_dropped.setText(str(stats["dropped_packets"]))
        if "corrupt_packets" in stats:
            self.lbl_corrupt.setText(str(stats["corrupt_packets"]))
        if "reconnect_count" in stats:
            self.lbl_reconnects.setText(str(stats["reconnect_count"]))
        if "com_port" in stats:
            self.lbl_com.setText(str(stats["com_port"]))
        if "baud_rate" in stats:
            self.lbl_baud.setText(str(stats["baud_rate"]))
