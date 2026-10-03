"""
Tests for FastMCP cad-cam-mcp-server tools: export_dxf_tool and generate_gcode_tool.
"""

from pathlib import Path
import json
import pytest

from mcp_server.server import export_dxf_tool, generate_gcode_tool, mcp
from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour


@pytest.fixture
def sample_drawing_json() -> str:
    """Fixture providing valid DrawingIR JSON with 2 holes and 1 slot."""
    drawing = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        stock_thickness=10.0,
        holes=[
            DrillHole(center=Point2D(x=25.0, y=25.0), diameter=10.0, depth=10.0),
            DrillHole(center=Point2D(x=75.0, y=50.0), diameter=10.0, depth=10.0),
        ],
        slots=[
            SlotContour(
                width=8.0,
                depth=5.0,
                centerline_path=[Point2D(x=10.0, y=50.0), Point2D(x=80.0, y=50.0)],
            )
        ],
    )
    return drawing.model_dump_json()


@pytest.fixture
def sample_params_json() -> str:
    """Fixture providing valid machining parameters JSON."""
    params = {
        "feedrate_xy": 750.0,
        "plunge_feed": 200.0,
        "spindle_speed": 10000,
        "safe_z": 5.0,
        "cut_depth_per_pass": 1.5,
        "tool_diameter": 4.0,
        "drilling_cycle": "G83",
        "peck_depth": 2.0,
    }
    return json.dumps(params)


def test_mcp_server_initialization():
    """Verify that FastMCP server is correctly named."""
    assert mcp.name == "cad-cam-mcp-server"


def test_export_dxf_tool_success(sample_drawing_json, tmp_path):
    """Verify successful DXF export via export_dxf_tool."""
    target_dxf = tmp_path / "test_out.dxf"
    result = export_dxf_tool(sample_drawing_json, str(target_dxf))

    assert "[SUCCESS]" in result
    assert str(target_dxf.resolve()) in result
    assert target_dxf.exists()
    assert target_dxf.stat().st_size > 0


def test_export_dxf_tool_invalid_json(tmp_path):
    """Verify error handling on invalid JSON input for export_dxf_tool."""
    target_dxf = tmp_path / "invalid.dxf"
    result = export_dxf_tool('{"stock_width": "not-a-number"}', str(target_dxf))

    assert "[ERROR]" in result
    assert "validation failed" in result.lower()
    assert not target_dxf.exists()


def test_generate_gcode_tool_success(sample_drawing_json, sample_params_json, tmp_path):
    """Verify successful G-Code generation and 20-line preview via generate_gcode_tool."""
    target_nc = tmp_path / "test_part.nc"
    result = generate_gcode_tool(sample_drawing_json, sample_params_json, str(target_nc))

    assert "[SUCCESS]" in result
    assert str(target_nc.resolve()) in result
    assert "--- [Preview First 20 Lines] ---" in result
    assert "G54" in result
    assert target_nc.exists()
    assert target_nc.stat().st_size > 0

    content = target_nc.read_text(encoding="utf-8")
    assert "M30" in content
    assert "G83" in content


def test_generate_gcode_tool_invalid_params(sample_drawing_json, tmp_path):
    """Verify error handling when machining params is not valid JSON."""
    target_nc = tmp_path / "invalid_params.nc"
    result = generate_gcode_tool(sample_drawing_json, "NOT_JSON", str(target_nc))

    assert "[ERROR]" in result
    assert "Failed to parse machining params JSON" in result
    assert not target_nc.exists()

