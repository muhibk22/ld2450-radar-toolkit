"""Launch offline analysis without a radar connection or fall-model initialization.

Usage: python -m app.dataset_visualization [directory]
"""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from .gui.dataset_studio import DatasetStudioWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Radar Dataset Visualization Studio")
    app.setOrganizationName("HLK-LD2450")
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    window = DatasetStudioWindow(directory=directory)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
