"""
VLM4CNC - UI Themes & Stylesheets Module.
Cung cấp định dạng giao diện chuẩn Qt Stylesheet (QSS) cho ứng dụng PySide6.
"""

CLASSIC_LIGHT_THEME_STYLESHEET = """
QMainWindow {
    background-color: #f0f0f0;
}

QWidget {
    background-color: #f0f0f0;
    color: #000000;
    font-family: 'Segoe UI', 'Ubuntu', 'Roboto', sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #555555;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 15px;
    font-weight: bold;
    color: #000000;
    background-color: #f8f8f8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    background-color: #f8f8f8;
    color: #000000;
}

QPushButton {
    background-color: #e6e6e6;
    color: #000000;
    border: 1px solid #707070;
    border-radius: 3px;
    padding: 6px 12px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #dadada;
    border-color: #000000;
}

QPushButton:pressed {
    background-color: #c4c4c4;
    border-color: #000000;
}

QPushButton:disabled {
    background-color: #f0f0f0;
    color: #888888;
    border-color: #cccccc;
}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background-color: #ffffff;
    border: 1px solid #707070;
    border-radius: 3px;
    padding: 5px 8px;
    color: #000000;
    selection-background-color: #0078d7;
    selection-color: #ffffff;
}

QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
    border: 1px solid #005a9e;
}

QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled {
    background-color: #eaeaea;
    color: #777777;
    border-color: #cccccc;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #707070;
    selection-background-color: #0078d7;
    selection-color: #ffffff;
}

QTableWidget {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #555555;
    border-radius: 2px;
    gridline-color: #b0b0b0;
    selection-background-color: #0078d7;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #e2e2e2;
    color: #000000;
    padding: 6px;
    border: 1px solid #888888;
    font-weight: bold;
}

QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid #707070;
    border-radius: 2px;
    color: #000000;
    selection-background-color: #0078d7;
    selection-color: #ffffff;
}

QTabWidget::pane {
    border: 1px solid #707070;
    border-radius: 2px;
    background-color: #ffffff;
}

QTabBar::tab {
    background-color: #dedede;
    color: #333333;
    border: 1px solid #707070;
    padding: 6px 14px;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #000000;
    border-bottom-color: #ffffff;
    font-weight: bold;
}

QProgressBar {
    border: 1px solid #707070;
    border-radius: 2px;
    text-align: center;
    background-color: #e6e6e6;
    color: #000000;
}

QProgressBar::chunk {
    background-color: #0078d7;
    border-radius: 1px;
}

QStatusBar {
    background-color: #e8e8e8;
    border-top: 1px solid #cccccc;
    color: #000000;
}

QSplitter::handle {
    background-color: #c4c4c4;
    width: 3px;
    height: 3px;
}

QSplitter::handle:hover {
    background-color: #555555;
}

QScrollBar:vertical {
    background: #f0f0f0;
    width: 14px;
    border: 1px solid #cccccc;
}

QScrollBar::handle:vertical {
    background: #c0c0c0;
    border: 1px solid #999999;
    border-radius: 2px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #a0a0a0;
}
"""

# Alias tuong thich nguoc
DARK_THEME_STYLESHEET = CLASSIC_LIGHT_THEME_STYLESHEET

