"""
VLM4CNC - Giao diện chính (PySide6 Desktop GUI).
Kiến trúc MVP (Model-View-Presenter) tinh gọn:
  - View Shell: Thiết lập bố cục 3 cột kỹ thuật (MainWindow).
  - Model Adapter: Quản lý và chuyển đổi dữ liệu thực thể 2 chiều (TableDataAdapter).
  - Controller: Quản lý luồng xử lý và xác thực VLM (VLMController).
  - Service: Quản lý xuất file DXF và G-Code ra đĩa cứng (ExportService).
"""

from pathlib import Path
import time
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
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
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from core.dxf_engine import export_drawing_to_dxf
from core.gcode_engine import generate_gcode
from ui.cnc_simulator import CNCToolpathSimulatorWidget
from ui.controllers.vlm_controller import VLMController, VLMWorker
from ui.models.drawing_table_model import TableDataAdapter
from ui.services.export_service import ExportService
from vision.schemas import DrawingIR
from vision.vlm_parser import parse_drawing


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
    """Cửa sổ làm việc CAD/CAM trung tâm cho VLM4CNC (View Shell)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VLM4CNC - Trạm gia công kỹ thuật CAD/CAM")
        self.resize(1380, 850)

        self.current_image_path: Optional[Path] = None

        # 1. Khởi tạo Controller điều phối VLM
        self.vlm_controller = VLMController(parent=self)
        self.vlm_controller.analysis_started.connect(self._on_vlm_started)
        self.vlm_controller.progress_message.connect(self.log_message)
        self.vlm_controller.analysis_finished.connect(self._on_vlm_finished)
        self.vlm_controller.analysis_error.connect(self._on_vlm_error)

        # 2. Khởi tạo Service xuất file
        self.export_service = ExportService(
            parent=self,
            log_callback=self.log_message,
            status_callback=lambda msg: self.statusBar().showMessage(msg),
        )

        # 3. Khởi tạo giao diện đồ họa
        self._init_ui()

        # 4. Khởi tạo Model Adapter sau khi các table widget đã được tạo
        self.data_adapter = TableDataAdapter(
            table_holes=self.table_holes,
            table_slots=self.table_slots,
            table_contour=self.table_contour,
            log_callback=self.log_message,
        )
        self.data_adapter.reset_contour_from_stock(
            self.spin_stock_w.value(), self.spin_stock_h.value()
        )

    @property
    def _api_keys(self):
        """Bí danh tương thích ngược cho controller api keys."""
        return self.vlm_controller._api_keys

    @property
    def vlm_worker(self):
        """Bí danh tương thích ngược cho controller worker thread."""
        return self.vlm_controller.worker

    def _init_ui(self):
        """Khởi tạo bố cục giao diện 3 cột kỹ thuật."""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, central_widget)
        self.splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self.splitter)

        # 3 cột chức năng
        self.splitter.addWidget(self._create_column_1())
        self.splitter.addWidget(self._create_column_2())
        self.splitter.addWidget(self._create_column_3())
        self.splitter.setSizes([420, 500, 460])

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

        self.btn_select_file = QPushButton("Chọn ảnh bản vẽ", grp_input)
        self.btn_select_file.clicked.connect(self._on_select_file)
        grp_layout.addWidget(self.btn_select_file)

        self.scroll_preview = QScrollArea(grp_input)
        self.scroll_preview.setWidgetResizable(True)
        self.lbl_preview = ImagePreviewLabel(self.scroll_preview)
        self.lbl_preview.file_dropped.connect(self._load_image_file)
        self.scroll_preview.setWidget(self.lbl_preview)
        self.scroll_preview.setMinimumHeight(300)
        grp_layout.addWidget(self.scroll_preview)

        grp_layout.addWidget(QLabel("Bộ phân tích AI (VLM Engine):", grp_input))
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

        self._on_engine_changed(0)

        self.btn_analyze = QPushButton("Bắt đầu phân tích AI", grp_input)
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self._on_start_vlm_analysis)
        grp_layout.addWidget(self.btn_analyze)

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

        self.chk_mill_contour = QCheckBox("Phay biên dạng 4 cạnh bao ngoài chi tiết", grp_review)
        self.chk_mill_contour.setChecked(True)
        review_layout.addWidget(self.chk_mill_contour)

        self.chk_mill_holes = QCheckBox("Khoét / Phay mở rộng hốc tròn cho lỗ lớn hơn dao (G03)", grp_review)
        self.chk_mill_holes.setChecked(True)
        review_layout.addWidget(self.chk_mill_holes)

        self.chk_mill_slots = QCheckBox("Phay mở rộng rãnh theo bề rộng danh nghĩa (G02/Racetrack)", grp_review)
        self.chk_mill_slots.setChecked(True)
        review_layout.addWidget(self.chk_mill_slots)

        self.tabs_features = QTabWidget(grp_review)

        # Tab 0: Lỗ khoan
        tab_holes_w = QWidget(self.tabs_features)
        tab_holes_l = QVBoxLayout(tab_holes_w)
        tab_holes_l.setContentsMargins(4, 4, 4, 4)
        self.table_holes = QTableWidget(0, 5, tab_holes_w)
        self.table_holes.setHorizontalHeaderLabels(
            ["STT", "Tọa độ X (mm)", "Tọa độ Y (mm)", "Đường kính Ø (mm)", "Chiều sâu (mm)"]
        )
        self.table_holes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab_holes_l.addWidget(self.table_holes)

        btn_hole_layout = QHBoxLayout()
        self.btn_add_hole = QPushButton("Thêm lỗ khoan", tab_holes_w)
        self.btn_add_hole.clicked.connect(self._add_hole_row)
        self.btn_del_hole = QPushButton("Xóa lỗ đã chọn", tab_holes_w)
        self.btn_del_hole.clicked.connect(self._delete_selected_hole)
        btn_hole_layout.addWidget(self.btn_add_hole)
        btn_hole_layout.addWidget(self.btn_del_hole)
        tab_holes_l.addLayout(btn_hole_layout)
        self.tabs_features.addTab(tab_holes_w, "Lỗ khoan (Holes)")

        # Tab 1: Cạnh bao ngoài
        tab_contour_w = QWidget(self.tabs_features)
        tab_contour_l = QVBoxLayout(tab_contour_w)
        tab_contour_l.setContentsMargins(4, 4, 4, 4)
        self.table_contour = QTableWidget(0, 3, tab_contour_w)
        self.table_contour.setHorizontalHeaderLabels(["Đỉnh", "Tọa độ X (mm)", "Tọa độ Y (mm)"])
        self.table_contour.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab_contour_l.addWidget(self.table_contour)

        btn_contour_layout = QHBoxLayout()
        self.btn_reset_contour = QPushButton("Tạo 4 cạnh từ phôi", tab_contour_w)
        self.btn_reset_contour.clicked.connect(self._reset_contour_from_stock)
        self.btn_add_contour = QPushButton("Thêm đỉnh", tab_contour_w)
        self.btn_add_contour.clicked.connect(self._add_contour_row)
        self.btn_del_contour = QPushButton("Xóa đỉnh đã chọn", tab_contour_w)
        self.btn_del_contour.clicked.connect(self._delete_selected_contour)
        btn_contour_layout.addWidget(self.btn_reset_contour)
        btn_contour_layout.addWidget(self.btn_add_contour)
        btn_contour_layout.addWidget(self.btn_del_contour)
        tab_contour_l.addLayout(btn_contour_layout)
        self.tabs_features.addTab(tab_contour_w, "Cạnh bao (Outer Edges)")

        # Tab 2: Rãnh phay
        tab_slots_w = QWidget(self.tabs_features)
        tab_slots_l = QVBoxLayout(tab_slots_w)
        tab_slots_l.setContentsMargins(4, 4, 4, 4)
        self.table_slots = QTableWidget(0, 5, tab_slots_w)
        self.table_slots.setHorizontalHeaderLabels(
            ["Rãnh / Điểm", "Tọa độ X (mm)", "Tọa độ Y (mm)", "Bề rộng rãnh (mm)", "Chiều sâu (mm)"]
        )
        self.table_slots.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab_slots_l.addWidget(self.table_slots)

        btn_slot_layout = QHBoxLayout()
        self.btn_add_slot = QPushButton("Thêm điểm", tab_slots_w)
        self.btn_add_slot.clicked.connect(self._add_slot_row)
        self.btn_new_slot = QPushButton("Thêm rãnh mới", tab_slots_w)
        self.btn_new_slot.clicked.connect(self._add_new_slot)
        self.btn_del_slot = QPushButton("Xóa điểm đã chọn", tab_slots_w)
        self.btn_del_slot.clicked.connect(self._delete_selected_slot)
        btn_slot_layout.addWidget(self.btn_add_slot)
        btn_slot_layout.addWidget(self.btn_new_slot)
        btn_slot_layout.addWidget(self.btn_del_slot)
        tab_slots_l.addLayout(btn_slot_layout)
        self.tabs_features.addTab(tab_slots_w, "Rãnh phay (Slots)")

        review_layout.addWidget(self.tabs_features)
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

        grid_cam.addWidget(QLabel("Cut depth Z:", grp_cam), 0, 0)
        self.spin_cut_depth_z = QDoubleSpinBox(grp_cam)
        self.spin_cut_depth_z.setDecimals(3)
        self.spin_cut_depth_z.setRange(-500.0, 100.0)
        self.spin_cut_depth_z.setValue(-5.000)
        self.spin_cut_depth_z.setSuffix(" mm")
        grid_cam.addWidget(self.spin_cut_depth_z, 0, 1)

        grid_cam.addWidget(QLabel("Tool dia Ø:", grp_cam), 0, 2)
        self.spin_tool_dia = QDoubleSpinBox(grp_cam)
        self.spin_tool_dia.setDecimals(3)
        self.spin_tool_dia.setRange(0.1, 100.0)
        self.spin_tool_dia.setValue(3.000)
        self.spin_tool_dia.setSuffix(" mm")
        grid_cam.addWidget(self.spin_tool_dia, 0, 3)

        grid_cam.addWidget(QLabel("Cut feed:", grp_cam), 1, 0)
        self.spin_feed_cut = QDoubleSpinBox(grp_cam)
        self.spin_feed_cut.setDecimals(1)
        self.spin_feed_cut.setRange(1.0, 30000.0)
        self.spin_feed_cut.setValue(300.0)
        self.spin_feed_cut.setSuffix(" mm/min")
        self.spin_feed_xy = self.spin_feed_cut
        grid_cam.addWidget(self.spin_feed_cut, 1, 1)

        grid_cam.addWidget(QLabel("Plunge feed:", grp_cam), 1, 2)
        self.spin_feed_plunge = QDoubleSpinBox(grp_cam)
        self.spin_feed_plunge.setDecimals(1)
        self.spin_feed_plunge.setRange(1.0, 15000.0)
        self.spin_feed_plunge.setValue(100.0)
        self.spin_feed_plunge.setSuffix(" mm/min")
        grid_cam.addWidget(self.spin_feed_plunge, 1, 3)

        grid_cam.addWidget(QLabel("Spindle RPM:", grp_cam), 2, 0)
        self.spin_spindle_rpm = QSpinBox(grp_cam)
        self.spin_spindle_rpm.setRange(100, 60000)
        self.spin_spindle_rpm.setValue(1500)
        self.spin_spindle_rpm.setSuffix(" rpm")
        self.spin_spindle_speed = self.spin_spindle_rpm
        grid_cam.addWidget(self.spin_spindle_rpm, 2, 1)

        grid_cam.addWidget(QLabel("Safe Z:", grp_cam), 2, 2)
        self.spin_safe_z = QDoubleSpinBox(grp_cam)
        self.spin_safe_z.setDecimals(3)
        self.spin_safe_z.setRange(0.0, 500.0)
        self.spin_safe_z.setValue(50.000)
        self.spin_safe_z.setSuffix(" mm")
        grid_cam.addWidget(self.spin_safe_z, 2, 3)

        grid_cam.addWidget(QLabel("Approach Z:", grp_cam), 3, 0)
        self.spin_approach_z = QDoubleSpinBox(grp_cam)
        self.spin_approach_z.setDecimals(3)
        self.spin_approach_z.setRange(0.0, 200.0)
        self.spin_approach_z.setValue(2.000)
        self.spin_approach_z.setSuffix(" mm")
        grid_cam.addWidget(self.spin_approach_z, 3, 1)

        grid_cam.addWidget(QLabel("Cắt mỗi lớp:", grp_cam), 3, 2)
        self.spin_cut_depth_pass = QDoubleSpinBox(grp_cam)
        self.spin_cut_depth_pass.setDecimals(3)
        self.spin_cut_depth_pass.setRange(0.05, 50.0)
        self.spin_cut_depth_pass.setValue(1.000)
        self.spin_cut_depth_pass.setSuffix(" mm")
        grid_cam.addWidget(self.spin_cut_depth_pass, 3, 3)

        grid_cam.addWidget(QLabel("Tool No (T):", grp_cam), 4, 0)
        self.spin_tool_number = QSpinBox(grp_cam)
        self.spin_tool_number.setRange(1, 99)
        self.spin_tool_number.setValue(1)
        grid_cam.addWidget(self.spin_tool_number, 4, 1)

        grid_cam.addWidget(QLabel("Offset (H):", grp_cam), 4, 2)
        self.spin_tool_offset = QSpinBox(grp_cam)
        self.spin_tool_offset.setRange(1, 99)
        self.spin_tool_offset.setValue(1)
        grid_cam.addWidget(self.spin_tool_offset, 4, 3)

        grid_cam.addWidget(QLabel("Prog No (O):", grp_cam), 5, 0)
        self.spin_prog_number = QSpinBox(grp_cam)
        self.spin_prog_number.setRange(1, 9999)
        self.spin_prog_number.setValue(1000)
        grid_cam.addWidget(self.spin_prog_number, 5, 1)

        cam_layout.addLayout(grid_cam)

        btn_action_layout = QHBoxLayout()
        self.btn_export_dxf = QPushButton("Xuất bản vẽ DXF", grp_cam)
        self.btn_export_dxf.clicked.connect(self._on_export_dxf)
        btn_action_layout.addWidget(self.btn_export_dxf)

        self.btn_generate_gcode = QPushButton("Sinh mã G-Code", grp_cam)
        self.btn_generate_gcode.clicked.connect(self._on_generate_gcode)
        btn_action_layout.addWidget(self.btn_generate_gcode)
        cam_layout.addLayout(btn_action_layout)

        layout.addWidget(grp_cam)

        self.tabs_output = QTabWidget(container)
        self.simulator_widget = CNCToolpathSimulatorWidget(self.tabs_output)
        self.tabs_output.addTab(self.simulator_widget, "Mô phỏng đường chạy dao")

        self.txt_gcode = QPlainTextEdit(self.tabs_output)
        self.txt_gcode.setReadOnly(True)
        self.txt_gcode.setFont(QFont("Monospace", 9))
        self.tabs_output.addTab(self.txt_gcode, "Xem trước G-Code")

        self.txt_log = QPlainTextEdit(self.tabs_output)
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Monospace", 9))
        self.tabs_output.addTab(self.txt_log, "Nhật ký tiến trình")

        layout.addWidget(self.tabs_output)
        return container

    def log_message(self, message: str):
        """Thêm bản ghi nhật ký có đóng dấu thời gian."""
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{timestamp}] {message}")

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
        data = self.combo_engine.itemData(index) or {}
        provider = data.get("provider", "local")
        self.txt_api_key.blockSignals(True)
        if provider == "local":
            self.txt_api_key.setEnabled(False)
            self.btn_toggle_key.setEnabled(False)
            self.txt_api_key.setText("")
            self.txt_api_key.setPlaceholderText("Local Ollama chạy trên máy cục bộ, không cần khóa API")
        else:
            self.txt_api_key.setEnabled(True)
            self.btn_toggle_key.setEnabled(True)
            p_prefix = "sk-" if provider == "openai" else "AIzaSy..."
            self.txt_api_key.setPlaceholderText(f"Nhập {provider.upper()} API Key ({p_prefix})")
            self.txt_api_key.setText(self.vlm_controller.get_api_key(provider))
        self.txt_api_key.blockSignals(False)

    def _on_api_key_text_changed(self, text: str):
        data = self.combo_engine.currentData() or {}
        provider = data.get("provider")
        if provider:
            self.vlm_controller.set_api_key(provider, text.strip())

    def _toggle_api_key_visibility(self):
        if self.txt_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_key.setText("Ẩn")
        else:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_key.setText("Hiện")

    # -------------------------------------------------------------------------
    # Xử lý VLM qua VLMController
    # -------------------------------------------------------------------------
    def _on_start_vlm_analysis(self):
        if not self.current_image_path or not self.current_image_path.is_file():
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tập tin ảnh bản vẽ hợp lệ trước.")
            return

        selected_data = self.combo_engine.currentData()
        provider = selected_data["provider"]
        model = selected_data["model"]

        valid, msg = self.vlm_controller.validate_api_key(provider, self.txt_api_key.text().strip())
        if not valid:
            QMessageBox.warning(self, "Thiếu khóa API", msg)
            self.txt_api_key.setFocus()
            return

        self.log_message(f"Bắt đầu phân tích qua Engine: {self.combo_engine.currentText()}")
        self.vlm_controller.start_analysis(
            image_path=self.current_image_path,
            provider=provider,
            model=model,
            api_key=self.txt_api_key.text().strip(),
        )

    def _on_vlm_started(self):
        self.btn_analyze.setEnabled(False)
        self.btn_select_file.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.statusBar().showMessage("Đang phân tích bản vẽ bằng AI...")

    @Slot(object, float)
    def _on_vlm_finished(self, drawing_ir: DrawingIR, elapsed: float):
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.btn_select_file.setEnabled(True)
        self.log_message(f"Phân tích AI hoàn tất trong {elapsed:.2f} giây.")
        if drawing_ir.reasoning:
            self.log_message(f"--- Chuỗi suy luận hình học của AI (Reasoning) ---\n{drawing_ir.reasoning}")
        self.statusBar().showMessage(f"Phân tích hoàn tất ({elapsed:.2f}s). Sẵn sàng hiệu chỉnh tọa độ.")
        self._populate_tables_from_drawing_ir(drawing_ir)

    @Slot(str)
    def _on_vlm_error(self, error_message: str):
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.btn_select_file.setEnabled(True)
        self.log_message(f"Lỗi phân tích VLM: {error_message}")
        self.statusBar().showMessage("Quá trình phân tích gặp lỗi.")
        QMessageBox.critical(self, "Lỗi phân tích AI", f"Không thể trích xuất bản vẽ:\n{error_message}")

    # -------------------------------------------------------------------------
    # Thao tác bảng tọa độ (ủy quyền qua TableDataAdapter)
    # -------------------------------------------------------------------------
    def _populate_tables_from_drawing_ir(self, drawing_ir: DrawingIR):
        self.spin_stock_w.setValue(drawing_ir.stock_width)
        self.spin_stock_h.setValue(drawing_ir.stock_height)
        self.spin_stock_t.setValue(drawing_ir.stock_thickness)
        self.data_adapter.populate_from_drawing_ir(drawing_ir)

    def _on_stock_dim_changed(self):
        self._reset_contour_from_stock()

    def _reset_contour_from_stock(self):
        if hasattr(self, "data_adapter"):
            self.data_adapter.reset_contour_from_stock(
                self.spin_stock_w.value(), self.spin_stock_h.value()
            )

    def _add_contour_row(self):
        self.data_adapter.add_contour_row()

    def _delete_selected_contour(self):
        self.data_adapter.delete_selected_contour()

    def _add_hole_row(self):
        self.data_adapter.add_hole_row()

    def _delete_selected_hole(self):
        self.data_adapter.delete_selected_hole()

    def _add_slot_row(self):
        self.data_adapter.add_slot_row()

    def _add_new_slot(self):
        self.data_adapter.add_new_slot()

    def _delete_selected_slot(self):
        self.data_adapter.delete_selected_slot()

    def build_drawing_ir_from_tables(self) -> DrawingIR:
        return self.data_adapter.build_drawing_ir(
            stock_width=self.spin_stock_w.value(),
            stock_height=self.spin_stock_h.value(),
            stock_thickness=self.spin_stock_t.value(),
        )

    # -------------------------------------------------------------------------
    # Xuất file CAD DXF và chương trình CNC G-Code (qua ExportService)
    # -------------------------------------------------------------------------
    def _on_export_dxf(self):
        drawing_ir = self.build_drawing_ir_from_tables()
        self.export_service.export_dxf(drawing_ir)

    def _on_generate_gcode(self):
        drawing_ir = self.build_drawing_ir_from_tables()
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
            "mill_large_holes": self.chk_mill_holes.isChecked(),
            "mill_slot_width": self.chk_mill_slots.isChecked(),
        }
        saved_file, gcode_text = self.export_service.export_gcode(drawing_ir, params)
        if gcode_text:
            self.txt_gcode.setPlainText(gcode_text)
            self.simulator_widget.load_gcode(
                gcode_text, drawing_ir.stock_width, drawing_ir.stock_height, self.spin_tool_dia.value()
            )
            self.tabs_output.setCurrentIndex(0)
