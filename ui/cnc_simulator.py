"""
CNC Toolpath Simulator Module for VLM4CNC.
Provides an interactive 2D CNC toolpath visualizer inspired by tools like MechSimulator.
Features:
  - G-Code motion parser (G00, G01, G02, G03, G81, G83, S, F, Z).
  - High-performance QPainter interactive 2D canvas with pan, zoom, grid, and stock bounds.
  - Rapid moves (G00 dashed orange/red), cutting moves (G01 solid blue with tool cut band).
  - Canned drilling cycles (G81/G83) with hole position and diameter markers.
  - Animated cutter with tool diameter Ø and crosshair cursor.
  - Playback controls: Run, Pause, Step, Reset, Speed slider (1x - 10x), Scrubber slider.
  - Real-time Digital Readout (DRO): Current X, Y, Z, Feedrate, Spindle RPM, active G-code block.
  - Toolpath statistics: Cut distance, Rapid distance, Total moves, Estimated cycle time.
"""

from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple, Union

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


@dataclass
class ToolpathSegment:
    """Represents a single parsed motion command in a G-Code program."""
    motion_type: str  # "G00", "G01", "G02", "G03", "G81", "G83", "OTHER"
    start: Tuple[float, float, float]  # (X, Y, Z)
    end: Tuple[float, float, float]    # (X, Y, Z)
    feed: float
    spindle: int
    line_num: int
    raw_text: str
    length: float = 0.0
    is_cutting: bool = False
    drill_depth: float = 0.0
    hole_diameter: float = 3.0

    def __post_init__(self):
        # Calculate 3D euclidean distance
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        dz = self.end[2] - self.start[2]
        self.length = math.sqrt(dx * dx + dy * dy + dz * dz)
        # Cutting if G01/G02/G03/G81/G83 and moving at or below Z <= 0
        if self.motion_type in ("G01", "G02", "G03"):
            self.is_cutting = (self.start[2] <= 0.0 or self.end[2] <= 0.0)
        elif self.motion_type in ("G81", "G83"):
            self.is_cutting = True
        else:
            self.is_cutting = False


