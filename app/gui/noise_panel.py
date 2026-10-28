"""Review and remove user-selected noise exclusions."""
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QListWidget,QListWidgetItem,QPushButton,QSpinBox,QHBoxLayout


class NoisePanel(QWidget):
    mark_requested=Signal()
    remove_requested=Signal(str)
    clear_requested=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        note=QLabel('Click a target on the radar, then mark it as noise. Right-clicking a target also offers this action. '
                    'Detections inside each exclusion circle are ignored before tracking. '
                    'Keep the radius small and remove exclusions if the radar moves.')
        note.setWordWrap(True)
        layout.addWidget(note)
        controls=QHBoxLayout()
        controls.addWidget(QLabel('Exclusion radius (mm)'))
        self.radius=QSpinBox()
        self.radius.setRange(50,1500)
        self.radius.setValue(300)
        self.radius.setSingleStep(50)
        controls.addWidget(self.radius)
        self.mark_button=QPushButton('Mark focused target as noise')
        self.mark_button.clicked.connect(lambda checked=False:self.mark_requested.emit())
        controls.addWidget(self.mark_button)
        layout.addLayout(controls)
        self.sources=QListWidget()
        layout.addWidget(self.sources)
        remove=QPushButton('Remove selected exclusion')
        remove.clicked.connect(self._remove)
        layout.addWidget(remove)
        clear=QPushButton('Clear all exclusions')
        clear.clicked.connect(lambda checked=False:self.clear_requested.emit())
        layout.addWidget(clear)

    def set_zones(self,zones):
        self.sources.clear()
        for zone in zones:
            item=QListWidgetItem(f"Noise {zone['id']} — X {zone['x_mm']:.0f}, Y {zone['y_mm']:.0f} mm; radius {zone['radius_mm']:.0f} mm")
            item.setData(Qt.ItemDataRole.UserRole,zone['id'])
            self.sources.addItem(item)

    def _remove(self):
        item=self.sources.currentItem()
        if item:
            self.remove_requested.emit(item.data(Qt.ItemDataRole.UserRole))
