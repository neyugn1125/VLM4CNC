"""
Kiem thu don vi cho phan he mo phong duong chay dao CNC (ui/cnc_simulator.py).
Bao gom:
  1. GCodeToolpathParser: boc tach G00, G01, G02, G03, G83, tinh quang duong va thoi gian.
  2. ToolpathCanvasWidget: phep chieu he toa do CNC sang viewport Qt.
  3. CNCToolpathSimulatorWidget: van hanh Transport (Play/Pause, Step, Reset, Scrubber) va cap nhat DRO.
"""

import os
from pathlib import Path
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
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

    # Tua thanh truot Scrubber den vi tri tuy y
    sim.slider_scrub.setValue(4)
    assert sim.current_idx == 4

    # Dieu chinh toc do mo phong
    sim.slider_speed.setValue(5)
    assert sim.playback_speed == 5.0

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
    assert "Chạy" in sim.btn_run.text()

    sim.close()
