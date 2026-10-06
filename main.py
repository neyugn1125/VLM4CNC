#!/usr/bin/env python3
"""
VLM4CNC - Main Application Entrypoint.
Converts 2D mechanical drawings into DXF CAD models and CNC G-Code via VLM & MCP Server.
Configures High-DPI scaling and classic light theme styling.
"""

import os
import sys
from pathlib import Path
import logging

# Support PyInstaller onefile bundle directory (_MEIPASS) and regular execution
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_ROOT = Path(sys._MEIPASS).resolve()
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("vlm4cnc")

from ui.themes import CLASSIC_LIGHT_THEME_STYLESHEET, DARK_THEME_STYLESHEET


def configure_platform_environment():
    """Configure platform-specific variables for Wayland/X11 on Linux."""
    if sys.platform.startswith("linux"):
        if "QT_QPA_PLATFORM" not in os.environ:
            os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"


def start_gui():
    """Start the PySide6 Desktop GUI."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from ui.main_window import MainWindow
    except ImportError as e:
        logger.error(
            f"PySide6 is not installed or GUI libraries are missing: {e}\n"
            "Run 'pip install -r requirements.txt' inside your virtual environment."
        )
        sys.exit(1)

    configure_platform_environment()

    # Configure High-DPI Scaling
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("VLM4CNC")
    app.setOrganizationName("VLM4CNC")
    app.setStyleSheet(CLASSIC_LIGHT_THEME_STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def start_mcp_server():
    """Start the MCP server directly."""
    try:
        from mcp_server.server import run_server
        logger.info("Starting VLM4CNC MCP Server on stdio...")
        run_server(transport="stdio")
    except Exception as e:
        logger.error(f"Failed to start MCP Server: {e}")
        sys.exit(1)


def main():
    """Main CLI & App dispatcher."""
    if len(sys.argv) > 1 and sys.argv[1] in ("--server", "--mcp"):
        start_mcp_server()
    else:
        start_gui()


if __name__ == "__main__":
    main()
