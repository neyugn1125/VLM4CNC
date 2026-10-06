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

from vision.schemas import DrawingIR, DrillHole, MachiningParams, Point2D, SlotContour
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
        "mill_large_holes": False,
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
    assert "X102.000 Y102.000" in gcode_text
    assert "X102.000 Y-2.000" in gcode_text
    assert "X-2.000 Y-2.000" in gcode_text
    assert "X-2.000 Y102.000" in gcode_text
    assert "G98 G83" in gcode_text
    assert "G00 G91 G28 Z0.000" in gcode_text
    assert "G28 X0.000 Y0.000" in gcode_text

    # Verify Air Lead-in & Lead-out
    assert "(Rapid to air lead-in point)" in gcode_text
    assert "(Plunge in free air)" in gcode_text
    assert "(Tangential lead-in)" in gcode_text
    assert "(Tangential air lead-out)" in gcode_text

    # 3. Verify G41 Machine Compensation mode
    params_g41 = dict(params)
    params_g41["cutter_comp"] = "G41"
    params_g41["cutter_offset_d"] = 1
    nc_g41_file = OUTPUTS_DIR / "test3_contour_g41.nc"
    gcode_g41 = generate_gcode(drawing_data, params_g41, str(nc_g41_file))
    assert "G41 D1" in gcode_g41
    assert "G40" in gcode_g41
    assert "X100.000" in gcode_g41

    # 4. Verify Circular Pocket Milling for large holes
    params_circ = dict(params)
    params_circ["mill_large_holes"] = True
    nc_circ_file = OUTPUTS_DIR / "test3_contour_circ.nc"
    gcode_circ = generate_gcode(drawing_data, params_circ, str(nc_circ_file))
    assert "CIRCULAR POCKET MILLING" in gcode_circ
    assert "G03" in gcode_circ
    assert "FINAL RADIUS: 3.000mm | RADIAL RINGS: 2" in gcode_circ
    assert "Move to ring radius 1.500mm" in gcode_circ
    assert "Move to ring radius 3.000mm" in gcode_circ

    print(f"Test 3 Passed: Generated {dxf_file.name} and {nc_file.name}")


def test_case_4_circular_pocket_hole_boring():
    """
    Test 4: Circular pocket milling / boring for large holes:
      Hole at (50, 50) with Ø16mm, tool Ø4mm.
      Final cut radius R = (16 - 4) / 2 = 6.0mm.
      Stepover = 4 * 0.65 = 2.6mm -> n = ceil(6.0 / 2.6) = 3 rings (2.0mm, 4.0mm, 6.0mm).
    """
    drawing_data = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        stock_thickness=10.0,
        holes=[
            DrillHole(center=Point2D(x=50.0, y=50.0), diameter=16.0, depth=5.0),
        ],
        slots=[],
    )
    nc_file = OUTPUTS_DIR / "test4_hole_boring.nc"
    params = {
        "cut_depth_z": -5.0,
        "cut_depth_per_pass": 2.5,
        "tool_diameter": 4.0,
        "mill_large_holes": True,
    }
    gcode = generate_gcode(drawing_data, params, str(nc_file))
    assert "OPERATION: CIRCULAR POCKET MILLING HOLE #1 (Ø16.00mm)" in gcode
    assert "FINAL RADIUS: 6.000mm | RADIAL RINGS: 3" in gcode
    assert "G03" in gcode
    assert "Move to ring radius 2.000mm" in gcode
    assert "Move to ring radius 4.000mm" in gcode
    assert "Move to ring radius 6.000mm" in gcode
    print(f"Test 4 Passed: Generated {nc_file.name}")


