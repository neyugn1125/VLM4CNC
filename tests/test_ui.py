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