class GCodeToolpathParser:
    """Parses standard ISO G-Code into a list of ToolpathSegments for visualization."""

    def __init__(self):
        self.segments: List[ToolpathSegment] = []
        self.total_cut_dist: float = 0.0
        self.total_rapid_dist: float = 0.0
        self.est_time_seconds: float = 0.0
        self.bbox_min: Tuple[float, float] = (0.0, 0.0)
        self.bbox_max: Tuple[float, float] = (100.0, 100.0)

    def parse(self, gcode_text: str, default_tool_dia: float = 3.0) -> List[ToolpathSegment]:
        """Parse G-Code text into sequential motion segments."""
        self.segments = []
        self.total_cut_dist = 0.0
        self.total_rapid_dist = 0.0
        self.est_time_seconds = 0.0

        current_x = 0.0
        current_y = 0.0
        current_z = 50.0  # safe Z default
        current_feed = 300.0
        current_spindle = 1500
        current_motion = "G00"
        tool_diameter = default_tool_dia

        min_x, min_y = 0.0, 0.0
        max_x, max_y = 100.0, 100.0

        lines = gcode_text.splitlines()
        for idx, line in enumerate(lines, start=1):
            raw_line = line.strip()
            if not raw_line or raw_line.startswith("%"):
                continue

            # Check for tool diameter in comments, e.g. "( TOOL DIA: Ø3.000 mm ... )"
            dia_match = re.search(r"TOOL DIA:\s*Ø?([0-9.]+)", raw_line, re.IGNORECASE)
            if dia_match:
                try:
                    tool_diameter = float(dia_match.group(1))
                except ValueError:
                    pass

            # Strip comments for code token parsing: "(...)" or ";..."
            clean_code = re.sub(r"\(.*?\)", "", raw_line)
            clean_code = re.sub(r";.*$", "", clean_code).strip()
            if not clean_code:
                continue

            # Update Spindle S
            s_match = re.search(r"\bS([0-9]+)\b", clean_code, re.IGNORECASE)
            if s_match:
                current_spindle = int(s_match.group(1))

            # Update Feedrate F
            f_match = re.search(r"\bF([0-9.]+)\b", clean_code, re.IGNORECASE)
            if f_match:
                current_feed = float(f_match.group(1))

            # Motion code detection
            m_code = re.search(r"\b(G00|G01|G02|G03|G80|G81|G83|G0|G1|G2|G3)\b", clean_code, re.IGNORECASE)
            if m_code:
                code_str = m_code.group(1).upper()
                if code_str == "G0":
                    code_str = "G00"
                elif code_str == "G1":
                    code_str = "G01"
                elif code_str == "G2":
                    code_str = "G02"
                elif code_str == "G3":
                    code_str = "G03"

                if code_str == "G80":
                    current_motion = "G00"
                else:
                    current_motion = code_str

            # Coordinate extraction
            x_match = re.search(r"\bX(-?[0-9.]+)\b", clean_code, re.IGNORECASE)
            y_match = re.search(r"\bY(-?[0-9.]+)\b", clean_code, re.IGNORECASE)
            z_match = re.search(r"\bZ(-?[0-9.]+)\b", clean_code, re.IGNORECASE)

            target_x = float(x_match.group(1)) if x_match else current_x
            target_y = float(y_match.group(1)) if y_match else current_y
            target_z = float(z_match.group(1)) if z_match else current_z

            has_motion = (x_match or y_match or z_match)

            if has_motion:
                start_pt = (current_x, current_y, current_z)
                end_pt = (target_x, target_y, target_z)

                drill_depth = 0.0
                if current_motion in ("G81", "G83") and z_match:
                    drill_depth = abs(target_z)

                seg = ToolpathSegment(
                    motion_type=current_motion,
                    start=start_pt,
                    end=end_pt,
                    feed=current_feed,
                    spindle=current_spindle,
                    line_num=idx,
                    raw_text=raw_line,
                    drill_depth=drill_depth,
                    hole_diameter=tool_diameter,
                )
                self.segments.append(seg)

                # Accumulate statistics
                if seg.motion_type == "G00":
                    self.total_rapid_dist += seg.length
                    # Rapid move estimated at 3000 mm/min
                    self.est_time_seconds += (seg.length / 3000.0) * 60.0
                else:
                    self.total_cut_dist += seg.length
                    feed = current_feed if current_feed > 0 else 300.0
                    self.est_time_seconds += (seg.length / feed) * 60.0

                min_x = min(min_x, target_x)
                min_y = min(min_y, target_y)
                max_x = max(max_x, target_x)
                max_y = max(max_y, target_y)

                current_x = target_x
                current_y = target_y
                current_z = target_z

        self.bbox_min = (min_x, min_y)
        self.bbox_max = (max_x, max_y)
        return self.segments


