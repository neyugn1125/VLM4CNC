"""
VLM4CNC - Giao diện chính (PySide6 Desktop GUI).
Bố cục 3 cột kỹ thuật chuẩn hóa tiếng Việt có dấu:
  - Cột 1: Nạp bản vẽ, xem trước và lựa chọn bộ phân tích AI.
  - Cột 2: Bảng kiểm tra tọa độ và chỉnh sửa trực tiếp (Human-in-the-Loop).
  - Cột 3: Thiết lập thông số CAM, sinh mã G-Code, xuất file DXF và nhật ký tiến trình.
Xử lý đa luồng VLM qua QThread, không sử dụng biểu tượng emoji.
"""

import os
from pathlib import Path
import sys
import time
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QGridLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.dxf_engine import export_drawing_to_dxf
from core.gcode_engine import generate_gcode
from ui.cnc_simulator import CNCToolpathSimulatorWidget
from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour
from vision.vlm_parser import parse_drawing


class VLMWorker(QThread):
    """Luồng worker xử lý phân tích VLM ngầm, không làm đóng băng giao diện."""

    progress_signal = Signal(str)
    finished_signal = Signal(object, float)  # DrawingIR, elapsed_seconds
    error_signal = Signal(str)

    def __init__(
        self,
        image_path: Path,
        provider: str = "local",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        super().__init__()
        self.image_path = image_path
        self.provider = provider
        self.model = model
        self.api_key = api_key

    def run(self):
        start_time = time.perf_counter()
        try:
            self.progress_signal.emit("Đang kết nối và phân tích bản vẽ qua bộ phân tích...")
            drawing_ir = parse_drawing(
                image_path=self.image_path,
                provider=self.provider,
                model=self.model,
                api_key=self.api_key,
            )
            elapsed = time.perf_counter() - start_time
            self.finished_signal.emit(drawing_ir, elapsed)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class ImagePreviewLabel(QLabel):
    """Khung hiển thị ảnh hỗ trợ kéo thả tập tin bản vẽ kỹ thuật."""

    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("Kéo thả ảnh bản vẽ vào đây\nhoặc bấm 'Chọn ảnh bản vẽ'")
        self.setStyleSheet(
            "border: 2px dashed #777777; border-radius: 4px; color: #444444; background-color: #fafafa; padding: 20px;"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            filepath = urls[0].toLocalFile()
            if filepath.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
                self.file_dropped.emit(filepath)


class MainWindow(QMainWindow):
    """Cửa sổ làm việc CAD/CAM trung tâm cho VLM4CNC."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VLM4CNC - Trạm gia công kỹ thuật CAD/CAM")
        self.resize(1380, 850)

        self.current_image_path: Optional[Path] = None
        self.vlm_worker: Optional[VLMWorker] = None
        self._api_keys: dict[str, str] = {
            "openai": os.getenv("OPENAI_API_KEY", ""),
            "gemini": os.getenv("GEMINI_API_KEY", ""),
        }

        self._init_ui()

    def _init_ui(self):
        """Khởi tạo bố cục giao diện 3 cột kỹ thuật."""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Bộ chia ngang cho 3 cột chức năng
        self.splitter = QSplitter(Qt.Orientation.Horizontal, central_widget)
        main_layout.addWidget(self.splitter)

        # 1. Cột 1: Bản vẽ & Nhận diện AI
        col1_widget = self._create_column_1()
        self.splitter.addWidget(col1_widget)

        # 2. Cột 2: Kiểm tra tọa độ (Human-in-the-Loop)
        col2_widget = self._create_column_2()
        self.splitter.addWidget(col2_widget)

        # 3. Cột 3: Thông số CAM & Xuất file
        col3_widget = self._create_column_3()
        self.splitter.addWidget(col3_widget)

        # Tỷ lệ bề rộng ban đầu các cột (32% - 36% - 32%)
        self.splitter.setSizes([420, 500, 460])

        # Thanh trạng thái
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Hệ thống sẵn sàng.")
        self.log_message("Hệ thống khởi động thành công. Sẵn sàng nạp bản vẽ.")

    # -------------------------------------------------------------------------
    # Cột 1: Bản vẽ kỹ thuật & Phân tích AI
    # -------------------------------------------------------------------------
    def _create_column_1(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)

        grp_input = QGroupBox("Bản vẽ kỹ thuật & Phân tích AI", container)
        grp_layout = QVBoxLayout(grp_input)

        # Nút chọn tập tin ảnh
        self.btn_select_file = QPushButton("Chọn ảnh bản vẽ", grp_input)
        self.btn_select_file.clicked.connect(self._on_select_file)
        grp_layout.addWidget(self.btn_select_file)

        # Khung xem trước ảnh hỗ trợ kéo thả
        self.scroll_preview = QScrollArea(grp_input)
        self.scroll_preview.setWidgetResizable(True)
        self.lbl_preview = ImagePreviewLabel(self.scroll_preview)
        self.lbl_preview.file_dropped.connect(self._load_image_file)
        self.scroll_preview.setWidget(self.lbl_preview)
        self.scroll_preview.setMinimumHeight(300)
        grp_layout.addWidget(self.scroll_preview)

        # Hộp chọn Engine phân tích
        lbl_engine = QLabel("Bộ phân tích AI (VLM Engine):", grp_input)
        grp_layout.addWidget(lbl_engine)
        self.combo_engine = QComboBox(grp_input)
        self.combo_engine.addItem(
            "Local Ollama: Qwen2.5-VL 7B (qwen2.5vl:7b)",
            userData={"provider": "local", "model": "qwen2.5vl:7b"},
        )
        self.combo_engine.addItem(
            "Google Gemini: 3.8 Flash (Khuyến nghị)",
            userData={"provider": "gemini", "model": "gemini-3.8-flash"},
        )
        self.combo_engine.addItem(
            "OpenAI: GPT-5.5 Pro",
            userData={"provider": "openai", "model": "gpt-5.5-pro"},
        )
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        grp_layout.addWidget(self.combo_engine)

        # Cụm nhập khóa API
        self.lbl_api_key = QLabel("Khóa API (API Key):", grp_input)
        grp_layout.addWidget(self.lbl_api_key)

        key_layout = QHBoxLayout()
        self.txt_api_key = QLineEdit(grp_input)
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_api_key.textChanged.connect(self._on_api_key_text_changed)
        key_layout.addWidget(self.txt_api_key)

        self.btn_toggle_key = QPushButton("Hiện", grp_input)
        self.btn_toggle_key.setFixedWidth(60)
        self.btn_toggle_key.clicked.connect(self._toggle_api_key_visibility)
        key_layout.addWidget(self.btn_toggle_key)
        grp_layout.addLayout(key_layout)

        # Thiết lập cấu hình ban đầu cho trường API Key theo engine mặc định
        self._on_engine_changed(0)

        # Nút kích hoạt phân tích
        self.btn_analyze = QPushButton("Bắt đầu phân tích AI", grp_input)
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self._on_start_vlm_analysis)
        grp_layout.addWidget(self.btn_analyze)

        # Thanh tiến trình
        self.progress_bar = QProgressBar(grp_input)
        self.progress_bar.setVisible(False)
        grp_layout.addWidget(self.progress_bar)

        layout.addWidget(grp_input)
        return container

    # -------------------------------------------------------------------------
    # Cột 2: Bảng kiểm tra tọa độ (Human-in-the-Loop)
    # -------------------------------------------------------------------------
    def _create_column_2(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)

        grp_review = QGroupBox("Kiểm tra tọa độ (Human-in-the-Loop)", container)
        review_layout = QVBoxLayout(grp_review)

        # Khung kích thước phôi
        grp_stock = QGroupBox("Kích thước phôi tiêu chuẩn (mm)", grp_review)
        stock_layout = QHBoxLayout(grp_stock)

        self.spin_stock_w = QDoubleSpinBox(grp_stock)
        self.spin_stock_w.setRange(10.0, 5000.0)
        self.spin_stock_w.setValue(100.0)
        self.spin_stock_w.setPrefix("Rộng W: ")
        self.spin_stock_w.valueChanged.connect(self._on_stock_dim_changed)
        stock_layout.addWidget(self.spin_stock_w)

        self.spin_stock_h = QDoubleSpinBox(grp_stock)
        self.spin_stock_h.setRange(10.0, 5000.0)
        self.spin_stock_h.setValue(100.0)
        self.spin_stock_h.setPrefix("Cao H: ")
        self.spin_stock_h.valueChanged.connect(self._on_stock_dim_changed)
        stock_layout.addWidget(self.spin_stock_h)

        self.spin_stock_t = QDoubleSpinBox(grp_stock)
        self.spin_stock_t.setRange(1.0, 500.0)
        self.spin_stock_t.setValue(10.0)
        self.spin_stock_t.setPrefix("Dày T: ")
        stock_layout.addWidget(self.spin_stock_t)

        review_layout.addWidget(grp_stock)

        # Checkbox tùy chọn phay biên dạng các cạnh bao ngoài
        self.chk_mill_contour = QCheckBox("Phay biên dạng 4 cạnh bao ngoài chi tiết", grp_review)
        self.chk_mill_contour.setChecked(True)
        review_layout.addWidget(self.chk_mill_contour)

        # Tab các tính năng gia công: Lỗ khoan, Cạnh biên dạng, Rãnh phay
        self.tabs_features = QTabWidget(grp_review)

        # Tab 0: Lỗ khoan
        tab_holes_widget = QWidget(self.tabs_features)
        tab_holes_layout = QVBoxLayout(tab_holes_widget)
        tab_holes_layout.setContentsMargins(4, 4, 4, 4)

        self.table_holes = QTableWidget(0, 5, tab_holes_widget)
        self.table_holes.setHorizontalHeaderLabels(
            ["STT", "Tọa độ X (mm)", "Tọa độ Y (mm)", "Đường kính Ø (mm)", "Chiều sâu (mm)"]
        )
        self.table_holes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab_holes_layout.addWidget(self.table_holes)

        btn_hole_layout = QHBoxLayout()
        self.btn_add_hole = QPushButton("Thêm lỗ khoan", tab_holes_widget)
        self.btn_add_hole.clicked.connect(self._add_hole_row)
        self.btn_del_hole = QPushButton("Xóa lỗ đã chọn", tab_holes_widget)
        self.btn_del_hole.clicked.connect(self._delete_selected_hole)
        btn_hole_layout.addWidget(self.btn_add_hole)
        btn_hole_layout.addWidget(self.btn_del_hole)
        tab_holes_layout.addLayout(btn_hole_layout)

        self.tabs_features.addTab(tab_holes_widget, "Lỗ khoan (Holes)")

        # Tab 1: Cạnh biên dạng bao ngoài chi tiết
        tab_contour_widget = QWidget(self.tabs_features)
        tab_contour_layout = QVBoxLayout(tab_contour_widget)
        tab_contour_layout.setContentsMargins(4, 4, 4, 4)

        self.table_contour = QTableWidget(0, 3, tab_contour_widget)
        self.table_contour.setHorizontalHeaderLabels(["Đỉnh", "Tọa độ X (mm)", "Tọa độ Y (mm)"])
        self.table_contour.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab_contour_layout.addWidget(self.table_contour)

        btn_contour_layout = QHBoxLayout()
        self.btn_reset_contour = QPushButton("Tạo 4 cạnh từ phôi", tab_contour_widget)
        self.btn_reset_contour.clicked.connect(self._reset_contour_from_stock)
        self.btn_add_contour = QPushButton("Thêm đỉnh", tab_contour_widget)
        self.btn_add_contour.clicked.connect(self._add_contour_row)
        self.btn_del_contour = QPushButton("Xóa đỉnh đã chọn", tab_contour_widget)
        self.btn_del_contour.clicked.connect(self._delete_selected_contour)
        btn_contour_layout.addWidget(self.btn_reset_contour)
        btn_contour_layout.addWidget(self.btn_add_contour)
        btn_contour_layout.addWidget(self.btn_del_contour)
        tab_contour_layout.addLayout(btn_contour_layout)

        self.tabs_features.addTab(tab_contour_widget, "Cạnh bao (Outer Edges)")

        # Tab 2: Rãnh phay
        tab_slots_widget = QWidget(self.tabs_features)
        tab_slots_layout = QVBoxLayout(tab_slots_widget)
        tab_slots_layout.setContentsMargins(4, 4, 4, 4)

        self.table_slots = QTableWidget(0, 5, tab_slots_widget)
        self.table_slots.setHorizontalHeaderLabels(
            ["STT", "Tọa độ X (mm)", "Tọa độ Y (mm)", "Bề rộng rãnh (mm)", "Chiều sâu (mm)"]
        )
        self.table_slots.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab_slots_layout.addWidget(self.table_slots)

        btn_slot_layout = QHBoxLayout()
        self.btn_add_slot = QPushButton("Thêm điểm rãnh", tab_slots_widget)
        self.btn_add_slot.clicked.connect(self._add_slot_row)
        self.btn_del_slot = QPushButton("Xóa điểm đã chọn", tab_slots_widget)
        self.btn_del_slot.clicked.connect(self._delete_selected_slot)
        btn_slot_layout.addWidget(self.btn_add_slot)
        btn_slot_layout.addWidget(self.btn_del_slot)
        tab_slots_layout.addLayout(btn_slot_layout)

        self.tabs_features.addTab(tab_slots_widget, "Rãnh phay (Slots)")

        review_layout.addWidget(self.tabs_features)
        self._reset_contour_from_stock()

        layout.addWidget(grp_review)
        return container

    # -------------------------------------------------------------------------
    # Cột 3: Thông số CAM & Mô phỏng đường chạy dao CNC
    # -------------------------------------------------------------------------
    def _create_column_3(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)

        grp_cam = QGroupBox("Thông số CAM & Dụng cụ cắt", container)
        cam_layout = QVBoxLayout(grp_cam)
        cam_layout.setContentsMargins(8, 8, 8, 8)

        grid_cam = QGridLayout()
        grid_cam.setHorizontalSpacing(8)
        grid_cam.setVerticalSpacing(4)

        # Hàng 0: Cut depth Z (mm) & Tool diameter Ø (mm)
        lbl_cut_z = QLabel("Cut depth Z:", grp_cam)
        grid_cam.addWidget(lbl_cut_z, 0, 0)
        self.spin_cut_depth_z = QDoubleSpinBox(grp_cam)
        self.spin_cut_depth_z.setDecimals(3)
        self.spin_cut_depth_z.setRange(-500.0, 100.0)
        self.spin_cut_depth_z.setValue(-5.000)
        self.spin_cut_depth_z.setSuffix(" mm")
        grid_cam.addWidget(self.spin_cut_depth_z, 0, 1)

        lbl_tool_dia = QLabel("Tool dia Ø:", grp_cam)
        grid_cam.addWidget(lbl_tool_dia, 0, 2)
        self.spin_tool_dia = QDoubleSpinBox(grp_cam)
        self.spin_tool_dia.setDecimals(3)
        self.spin_tool_dia.setRange(0.1, 100.0)
        self.spin_tool_dia.setValue(3.000)
        self.spin_tool_dia.setSuffix(" mm")
        grid_cam.addWidget(self.spin_tool_dia, 0, 3)

        # Hàng 1: Cut feed (mm/min) & Plunge feed (mm/min)
        lbl_cut_feed = QLabel("Cut feed:", grp_cam)
        grid_cam.addWidget(lbl_cut_feed, 1, 0)
        self.spin_feed_cut = QDoubleSpinBox(grp_cam)
        self.spin_feed_cut.setDecimals(1)
        self.spin_feed_cut.setRange(1.0, 30000.0)
        self.spin_feed_cut.setValue(300.0)
        self.spin_feed_cut.setSuffix(" mm/min")
        self.spin_feed_xy = self.spin_feed_cut  # Bí danh tương thích
        grid_cam.addWidget(self.spin_feed_cut, 1, 1)

        lbl_plunge_feed = QLabel("Plunge feed:", grp_cam)
        grid_cam.addWidget(lbl_plunge_feed, 1, 2)
        self.spin_feed_plunge = QDoubleSpinBox(grp_cam)
        self.spin_feed_plunge.setDecimals(1)
        self.spin_feed_plunge.setRange(1.0, 15000.0)
        self.spin_feed_plunge.setValue(100.0)
        self.spin_feed_plunge.setSuffix(" mm/min")
        grid_cam.addWidget(self.spin_feed_plunge, 1, 3)

        # Hàng 2: Spindle RPM & Safe Z (mm)
        lbl_spindle = QLabel("Spindle RPM:", grp_cam)
        grid_cam.addWidget(lbl_spindle, 2, 0)
        self.spin_spindle_rpm = QSpinBox(grp_cam)
        self.spin_spindle_rpm.setRange(100, 60000)
        self.spin_spindle_rpm.setValue(1500)
        self.spin_spindle_rpm.setSuffix(" rpm")
        self.spin_spindle_speed = self.spin_spindle_rpm  # Bí danh tương thích
        grid_cam.addWidget(self.spin_spindle_rpm, 2, 1)

        lbl_safe_z = QLabel("Safe Z:", grp_cam)
        grid_cam.addWidget(lbl_safe_z, 2, 2)
        self.spin_safe_z = QDoubleSpinBox(grp_cam)
        self.spin_safe_z.setDecimals(3)
        self.spin_safe_z.setRange(0.0, 500.0)
        self.spin_safe_z.setValue(50.000)
        self.spin_safe_z.setSuffix(" mm")
        grid_cam.addWidget(self.spin_safe_z, 2, 3)

        # Hàng 3: Approach Z (mm) & Cắt mỗi lớp (mm)
        lbl_approach_z = QLabel("Approach Z:", grp_cam)
        grid_cam.addWidget(lbl_approach_z, 3, 0)
        self.spin_approach_z = QDoubleSpinBox(grp_cam)
        self.spin_approach_z.setDecimals(3)
        self.spin_approach_z.setRange(0.0, 200.0)
        self.spin_approach_z.setValue(2.000)
        self.spin_approach_z.setSuffix(" mm")
        grid_cam.addWidget(self.spin_approach_z, 3, 1)

        lbl_pass_depth = QLabel("Cắt mỗi lớp:", grp_cam)
        grid_cam.addWidget(lbl_pass_depth, 3, 2)
        self.spin_cut_depth_pass = QDoubleSpinBox(grp_cam)
        self.spin_cut_depth_pass.setDecimals(3)
        self.spin_cut_depth_pass.setRange(0.05, 50.0)
        self.spin_cut_depth_pass.setValue(1.000)
        self.spin_cut_depth_pass.setSuffix(" mm")
        grid_cam.addWidget(self.spin_cut_depth_pass, 3, 3)

        # Hàng 4: Tool number (T) & Tool offset (H)
        lbl_tool_num = QLabel("Tool No (T):", grp_cam)
        grid_cam.addWidget(lbl_tool_num, 4, 0)
        self.spin_tool_number = QSpinBox(grp_cam)
        self.spin_tool_number.setRange(1, 99)
        self.spin_tool_number.setValue(1)
        grid_cam.addWidget(self.spin_tool_number, 4, 1)

        lbl_tool_off = QLabel("Offset (H):", grp_cam)
        grid_cam.addWidget(lbl_tool_off, 4, 2)
        self.spin_tool_offset = QSpinBox(grp_cam)
        self.spin_tool_offset.setRange(1, 99)
        self.spin_tool_offset.setValue(1)
        grid_cam.addWidget(self.spin_tool_offset, 4, 3)

        # Hàng 5: Program number (O)
        lbl_prog_num = QLabel("Prog No (O):", grp_cam)
        grid_cam.addWidget(lbl_prog_num, 5, 0)
        self.spin_prog_number = QSpinBox(grp_cam)
        self.spin_prog_number.setRange(1, 9999)
        self.spin_prog_number.setValue(1000)
        grid_cam.addWidget(self.spin_prog_number, 5, 1)

        cam_layout.addLayout(grid_cam)

        # Các nút xuất file
        btn_action_layout = QHBoxLayout()
        self.btn_export_dxf = QPushButton("Xuất bản vẽ DXF", grp_cam)
        self.btn_export_dxf.clicked.connect(self._on_export_dxf)
        btn_action_layout.addWidget(self.btn_export_dxf)

        self.btn_generate_gcode = QPushButton("Sinh mã G-Code", grp_cam)
        self.btn_generate_gcode.clicked.connect(self._on_generate_gcode)
        btn_action_layout.addWidget(self.btn_generate_gcode)
        cam_layout.addLayout(btn_action_layout)

        layout.addWidget(grp_cam)

        # Các tab kết quả & Mô phỏng đường chạy dao
        self.tabs_output = QTabWidget(container)

        # Tab 0: Mô phỏng đường chạy dao CNC đồ họa tương tác
        self.simulator_widget = CNCToolpathSimulatorWidget(self.tabs_output)
        self.tabs_output.addTab(self.simulator_widget, "Mô phỏng đường chạy dao")

        # Tab 1: Xem trước mã chương trình G-Code
        self.txt_gcode = QPlainTextEdit(self.tabs_output)
        self.txt_gcode.setReadOnly(True)
        self.txt_gcode.setFont(QFont("Monospace", 9))
        self.tabs_output.addTab(self.txt_gcode, "Xem trước G-Code")

        # Tab 2: Nhật ký tiến trình
        self.txt_log = QPlainTextEdit(self.tabs_output)
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Monospace", 9))
        self.tabs_output.addTab(self.txt_log, "Nhật ký tiến trình")

        layout.addWidget(self.tabs_output)
        return container

    # -------------------------------------------------------------------------
    # Ghi log và phản hồi trạng thái
    # -------------------------------------------------------------------------
    def log_message(self, message: str):
        """Thêm bản ghi nhật ký có đóng dấu thời gian."""
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        self.txt_log.appendPlainText(formatted)

    # -------------------------------------------------------------------------
    # Thao tác nạp và xem trước ảnh
    # -------------------------------------------------------------------------
    def _on_select_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file ảnh bản vẽ kỹ thuật",
            "",
            "Ảnh bản vẽ (*.png *.jpg *.jpeg *.bmp *.webp);;Tất cả tập tin (*)",
        )
        if filepath:
            self._load_image_file(filepath)

    def _load_image_file(self, filepath: str):
        self.current_image_path = Path(filepath)
        pixmap = QPixmap(str(self.current_image_path))
        if not pixmap.isNull():
            self.lbl_preview.setPixmap(
                pixmap.scaled(
                    self.scroll_preview.viewport().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.btn_analyze.setEnabled(True)
            self.log_message(f"Đã nạp ảnh bản vẽ: {self.current_image_path.name}")
            self.statusBar().showMessage(f"Tập tin: {self.current_image_path.name}")
        else:
            QMessageBox.warning(self, "Lỗi", "Không thể tải định dạng tập tin ảnh đã chọn.")

    def _on_engine_changed(self, index: int):
        data = self.combo_engine.itemData(index)
        if not data:
            return
        provider = data.get("provider", "local")

        self.txt_api_key.blockSignals(True)
        if provider == "local":
            self.txt_api_key.setEnabled(False)
            self.btn_toggle_key.setEnabled(False)
            self.txt_api_key.setText("")
            self.txt_api_key.setPlaceholderText("Local Ollama chạy trên máy cục bộ, không cần khóa API")
        elif provider == "openai":
            self.txt_api_key.setEnabled(True)
            self.btn_toggle_key.setEnabled(True)
            self.txt_api_key.setPlaceholderText("Nhập OpenAI API Key (sk-...)")
            self.txt_api_key.setText(self._api_keys.get("openai", ""))
        elif provider == "gemini":
            self.txt_api_key.setEnabled(True)
            self.btn_toggle_key.setEnabled(True)
            self.txt_api_key.setPlaceholderText("Nhập Google Gemini API Key (AIzaSy...)")
            self.txt_api_key.setText(self._api_keys.get("gemini", ""))
        self.txt_api_key.blockSignals(False)

    def _on_api_key_text_changed(self, text: str):
        data = self.combo_engine.currentData()
        if not data:
            return
        provider = data.get("provider")
        if provider in ("openai", "gemini"):
            self._api_keys[provider] = text.strip()

    def _toggle_api_key_visibility(self):
        if self.txt_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_key.setText("Ẩn")
        else:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_key.setText("Hiện")

    # -------------------------------------------------------------------------
    # Xử lý phân tích VLM đa luồng
    # -------------------------------------------------------------------------
    def _on_start_vlm_analysis(self):
        if not self.current_image_path or not self.current_image_path.is_file():
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tập tin ảnh bản vẽ hợp lệ trước.")
            return

        selected_data = self.combo_engine.currentData()
        provider = selected_data["provider"]
        model = selected_data["model"]

        # Kiểm tra khóa API với các dịch vụ đám mây
        api_key = None
        if provider in ("openai", "gemini"):
            api_key = self.txt_api_key.text().strip()
            if not api_key:
                provider_title = "OpenAI" if provider == "openai" else "Google Gemini"
                QMessageBox.warning(
                    self,
                    "Thiếu khóa API",
                    f"Vui lòng nhập khóa API cho {provider_title} trước khi bắt đầu phân tích.",
                )
                self.txt_api_key.setFocus()
                return

        self.btn_analyze.setEnabled(False)
        self.btn_select_file.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Chế độ xoay vòng không giới hạn

        self.log_message(f"Bắt đầu phân tích qua Engine: {self.combo_engine.currentText()}")
        self.statusBar().showMessage("Đang phân tích bản vẽ bằng AI...")

        self.vlm_worker = VLMWorker(
            image_path=self.current_image_path,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        self.vlm_worker.progress_signal.connect(self.log_message)
        self.vlm_worker.finished_signal.connect(self._on_vlm_analysis_finished)
        self.vlm_worker.error_signal.connect(self._on_vlm_analysis_error)
        self.vlm_worker.start()

    @Slot(object, float)
    def _on_vlm_analysis_finished(self, drawing_ir: DrawingIR, elapsed: float):
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.btn_select_file.setEnabled(True)

        self.log_message(f"Phân tích AI hoàn tất trong {elapsed:.2f} giây.")
        if drawing_ir.reasoning:
            self.log_message(f"--- Chuỗi suy luận hình học của AI (Reasoning) ---\n{drawing_ir.reasoning}")
        self.statusBar().showMessage(f"Phân tích hoàn tất ({elapsed:.2f}s). Sẵn sàng hiệu chỉnh tọa độ.")

        # Điền dữ liệu bóc tách được vào bảng
        self._populate_tables_from_drawing_ir(drawing_ir)

    @Slot(str)
    def _on_vlm_analysis_error(self, error_message: str):
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.btn_select_file.setEnabled(True)

        self.log_message(f"Lỗi phân tích VLM: {error_message}")
        self.statusBar().showMessage("Quá trình phân tích gặp lỗi.")
        QMessageBox.critical(self, "Lỗi phân tích AI", f"Không thể trích xuất bản vẽ:\n{error_message}")

    # -------------------------------------------------------------------------
    # Thao tác bảng tọa độ (Human-in-the-Loop)
    # -------------------------------------------------------------------------
    def _populate_tables_from_drawing_ir(self, drawing_ir: DrawingIR):
        """Điền thông số phôi và các bảng dữ liệu từ đối tượng DrawingIR."""
        self.spin_stock_w.setValue(drawing_ir.stock_width)
        self.spin_stock_h.setValue(drawing_ir.stock_height)
        self.spin_stock_t.setValue(drawing_ir.stock_thickness)

        # Điền bảng lỗ khoan
        self.table_holes.setRowCount(0)
        for idx, hole in enumerate(drawing_ir.holes, start=1):
            row = self.table_holes.rowCount()
            self.table_holes.insertRow(row)
            self.table_holes.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table_holes.setItem(row, 1, QTableWidgetItem(f"{hole.center.x:.3f}"))
            self.table_holes.setItem(row, 2, QTableWidgetItem(f"{hole.center.y:.3f}"))
            self.table_holes.setItem(row, 3, QTableWidgetItem(f"{hole.diameter:.3f}"))
            self.table_holes.setItem(row, 4, QTableWidgetItem(f"{hole.depth:.3f}"))

        # Điền bảng rãnh phay
        self.table_slots.setRowCount(0)
        point_idx = 1
        for slot in drawing_ir.slots:
            for pt in slot.centerline_path:
                row = self.table_slots.rowCount()
                self.table_slots.insertRow(row)
                self.table_slots.setItem(row, 0, QTableWidgetItem(str(point_idx)))
                self.table_slots.setItem(row, 1, QTableWidgetItem(f"{pt.x:.3f}"))
                self.table_slots.setItem(row, 2, QTableWidgetItem(f"{pt.y:.3f}"))
                self.table_slots.setItem(row, 3, QTableWidgetItem(f"{slot.width:.3f}"))
                self.table_slots.setItem(row, 4, QTableWidgetItem(f"{slot.depth:.3f}"))
                point_idx += 1

        # Điền bảng cạnh biên dạng bao ngoài chi tiết
        contour_pts = drawing_ir.get_effective_outer_contour()
        self.table_contour.setRowCount(0)
        for idx, pt in enumerate(contour_pts, start=1):
            row = self.table_contour.rowCount()
            self.table_contour.insertRow(row)
            self.table_contour.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table_contour.setItem(row, 1, QTableWidgetItem(f"{pt.x:.3f}"))
            self.table_contour.setItem(row, 2, QTableWidgetItem(f"{pt.y:.3f}"))

        self.log_message(
            f"Đã đồng bộ vào bảng: {len(drawing_ir.holes)} lỗ khoan, "
            f"{len(contour_pts)} đỉnh cạnh bao ngoài và {point_idx - 1} điểm tim rãnh."
        )

    def _on_stock_dim_changed(self):
        """Tự động cập nhật 4 cạnh bao ngoài chi tiết khi thay đổi kích thước phôi."""
        self._reset_contour_from_stock()

    def _reset_contour_from_stock(self):
        """Khởi tạo lại 4 cạnh bao ngoài chi tiết khép kín theo kích thước phôi hiện thời."""
        w = self.spin_stock_w.value()
        h = self.spin_stock_h.value()
        pts = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
        self.table_contour.setRowCount(0)
        for idx, (x, y) in enumerate(pts, start=1):
            row = self.table_contour.rowCount()
            self.table_contour.insertRow(row)
            self.table_contour.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table_contour.setItem(row, 1, QTableWidgetItem(f"{x:.3f}"))
            self.table_contour.setItem(row, 2, QTableWidgetItem(f"{y:.3f}"))

    def _add_contour_row(self):
        row = self.table_contour.rowCount()
        self.table_contour.insertRow(row)
        self.table_contour.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_contour.setItem(row, 1, QTableWidgetItem("0.000"))
        self.table_contour.setItem(row, 2, QTableWidgetItem("0.000"))

    def _delete_selected_contour(self):
        curr_row = self.table_contour.currentRow()
        if curr_row >= 0:
            self.table_contour.removeRow(curr_row)

    def _add_hole_row(self):
        row = self.table_holes.rowCount()
        self.table_holes.insertRow(row)
        self.table_holes.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_holes.setItem(row, 1, QTableWidgetItem("0.000"))
        self.table_holes.setItem(row, 2, QTableWidgetItem("0.000"))
        self.table_holes.setItem(row, 3, QTableWidgetItem("10.000"))
        self.table_holes.setItem(row, 4, QTableWidgetItem("10.000"))

    def _delete_selected_hole(self):
        curr_row = self.table_holes.currentRow()
        if curr_row >= 0:
            self.table_holes.removeRow(curr_row)

    def _add_slot_row(self):
        row = self.table_slots.rowCount()
        self.table_slots.insertRow(row)
        self.table_slots.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_slots.setItem(row, 1, QTableWidgetItem("0.000"))
        self.table_slots.setItem(row, 2, QTableWidgetItem("0.000"))
        self.table_slots.setItem(row, 3, QTableWidgetItem("8.000"))
        self.table_slots.setItem(row, 4, QTableWidgetItem("5.000"))

    def _delete_selected_slot(self):
        curr_row = self.table_slots.currentRow()
        if curr_row >= 0:
            self.table_slots.removeRow(curr_row)

    def build_drawing_ir_from_tables(self) -> DrawingIR:
        """Đọc và tái cấu trúc đối tượng DrawingIR từ toàn bộ dữ liệu bảng hiện thời."""
        holes: List[DrillHole] = []
        for row in range(self.table_holes.rowCount()):
            try:
                x = float(self.table_holes.item(row, 1).text())
                y = float(self.table_holes.item(row, 2).text())
                dia = float(self.table_holes.item(row, 3).text())
                dep = float(self.table_holes.item(row, 4).text())
                holes.append(DrillHole(center=Point2D(x=x, y=y), diameter=dia, depth=dep))
            except Exception as e:
                self.log_message(f"Bỏ qua dòng lỗ {row + 1} do sai định dạng số: {e}")

        slots: List[SlotContour] = []
        slot_pts: List[Point2D] = []
        slot_w = 8.0
        slot_d = 5.0
        for row in range(self.table_slots.rowCount()):
            try:
                x = float(self.table_slots.item(row, 1).text())
                y = float(self.table_slots.item(row, 2).text())
                slot_w = float(self.table_slots.item(row, 3).text())
                slot_d = float(self.table_slots.item(row, 4).text())
                slot_pts.append(Point2D(x=x, y=y))
            except Exception as e:
                self.log_message(f"Bỏ qua dòng rãnh {row + 1} do sai định dạng số: {e}")

        if len(slot_pts) >= 2:
            slots.append(SlotContour(width=slot_w, depth=slot_d, centerline_path=slot_pts))

        contour_pts: List[Point2D] = []
        for row in range(self.table_contour.rowCount()):
            try:
                x = float(self.table_contour.item(row, 1).text())
                y = float(self.table_contour.item(row, 2).text())
                contour_pts.append(Point2D(x=x, y=y))
            except Exception as e:
                self.log_message(f"Bỏ qua dòng đỉnh cạnh {row + 1} do sai định dạng số: {e}")

        return DrawingIR(
            stock_width=self.spin_stock_w.value(),
            stock_height=self.spin_stock_h.value(),
            stock_thickness=self.spin_stock_t.value(),
            holes=holes,
            slots=slots,
            outer_contour=contour_pts if len(contour_pts) >= 3 else None,
        )

    # -------------------------------------------------------------------------
    # Xuất file CAD DXF và chương trình CNC G-Code
    # -------------------------------------------------------------------------
    def _on_export_dxf(self):
        drawing_ir = self.build_drawing_ir_from_tables()
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu bản vẽ AutoCAD DXF",
            str(Path("outputs") / "drawing_output.dxf"),
            "DXF Files (*.dxf)",
        )
        if filepath:
            try:
                saved = export_drawing_to_dxf(drawing_ir, filepath)
                self.log_message(f"Xuất file DXF thành công: {saved}")
                self.statusBar().showMessage(f"DXF lưu tại: {Path(saved).name}")
                QMessageBox.information(self, "Thành công", f"Đã xuất bản vẽ DXF:\n{saved}")
            except Exception as e:
                self.log_message(f"Lỗi xuất DXF: {e}")
                QMessageBox.critical(self, "Lỗi", f"Không thể xuất DXF: {e}")

    def _on_generate_gcode(self):
        drawing_ir = self.build_drawing_ir_from_tables()
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu chương trình CNC G-Code",
            str(Path("outputs") / "program_output.nc"),
            "G-Code Files (*.nc *.gcode *.tap)",
        )
        if filepath:
            params = {
                "cut_depth_z": self.spin_cut_depth_z.value(),
                "plunge_feed": self.spin_feed_plunge.value(),
                "cut_feed": self.spin_feed_cut.value(),
                "feedrate_xy": self.spin_feed_cut.value(),
                "spindle_rpm": self.spin_spindle_rpm.value(),
                "spindle_speed": self.spin_spindle_rpm.value(),
                "safe_z": self.spin_safe_z.value(),
                "approach_z": self.spin_approach_z.value(),
                "tool_diameter": self.spin_tool_dia.value(),
                "tool_number": self.spin_tool_number.value(),
                "tool_offset": self.spin_tool_offset.value(),
                "program_number": self.spin_prog_number.value(),
                "cut_depth_per_pass": self.spin_cut_depth_pass.value(),
                "drilling_cycle": "G83",
                "mill_outer_contour": self.chk_mill_contour.isChecked(),
            }
            try:
                gcode_text = generate_gcode(drawing_ir, params, filepath)
                self.txt_gcode.setPlainText(gcode_text)

                # Nạp chương trình vào bộ mô phỏng đường chạy dao CNC
                stock_w = drawing_ir.stock_width
                stock_h = drawing_ir.stock_height
                tool_dia = self.spin_tool_dia.value()
                self.simulator_widget.load_gcode(gcode_text, stock_w, stock_h, tool_dia)
                self.tabs_output.setCurrentIndex(0)

                self.log_message(f"Sinh mã G-Code thành công ({len(gcode_text.splitlines())} dòng): {filepath}")
                self.statusBar().showMessage(f"G-Code lưu tại: {Path(filepath).name}")
                QMessageBox.information(self, "Thành công", f"Đã sinh chương trình G-Code:\n{filepath}")
            except Exception as e:
                self.log_message(f"Lỗi sinh G-Code: {e}")
                QMessageBox.critical(self, "Lỗi", f"Không thể sinh G-Code: {e}")
