"""
Mô hình dữ liệu và Bộ chuyển đổi dữ liệu bảng (TableDataAdapter & QAbstractTableModel).
Hỗ trợ quản lý thực thể gia công (Lỗ khoan, Rãnh phay, Cạnh biên dạng) theo kiến trúc Model/View chuẩn Qt.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour


@dataclass
class DrawingEntityItem:
    """Đại diện một thực thể kỹ thuật hiển thị trên bảng."""
    entity_type: str
    params: Dict[str, Any]


class HolesTableModel(QAbstractTableModel):
    """Mô hình dữ liệu QAbstractTableModel cho bảng lỗ khoan."""

    HEADERS = ["STT", "Tọa độ X (mm)", "Tọa độ Y (mm)", "Đường kính Ø (mm)", "Chiều sâu (mm)"]

    def __init__(self, holes: Optional[List[DrillHole]] = None, parent=None):
        super().__init__(parent)
        self._holes: List[DrillHole] = holes or []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._holes)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._holes)):
            return None
        hole = self._holes[index.row()]
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return str(index.row() + 1)
            elif col == 1:
                return f"{hole.center.x:.3f}"
            elif col == 2:
                return f"{hole.center.y:.3f}"
            elif col == 3:
                return f"{hole.diameter:.3f}"
            elif col == 4:
                return f"{hole.depth:.3f}"
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        row = index.row()
        col = index.column()
        hole = self._holes[row]
        try:
            val_float = float(value)
            if col == 1:
                hole.center.x = val_float
            elif col == 2:
                hole.center.y = val_float
            elif col == 3:
                hole.diameter = val_float
            elif col == 4:
                hole.depth = val_float
            else:
                return False
            self.dataChanged.emit(index, index, [role])
            return True
        except (ValueError, TypeError):
            return False

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def set_holes(self, holes: List[DrillHole]):
        self.beginResetModel()
        self._holes = list(holes)
        self.endResetModel()

    def get_holes(self) -> List[DrillHole]:
        return list(self._holes)

    def add_hole(self, hole: DrillHole):
        row = len(self._holes)
        self.beginInsertRows(QModelIndex(), row, row)
        self._holes.append(hole)
        self.endInsertRows()

    def remove_hole(self, row: int) -> bool:
        if 0 <= row < len(self._holes):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._holes.pop(row)
            self.endRemoveRows()
            return True
        return False


class SlotsTableModel(QAbstractTableModel):
    """Mô hình dữ liệu QAbstractTableModel cho bảng rãnh phay."""

    HEADERS = ["Rãnh / Điểm", "Tọa độ X (mm)", "Tọa độ Y (mm)", "Bề rộng rãnh (mm)", "Chiều sâu (mm)"]

    def __init__(self, slots: Optional[List[SlotContour]] = None, parent=None):
        super().__init__(parent)
        self._slots: List[SlotContour] = slots or []
        self._flattened_rows: List[Dict[str, Any]] = []
        self._rebuild_flattened()

    def _rebuild_flattened(self):
        self._flattened_rows = []
        for slot_idx, slot in enumerate(self._slots, start=1):
            for pt in slot.centerline_path:
                self._flattened_rows.append({
                    "slot_label": f"Rãnh {slot_idx}",
                    "x": pt.x,
                    "y": pt.y,
                    "width": slot.width,
                    "depth": slot.depth,
                })

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._flattened_rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._flattened_rows)):
            return None
        item = self._flattened_rows[index.row()]
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return item["slot_label"]
            elif col == 1:
                return f"{item['x']:.3f}"
            elif col == 2:
                return f"{item['y']:.3f}"
            elif col == 3:
                return f"{item['width']:.3f}"
            elif col == 4:
                return f"{item['depth']:.3f}"
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def set_slots(self, slots: List[SlotContour]):
        self.beginResetModel()
        self._slots = list(slots)
        self._rebuild_flattened()
        self.endResetModel()


class ContourTableModel(QAbstractTableModel):
    """Mô hình dữ liệu QAbstractTableModel cho bảng đỉnh cạnh bao ngoài."""

    HEADERS = ["Đỉnh", "Tọa độ X (mm)", "Tọa độ Y (mm)"]

    def __init__(self, contour: Optional[List[Point2D]] = None, parent=None):
        super().__init__(parent)
        self._contour: List[Point2D] = contour or []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._contour)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._contour)):
            return None
        pt = self._contour[index.row()]
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return str(index.row() + 1)
            elif col == 1:
                return f"{pt.x:.3f}"
            elif col == 2:
                return f"{pt.y:.3f}"
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def set_contour(self, contour: List[Point2D]):
        self.beginResetModel()
        self._contour = list(contour)
        self.endResetModel()

    def get_contour(self) -> List[Point2D]:
        return list(self._contour)


class TableDataAdapter:
    """
    Bộ chuyển đổi dữ liệu hai chiều giữa các QTableWidget và schema Pydantic DrawingIR.
    Tách biệt hoàn toàn logic quản lý dữ liệu bảng khỏi MainWindow.
    """

    def __init__(
        self,
        table_holes: QTableWidget,
        table_slots: QTableWidget,
        table_contour: QTableWidget,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.table_holes = table_holes
        self.table_slots = table_slots
        self.table_contour = table_contour
        self.log_callback = log_callback or (lambda msg: None)

    def log(self, message: str):
        self.log_callback(message)

    def populate_from_drawing_ir(self, drawing_ir: DrawingIR):
        """Điền dữ liệu DrawingIR vào các bảng giao diện."""
        # 1. Bảng lỗ khoan
        self.table_holes.setRowCount(0)
        for idx, hole in enumerate(drawing_ir.holes, start=1):
            row = self.table_holes.rowCount()
            self.table_holes.insertRow(row)
            self.table_holes.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table_holes.setItem(row, 1, QTableWidgetItem(f"{hole.center.x:.3f}"))
            self.table_holes.setItem(row, 2, QTableWidgetItem(f"{hole.center.y:.3f}"))
            self.table_holes.setItem(row, 3, QTableWidgetItem(f"{hole.diameter:.3f}"))
            self.table_holes.setItem(row, 4, QTableWidgetItem(f"{hole.depth:.3f}"))

        # 2. Bảng rãnh phay
        self.table_slots.setRowCount(0)
        total_slot_pts = 0
        for slot_idx, slot in enumerate(drawing_ir.slots, start=1):
            for pt in slot.centerline_path:
                row = self.table_slots.rowCount()
                self.table_slots.insertRow(row)
                self.table_slots.setItem(row, 0, QTableWidgetItem(f"Rãnh {slot_idx}"))
                self.table_slots.setItem(row, 1, QTableWidgetItem(f"{pt.x:.3f}"))
                self.table_slots.setItem(row, 2, QTableWidgetItem(f"{pt.y:.3f}"))
                self.table_slots.setItem(row, 3, QTableWidgetItem(f"{slot.width:.3f}"))
                self.table_slots.setItem(row, 4, QTableWidgetItem(f"{slot.depth:.3f}"))
                total_slot_pts += 1

        # 3. Bảng cạnh bao ngoài
        contour_pts = drawing_ir.get_effective_outer_contour()
        self.table_contour.setRowCount(0)
        for idx, pt in enumerate(contour_pts, start=1):
            row = self.table_contour.rowCount()
            self.table_contour.insertRow(row)
            self.table_contour.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table_contour.setItem(row, 1, QTableWidgetItem(f"{pt.x:.3f}"))
            self.table_contour.setItem(row, 2, QTableWidgetItem(f"{pt.y:.3f}"))

        self.log(
            f"Đã đồng bộ vào bảng: {len(drawing_ir.holes)} lỗ khoan, "
            f"{len(drawing_ir.slots)} rãnh phay ({total_slot_pts} điểm) và {len(contour_pts)} đỉnh cạnh bao ngoài."
        )

    def reset_contour_from_stock(self, width: float, height: float):
        """Tạo lại 4 cạnh bao ngoài khép kín từ kích thước phôi."""
        pts = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
        self.table_contour.setRowCount(0)
        for idx, (x, y) in enumerate(pts, start=1):
            row = self.table_contour.rowCount()
            self.table_contour.insertRow(row)
            self.table_contour.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table_contour.setItem(row, 1, QTableWidgetItem(f"{x:.3f}"))
            self.table_contour.setItem(row, 2, QTableWidgetItem(f"{y:.3f}"))

    def add_hole_row(self, x: float = 0.0, y: float = 0.0, diameter: float = 10.0, depth: float = 5.0):
        row = self.table_holes.rowCount()
        self.table_holes.insertRow(row)
        self.table_holes.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_holes.setItem(row, 1, QTableWidgetItem(f"{x:.3f}"))
        self.table_holes.setItem(row, 2, QTableWidgetItem(f"{y:.3f}"))
        self.table_holes.setItem(row, 3, QTableWidgetItem(f"{diameter:.3f}"))
        self.table_holes.setItem(row, 4, QTableWidgetItem(f"{depth:.3f}"))

    def delete_selected_hole(self):
        curr_row = self.table_holes.currentRow()
        if curr_row >= 0:
            self.table_holes.removeRow(curr_row)

    def add_slot_row(self, x: float = 0.0, y: float = 0.0, width: float = 8.0, depth: float = 5.0):
        row = self.table_slots.rowCount()
        self.table_slots.insertRow(row)
        prev_label = "Rãnh 1"
        if row > 0 and self.table_slots.item(row - 1, 0):
            prev_label = self.table_slots.item(row - 1, 0).text().strip()
        self.table_slots.setItem(row, 0, QTableWidgetItem(prev_label))
        self.table_slots.setItem(row, 1, QTableWidgetItem(f"{x:.3f}"))
        self.table_slots.setItem(row, 2, QTableWidgetItem(f"{y:.3f}"))
        self.table_slots.setItem(row, 3, QTableWidgetItem(f"{width:.3f}"))
        self.table_slots.setItem(row, 4, QTableWidgetItem(f"{depth:.3f}"))

    def add_new_slot(self, width: float = 8.0, depth: float = 5.0):
        row = self.table_slots.rowCount()
        max_slot_num = 0
        for r in range(row):
            item = self.table_slots.item(r, 0)
            if item:
                txt = item.text().replace("Rãnh", "").replace("Slot", "").strip()
                if txt.isdigit():
                    max_slot_num = max(max_slot_num, int(txt))
        next_label = f"Rãnh {max_slot_num + 1}"
        for i in range(2):
            r_idx = self.table_slots.rowCount()
            self.table_slots.insertRow(r_idx)
            self.table_slots.setItem(r_idx, 0, QTableWidgetItem(next_label))
            self.table_slots.setItem(r_idx, 1, QTableWidgetItem("0.000" if i == 0 else "10.000"))
            self.table_slots.setItem(r_idx, 2, QTableWidgetItem("0.000"))
            self.table_slots.setItem(r_idx, 3, QTableWidgetItem(f"{width:.3f}"))
            self.table_slots.setItem(r_idx, 4, QTableWidgetItem(f"{depth:.3f}"))

    def delete_selected_slot(self):
        curr_row = self.table_slots.currentRow()
        if curr_row >= 0:
            self.table_slots.removeRow(curr_row)

    def add_contour_row(self, x: float = 0.0, y: float = 0.0):
        row = self.table_contour.rowCount()
        self.table_contour.insertRow(row)
        self.table_contour.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_contour.setItem(row, 1, QTableWidgetItem(f"{x:.3f}"))
        self.table_contour.setItem(row, 2, QTableWidgetItem(f"{y:.3f}"))

    def delete_selected_contour(self):
        curr_row = self.table_contour.currentRow()
        if curr_row >= 0:
            self.table_contour.removeRow(curr_row)

    def build_drawing_ir(
        self, stock_width: float, stock_height: float, stock_thickness: float
    ) -> DrawingIR:
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
                self.log(f"Bỏ qua dòng lỗ {row + 1} do sai định dạng số: {e}")

        slots: List[SlotContour] = []
        raw_rows = []
        has_explicit_slot_names = False

        for row in range(self.table_slots.rowCount()):
            try:
                col0_item = self.table_slots.item(row, 0)
                raw_id = col0_item.text().strip() if col0_item else "1"
                if raw_id.startswith("Rãnh") or raw_id.startswith("Slot"):
                    has_explicit_slot_names = True
                x = float(self.table_slots.item(row, 1).text())
                y = float(self.table_slots.item(row, 2).text())
                slot_w = float(self.table_slots.item(row, 3).text())
                slot_d = float(self.table_slots.item(row, 4).text())
                raw_rows.append((raw_id, x, y, slot_w, slot_d))
            except Exception as e:
                self.log(f"Bỏ qua dòng rãnh {row + 1} do sai định dạng số: {e}")

        current_slot_id = None
        current_pts: List[Point2D] = []
        current_w = 8.0
        current_d = 5.0

        for raw_id, x, y, slot_w, slot_d in raw_rows:
            is_new_slot = False
            if has_explicit_slot_names:
                is_new_slot = (current_slot_id is not None and raw_id != current_slot_id)
            else:
                is_new_slot = (
                    current_slot_id is not None
                    and (abs(slot_w - current_w) > 0.05 or abs(slot_d - current_d) > 0.05)
                )

            if is_new_slot:
                if len(current_pts) >= 2:
                    slots.append(SlotContour(width=current_w, depth=current_d, centerline_path=current_pts))
                current_pts = []

            current_slot_id = raw_id
            current_w = slot_w
            current_d = slot_d
            current_pts.append(Point2D(x=x, y=y))

        if len(current_pts) >= 2:
            slots.append(SlotContour(width=current_w, depth=current_d, centerline_path=current_pts))

        contour_pts: List[Point2D] = []
        for row in range(self.table_contour.rowCount()):
            try:
                x = float(self.table_contour.item(row, 1).text())
                y = float(self.table_contour.item(row, 2).text())
                contour_pts.append(Point2D(x=x, y=y))
            except Exception as e:
                self.log(f"Bỏ qua dòng đỉnh cạnh {row + 1} do sai định dạng số: {e}")

        return DrawingIR(
            stock_width=stock_width,
            stock_height=stock_height,
            stock_thickness=stock_thickness,
            holes=holes,
            slots=slots,
            outer_contour=contour_pts if len(contour_pts) >= 3 else None,
        )

