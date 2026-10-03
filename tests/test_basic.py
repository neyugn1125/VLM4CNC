"""
Basic tests for VLM4CNC data structures and engines.
"""

from vision.schemas import Point2D, LineEntity, CircleEntity, PartAnalysisResult
from core.gcode_engine import GCodeEngine, ToolSettings
from core.dxf_engine import DXFEngine


def test_schemas_instantiation():
    """Verify that Pydantic models validate correctly."""
    pt1 = Point2D(x=0.0, y=0.0)
    pt2 = Point2D(x=50.0, y=25.0)
    line = LineEntity(start=pt1, end=pt2, layer="OUTLINE")
    circle = CircleEntity(center=pt1, radius=5.0, is_hole=True)

    result = PartAnalysisResult(
        part_name="TEST_FLANGE",
        width=100.0,
        height=80.0,
        lines=[line],
        circles=[circle],
    )

    assert result.part_name == "TEST_FLANGE"
    assert len(result.lines) == 1
    assert result.lines[0].end.x == 50.0
    assert result.circles[0].radius == 5.0


def test_gcode_engine_compilation(tmp_path):
    """Verify basic G-code compilation."""
    settings = ToolSettings(
        feed_rate=500.0,
        spindle_speed=10000,
        cut_depth=-1.0,
        pass_depth=1.0,
        safe_z=5.0,
    )
    engine = GCodeEngine(settings)
    square_contour = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    gcode = engine.compile_program([square_contour], program_name="TEST_SQUARE")

    assert "G21" in gcode
    assert "M03 S10000" in gcode
    assert "M30" in gcode

    test_file = tmp_path / "test.gcode"
    saved = engine.save_gcode(gcode, test_file)
    assert saved.exists()
    assert saved.read_text(encoding="utf-8") == gcode


def test_dxf_engine_initialization(tmp_path):
    """Verify DXF engine creates a file even in stub mode."""
    engine = DXFEngine()
    engine.add_line((0.0, 0.0), (20.0, 20.0))
    engine.add_circle((10.0, 10.0), 5.0)

    test_dxf = tmp_path / "test.dxf"
    saved = engine.save(test_dxf)
    assert saved.exists()
