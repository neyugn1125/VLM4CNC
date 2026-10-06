"""
DXF Engine Module for VLM4CNC.
Converts DrawingIR into standard AutoCAD DXF files (R2010/R2018) using ezdxf and shapely.
"""

from pathlib import Path
from typing import Any, List, Optional, Tuple, Union
import math
import logging

from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour

logger = logging.getLogger("vlm4cnc.core.dxf")


def _generate_slot_contour_shapely(
    points: List[Tuple[float, float]], radius: float, resolution: int = 16
) -> List[Tuple[float, float]]:
    """Generate round-capped slot contour points using Shapely."""
    from shapely.geometry import LineString

    line = LineString(points)
    # buffer with cap_style='round' (value 1 in shapely) and join_style='round' (value 1)
    buffered = line.buffer(radius, cap_style="round", join_style="round", quad_segs=resolution)
    if hasattr(buffered, "exterior") and buffered.exterior is not None:
        return list(buffered.exterior.coords)
    return []


def _generate_slot_contour_pure_python(
    points: List[Tuple[float, float]], radius: float, arc_segments: int = 16
) -> List[Tuple[float, float]]:
    """
    Fallback pure-Python calculation for slot outline with round end caps
    if shapely is not available.
    """
    if len(points) < 2:
        return []

    # Calculate segment normals and offsets
    left_points: List[Tuple[float, float]] = []
    right_points: List[Tuple[float, float]] = []

    for i in range(len(points) - 1):
        p1, p2 = points[i], points[i + 1]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        nx, ny = -dy / length, dx / length
        left_points.extend([(p1[0] + radius * nx, p1[1] + radius * ny), (p2[0] + radius * nx, p2[1] + radius * ny)])
        right_points.extend([(p2[0] - radius * nx, p2[1] - radius * ny), (p1[0] - radius * nx, p1[1] - radius * ny)])

    if not left_points or not right_points:
        return []

    # End cap at the last point
    end_pt = points[-1]
    dx = end_pt[0] - points[-2][0]
    dy = end_pt[1] - points[-2][1]
    end_angle = math.atan2(dy, dx)
    end_arc: List[Tuple[float, float]] = []
    for step in range(arc_segments + 1):
        angle = end_angle + math.pi / 2.0 - step * (math.pi / arc_segments)
        end_arc.append((end_pt[0] + radius * math.cos(angle), end_pt[1] + radius * math.sin(angle)))

    # Start cap at the first point
    start_pt = points[0]
    dx0 = points[1][0] - start_pt[0]
    dy0 = points[1][1] - start_pt[1]
    start_angle = math.atan2(dy0, dx0)
    start_arc: List[Tuple[float, float]] = []
    for step in range(arc_segments + 1):
        angle = start_angle - math.pi / 2.0 - step * (math.pi / arc_segments)
        start_arc.append((start_pt[0] + radius * math.cos(angle), start_pt[1] + radius * math.sin(angle)))

    # Combine full contour loop
    contour = left_points + end_arc + right_points + start_arc
    return contour


def calculate_slot_contour(points: List[Tuple[float, float]], width: float) -> List[Tuple[float, float]]:
    """Calculate closed polygon coordinates for a slot contour with rounded ends."""
    radius = width / 2.0
    try:
        return _generate_slot_contour_shapely(points, radius)
    except Exception as e:
        logger.debug(f"Shapely buffer not used ({e}). Falling back to pure Python calculation.")
        return _generate_slot_contour_pure_python(points, radius)


