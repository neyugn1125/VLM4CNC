"""
Kiem thu don vi cho phan he mo phong duong chay dao CNC (ui/cnc_simulator.py).
Bao gom:
  1. GCodeToolpathParser: boc tach G00, G01, G02, G03, G83, tinh quang duong va thoi gian.
  2. ToolpathCanvasWidget: phep chieu he toa do CNC sang viewport Qt.
  3. CNCToolpathSimulatorWidget: van hanh Transport (Play/Pause, Step, Reset, Scrubber) va cap nhat DRO.
"""

import math
import os
from pathlib import Path
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QSizePolicy
from ui.cnc_simulator import (
    CNCToolpathSimulatorWidget,
    GCodeToolpathParser,
    ToolpathCanvasWidget,
    ToolpathSegment,
)


@pytest.fixture(scope="session")
def qapp():
    """Khoi tao instance QApplication cho kiem thu."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


SAMPLE_GCODE = """%
O1000 (TEST PART)
G21 G90 G54
T1 M06
G43 H1 Z50.000
M03 S1500
G00 X10.000 Y10.000
G00 Z2.000
G01 Z-5.000 F100.0
G01 X60.000 Y10.000 F300.0
G01 X60.000 Y50.000 F300.0
G00 Z50.000
G83 X25.000 Y25.000 Z-10.000 R2.000 Q2.000 F100.0
G80
G00 Z50.000
M05
M30
%
"""


def test_gcode_toolpath_parser():
    """Kiem tra parser doc dung cac lenh di chuyen va chu trinh gia cong."""
    parser = GCodeToolpathParser()
    segments = parser.parse(SAMPLE_GCODE)

    assert len(segments) > 0, "Parser phai tra ve danh sach doan chay dao khong rong"

    # Kiem tra co cac doan G00 va G01
    g00_segments = [s for s in segments if s.motion_type == "G00"]
    g01_segments = [s for s in segments if s.motion_type == "G01"]
    g83_segments = [s for s in segments if s.motion_type == "G83"]

    assert len(g00_segments) >= 2, "Phai co it nhat 2 doan di chuyen nhanh G00"
    assert len(g01_segments) >= 3, "Phai co it nhat 3 doan an phoi G01"
    assert len(g83_segments) >= 1, "Phai co it nhat 1 chu trinh khoan G83"

    # Kiem tra thong ke chieu dai va thoi gian
    assert parser.total_cut_dist > 0.0, "Tong quang duong cat phai lon hon 0"
    assert parser.total_rapid_dist > 0.0, "Tong quang duong chay nhanh phai lon hon 0"
    assert parser.est_time_seconds > 0.0, "Thoi gian gia cong uoc tinh phai lon hon 0"

    # Kiem tra bounding box
    b_min, b_max = parser.bbox_min, parser.bbox_max
    assert b_min[0] <= 10.0
    assert b_max[0] >= 60.0
    assert b_min[1] <= 10.0
    assert b_max[1] >= 50.0


def test_toolpath_canvas_widget(qapp):
    """Kiem tra widget ve do hoa toa do 2D va phep chieu cnc_to_screen."""
    canvas = ToolpathCanvasWidget()
    canvas.resize(400, 300)
    canvas.set_stock(100.0, 100.0)

    # Chuyen doi toa do goc (0,0) va (100,100)
    pt0 = canvas.to_screen(0.0, 0.0)
    pt100 = canvas.to_screen(100.0, 100.0)

    # Do truc Y tren man hinh dao nguoc so voi CNC (pt0.y() > pt100.y() vi Y=0 o duoi)
    assert pt100.x() > pt0.x(), "Toa do X man hinh phai tang dan tu trai sang phai"
    assert pt0.y() > pt100.y(), "Toa do Y man hinh cua CNC Y=0 phai lon hon Y=100 (phia duoi)"

    # Nap doan toolpath vao canvas
    parser = GCodeToolpathParser()
    segments = parser.parse(SAMPLE_GCODE)
    canvas.set_segments(segments, tool_dia=3.0)
    assert len(canvas.segments) == len(segments)

    # Kiem tra cap nhat phan doan hien tai
    canvas.set_current_step(2)
    assert canvas.current_segment_idx == 2


def test_cnc_simulator_widget_lifecycle(qapp):
    """Kiem tra quy trinh nap G-code, van hanh cac nut dieu khien va cap nhat DRO."""
    sim = CNCToolpathSimulatorWidget()
    sim.load_gcode(SAMPLE_GCODE, stock_w=100.0, stock_h=100.0, tool_dia=3.0)

    # Kiem tra trang thai ban dau
    assert len(sim.segments) > 0
    assert sim.current_idx == 0
    assert sim.dro_feed is not None
    assert sim.dro_spindle is not None

    # Chay tung buoc tiep theo
    sim.step_forward()
    assert sim.current_idx == 1

    # Chay lui 1 buoc (Step backward)
    sim.step_backward()
    assert sim.current_idx == 0

    # Chay tiep 2 buoc
    sim.step_forward()
    sim.step_forward()
    assert sim.current_idx == 2

    # Tua thanh truot Scrubber den vi tri tuy y
    sim.slider_scrub.setValue(4)
    assert sim.current_idx == 4

    # Dieu chinh toc do mo phong
    sim.slider_speed.setValue(5)
    assert sim.playback_speed == 5.0

    # Kiem tra View Toggles
    sim.chk_grid.setChecked(False)
    assert sim.canvas.show_grid is False
    sim.chk_arrows.setChecked(False)
    assert sim.canvas.show_arrows is False
    sim.chk_traveled.setChecked(False)
    assert sim.canvas.show_traveled is False

    # Kiem tra timeline va envelope
    assert sim.parser.envelope_width > 0.0
    assert sim.parser.envelope_height > 0.0
    for seg in sim.segments:
        assert hasattr(seg, "duration")
        assert seg.duration >= 0.0
        assert seg.time_end >= seg.time_start

    # Dat lai mo phong (Reset)
    sim.reset_simulation()
    assert sim.current_idx == 0
    assert "Chạy" in sim.btn_run.text()

    # Bat dau / Tam dung mo phong
    sim.toggle_run()
    assert sim.timer.isActive() is True
    assert "Tạm dừng" in sim.btn_run.text()

    sim.toggle_run()
    assert sim.timer.isActive() is False
    sim.close()


def test_simulator_independent_slots_no_cross_cut(qapp):
    """
    Verify that multi-slot G-code loaded into simulator contains no cutting
    segments crossing between independent slots at cutting depth.
    """
    from core.gcode_engine import generate_gcode
    from vision.schemas import DrawingIR, Point2D, SlotContour

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
    params = {
        "cut_depth_z": -5.0,
        "cut_depth_per_pass": 2.5,
        "safe_z": 5.0,
        "approach_z": 2.0,
        "tool_diameter": 4.0,
        "mill_slot_width": True,
    }
    gcode = generate_gcode(drawing_data, params)

    parser = GCodeToolpathParser()
    segments = parser.parse(gcode, default_tool_dia=4.0)

    # Filter all cutting segments (Z <= 0 and G01/G02/G03)
    cutting_segs = [s for s in segments if s.is_cutting]
    assert len(cutting_segs) > 0

    # Verify G02 circular segments are present for slot racetrack loops
    g02_segs = [s for s in segments if s.motion_type == "G02"]
    assert len(g02_segs) > 0, "Expected G02 racetrack segments to be parsed"

    # CRITICAL CHECK: Verify NO cutting segment cuts across between independent slots
    for seg in cutting_segs:
        # Cross cut from Slot 1 (near 50, 80) to Slot 2 (near 20, 16)
        if math.hypot(seg.start[0] - 50.0, seg.start[1] - 80.0) < 15.0 and math.hypot(seg.end[0] - 20.0, seg.end[1] - 16.0) < 15.0:
            pytest.fail(f"Found forbidden cross-workpiece cut between Slot 1 and Slot 2: {seg.raw_text}")
        # Cross cut from Slot 2 (near 80, 64) to Slot 3 (near 65, 28)
        if math.hypot(seg.start[0] - 80.0, seg.start[1] - 64.0) < 15.0 and math.hypot(seg.end[0] - 65.0, seg.end[1] - 28.0) < 15.0:
            pytest.fail(f"Found forbidden cross-workpiece cut between Slot 2 and Slot 3: {seg.raw_text}")

    # Verify rapid segments at safe Z connect the slots
    rapid_safe_z = [s for s in segments if s.motion_type == "G00" and s.end[2] >= 5.0]
    assert len(rapid_safe_z) >= 3, "Expected rapid moves at safe Z between operations"


def test_arc_interpolation_g02_g03(qapp):
    """
    Kiem tra tinh toan hinh hoc noi suy cung tron G02/G03:
      - Xac dinh tam cung I/J hoac R
      - Tinh dung ban kinh R va chieu dai cung thuc te L = R * |sweep_angle|
      - Tinh toa do chuoi diem noi suy tren canvas
    """
    # G02: Tu (10, 20) qua (30, 20) voi I=10, J=0 -> Tam (20, 20), R=10, nua duong tron (180 do)
    gcode_arc = """%
    G21 G90
    G00 X10.000 Y20.000 Z2.000
    G01 Z-2.000 F100.0
    G02 X30.000 Y20.000 I10.000 J0.000 F300.0
    G03 X10.000 Y20.000 R10.000 F300.0
    G00 Z5.000
    M30
    %"""
    parser = GCodeToolpathParser()
    segments = parser.parse(gcode_arc)

    g02_seg = next(s for s in segments if s.motion_type == "G02")
    assert g02_seg.is_arc is True
    assert g02_seg.arc_clockwise is True
    assert math.isclose(g02_seg.arc_center[0], 20.0, abs_tol=1e-3)
    assert math.isclose(g02_seg.arc_center[1], 20.0, abs_tol=1e-3)
    assert math.isclose(g02_seg.arc_radius, 10.0, abs_tol=1e-3)
    # Nua vong tron: length = pi * R = 10 * pi ~ 31.4159
    expected_len = math.pi * 10.0
    assert math.isclose(g02_seg.length, expected_len, rel_tol=1e-2)

    g03_seg = next(s for s in segments if s.motion_type == "G03")
    assert g03_seg.is_arc is True
    assert g03_seg.arc_clockwise is False
    assert math.isclose(g03_seg.arc_radius, 10.0, abs_tol=1e-3)
    assert math.isclose(g03_seg.length, expected_len, rel_tol=1e-2)

    # Kiem tra sinh diem tren canvas
    canvas = ToolpathCanvasWidget()
    canvas.resize(500, 500)
    canvas.set_stock(100.0, 100.0)
    pts = canvas._get_segment_screen_points(g02_seg, steps=16)
    assert len(pts) == 17, f"Expected 17 screen points for 16-step arc, got {len(pts)}"
    # Diem dau va diem cuoi phai khop voi start va end
    start_scr = canvas.to_screen(g02_seg.start[0], g02_seg.start[1])
    end_scr = canvas.to_screen(g02_seg.end[0], g02_seg.end[1])
    assert math.isclose(pts[0].x(), start_scr.x(), abs_tol=1.0)
    assert math.isclose(pts[0].y(), start_scr.y(), abs_tol=1.0)
    assert math.isclose(pts[-1].x(), end_scr.x(), abs_tol=1.0)
    assert math.isclose(pts[-1].y(), end_scr.y(), abs_tol=1.0)


def test_dro_layout_stability_no_jitter(qapp):
    """
    Xac minh co che chong rung man hinh (Layout Thrashing Prevention):
      - Cac nhan DRO co QSizePolicy.Policy.Ignored theo chieu ngang
      - Khi cap nhat van ban dai dot bien trong animation loop, minimum size va layout khong bi ep gian no
    """
    sim = CNCToolpathSimulatorWidget()
    sim.resize(800, 600)
    sim.show()

    # Kiem tra SizePolicy Ignored da duoc thiet lap cho cac nhan thong so
    assert sim.dro_cmd.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.dro_x.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.dro_y.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.dro_z.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.dro_feed.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.dro_spindle.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.dro_motion.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert sim.lbl_stats.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored

    qapp.processEvents()
    initial_w = sim.width()
    initial_cmd_w = sim.dro_cmd.width()

    # Thu thay doi text voi chuoi cuc dai (> 100 ky tu)
    sim.dro_cmd.setText("G83 X123.456 Y789.012 Z-15.000 R2.000 Q2.000 F150.0 (EXTREMELY LONG COMMAND THAT PREVIOUSLY BROKE LAYOUT)")
    sim.dro_x.setText("+999.999 mm")
    sim.dro_y.setText("+999.999 mm")
    sim.dro_z.setText("-999.999 mm")
    sim.lbl_stats.setText("T: 99m 59s / 99m 59s | Tiến độ: 100.0% | Cắt: 99999.9mm | Nhanh: 99999.9mm")

    qapp.processEvents()

    # Chieu rong cua widget khong bi giat / bi ep thay doi boi text moi
    assert sim.width() == initial_w, "Widget width bi thay doi khi text DRO cap nhat!"
    sim.close()

