"""
G-Code Engine Module for VLM4CNC.
Converts DrawingIR intermediate representation into standard CNC G-Code programs.
Supports G54 WCS, canned drilling cycles (G81/G83), and multi-pass step-down slot milling.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
import logging

from vision.schemas import DrawingIR, DrillHole, SlotContour

logger = logging.getLogger("vlm4cnc.gcode_engine")


def generate_gcode(
    drawing_data: DrawingIR,
    machining_params: Dict[str, Any],
    output_path: str,
) -> str:
    """
    Generate CNC G-Code program from DrawingIR and machining parameters.

    Args:
        drawing_data: The DrawingIR containing stock dimensions, holes, and slots.
        machining_params: Dictionary of machining settings:
            - cut_depth_z: Target cut depth Z in mm (e.g. -5.0)
            - plunge_feed: Vertical plunge feedrate (mm/min, e.g. 100.0)
            - cut_feed: Horizontal cutting feedrate (mm/min, e.g. 300.0)
            - spindle_rpm: Spindle rotation speed (RPM, e.g. 1500)
            - safe_z: Clearance height above workpiece (mm, e.g. 50.0)
            - approach_z: Approach height before plunging (mm, e.g. 2.0)
            - tool_diameter: Endmill/drill tool diameter (mm, e.g. 3.0)
            - tool_number: Tool number in magazine (e.g. 1)
            - tool_offset_h: Tool length compensation index (e.g. 1)
            - program_number: CNC program number O (e.g. 1000)
            - cut_depth_per_pass: Maximum depth per milling pass (mm, e.g. 1.0)
            - drilling_cycle: Canned cycle type ('G81' or 'G83', default 'G83')
            - peck_depth: Peck increment for G83 (mm, default 2.0)
        output_path: Target path to write .nc or .gcode file.

    Returns:
        The generated G-Code program string.
    """
    # 1. Parse parameters with robust defaults matching standard machining setup
    cut_feed = float(machining_params.get("cut_feed") or machining_params.get("feedrate_xy", 300.0))
    plunge_feed = float(machining_params.get("plunge_feed", 100.0))
    spindle_rpm = int(machining_params.get("spindle_rpm") or machining_params.get("spindle_speed", 1500))
    safe_z = float(machining_params.get("safe_z", 50.0))
    approach_z = float(machining_params.get("approach_z", 2.0))
    tool_diameter = float(machining_params.get("tool_diameter", 3.0))
    tool_number = int(machining_params.get("tool_number", 1))
    tool_offset_h = int(machining_params.get("tool_offset_h", 1))
    program_number = int(machining_params.get("program_number", 1000))
    cut_depth_z = float(machining_params.get("cut_depth_z", -5.0))
    cut_depth_per_pass = float(machining_params.get("cut_depth_per_pass", 1.0))
    drilling_cycle = str(machining_params.get("drilling_cycle", "G83")).upper()
    peck_depth = float(machining_params.get("peck_depth", 2.0))

    lines: List[str] = []

    # 2. Header: Program number, safety preamble, tool change and spindle start
    lines.extend([
        "%",
        f"O{program_number:04d} (VLM4CNC GENERATED CNC PROGRAM)",
        "(=======================================================)",
        f"( STOCK SIZE : {drawing_data.stock_width:.2f} x {drawing_data.stock_height:.2f} x {drawing_data.stock_thickness:.2f} mm )",
        f"( TOOL #{tool_number}   : Ø{tool_diameter:.3f} mm ENDMILL/DRILL | OFFSET H{tool_offset_h} )",
        f"( SPINDLE    : {spindle_rpm} RPM | FEED: {cut_feed:.1f} mm/min | PLUNGE: {plunge_feed:.1f} mm/min )",
        f"( SAFE Z     : {safe_z:.1f} mm | APPROACH Z: {approach_z:.1f} mm | CUT Z: {cut_depth_z:.1f} mm )",
        "(=======================================================)",
        "G21 (Units in millimeters)",
        "G90 (Absolute programming mode)",
        "G40 (Tool radius compensation OFF)",
        "G80 (Cancel canned cycles)",
        "G17 (XY circular interpolation plane)",
        "G54 (Work coordinate system 1)",
        f"T{tool_number} M06 (Tool change to Tool #{tool_number})",
        f"G43 H{tool_offset_h} Z{safe_z:.3f} (Tool length compensation)",
        f"M03 S{spindle_rpm} (Spindle ON clockwise)",
        "G04 P1.5 (Dwell 1.5s for spindle to reach target speed)",
        "",
    ])

    # 3. Drilling Operations (G81 or G83 canned cycles)
    if drawing_data.holes:
        lines.extend([
            "(-------------------------------------------------------)",
            f"( OPERATION: DRILLING {len(drawing_data.holes)} HOLES )",
            "(-------------------------------------------------------)",
        ])

        first_hole = drawing_data.holes[0]
        # Rapid to first hole position in XY, then to Approach Z
        lines.append(f"G00 X{first_hole.center.x:.3f} Y{first_hole.center.y:.3f}")
        lines.append(f"G00 Z{approach_z:.3f}")

        # Execute canned cycle with R at approach_z
        if drilling_cycle == "G81":
            lines.append(
                f"G81 X{first_hole.center.x:.3f} Y{first_hole.center.y:.3f} "
                f"Z-{first_hole.depth:.3f} R{approach_z:.3f} F{plunge_feed:.1f}"
            )
            for h in drawing_data.holes[1:]:
                lines.append(f"X{h.center.x:.3f} Y{h.center.y:.3f} Z-{h.depth:.3f}")
        else:
            lines.append(
                f"G83 X{first_hole.center.x:.3f} Y{first_hole.center.y:.3f} "
                f"Z-{first_hole.depth:.3f} R{approach_z:.3f} Q{peck_depth:.3f} F{plunge_feed:.1f}"
            )
            for h in drawing_data.holes[1:]:
                lines.append(f"X{h.center.x:.3f} Y{h.center.y:.3f} Z-{h.depth:.3f}")

        # Cancel canned cycle and retract to safe height
        lines.extend([
            "G80 (Cancel canned drilling cycle)",
            f"G00 Z{safe_z:.3f} (Retract to safe Z)",
            "",
        ])

    # 4. Slot Milling Operations (Multi-pass step-down along centerline)
    if drawing_data.slots:
        lines.extend([
            "(-------------------------------------------------------)",
            f"( OPERATION: MILLING {len(drawing_data.slots)} SLOTS )",
            "(-------------------------------------------------------)",
        ])

        for slot_idx, slot in enumerate(drawing_data.slots, start=1):
            pts = slot.centerline_path
            # Target total depth: prefer slot.depth if specified, otherwise abs(cut_depth_z)
            total_depth = abs(slot.depth) if slot.depth > 0 else abs(cut_depth_z)
            step_down = max(cut_depth_per_pass, 0.05)

            # Compute depth levels
            z_levels: List[float] = []
            curr_depth = 0.0
            while curr_depth < total_depth:
                curr_depth = min(curr_depth + step_down, total_depth)
                z_levels.append(-curr_depth)

            lines.extend([
                f"(--- Slot {slot_idx}: Width={slot.width:.2f}mm, Target Depth={total_depth:.2f}mm ---)",
                f"G00 X{pts[0].x:.3f} Y{pts[0].y:.3f} (Rapid to slot entry)",
                f"G00 Z{approach_z:.3f} (Rapid to approach clearance)",
            ])

            for pass_idx, target_z in enumerate(z_levels, start=1):
                lines.append(f"(Pass {pass_idx}/{len(z_levels)} at Z={target_z:.3f})")
                # Plunge into material
                lines.append(f"G01 Z{target_z:.3f} F{plunge_feed:.1f}")

                # Cut forward through path points
                for p in pts[1:]:
                    lines.append(f"G01 X{p.x:.3f} Y{p.y:.3f} F{cut_feed:.1f}")

                # Retract back to approach height and return to start for next step-down
                if pass_idx < len(z_levels):
                    lines.append(f"G00 Z{approach_z:.3f}")
                    lines.append(f"G00 X{pts[0].x:.3f} Y{pts[0].y:.3f}")

            # Retract after finishing slot
            lines.extend([
                f"G00 Z{safe_z:.3f}",
                "",
            ])

    # 5. Outer Profile Contour Milling (Phay biên dạng bao ngoài các cạnh chi tiết)
    mill_outer_contour = machining_params.get("mill_outer_contour", True)
    contour_pts = (
        drawing_data.get_effective_outer_contour()
        if hasattr(drawing_data, "get_effective_outer_contour")
        else getattr(drawing_data, "outer_contour", None)
    )

    if mill_outer_contour and contour_pts and len(contour_pts) >= 3:
        total_depth = abs(cut_depth_z) if abs(cut_depth_z) > 0 else 5.0
        step_down = max(cut_depth_per_pass, 0.05)

        z_levels_contour: List[float] = []
        curr_depth = 0.0
        while curr_depth < total_depth:
            curr_depth = min(curr_depth + step_down, total_depth)
            z_levels_contour.append(-curr_depth)

        lines.extend([
            "(-------------------------------------------------------)",
            f"( OPERATION: PROFILE MILLING OUTER CONTOUR ({len(contour_pts)} POINTS) )",
            f"( CUT DEPTH Z: -{total_depth:.3f} mm | PASSES: {len(z_levels_contour)} )",
            "(-------------------------------------------------------)",
        ])

        first_pt = contour_pts[0]
        lines.extend([
            f"G00 X{first_pt.x:.3f} Y{first_pt.y:.3f} (Rapid to contour start)",
            f"G00 Z{approach_z:.3f} (Rapid to approach clearance)",
        ])

        for pass_idx, target_z in enumerate(z_levels_contour, start=1):
            lines.append(f"(Contour Pass {pass_idx}/{len(z_levels_contour)} at Z={target_z:.3f})")
            # Plunge into material
            lines.append(f"G01 Z{target_z:.3f} F{plunge_feed:.1f}")

            # Profile along edges
            for pt in contour_pts[1:]:
                lines.append(f"G01 X{pt.x:.3f} Y{pt.y:.3f} F{cut_feed:.1f}")

            # If more passes, return to start point
            if pass_idx < len(z_levels_contour):
                lines.append(f"G00 Z{approach_z:.3f}")
                lines.append(f"G00 X{first_pt.x:.3f} Y{first_pt.y:.3f}")

        lines.extend([
            f"G00 Z{safe_z:.3f} (Retract to safe clearance)",
            "",
        ])

    # 6. Footer: Safe parking and program end
    lines.extend([
        "(-------------------------------------------------------)",
        "( PROGRAM TERMINATION                                   )",
        "(-------------------------------------------------------)",
        f"G00 Z{safe_z:.3f} (Retract to safe clearance)",
        "M05 (Spindle stop)",
        "G00 X0.000 Y0.000 (Return to work origin)",
        "M30 (End of program)",
        "%",
    ])

    program_text = "\n".join(lines) + "\n"

    # 6. Save to output file
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(program_text, encoding="utf-8")
    logger.info(f"G-Code saved to {target.resolve()}")

    return program_text


from dataclasses import dataclass, asdict


@dataclass
class ToolSettings:
    """Tooling and machining parameters for CNC G-code generation."""
    tool_diameter: float = 3.175  # mm (1/8 inch)
    feed_rate: float = 800.0      # mm/min
    plunge_rate: float = 300.0    # mm/min
    spindle_speed: int = 12000    # RPM
    safe_z: float = 5.0           # mm above workpiece
    cut_depth: float = -2.0       # mm target depth
    pass_depth: float = 1.0       # mm per pass


class GCodeEngine:
    """Class wrapper for G-Code compilation (retained for backward compatibility)."""

    def __init__(self, settings: ToolSettings = None):
        self.settings = settings or ToolSettings()

    def generate(self, drawing_data: DrawingIR, machining_params: Dict[str, Any], output_path: str) -> str:
        return generate_gcode(drawing_data, machining_params, output_path)

    def compile_program(self, contours: List[List[Tuple[float, float]]], program_name: str = "PART_01") -> str:
        """Compile raw contour coordinates into a G-Code program."""
        lines = [
            f"(Program: {program_name})",
            "G21", "G90", "G40", "G80", "G17", "G54",
            f"G00 Z{self.settings.safe_z:.3f}",
            f"M03 S{self.settings.spindle_speed}",
        ]
        for contour in contours:
            if not contour:
                continue
            lines.append(f"G00 X{contour[0][0]:.3f} Y{contour[0][1]:.3f}")
            lines.append(f"G01 Z{self.settings.cut_depth:.3f} F{self.settings.plunge_rate:.1f}")
            for pt in contour[1:]:
                lines.append(f"G01 X{pt[0]:.3f} Y{pt[1]:.3f} F{self.settings.feed_rate:.1f}")
            lines.append(f"G00 Z{self.settings.safe_z:.3f}")
        lines.extend([
            f"G00 Z{self.settings.safe_z:.3f}",
            "M05",
            "G00 X0.000 Y0.000",
            "M30",
        ])
        return "\n".join(lines) + "\n"

    def save_gcode(self, content: str, filepath: Union[str, Path]) -> Path:
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

