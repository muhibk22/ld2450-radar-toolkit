"""
2D Radar Canvas displaying target positions, motion trails, velocity vectors, target focus lock reticle, and persistent IDs.
"""

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg
import numpy as np
import math
from typing import List, Dict, Optional
from ..models.target import Target
from ..visualization.renderer import get_target_color
from ..visualization.trails import MotionTrailManager
from ..config import COLOR_BACKGROUND, COLOR_GRID, DEFAULT_RADAR_MAX_X, DEFAULT_RADAR_MAX_Y

class RadarViewWidget(QWidget):
    """
    2D Radar Canvas displaying persistent targets, motion trail histories,
    directional velocity vectors, and interactive Click-to-Lock target focus reticles.
    """
    target_clicked = Signal(str)  # Emitted when user clicks a target scatter point

    def __init__(self, parent=None):
        super().__init__(parent)
        self.trail_manager = MotionTrailManager()
        self.display_unit_meters = False
        self.max_x = DEFAULT_RADAR_MAX_X
        self.max_y = DEFAULT_RADAR_MAX_Y
        self.locked_target_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOption("background", COLOR_BACKGROUND)
        pg.setConfigOption("foreground", "#94A3B8")

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setAspectLocked(True)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.getAxis("bottom").setGrid(200)
        self.plot_widget.getAxis("left").setGrid(200)
        
        self.plot_widget.setLabel("bottom", "X Horizontal Position (-X Left | +X Right) [mm]")
        self.plot_widget.setLabel("left", "Y Depth Distance Ahead (+Y) [mm]")
        self.plot_widget.setXRange(-self.max_x, self.max_x)
        self.plot_widget.setYRange(-500, self.max_y)

        layout.addWidget(self.plot_widget)

        self._draw_grid_and_origin()

        self.scatter_item = pg.ScatterPlotItem(size=16, pxMode=True)
        self.scatter_item.sigClicked.connect(self._on_scatter_clicked)
        self.plot_widget.addItem(self.scatter_item)

        # Reticle indicator for Locked Target Focus
        self.lock_reticle = pg.ScatterPlotItem(
            size=28, symbol="o", pen=pg.mkPen("#F59E0B", width=3), brush=pg.mkBrush(0, 0, 0, 0)
        )
        self.plot_widget.addItem(self.lock_reticle)

        # target_id -> TextItem
        self.text_labels: Dict[str, pg.TextItem] = {}
        # target_id -> PlotCurveItem (Trail)
        self.trail_curves: Dict[str, pg.PlotCurveItem] = {}
        # target_id -> PlotCurveItem (Velocity Vector)
        self.vector_items: Dict[str, pg.PlotCurveItem] = {}

    def _draw_grid_and_origin(self):
        """Origin marker and polar distance arcs."""
        origin = pg.ScatterPlotItem(
            x=[0], y=[0], size=16, symbol="t", pen=pg.mkPen("#38BDF8", width=2), brush=pg.mkBrush("#0284C7")
        )
        self.plot_widget.addItem(origin)

        angles = np.linspace(-math.pi / 3, math.pi / 3, 100)
        for r_m in range(1, 9):
            r_mm = r_m * 1000.0
            arc_x = r_mm * np.sin(angles)
            arc_y = r_mm * np.cos(angles)
            arc_item = pg.PlotCurveItem(
                arc_x, arc_y, pen=pg.mkPen(COLOR_GRID, width=1, style=Qt.PenStyle.DashLine)
            )
            self.plot_widget.addItem(arc_item)

    def set_locked_target(self, target_id: Optional[str]):
        """Sets active target focus lock ID and updates golden reticle."""
        self.locked_target_id = target_id if target_id and target_id != "Track All Targets" else None
        if not self.locked_target_id:
            self.lock_reticle.setData([])

    def _on_scatter_clicked(self, plot, points):
        if points:
            pt = points[0]
            data = pt.data()
            if data and "tid" in data:
                self.target_clicked.emit(data["tid"])

    def set_display_unit_meters(self, meters: bool):
        """Switches display axes between mm and meters."""
        self.display_unit_meters = meters
        if meters:
            self.plot_widget.setLabel("bottom", "X Horizontal Position (-X Left | +X Right) [m]")
            self.plot_widget.setLabel("left", "Y Depth Distance Ahead (+Y) [m]")
            self.plot_widget.setXRange(-self.max_x / 1000.0, self.max_x / 1000.0)
            self.plot_widget.setYRange(-0.5, self.max_y / 1000.0)
        else:
            self.plot_widget.setLabel("bottom", "X Horizontal Position (-X Left | +X Right) [mm]")
            self.plot_widget.setLabel("left", "Y Depth Distance Ahead (+Y) [mm]")
            self.plot_widget.setXRange(-self.max_x, self.max_x)
            self.plot_widget.setYRange(-500, self.max_y)

    def set_trail_length(self, length: int):
        """Updates max trail points stored per target."""
        self.trail_manager.set_max_length(length)

    @Slot(list)
    def update_targets(self, targets: List[Target]):
        """Refreshes plot with tracked targets, trails, velocity arrows, and focus reticle."""
        valid_targets = [t for t in targets if t.valid and t.y > 0]
        active_ids = {str(t.id) for t in valid_targets}

        spots = []
        scale = 0.001 if self.display_unit_meters else 1.0
        reticle_spot = []

        for t in valid_targets:
            tid = str(t.id)
            
            if getattr(t, 'fall_alert', False):
                color_hex = "#EF4444"  # Alert Red
                pen = pg.mkPen("#DC2626", width=3)
            else:
                color_hex = get_target_color(t.id)
                pen = pg.mkPen(color_hex, width=2)
                
            brush = pg.mkBrush(color_hex)

            x_pos = t.x * scale
            y_pos = t.y * scale

            spots.append({
                "pos": (x_pos, y_pos),
                "pen": pen,
                "brush": brush,
                "symbol": "o",
                "data": {"tid": tid}
            })

            # Check if this target is locked
            if self.locked_target_id and tid == self.locked_target_id:
                # If fall detected, reticle turns RED. Otherwise Golden.
                reticle_color = "#EF4444" if getattr(t, 'fall_alert', False) else "#F59E0B"
                self.lock_reticle.setPen(pg.mkPen(reticle_color, width=3))
                reticle_spot.append({"pos": (x_pos, y_pos)})

            # Record motion trail point
            self.trail_manager.add_point(tid, x_pos, y_pos)

            # Motion Trail Curve
            trail_pts = self.trail_manager.get_trail(tid)
            if tid not in self.trail_curves:
                curve = pg.PlotCurveItem(pen=pg.mkPen(color_hex, width=2, style=Qt.PenStyle.DotLine))
                self.plot_widget.addItem(curve)
                self.trail_curves[tid] = curve
            
            if trail_pts and len(trail_pts) >= 2:
                tx, ty = zip(*trail_pts)
                self.trail_curves[tid].setData(np.array(tx, dtype=np.float64), np.array(ty, dtype=np.float64))
            else:
                self.trail_curves[tid].clear()

            # Directional Velocity Vector Arrow
            if tid not in self.vector_items:
                vcurve = pg.PlotCurveItem(pen=pg.mkPen("#F59E0B", width=2))
                self.plot_widget.addItem(vcurve)
                self.vector_items[tid] = vcurve
            
            speed_vec_len = (t.speed * 0.5) * scale
            rad = math.radians(t.angle)
            vx_end = x_pos + speed_vec_len * math.sin(rad)
            vy_end = y_pos + speed_vec_len * math.cos(rad)
            self.vector_items[tid].setData(
                np.array([x_pos, vx_end], dtype=np.float64),
                np.array([y_pos, vy_end], dtype=np.float64)
            )

            # Text Label
            if tid not in self.text_labels:
                txt = pg.TextItem(text=tid, color=color_hex, anchor=(-0.2, 0.5))
                txt.setFont(pg.QtGui.QFont("Segoe UI", 10, pg.QtGui.QFont.Weight.Bold))
                self.plot_widget.addItem(txt)
                self.text_labels[tid] = txt
            
            self.text_labels[tid].setPos(x_pos, y_pos)
            unit_str = "m/s" if self.display_unit_meters else "mm/s"
            disp_speed = t.speed / 1000.0 if self.display_unit_meters else t.speed
            lock_prefix = "🔒 " if (self.locked_target_id and tid == self.locked_target_id) else ""
            fall_warn = " ⚠ FALL!" if getattr(t, 'fall_alert', False) else ""
            self.text_labels[tid].setText(f"{lock_prefix}{tid} ({disp_speed:.1f} {unit_str}) [{t.status}]{fall_warn}")

        self.scatter_item.setData(spots)
        self.lock_reticle.setData(reticle_spot)

        # Cleanup missing targets
        for tid in list(self.text_labels.keys()):
            if tid not in active_ids:
                self.plot_widget.removeItem(self.text_labels[tid])
                del self.text_labels[tid]
        
        for tid in list(self.trail_curves.keys()):
            if tid not in active_ids:
                self.plot_widget.removeItem(self.trail_curves[tid])
                del self.trail_curves[tid]

        for tid in list(self.vector_items.keys()):
            if tid not in active_ids:
                self.plot_widget.removeItem(self.vector_items[tid])
                del self.vector_items[tid]
