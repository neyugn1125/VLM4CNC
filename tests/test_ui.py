"""
Tests for VLM4CNC Desktop UI (PySide6 MainWindow).
Verifies:
  1. 3-column layout structure in QSplitter.
  2. Human-in-the-Loop coordinate table editing (add, delete, modify, and build_drawing_ir_from_tables).
  3. CAM parameter controls and output tabs.
  4. VLMWorker background thread signal handling.
Runs in headless offscreen mode without displaying windows.
"""

import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Force offscreen rendering for headless testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit, QTableWidgetItem
from ui.main_window import MainWindow, VLMWorker
from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour


@pytest.fixture(scope="session")
def qapp():
    """Ensure a single QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_3_columns_and_components(qapp):
    """Verify 3-column layout, engine selector, and default CAM parameters."""
    window = MainWindow()

    # Window title and visibility
    assert "VLM4CNC" in window.windowTitle()
    assert window.isVisible() is False

    # Check 3 columns in QSplitter
    assert window.splitter.count() == 3

    # Column 1 components
    assert window.btn_select_file is not None
    assert window.combo_engine.count() == 3
    engine_texts = [window.combo_engine.itemText(i) for i in range(window.combo_engine.count())]
    assert any("Qwen2.5-VL 7B" in t for t in engine_texts)
    assert any("Google Gemini: 3.8 Flash" in t for t in engine_texts)
    assert any("OpenAI: GPT-5.5 Pro" in t for t in engine_texts)

    # API Key input controls
    assert window.txt_api_key is not None
    assert window.btn_toggle_key is not None
    assert window.txt_api_key.isEnabled() is False  # Mặc định Local Ollama nên vô hiệu hóa
    assert window.btn_toggle_key.isEnabled() is False

    # Column 2 components (Tables)
    assert window.table_holes.columnCount() == 5
    assert window.table_slots.columnCount() == 5
    assert window.table_contour.columnCount() == 3
    assert window.table_contour.rowCount() == 5
    assert window.chk_mill_contour.isChecked() is True
    assert window.chk_mill_holes.isChecked() is True
    assert window.spin_stock_w.value() == 100.0
    assert window.spin_stock_h.value() == 100.0
    assert window.spin_stock_t.value() == 10.0

    # Column 3 components (CAM & Logs & Simulator)
    assert window.spin_tool_dia.value() == 3.0
    assert window.spin_cut_depth_pass.value() == 1.0
    assert window.spin_spindle_speed.value() == 1500
    assert window.spin_spindle_rpm.value() == 1500
    assert window.spin_feed_xy.value() == 300.0
    assert window.spin_feed_cut.value() == 300.0
    assert window.spin_feed_plunge.value() == 100.0
    assert window.spin_safe_z.value() == 50.0
    assert window.spin_approach_z.value() == 2.0
    assert window.spin_cut_depth_z.value() == -5.0
    assert window.spin_tool_number.value() == 1
    assert window.spin_tool_offset.value() == 1
    assert window.spin_prog_number.value() == 1000

    # Output tabs
    assert window.tabs_output.count() == 3
    assert "Mô phỏng" in window.tabs_output.tabText(0)
    assert "Xem trước G-Code" in window.tabs_output.tabText(1)
    assert "Nhật ký" in window.tabs_output.tabText(2)
    assert window.simulator_widget is not None

    window.close()


def test_human_in_the_loop_table_editing(qapp):
    """Verify adding, editing, deleting rows and dynamically rebuilding DrawingIR."""
    window = MainWindow()

    # Add 2 holes
    window._add_hole_row()
    window._add_hole_row()
    assert window.table_holes.rowCount() == 2
    assert window.table_holes.item(0, 4).text() == "5.000"

    # Edit hole 1: X=25.0, Y=25.0, Dia=10.0, Depth=8.0
    window.table_holes.setItem(0, 1, QTableWidgetItem("25.000"))
    window.table_holes.setItem(0, 2, QTableWidgetItem("25.000"))
    window.table_holes.setItem(0, 3, QTableWidgetItem("10.000"))
    window.table_holes.setItem(0, 4, QTableWidgetItem("8.000"))

    # Edit hole 2: X=75.0, Y=50.0, Dia=12.0, Depth=10.0
    window.table_holes.setItem(1, 1, QTableWidgetItem("75.000"))
    window.table_holes.setItem(1, 2, QTableWidgetItem("50.000"))
    window.table_holes.setItem(1, 3, QTableWidgetItem("12.000"))
    window.table_holes.setItem(1, 4, QTableWidgetItem("10.000"))

    # Add 2 slot points
    window._add_slot_row()
    window._add_slot_row()
    assert window.table_slots.rowCount() == 2

    # Point 1: (10, 20), Width=8.0, Depth=4.0
    window.table_slots.setItem(0, 1, QTableWidgetItem("10.000"))
    window.table_slots.setItem(0, 2, QTableWidgetItem("20.000"))
    window.table_slots.setItem(0, 3, QTableWidgetItem("8.000"))
    window.table_slots.setItem(0, 4, QTableWidgetItem("4.000"))

    # Point 2: (80, 20), Width=8.0, Depth=4.0
    window.table_slots.setItem(1, 1, QTableWidgetItem("80.000"))
    window.table_slots.setItem(1, 2, QTableWidgetItem("20.000"))
    window.table_slots.setItem(1, 3, QTableWidgetItem("8.000"))
    window.table_slots.setItem(1, 4, QTableWidgetItem("4.000"))

    # Reconstruct DrawingIR from tables
    ir = window.build_drawing_ir_from_tables()
    assert isinstance(ir, DrawingIR)
    assert len(ir.holes) == 2
    assert ir.holes[0].center.x == 25.0
    assert ir.holes[0].center.y == 25.0
    assert ir.holes[0].diameter == 10.0
    assert ir.holes[1].center.x == 75.0
    assert ir.holes[1].diameter == 12.0

    assert len(ir.slots) == 1
    assert ir.slots[0].width == 8.0
    assert ir.slots[0].depth == 4.0
    assert len(ir.slots[0].centerline_path) == 2
    assert ir.slots[0].centerline_path[1].x == 80.0

    # Test delete hole row
    window.table_holes.setCurrentCell(1, 0)
    window._delete_selected_hole()
    assert window.table_holes.rowCount() == 1

    window.close()


def test_vlm_worker_thread(qapp, tmp_path):
    """Verify VLMWorker emits finished_signal with DrawingIR without freezing UI."""
    sample_img = tmp_path / "dummy_drawing.png"
    sample_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")

    mock_ir = DrawingIR(
        stock_width=120.0,
        stock_height=80.0,
        stock_thickness=12.0,
        holes=[DrillHole(center=Point2D(x=30.0, y=40.0), diameter=8.0, depth=12.0)],
        slots=[],
    )

    received_signals = []

    def on_finished(ir, elapsed):
        received_signals.append((ir, elapsed))

    worker = VLMWorker(image_path=sample_img, provider="local")
    worker.finished_signal.connect(on_finished)

    with patch("ui.main_window.parse_drawing", return_value=mock_ir):
        worker.start()
        worker.wait(3000)
        qapp.processEvents()

    assert len(received_signals) == 1
    ir_res, elapsed_res = received_signals[0]
    assert ir_res.stock_width == 120.0
    assert len(ir_res.holes) == 1
    assert elapsed_res >= 0.0


def test_export_file_actions(qapp, tmp_path):
    """Verify DXF and G-Code export methods from MainWindow."""
    window = MainWindow()

    # Setup dummy data in tables
    window._add_hole_row()
    window.table_holes.setItem(0, 1, QTableWidgetItem("50.000"))
    window.table_holes.setItem(0, 2, QTableWidgetItem("50.000"))
    window.table_holes.setItem(0, 3, QTableWidgetItem("10.000"))
    window.table_holes.setItem(0, 4, QTableWidgetItem("10.000"))

    # Test export DXF with mocked QFileDialog
    dxf_target = tmp_path / "export_test.dxf"
    with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(dxf_target), "DXF Files (*.dxf)")):
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            window._on_export_dxf()

    assert dxf_target.exists()
    assert dxf_target.stat().st_size > 0

    # Test export G-Code with mocked QFileDialog
    nc_target = tmp_path / "export_test.nc"
    with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(nc_target), "G-Code Files (*.nc)")):
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            window._on_generate_gcode()

    assert nc_target.exists()
    assert nc_target.stat().st_size > 0
    assert "G54" in window.txt_gcode.toPlainText()

    window.close()


def test_api_key_interaction_and_validation(qapp, tmp_path):
    """Verify API key UI interaction, password toggling, caching, and validation."""
    window = MainWindow()

    # 1. Ban đầu Local Ollama được chọn: txt_api_key bị disable
    assert window.txt_api_key.isEnabled() is False
    assert window.btn_toggle_key.isEnabled() is False

    idx_openai = [i for i in range(window.combo_engine.count()) if window.combo_engine.itemData(i).get("provider") == "openai"][0]
    idx_gemini = [i for i in range(window.combo_engine.count()) if window.combo_engine.itemData(i).get("provider") == "gemini"][0]
    idx_local = [i for i in range(window.combo_engine.count()) if window.combo_engine.itemData(i).get("provider") == "local"][0]

    # 2. Chọn OpenAI
    window.combo_engine.setCurrentIndex(idx_openai)
    assert window.txt_api_key.isEnabled() is True
    assert window.btn_toggle_key.isEnabled() is True
    assert "sk-" in window.txt_api_key.placeholderText()

    # Nhập OpenAI API Key
    window.txt_api_key.setText("sk-test-openai-key-12345")
    assert window._api_keys["openai"] == "sk-test-openai-key-12345"

    # Kiểm tra nút toggle ẩn/hiện mật khẩu
    assert window.txt_api_key.echoMode() == QLineEdit.EchoMode.Password
    assert window.btn_toggle_key.text() == "Hiện"
    window.btn_toggle_key.click()
    assert window.txt_api_key.echoMode() == QLineEdit.EchoMode.Normal
    assert window.btn_toggle_key.text() == "Ẩn"
    window.btn_toggle_key.click()
    assert window.txt_api_key.echoMode() == QLineEdit.EchoMode.Password
    assert window.btn_toggle_key.text() == "Hiện"

    # 3. Chuyển sang Google Gemini
    window.combo_engine.setCurrentIndex(idx_gemini)
    assert "AIzaSy" in window.txt_api_key.placeholderText()
    # Nhập Gemini API Key
    window.txt_api_key.setText("AIzaSy-test-gemini-key-67890")
    assert window._api_keys["gemini"] == "AIzaSy-test-gemini-key-67890"

    # 4. Chuyển lại OpenAI: kiểm tra key đã lưu trước đó được tự động khôi phục
    window.combo_engine.setCurrentIndex(idx_openai)
    assert window.txt_api_key.text() == "sk-test-openai-key-12345"

    # 5. Chuyển lại Local: kiểm tra bị disable và xóa text hiển thị
    window.combo_engine.setCurrentIndex(idx_local)
    assert window.txt_api_key.isEnabled() is False
    assert window.txt_api_key.text() == ""

    # 6. Kiểm tra validation: Chọn OpenAI nhưng xóa trắng key, nạp ảnh mẫu và bấm phân tích
    window.combo_engine.setCurrentIndex(idx_openai)
    window.txt_api_key.setText("")

    dummy_img = tmp_path / "test_drawing.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
    window.current_image_path = dummy_img

    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        window._on_start_vlm_analysis()
        mock_warn.assert_called_once()
        args, _ = mock_warn.call_args
        assert "Thiếu khóa API" in args[1]
        assert window.vlm_worker is None

    window.close()


def test_multiple_slots_grouping_and_new_slot_button(qapp):
    """
    Verify slot grouping, 'Thêm rãnh mới' button, and checkbox for racetrack slot milling:
      1. Default chk_mill_slots is True.
      2. _add_new_slot() correctly increments slot index label ('Rãnh 1', 'Rãnh 2', ...).
      3. build_drawing_ir_from_tables() groups rows by slot label into independent SlotContour objects.
      4. _populate_tables_from_drawing_ir() properly sets 'Rãnh 1', 'Rãnh 2', etc. in column 0.
    """
    window = MainWindow()

    assert window.chk_mill_slots.isChecked() is True

    # Check button 'Thêm rãnh mới'
    assert hasattr(window, "btn_new_slot")
    window.table_slots.setRowCount(0)

    # Click add new slot -> Rãnh 1
    window._add_new_slot()
    assert window.table_slots.rowCount() == 2
    assert window.table_slots.item(0, 0).text() == "Rãnh 1"
    assert window.table_slots.item(1, 0).text() == "Rãnh 1"

    # Set coordinates for Slot 1: (10, 80) -> (50, 80), width 12.0, depth 5.0
    window.table_slots.setItem(0, 1, QTableWidgetItem("10.000"))
    window.table_slots.setItem(0, 2, QTableWidgetItem("80.000"))
    window.table_slots.setItem(0, 3, QTableWidgetItem("12.000"))
    window.table_slots.setItem(0, 4, QTableWidgetItem("5.000"))

    window.table_slots.setItem(1, 1, QTableWidgetItem("50.000"))
    window.table_slots.setItem(1, 2, QTableWidgetItem("80.000"))
    window.table_slots.setItem(1, 3, QTableWidgetItem("12.000"))
    window.table_slots.setItem(1, 4, QTableWidgetItem("5.000"))

    # Click add new slot again -> Rãnh 2
    window._add_new_slot()
    assert window.table_slots.rowCount() == 4
    assert window.table_slots.item(2, 0).text() == "Rãnh 2"
    assert window.table_slots.item(3, 0).text() == "Rãnh 2"

    # Set coordinates for Slot 2: (20, 16) -> (80, 64), width 20.0, depth 5.0
    window.table_slots.setItem(2, 1, QTableWidgetItem("20.000"))
    window.table_slots.setItem(2, 2, QTableWidgetItem("16.000"))
    window.table_slots.setItem(2, 3, QTableWidgetItem("20.000"))
    window.table_slots.setItem(2, 4, QTableWidgetItem("5.000"))

    window.table_slots.setItem(3, 1, QTableWidgetItem("80.000"))
    window.table_slots.setItem(3, 2, QTableWidgetItem("64.000"))
    window.table_slots.setItem(3, 3, QTableWidgetItem("20.000"))
    window.table_slots.setItem(3, 4, QTableWidgetItem("5.000"))

    # Reconstruct DrawingIR
    ir = window.build_drawing_ir_from_tables()
    assert len(ir.slots) == 2, f"Expected 2 independent slots, got {len(ir.slots)}"

    assert ir.slots[0].width == 12.0
    assert ir.slots[0].depth == 5.0
    assert len(ir.slots[0].centerline_path) == 2
    assert ir.slots[0].centerline_path[0].x == 10.0
    assert ir.slots[0].centerline_path[1].x == 50.0

    assert ir.slots[1].width == 20.0
    assert ir.slots[1].depth == 5.0
    assert len(ir.slots[1].centerline_path) == 2
    assert ir.slots[1].centerline_path[0].x == 20.0
    assert ir.slots[1].centerline_path[1].x == 80.0

    # Test populate back to tables
    window._populate_tables_from_drawing_ir(ir)
    assert window.table_slots.rowCount() == 4
    assert window.table_slots.item(0, 0).text() == "Rãnh 1"
    assert window.table_slots.item(1, 0).text() == "Rãnh 1"
    assert window.table_slots.item(2, 0).text() == "Rãnh 2"
    assert window.table_slots.item(3, 0).text() == "Rãnh 2"

    window.close()


def test_drawing_table_model_qt(qapp):
    """Kiem thu doc lap cac mo hinh QAbstractTableModel (Holes, Slots, Contour)."""
    from PySide6.QtCore import Qt
    from ui.models.drawing_table_model import (
        HolesTableModel,
        SlotsTableModel,
        ContourTableModel,
    )

    # 1. HolesTableModel
    holes = [
        DrillHole(center=Point2D(x=10.0, y=20.0), diameter=5.0, depth=6.0),
        DrillHole(center=Point2D(x=40.0, y=50.0), diameter=8.0, depth=10.0),
    ]
    model_holes = HolesTableModel(holes)
    assert model_holes.rowCount() == 2
    assert model_holes.columnCount() == 5
    assert model_holes.headerData(1, Qt.Orientation.Horizontal) == "Tọa độ X (mm)"

    # Doc du lieu dong 0
    idx_x0 = model_holes.index(0, 1)
    assert model_holes.data(idx_x0) == "10.000"

    # Chinh sua du lieu qua setData
    success = model_holes.setData(idx_x0, "15.5", Qt.ItemDataRole.EditRole)
    assert success is True
    assert model_holes.data(idx_x0) == "15.500"

    # Them va xoa lo khoan
    model_holes.add_hole(DrillHole(center=Point2D(x=70.0, y=70.0), diameter=12.0))
    assert model_holes.rowCount() == 3
    assert model_holes.remove_hole(0) is True
    assert model_holes.rowCount() == 2

    # 2. SlotsTableModel
    slots = [
        SlotContour(
            width=10.0,
            depth=4.0,
            centerline_path=[Point2D(x=0.0, y=0.0), Point2D(x=50.0, y=0.0)],
        )
    ]
    model_slots = SlotsTableModel(slots)
    assert model_slots.rowCount() == 2  # 2 diem tren duong tam
    assert model_slots.data(model_slots.index(0, 0)) == "Rãnh 1"

    # 3. ContourTableModel
    contour = [Point2D(x=0.0, y=0.0), Point2D(x=100.0, y=0.0), Point2D(x=100.0, y=100.0)]
    model_contour = ContourTableModel(contour)
    assert model_contour.rowCount() == 3
    assert model_contour.data(model_contour.index(1, 1)) == "100.000"


def test_table_data_adapter(qapp):
    """Kiem thu TableDataAdapter chuyen doi 2 chieu voi QTableWidget."""
    from PySide6.QtWidgets import QTableWidget
    from ui.models.drawing_table_model import TableDataAdapter

    tbl_h = QTableWidget(0, 5)
    tbl_s = QTableWidget(0, 5)
    tbl_c = QTableWidget(0, 3)

    adapter = TableDataAdapter(tbl_h, tbl_s, tbl_c)

    # 1. Populate tu DrawingIR
    test_ir = DrawingIR(
        stock_width=120.0,
        stock_height=90.0,
        stock_thickness=15.0,
        holes=[DrillHole(center=Point2D(x=20.0, y=30.0), diameter=6.0, depth=8.0)],
        slots=[
            SlotContour(
                width=8.0,
                depth=5.0,
                centerline_path=[Point2D(x=10.0, y=10.0), Point2D(x=60.0, y=10.0)],
            )
        ],
    )
    adapter.populate_from_drawing_ir(test_ir)
    assert tbl_h.rowCount() == 1
    assert tbl_s.rowCount() == 2
    assert tbl_c.rowCount() == 5  # 4 canh bao tu stock

    # 2. Thao tac them dong qua Adapter
    adapter.add_hole_row(x=50.0, y=50.0, diameter=10.0, depth=5.0)
    assert tbl_h.rowCount() == 2

    adapter.add_new_slot(width=12.0, depth=6.0)
    assert tbl_s.rowCount() == 4  # 2 diem slot cu + 2 diem slot moi

    # 3. Tais sinh DrawingIR
    rebuilt_ir = adapter.build_drawing_ir(120.0, 90.0, 15.0)
    assert len(rebuilt_ir.holes) == 2
    assert len(rebuilt_ir.slots) == 2
    assert rebuilt_ir.stock_width == 120.0


def test_export_service_methods(qapp, tmp_path):
    """Kiem thu ExportService xuat DXF va G-Code doc lap khong can MainWindow."""
    from ui.services.export_service import ExportService

    logs = []
    service = ExportService(log_callback=lambda msg: logs.append(msg))

    test_ir = DrawingIR(
        stock_width=100.0,
        stock_height=100.0,
        holes=[DrillHole(center=Point2D(x=25.0, y=25.0), diameter=5.0, depth=5.0)],
    )

    # Xuat DXF
    dxf_path = str(tmp_path / "standalone_test.dxf")
    saved_dxf = service.export_dxf(test_ir, target_path=dxf_path)
    assert saved_dxf == dxf_path
    assert Path(dxf_path).exists()
    assert Path(dxf_path).stat().st_size > 0

    # Xuat G-Code
    nc_path = str(tmp_path / "standalone_test.nc")
    saved_nc, code_text = service.export_gcode(
        test_ir,
        params={"cut_depth_z": -5.0, "tool_diameter": 3.0},
        target_path=nc_path,
    )
    assert saved_nc == nc_path
    assert Path(nc_path).exists()
    assert "G54" in code_text
    assert len(logs) >= 2


def test_vlm_controller_lifecycle(qapp, tmp_path):
    """Kiem thu VLMController quan ly key, validation va luong Worker."""
    from ui.controllers.vlm_controller import VLMController

    controller = VLMController()

    # Kiem tra validation
    v_local, _ = controller.validate_api_key("local")
    assert v_local is True

    v_gemini, msg = controller.validate_api_key("gemini", key="")
    assert v_gemini is False
    assert "Gemini" in msg

    controller.set_api_key("gemini", "AIzaSy-Test-Key-999")
    v_gemini2, _ = controller.validate_api_key("gemini")
    assert v_gemini2 is True
    assert controller.get_api_key("gemini") == "AIzaSy-Test-Key-999"

    # Kiem tra chay worker qua start_analysis
    dummy_img = tmp_path / "dummy.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")

    mock_ir = DrawingIR(stock_width=80.0, stock_height=80.0)
    received = []
    controller.analysis_finished.connect(lambda ir, el: received.append(ir))

    with patch("vision.vlm_parser.parse_drawing", return_value=mock_ir):
        controller.start_analysis(dummy_img, provider="local")
        assert controller.is_running() is True
        controller.worker.wait(3000)
        qapp.processEvents()

    assert len(received) == 1
    assert received[0].stock_width == 80.0


