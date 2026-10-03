"""
Independent test suite for VLM4CNC CAD/CAM core processing modules.
Tests DXF generation and CNC G-Code compilation on 2 benchmark datasets:
  1. Test 1: 100x100 stock with 3 drill holes (Ø10) at (25, 25), (25, 75), (75, 50).
  2. Test 2: 100x100 stock with an 8mm rounded slot along polyline path.
"""

from pathlib import Path
import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour
from core.dxf_engine import export_drawing_to_dxf
from core.gcode_engine import generate_gcode


OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def get_default_machining_params() -> dict:
    """Standard machining settings for aluminum / engineering plastic machining."""
    return {
        "feedrate_xy": 800.0,
        "plunge_feed": 250.0,
        "spindle_speed": 12000,
        "safe_z": 5.0,
        "cut_depth_per_pass": 1.5,
        "tool_diameter": 4.0,
        "drilling_cycle": "G83",
        "peck_depth": 2.0,
        "retract_r": 2.0,
    }


def test_case_1_three_holes():
    """
    Test 1: 100x100 mm stock with 3 drill holes:
      - Hole 1: (25, 25), Ø10mm, depth 10mm
      - Hole 2: (25, 75), Ø10mm, depth 10mm
      - Hole 3: (75, 50), Ø10mm, depth 10mm
    Outputs: outputs/test1_3holes.dxf and outputs/test1_3holes.nc
    """
    drawing_data = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        stock_thickness=10.0,
        holes=[
            DrillHole(center=Point2D(x=25.0, y=25.0), diameter=10.0, depth=10.0),
            DrillHole(center=Point2D(x=25.0, y=75.0), diameter=10.0, depth=10.0),
            DrillHole(center=Point2D(x=75.0, y=50.0), diameter=10.0, depth=10.0),
        ],
        slots=[],
    )

    dxf_file = OUTPUTS_DIR / "test1_3holes.dxf"
    nc_file = OUTPUTS_DIR / "test1_3holes.nc"

    # 1. Export DXF
    dxf_result = export_drawing_to_dxf(drawing_data, str(dxf_file))
    assert Path(dxf_result).exists(), "DXF output file was not created"
    assert Path(dxf_result).stat().st_size > 0, "DXF output file is empty"

    # Verify DXF contents using ezdxf
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_file))
        assert "STOCK_OUTLINE" in doc.layers
        assert "HOLES" in doc.layers
        circles = list(doc.modelspace().query("CIRCLE"))
        assert len(circles) == 3, f"Expected 3 circles, found {len(circles)}"
    except ImportError:
        pass

    # 2. Generate G-Code
    gcode_text = generate_gcode(drawing_data, get_default_machining_params(), str(nc_file))
    assert nc_file.exists(), "NC output file was not created"
    assert nc_file.stat().st_size > 0, "NC output file is empty"

    # Verify G-Code contents
    assert "G54" in gcode_text, "Missing G54 work coordinate system"
    assert "G83" in gcode_text, "Missing G83 drilling cycle"
    assert "G80" in gcode_text, "Missing G80 canned cycle cancel"
    assert "M30" in gcode_text, "Missing M30 program end"
    assert "X25.000 Y25.000" in gcode_text
    assert "X25.000 Y75.000" in gcode_text
    assert "X75.000 Y50.000" in gcode_text

    print(f"✓ Test 1 Passed: Generated {dxf_file.name} and {nc_file.name}")


