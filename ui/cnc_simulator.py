"""
CNC Toolpath Simulator Module for VLM4CNC.
Provides an interactive 2D CNC toolpath visualizer inspired by CAD/CAM software and ImageToGCode.
Features:
  - G-Code physical motion parser (G00, G01, G02, G03, G81, G83, S, F, Z).
  - High-performance QPainter interactive 2D canvas with pan, zoom, dynamic adaptive grid, and stock bounds.
  - Rapid moves (G00 dashed grey), cutting moves (G01 solid green with tool cut band), Arcs (G02/G03).
  - Direction Chevrons: subtle arrows along path moves showing cutting direction.
  - Traveled Path Highlight: clear visual progress trail of already cut paths.
  - Canned drilling cycles (G81/G83) with hole position and diameter markers.
  - Animated transparent cutter with tool diameter Ø and precision crosshair cursor.
  - Playback controls: Run/Pause, Step Forward, Step Backward, Reset, Speed slider (1x - 10x), Scrubber slider.
  - Real-time Digital Readout (DRO): Current X, Y, Z, Feedrate, Spindle RPM, Motion mode, active G-code block.
  - Toolpath statistics & Envelope: Width x Height mm, Cut distance, Rapid distance, Total moves, Estimated cycle time.
  - View toggles: Grid, Rapids, Direction Arrows, Tool Band, Traveled Trail.
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


# CAD Simulation Palette inspired by ImageToGCode and industrial CAM viewers
SIM_CANVAS_BG = QColor(255, 255, 255)
SIM_GRID_COLOR = QColor(233, 236, 239)
SIM_AXIS_X_COLOR = QColor(234, 67, 53)
SIM_AXIS_Y_COLOR = QColor(52, 168, 83)
SIM_RAPID_COLOR = QColor(154, 160, 166)
SIM_LINEAR_COLOR = QColor(30, 142, 62)
SIM_ARC_CW_COLOR = QColor(26, 115, 232)
SIM_ARC_CCW_COLOR = QColor(227, 116, 0)
SIM_TRAVELED_COLOR = QColor(255, 140, 0)
SIM_TOOL_OUTLINE = QColor(230, 81, 0)
SIM_TOOL_FILL = QColor(255, 243, 224, 175)
SIM_TOOL_CENTER = QColor(32, 33, 36)
RAPID_DISPLAY_FEED = 3000.0  # mm/min display speed for rapid G00 moves


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
    time_start: float = 0.0
    time_end: float = 0.0
    duration: float = 0.0
    # Arc metadata for G02/G03
    is_arc: bool = False
    arc_center: Optional[Tuple[float, float]] = None
    arc_radius: float = 0.0
    arc_clockwise: bool = True
    arc_start_angle: float = 0.0
    arc_sweep_angle: float = 0.0

    def __post_init__(self):
        dz = self.end[2] - self.start[2]
        if self.is_arc and self.arc_radius > 1e-4:
            arc_dist = self.arc_radius * abs(self.arc_sweep_angle)
            self.length = math.sqrt(arc_dist * arc_dist + dz * dz)
        else:
            dx = self.end[0] - self.start[0]
            dy = self.end[1] - self.start[1]
            self.length = math.sqrt(dx * dx + dy * dy + dz * dz)

        # Cutting if G01/G02/G03/G81/G83 and moving at or below Z <= 0
        if self.motion_type in ("G01", "G02", "G03"):
            self.is_cutting = (self.start[2] <= 0.0 or self.end[2] <= 0.0)
        elif self.motion_type in ("G81", "G83"):
            self.is_cutting = True
        else:
            self.is_cutting = False


class GCodeToolpathParser:
    """Parses standard ISO G-Code into sequential motion segments with physical timeline."""

    def __init__(self):
        self.segments: List[ToolpathSegment] = []
        self.total_cut_dist: float = 0.0
        self.total_rapid_dist: float = 0.0
        self.est_time_seconds: float = 0.0
        self.bbox_min: Tuple[float, float] = (0.0, 0.0)
        self.bbox_max: Tuple[float, float] = (100.0, 100.0)
        self.envelope_width: float = 100.0
        self.envelope_height: float = 100.0

    def parse(self, gcode_text: str, default_tool_dia: float = 3.0) -> List[ToolpathSegment]:
        """Parse G-Code text into sequential motion segments with physical feedrate timing."""
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
        current_time = 0.0

        min_x, min_y = 0.0, 0.0
        max_x, max_y = 100.0, 100.0
        first_motion = True

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

            # Strip comments for code token parsing
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

            # Arc parameters extraction
            i_match = re.search(r"\bI(-?[0-9.]+)\b", clean_code, re.IGNORECASE)
            j_match = re.search(r"\bJ(-?[0-9.]+)\b", clean_code, re.IGNORECASE)
            r_match = re.search(r"\bR(-?[0-9.]+)\b", clean_code, re.IGNORECASE)

            has_arc_params = bool(i_match or j_match or r_match)
            has_motion = (x_match or y_match or z_match or (has_arc_params and current_motion in ("G02", "G03")))

            if has_motion:
                start_pt = (current_x, current_y, current_z)
                end_pt = (target_x, target_y, target_z)

                drill_depth = 0.0
                if current_motion in ("G81", "G83") and z_match:
                    drill_depth = abs(target_z)

                # Arc geometry calculation for G02/G03
                is_arc = False
                cx, cy = 0.0, 0.0
                radius = 0.0
                is_cw = (current_motion == "G02")
                theta_start = 0.0
                sweep_angle = 0.0

                if current_motion in ("G02", "G03"):
                    if i_match or j_match:
                        i_val = float(i_match.group(1)) if i_match else 0.0
                        j_val = float(j_match.group(1)) if j_match else 0.0
                        cx = current_x + i_val
                        cy = current_y + j_val
                        radius = math.hypot(i_val, j_val)
                        is_arc = (radius > 1e-4)
                    elif r_match:
                        r_val = float(r_match.group(1))
                        radius = abs(r_val)
                        chord_dx = target_x - current_x
                        chord_dy = target_y - current_y
                        chord_len = math.hypot(chord_dx, chord_dy)
                        if chord_len > 1e-6 and radius >= chord_len / 2.0:
                            h = math.sqrt(max(0.0, radius * radius - (chord_len / 2.0) ** 2))
                            mx = (current_x + target_x) / 2.0
                            my = (current_y + target_y) / 2.0
                            nx = -chord_dy / chord_len
                            ny = chord_dx / chord_len
                            sign = 1.0 if (is_cw if r_val > 0 else not is_cw) else -1.0
                            cx = mx + sign * h * nx
                            cy = my + sign * h * ny
                            is_arc = True
                        elif chord_len > 1e-6:
                            cx = (current_x + target_x) / 2.0
                            cy = (current_y + target_y) / 2.0
                            radius = chord_len / 2.0
                            is_arc = True

                    if is_arc and radius > 1e-4:
                        theta_start = math.atan2(current_y - cy, current_x - cx)
                        theta_end = math.atan2(target_y - cy, target_x - cx)
                        is_full_circle = (math.hypot(target_x - current_x, target_y - current_y) < 1e-4)
                        if is_full_circle:
                            sweep_angle = -2.0 * math.pi if is_cw else 2.0 * math.pi
                        else:
                            diff = theta_end - theta_start
                            if is_cw:
                                while diff >= 0.0:
                                    diff -= 2.0 * math.pi
                                sweep_angle = diff
                            else:
                                while diff <= 0.0:
                                    diff += 2.0 * math.pi
                                sweep_angle = diff
                    else:
                        is_arc = False

                # Physical move duration based on feedrate
                eff_feed = current_feed if current_feed > 0 else 300.0
                speed_feed = RAPID_DISPLAY_FEED if current_motion == "G00" else eff_feed
                dz = target_z - current_z
                if is_arc:
                    arc_dist = radius * abs(sweep_angle)
                    dist_3d = math.sqrt(arc_dist * arc_dist + dz * dz)
                else:
                    dist_3d = math.sqrt(
                        (target_x - current_x) ** 2 +
                        (target_y - current_y) ** 2 +
                        dz ** 2
                    )
                duration = (dist_3d / speed_feed) * 60.0 if speed_feed > 0 else 0.0

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
                    time_start=current_time,
                    time_end=current_time + duration,
                    duration=duration,
                    is_arc=is_arc,
                    arc_center=(cx, cy) if is_arc else None,
                    arc_radius=radius if is_arc else 0.0,
                    arc_clockwise=is_cw if is_arc else True,
                    arc_start_angle=theta_start if is_arc else 0.0,
                    arc_sweep_angle=sweep_angle if is_arc else 0.0,
                )
                current_time += duration
                self.segments.append(seg)

                # Accumulate statistics
                if seg.motion_type == "G00":
                    self.total_rapid_dist += seg.length
                else:
                    self.total_cut_dist += seg.length

                pts_to_bound = [(target_x, target_y)]
                if is_arc:
                    for s_frac in (0.25, 0.5, 0.75):
                        ang = theta_start + sweep_angle * s_frac
                        pts_to_bound.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))

                for bx, by in pts_to_bound:
                    if first_motion:
                        min_x, max_x = bx, bx
                        min_y, max_y = by, by
                        first_motion = False
                    else:
                        min_x = min(min_x, bx)
                        min_y = min(min_y, by)
                        max_x = max(max_x, bx)
                        max_y = max(max_y, by)

                current_x = target_x
                current_y = target_y
                current_z = target_z

        self.est_time_seconds = current_time
        self.bbox_min = (min_x, min_y)
        self.bbox_max = (max_x, max_y)
        self.envelope_width = max(0.0, max_x - min_x)
        self.envelope_height = max(0.0, max_y - min_y)
        return self.segments


class ToolpathCanvasWidget(QWidget):
    """
    High-performance 2D QPainter canvas that visualizes stock boundary,
    coordinate axes, dynamic adaptive grid, G00/G01/G83 paths, direction arrows,
    traveled progress trail, and animated cutter cursor.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setStyleSheet("background-color: #ffffff; border: 1px solid #1a1a1a;")

        # Workpiece and simulation data
        self.stock_width: float = 100.0
        self.stock_height: float = 100.0
        self.tool_diameter: float = 3.0
        self.segments: List[ToolpathSegment] = []
        self.current_segment_idx: int = 0
        self.tool_pos: Tuple[float, float, float] = (0.0, 0.0, 50.0)

        # View toggles
        self.show_grid: bool = True
        self.show_rapids: bool = True
        self.show_arrows: bool = True
        self.show_tool_band: bool = True
        self.show_traveled: bool = True
        self.show_cutter: bool = True

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
        """Draw dynamic adaptive millimeter grid with numerical labels."""
        if not self.show_grid or self.scale <= 1e-4:
            return

        painter.save()
        w = self.width()
        h = self.height()

        target_px = 60.0
        raw_step = target_px / self.scale
        steps = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0]
        grid_step = steps[-1]
        for s in steps:
            if s >= raw_step:
                grid_step = s
                break

        # Bounds in CNC space
        cnc_min_x = (0.0 - self.pan_x) / self.scale
        cnc_max_x = (float(w) - self.pan_x) / self.scale
        cnc_min_y = (self.height() - self.pan_y - float(h)) / self.scale
        cnc_max_y = (self.height() - self.pan_y - 0.0) / self.scale

        start_x_idx = math.floor(min(cnc_min_x, cnc_max_x) / grid_step)
        end_x_idx = math.ceil(max(cnc_min_x, cnc_max_x) / grid_step)
        start_y_idx = math.floor(min(cnc_min_y, cnc_max_y) / grid_step)
        end_y_idx = math.ceil(max(cnc_min_y, cnc_max_y) / grid_step)

        grid_pen = QPen(SIM_GRID_COLOR, 1, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)
        painter.setFont(QFont("Monospace", 8))

        # Vertical grid lines
        for i in range(start_x_idx, end_x_idx + 1):
            wx = i * grid_step
            p_top = self.to_screen(wx, max(cnc_min_y, cnc_max_y))
            p_bot = self.to_screen(wx, min(cnc_min_y, cnc_max_y))
            painter.drawLine(p_top, p_bot)

            if i != 0 and abs(wx) >= 1e-4 and 0 <= p_bot.x() <= w:
                painter.setPen(QColor(154, 160, 166))
                lbl = f"{wx:.0f}" if grid_step >= 1.0 else f"{wx:.1f}"
                painter.drawText(int(p_bot.x() + 3), h - 4, lbl)
                painter.setPen(grid_pen)

        # Horizontal grid lines
        for j in range(start_y_idx, end_y_idx + 1):
            wy = j * grid_step
            p_left = self.to_screen(min(cnc_min_x, cnc_max_x), wy)
            p_right = self.to_screen(max(cnc_min_x, cnc_max_x), wy)
            painter.drawLine(p_left, p_right)

            if j != 0 and abs(wy) >= 1e-4 and 0 <= p_left.y() <= h:
                painter.setPen(QColor(154, 160, 166))
                lbl = f"{wy:.0f}" if grid_step >= 1.0 else f"{wy:.1f}"
                painter.drawText(6, int(p_left.y() - 3), lbl)
                painter.setPen(grid_pen)

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
        """Draw G54 coordinate target origin O(0,0) and +X/+Y direction arrows."""
        painter.save()
        origin_pt = self.to_screen(0.0, 0.0)

        # Target circle marker (G54)
        painter.setPen(QPen(SIM_TOOL_CENTER, 1.5))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(origin_pt, 5.0, 5.0)
        painter.drawEllipse(origin_pt, 1.5, 1.5)

        # Text label G54 (0,0)
        painter.setPen(QColor(32, 33, 36))
        painter.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
        painter.drawText(int(origin_pt.x() + 8), int(origin_pt.y() + 16), "G54 (0,0)")

        # +X Axis Line & Arrow (Red)
        painter.setPen(QPen(SIM_AXIS_X_COLOR, 1.8))
        arrow_len = 40.0
        x_end = QPointF(origin_pt.x() + arrow_len, origin_pt.y())
        painter.drawLine(origin_pt, x_end)
        painter.drawLine(x_end, QPointF(x_end.x() - 6, x_end.y() - 4))
        painter.drawLine(x_end, QPointF(x_end.x() - 6, x_end.y() + 4))
        painter.drawText(int(x_end.x() + 4), int(x_end.y() + 4), "+X (mm)")

        # +Y Axis Line & Arrow (Green)
        painter.setPen(QPen(SIM_AXIS_Y_COLOR, 1.8))
        y_end = QPointF(origin_pt.x(), origin_pt.y() - arrow_len)
        painter.drawLine(origin_pt, y_end)
        painter.drawLine(y_end, QPointF(y_end.x() - 4, y_end.y() + 6))
        painter.drawLine(y_end, QPointF(y_end.x() + 4, y_end.y() + 6))
        painter.drawText(int(y_end.x() - 10), int(y_end.y() - 6), "+Y (mm)")

        painter.restore()

    def _draw_direction_arrow(self, painter: QPainter, p1: QPointF, p2: QPointF, color: QColor):
        """Draw subtle chevrons along path moves to show cutting direction."""
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        if length < 22.0:
            return

        mx = (p1.x() + p2.x()) / 2.0
        my = (p1.y() + p2.y()) / 2.0
        ux = dx / length
        uy = dy / length
        nx = -uy
        ny = ux

        arrow_len = 5.0
        arrow_w = 3.5
        tip_x = mx + ux * (arrow_len * 0.5)
        tip_y = my + uy * (arrow_len * 0.5)
        w1_x = mx - ux * (arrow_len * 0.5) + nx * arrow_w
        w1_y = my - uy * (arrow_len * 0.5) + ny * arrow_w
        w2_x = mx - ux * (arrow_len * 0.5) - nx * arrow_w
        w2_y = my - uy * (arrow_len * 0.5) - ny * arrow_w

        painter.save()
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine))
        painter.drawLine(QPointF(w1_x, w1_y), QPointF(tip_x, tip_y))
        painter.drawLine(QPointF(tip_x, tip_y), QPointF(w2_x, w2_y))
        painter.restore()

    def _get_segment_screen_points(self, seg: ToolpathSegment, steps: int = 24) -> List[QPointF]:
        """Convert segment into screen points, interpolating G02/G03 arcs into smooth curves."""
        if not seg.is_arc or seg.arc_radius <= 1e-4 or seg.arc_center is None:
            return [
                self.to_screen(seg.start[0], seg.start[1]),
                self.to_screen(seg.end[0], seg.end[1]),
            ]

        cx, cy = seg.arc_center
        rad = seg.arc_radius
        start_a = seg.arc_start_angle
        sweep_a = seg.arc_sweep_angle
        n_pts = max(steps, int(abs(sweep_a) / (math.pi / 16.0)))
        pts: List[QPointF] = []
        for s in range(n_pts + 1):
            frac = s / n_pts
            ang = start_a + sweep_a * frac
            px = cx + rad * math.cos(ang)
            py = cy + rad * math.sin(ang)
            pts.append(self.to_screen(px, py))
        return pts

    def _draw_traveled_trail(self, painter: QPainter):
        """Draw highlighted trail over paths that have already been machined."""
        if not self.show_traveled or not self.segments or self.current_segment_idx == 0:
            return

        painter.save()
        traveled_pen = QPen(SIM_TRAVELED_COLOR, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(traveled_pen)

        for i in range(min(self.current_segment_idx, len(self.segments))):
            seg = self.segments[i]
            if seg.motion_type != "G00":
                pts = self._get_segment_screen_points(seg)
                if len(pts) >= 2:
                    painter.drawPolyline(pts)

        painter.restore()

    def _draw_toolpaths(self, painter: QPainter):
        """Draw complete G-Code toolpath segments."""
        if not self.segments:
            return

        painter.save()
        band_radius_px = (self.tool_diameter / 2.0) * self.scale

        # 1. Background ghost paths (future segments)
        ghost_pen = QPen(QColor(220, 224, 230), 1, Qt.PenStyle.DotLine)
        painter.setPen(ghost_pen)
        for seg in self.segments[self.current_segment_idx:]:
            pts = self._get_segment_screen_points(seg)
            if len(pts) >= 2:
                painter.drawPolyline(pts)

        # 2. Executed path segments (up to current_segment_idx)
        for i in range(min(self.current_segment_idx, len(self.segments))):
            seg = self.segments[i]
            pts = self._get_segment_screen_points(seg)
            if len(pts) < 2:
                continue

            if seg.motion_type == "G00":
                if self.show_rapids:
                    rapid_pen = QPen(SIM_RAPID_COLOR, 1.2, Qt.PenStyle.DashLine)
                    painter.setPen(rapid_pen)
                    painter.drawPolyline(pts)

            elif seg.motion_type in ("G01", "G02", "G03"):
                # Tool cut width band (semi-transparent)
                if self.show_tool_band and band_radius_px > 1.0:
                    band_pen = QPen(QColor(30, 142, 62, 45), band_radius_px * 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(band_pen)
                    painter.drawPolyline(pts)

                # Toolpath centerline
                c = SIM_LINEAR_COLOR if seg.motion_type == "G01" else (
                    SIM_ARC_CW_COLOR if seg.motion_type == "G02" else SIM_ARC_CCW_COLOR
                )
                cut_pen = QPen(c, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(cut_pen)
                painter.drawPolyline(pts)

                # Direction arrow
                if self.show_arrows:
                    mid_idx = len(pts) // 2
                    if mid_idx < len(pts) - 1:
                        self._draw_direction_arrow(painter, pts[mid_idx], pts[mid_idx + 1], c)
                    else:
                        self._draw_direction_arrow(painter, pts[0], pts[-1], c)

            elif seg.motion_type in ("G81", "G83"):
                # Drill hole marker
                hole_radius_px = max(3.0, (seg.hole_diameter / 2.0) * self.scale)
                center_pt = self.to_screen(seg.end[0], seg.end[1])

                painter.setPen(QPen(QColor(123, 31, 162), 1.8, Qt.PenStyle.SolidLine))
                painter.setBrush(QBrush(QColor(225, 190, 231, 130)))
                painter.drawEllipse(center_pt, hole_radius_px, hole_radius_px)

                painter.setPen(QPen(QColor(123, 31, 162), 1.2))
                painter.drawLine(QPointF(center_pt.x() - 5, center_pt.y()), QPointF(center_pt.x() + 5, center_pt.y()))
                painter.drawLine(QPointF(center_pt.x(), center_pt.y() - 5), QPointF(center_pt.x(), center_pt.y() + 5))

        # 3. Draw Traveled Highlight Trail over executed cuts
        self._draw_traveled_trail(painter)

        # 4. Start (Green) and End (Red) Nodes
        if self.segments:
            start_pt = self.to_screen(self.segments[0].start[0], self.segments[0].start[1])
            painter.setPen(QPen(QColor(22, 163, 74), 1.5))
            painter.setBrush(QBrush(QColor(34, 197, 94)))
            painter.drawEllipse(start_pt, 4.0, 4.0)

            last_seg = self.segments[-1]
            end_pt = self.to_screen(last_seg.end[0], last_seg.end[1])
            painter.setPen(QPen(QColor(220, 38, 38), 1.5))
            painter.setBrush(QBrush(QColor(239, 68, 68)))
            painter.drawEllipse(end_pt, 4.0, 4.0)

        painter.restore()

    def _draw_tool_cutter(self, painter: QPainter):
        """Draw the animated cutter tool with current X, Y, Z readout."""
        if not self.show_cutter:
            return

        painter.save()
        cur_x, cur_y, cur_z = self.tool_pos
        center_pt = self.to_screen(cur_x, cur_y)
        tool_radius_px = max(4.0, (self.tool_diameter / 2.0) * self.scale)

        # Circular Cutter Body (semi-transparent with orange outline)
        painter.setPen(QPen(SIM_TOOL_OUTLINE, 1.8, Qt.PenStyle.SolidLine))
        painter.setBrush(QBrush(SIM_TOOL_FILL))
        painter.drawEllipse(center_pt, tool_radius_px, tool_radius_px)

        # Center precision crosshair
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QBrush(SIM_TOOL_CENTER))
        painter.drawEllipse(center_pt, 3.5, 3.5)

        painter.setPen(QPen(SIM_TOOL_CENTER, 1.2))
        painter.drawLine(QPointF(center_pt.x() - tool_radius_px - 4, center_pt.y()), QPointF(center_pt.x() + tool_radius_px + 4, center_pt.y()))
        painter.drawLine(QPointF(center_pt.x(), center_pt.y() - tool_radius_px - 4), QPointF(center_pt.x(), center_pt.y() + tool_radius_px + 4))

        # Position label badge
        pos_text = f"X:{cur_x:.2f} Y:{cur_y:.2f} Z:{cur_z:.2f}"
        painter.setFont(QFont("Monospace", 8, QFont.Weight.Bold))
        painter.setPen(QColor(32, 33, 36))
        painter.drawText(int(center_pt.x() + tool_radius_px + 6), int(center_pt.y() - 4), pos_text)

        painter.restore()


class CNCToolpathSimulatorWidget(QWidget):
    """
    Main CNC Toolpath Simulator Widget.
    Combines Playback Controls, Canvas Viewport, Scrubber Slider, DRO, View Toggles and Envelope Stats.
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
        # 1. Top Toolbar (Controls, Speed, Zoom)
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

        self.btn_step_back = QPushButton("Lùi (Back)", toolbar_frame)
        self.btn_step_back.setFixedHeight(28)
        self.btn_step_back.setToolTip("Lùi lại 1 bước di chuyển")
        self.btn_step_back.clicked.connect(self.step_backward)
        tb_layout.addWidget(self.btn_step_back)

        self.btn_step = QPushButton("Tiến (Step)", toolbar_frame)
        self.btn_step.setFixedHeight(28)
        self.btn_step.setToolTip("Tiến tới 1 bước di chuyển")
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

        tb_layout.addStretch()
        root_layout.addWidget(toolbar_frame)

        # ---------------------------------------------------------------------
        # 2. View Toggles Bar (Grid, Rapids, Arrows, Tool Band, Traveled Trail)
        # ---------------------------------------------------------------------
        toggles_frame = QFrame(self)
        toggles_frame.setStyleSheet("QFrame { background-color: #ffffff; border: 1px solid #d0d7de; padding: 2px 6px; }")
        tog_layout = QHBoxLayout(toggles_frame)
        tog_layout.setContentsMargins(4, 2, 4, 2)
        tog_layout.setSpacing(12)

        self.chk_grid = QCheckBox("Lưới", toggles_frame)
        self.chk_grid.setToolTip("Bật/tắt lưới tọa độ milimét")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self._on_toggle_grid)
        tog_layout.addWidget(self.chk_grid)

        self.chk_rapids = QCheckBox("G00", toggles_frame)
        self.chk_rapids.setToolTip("Bật/tắt đường chạy dao nhanh G00")
        self.chk_rapids.setChecked(True)
        self.chk_rapids.toggled.connect(self._on_toggle_rapids)
        tog_layout.addWidget(self.chk_rapids)

        self.chk_arrows = QCheckBox("Hướng dao", toggles_frame)
        self.chk_arrows.setToolTip("Bật/tắt mũi tên chỉ hướng chạy dao")
        self.chk_arrows.setChecked(True)
        self.chk_arrows.toggled.connect(self._on_toggle_arrows)
        tog_layout.addWidget(self.chk_arrows)

        self.chk_tool_band = QCheckBox("Vệt cắt", toggles_frame)
        self.chk_tool_band.setToolTip("Bật/tắt vệt cắt rộng bán kính dao")
        self.chk_tool_band.setChecked(True)
        self.chk_tool_band.toggled.connect(self._on_toggle_tool_band)
        tog_layout.addWidget(self.chk_tool_band)

        self.chk_traveled = QCheckBox("Vệt đã chạy", toggles_frame)
        self.chk_traveled.setToolTip("Bật/tắt vệt chạy dao đã hoàn thành")
        self.chk_traveled.setChecked(True)
        self.chk_traveled.toggled.connect(self._on_toggle_traveled)
        tog_layout.addWidget(self.chk_traveled)

        tog_layout.addStretch()
        root_layout.addWidget(toggles_frame)

        # ---------------------------------------------------------------------
        # 3. Center Viewport (Canvas)
        # ---------------------------------------------------------------------
        self.canvas = ToolpathCanvasWidget(self)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root_layout.addWidget(self.canvas, stretch=1)

        # ---------------------------------------------------------------------
        # 4. Scrubber Slider & Timeline Readout
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

        self.lbl_scrub_counter = QLabel("00:00 / 00:00 (0%) | 0 / 0 bước", scrub_frame)
        self.lbl_scrub_counter.setFixedWidth(230)
        self.lbl_scrub_counter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.lbl_scrub_counter.setStyleSheet("font-family: monospace; font-size: 11px;")
        scrub_layout.addWidget(self.lbl_scrub_counter)

        root_layout.addWidget(scrub_frame)

        # ---------------------------------------------------------------------
        # 5. Digital Readout (DRO) Cards
        # ---------------------------------------------------------------------
        dro_frame = QFrame(self)
        dro_frame.setStyleSheet("QFrame { background-color: #f0f0f0; border: 1px solid #1a1a1a; }")
        dro_layout = QGridLayout(dro_frame)
        dro_layout.setContentsMargins(4, 4, 4, 4)
        dro_layout.setHorizontalSpacing(4)
        dro_layout.setVerticalSpacing(4)
        for c in range(6):
            dro_layout.setColumnStretch(c, 1)

        card_style = "background-color: #ffffff; border: 1px solid #999999; padding: 2px; font-family: monospace; font-size: 11px;"

        self.dro_x = QLabel("X: 0.000 mm", dro_frame)
        self.dro_x.setStyleSheet(card_style)
        self.dro_x.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_x.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dro_x.setFixedHeight(24)
        dro_layout.addWidget(self.dro_x, 0, 0)

        self.dro_y = QLabel("Y: 0.000 mm", dro_frame)
        self.dro_y.setStyleSheet(card_style)
        self.dro_y.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_y.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dro_y.setFixedHeight(24)
        dro_layout.addWidget(self.dro_y, 0, 1)

        self.dro_z = QLabel("Z: 50.000 mm", dro_frame)
        self.dro_z.setStyleSheet(card_style)
        self.dro_z.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_z.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dro_z.setFixedHeight(24)
        dro_layout.addWidget(self.dro_z, 0, 2)

        self.dro_feed = QLabel("F: 0 mm/min", dro_frame)
        self.dro_feed.setStyleSheet(card_style)
        self.dro_feed.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_feed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dro_feed.setFixedHeight(24)
        dro_layout.addWidget(self.dro_feed, 0, 3)

        self.dro_spindle = QLabel("S: 0 RPM", dro_frame)
        self.dro_spindle.setStyleSheet(card_style)
        self.dro_spindle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_spindle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dro_spindle.setFixedHeight(24)
        dro_layout.addWidget(self.dro_spindle, 0, 4)

        self.dro_motion = QLabel("Mode: Idle", dro_frame)
        self.dro_motion.setStyleSheet("background-color: #ffffff; border: 1px solid #999999; padding: 2px; font-weight: bold; color: #2e7d32; font-family: monospace; font-size: 11px;")
        self.dro_motion.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_motion.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dro_motion.setFixedHeight(24)
        dro_layout.addWidget(self.dro_motion, 0, 5)

        self.dro_cmd = QLabel("Lệnh: (Sẵn sàng)", dro_frame)
        self.dro_cmd.setStyleSheet("background-color: #ffffff; border: 1px solid #999999; padding: 2px 6px; font-weight: bold; color: #0d47a1; font-family: monospace; font-size: 11px;")
        self.dro_cmd.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.dro_cmd.setFixedHeight(24)
        dro_layout.addWidget(self.dro_cmd, 1, 0, 1, 6)

        root_layout.addWidget(dro_frame)

        # ---------------------------------------------------------------------
        # 6. Envelope & Statistics Footer
        # ---------------------------------------------------------------------
        self.lbl_stats = QLabel(
            "Bao gia công: 0.0 x 0.0 mm | Chiều dài cắt: 0.0 mm | Chạy nhanh: 0.0 mm | Tổng bước: 0 | Thời gian ước tính: 00:00",
            self,
        )
        self.lbl_stats.setStyleSheet("color: #333333; font-size: 11px; padding: 2px;")
        self.lbl_stats.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.lbl_stats.setFixedHeight(20)
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

        # Format stats & envelope
        mins = int(self.parser.est_time_seconds // 60)
        secs = int(self.parser.est_time_seconds % 60)
        time_str = f"{mins:02d}:{secs:02d}"
        self.lbl_stats.setText(
            f"Bao gia công: {self.parser.envelope_width:.1f} x {self.parser.envelope_height:.1f} mm | "
            f"Chiều dài cắt: {self.parser.total_cut_dist:.1f} mm | "
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
        """Execute single block step forward."""
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

    def step_backward(self):
        """Execute single block step backward."""
        if not self.segments:
            return
        self.pause_simulation()
        if self.current_idx > 0:
            self.current_idx -= 1
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
        total_time = self.parser.est_time_seconds

        cur_time = 0.0
        if self.segments and self.current_idx > 0:
            active_idx = min(self.current_idx - 1, total - 1)
            cur_time = self.segments[active_idx].time_end

        cur_min = int(cur_time // 60)
        cur_sec = int(cur_time % 60)
        tot_min = int(total_time // 60)
        tot_sec = int(total_time % 60)
        pct = int((cur_time / total_time * 100.0)) if total_time > 0 else 0

        self.lbl_scrub_counter.setText(
            f"{cur_min:02d}:{cur_sec:02d} / {tot_min:02d}:{tot_sec:02d} ({pct}%) | {self.current_idx} / {total} bước"
        )

        if not self.segments or self.current_idx == 0:
            self.dro_x.setText("X: 0.000 mm")
            self.dro_y.setText("Y: 0.000 mm")
            self.dro_z.setText("Z: 50.000 mm")
            self.dro_feed.setText("F: 0 mm/min")
            self.dro_spindle.setText("S: 0 RPM")
            self.dro_motion.setText("Mode: Idle")
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

        mode_labels = {
            "G00": "G00 (Rapid)",
            "G01": "G01 (Linear Cut)",
            "G02": "G02 (Arc CW)",
            "G03": "G03 (Arc CCW)",
            "G81": "G81 (Spot Drill)",
            "G83": "G83 (Peck Drill)",
        }
        self.dro_motion.setText(f"Mode: {mode_labels.get(seg.motion_type, seg.motion_type)}")
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

    def _on_toggle_grid(self, checked: bool):
        self.canvas.show_grid = checked
        self.canvas.update()

    def _on_toggle_rapids(self, checked: bool):
        self.canvas.show_rapids = checked
        self.canvas.update()

    def _on_toggle_arrows(self, checked: bool):
        self.canvas.show_arrows = checked
        self.canvas.update()

    def _on_toggle_tool_band(self, checked: bool):
        self.canvas.show_tool_band = checked
        self.canvas.update()

    def _on_toggle_traveled(self, checked: bool):
        self.canvas.show_traveled = checked
        self.canvas.update()

    def _zoom_in(self):
        self.canvas.zoom_in()

    def _zoom_out(self):
        self.canvas.zoom_out()

    def _zoom_reset(self):
        self.canvas.reset_view()
