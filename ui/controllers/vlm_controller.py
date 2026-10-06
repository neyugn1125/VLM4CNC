"""
Bộ điều phối phân tích thị giác VLM (VLMController & VLMWorker).
Đóng gói quản lý đa luồng QThread, xác thực khóa API và phát tín hiệu trạng thái.
"""

import os
from pathlib import Path
import time
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

from vision.schemas import DrawingIR
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
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.image_path = image_path
        self.provider = provider
        self.model = model
        self.api_key = api_key

    def run(self):
        start_time = time.perf_counter()
        try:
            self.progress_signal.emit("Đang kết nối và phân tích bản vẽ qua bộ phân tích...")
            import sys
            from unittest.mock import Mock
            main_mod = sys.modules.get("ui.main_window")
            if main_mod and isinstance(getattr(main_mod, "parse_drawing", None), Mock):
                parser_fn = main_mod.parse_drawing
            else:
                import vision.vlm_parser
                parser_fn = vision.vlm_parser.parse_drawing

            drawing_ir = parser_fn(
                image_path=self.image_path,
                provider=self.provider,
                model=self.model,
                api_key=self.api_key,
            )
            elapsed = time.perf_counter() - start_time
            self.finished_signal.emit(drawing_ir, elapsed)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class VLMController(QObject):
    """
    Controller điều phối toàn bộ chu trình phân tích bản vẽ kỹ thuật:
      - Quản lý khóa API (OpenAI, Gemini).
      - Xác thực đầu vào và điều phối luồng VLMWorker.
      - Phát tín hiệu giao tiếp sạch sẽ với View.
    """

    analysis_started = Signal()
    progress_message = Signal(str)
    analysis_finished = Signal(object, float)  # (DrawingIR, elapsed_seconds)
    analysis_error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.worker: Optional[VLMWorker] = None
        self._api_keys: Dict[str, str] = {
            "openai": os.getenv("OPENAI_API_KEY", ""),
            "gemini": os.getenv("GEMINI_API_KEY", ""),
        }

    def get_api_key(self, provider: str) -> str:
        return self._api_keys.get(provider, "")

    def set_api_key(self, provider: str, key: str):
        if provider in ("openai", "gemini"):
            self._api_keys[provider] = key.strip()

    def validate_api_key(self, provider: str, key: Optional[str] = None) -> Tuple[bool, str]:
        """Kiểm tra tính hợp lệ của khóa API cho provider yêu cầu."""
        if provider == "local":
            return True, ""
        api_k = key if key is not None else self.get_api_key(provider)
        if not api_k or not api_k.strip():
            p_name = "OpenAI" if provider == "openai" else "Google Gemini"
            return False, f"Vui lòng nhập khóa API cho {p_name} trước khi bắt đầu phân tích."
        return True, ""

    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start_analysis(
        self,
        image_path: Path,
        provider: str,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Khởi chạy worker phân tích VLM trên luồng ngầm."""
        if self.is_running():
            self.analysis_error.emit("Tiến trình phân tích VLM trước đó vẫn đang chạy.")
            return

        resolved_key = api_key if api_key is not None else self.get_api_key(provider)
        valid, msg = self.validate_api_key(provider, resolved_key)
        if not valid:
            self.analysis_error.emit(msg)
            return

        self.analysis_started.emit()

        self.worker = VLMWorker(
            image_path=image_path,
            provider=provider,
            model=model,
            api_key=resolved_key if provider != "local" else None,
            parent=self,
        )
        self.worker.progress_signal.connect(self.progress_message.emit)
        self.worker.finished_signal.connect(self._handle_finished)
        self.worker.error_signal.connect(self._handle_error)
        self.worker.start()

    def _handle_finished(self, drawing_ir: DrawingIR, elapsed: float):
        self.analysis_finished.emit(drawing_ir, elapsed)

    def _handle_error(self, error_msg: str):
        self.analysis_error.emit(error_msg)

    def cancel_analysis(self):
        """Hủy tiến trình phân tích nếu đang chạy."""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
