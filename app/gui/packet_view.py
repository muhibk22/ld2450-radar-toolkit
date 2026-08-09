"""
Raw Packet Viewer Widget displaying live hex packet stream and raw UART stream.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QFileDialog, QMessageBox, QTabWidget, QPlainTextEdit
)
from PySide6.QtGui import QGuiApplication
import time
from typing import List
from ..models.packet import Packet

class PacketViewWidget(QWidget):
    """
    Live Hex Packet Inspector Widget with Parsed Frames & Unfiltered Raw Stream inspection.
    """

    MAX_ROWS = 500  # Rolling buffer limit for display

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_paused = False
        self.raw_packet_history: List[Packet] = []
        self.raw_stream_bytes = bytearray()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header toolbar
        toolbar = QHBoxLayout()
        title = QLabel("Raw Packet Viewer")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #F8FAFC;")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.btn_pause = QPushButton("Pause Stream")
        self.btn_pause.clicked.connect(self._toggle_pause)
        toolbar.addWidget(self.btn_pause)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_view)
        toolbar.addWidget(btn_clear)

        btn_copy = QPushButton("Copy Selected")
        btn_copy.clicked.connect(self._copy_selected_packet)
        toolbar.addWidget(btn_copy)

        btn_export = QPushButton("Export Stream...")
        btn_export.clicked.connect(self._export_packets)
        toolbar.addWidget(btn_export)

        layout.addLayout(toolbar)

        # Inner Sub-Tabs: Parsed Packet Frames vs Unfiltered Raw UART Stream
        self.sub_tabs = QTabWidget()

        # 1. Parsed Packet Frames Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Pkt #", "Time", "Size", "Header", "Footer", "Raw Hex Bytes"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0F172A;
                color: #38BDF8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                gridline-color: #1E293B;
                border: None;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #94A3B8;
                font-weight: bold;
                padding: 4px;
            }
        """)
        self.sub_tabs.addTab(self.table, "Parsed Packet Frames")

        # 2. Unfiltered Raw UART Stream Text View
        self.txt_raw_stream = QPlainTextEdit()
        self.txt_raw_stream.setReadOnly(True)
        self.txt_raw_stream.setMaximumBlockCount(1000)
        self.txt_raw_stream.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0F172A;
                color: #F59E0B;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border: None;
            }
        """)
        self.sub_tabs.addTab(self.txt_raw_stream, "Unfiltered Raw UART Stream (Hex)")

        layout.addWidget(self.sub_tabs)

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.setText("Resume Stream")
            self.btn_pause.setStyleSheet("background-color: #F59E0B; color: white;")
        else:
            self.btn_pause.setText("Pause Stream")
            self.btn_pause.setStyleSheet("")

    def _clear_view(self):
        self.table.setRowCount(0)
        self.txt_raw_stream.clear()
        self.raw_packet_history.clear()
        self.raw_stream_bytes.clear()

    @Slot(object)
    def add_packet(self, pkt: Packet):
        """Appends a new raw packet frame row."""
        self.raw_packet_history.append(pkt)
        if self.is_paused:
            return

        row = self.table.rowCount()
        if row >= self.MAX_ROWS:
            self.table.removeRow(0)
            row = self.table.rowCount()

        self.table.insertRow(row)

        ts_str = time.strftime("%H:%M:%S", time.localtime(pkt.timestamp)) + f".{int((pkt.timestamp % 1) * 1000):03d}"
        hdr_status = "OK" if pkt.header_valid else "ERR"
        ftr_status = "OK" if pkt.footer_valid else "ERR"

        items = [
            QTableWidgetItem(str(pkt.sequence_id)),
            QTableWidgetItem(ts_str),
            QTableWidgetItem(f"{pkt.size_bytes}B"),
            QTableWidgetItem(hdr_status),
            QTableWidgetItem(ftr_status),
            QTableWidgetItem(pkt.hex_string),
        ]

        for col, item in enumerate(items):
            if col in (0, 1, 2, 3, 4):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)

        self.table.scrollToBottom()

    @Slot(bytes)
    def add_raw_chunk(self, chunk: bytes):
        """Appends incoming raw serial bytes chunk to unfiltered text inspector."""
        if self.is_paused or not chunk:
            return
        
        self.raw_stream_bytes.extend(chunk)
        ts_str = time.strftime("%H:%M:%S", time.localtime())
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        
        self.txt_raw_stream.appendPlainText(f"[{ts_str}] ({len(chunk)}B) {hex_str}")

    def _copy_selected_packet(self):
        if self.sub_tabs.currentIndex() == 0:
            selected_rows = self.table.selectionModel().selectedRows()
            if not selected_rows:
                return
            row = selected_rows[0].row()
            hex_item = self.table.item(row, 5)
            if hex_item:
                QGuiApplication.clipboard().setText(hex_item.text())
        else:
            QGuiApplication.clipboard().setText(self.txt_raw_stream.textCursor().selectedText() or self.txt_raw_stream.toPlainText())

    def _export_packets(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Raw Hex Stream", "", "Text Files (*.txt);;Log Files (*.log)")
        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            if self.sub_tabs.currentIndex() == 0:
                for pkt in self.raw_packet_history:
                    f.write(f"[{pkt.sequence_id}] {pkt.timestamp} | {pkt.hex_string}\n")
            else:
                f.write(self.txt_raw_stream.toPlainText())
        QMessageBox.information(self, "Export Successful", f"Saved stream log to {path}.")
