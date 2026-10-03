"""
MCP Server implementation for VLM4CNC using FastMCP (Anthropic official Python SDK).
Exposes CAD DXF export and CNC G-Code generation tools to AI agents and LLMs.
"""

import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError
from mcp.server.fastmcp import FastMCP

from vision.schemas import DrawingIR
from core.dxf_engine import export_drawing_to_dxf
from core.gcode_engine import generate_gcode

logger = logging.getLogger("vlm4cnc.mcp_server")

# 1. Initialize FastMCP server
mcp = FastMCP("cad-cam-mcp-server")


DEFAULT_DXF_PATH = str(Path("outputs") / "drawing.dxf")
DEFAULT_GCODE_PATH = str(Path("outputs") / "part.nc")


# 2. Tool 1: export_dxf_tool
@mcp.tool()
def export_dxf_tool(drawing_ir_json: str, output_path: str = DEFAULT_DXF_PATH) -> str:
    """
    Export 2D mechanical drawing intermediate representation (DrawingIR) to a standard AutoCAD DXF file.

    Args:
        drawing_ir_json: JSON string representing DrawingIR model (stock dimensions, holes, slots).
        output_path: Target path for the output .dxf file (e.g., 'outputs/part.dxf').

    Returns:
        Status message with the absolute path of the generated DXF file, or error message.
    """
    try:
        # Validate input JSON against DrawingIR schema
        try:
            drawing_data = DrawingIR.model_validate_json(drawing_ir_json)
        except ValidationError as val_err:
            return f"[ERROR] Invalid DrawingIR schema validation failed:\n{val_err}"
        except Exception as json_err:
            return f"[ERROR] Failed to parse DrawingIR JSON string: {json_err}"

        # Resolve destination path using pathlib.Path
        target_path = Path(output_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Call core DXF engine
        saved_path = export_drawing_to_dxf(drawing_data, str(target_path))

        return f"[SUCCESS] DXF file generated successfully at: {saved_path}"

    except Exception as exc:
        logger.exception("Unexpected error in export_dxf_tool")
        return f"[ERROR] An unexpected error occurred while exporting DXF: {exc}"


# 3. Tool 2: generate_gcode_tool
@mcp.tool()
def generate_gcode_tool(
    drawing_ir_json: str,
    params_json: str = "{}",
    output_path: str = DEFAULT_GCODE_PATH,
) -> str:
    """
    Generate CNC G-Code program from DrawingIR and machining parameters.

    Args:
        drawing_ir_json: JSON string representing DrawingIR model.
        params_json: JSON string containing machining settings:
            - feedrate_xy: Horizontal cutting feedrate (mm/min, e.g. 800)
            - plunge_feed: Plunge feedrate (mm/min, e.g. 300)
            - spindle_speed: Spindle speed (RPM, e.g. 12000)
            - safe_z: Safe clearance height (mm, e.g. 5.0)
            - cut_depth_per_pass: Maximum depth per pass (mm, e.g. 1.0)
            - tool_diameter: Endmill tool diameter (mm, e.g. 3.175)
            - drilling_cycle: Canned cycle type ('G81' or 'G83', default 'G83')
            - peck_depth: Peck increment for G83 (mm, default 2.0)
            - retract_r: Retract clearance plane R (mm, default 2.0)
        output_path: Target path for the output .nc file (e.g., 'outputs/part.nc').

    Returns:
        Status message with output path and a 20-line preview of the generated G-code, or error message.
    """
    try:
        # Validate DrawingIR JSON
        try:
            drawing_data = DrawingIR.model_validate_json(drawing_ir_json)
        except ValidationError as val_err:
            return f"[ERROR] Invalid DrawingIR schema validation failed:\n{val_err}"
        except Exception as json_err:
            return f"[ERROR] Failed to parse DrawingIR JSON string: {json_err}"

        # Validate machining parameters JSON
        try:
            if isinstance(params_json, str):
                machining_params = json.loads(params_json) if params_json.strip() else {}
            elif isinstance(params_json, dict):
                machining_params = params_json
            else:
                return f"[ERROR] params_json must be a JSON string or dict, got {type(params_json).__name__}"

            if not isinstance(machining_params, dict):
                return "[ERROR] params_json must evaluate to a dictionary object."
        except json.JSONDecodeError as json_err:
            return f"[ERROR] Failed to parse machining params JSON: {json_err}"

        # Resolve output path using pathlib.Path
        target_path = Path(output_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Call core G-Code engine
        gcode_text = generate_gcode(drawing_data, machining_params, str(target_path))

        # Extract first 20 lines for preview
        gcode_lines = gcode_text.splitlines()
        preview_lines = gcode_lines[:20]
        preview_text = "\n".join(preview_lines)

        return (
            f"[SUCCESS] CNC G-Code program generated successfully at: {target_path}\n"
            f"Total Lines: {len(gcode_lines)}\n"
            f"--- [Preview First 20 Lines] ---\n"
            f"{preview_text}\n"
            f"--- [End of Preview] ---"
        )

    except Exception as exc:
        logger.exception("Unexpected error in generate_gcode_tool")
        return f"[ERROR] An unexpected error occurred while generating G-Code: {exc}"


def create_mcp_server():
    """Return the FastMCP server instance (retained for backward compatibility)."""
    return mcp


def run_server(transport: str = "stdio") -> None:
    """Run the FastMCP server."""
    logger.info(f"Starting cad-cam-mcp-server with {transport} transport...")
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_server(transport="stdio")
