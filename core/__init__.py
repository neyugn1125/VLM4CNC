"""
VLM4CNC - Core CAD/CAM Engine Module.
"""

from .dxf_engine import DXFEngine, export_drawing_to_dxf, calculate_slot_contour
from .gcode_engine import GCodeEngine, ToolSettings, generate_gcode, MachiningParams

__all__ = [
    "DXFEngine",
    "export_drawing_to_dxf",
    "calculate_slot_contour",
    "GCodeEngine",
    "ToolSettings",
    "generate_gcode",
    "MachiningParams",
]