def test_case_5_multiple_slots_and_racetrack_milling():
    """
    Test 5: Independent multiple slots with safe retracts and racetrack stadium passes:
      - Slot 1: (10, 80) -> (50, 80), width 12mm, depth 5mm
      - Slot 2: (20, 16) -> (80, 64), width 20mm, depth 5mm
      - Slot 3: (65, 28) -> (90, 10), width 8mm, depth 5mm
      Tool diameter: 4.0mm
    Verifies:
      1. Each slot is treated as an independent operation with safe retract G00 Z5.0.
      2. No continuous cut connects the end of Slot 1 to start of Slot 2 at cut depth.
      3. Racetrack expanding passes (G02 arcs) are generated when slot.width > tool_diameter.
      4. When mill_slot_width=False, only centerline passes are generated (no G02).
    """
    drawing_data = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        stock_thickness=10.0,
        holes=[],
        slots=[
            SlotContour(width=12.0, depth=5.0, centerline_path=[Point2D(x=10.0, y=80.0), Point2D(x=50.0, y=80.0)]),
            SlotContour(width=20.0, depth=5.0, centerline_path=[Point2D(x=20.0, y=16.0), Point2D(x=80.0, y=64.0)]),
            SlotContour(width=8.0, depth=5.0, centerline_path=[Point2D(x=65.0, y=28.0), Point2D(x=90.0, y=10.0)]),
        ],
    )
    nc_file = OUTPUTS_DIR / "test5_multiple_slots.nc"
    params = {
        "cut_depth_z": -5.0,
        "cut_depth_per_pass": 2.5,
        "safe_z": 5.0,
        "approach_z": 2.0,
        "tool_diameter": 4.0,
        "mill_slot_width": True,
    }
    gcode = generate_gcode(drawing_data, params, str(nc_file))
    assert "OPERATION: MILLING 3 INDEPENDENT SLOTS" in gcode
    assert "SLOT MILLING #1 (Width: 12.00mm, Depth: -5.00mm)" in gcode
    assert "SLOT MILLING #2 (Width: 20.00mm, Depth: -5.00mm)" in gcode
    assert "SLOT MILLING #3 (Width: 8.00mm, Depth: -5.00mm)" in gcode

    # Verify G02 CW arcs for rounded caps in racetrack passes
    assert "G02" in gcode
    assert "(End cap arc)" in gcode
    assert "(Start cap arc)" in gcode

    # Verify safe retract G00 Z5.000 occurs between slots
    lines = gcode.splitlines()
    slot1_indices = [i for i, l in enumerate(lines) if "SLOT MILLING #1" in l]
    slot2_indices = [i for i, l in enumerate(lines) if "SLOT MILLING #2" in l]
    assert len(slot1_indices) == 1 and len(slot2_indices) == 1
    between_slot1_and_slot2 = lines[slot1_indices[0]:slot2_indices[0]]

    # Ensure retract to safe Z occurs before slot 2 starts
    assert any("G00 Z5.000" in l and "safe Z" in l for l in between_slot1_and_slot2)

    # Verify with mill_slot_width=False: only centerline passes, no G02
    params_no_expand = dict(params)
    params_no_expand["mill_slot_width"] = False
    gcode_no_expand = generate_gcode(drawing_data, params_no_expand)
    assert "OPERATION: MILLING 3 INDEPENDENT SLOTS" in gcode_no_expand
    assert "(Centerline, Width: 12.00mm" in gcode_no_expand
    assert "G02" not in gcode_no_expand
    print(f"Test 5 Passed: Generated {nc_file.name}")


def test_case_6_machining_params_pydantic_and_exports():
    """Test 6: Verify MachiningParams Pydantic model validation and core package exports."""
    from core import (
        export_drawing_to_dxf,
        generate_gcode,
        MachiningParams,
        ToolSettings,
        DXFEngine,
        GCodeEngine,
    )

    # 1. Test MachiningParams model validation and property aliases
    params = MachiningParams(
        tool_diameter=5.0,
        cut_feed=600.0,
        plunge_feed=150.0,
        spindle_rpm=4000,
        safe_z=25.0,
        cut_depth_z=-4.0,
    )
    assert params.tool_diameter == 5.0
    assert params.feedrate_xy == 600.0
    assert params.spindle_speed == 4000

    # 2. Test generate_gcode with MachiningParams object
    ir = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        holes=[DrillHole(center=Point2D(x=25.0, y=25.0), diameter=10.0)],
    )
    nc_text = generate_gcode(ir, machining_params=params)
    assert "Ø5.000 mm ENDMILL/DRILL" in nc_text
    assert "4000 RPM" in nc_text
    assert "600.0 mm/min" in nc_text

    # 3. Test GCodeEngine legacy wrapper syncing ToolSettings to generate()
    engine = GCodeEngine(settings=ToolSettings(
        tool_diameter=6.0,
        feed_rate=450.0,
        spindle_speed=5500,
        cut_depth=-3.0,
    ))
    gcode_engine_out = engine.generate(ir)
    assert "Ø6.000 mm ENDMILL/DRILL" in gcode_engine_out
    assert "5500 RPM" in gcode_engine_out
    assert "450.0 mm/min" in gcode_engine_out


