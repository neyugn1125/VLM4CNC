"""
Pydantic v2 Schemas for 2D Mechanical Drawing Analysis and Geometric Extraction.
Defines core data models and intermediate representation (DrawingIR) for CAD/CAM operations.
"""

from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field


class Point2D(BaseModel):
    """2D Point coordinate in mm, origin (0, 0) at bottom-left corner."""
    x: float = Field(..., description="X coordinate in mm (origin at bottom-left)")
    y: float = Field(..., description="Y coordinate in mm (origin at bottom-left)")

    def to_tuple(self) -> Tuple[float, float]:
        """Convert point to (x, y) tuple."""
        return (self.x, self.y)


class DrillHole(BaseModel):
    """Drilling hole specification."""
    center: Point2D = Field(..., description="Hole center coordinates (X, Y)")
    diameter: float = Field(..., ge=0.0, description="Hole diameter in mm")
    depth: float = Field(..., ge=0.0, description="Drilling depth in mm")

    @property
    def radius(self) -> float:
        """Radius of the hole."""
        return self.diameter / 2.0


class SlotContour(BaseModel):
    """Milling slot specification defined by a centerline trajectory."""
    width: float = Field(..., ge=0.0, description="Slot width in mm")
    depth: float = Field(..., ge=0.0, description="Slot cut depth in mm")
    centerline_path: List[Point2D] = Field(
        ..., min_length=2, description="List of 2D points along slot centerline"
    )


class DrawingIR(BaseModel):
    """Intermediate Representation (IR) of the mechanical drawing."""
    reasoning: Optional[str] = Field(
        default=None,
        description="Detailed geometric reasoning, datum identification, and dimension chaining calculations before coordinates.",
    )
    stock_width: float = Field(..., ge=0.0, description="Total stock plate width (X) in mm")
    stock_height: float = Field(..., ge=0.0, description="Total stock plate height (Y) in mm")
    stock_thickness: float = Field(..., ge=0.0, description="Stock plate thickness (Z) in mm")
    holes: List[DrillHole] = Field(default_factory=list, description="List of holes to drill")
    slots: List[SlotContour] = Field(default_factory=list, description="List of slots to mill")
    outer_contour: Optional[List[Point2D]] = Field(
        default=None,
        description="List of 2D vertex points (X, Y) forming the outer perimeter edges/contour of the part.",
    )

    def get_effective_outer_contour(self) -> List[Point2D]:
        """
        Return the outer contour if defined with at least 3 points,
        or synthesize the 4 rectangular boundary edges from stock_width and stock_height.
        """
        if self.outer_contour and len(self.outer_contour) >= 3:
            pts = list(self.outer_contour)
            if pts[0].x != pts[-1].x or pts[0].y != pts[-1].y:
                pts.append(Point2D(x=pts[0].x, y=pts[0].y))
            return pts

        w, h = self.stock_width, self.stock_height
        return [
            Point2D(x=0.0, y=0.0),
            Point2D(x=w, y=0.0),
            Point2D(x=w, y=h),
            Point2D(x=0.0, y=h),
            Point2D(x=0.0, y=0.0),
        ]


# General drawing entities (for VLM extraction / full CAD entity support)
class LineEntity(BaseModel):
    """Line segment representing an edge or boundary."""
    type: Literal["line"] = "line"
    start: Point2D = Field(..., description="Start point")
    end: Point2D = Field(..., description="End point")
    layer: str = Field(default="OUTLINE", description="CAD Layer name")


class CircleEntity(BaseModel):
    """Circle entity representing holes, round bosses, or features."""
    type: Literal["circle"] = "circle"
    center: Point2D = Field(..., description="Center coordinate")
    radius: float = Field(..., ge=0.0, description="Radius in mm")
    is_hole: bool = Field(default=True, description="True if this is a cut hole")
    layer: str = Field(default="HOLES", description="CAD Layer name")


class ArcEntity(BaseModel):
    """Circular arc entity for fillets, chamfers, or curved contours."""
    type: Literal["arc"] = "arc"
    center: Point2D = Field(..., description="Center coordinate")
    radius: float = Field(..., ge=0.0, description="Radius in mm")
    start_angle: float = Field(..., description="Start angle in degrees (0-360)")
    end_angle: float = Field(..., description="End angle in degrees (0-360)")
    layer: str = Field(default="OUTLINE", description="CAD Layer name")


class ContourEntity(BaseModel):
    """Continuous sequence of 2D points forming a cutting path or perimeter."""
    type: Literal["contour"] = "contour"
    points: List[Point2D] = Field(..., min_length=2, description="List of ordered 2D vertices")
    is_closed: bool = Field(default=True, description="Whether the contour closes on itself")
    layer: str = Field(default="OUTLINE", description="CAD Layer name")


class DimensionAnnotation(BaseModel):
    """Dimension or tolerance notation detected in drawing."""
    text: str = Field(..., description="Text as written on drawing")
    nominal_value: float = Field(..., description="Nominal measurement value in mm")
    tolerance_plus: Optional[float] = Field(default=None, description="Upper tolerance deviation")
    tolerance_minus: Optional[float] = Field(default=None, description="Lower tolerance deviation")


class PartAnalysisResult(BaseModel):
    """Complete structured extraction result from a 2D mechanical drawing."""
    part_name: str = Field(default="PART", description="Extracted part or drawing title")
    units: Literal["mm", "inch"] = Field(default="mm", description="Units detected from drawing")
    width: Optional[float] = Field(default=None, description="Overall estimated bounding width in mm")
    height: Optional[float] = Field(default=None, description="Overall estimated bounding height in mm")
    thickness: Optional[float] = Field(default=None, description="Stock or plate thickness in mm")
    
    lines: List[LineEntity] = Field(default_factory=list, description="Extracted line segments")
    circles: List[CircleEntity] = Field(default_factory=list, description="Extracted circles/holes")
    arcs: List[ArcEntity] = Field(default_factory=list, description="Extracted arc fillets/curves")
    contours: List[ContourEntity] = Field(default_factory=list, description="Extracted machining paths")
    dimensions: List[DimensionAnnotation] = Field(default_factory=list, description="Dimension callouts")
    notes: Optional[str] = Field(default=None, description="General drawing notes or machining notes")
