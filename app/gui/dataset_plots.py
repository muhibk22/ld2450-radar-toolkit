"""Native pyqtgraph plots used only by the offline Dataset Visualization Studio."""
from __future__ import annotations

from collections import Counter
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem

from ..analysis.dataset import LABELS, Session

BACKGROUND = "#0f172a"
FOREGROUND = "#cbd5e1"
COLORS = {-1: "#a1a1aa", 1: "#38bdf8", 2: "#94a3b8", 3: "#c084fc",
          4: "#facc15", 5: "#34d399", 6: "#fb7185", 7: "#a5b4fc", 8: "#fb923c"}
SHORT_LABELS = {-1: "Unknown", 1: "Walk", 2: "Idle", 3: "Sit", 4: "Kneel",
                5: "Lie down", 6: "Fall onset", 7: "Post-fall", 8: "Recovery"}


def chart(title: str, x: str, y: str) -> pg.PlotWidget:
    widget = pg.PlotWidget(background=BACKGROUND, title=title)
    widget.setLabel("bottom", x)
    widget.setLabel("left", y)
    widget.showGrid(x=True, y=True, alpha=.15)
    for axis in ("left", "bottom"):
        widget.getAxis(axis).setTextPen(FOREGROUND)
        widget.getAxis(axis).setPen("#475569")
    widget.setMinimumHeight(190)
    return widget


def bars(plot, labels, values, colors=None):
    plot.clear()
    plot.getAxis("bottom").setTicks([list(enumerate(labels))])
    if not labels:
        return
    plot.addItem(pg.BarGraphItem(x=np.arange(len(values)), height=values, width=.65,
                                brushes=colors or [COLORS[1]]*len(values), pen=None))
    plot.setXRange(-.7, len(labels)-.3, padding=0)
    plot.setYRange(0, max(1, max(values))*1.12, padding=0)


def overview_plots(plots: list, sessions: list[Session]):
    counts = Counter()
    for session in sessions:
        counts.update(session.counts)
    codes = sorted(counts)
    bars(plots[0], [SHORT_LABELS.get(c, str(c)) for c in codes], [counts[c]/1000 for c in codes],
         [COLORS.get(c, COLORS[-1]) for c in codes])
    people = sorted({s.person for s in sessions})
    bars(plots[1], people, [sum(s.rows for s in sessions if s.person == p)/1000 for p in people])
    plots[2].clear()
    plots[3].clear()
    plots[3].getAxis("bottom").setTicks([list(enumerate([SHORT_LABELS.get(c, str(c)) for c in codes]))])
    if not sessions:
        return
    positions = np.concatenate([t.values[:, 1:3] for s in sessions for t in s.tracks])
    hist, xedges, yedges = np.histogram2d(positions[:, 0], positions[:, 1], bins=96)
    image = pg.ImageItem(axisOrder="col-major")
    image.setImage(np.log1p(hist), autoLevels=True)
    lookup = pg.colormap.get("viridis").getLookupTable(alpha=True)
    lookup[0, 3] = 0  # Empty spatial bins should leave the chart background visible.
    image.setLookupTable(lookup)
    transform = QTransform()
    transform.translate(float(xedges[0]), float(yedges[0]))
    transform.scale(float((xedges[-1]-xedges[0])/96), float((yedges[-1]-yedges[0])/96))
    image.setTransform(transform)
    plots[2].addItem(image)
    plots[2].setAspectLocked(True)
    plots[2].autoRange()
    # A percentile range rather than a mean helps expose overlap between classes.
    for i, code in enumerate(codes):
        speeds = np.concatenate([np.abs(t.values[t.labels == code, 3])
                                 for s in sessions for t in s.tracks if s.counts[code]])
        if not len(speeds):
            continue
        low, q1, median, q3, high = np.percentile(speeds, [5, 25, 50, 75, 95])
        color = COLORS.get(code, COLORS[-1])
        plots[3].plot([i, i], [low, high], pen=pg.mkPen(color, width=1.5))
        plots[3].plot([i, i], [q1, q3], pen=pg.mkPen(color, width=9))
        plots[3].plot([i], [median], pen=None, symbol="o", symbolSize=7,
                      symbolBrush=FOREGROUND, symbolPen=BACKGROUND)
    plots[3].autoRange()
    plots[3].setXRange(-.7, len(codes)-.3, padding=0)


class HumanMarker(pg.GraphicsObject):
    """Fixed-pixel schematic human centered on a measured target position."""
    def __init__(self):
        super().__init__()
        self.color = COLORS[1]
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(20)

    def boundingRect(self):
        return QRectF(-17, -34, 34, 53)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(QColor(self.color), 2.5))
        painter.setBrush(QColor(BACKGROUND))
        painter.drawEllipse(QRectF(-5, -31, 10, 10))
        painter.drawLines([QLineF(0, -21, 0, 0), QLineF(-13, -5, 0, -16),
                           QLineF(0, -16, 13, -5), QLineF(-12, 16, 0, 0), QLineF(0, 0, 12, 16)])
        painter.setBrush(QColor(FOREGROUND))
        painter.drawEllipse(QRectF(-2, -2, 4, 4))

    def locate(self, x, y, code):
        self.color = COLORS.get(code, COLORS[-1])
        self.setPos(float(x), float(y))
        self.show()
        self.update()
