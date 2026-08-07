"""
Application Entry Point for LD2450 Desktop Toolkit.
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.gui.main_window import MainWindow
from app.utils.logger import setup_logger

def main():
    """Initializes logging, Qt application instance, and launches main window."""
    logger = setup_logger("ld2450")
    logger.info("Starting LD2450 Desktop Toolkit...")

    # Enable High DPI scaling for modern displays
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("LD2450 Desktop Toolkit")
    app.setOrganizationName("HLK-LD2450")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