def test_sub_generators_isolated_execution():
    """
    Kiem tra tinh doc lap va do chinh xac cua cac sub-generators trong core.gcode_engine:
      - _calculate_z_passes
      - _emit_safety_header
      - _emit_drilling_cycles
      - _emit_circular_pocket_cycles
      - _emit_slot_cycles
      - _emit_contour_cycle
      - _emit_footer
    """
    from core.gcode_engine import (
        _calculate_z_passes,
        _emit_safety_header,
        _emit_drilling_cycles,
        _emit_circular_pocket_cycles,
        _emit_slot_cycles,
        _emit_contour_cycle,
        _emit_footer,
    )

    # 1. Test _calculate_z_passes voi cac gia tri am va duong
    passes_neg = _calculate_z_passes(-6.0, 2.0)
    assert passes_neg == [-2.0, -4.0, -6.0], f"Expected [-2.0, -4.0, -6.0], got {passes_neg}"

    passes_pos = _calculate_z_passes(5.0, 2.0)
    assert passes_pos == [-2.0, -4.0, -5.0], f"Expected [-2.0, -4.0, -5.0], got {passes_pos}"

    passes_zero = _calculate_z_passes(0.0, 2.0)
    assert passes_zero == [], "Depth 0 should return no cutting passes"

    # 2. Test _emit_safety_header
    params_model = MachiningParams(
        spindle_rpm=12000,
        cut_feed=800.0,
        plunge_feed=250.0,
        safe_z=5.0,
        approach_z=2.0,
    )
    ir_hdr = DrawingIR(stock_width=120.0, stock_height=80.0, stock_thickness=15.0)
    lines_hdr = _emit_safety_header(params_model, ir_hdr)
    hdr_text = "\n".join(lines_hdr)
    assert "G21" in hdr_text
    assert "G90" in hdr_text
    assert "G54" in hdr_text
    assert "M03 S12000" in hdr_text
    assert "120.00 x 80.00" in hdr_text

    # 3. Test _emit_drilling_cycles
    ir_drill = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        holes=[
            DrillHole(center=Point2D(x=30.0, y=40.0), diameter=4.0, depth=8.0),
        ],
    )
    lines_drill = _emit_drilling_cycles(ir_drill.holes, params_model)
    drill_text = "\n".join(lines_drill)
    assert "G83 X30.000 Y40.000 Z-8.000" in drill_text
    assert "G80" in drill_text

    # 4. Test _emit_circular_pocket_cycles
    ir_pocket = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        holes=[
            DrillHole(center=Point2D(x=50.0, y=50.0), diameter=12.0, depth=4.0),
        ],
    )
    params_pocket = MachiningParams(
        **dict(get_default_machining_params(), mill_large_holes=True, tool_diameter=4.0)
    )
    lines_pocket = _emit_circular_pocket_cycles(ir_pocket.holes, params_pocket)
    pocket_text = "\n".join(lines_pocket)
    assert "CIRCULAR POCKET MILLING" in pocket_text
    assert "G03" in pocket_text
    assert "I" in pocket_text or "J" in pocket_text

    # 5. Test _emit_slot_cycles
    ir_slot = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        slots=[
            SlotContour(width=4.0, depth=3.0, centerline_path=[Point2D(x=10.0, y=10.0), Point2D(x=40.0, y=10.0)]),
        ],
    )
    lines_slot = _emit_slot_cycles(ir_slot.slots, params_model)
    slot_text = "\n".join(lines_slot)
    assert "SLOT MILLING" in slot_text
    assert "X40.000 Y10.000" in slot_text

    # 6. Test _emit_contour_cycle
    contour_pts = [
        Point2D(x=0.0, y=0.0),
        Point2D(x=50.0, y=0.0),
        Point2D(x=50.0, y=50.0),
        Point2D(x=0.0, y=50.0),
        Point2D(x=0.0, y=0.0),
    ]
    params_contour = MachiningParams(
        **dict(get_default_machining_params(), mill_outer_contour=True, stock_thickness=5.0)
    )
    lines_contour = _emit_contour_cycle(contour_pts, params_contour)
    contour_text = "\n".join(lines_contour)
    assert "PROFILE MILLING OUTER CONTOUR" in contour_text
    assert "G41" in contour_text or "G01" in contour_text

    # 7. Test _emit_footer
    lines_footer = _emit_footer(params_model)
    footer_text = "\n".join(lines_footer)
    assert "M05" in footer_text
    assert "M09" in footer_text
    assert "G28" in footer_text
    assert "M30" in footer_text


if __name__ == "__main__":
    test_case_1_three_holes()
    test_case_2_rounded_slot()
    test_case_3_outer_contour_milling()
    test_case_4_circular_pocket_hole_boring()
    test_case_5_multiple_slots_and_racetrack_milling()
    test_case_6_machining_params_pydantic_and_exports()
    test_sub_generators_isolated_execution()
    print("\nAll CAD/CAM benchmark tests executed successfully!")


