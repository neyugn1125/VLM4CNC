"""
Dịch vụ xuất tập tin CAD DXF và chương trình CNC G-Code (ExportService).
Đóng gói toàn bộ logic tương tác hộp thoại tập tin (QFileDialog), xử lý lỗi và ghi nhật ký.
"""

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from core.dxf_engine import export_drawing_to_dxf
from core.gcode_engine import generate_gcode
from vision.schemas import DrawingIR, MachiningParams


class ExportService:
    """Quản lý các tác vụ xuất dữ liệu ra đĩa cứng."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        self.parent = parent
        self.log_callback = log_callback or (lambda msg: None)
        self.status_callback = status_callback or (lambda msg: None)

    def log(self, message: str):
        self.log_callback(message)

    def status(self, message: str):
        self.status_callback(message)

    def export_dxf(
        self,
        drawing_ir: DrawingIR,
        target_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Xuất đối tượng DrawingIR ra định dạng AutoCAD DXF.
        Nếu target_path là None, hiển thị QFileDialog để người dùng chọn vị trí lưu.
        """
        filepath = target_path
        if not filepath:
            default_dir = Path("outputs")
            default_dir.mkdir(parents=True, exist_ok=True)
            chosen, _ = QFileDialog.getSaveFileName(
                self.parent,
                "Lưu bản vẽ AutoCAD DXF",
                str(default_dir / "drawing_output.dxf"),
                "DXF Files (*.dxf)",
            )
            if not chosen:
                return None
            filepath = chosen

        try:
            saved = export_drawing_to_dxf(drawing_ir, filepath)
            self.log(f"Xuất file DXF thành công: {saved}")
            self.status(f"DXF lưu tại: {Path(saved).name}")
            if self.parent:
                QMessageBox.information(self.parent, "Thành công", f"Đã xuất bản vẽ DXF:\n{saved}")
            return saved
        except Exception as exc:
            self.log(f"Lỗi xuất DXF: {exc}")
            if self.parent:
                QMessageBox.critical(self.parent, "Lỗi", f"Không thể xuất DXF: {exc}")
            raise exc

    def export_gcode(
        self,
        drawing_ir: DrawingIR,
        params: Union[MachiningParams, Dict[str, Any]],
        target_path: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Biên dịch đối tượng DrawingIR thành G-Code và lưu ra đĩa cứng.
        Nếu target_path là None, hiển thị QFileDialog để người dùng chọn vị trí lưu.
        Trả về tuple (saved_filepath, gcode_text).
        """
        filepath = target_path
        if not filepath:
            default_dir = Path("outputs")
            default_dir.mkdir(parents=True, exist_ok=True)
            chosen, _ = QFileDialog.getSaveFileName(
                self.parent,
                "Lưu chương trình CNC G-Code",
                str(default_dir / "program_output.nc"),
                "G-Code Files (*.nc *.gcode *.tap)",
            )
            if not chosen:
                return None, None
            filepath = chosen

        try:
            gcode_text = generate_gcode(drawing_ir, params, filepath)
            line_count = len(gcode_text.splitlines())
            self.log(f"Sinh mã G-Code thành công ({line_count} dòng): {filepath}")
            self.status(f"G-Code lưu tại: {Path(filepath).name}")
            if self.parent:
                QMessageBox.information(self.parent, "Thành công", f"Đã sinh chương trình G-Code:\n{filepath}")
            return filepath, gcode_text
        except Exception as exc:
            self.log(f"Lỗi sinh G-Code: {exc}")
            if self.parent:
                QMessageBox.critical(self.parent, "Lỗi", f"Không thể sinh G-Code: {exc}")
            raise exc