def export_drawing_to_dxf(drawing_data: DrawingIR, output_path: str) -> str:
    """
    Export DrawingIR intermediate representation to a standard DXF (R2010) file.

    Layers created:
      - 'STOCK_OUTLINE' (Color 7 - White/Black): Rectangular stock perimeter.
      - 'HOLES' (Color 1 - Red): Circular drill holes.
      - 'SLOTS_CENTERLINE' (Color 3 - Green): Polyline of slot centerlines.
      - 'SLOTS_CONTOUR' (Color 2 - Yellow): Full offset slot boundary with rounded semicircular caps.

    Args:
        drawing_data: The DrawingIR object containing stock dimensions, holes, and slots.
        output_path: Path where the .dxf file will be saved.

    Returns:
        The resolved absolute path string of the saved DXF file.
    """
    import ezdxf

    # 1. Initialize DXF R2010 document
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 2. Setup standard CAD layers with AutoCAD Color Index (ACI)
    doc.layers.add("STOCK_OUTLINE", color=7)     # 7: White / Black
    doc.layers.add("HOLES", color=1)             # 1: Red
    doc.layers.add("SLOTS_CENTERLINE", color=3)  # 3: Green
    doc.layers.add("SLOTS_CONTOUR", color=2)     # 2: Yellow

    # 3. Layer 'STOCK_OUTLINE': Bounding rectangle (0,0) -> (W, 0) -> (W, H) -> (0, H)
    sw = drawing_data.stock_width
    sh = drawing_data.stock_height
    stock_rect = [
        (0.0, 0.0),
        (sw, 0.0),
        (sw, sh),
        (0.0, sh),
    ]
    msp.add_lwpolyline(stock_rect, close=True, dxfattribs={"layer": "STOCK_OUTLINE"})

    # 4. Layer 'HOLES': Add circles for drill holes
    for hole in drawing_data.holes:
        cx, cy = hole.center.x, hole.center.y
        radius = hole.diameter / 2.0
        msp.add_circle(center=(cx, cy), radius=radius, dxfattribs={"layer": "HOLES"})

    # 5. Layer 'SLOTS_CENTERLINE' and 'SLOTS_CONTOUR': Add slots
    for slot in drawing_data.slots:
        center_pts = [p.to_tuple() for p in slot.centerline_path]

        # Draw centerline polyline
        msp.add_lwpolyline(center_pts, close=False, dxfattribs={"layer": "SLOTS_CENTERLINE"})

        # Draw full offset contour with rounded caps
        contour_pts = calculate_slot_contour(center_pts, slot.width)
        if contour_pts:
            msp.add_lwpolyline(contour_pts, close=True, dxfattribs={"layer": "SLOTS_CONTOUR"})

    # 6. Layer 'PART_OUTLINE_CONTOUR': Add outer part perimeter edges
    if hasattr(drawing_data, "outer_contour") and drawing_data.outer_contour and len(drawing_data.outer_contour) >= 3:
        if "PART_OUTLINE_CONTOUR" not in doc.layers:
            doc.layers.add(name="PART_OUTLINE_CONTOUR", color=4)  # Cyan
        contour_tuples = [p.to_tuple() for p in drawing_data.outer_contour]
        msp.add_lwpolyline(contour_tuples, close=True, dxfattribs={"layer": "PART_OUTLINE_CONTOUR"})

    # 7. Save document to output path
    dest_path = Path(output_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(dest_path), encoding="utf-8")
    logger.info(f"DXF exported successfully: {dest_path.resolve()}")
    return str(dest_path.resolve())


class DXFEngine:
    """Class wrapper for DXF manipulation (retained for backward compatibility)."""

    def __init__(self, dxf_version: str = "R2010"):
        self.dxf_version = dxf_version
        try:
            import ezdxf
            self.doc = ezdxf.new(dxf_version)
            self.msp = self.doc.modelspace()
        except ImportError:
            self.doc = None
            self.msp = None

    def add_line(self, start: Tuple[float, float], end: Tuple[float, float], layer: str = "OUTLINE") -> None:
        if self.msp is not None:
            self.msp.add_line(start, end, dxfattribs={"layer": layer})

    def add_circle(self, center: Tuple[float, float], radius: float, layer: str = "HOLES") -> None:
        if self.msp is not None:
            self.msp.add_circle(center, radius, dxfattribs={"layer": layer})

    def add_arc(self, center: Tuple[float, float], radius: float, start_angle: float, end_angle: float, layer: str = "OUTLINE") -> None:
        if self.msp is not None:
            self.msp.add_arc(center, radius, start_angle, end_angle, dxfattribs={"layer": layer})

    def add_polyline(self, points: List[Tuple[float, float]], is_closed: bool = True, layer: str = "OUTLINE") -> None:
        if self.msp is not None:
            self.msp.add_lwpolyline(points, close=is_closed, dxfattribs={"layer": layer})

    def save(self, filepath: Union[str, Path]) -> Path:
        target_path = Path(filepath)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if self.doc is not None:
            self.doc.saveas(str(target_path), encoding="utf-8")
        else:
            target_path.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        return target_path

    def export(self, drawing_data: DrawingIR, output_path: str) -> str:
        return export_drawing_to_dxf(drawing_data, output_path)

