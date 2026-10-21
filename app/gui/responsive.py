"""Small native layout helpers shared by the radar workspace and dataset studio."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QLayout, QScrollArea, QSizePolicy, QWidget


class ScrollPanelWheelFilter(QObject):
    """Keep wheel scrolling over plot viewports inside their own scroll panel."""
    def __init__(self, area, viewports):
        super().__init__(area)
        self.area = area
        for viewport in viewports:
            viewport.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        bar = self.area.verticalScrollBar()
        delta = event.pixelDelta().y()
        if not delta:
            delta = event.angleDelta().y()/120 * bar.singleStep() * QApplication.wheelScrollLines()
        bar.setValue(bar.value()-round(delta))
        event.accept()
        return True


class FlowLayout(QLayout):
    """Wrap complete controls or field groups rather than clipping a toolbar."""
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left()+margins.right(), margins.top()+margins.bottom())

    def _arrange(self, rect, measure):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, height = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            width = min(hint.width(), max(1, area.width()))
            if x > area.x() and x+width > area.right()+1:
                x = area.x()
                y += height+self.spacing()
                height = 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, hint.height())))
            x += width+self.spacing()
            height = max(height, hint.height())
        return y+height-rect.y()+margins.bottom()


class AdaptiveGrid(QWidget):
    """Use readable stacked charts when two columns no longer fit."""
    def __init__(self, widgets, minimum_column_width=310, parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self.minimum_column_width = minimum_column_width
        self.columns = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._arrange(2)

    def _arrange(self, columns):
        if self.columns == columns:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        for i, widget in enumerate(self.widgets):
            self.grid.addWidget(widget, i//columns, i%columns)
        for column in range(2):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(2 if event.size().width() >= 2*self.minimum_column_width+12 else 1)


def scroll_page(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setMinimumSize(0, 0)
    area.setWidget(widget)
    return area


def labeled_control(text, control):
    group = QWidget()
    layout = QHBoxLayout(group)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(text))
    layout.addWidget(control, 1)
    return group
