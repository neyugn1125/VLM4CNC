"""
G-Code Engine Module for VLM4CNC.
Converts DrawingIR intermediate representation into standard CNC G-Code programs.
Supports G54 WCS, canned drilling cycles (G81/G83), and multi-pass step-down slot milling.
"""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import logging

from vision.schemas import DrawingIR, DrillHole, MachiningParams, Point2D, SlotContour

logger = logging.getLogger("vlm4cnc.core.gcode")


def signed_polygon_area(points: List[Tuple[float, float]]) -> float:
    """Calculate signed polygon area (positive = CCW, negative = CW)."""
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        p1 = points[i]
        p2 = points[(i + 1) % n]
        area += (p1[0] * p2[1] - p2[0] * p1[1])
    return 0.5 * area


def ensure_polygon_winding(points: List[Tuple[float, float]], clockwise: bool = True) -> List[Tuple[float, float]]:
    """Ensure polygon vertices follow requested winding direction (CW for Climb Milling, CCW for Conventional)."""
    if len(points) < 3:
        return list(points)
    is_closed = (abs(points[0][0] - points[-1][0]) < 1e-4 and abs(points[0][1] - points[-1][1]) < 1e-4)
    base_pts = points[:-1] if is_closed else list(points)
    area = signed_polygon_area(base_pts)
    is_ccw = area > 0.0
    if (clockwise and is_ccw) or (not clockwise and not is_ccw):
        base_pts = base_pts[::-1]
    if is_closed:
        base_pts.append(base_pts[0])
    return base_pts