class ToolpathCanvasWidget(QWidget):
    """
    High-performance 2D QPainter canvas that visualizes stock boundary,
    coordinate axes, grid, G00/G01/G83 paths, and animated cutter cursor.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setStyleSheet("background-color: #ffffff; border: 1px solid #1a1a1a;")

        # Workpiece and simulation data
        self.stock_width: float = 100.0
        self.stock_height: float = 100.0
        self.tool_diameter: float = 3.0
        self.segments: List[ToolpathSegment] = []
        self.current_segment_idx: int = 0
        self.tool_pos: Tuple[float, float, float] = (0.0, 0.0, 50.0)
        self.show_tool_band: bool = True

        # Viewport navigation (pan and zoom)
        self.scale: float = 3.0  # pixels per mm
        self.pan_x: float = 60.0  # left margin
        self.pan_y: float = 60.0  # bottom margin
        self._is_panning: bool = False
        self._last_mouse_pos = QPointF(0, 0)

    def set_stock(self, width: float, height: float):
        """Update stock boundaries and auto-fit view."""
        self.stock_width = max(10.0, width)
        self.stock_height = max(10.0, height)
        self.reset_view()

    def set_tool_diameter(self, dia: float):
        """Update active tool cutter diameter."""
        self.tool_diameter = max(0.5, dia)
        self.update()

    def set_segments(self, segments: List[ToolpathSegment], tool_dia: float = 3.0):
        """Load new parsed segments into canvas."""
        self.segments = segments
        self.tool_diameter = tool_dia
        self.current_segment_idx = 0
        if segments:
            self.tool_pos = segments[0].start
        else:
            self.tool_pos = (0.0, 0.0, 50.0)
        self.reset_view()

    def set_current_step(self, segment_idx: int):
        """Set playback position to a specific segment index."""
        if not self.segments:
            return
        self.current_segment_idx = max(0, min(segment_idx, len(self.segments)))
        if self.current_segment_idx < len(self.segments):
            self.tool_pos = self.segments[self.current_segment_idx].end
        elif self.segments:
            self.tool_pos = self.segments[-1].end
        self.update()

    def reset_view(self):
        """Auto-fit stock plate neatly within viewport."""
        w = max(100, self.width())
        h = max(100, self.height())
        scale_x = (w * 0.75) / self.stock_width
        scale_y = (h * 0.75) / self.stock_height
        self.scale = max(0.5, min(scale_x, scale_y))
        self.pan_x = (w - self.stock_width * self.scale) / 2.0
        self.pan_y = (h - self.stock_height * self.scale) / 2.0
        self.update()

    def zoom_in(self):
        self.scale *= 1.2
        self.update()

    def zoom_out(self):
        self.scale = max(0.2, self.scale / 1.2)
        self.update()

    # --- Coordinate Transformations: Bottom-Left CNC -> Screen Top-Left ---
    def to_screen(self, x: float, y: float) -> QPointF:
        """Convert CNC millimeters (O at bottom-left) to widget screen pixels."""
        sx = self.pan_x + x * self.scale
        sy = self.height() - self.pan_y - (y * self.scale)
        return QPointF(sx, sy)

    def to_cnc(self, sx: float, sy: float) -> Tuple[float, float]:
        """Convert screen pixel coordinates back to CNC millimeters."""
        x = (sx - self.pan_x) / self.scale
        y = (self.height() - self.pan_y - sy) / self.scale
        return (x, y)

    # --- Mouse interaction: Pan & Zoom ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._is_panning = True
            self._last_mouse_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning:
            delta = event.position() - self._last_mouse_pos
            self.pan_x += delta.x()
            self.pan_y -= delta.y()  # Inverted for Bottom-Left CNC axis
            self._last_mouse_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._is_panning = False

    def wheelEvent(self, event: QWheelEvent):
        """Zoom centered at mouse cursor position."""
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        mouse_pt = event.position()
        cnc_x, cnc_y = self.to_cnc(mouse_pt.x(), mouse_pt.y())

        self.scale = max(0.2, min(50.0, self.scale * factor))

        # Re-adjust pan so mouse point remains invariant
        self.pan_x = mouse_pt.x() - cnc_x * self.scale
        self.pan_y = (self.height() - mouse_pt.y()) - cnc_y * self.scale
        self.update()

    # --- Painting Viewport ---
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self._draw_grid(painter)
        self._draw_stock(painter)
        self._draw_origin_axes(painter)
        self._draw_toolpaths(painter)
        self._draw_tool_cutter(painter)

    def _draw_grid(self, painter: QPainter):
        """Draw technical coordinate millimeter grid."""
        painter.save()
        grid_pen = QPen(QColor(235, 235, 235), 1, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)

        step_mm = 10.0 if self.scale > 2.0 else 50.0
        max_extent = max(self.stock_width, self.stock_height) * 2.0

        for i in range(-5, int(max_extent / step_mm) + 5):
            val = i * step_mm
            # Vertical line
            p1 = self.to_screen(val, -max_extent)
            p2 = self.to_screen(val, max_extent)
            painter.drawLine(p1, p2)
            # Horizontal line
            p3 = self.to_screen(-max_extent, val)
            p4 = self.to_screen(max_extent, val)
            painter.drawLine(p3, p4)

        painter.restore()

    def _draw_stock(self, painter: QPainter):
        """Draw rectangular workpiece blank."""
        painter.save()
        top_left = self.to_screen(0.0, self.stock_height)
        w_px = self.stock_width * self.scale
        h_px = self.stock_height * self.scale

        # Workpiece fill and border
        stock_rect = QRectF(top_left.x(), top_left.y(), w_px, h_px)
        painter.setBrush(QBrush(QColor(248, 249, 250)))
        painter.setPen(QPen(QColor(40, 40, 40), 2, Qt.PenStyle.SolidLine))
        painter.drawRect(stock_rect)

        # Dimension label
        painter.setPen(QColor(100, 100, 100))
        font = QFont("Monospace", 9)
        painter.setFont(font)
        label = f"Phôi: {self.stock_width:.1f} x {self.stock_height:.1f} mm"
        painter.drawText(int(top_left.x() + 8), int(top_left.y() + 18), label)

        painter.restore()

    def _draw_origin_axes(self, painter: QPainter):
        """Draw CNC coordinate origin O(0,0) and X/Y direction arrows."""
        painter.save()
        origin_pt = self.to_screen(0.0, 0.0)

        # Origin circle
        painter.setPen(QPen(QColor(0, 0, 0), 1.5))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(origin_pt, 4.0, 4.0)

        # X Axis Arrow (Red, horizontal to right)
        arrow_len = 35.0
        x_end = QPointF(origin_pt.x() + arrow_len, origin_pt.y())
        painter.setPen(QPen(QColor(211, 47, 47), 2))
        painter.drawLine(origin_pt, x_end)
        painter.drawText(int(x_end.x() + 4), int(x_end.y() + 4), "X+")

        # Y Axis Arrow (Green, vertical upwards)
        y_end = QPointF(origin_pt.x(), origin_pt.y() - arrow_len)
        painter.setPen(QPen(QColor(46, 125, 50), 2))
        painter.drawLine(origin_pt, y_end)
        painter.drawText(int(y_end.x() - 6), int(y_end.y() - 6), "Y+")

        # Origin O mark
        painter.setPen(QColor(0, 0, 0))
        painter.drawText(int(origin_pt.x() - 14), int(origin_pt.y() + 14), "O(0,0)")
        painter.restore()

    def _draw_toolpaths(self, painter: QPainter):
        """Draw complete G-Code toolpath segments."""
        if not self.segments:
            return

        painter.save()
        band_radius_px = (self.tool_diameter / 2.0) * self.scale

        # 1. Background ghost paths (future segments yet to be executed)
        ghost_pen = QPen(QColor(220, 220, 220), 1, Qt.PenStyle.DotLine)
        painter.setPen(ghost_pen)
        for seg in self.segments[self.current_segment_idx:]:
            p1 = self.to_screen(seg.start[0], seg.start[1])
            p2 = self.to_screen(seg.end[0], seg.end[1])
            painter.drawLine(p1, p2)

        # 2. Executed path segments (up to current_segment_idx)
        for i in range(min(self.current_segment_idx, len(self.segments))):
            seg = self.segments[i]
            p1 = self.to_screen(seg.start[0], seg.start[1])
            p2 = self.to_screen(seg.end[0], seg.end[1])

            if seg.motion_type == "G00":
                # Rapid move: dashed orange-red line
                rapid_pen = QPen(QColor(230, 81, 0), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(rapid_pen)
                painter.drawLine(p1, p2)

            elif seg.motion_type in ("G01", "G02", "G03"):
                # Tool cut width band (semi-transparent cyan/blue)
                if self.show_tool_band and band_radius_px > 1.0:
                    band_pen = QPen(QColor(33, 150, 243, 60), band_radius_px * 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                    painter.setPen(band_pen)
                    painter.drawLine(p1, p2)

                # Toolpath centerline: solid deep blue
                cut_pen = QPen(QColor(25, 118, 210), 2.0, Qt.PenStyle.SolidLine)
                painter.setPen(cut_pen)
                painter.drawLine(p1, p2)

            elif seg.motion_type in ("G81", "G83"):
                # Canned cycle drill hole marker
                hole_radius_px = max(3.0, (seg.hole_diameter / 2.0) * self.scale)
                center_pt = self.to_screen(seg.end[0], seg.end[1])

                # Outer drill circle
                painter.setPen(QPen(QColor(123, 31, 162), 1.8, Qt.PenStyle.SolidLine))
                painter.setBrush(QBrush(QColor(225, 190, 231, 120)))
                painter.drawEllipse(center_pt, hole_radius_px, hole_radius_px)

                # Center crosshair
                painter.setPen(QPen(QColor(123, 31, 162), 1.2))
                painter.drawLine(QPointF(center_pt.x() - 5, center_pt.y()), QPointF(center_pt.x() + 5, center_pt.y()))
                painter.drawLine(QPointF(center_pt.x(), center_pt.y() - 5), QPointF(center_pt.x(), center_pt.y() + 5))

        painter.restore()

    def _draw_tool_cutter(self, painter: QPainter):
        """Draw the animated cutter tool with current X, Y, Z readout."""
        painter.save()
        cur_x, cur_y, cur_z = self.tool_pos
        center_pt = self.to_screen(cur_x, cur_y)
        tool_radius_px = max(4.0, (self.tool_diameter / 2.0) * self.scale)

        # Cutter body: yellow circle with dark border
        painter.setPen(QPen(QColor(230, 81, 0), 2, Qt.PenStyle.SolidLine))
        painter.setBrush(QBrush(QColor(255, 193, 7, 160)))
        painter.drawEllipse(center_pt, tool_radius_px, tool_radius_px)

        # Center precision crosshair
        painter.setPen(QPen(QColor(0, 0, 0), 1.5))
        painter.drawLine(QPointF(center_pt.x() - tool_radius_px - 4, center_pt.y()), QPointF(center_pt.x() + tool_radius_px + 4, center_pt.y()))
        painter.drawLine(QPointF(center_pt.x(), center_pt.y() - tool_radius_px - 4), QPointF(center_pt.x(), center_pt.y() + tool_radius_px + 4))

        # Position label badge
        pos_text = f"X:{cur_x:.2f} Y:{cur_y:.2f} Z:{cur_z:.2f}"
        painter.setFont(QFont("Monospace", 8, QFont.Weight.Bold))
        painter.setPen(QColor(26, 26, 26))
        painter.drawText(int(center_pt.x() + tool_radius_px + 6), int(center_pt.y() - 4), pos_text)

        painter.restore()


class CNCToolpathSimulatorWidget(QWidget):
    """
    Main CNC Toolpath Simulator Widget.
    Combines Playback Controls, Canvas Viewport, Scrubber Slider, DRO and Statistics.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.parser = GCodeToolpathParser()
        self.segments: List[ToolpathSegment] = []
        self.current_idx: int = 0
        self.is_playing: bool = False
        self.playback_speed: float = 1.0

        # Animation timer (30ms per tick)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._on_animation_tick)

        self._init_ui()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # ---------------------------------------------------------------------
        # 1. Top Toolbar (Controls, Speed, Zoom, Tool Band)
        # ---------------------------------------------------------------------
        toolbar_frame = QFrame(self)
        toolbar_frame.setStyleSheet("QFrame { background-color: #f8f9fa; border: 1px solid #1a1a1a; padding: 4px; }")
        tb_layout = QHBoxLayout(toolbar_frame)
        tb_layout.setContentsMargins(4, 4, 4, 4)
        tb_layout.setSpacing(6)

        self.btn_run = QPushButton("Chạy (Run)", toolbar_frame)
        self.btn_run.setFixedHeight(28)
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #1a1a1a; color: #ffffff;")
        self.btn_run.clicked.connect(self.toggle_run)
        tb_layout.addWidget(self.btn_run)

        self.btn_step = QPushButton("Từng bước (Step)", toolbar_frame)
        self.btn_step.setFixedHeight(28)
        self.btn_step.clicked.connect(self.step_forward)
        tb_layout.addWidget(self.btn_step)

        self.btn_reset = QPushButton("Đặt lại (Reset)", toolbar_frame)
        self.btn_reset.setFixedHeight(28)
        self.btn_reset.clicked.connect(self.reset_simulation)
        tb_layout.addWidget(self.btn_reset)

        tb_layout.addSpacing(10)

        # Speed slider
        lbl_speed = QLabel("Tốc độ:", toolbar_frame)
        tb_layout.addWidget(lbl_speed)
        self.slider_speed = QSlider(Qt.Orientation.Horizontal, toolbar_frame)
        self.slider_speed.setRange(1, 10)
        self.slider_speed.setValue(2)
        self.slider_speed.setFixedWidth(80)
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        tb_layout.addWidget(self.slider_speed)

        self.lbl_speed_val = QLabel("2x", toolbar_frame)
        self.lbl_speed_val.setFixedWidth(24)
        tb_layout.addWidget(self.lbl_speed_val)

        tb_layout.addSpacing(10)

        # Zoom controls
        self.btn_zoom_in = QPushButton("+", toolbar_frame)
        self.btn_zoom_in.setFixedSize(26, 26)
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        tb_layout.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("-", toolbar_frame)
        self.btn_zoom_out.setFixedSize(26, 26)
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        tb_layout.addWidget(self.btn_zoom_out)

        self.btn_zoom_reset = QPushButton("↺", toolbar_frame)
        self.btn_zoom_reset.setFixedSize(26, 26)
        self.btn_zoom_reset.setToolTip("Khôi phục khung nhìn vừa vặn phôi")
        self.btn_zoom_reset.clicked.connect(self._zoom_reset)
        tb_layout.addWidget(self.btn_zoom_reset)

        tb_layout.addSpacing(10)

        # Checkbox Tool Band
        self.chk_tool_band = QCheckBox("Vệt cắt dao (Tool Band)", toolbar_frame)
        self.chk_tool_band.setChecked(True)
        self.chk_tool_band.toggled.connect(self._on_toggle_tool_band)
        tb_layout.addWidget(self.chk_tool_band)

        tb_layout.addStretch()
        root_layout.addWidget(toolbar_frame)

        # ---------------------------------------------------------------------
        # 2. Center Viewport (Canvas)
        # ---------------------------------------------------------------------
        self.canvas = ToolpathCanvasWidget(self)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root_layout.addWidget(self.canvas, stretch=1)

        # ---------------------------------------------------------------------
        # 3. Scrubber Slider
        # ---------------------------------------------------------------------
        scrub_frame = QFrame(self)
        scrub_frame.setStyleSheet("QFrame { background-color: #f8f9fa; border: 1px solid #1a1a1a; padding: 2px 6px; }")
        scrub_layout = QHBoxLayout(scrub_frame)
        scrub_layout.setContentsMargins(4, 2, 4, 2)
        scrub_layout.setSpacing(6)

        lbl_scrub = QLabel("Tua lệnh (Scrub):", scrub_frame)
        scrub_layout.addWidget(lbl_scrub)

        self.slider_scrub = QSlider(Qt.Orientation.Horizontal, scrub_frame)
        self.slider_scrub.setRange(0, 0)
        self.slider_scrub.setValue(0)
        self.slider_scrub.valueChanged.connect(self._on_scrubber_changed)
        scrub_layout.addWidget(self.slider_scrub, stretch=1)

        self.lbl_scrub_counter = QLabel("0 / 0 bước", scrub_frame)
        self.lbl_scrub_counter.setFixedWidth(80)
        scrub_layout.addWidget(self.lbl_scrub_counter)

        root_layout.addWidget(scrub_frame)

        # ---------------------------------------------------------------------
        # 4. Digital Readout (DRO) Cards
        # ---------------------------------------------------------------------
        dro_frame = QFrame(self)
        dro_frame.setStyleSheet("QFrame { background-color: #f0f0f0; border: 1px solid #1a1a1a; }")
        dro_layout = QGridLayout(dro_frame)
        dro_layout.setContentsMargins(6, 6, 6, 6)
        dro_layout.setHorizontalSpacing(8)
        dro_layout.setVerticalSpacing(4)

        card_style = "background-color: #ffffff; border: 1px solid #999999; padding: 4px; font-family: monospace;"

        self.dro_x = QLabel("X: 0.000 mm", dro_frame)
        self.dro_x.setStyleSheet(card_style)
        dro_layout.addWidget(self.dro_x, 0, 0)

        self.dro_y = QLabel("Y: 0.000 mm", dro_frame)
        self.dro_y.setStyleSheet(card_style)
        dro_layout.addWidget(self.dro_y, 0, 1)

        self.dro_z = QLabel("Z: 50.000 mm", dro_frame)
        self.dro_z.setStyleSheet(card_style)
        dro_layout.addWidget(self.dro_z, 0, 2)

        self.dro_feed = QLabel("F: 0 mm/min", dro_frame)
        self.dro_feed.setStyleSheet(card_style)
        dro_layout.addWidget(self.dro_feed, 0, 3)

        self.dro_spindle = QLabel("S: 0 RPM", dro_frame)
        self.dro_spindle.setStyleSheet(card_style)
        dro_layout.addWidget(self.dro_spindle, 0, 4)

        self.dro_cmd = QLabel("Lệnh: (Sẵn sàng)", dro_frame)
        self.dro_cmd.setStyleSheet("background-color: #ffffff; border: 1px solid #999999; padding: 4px; font-weight: bold; color: #0d47a1;")
        dro_layout.addWidget(self.dro_cmd, 1, 0, 1, 5)

        root_layout.addWidget(dro_frame)

        # ---------------------------------------------------------------------
        # 5. Statistics Footer
        # ---------------------------------------------------------------------
        self.lbl_stats = QLabel(
            "Thống kê: Chiều dài cắt: 0.0 mm | Chạy nhanh: 0.0 mm | Tổng bước: 0 | Thời gian ước tính: 0:00",
            self,
        )
        self.lbl_stats.setStyleSheet("color: #333333; font-size: 11px; padding: 2px;")
        root_layout.addWidget(self.lbl_stats)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def load_gcode(self, gcode_text: str, stock_w: float = 100.0, stock_h: float = 100.0, tool_dia: float = 3.0):
        """Parse G-code program, update canvas and reset simulator."""
        self.reset_simulation()
        self.segments = self.parser.parse(gcode_text, default_tool_dia=tool_dia)
        self.canvas.stock_width = stock_w
        self.canvas.stock_height = stock_h
        self.canvas.set_segments(self.segments, tool_dia=tool_dia)

        total_moves = len(self.segments)
        self.slider_scrub.setRange(0, total_moves)
        self.slider_scrub.setValue(0)
        self.lbl_scrub_counter.setText(f"0 / {total_moves} bước")

        # Format stats
        mins = int(self.parser.est_time_seconds // 60)
        secs = int(self.parser.est_time_seconds % 60)
        time_str = f"{mins}:{secs:02d}"
        self.lbl_stats.setText(
            f"Thống kê: Chiều dài cắt: {self.parser.total_cut_dist:.1f} mm | "
            f"Chạy nhanh: {self.parser.total_rapid_dist:.1f} mm | "
            f"Tổng bước: {total_moves} | "
            f"Thời gian ước tính: {time_str}"
        )
        self._update_dro_display()

    # -------------------------------------------------------------------------
    # Controls & Playback
    # -------------------------------------------------------------------------
    def toggle_run(self):
        """Start or pause playback."""
        if not self.segments:
            return

        if self.is_playing:
            self.pause_simulation()
        else:
            self.start_simulation()

    def start_simulation(self):
        if not self.segments:
            return
        if self.current_idx >= len(self.segments):
            self.current_idx = 0

        self.is_playing = True
        self.btn_run.setText("Tạm dừng (Pause)")
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #d32f2f; color: #ffffff;")
        self.timer.start()

    def pause_simulation(self):
        self.is_playing = False
        self.btn_run.setText("Chạy (Run)")
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #1a1a1a; color: #ffffff;")
        self.timer.stop()

    def step_forward(self):
        """Execute single block step."""
        if not self.segments:
            return
        self.pause_simulation()
        if self.current_idx < len(self.segments):
            self.current_idx += 1
            self.canvas.set_current_step(self.current_idx)
            self.slider_scrub.blockSignals(True)
            self.slider_scrub.setValue(self.current_idx)
            self.slider_scrub.blockSignals(False)
            self._update_dro_display()

    def reset_simulation(self):
        """Reset tool position and stop playback."""
        self.pause_simulation()
        self.current_idx = 0
        self.canvas.set_current_step(0)
        self.slider_scrub.blockSignals(True)
        self.slider_scrub.setValue(0)
        self.slider_scrub.blockSignals(False)
        self._update_dro_display()

    def _on_animation_tick(self):
        """Timer advance step."""
        if not self.segments or self.current_idx >= len(self.segments):
            self.pause_simulation()
            return

        # Advance by steps proportional to speed
        step_increment = max(1, int(self.playback_speed))
        self.current_idx = min(len(self.segments), self.current_idx + step_increment)
        self.canvas.set_current_step(self.current_idx)

        self.slider_scrub.blockSignals(True)
        self.slider_scrub.setValue(self.current_idx)
        self.slider_scrub.blockSignals(False)

        self._update_dro_display()

        if self.current_idx >= len(self.segments):
            self.pause_simulation()

    def _update_dro_display(self):
        """Refresh DRO indicators."""
        total = len(self.segments)
        self.lbl_scrub_counter.setText(f"{self.current_idx} / {total} bước")

        if not self.segments or self.current_idx == 0:
            self.dro_x.setText("X: 0.000 mm")
            self.dro_y.setText("Y: 0.000 mm")
            self.dro_z.setText("Z: 50.000 mm")
            self.dro_feed.setText("F: 0 mm/min")
            self.dro_spindle.setText("S: 0 RPM")
            self.dro_cmd.setText("Lệnh: (Bắt đầu chương trình)")
            return

        active_idx = min(self.current_idx - 1, total - 1)
        seg = self.segments[active_idx]
        cur_x, cur_y, cur_z = seg.end

        self.dro_x.setText(f"X: {cur_x:.3f} mm")
        self.dro_y.setText(f"Y: {cur_y:.3f} mm")
        self.dro_z.setText(f"Z: {cur_z:.3f} mm")
        self.dro_feed.setText(f"F: {seg.feed:.1f} mm/min")
        self.dro_spindle.setText(f"S: {seg.spindle} RPM")
        self.dro_cmd.setText(f"Lệnh [Dòng {seg.line_num}]: {seg.raw_text}")

    # -------------------------------------------------------------------------
    # Internal UI handlers
    # -------------------------------------------------------------------------
    def _on_speed_changed(self, value: int):
        self.playback_speed = float(value)
        self.lbl_speed_val.setText(f"{value}x")

    def _on_scrubber_changed(self, value: int):
        self.current_idx = value
        self.canvas.set_current_step(value)
        self._update_dro_display()

    def _on_toggle_tool_band(self, checked: bool):
        self.canvas.show_tool_band = checked
        self.canvas.update()

    def _zoom_in(self):
        self.canvas.zoom_in()

    def _zoom_out(self):
        self.canvas.zoom_out()

    def _zoom_reset(self):
        self.canvas.reset_view()