def test_case_2_rounded_slot():
    """
    Test 2: 100x100 mm stock with 8mm rounded slot along path:
      (10, 50) -> (10, 10) -> (60, 10) -> (80, 30), depth 5mm
    Outputs: outputs/test2_slot.dxf and outputs/test2_slot.nc
    """
    path_points = [
        Point2D(x=10.0, y=50.0),
        Point2D(x=10.0, y=10.0),
        Point2D(x=60.0, y=10.0),
        Point2D(x=80.0, y=30.0),
    ]
    drawing_data = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        stock_thickness=10.0,
        holes=[],
        slots=[
            SlotContour(
                width=8.0,
                depth=5.0,
                centerline_path=path_points,
            )
        ],
    )

    dxf_file = OUTPUTS_DIR / "test2_slot.dxf"
    nc_file = OUTPUTS_DIR / "test2_slot.nc"

    # 1. Export DXF
    dxf_result = export_drawing_to_dxf(drawing_data, str(dxf_file))
    assert Path(dxf_result).exists(), "DXF output file was not created"
    assert Path(dxf_result).stat().st_size > 0, "DXF output file is empty"

    # Verify DXF contents using ezdxf
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_file))
        assert "STOCK_OUTLINE" in doc.layers
        assert "SLOTS_CENTERLINE" in doc.layers
        assert "SLOTS_CONTOUR" in doc.layers
        polylines = list(doc.modelspace().query("LWPOLYLINE"))
        assert len(polylines) >= 3, f"Expected at least 3 polylines (stock, center, contour), got {len(polylines)}"
    except ImportError:
        pass

    # 2. Generate G-Code
    gcode_text = generate_gcode(drawing_data, get_default_machining_params(), str(nc_file))
    assert nc_file.exists(), "NC output file was not created"
    assert nc_file.stat().st_size > 0, "NC output file is empty"

    # Verify G-Code contents
    assert "G54" in gcode_text, "Missing G54 work coordinate system"
    assert "M30" in gcode_text, "Missing M30 program end"
    assert "X10.000 Y50.000" in gcode_text, "Missing slot entry point"
    assert "X80.000 Y30.000" in gcode_text, "Missing slot exit point"
    assert "Z-5.000" in gcode_text, "Missing final Z-depth target (-5.000mm)"

    print(f"Test 2 Passed: Generated {dxf_file.name} and {nc_file.name}")


def test_case_3_outer_contour_milling():
    """
    Test 3: 100x100 mm stock with outer contour (4 edges) and 3 holes (matching actual user drawing).
    Outputs: outputs/test3_contour.dxf and outputs/test3_contour.nc
    """
    drawing_data = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        stock_thickness=10.0,
        holes=[
            DrillHole(center=Point2D(x=25.0, y=25.0), diameter=10.0, depth=10.0),
            DrillHole(center=Point2D(x=75.0, y=50.0), diameter=10.0, depth=10.0),
            DrillHole(center=Point2D(x=25.0, y=75.0), diameter=10.0, depth=10.0),
        ],
        slots=[],
        outer_contour=[
            Point2D(x=0.0, y=0.0),
            Point2D(x=100.0, y=0.0),
            Point2D(x=100.0, y=100.0),
            Point2D(x=0.0, y=100.0),
            Point2D(x=0.0, y=0.0),
        ],
    )

    dxf_file = OUTPUTS_DIR / "test3_contour.dxf"
    nc_file = OUTPUTS_DIR / "test3_contour.nc"

    # 1. Export DXF
    dxf_result = export_drawing_to_dxf(drawing_data, str(dxf_file))
    assert Path(dxf_result).exists()
    assert Path(dxf_result).stat().st_size > 0

    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_file))
        assert "PART_OUTLINE_CONTOUR" in doc.layers
        assert "HOLES" in doc.layers
    except ImportError:
        pass

    # 2. Generate G-Code with outer contour milling
    params = get_default_machining_params()
    params["mill_outer_contour"] = True
    params["cut_depth_z"] = -5.0
    params["cut_depth_per_pass"] = 1.0

    gcode_text = generate_gcode(drawing_data, params, str(nc_file))
    assert nc_file.exists()
    assert nc_file.stat().st_size > 0

    assert "OPERATION: PROFILE MILLING OUTER CONTOUR" in gcode_text
    assert "OPERATION: DRILLING 3 HOLES" in gcode_text
    assert "X100.000 Y0.000" in gcode_text
    assert "X100.000 Y100.000" in gcode_text
    assert "X0.000 Y100.000" in gcode_text
    assert "X0.000 Y0.000" in gcode_text
    assert "G83" in gcode_text

    print(f"Test 3 Passed: Generated {dxf_file.name} and {nc_file.name}")


if __name__ == "__main__":
    test_case_1_three_holes()
    test_case_2_rounded_slot()
    test_case_3_outer_contour_milling()
    print("\nAll CAD/CAM benchmark tests executed successfully!")