def offset_polygon(points: List[Tuple[float, float]], offset_dist: float) -> List[Tuple[float, float]]:
    """
    Offset a 2D closed polygon by offset_dist along its edge normals.
    Positive offset_dist expands outward, negative shrinks inward.
    Uses miter intersection with miter limit to prevent corner spikes.
    """
    if len(points) < 3 or abs(offset_dist) < 1e-6:
        return list(points)

    is_closed = (abs(points[0][0] - points[-1][0]) < 1e-4 and abs(points[0][1] - points[-1][1]) < 1e-4)
    pts = points[:-1] if is_closed else list(points)
    n_pts = len(pts)
    if n_pts < 3:
        return list(points)

    area = signed_polygon_area(pts)
    is_ccw = area > 0.0

    normals = []
    edge_dirs = []
    for i in range(n_pts):
        p_curr = pts[i]
        p_next = pts[(i + 1) % n_pts]
        dx = p_next[0] - p_curr[0]
        dy = p_next[1] - p_curr[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / length, dy / length
        edge_dirs.append((ux, uy))
        if is_ccw:
            normals.append((uy, -ux))
        else:
            normals.append((-uy, ux))

    new_pts = []
    miter_limit = 2.5 * abs(offset_dist)

    for i in range(n_pts):
        prev_idx = (i - 1 + n_pts) % n_pts
        n1 = normals[prev_idx]
        u1 = edge_dirs[prev_idx]
        p1 = (pts[prev_idx][0] + offset_dist * n1[0], pts[prev_idx][1] + offset_dist * n1[1])

        n2 = normals[i]
        u2 = edge_dirs[i]
        p2 = (pts[i][0] + offset_dist * n2[0], pts[i][1] + offset_dist * n2[1])

        denom = u1[0] * u2[1] - u1[1] * u2[0]
        if abs(denom) < 1e-4:
            new_pt = (pts[i][0] + offset_dist * normals[i][0], pts[i][1] + offset_dist * normals[i][1])
        else:
            dp = (p2[0] - p1[0], p2[1] - p1[1])
            t = (dp[0] * u2[1] - dp[1] * u2[0]) / denom
            cand_x = p1[0] + t * u1[0]
            cand_y = p1[1] + t * u1[1]
            dist_from_orig = math.hypot(cand_x - pts[i][0], cand_y - pts[i][1])
            if dist_from_orig > miter_limit:
                new_pt = (pts[i][0] + offset_dist * normals[i][0], pts[i][1] + offset_dist * normals[i][1])
            else:
                new_pt = (cand_x, cand_y)

        new_pts.append(new_pt)

    if is_closed:
        new_pts.append(new_pts[0])
    return new_pts


def _calculate_z_passes(target_depth: float, max_step_down: float) -> List[float]:
    """Calculate negative Z cut levels for multi-pass step down."""
    depth = abs(target_depth)
    step = max(max_step_down, 0.05)
    passes: List[float] = []
    curr = 0.0
    while curr < depth:
        curr = min(curr + step, depth)
        passes.append(-curr)
    return passes


def _emit_safety_header(params: MachiningParams, drawing_data: DrawingIR) -> List[str]:
    """Generate Fanuc CNC program header with safety preamble and tool setup."""
    return [
        "%",
        f"O{params.program_number:04d} (VLM4CNC GENERATED CNC PROGRAM)",
        "(=======================================================)",
        f"( STOCK SIZE : {drawing_data.stock_width:.2f} x {drawing_data.stock_height:.2f} x {drawing_data.stock_thickness:.2f} mm )",
        f"( TOOL #{params.tool_number}   : Ø{params.tool_diameter:.3f} mm ENDMILL/DRILL | OFFSET H{params.tool_offset_h} )",
        f"( SPINDLE    : {params.spindle_rpm} RPM | FEED: {params.cut_feed:.1f} mm/min | PLUNGE: {params.plunge_feed:.1f} mm/min )",
        f"( SAFE Z     : {params.safe_z:.1f} mm | APPROACH Z: {params.approach_z:.1f} mm | CUT Z: {params.cut_depth_z:.1f} mm )",
        "(=======================================================)",
        "G21 (Units in millimeters)",
        "G90 (Absolute programming mode)",
        "G40 (Tool radius compensation OFF)",
        "G80 (Cancel canned cycles)",
        "G17 (XY circular interpolation plane)",
        "G49 (Tool length compensation cancel)",
        "G54 (Work coordinate system 1)",
        "G00 G91 G28 Z0.000 (Safe Z zero return)",
        "G90 (Absolute positioning)",
        f"T{params.tool_number} M06 (Tool change to Tool #{params.tool_number})",
        f"G43 H{params.tool_offset_h} Z{params.safe_z:.3f} (Tool length compensation)",
        f"M03 S{params.spindle_rpm} (Spindle ON clockwise)",
        "M08 (Coolant ON)",
        "G04 P1.5 (Dwell 1.5s for spindle to reach target speed)",
        "",
    ]


def _emit_drilling_cycles(drilled_holes: List[DrillHole], params: MachiningParams) -> List[str]:
    """Generate Fanuc canned drilling cycle (G81 or G83 with G98 safe retract plane)."""
    if not drilled_holes:
        return []

    lines: List[str] = [
        "(-------------------------------------------------------)",
        f"( OPERATION: DRILLING {len(drilled_holes)} HOLES )",
        "(-------------------------------------------------------)",
    ]

    first_hole = drilled_holes[0]
    lines.append(f"G00 X{first_hole.center.x:.3f} Y{first_hole.center.y:.3f}")
    lines.append(f"G00 Z{params.approach_z:.3f}")

    hole_depth = abs(first_hole.depth) if first_hole.depth > 0 else (abs(params.cut_depth_z) if abs(params.cut_depth_z) > 0 else 5.0)
    cycle_type = params.drilling_cycle.upper()

    if cycle_type == "G81":
        lines.append(
            f"G98 G81 X{first_hole.center.x:.3f} Y{first_hole.center.y:.3f} "
            f"Z-{hole_depth:.3f} R{params.approach_z:.3f} F{params.plunge_feed:.1f}"
        )
        for h in drilled_holes[1:]:
            lines.append(f"X{h.center.x:.3f} Y{h.center.y:.3f}")
    else:
        lines.append(
            f"G98 G83 X{first_hole.center.x:.3f} Y{first_hole.center.y:.3f} "
            f"Z-{hole_depth:.3f} R{params.approach_z:.3f} Q{params.peck_depth:.3f} F{params.plunge_feed:.1f}"
        )
        for h in drilled_holes[1:]:
            lines.append(f"X{h.center.x:.3f} Y{h.center.y:.3f}")

    lines.extend([
        "G80 (Cancel canned drilling cycle)",
        f"G00 Z{params.safe_z:.3f} (Retract to safe Z)",
        "",
    ])
    return lines


def _emit_circular_pocket_cycles(milled_holes: List[DrillHole], params: MachiningParams) -> List[str]:
    """Generate G03 circular pocket milling passes for holes wider than tool diameter."""
    if not milled_holes:
        return []

    lines: List[str] = []
    for hole_idx, hole in enumerate(milled_holes, start=1):
        r_cut = (hole.diameter - params.tool_diameter) / 2.0
        total_depth = abs(hole.depth) if hole.depth > 0 else (abs(params.cut_depth_z) if abs(params.cut_depth_z) > 0 else 5.0)
        z_levels_hole = _calculate_z_passes(total_depth, params.cut_depth_per_pass)

        radial_stepover = max(params.tool_diameter * 0.65, 0.5)
        if r_cut <= radial_stepover:
            pocket_radii = [r_cut]
        else:
            n_steps = max(int(math.ceil(r_cut / radial_stepover)), 1)
            pocket_radii = [(r_cut / n_steps) * i for i in range(1, n_steps + 1)]

        lines.extend([
            "(-------------------------------------------------------)",
            f"( OPERATION: CIRCULAR POCKET MILLING HOLE #{hole_idx} (Ø{hole.diameter:.2f}mm) )",
            f"( CENTER: X{hole.center.x:.3f} Y{hole.center.y:.3f} | DEPTH: -{total_depth:.3f}mm | PASSES: {len(z_levels_hole)} )",
            f"( FINAL RADIUS: {r_cut:.3f}mm | RADIAL RINGS: {len(pocket_radii)} )",
            "(-------------------------------------------------------)",
            f"G00 X{hole.center.x:.3f} Y{hole.center.y:.3f} (Rapid to hole center)",
            f"G00 Z{params.approach_z:.3f}",
        ])

        for pass_idx, target_z in enumerate(z_levels_hole, start=1):
            lines.append(f"(Hole Pass {pass_idx}/{len(z_levels_hole)} at Z={target_z:.3f})")
            lines.append(f"G01 Z{target_z:.3f} F{params.plunge_feed:.1f} (Plunge at center)")
            for r_ring in pocket_radii:
                lines.append(f"G01 X{hole.center.x + r_ring:.3f} Y{hole.center.y:.3f} F{params.cut_feed:.1f} (Move to ring radius {r_ring:.3f}mm)")
                lines.append(f"G03 X{hole.center.x - r_ring:.3f} Y{hole.center.y:.3f} I{-r_ring:.3f} J0.000 F{params.cut_feed:.1f} (Circle half 1)")
                lines.append(f"G03 X{hole.center.x + r_ring:.3f} Y{hole.center.y:.3f} I{r_ring:.3f} J0.000 F{params.cut_feed:.1f} (Circle half 2)")
            lines.append(f"G01 X{hole.center.x:.3f} Y{hole.center.y:.3f} F{params.cut_feed:.1f} (Return to center)")

        lines.extend([
            f"G00 Z{params.safe_z:.3f} (Retract to safe Z)",
            "",
        ])
    return lines


def _emit_slot_cycles(slots: List[SlotContour], params: MachiningParams) -> List[str]:
    """Generate multi-pass slot milling operations (centerline or expanding racetrack G02)."""
    if not slots:
        return []

    lines: List[str] = [
        "(-------------------------------------------------------)",
        f"( OPERATION: MILLING {len(slots)} INDEPENDENT SLOTS )",
        "(-------------------------------------------------------)",
    ]

    for slot_idx, slot in enumerate(slots, start=1):
        pts = slot.centerline_path
        if len(pts) < 2:
            continue

        total_depth = abs(slot.depth) if slot.depth > 0 else abs(params.cut_depth_z)
        if total_depth <= 0.0:
            total_depth = 5.0
        z_levels = _calculate_z_passes(total_depth, params.cut_depth_per_pass)

        dx = pts[1].x - pts[0].x
        dy = pts[1].y - pts[0].y
        length = math.hypot(dx, dy)
        can_expand = (
            len(pts) == 2
            and length > 1e-4
            and params.mill_slot_width
            and (slot.width > params.tool_diameter + 0.1)
        )

        if can_expand:
            ux = dx / length
            uy = dy / length
            nx = -uy
            ny = ux
            d_max = (slot.width - params.tool_diameter) / 2.0
            radial_stepover = max(params.tool_diameter * 0.6, 0.5)

            if d_max <= radial_stepover:
                offsets = [d_max]
            else:
                n_steps = max(int(math.ceil(d_max / radial_stepover)), 1)
                offsets = [(d_max / n_steps) * i for i in range(1, n_steps + 1)]

            lines.extend([
                "(-------------------------------------------------------)",
                f"( OPERATION: SLOT MILLING #{slot_idx} (Width: {slot.width:.2f}mm, Depth: -{total_depth:.2f}mm) )",
                f"( FROM: X{pts[0].x:.3f} Y{pts[0].y:.3f} TO: X{pts[1].x:.3f} Y{pts[1].y:.3f} )",
                f"( PASSES: {len(z_levels)} Z-levels | RACETRACK OFFSETS: {len(offsets)} )",
                "(-------------------------------------------------------)",
                f"G00 X{pts[0].x:.3f} Y{pts[0].y:.3f} (Rapid to slot start)",
                f"G00 Z{params.approach_z:.3f} (Rapid to approach clearance)",
            ])

            for pass_idx, target_z in enumerate(z_levels, start=1):
                lines.append(f"(Slot #{slot_idx} Pass {pass_idx}/{len(z_levels)} at Z={target_z:.3f})")
                lines.append(f"G01 Z{target_z:.3f} F{params.plunge_feed:.1f} (Plunge into material)")

                # Centerline pass
                lines.append(f"G01 X{pts[1].x:.3f} Y{pts[1].y:.3f} F{params.cut_feed:.1f} (Centerline pass)")
                lines.append(f"G01 X{pts[0].x:.3f} Y{pts[0].y:.3f} F{params.cut_feed:.1f}")

                # Expanding racetrack passes
                for off_idx, d in enumerate(offsets, start=1):
                    p1_left_x = pts[0].x + d * nx
                    p1_left_y = pts[0].y + d * ny
                    p2_left_x = pts[1].x + d * nx
                    p2_left_y = pts[1].y + d * ny
                    p2_right_x = pts[1].x - d * nx
                    p2_right_y = pts[1].y - d * ny
                    p1_right_x = pts[0].x - d * nx
                    p1_right_y = pts[0].y - d * ny
                    i_p2 = d * uy
                    j_p2 = -d * ux
                    i_p1 = -d * uy
                    j_p1 = d * ux

                    lines.append(f"G01 X{p1_left_x:.3f} Y{p1_left_y:.3f} F{params.cut_feed:.1f} (Offset {off_idx}/{len(offsets)} left flank)")
                    lines.append(f"G01 X{p2_left_x:.3f} Y{p2_left_y:.3f} F{params.cut_feed:.1f}")
                    lines.append(f"G02 X{p2_right_x:.3f} Y{p2_right_y:.3f} I{i_p2:.3f} J{j_p2:.3f} F{params.cut_feed:.1f} (End cap arc)")
                    lines.append(f"G01 X{p1_right_x:.3f} Y{p1_right_y:.3f} F{params.cut_feed:.1f} (Right flank)")
                    lines.append(f"G02 X{p1_left_x:.3f} Y{p1_left_y:.3f} I{i_p1:.3f} J{j_p1:.3f} F{params.cut_feed:.1f} (Start cap arc)")

                lines.append(f"G01 X{pts[0].x:.3f} Y{pts[0].y:.3f} F{params.cut_feed:.1f} (Return to centerline)")

                if pass_idx < len(z_levels):
                    lines.append(f"G00 Z{params.approach_z:.3f}")
                    lines.append(f"G00 X{pts[0].x:.3f} Y{pts[0].y:.3f}")

            lines.extend([
                f"G00 Z{params.safe_z:.3f} (Retract to safe Z)",
                "",
            ])
        else:
            lines.extend([
                "(-------------------------------------------------------)",
                f"( OPERATION: SLOT MILLING #{slot_idx} (Centerline, Width: {slot.width:.2f}mm, Depth: -{total_depth:.2f}mm) )",
                f"( PASSES: {len(z_levels)} Z-levels )",
                "(-------------------------------------------------------)",
                f"G00 X{pts[0].x:.3f} Y{pts[0].y:.3f} (Rapid to slot start)",
                f"G00 Z{params.approach_z:.3f} (Rapid to approach clearance)",
            ])

            for pass_idx, target_z in enumerate(z_levels, start=1):
                lines.append(f"(Slot #{slot_idx} Pass {pass_idx}/{len(z_levels)} at Z={target_z:.3f})")
                lines.append(f"G01 Z{target_z:.3f} F{params.plunge_feed:.1f}")

                for p in pts[1:]:
                    lines.append(f"G01 X{p.x:.3f} Y{p.y:.3f} F{params.cut_feed:.1f}")

                if pass_idx < len(z_levels):
                    lines.append(f"G00 Z{params.approach_z:.3f}")
                    lines.append(f"G00 X{pts[0].x:.3f} Y{pts[0].y:.3f}")

            lines.extend([
                f"G00 Z{params.safe_z:.3f} (Retract to safe Z)",
                "",
            ])
    return lines


def _emit_contour_cycle(contour_pts: Optional[List[Point2D]], params: MachiningParams) -> List[str]:
    """Generate outer profile contour milling passes with tangential air lead-in/lead-out."""
    if not contour_pts or len(contour_pts) < 3:
        return []

    total_depth = abs(params.cut_depth_z) if abs(params.cut_depth_z) > 0 else 5.0
    z_levels_contour = _calculate_z_passes(total_depth, params.cut_depth_per_pass)

    tool_radius = params.tool_diameter / 2.0
    raw_pts = [(p.x, p.y) for p in contour_pts]
    cutter_comp = params.cutter_comp.upper()

    if cutter_comp == "CAM" and tool_radius > 0:
        cut_pts = offset_polygon(raw_pts, tool_radius)
        cut_pts = ensure_polygon_winding(cut_pts, clockwise=True)
        use_g41 = False
    elif cutter_comp in ("G41", "G42"):
        cut_pts = ensure_polygon_winding(raw_pts, clockwise=True)
        use_g41 = True
    else:
        cut_pts = list(raw_pts)
        use_g41 = False

    first_pt = cut_pts[0]
    second_pt = cut_pts[1] if len(cut_pts) > 1 else first_pt

    dx = second_pt[0] - first_pt[0]
    dy = second_pt[1] - first_pt[1]
    edge_len = math.hypot(dx, dy)
    ux = dx / edge_len if edge_len > 1e-6 else 1.0
    uy = dy / edge_len if edge_len > 1e-6 else 0.0

    last_pt = cut_pts[-1]
    penult_pt = cut_pts[-2] if len(cut_pts) >= 2 else first_pt
    ldx = last_pt[0] - penult_pt[0]
    ldy = last_pt[1] - penult_pt[1]
    l_len = math.hypot(ldx, ldy)
    lux = ldx / l_len if l_len > 1e-6 else 1.0
    luy = ldy / l_len if l_len > 1e-6 else 0.0

    lead_dist = max(2.0, min(5.0, params.tool_diameter * 0.75))

    if use_g41:
        nx = -uy
        ny = ux
        lead_in_x = first_pt[0] - ux * lead_dist + nx * lead_dist
        lead_in_y = first_pt[1] - uy * lead_dist + ny * lead_dist
        lead_out_x = last_pt[0] + lux * lead_dist + (-luy) * lead_dist
        lead_out_y = last_pt[1] + luy * lead_dist + (lux) * lead_dist
    else:
        lead_in_x = first_pt[0] - ux * lead_dist
        lead_in_y = first_pt[1] - uy * lead_dist
        lead_out_x = last_pt[0] + lux * lead_dist
        lead_out_y = last_pt[1] + luy * lead_dist

    lines = [
        "(-------------------------------------------------------)",
        f"( OPERATION: PROFILE MILLING OUTER CONTOUR ({len(cut_pts)} POINTS) )",
        f"( CUT DEPTH Z: -{total_depth:.3f} mm | PASSES: {len(z_levels_contour)} | COMP: {cutter_comp} )",
        "(-------------------------------------------------------)",
        f"G00 X{lead_in_x:.3f} Y{lead_in_y:.3f} (Rapid to air lead-in point)",
        f"G00 Z{params.approach_z:.3f} (Rapid to approach clearance)",
    ]

    for pass_idx, target_z in enumerate(z_levels_contour, start=1):
        lines.append(f"(Contour Pass {pass_idx}/{len(z_levels_contour)} at Z={target_z:.3f})")
        lines.append(f"G01 Z{target_z:.3f} F{params.plunge_feed:.1f} (Plunge in free air)")

        if use_g41:
            lines.append(f"G01 {cutter_comp} D{params.cutter_offset_d} X{first_pt[0]:.3f} Y{first_pt[1]:.3f} F{params.cut_feed:.1f} (Lead-in with {cutter_comp})")
        else:
            lines.append(f"G01 X{first_pt[0]:.3f} Y{first_pt[1]:.3f} F{params.cut_feed:.1f} (Tangential lead-in)")

        for pt in cut_pts[1:]:
            lines.append(f"G01 X{pt[0]:.3f} Y{pt[1]:.3f} F{params.cut_feed:.1f}")

        if use_g41:
            lines.append(f"G01 G40 X{lead_out_x:.3f} Y{lead_out_y:.3f} F{params.cut_feed:.1f} (Lead-out with G40)")
        else:
            lines.append(f"G01 X{lead_out_x:.3f} Y{lead_out_y:.3f} F{params.cut_feed:.1f} (Tangential air lead-out)")

        if pass_idx < len(z_levels_contour):
            lines.append(f"G00 Z{params.approach_z:.3f}")
            lines.append(f"G00 X{lead_in_x:.3f} Y{lead_in_y:.3f}")

    lines.extend([
        f"G00 Z{params.safe_z:.3f} (Retract to safe clearance)",
        "",
    ])
    return lines


def _emit_footer(params: MachiningParams) -> List[str]:
    """Generate program footer with safe parking and end of program."""
    return [
        "(-------------------------------------------------------)",
        "( PROGRAM TERMINATION                                   )",
        "(-------------------------------------------------------)",
        "M09 (Coolant OFF)",
        "M05 (Spindle stop)",
        f"G00 Z{params.safe_z:.3f} (Retract to safe clearance)",
        "G00 G91 G28 Z0.000 (Safe Z zero return to machine home)",
        "G28 X0.000 Y0.000 (Return to XY machine home)",
        "G90 (Restore absolute mode)",
        "M30 (End of program)",
        "%",
    ]


def generate_gcode(
    drawing_data: DrawingIR,
    machining_params: Optional[Union[MachiningParams, Dict[str, Any]]] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate CNC G-Code program from DrawingIR and machining parameters.

    Args:
        drawing_data: The DrawingIR containing stock dimensions, holes, and slots.
        machining_params: MachiningParams model or dictionary of machining settings.
        output_path: Target path to write .nc or .gcode file.

    Returns:
        The generated G-Code program string.
    """
    if machining_params is None:
        params = MachiningParams()
    elif isinstance(machining_params, MachiningParams):
        params = machining_params
    elif isinstance(machining_params, dict):
        d = dict(machining_params)
        if "feedrate_xy" in d and "cut_feed" not in d:
            d["cut_feed"] = d["feedrate_xy"]
        if "spindle_speed" in d and "spindle_rpm" not in d:
            d["spindle_rpm"] = d["spindle_speed"]
        params = MachiningParams.model_validate(d)
    else:
        raise TypeError(f"machining_params must be MachiningParams or dict, got {type(machining_params).__name__}")

    logger.info(
        f"Generating G-Code: stock={drawing_data.stock_width:.1f}x{drawing_data.stock_height:.1f}mm, "
        f"holes={len(drawing_data.holes)}, slots={len(drawing_data.slots)}, tool=Ø{params.tool_diameter:.2f}mm"
    )

    lines: List[str] = []

    # 1. Safety Header
    lines.extend(_emit_safety_header(params, drawing_data))

    # 2. Holes (Drilling cycles & Circular Pocket Milling)
    if drawing_data.holes:
        milled_holes = [h for h in drawing_data.holes if (h.diameter > params.tool_diameter + 0.1 and params.mill_large_holes)]
        drilled_holes = [h for h in drawing_data.holes if h not in milled_holes]

        lines.extend(_emit_drilling_cycles(drilled_holes, params))
        lines.extend(_emit_circular_pocket_cycles(milled_holes, params))

    # 3. Slots
    if drawing_data.slots:
        lines.extend(_emit_slot_cycles(drawing_data.slots, params))

    # 4. Profile Outer Contour
    mill_outer_contour = bool(params.get("mill_outer_contour", True))
    if mill_outer_contour:
        contour_pts = (
            drawing_data.get_effective_outer_contour()
            if hasattr(drawing_data, "get_effective_outer_contour")
            else getattr(drawing_data, "outer_contour", None)
        )
        lines.extend(_emit_contour_cycle(contour_pts, params))

    # 5. Program Footer
    lines.extend(_emit_footer(params))

    program_text = "\n".join(lines) + "\n"

    if output_path is not None:
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

    def generate(
        self,
        drawing_data: DrawingIR,
        machining_params: Optional[Union[MachiningParams, Dict[str, Any]]] = None,
        output_path: Optional[str] = None,
    ) -> str:
        if machining_params is None:
            machining_params = MachiningParams(
                tool_diameter=self.settings.tool_diameter,
                cut_feed=self.settings.feed_rate,
                plunge_feed=self.settings.plunge_rate,
                spindle_rpm=self.settings.spindle_speed,
                safe_z=self.settings.safe_z,
                cut_depth_z=self.settings.cut_depth,
                cut_depth_per_pass=self.settings.pass_depth,
            )
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

