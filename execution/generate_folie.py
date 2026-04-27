#!/usr/bin/env python3
"""
Tschumi Folie Generator — emits .glb geometry compliant with the grammar in
../references/folie-grammar.md. See ../SKILL.md for usage.
"""

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import List

import numpy as np
import trimesh
from trimesh.transformations import (
    rotation_matrix,
    translation_matrix,
    concatenate_matrices,
)


CUBE_SIZE = 10.8
SUB = 3
SUB_CELL = CUBE_SIZE / SUB
FRAME_SECTION = 0.12
PANEL_THICKNESS = 0.05
GRID_SPACING = 120.0
TSCHUMI_RED_HEX = "#C8102E"
LOD_DEFAULT = 300
DECK_THICKNESS = 0.1
RAIL_HEIGHT_M = 1.0
MID_RAIL_HEIGHT_M = 0.5


# ---------------------------------------------------------------------------
# Low-level geometry helpers

def hex_to_rgba(hex_str: str) -> np.ndarray:
    h = hex_str.lstrip("#")
    if len(h) == 6:
        return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255], dtype=np.uint8)
    if len(h) == 8:
        return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4, 6)], dtype=np.uint8)
    raise ValueError(f"Invalid hex color: {hex_str}")


def box_section(p1, p2, section=FRAME_SECTION):
    """Steel box section between p1 and p2."""
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    direction = p2 - p1
    length = np.linalg.norm(direction)
    if length < 1e-6:
        return None
    box = trimesh.creation.box(extents=[section, section, length])
    box.apply_translation([0, 0, length / 2])
    z = np.array([0.0, 0.0, 1.0])
    d = direction / length
    if not np.allclose(d, z):
        if np.allclose(d, -z):
            R = rotation_matrix(math.pi, [1, 0, 0])
        else:
            axis = np.cross(z, d)
            axis = axis / np.linalg.norm(axis)
            angle = math.acos(np.clip(np.dot(z, d), -1, 1))
            R = rotation_matrix(angle, axis)
        box.apply_transform(R)
    box.apply_translation(p1)
    return box


# ---------------------------------------------------------------------------
# Cube + subdivision frame

def cube_corners(origin, size):
    ox, oy, oz = origin
    s = size
    return np.array(
        [
            [ox, oy, oz],
            [ox + s, oy, oz],
            [ox, oy + s, oz],
            [ox + s, oy + s, oz],
            [ox, oy, oz + s],
            [ox + s, oy, oz + s],
            [ox, oy + s, oz + s],
            [ox + s, oy + s, oz + s],
        ]
    )


CUBE_EDGE_PAIRS = [
    (0, 1), (1, 3), (3, 2), (2, 0),
    (4, 5), (5, 7), (7, 6), (6, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]


def make_cube_frame(origin, size, section, absent_edges=None):
    absent = set(absent_edges or [])
    corners = cube_corners(origin, size)
    meshes = []
    for i, (a, b) in enumerate(CUBE_EDGE_PAIRS):
        if i in absent:
            continue
        m = box_section(corners[a], corners[b], section)
        if m is not None:
            meshes.append(m)
    return meshes


def make_subdivision_frame(origin, size, subdivisions, section):
    """Full 3x3x3 (by default) grid skeleton. Outlines every sub-cube, not just
    the outer faces: adds interior horizontal crossbars at each intermediate
    z-level plus interior vertical columns at sub-grid intersection points."""
    ox, oy, oz = origin
    s = size
    n = subdivisions
    meshes = []
    offsets = [s * i / n for i in range(n + 1)]  # [0, s/3, 2s/3, s]
    mids = offsets[1:-1]                          # intermediate positions only

    # Horizontal rings at each intermediate z-level (perimeter)
    for z in (oz + m for m in mids):
        perim = [
            ((ox, oy, z), (ox + s, oy, z)),
            ((ox + s, oy, z), (ox + s, oy + s, z)),
            ((ox + s, oy + s, z), (ox, oy + s, z)),
            ((ox, oy + s, z), (ox, oy, z)),
        ]
        for a, b in perim:
            m = box_section(a, b, section)
            if m: meshes.append(m)

    # Vertical members on the 4 outer vertical faces at intermediate positions
    for t in mids:
        for fx, fy in [(ox + t, oy), (ox + t, oy + s), (ox, oy + t), (ox + s, oy + t)]:
            m = box_section((fx, fy, oz), (fx, fy, oz + s), section)
            if m: meshes.append(m)

    # Grid on top and bottom faces
    for t in mids:
        for z in (oz, oz + s):
            m = box_section((ox, oy + t, z), (ox + s, oy + t, z), section)
            if m: meshes.append(m)
            m = box_section((ox + t, oy, z), (ox + t, oy + s, z), section)
            if m: meshes.append(m)

    # Interior crossbars at each intermediate z-level — the members threading
    # through the cube interior, so every sub-cube gets outlined.
    for z in (oz + m for m in mids):
        for t in mids:
            # X-direction bar at y=t (full span)
            m = box_section((ox, oy + t, z), (ox + s, oy + t, z), section)
            if m: meshes.append(m)
            # Y-direction bar at x=t (full span)
            m = box_section((ox + t, oy, z), (ox + t, oy + s, z), section)
            if m: meshes.append(m)

    # Interior vertical columns at sub-grid intersections
    for tx in mids:
        for ty in mids:
            m = box_section((ox + tx, oy + ty, oz), (ox + tx, oy + ty, oz + s), section)
            if m: meshes.append(m)

    return meshes


def make_solid_cell(cell_ijk, cube_origin, sub_size, offset_m=None):
    """LOD 200: monolithic solid cube at a sub-grid cell."""
    i, j, k = cell_ijk
    ox, oy, oz = cube_origin
    x = ox + i * sub_size
    y = oy + j * sub_size
    z = oz + k * sub_size
    if offset_m:
        x += offset_m[0]; y += offset_m[1]; z += offset_m[2]
    inset = 0.002
    e = sub_size - 2 * inset
    box = trimesh.creation.box(extents=[e, e, e])
    box.apply_translation([x + sub_size / 2, y + sub_size / 2, z + sub_size / 2])
    return box


def make_solid_cells_panels(solid_cells, cube_origin, sub_size, panel_thickness=0.05, inset=0.08):
    """LOD 300: for a set of solid cells, render only the outer boundary as panels
    (dedupe faces shared with adjacent solid cells), inset from the frame so the frame
    is visible around each panel."""
    cells = set(tuple(c) for c in solid_cells)
    ox, oy, oz = cube_origin
    panels = []
    pw = sub_size - 2 * inset
    for (i, j, k) in cells:
        x0 = ox + i * sub_size
        y0 = oy + j * sub_size
        z0 = oz + k * sub_size
        cx = x0 + sub_size / 2
        cy = y0 + sub_size / 2
        cz = z0 + sub_size / 2
        if (i - 1, j, k) not in cells:
            p = trimesh.creation.box(extents=[panel_thickness, pw, pw])
            p.apply_translation([x0 + inset, cy, cz]); panels.append(p)
        if (i + 1, j, k) not in cells:
            p = trimesh.creation.box(extents=[panel_thickness, pw, pw])
            p.apply_translation([x0 + sub_size - inset, cy, cz]); panels.append(p)
        if (i, j - 1, k) not in cells:
            p = trimesh.creation.box(extents=[pw, panel_thickness, pw])
            p.apply_translation([cx, y0 + inset, cz]); panels.append(p)
        if (i, j + 1, k) not in cells:
            p = trimesh.creation.box(extents=[pw, panel_thickness, pw])
            p.apply_translation([cx, y0 + sub_size - inset, cz]); panels.append(p)
        if (i, j, k - 1) not in cells:
            p = trimesh.creation.box(extents=[pw, pw, panel_thickness])
            p.apply_translation([cx, cy, z0 + inset]); panels.append(p)
        if (i, j, k + 1) not in cells:
            p = trimesh.creation.box(extents=[pw, pw, panel_thickness])
            p.apply_translation([cx, cy, z0 + sub_size - inset]); panels.append(p)
    return panels


def _balustrade_segment(p_start, p_end, mid_rail=True, post_spacing=1.5,
                         rail_h=RAIL_HEIGHT_M, mid_h=MID_RAIL_HEIGHT_M):
    """Build a balustrade segment between two horizontal points."""
    p_start = np.asarray(p_start, dtype=float)
    p_end = np.asarray(p_end, dtype=float)
    up = np.array([0.0, 0.0, 1.0])
    meshes = []
    # Top rail
    tr = box_section(p_start + up * rail_h, p_end + up * rail_h, 0.05)
    if tr: meshes.append(tr)
    if mid_rail:
        mr = box_section(p_start + up * mid_h, p_end + up * mid_h, 0.04)
        if mr: meshes.append(mr)
    length = float(np.linalg.norm(p_end - p_start))
    n_posts = max(2, int(length / post_spacing) + 1)
    for k in range(n_posts):
        t = k / (n_posts - 1)
        base = p_start + (p_end - p_start) * t
        top = base + up * rail_h
        post = box_section(base, top, 0.06)
        if post: meshes.append(post)
    return meshes


def make_platform(cells_2d, level, cube_origin, sub_size,
                   balustrade=True, mid_rail=True, open_sides=None,
                   cutout_cells=None, solid_cells_3d=None):
    """Platform: one or more adjacent cells at subdivision Z level.
    `cells_2d` is a list of [col, row] pairs.
    `level` is integer 1..3 corresponding to z = level * sub_size.
    `open_sides` can specify edges to leave without balustrade (for stair/ramp entry).
    `cutout_cells` lists cells that are part of the platform's connectivity
    (so balustrades don't appear on shared edges with them) but whose deck plate
    is NOT rendered — use when another primitive (e.g. stair_helical landing)
    fills that cell with custom geometry.
    `solid_cells_3d` lists the cube's solid cells (as [col, row, layer]); used
    to skip balustrade segments that coincide with a solid cube wall. §R3."""
    ox, oy, oz = cube_origin
    z = oz + level * sub_size
    meshes = []
    cells = [tuple(c) for c in cells_2d]
    cutouts = set(tuple(c) for c in (cutout_cells or []))
    cell_set = set(cells) | cutouts
    render_cells = [c for c in cells if c not in cutouts]

    # Deck per cell (skip cutouts — another primitive fills them)
    for (col, row) in render_cells:
        x0 = ox + col * sub_size
        y0 = oy + row * sub_size
        plate = trimesh.creation.box(
            extents=[sub_size - 0.02, sub_size - 0.02, DECK_THICKNESS]
        )
        plate.apply_translation([x0 + sub_size / 2, y0 + sub_size / 2, z - DECK_THICKNESS / 2])
        meshes.append(plate)

    if not balustrade:
        return meshes

    # open_sides entries can be either a label string ("x+") or a per-cell
    # [col, row, label] list (from the autofix) — normalise to hashable tuples.
    _os = set()
    for entry in (open_sides or []):
        if isinstance(entry, str):
            _os.add(entry)
        elif isinstance(entry, (list, tuple)) and len(entry) == 3:
            _os.add((int(entry[0]), int(entry[1]), str(entry[2])))
    open_sides = _os
    # §R3: skip the balustrade on an edge when a solid cell at the same level
    # already provides a wall along that edge. Keep rails on open cube faces —
    # those are fall hazards that need protection.
    solid_set = set(tuple(c) for c in (solid_cells_3d or []))

    def _edge_has_wall(c, r, label):
        if label == "x-":
            adj = (c - 1, r, level)
        elif label == "x+":
            adj = (c + 1, r, level)
        elif label == "y-":
            adj = (c, r - 1, level)
        else:  # y+
            adj = (c, r + 1, level)
        return adj in solid_set

    for (col, row) in render_cells:
        x0 = ox + col * sub_size
        y0 = oy + row * sub_size
        x1 = x0 + sub_size
        y1 = y0 + sub_size
        edges = []
        if (col - 1, row) not in cell_set:
            edges.append(("x-", (x0, y0, z), (x0, y1, z)))
        if (col + 1, row) not in cell_set:
            edges.append(("x+", (x1, y0, z), (x1, y1, z)))
        if (col, row - 1) not in cell_set:
            edges.append(("y-", (x0, y0, z), (x1, y0, z)))
        if (col, row + 1) not in cell_set:
            edges.append(("y+", (x0, y1, z), (x1, y1, z)))
        for (label, p1, p2) in edges:
            if (col, row, label) in open_sides or label in open_sides:
                continue
            if _edge_has_wall(col, row, label):
                continue
            meshes.extend(_balustrade_segment(p1, p2, mid_rail=mid_rail))
    return meshes


def make_landing(center_xyz, size=2.4, balustrade=True, mid_rail=True, open_direction=None):
    """Small deck landing at ramp/stair terminus. `open_direction` is a 3-vector indicating
    the arrival side (which should be left open for access)."""
    cx, cy, cz = center_xyz
    meshes = []
    plate = trimesh.creation.box(extents=[size, size, DECK_THICKNESS])
    plate.apply_translation([cx, cy, cz - DECK_THICKNESS / 2])
    meshes.append(plate)
    if balustrade:
        half = size / 2
        corners = [
            (cx - half, cy - half, cz),  # SW
            (cx + half, cy - half, cz),  # SE
            (cx + half, cy + half, cz),  # NE
            (cx - half, cy + half, cz),  # NW
        ]
        edges = [
            ("y-", corners[0], corners[1]),  # south
            ("x+", corners[1], corners[2]),  # east
            ("y+", corners[2], corners[3]),  # north
            ("x-", corners[3], corners[0]),  # west
        ]
        skip_label = None
        if open_direction is not None:
            dx, dy = open_direction[0], open_direction[1]
            if abs(dx) >= abs(dy):
                skip_label = "x+" if dx > 0 else "x-"
            else:
                skip_label = "y+" if dy > 0 else "y-"
        for (label, p1, p2) in edges:
            if label == skip_label:
                continue
            meshes.extend(_balustrade_segment(p1, p2, mid_rail=mid_rail))
    return meshes


# ---------------------------------------------------------------------------
# Attachment builders

def _xy_yaw(direction):
    dx, dy = direction[0], direction[1]
    if abs(dx) + abs(dy) < 1e-9:
        return 0.0
    return math.atan2(dy, dx)


def make_ramp(anchor, direction, length_m, width_m, tilt_deg,
               balustrade=True, mid_rail=True, landing=False, landing_size=2.4):
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    yaw = _xy_yaw(direction)
    tilt_rad = math.radians(tilt_deg)

    R_tilt = rotation_matrix(-tilt_rad, [0, 1, 0])
    R_yaw = rotation_matrix(yaw, [0, 0, 1])
    T = translation_matrix(anchor)
    M = concatenate_matrices(T, R_yaw, R_tilt)

    slab_thickness = 0.15
    slab = trimesh.creation.box(extents=[length_m, width_m, slab_thickness])
    slab.apply_translation([length_m / 2, 0, -slab_thickness / 2])
    slab.apply_transform(M)
    meshes = [slab]

    for side in [-1, 1]:
        y = side * width_m / 2
        p_start = (M @ np.array([0, y, -slab_thickness, 1]))[:3]
        p_end = (M @ np.array([length_m, y, -slab_thickness, 1]))[:3]
        m = box_section(p_start, p_end, 0.1)
        if m: meshes.append(m)

    if balustrade:
        rail_h = RAIL_HEIGHT_M
        mid_h = MID_RAIL_HEIGHT_M
        for side in [-1, 1]:
            y = side * width_m / 2
            b0 = (M @ np.array([0, y, 0, 1]))[:3]
            b1 = (M @ np.array([length_m, y, 0, 1]))[:3]
            t0 = (M @ np.array([0, y, rail_h, 1]))[:3]
            t1 = (M @ np.array([length_m, y, rail_h, 1]))[:3]
            rail = box_section(t0, t1, 0.05)
            if rail: meshes.append(rail)
            if mid_rail:
                m0 = (M @ np.array([0, y, mid_h, 1]))[:3]
                m1 = (M @ np.array([length_m, y, mid_h, 1]))[:3]
                mr = box_section(m0, m1, 0.04)
                if mr: meshes.append(mr)
            n_posts = max(2, int(length_m / 1.5) + 1)
            for k in range(n_posts):
                tt = k / (n_posts - 1)
                p_bot = b0 + (b1 - b0) * tt
                p_top = t0 + (t1 - t0) * tt
                post = box_section(p_bot, p_top, 0.04)
                if post: meshes.append(post)

    if landing:
        # Landing at the upper (far) end of the ramp
        top_end = (M @ np.array([length_m, 0, 0, 1]))[:3]
        # Push landing slightly forward from ramp terminus
        forward = np.array([direction[0], direction[1], 0.0])
        n = np.linalg.norm(forward)
        if n > 1e-9:
            forward = forward / n
        landing_center = top_end + forward * (landing_size / 2)
        # Open side = direction FROM which the ramp approaches (reverse direction)
        meshes.extend(
            make_landing(landing_center, size=landing_size, balustrade=balustrade,
                         mid_rail=mid_rail, open_direction=[-forward[0], -forward[1], 0])
        )
    return meshes


def make_stair_cantilever(
    anchor, direction, steps, width_m, step_rise_m=0.30, step_run_m=0.30,
    balustrade=True, mid_rail=True, landing=False, landing_size=2.4
):
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    d_h = direction.copy(); d_h[2] = 0
    n = np.linalg.norm(d_h)
    d_h = np.array([1.0, 0.0, 0.0]) if n < 1e-9 else d_h / n
    perp = np.array([-d_h[1], d_h[0], 0.0])
    up = np.array([0.0, 0.0, 1.0])

    meshes = []
    yaw = math.atan2(d_h[1], d_h[0])
    R = rotation_matrix(yaw, [0, 0, 1])

    for i in range(steps):
        center = anchor + d_h * (i * step_run_m + step_run_m / 2) + up * (
            i * step_rise_m + step_rise_m / 2
        )
        tread = trimesh.creation.box(extents=[step_run_m, width_m, 0.05])
        tread.apply_transform(R)
        tread.apply_translation(center)
        meshes.append(tread)

    for side in [-1, 1]:
        side_off = perp * (width_m / 2 * side)
        start = anchor + side_off
        end = anchor + side_off + d_h * (steps * step_run_m) + up * (steps * step_rise_m)
        stringer = box_section(start, end, 0.1)
        if stringer: meshes.append(stringer)
        if balustrade:
            rail_start = start + up * RAIL_HEIGHT_M
            rail_end = end + up * RAIL_HEIGHT_M
            rail = box_section(rail_start, rail_end, 0.05)
            if rail: meshes.append(rail)
            if mid_rail:
                mr_start = start + up * MID_RAIL_HEIGHT_M
                mr_end = end + up * MID_RAIL_HEIGHT_M
                mr = box_section(mr_start, mr_end, 0.04)
                if mr: meshes.append(mr)
            n_posts = max(2, steps // 3 + 1)
            for k in range(n_posts):
                t = k / (n_posts - 1)
                p_b = start + (end - start) * t
                p_t = rail_start + (rail_end - rail_start) * t
                post = box_section(p_b, p_t, 0.04)
                if post: meshes.append(post)

    if landing:
        top_center = anchor + d_h * (steps * step_run_m) + up * (steps * step_rise_m)
        landing_center = top_center + d_h * (landing_size / 2)
        meshes.extend(
            make_landing(landing_center, size=landing_size, balustrade=balustrade,
                         mid_rail=mid_rail, open_direction=[-d_h[0], -d_h[1], 0])
        )
    return meshes


def _make_pac_man_deck(axis_xy, top_z, outer_radius, tongue_angle_rad,
                        cell_size=3.6, tongue_width_deg=90, thickness=0.1,
                        balustrade=True, mid_rail=True):
    """Landing deck at helical top: a `cell_size` square minus a 3/4 annular sector
    of radius `outer_radius + 0.1`. The remaining 1/4 'tongue' points toward
    `tongue_angle_rad` and is the only connection between the helical's last tread
    and the surrounding deck. Built with shapely + trimesh.extrude_polygon.

    If `balustrade=True`, a fall-protection rail is drawn along the 3/4 arc at
    the hole's outer radius. The rail is OPEN where the tongue meets it (i.e.
    the rail does not cross the tongue), so a walker stepping off the last
    tread onto the tongue is not blocked. (§R2 / §R4 — every fall hazard gets
    a rail except where access is provided.)"""
    from shapely.geometry import Polygon
    cx, cy = axis_xy
    half = cell_size / 2
    r_cut = outer_radius + 0.1
    tongue_half = math.radians(tongue_width_deg / 2)
    arc_span = 2 * math.pi - 2 * tongue_half
    # Cutout polygon: pac-man shape, axis + 3/4 arc
    n_arc = 48
    cutout = [(cx, cy)]
    arc_start = tongue_angle_rad + tongue_half
    arc_pts = []
    for i in range(n_arc + 1):
        a = arc_start + arc_span * i / n_arc
        arc_pts.append((cx + r_cut * math.cos(a), cy + r_cut * math.sin(a)))
        cutout.append(arc_pts[-1])
    cutout.append((cx, cy))
    square = Polygon([(cx - half, cy - half), (cx + half, cy - half),
                       (cx + half, cy + half), (cx - half, cy + half)])
    deck_poly = square.difference(Polygon(cutout))
    if deck_poly.is_empty:
        return []
    mesh = trimesh.creation.extrude_polygon(deck_poly, height=thickness)
    mesh.apply_translation([0, 0, top_z - thickness])
    meshes = [mesh]

    # Hole-perimeter balustrade — runs along the 3/4 arc on the deck side, at
    # the same radius as the cutout. Stops cleanly at the tongue's two flank
    # edges. The top rail and mid rail FOLLOW the arc smoothly (one short box
    # section per fine tessellation segment), so the rail reads as round —
    # matching the shape of the hole in the deck. Posts are sampled separately
    # at the project's default 1.5 m spacing so post count remains consistent
    # with platform / ramp / stair railings.
    if balustrade:
        arc_length = r_cut * arc_span
        n_rail = 48                              # rail tessellation — smooth curve
        n_posts = max(2, int(arc_length / 1.5) + 1)

        def _arc_pt(t, z=top_z):
            a = arc_start + arc_span * t
            return np.array([cx + r_cut * math.cos(a),
                             cy + r_cut * math.sin(a),
                             z])

        # Top + mid rails: piecewise-straight box sections along the fine arc.
        for i in range(n_rail):
            t0, t1 = i / n_rail, (i + 1) / n_rail
            top0 = _arc_pt(t0, top_z + RAIL_HEIGHT_M)
            top1 = _arc_pt(t1, top_z + RAIL_HEIGHT_M)
            seg = box_section(top0, top1, 0.05)
            if seg: meshes.append(seg)
            if mid_rail:
                m0 = _arc_pt(t0, top_z + MID_RAIL_HEIGHT_M)
                m1 = _arc_pt(t1, top_z + MID_RAIL_HEIGHT_M)
                seg = box_section(m0, m1, 0.04)
                if seg: meshes.append(seg)

        # Posts at 1.5 m intervals.
        for k in range(n_posts):
            t = k / (n_posts - 1)
            base = _arc_pt(t, top_z)
            top = _arc_pt(t, top_z + RAIL_HEIGHT_M)
            post = box_section(base, top, 0.06)
            if post: meshes.append(post)
    return meshes


def make_stair_helical(anchor, top_z_m, radius_m=1.2, revolutions=None,
                        clockwise=True, balustrade=True, mid_rail=True,
                        central_post=True, step_rise_m=0.18, landing=False):
    """Helical / spiral staircase wrapping a vertical axis.

    anchor: [x, y, z_bottom] — the axis base.
    top_z_m: absolute z of the axis top (must be supported: platform, cube top, or ground).
    radius_m: outer radius (inner = fixed central post ~0.15 m).
    revolutions: number of full turns; if None, defaults to one revolution per 3.6 m of rise.
    clockwise: winding direction viewed from above.
    step_rise_m: vertical gain per step (fixed 0.18 m by convention).

    Signature Villette move (Belvedere folie). Counts as a single attachment regardless of
    rise, so one helical stair can do ground→L3 where stair_cantilever cannot.
    """
    anchor = np.asarray(anchor, dtype=float)
    cx, cy, z_bottom = float(anchor[0]), float(anchor[1]), float(anchor[2])
    total_rise = top_z_m - z_bottom
    if total_rise <= 0.01:
        return []
    n_steps = max(1, int(round(total_rise / step_rise_m)))
    dz = total_rise / n_steps
    if revolutions is None:
        revolutions = max(0.5, total_rise / 3.6)
    total_angle = revolutions * 2 * math.pi
    if clockwise:
        total_angle = -total_angle
    d_angle = total_angle / n_steps
    r_inner = 0.15
    r_outer = float(radius_m)
    tread_thk = 0.05
    sub = 4  # angular subdivisions per tread

    meshes = []

    # Central post — simple vertical cylinder
    if central_post:
        post_h = total_rise
        post_cyl = trimesh.creation.cylinder(radius=r_inner, height=post_h, sections=16)
        post_cyl.apply_translation([cx, cy, z_bottom + post_h / 2])
        meshes.append(post_cyl)

    # Treads — each an annular sector built from vertices
    for i in range(n_steps):
        z_top = z_bottom + (i + 1) * dz
        a_start = i * d_angle
        a_end = (i + 1) * d_angle
        verts_top = []
        verts_bot = []
        for j in range(sub + 1):
            a = a_start + (a_end - a_start) * (j / sub)
            co, si = math.cos(a), math.sin(a)
            verts_top.append([cx + r_inner * co, cy + r_inner * si, z_top])
            verts_top.append([cx + r_outer * co, cy + r_outer * si, z_top])
            verts_bot.append([cx + r_inner * co, cy + r_inner * si, z_top - tread_thk])
            verts_bot.append([cx + r_outer * co, cy + r_outer * si, z_top - tread_thk])
        all_verts = verts_top + verts_bot
        faces = []
        off = 2 * (sub + 1)
        for j in range(sub):
            t_i, t_o = 2 * j, 2 * j + 1
            t_i2, t_o2 = 2 * (j + 1), 2 * (j + 1) + 1
            b_i, b_o = off + 2 * j, off + 2 * j + 1
            b_i2, b_o2 = off + 2 * (j + 1), off + 2 * (j + 1) + 1
            # Top
            faces.append([t_i, t_i2, t_o]); faces.append([t_o, t_i2, t_o2])
            # Bottom (reverse winding)
            faces.append([b_i, b_o, b_i2]); faces.append([b_o, b_o2, b_i2])
            # Inner radial strip
            faces.append([t_i, b_i, b_i2]); faces.append([t_i, b_i2, t_i2])
            # Outer radial strip
            faces.append([t_o, t_o2, b_o2]); faces.append([t_o, b_o2, b_o])
        # Start cap (radial face at a_start)
        idx = [0, 1, off + 1, off]
        faces.append([idx[0], idx[1], idx[2]]); faces.append([idx[0], idx[2], idx[3]])
        # End cap (radial face at a_end)
        last = 2 * sub
        idx = [last, last + 1, off + last + 1, off + last]
        faces.append([idx[0], idx[2], idx[1]]); faces.append([idx[0], idx[3], idx[2]])
        tread = trimesh.Trimesh(vertices=all_verts, faces=faces, process=False)
        meshes.append(tread)

    # Outer balustrade — posts at each tread, rail segments between
    if balustrade:
        prev_outer = None
        for i in range(n_steps + 1):
            z_i = z_bottom + i * dz
            a_i = i * d_angle
            co, si = math.cos(a_i), math.sin(a_i)
            outer_pt = np.array([cx + r_outer * co, cy + r_outer * si, z_i])
            rail_pt = outer_pt + np.array([0, 0, RAIL_HEIGHT_M])
            post = box_section(outer_pt, rail_pt, 0.04)
            if post is not None:
                meshes.append(post)
            if prev_outer is not None:
                prev_rail = prev_outer + np.array([0, 0, RAIL_HEIGHT_M])
                seg = box_section(prev_rail, rail_pt, 0.05)
                if seg is not None:
                    meshes.append(seg)
                if mid_rail:
                    prev_mid = prev_outer + np.array([0, 0, MID_RAIL_HEIGHT_M])
                    cur_mid = outer_pt + np.array([0, 0, MID_RAIL_HEIGHT_M])
                    seg_m = box_section(prev_mid, cur_mid, 0.04)
                    if seg_m is not None:
                        meshes.append(seg_m)
            prev_outer = outer_pt

    # Optional landing deck at top — a 3.6 m square with a 3/4 annular cutout
    # around the axis. The 1/4 'tongue' is oriented so that one EDGE of the
    # tongue aligns with the last tread's leading edge at `last_angle`; the
    # tongue then extends into the quadrant OPPOSITE the helical's winding
    # (CCW for a CW helical, CW for a CCW helical), which keeps the tongue
    # clear of the helical's own footprint and gives the walker a clean step
    # from the last tread onto the landing.
    if landing:
        last_angle = n_steps * d_angle  # radians, end of last tread
        tongue_width_deg = 90
        tongue_half_rad = math.radians(tongue_width_deg / 2)
        if clockwise:
            tongue_center = last_angle - tongue_half_rad
        else:
            tongue_center = last_angle + tongue_half_rad
        landing_meshes = _make_pac_man_deck(
            (cx, cy), top_z_m, r_outer, tongue_center,
            cell_size=3.6, tongue_width_deg=tongue_width_deg,
        )
        meshes.extend(landing_meshes)
    return meshes


def _make_hollow_cylinder(radius_m, length_m, wall_thickness=0.1, sections=48):
    """Hollow cylindrical shell along Z axis, centered at origin. Built directly from
    vertices — no boolean engine required. Open-ended (no caps beyond the annular rim)."""
    N = sections
    R = radius_m
    r = max(0.02, radius_m - wall_thickness)
    h = length_m
    verts = []
    for i in range(N):
        a = 2 * math.pi * i / N
        co, si = math.cos(a), math.sin(a)
        verts.append([R * co, R * si, -h / 2])  # Ob
        verts.append([r * co, r * si, -h / 2])  # Ib
        verts.append([R * co, R * si,  h / 2])  # Ot
        verts.append([r * co, r * si,  h / 2])  # It
    verts = np.array(verts)
    faces = []
    for i in range(N):
        j = (i + 1) % N
        Ob, Ib, Ot, It = 4 * i,     4 * i + 1, 4 * i + 2, 4 * i + 3
        Ob2, Ib2, Ot2, It2 = 4 * j, 4 * j + 1, 4 * j + 2, 4 * j + 3
        # Outer wall (normals outward)
        faces.append([Ob, Ob2, Ot2]); faces.append([Ob, Ot2, Ot])
        # Inner wall (normals inward)
        faces.append([Ib, It2, Ib2]); faces.append([Ib, It, It2])
        # Top annulus (normals +Z)
        faces.append([Ot, Ot2, It2]); faces.append([Ot, It2, It])
        # Bottom annulus (normals -Z)
        faces.append([Ob, Ib2, Ob2]); faces.append([Ob, Ib, Ib2])
    return trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)


def make_cylinder_tower(anchor, radius_m, height_m, hollow=False):
    anchor = np.asarray(anchor, dtype=float)
    if hollow and radius_m > 0.15:
        mesh = _make_hollow_cylinder(radius_m, height_m, wall_thickness=0.1, sections=48)
    else:
        mesh = trimesh.creation.cylinder(radius=radius_m, height=height_m, sections=48)
    mesh.apply_translation([0, 0, height_m / 2])
    mesh.apply_translation(anchor)
    return [mesh]


def make_cylinder_drum(anchor, direction, radius_m, length_m, hollow=False):
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    if hollow and radius_m > 0.15:
        mesh = _make_hollow_cylinder(radius_m, length_m, wall_thickness=0.1, sections=48)
    else:
        mesh = trimesh.creation.cylinder(radius=radius_m, height=length_m, sections=48)
    z = np.array([0.0, 0.0, 1.0])
    if not np.allclose(direction, z):
        if np.allclose(direction, -z):
            R = rotation_matrix(math.pi, [1, 0, 0])
        else:
            axis = np.cross(z, direction)
            axis = axis / np.linalg.norm(axis)
            angle = math.acos(np.clip(np.dot(z, direction), -1, 1))
            R = rotation_matrix(angle, axis)
        mesh.apply_transform(R)
    mesh.apply_translation(anchor + direction * (length_m / 2))
    return [mesh]


def make_wedge(anchor, direction, length_m, width_m, height_m):
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    verts = np.array(
        [
            [0, -width_m / 2, 0],
            [0, width_m / 2, 0],
            [0, -width_m / 2, height_m],
            [length_m, -width_m / 2, 0],
            [length_m, width_m / 2, 0],
            [length_m, -width_m / 2, height_m],
        ]
    )
    faces = np.array(
        [
            [0, 2, 1],
            [3, 4, 5],
            [0, 1, 4], [0, 4, 3],
            [0, 3, 5], [0, 5, 2],
            [1, 2, 5], [1, 5, 4],
        ]
    )
    m = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    x = np.array([1.0, 0.0, 0.0])
    if not np.allclose(direction, x):
        if np.allclose(direction, -x):
            R = rotation_matrix(math.pi, [0, 0, 1])
        else:
            axis = np.cross(x, direction)
            axis = axis / np.linalg.norm(axis)
            angle = math.acos(np.clip(np.dot(x, direction), -1, 1))
            R = rotation_matrix(angle, axis)
        m.apply_transform(R)
    m.apply_translation(anchor)
    return [m]


def make_curved_plane(anchor, direction, radius_m, height_m, sweep_deg, wall_thickness_m=0.1):
    """Curved wall attached to a cube face.
    - `anchor` is the chord midpoint on the cube face (world or cube-local).
    - `direction` is the outward normal (horizontal).
    - The arc's two chord endpoints sit on the face; the arc bulges outward by
      the sagitta (= radius * (1 - cos(sweep/2))).
    """
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    dx, dy = direction[0], direction[1]
    if abs(dx) + abs(dy) < 1e-9:
        normal_xy = np.array([0.0, 1.0])
    else:
        nrm = math.hypot(dx, dy)
        normal_xy = np.array([dx / nrm, dy / nrm])

    sweep = math.radians(sweep_deg)
    sagitta = radius_m * (1 - math.cos(sweep / 2))
    # Axis of arc sits behind the anchor (into the cube) by (radius - sagitta),
    # so the two arc endpoints land on the face plane through the anchor.
    axis_offset = radius_m - sagitta

    heading = math.atan2(normal_xy[1], normal_xy[0])
    start_angle = heading - sweep / 2

    n_seg = max(12, int(sweep_deg / 4))
    outer_r = radius_m
    inner_r = max(0.01, radius_m - wall_thickness_m)
    verts = []
    for i in range(n_seg + 1):
        a = start_angle + sweep * i / n_seg
        co, si = math.cos(a), math.sin(a)
        verts.append([outer_r * co, outer_r * si, 0])
        verts.append([inner_r * co, inner_r * si, 0])
        verts.append([outer_r * co, outer_r * si, height_m])
        verts.append([inner_r * co, inner_r * si, height_m])
    verts = np.array(verts)
    faces = []
    for i in range(n_seg):
        o0, i0, ot0, it0 = i * 4, i * 4 + 1, i * 4 + 2, i * 4 + 3
        o1, i1, ot1, it1 = (i + 1) * 4, (i + 1) * 4 + 1, (i + 1) * 4 + 2, (i + 1) * 4 + 3
        faces.append([o0, o1, ot1]); faces.append([o0, ot1, ot0])
        faces.append([i0, it1, i1]); faces.append([i0, it0, it1])
        faces.append([ot0, ot1, it1]); faces.append([ot0, it1, it0])
        faces.append([o0, i1, o1]); faces.append([o0, i0, i1])
    faces.append([0, 2, 3]); faces.append([0, 3, 1])
    last = n_seg * 4
    faces.append([last, last + 3, last + 2]); faces.append([last, last + 1, last + 3])
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    # Position the arc's axis behind the anchor along -normal.
    axis_pos = np.array([
        anchor[0] - normal_xy[0] * axis_offset,
        anchor[1] - normal_xy[1] * axis_offset,
        anchor[2],
    ])
    m.apply_translation(axis_pos)
    return [m]


def make_cantilever_beam(anchor, direction, length_m, section_m=0.25):
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    end = anchor + direction * length_m
    m = box_section(anchor, end, section_m)
    return [m] if m is not None else []


def make_raw_beam(from_m, to_m, section_m=0.12):
    """Untyped beam between two arbitrary points. Escape hatch from typed
    attachments — used for sculptural extrusions, structural links between
    dislocated pieces, or any linear element that doesn't fit the vocabulary."""
    m = box_section(from_m, to_m, section_m)
    return [m] if m is not None else []


def make_canopy(anchor, direction, width_m, depth_m, thickness_m=0.1):
    anchor = np.asarray(anchor, dtype=float)
    direction = np.asarray(direction, dtype=float)
    d_h = direction.copy(); d_h[2] = 0
    n = np.linalg.norm(d_h)
    d_h = np.array([1.0, 0.0, 0.0]) if n < 1e-9 else d_h / n
    yaw = math.atan2(d_h[1], d_h[0])
    R = rotation_matrix(yaw, [0, 0, 1])
    canopy = trimesh.creation.box(extents=[depth_m, width_m, thickness_m])
    canopy.apply_translation([depth_m / 2, 0, -thickness_m / 2])
    canopy.apply_transform(R)
    canopy.apply_translation(anchor)
    return [canopy]


ATTACHMENT_BUILDERS = {
    "ramp": lambda a: make_ramp(
        a["anchor_m"], a["direction"],
        a.get("length_m", 12), a.get("width_m", 1.8),
        a.get("tilt_deg", 18), a.get("balustrade", True),
        a.get("mid_rail", True), a.get("landing", False),
        a.get("landing_size_m", 2.4),
    ),
    "stair_cantilever": lambda a: make_stair_cantilever(
        a["anchor_m"], a["direction"],
        a.get("steps", 12), a.get("width_m", 1.2),
        a.get("step_rise_m", 0.30), a.get("step_run_m", 0.30),
        a.get("balustrade", True), a.get("mid_rail", True),
        a.get("landing", False), a.get("landing_size_m", 2.4),
    ),
    "stair_helical": lambda a: make_stair_helical(
        a["anchor_m"], a["top_z_m"], a.get("radius_m", 1.2),
        a.get("revolutions"), a.get("clockwise", True),
        a.get("balustrade", True), a.get("mid_rail", True),
        a.get("central_post", True), a.get("step_rise_m", 0.18),
        a.get("landing", False),
    ),
    "cylinder_tower": lambda a: make_cylinder_tower(
        a["anchor_m"], a.get("radius_m", 1.2), a.get("height_m", 6), a.get("hollow", False)
    ),
    "cylinder_drum": lambda a: make_cylinder_drum(
        a["anchor_m"], a["direction"], a.get("radius_m", 1.5),
        a.get("length_m", 5), a.get("hollow", False),
    ),
    "wedge": lambda a: make_wedge(
        a["anchor_m"], a["direction"],
        a.get("length_m", 4), a.get("width_m", 3), a.get("height_m", 3),
    ),
    "curved_plane": lambda a: make_curved_plane(
        a["anchor_m"], a["direction"], a.get("radius_m", 4),
        a.get("height_m", 7.2), a.get("sweep_deg", 90), a.get("wall_thickness_m", 0.1),
    ),
    "cantilever_beam": lambda a: make_cantilever_beam(
        a["anchor_m"], a["direction"], a.get("length_m", 5), a.get("section_m", 0.25)
    ),
    "canopy": lambda a: make_canopy(
        a["anchor_m"], a["direction"],
        a.get("width_m", 4), a.get("depth_m", 2.5), a.get("thickness_m", 0.1),
    ),
    "raw_beam": lambda a: make_raw_beam(
        a["from_m"], a["to_m"], a.get("section_m", 0.12)
    ),
}


# ---------------------------------------------------------------------------
# Stochastic folie generation

def _face_anchor(face, cube_origin, size, z_offset):
    ox, oy, oz = cube_origin
    if face == 0:
        return [ox, oy + size / 2, oz + z_offset], [-1, 0, 0]
    if face == 1:
        return [ox + size, oy + size / 2, oz + z_offset], [1, 0, 0]
    if face == 2:
        return [ox + size / 2, oy, oz + z_offset], [0, -1, 0]
    return [ox + size / 2, oy + size, oz + z_offset], [0, 1, 0]


def random_attachment(rng, cube_origin, size, target_z=None, atype=None, want_landing=False):
    if atype is None:
        atype = rng.choices(
            ["ramp", "stair_cantilever", "cylinder_tower", "cylinder_drum",
             "wedge", "curved_plane", "cantilever_beam", "canopy"],
            weights=[3, 2, 2, 1, 1, 2, 2, 1],
        )[0]
    ox, oy, oz = cube_origin

    if atype == "ramp":
        face = rng.choice([0, 1, 2, 3])
        if target_z is None:
            target_z, tilt = rng.choice([
                (3.6, 15), (3.6, 18), (3.6, 20), (3.6, 25),
                (7.2, 25), (7.2, 28), (7.2, 30),
            ])
        else:
            tilt = rng.choice([15, 18, 20, 25]) if target_z <= 3.6 else rng.choice([25, 28, 30])
        length = target_z / math.sin(math.radians(tilt))
        run = length * math.cos(math.radians(tilt))
        if face == 0:
            anchor = [ox - run, oy + size / 2, oz]; direction = [1, 0, 0]
        elif face == 1:
            anchor = [ox + size + run, oy + size / 2, oz]; direction = [-1, 0, 0]
        elif face == 2:
            anchor = [ox + size / 2, oy - run, oz]; direction = [0, 1, 0]
        else:
            anchor = [ox + size / 2, oy + size + run, oz]; direction = [0, -1, 0]
        spec = {
            "type": "ramp", "anchor_m": anchor, "direction": direction,
            "length_m": round(length, 3), "width_m": rng.choice([1.5, 1.8, 2.1]),
            "tilt_deg": tilt, "target_z_m": target_z,
        }
        if want_landing:
            spec["landing"] = True
        return spec

    if atype == "stair_cantilever":
        # `target_z` here means: where should the stair END (i.e. which platform does it reach).
        # Start z is picked independently (usually a lower platform or the ground+0.1).
        face = rng.choice([0, 1, 2, 3])
        if target_z is not None:
            # Stairs cantilever off cube faces, so z_start must be a face height
            # (3.6 or 7.2), never ground (0.0). Choose a start z that yields steps in [8, 20].
            candidate_starts = [z for z in (3.6, 7.2) if z < target_z]
            if candidate_starts:
                z_start = rng.choice(candidate_starts)
                steps = max(1, round((target_z - z_start) / 0.30))
                if not (8 <= steps <= 20):
                    # Can't reach from any face height — fall back, add landing later
                    z_start = rng.choice([3.6, 7.2])
                    steps = rng.randint(8, 14)
                    target_z = None
            else:
                z_start = rng.choice([3.6, 7.2])
                steps = rng.randint(8, 14)
                target_z = None
        else:
            z_start = rng.choice([3.6, 7.2])
            steps = rng.randint(8, 14)
        anchor, direction = _face_anchor(face, cube_origin, size, z_start)
        spec = {
            "type": "stair_cantilever", "anchor_m": anchor, "direction": direction,
            "steps": steps, "width_m": rng.choice([1.0, 1.2, 1.5]),
        }
        if target_z is not None:
            spec["target_z_m"] = target_z
        if want_landing:
            spec["landing"] = True
        return spec

    if atype == "cylinder_tower":
        pos = rng.choice(["top_center", "top_corner", "top_edge"])
        if pos == "top_center":
            anchor = [ox + size / 2, oy + size / 2, oz + size]
        elif pos == "top_corner":
            anchor = [rng.choice([ox, ox + size]), rng.choice([oy, oy + size]), oz + size]
        else:
            axis = rng.choice(["x", "y"])
            if axis == "x":
                anchor = [ox + size / 2, rng.choice([oy, oy + size]), oz + size]
            else:
                anchor = [rng.choice([ox, ox + size]), oy + size / 2, oz + size]
        return {
            "type": "cylinder_tower", "anchor_m": anchor,
            "radius_m": rng.choice([0.9, 1.2, 1.5, 1.8]),
            "height_m": rng.choice([4, 6, 8, 10]),
            "hollow": rng.random() < 0.3,
        }

    if atype == "cylinder_drum":
        face = rng.choice([0, 1, 2, 3])
        anchor, direction = _face_anchor(face, cube_origin, size, rng.choice([3.6, 7.2]))
        return {
            "type": "cylinder_drum", "anchor_m": anchor, "direction": direction,
            "radius_m": rng.choice([1.2, 1.5, 1.8]),
            "length_m": rng.choice([3, 4, 5, 6]),
        }

    if atype == "wedge":
        face = rng.choice([0, 1, 2, 3])
        anchor, direction = _face_anchor(face, cube_origin, size, rng.choice([0, 3.6, 7.2]))
        return {
            "type": "wedge", "anchor_m": anchor, "direction": direction,
            "length_m": rng.choice([3, 4, 5]),
            "width_m": rng.choice([2, 3, 4]),
            "height_m": rng.choice([2, 3, 4]),
        }

    if atype == "curved_plane":
        # Anchor is the chord midpoint on a face; direction is the outward normal.
        face = rng.choice([0, 1, 2, 3])
        anchor, direction = _face_anchor(face, cube_origin, size, 0)  # base on ground
        return {
            "type": "curved_plane", "anchor_m": anchor, "direction": direction,
            "radius_m": rng.choice([3, 4, 5]),
            "height_m": rng.choice([3.6, 7.2, 10.8]),
            "sweep_deg": rng.choice([60, 90, 120]),
        }

    if atype == "cantilever_beam":
        face = rng.choice([0, 1, 2, 3])
        anchor, direction = _face_anchor(face, cube_origin, size, rng.choice([3.6, 7.2, 10.8]))
        return {
            "type": "cantilever_beam", "anchor_m": anchor, "direction": direction,
            "length_m": rng.choice([3, 4, 5, 6]),
        }

    # canopy
    face = rng.choice([0, 1, 2, 3])
    anchor, direction = _face_anchor(face, cube_origin, size, rng.choice([3.6, 7.2]))
    return {
        "type": "canopy", "anchor_m": anchor, "direction": direction,
        "width_m": rng.choice([3, 4, 5]), "depth_m": rng.choice([2, 2.5, 3]),
    }


def _stair_config_candidates(from_cells, to_cells, sub, from_level,
                               n_steps=12, step_run=0.30):
    """Enumerate all valid (anchor, direction) pairs for a stair of `n_steps`
    that starts in any `from_cells` at `from_level` and lands in any `to_cells`."""
    h_run = n_steps * step_run
    candidates = []
    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        for (c1, r1) in from_cells:
            for (c2, r2) in to_cells:
                if dy == 0 and r1 != r2:
                    continue
                if dx == 0 and c1 != c2:
                    continue
                if dx == 1:
                    x_lo = max(c1 * sub, c2 * sub - h_run)
                    x_hi = min((c1 + 1) * sub, (c2 + 1) * sub - h_run)
                    y_lo, y_hi = r1 * sub, (r1 + 1) * sub
                elif dx == -1:
                    x_lo = max(c1 * sub, c2 * sub + h_run)
                    x_hi = min((c1 + 1) * sub, (c2 + 1) * sub + h_run)
                    y_lo, y_hi = r1 * sub, (r1 + 1) * sub
                elif dy == 1:
                    x_lo, x_hi = c1 * sub, (c1 + 1) * sub
                    y_lo = max(r1 * sub, r2 * sub - h_run)
                    y_hi = min((r1 + 1) * sub, (r2 + 1) * sub - h_run)
                else:
                    x_lo, x_hi = c1 * sub, (c1 + 1) * sub
                    y_lo = max(r1 * sub, r2 * sub + h_run)
                    y_hi = min((r1 + 1) * sub, (r2 + 1) * sub + h_run)
                if x_lo > x_hi or y_lo > y_hi:
                    continue
                anchor = [(x_lo + x_hi) / 2, (y_lo + y_hi) / 2, from_level * sub]
                candidates.append((anchor, [dx, dy, 0]))
    return candidates


def _find_stair_config(rng, from_cells, to_cells, sub, from_level, to_level,
                         n_steps=12, step_run=0.30, exclude_keys=None):
    """Pick a random valid stair config, excluding configs whose key is in
    `exclude_keys` (keys are (x, y, dx, dy) tuples, rounded)."""
    candidates = _stair_config_candidates(from_cells, to_cells, sub, from_level,
                                            n_steps=n_steps, step_run=step_run)
    if exclude_keys:
        filtered = []
        for anchor, direction in candidates:
            key = (round(anchor[0], 1), round(anchor[1], 1),
                   round(direction[0]), round(direction[1]))
            if key not in exclude_keys:
                filtered.append((anchor, direction))
        candidates = filtered
    if not candidates:
        return None, None
    return rng.choice(candidates)


def randomize_folie(seed, cube_origin, cube_size, lod=LOD_DEFAULT):
    rng = random.Random(seed)
    sub = cube_size / 3

    n_solid = rng.randint(1, 6)
    all_cells = [(i, j, k) for i in range(3) for j in range(3) for k in range(3)]
    solid_cells = rng.sample(all_cells, n_solid)

    platforms = []
    access_levels = []  # z values where a human can land
    if lod >= 300:
        # Always include at least one platform at z = 3.6 or 7.2
        n_plat = rng.randint(1, 2)
        levels_used = set()
        all_2d = [(i, j) for i in range(3) for j in range(3)]
        for _ in range(n_plat):
            level = rng.choice([1, 2])
            if level in levels_used and n_plat > 1:
                level = 2 if level == 1 else 1
            levels_used.add(level)
            n_cells = rng.randint(1, 4)
            # Pick a connected-ish blob: start with one cell, grow outward
            start = rng.choice(all_2d)
            chosen = [start]
            remaining = set(all_2d) - {start}
            for _ in range(n_cells - 1):
                neighbors = [
                    (i + di, j + dj)
                    for (i, j) in chosen
                    for (di, dj) in [(1, 0), (-1, 0), (0, 1), (0, -1)]
                    if (i + di, j + dj) in remaining
                ]
                if not neighbors:
                    break
                pick = rng.choice(neighbors)
                chosen.append(pick)
                remaining.discard(pick)
            platforms.append({
                "level": level,
                "cells": [list(c) for c in chosen],
            })
            access_levels.append(level * sub)

    # Attachments — ensure accessibility: ground-ramp to lowest platform,
    # plus stairs connecting higher platforms. Stairs are sized so terminus
    # lands on a platform cell (rule §9a).
    n_attach = rng.randint(3, 5)
    attachments = []
    used_ramp_faces = set()  # dedupe ramp approach faces (rule §10)
    if lod >= 300 and access_levels:
        sorted_levels = sorted(set(access_levels))
        # Mandatory ground-access ramp to the lowest platform
        ramp_spec = random_attachment(
            rng, cube_origin, cube_size, target_z=sorted_levels[0],
            atype="ramp", want_landing=False,
        )
        # Record which face this ramp approaches (direction inverted = face normal)
        d = ramp_spec.get("direction", [0, 0, 0])
        used_ramp_faces.add((round(-d[0]), round(-d[1])))
        attachments.append(ramp_spec)
        n_attach -= 1
        # Stairs connecting upper platforms: compute anchor/direction to hit a cell
        # Build level → cells lookup
        level_cells = {}
        for p in platforms:
            lvl = p["level"]
            level_cells.setdefault(lvl, []).extend(tuple(c) for c in p["cells"])
        level_values = sorted(level_cells.keys())
        for i in range(1, len(level_values)):
            from_lvl = level_values[i - 1]
            to_lvl = level_values[i]
            n_steps = int(round((to_lvl - from_lvl) * sub / 0.30))
            n_steps = max(8, min(16, n_steps))
            anchor, direction = _find_stair_config(
                rng, level_cells[from_lvl], level_cells[to_lvl],
                sub=sub, from_level=from_lvl, to_level=to_lvl,
                n_steps=n_steps,
            )
            if anchor is not None:
                attachments.append({
                    "type": "stair_cantilever",
                    "anchor_m": [round(v, 3) for v in anchor],
                    "direction": direction,
                    "steps": n_steps, "width_m": rng.choice([1.0, 1.2, 1.5]),
                    "target_z_m": to_lvl * sub,
                })
                n_attach -= 1

    # Decorative attachments — exclude ramp (mandatory ramp already placed) and
    # stair_cantilever (requires a platform target, handled above). Use only
    # volumetric and cantilever-by-design elements for decoration.
    decorative_types = ["cylinder_tower", "cylinder_drum", "wedge", "curved_plane",
                        "cantilever_beam", "canopy"]
    decorative_weights = [3, 2, 2, 2, 2, 1]
    for _ in range(max(0, n_attach)):
        atype = rng.choices(decorative_types, weights=decorative_weights)[0]
        attachments.append(random_attachment(rng, cube_origin, cube_size, atype=atype))

    cube_out = {
        # Subdivision frame is the signature Tschumi cage look — always on in random
        # generation. Users can override with `"show_subdivision_frame": false` for
        # a minimalist folie.
        "show_subdivision_frame": True,
        "solid_cells": [list(c) for c in solid_cells],
    }
    if platforms:
        cube_out["platforms"] = platforms
    return cube_out, attachments


# ---------------------------------------------------------------------------
# Assembly

def generate_folie(folie_spec, defaults, origin_world=(0, 0, 0)):
    cube_size = defaults.get("cube_size_m", CUBE_SIZE)
    subs = defaults.get("subdivisions", SUB)
    sub_cell = cube_size / subs
    section = defaults.get("frame_section_m", FRAME_SECTION)
    lod = defaults.get("lod", LOD_DEFAULT)
    cube_origin = np.asarray(origin_world, dtype=float)

    seed = folie_spec.get("seed")
    cube_spec = folie_spec.get("cube")
    attachments_spec = folie_spec.get("attachments")

    if (cube_spec is None or attachments_spec is None) and seed is not None:
        # Generate in cube-local coordinates (origin at 0,0,0). The uniform shift
        # below places them in world space alongside user-specified attachments.
        auto_cube, auto_attach = randomize_folie(
            seed, np.zeros(3), cube_size, lod=lod
        )
        if cube_spec is None: cube_spec = auto_cube
        if attachments_spec is None: attachments_spec = auto_attach
    cube_spec = cube_spec or {}
    attachments_spec = attachments_spec or []

    # All attachment anchors are in cube-local coordinates. Shift to world space.
    shifted = []
    for a in attachments_spec:
        a2 = dict(a)
        if "anchor_m" in a2:
            a2["anchor_m"] = [a2["anchor_m"][i] + cube_origin[i] for i in range(3)]
        shifted.append(a2)

    meshes = []
    meshes.extend(make_cube_frame(cube_origin, cube_size, section, cube_spec.get("absent_edges")))
    if cube_spec.get("show_subdivision_frame", True):
        meshes.extend(make_subdivision_frame(cube_origin, cube_size, subs, section))

    # Solid cells — framed panels at LOD 300, monolithic at LOD 200
    solid_cells = cube_spec.get("solid_cells", [])
    if solid_cells:
        if lod >= 300:
            meshes.extend(
                make_solid_cells_panels(solid_cells, cube_origin, sub_cell,
                                         panel_thickness=defaults.get("panel_thickness_m", PANEL_THICKNESS))
            )
        else:
            for cell in solid_cells:
                meshes.append(make_solid_cell(cell, cube_origin, sub_cell))
    for dc in cube_spec.get("dislocated_cells", []):
        offset = dc.get("offset_m", [0, 0, 0])
        if "cells" in dc:
            # Group form: many cells share the same offset. Render as a single
            # boundary-deduped panel set (LOD 300) or as individual boxes (LOD 200).
            group_origin = cube_origin + np.asarray(offset, dtype=float)
            cells = dc["cells"]
            if lod >= 300:
                meshes.extend(
                    make_solid_cells_panels(
                        cells, group_origin, sub_cell,
                        panel_thickness=defaults.get("panel_thickness_m", PANEL_THICKNESS),
                    )
                )
            else:
                for cell in cells:
                    meshes.append(make_solid_cell(cell, group_origin, sub_cell))
        elif "cell" in dc:
            meshes.append(make_solid_cell(dc["cell"], cube_origin, sub_cell, offset))

    # Platforms (LOD 300)
    if lod >= 300:
        solid_cells_3d = cube_spec.get("solid_cells", []) or []
        for plat in cube_spec.get("platforms", []):
            meshes.extend(
                make_platform(
                    plat["cells"], plat["level"], cube_origin, sub_cell,
                    balustrade=plat.get("balustrade", True),
                    mid_rail=plat.get("mid_rail", True),
                    open_sides=plat.get("open_sides"),
                    cutout_cells=plat.get("cutout_cells"),
                    solid_cells_3d=solid_cells_3d,
                )
            )

    # Attachments
    for a in shifted:
        builder = ATTACHMENT_BUILDERS.get(a.get("type"))
        if builder is None:
            print(f"WARNING: unknown attachment type '{a.get('type')}'", file=sys.stderr)
            continue
        try:
            meshes.extend(builder(a))
        except Exception as e:
            print(f"WARNING: failed {a.get('type')}: {e}", file=sys.stderr)

    return meshes, {"cube": cube_spec, "attachments": attachments_spec}


def apply_red(mesh, rgba, metallic=0.2, roughness=0.45):
    """Apply a glTF PBR material to the mesh.

    rgba values are 0–255 uint8; converted to 0–1 floats for PBR.
    metallic / roughness are PBR factors in [0, 1].

    Also splits vertices per face so flat panel faces shade correctly.
    trimesh's box creator shares vertices at corners; averaging three
    adjacent face normals at a corner gives a diagonal vertex normal,
    which makes Phong shading draw the triangle seams as visible
    gradients across otherwise-flat panels (Rhino / three.js / Unreal
    all show this). Unmerging gives each face its own vertex set and
    therefore its own face-aligned normal.
    """
    try:
        mesh.unmerge_vertices()
    except Exception:
        pass
    base_color = [float(c) / 255.0 for c in rgba]
    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=base_color,
        metallicFactor=float(metallic),
        roughnessFactor=float(roughness),
    )
    mesh.visual = trimesh.visual.TextureVisuals(material=material)
    return mesh


def build_scene(spec):
    # Resolve target_z_m → length_m / steps before geometry is built.
    preprocess_spec(spec)

    defaults = spec.get("defaults", {})
    grid_spacing = defaults.get("grid_spacing_m", GRID_SPACING)
    color_hex = defaults.get("color", TSCHUMI_RED_HEX)
    metallic = defaults.get("metallic", 0.2)
    roughness = defaults.get("roughness", 0.45)
    rgba = hex_to_rgba(color_hex)

    scene = trimesh.Scene()
    resolved = {"defaults": {**defaults, "color": color_hex,
                             "metallic": metallic, "roughness": roughness},
                "folies": []}

    for folie_spec in spec.get("folies", []):
        col, row = folie_spec.get("grid_pos", [0, 0])
        origin = (col * grid_spacing, row * grid_spacing, 0)
        meshes, resolved_cube_attach = generate_folie(folie_spec, defaults, origin)
        for idx, m in enumerate(meshes):
            apply_red(m, rgba, metallic=metallic, roughness=roughness)
            # Split vertices per face so each face keeps its own normal.
            # trimesh merges box corners to 8 verts by default, which gives
            # smoothed corner normals and produces striped/banded shading in
            # runtime glTF loaders (e.g. UE glTFRuntime). unmerge → flat shading.
            m.unmerge_vertices()
            # Force normal computation + caching so they actually end up in the
            # exported glb (trimesh's glb exporter skips normals that aren't
            # explicitly cached on the mesh).
            _ = m.vertex_normals
            scene.add_geometry(m, node_name=f"folie_{col}_{row}_{idx}")
        resolved["folies"].append({
            "grid_pos": [col, row],
            "seed": folie_spec.get("seed"),
            **resolved_cube_attach,
        })

    # Convert Z-up (architectural / Rhino / Unreal convention) to Y-up (glTF 2.0 spec).
    # Rotation -90° about X: (x, y, z) -> (x, z, -y). Rhino / three.js / Unreal glTF importers
    # reverse this automatically on import, yielding correct Z-up orientation in those tools.
    # Bake into vertex data (not scene graph) so the file on disk is genuinely Y-up.
    if defaults.get("export_yup", True):
        R = rotation_matrix(-math.pi / 2, [1, 0, 0])
        for geom in scene.geometry.values():
            geom.apply_transform(R)

    return scene, resolved


# ---------------------------------------------------------------------------
# Spec preprocessing — resolve `target_z_m` to concrete length/steps

def preprocess_spec(spec):
    """Mutate a spec in-place:
    - §R1: auto-add an L3 roof platform when at least one attachment reaches L3
      (target_z_m ≈ cube_size, or a helical whose top_z_m ≈ cube_size). This
      keeps the "every cube has a platform on top" rule without forcing roofs
      on folies that have no circulation to them. Override either way with
      `force_auto_roof: true` or `skip_auto_roof: true`.
    - For ramps and stairs with `target_z_m`, compute the canonical `length_m`
      (ramp) or `steps` (stair).
    """
    defaults = spec.get("defaults", {})
    cube_size = defaults.get("cube_size_m", CUBE_SIZE)
    step_rise = 0.30
    for folie in spec.get("folies", []):
        cube = folie.get("cube", {}) or {}
        platforms = cube.setdefault("platforms", [])
        has_l3 = any(p.get("level") == 3 for p in platforms)
        attachments = folie.get("attachments", []) or []

        def _reaches_l3(a):
            if a.get("type") == "stair_helical":
                t = a.get("top_z_m")
                return t is not None and abs(t - cube_size) < 0.4
            t = a.get("target_z_m")
            return t is not None and abs(t - cube_size) < 0.4

        if not has_l3 and not cube.get("skip_auto_roof"):
            if cube.get("force_auto_roof") or any(_reaches_l3(a) for a in attachments):
                platforms.append({
                    "level": 3,
                    "cells": [[c, r] for c in range(SUB) for r in range(SUB)],
                    "auto_roof": True,
                })

        for a in attachments:
            atype = a.get("type")
            if atype == "ramp":
                target_z = a.get("target_z_m")
                tilt = a.get("tilt_deg")
                if target_z is not None and tilt is not None:
                    a["length_m"] = round(target_z / math.sin(math.radians(tilt)), 3)
            elif atype == "stair_cantilever":
                target_z = a.get("target_z_m")
                rise = a.get("step_rise_m", step_rise)
                if target_z is not None and "anchor_m" in a:
                    anchor_z = a["anchor_m"][2]
                    a["steps"] = max(1, round((target_z - anchor_z) / rise))
    return spec


# ---------------------------------------------------------------------------
# Autofix — patch the spec based on validator findings, so next generation passes

def _open_platform_ingress(cube, direction, terminus, target_z, sub, cube_size, tag, fixes):
    """When a ramp/stair terminus lands on a platform cell, add the ingress edge
    to that platform's `open_sides` so the balustrade doesn't block entry.
    Cardinal directions only. Returns True if a fix was added."""
    dx, dy = direction[0], direction[1]
    dx_i = 1 if dx > 0.5 else (-1 if dx < -0.5 else 0)
    dy_i = 1 if dy > 0.5 else (-1 if dy < -0.5 else 0)
    if abs(dx_i) + abs(dy_i) != 1:
        return False
    if dx_i == -1:
        edge = "x+"
    elif dx_i == 1:
        edge = "x-"
    elif dy_i == -1:
        edge = "y+"
    else:
        edge = "y-"

    target_lvl = int(round(target_z / sub))
    tx, ty = terminus[0], terminus[1]

    # Direction-biased sub-cell snapping. When tx sits exactly on a sub-cell
    # boundary (modulo floating-point noise), the "cell the walker enters"
    # depends on which way they're moving. For direction +x they enter the cell
    # east of the boundary; for -x they enter the cell west of it. Floor-based
    # indexing picks the wrong cell ~half the time because 7.2/3.6 lands at
    # 1.9999…, not 2.0. Handle the boundary case explicitly.
    def _snap(coord, axis_dir, subs=SUB, size=cube_size):
        f = coord / sub
        if abs(f - round(f)) < 0.02:  # on a boundary within ~7cm tolerance
            boundary = int(round(f))
            c = boundary if axis_dir > 0 else boundary - 1
        else:
            c = int(coord // sub)
        # Cube outer boundary snap (unchanged semantics for terminus on cube face).
        if coord >= size - 0.05:
            c = subs - 1
        elif coord <= 0.05:
            c = 0
        return max(0, min(subs - 1, c))

    col = _snap(tx, dx_i)
    row = _snap(ty, dy_i)

    for plat in cube.get("platforms", []) or []:
        if plat.get("level") != target_lvl:
            continue
        cells = [tuple(c) for c in plat.get("cells", [])]
        if (col, row) not in cells:
            continue
        new_entry = [col, row, edge]
        existing = plat.setdefault("open_sides", [])
        for e in existing:
            if isinstance(e, (list, tuple)) and len(e) == 3 and list(e) == new_entry:
                return False
            if isinstance(e, str) and e == edge:
                return False
        existing.append(new_entry)
        fixes.append(f"{tag}: opened platform [{col},{row}] {edge} for ingress")
        return True
    return False


def _open_platform_anchor(cube, direction, anchor, sub, cube_size, tag, fixes):
    """Symmetric to _open_platform_ingress: open the platform balustrade on the
    cell(s) adjacent to a stair/ramp anchor, so the rail at the anchor doesn't
    collide with the stair's stringer at the point of origin.

    The anchor sits on (or near) an edge perpendicular to `direction`. Either of
    the two cells flanking that edge could carry the platform; open whichever
    one is actually in the spec at `anchor_lvl`.
    """
    if anchor[2] < 0.05:
        return False  # on ground — no platform edge to touch
    anchor_lvl = int(round(anchor[2] / sub))
    if anchor_lvl not in (1, 2, 3):
        return False

    dx, dy = direction[0], direction[1]
    dx_i = 1 if dx > 0.5 else (-1 if dx < -0.5 else 0)
    dy_i = 1 if dy > 0.5 else (-1 if dy < -0.5 else 0)
    if abs(dx_i) + abs(dy_i) != 1:
        return False

    target_plat = None
    for plat in cube.get("platforms", []) or []:
        if plat.get("level") == anchor_lvl:
            target_plat = plat
            break
    if target_plat is None:
        return False
    plat_cells = set(tuple(c) for c in target_plat.get("cells", []))

    ax, ay = anchor[0], anchor[1]
    if dx_i != 0:
        col_boundary = int(round(ax / sub))
        row = max(0, min(SUB - 1, int(ay // sub)))
        # Cell "behind" the direction (walker is on this one if it's in spec)
        col_behind = col_boundary - (1 if dx_i > 0 else 0)
        col_ahead = col_boundary - (0 if dx_i > 0 else 1)
        cand = [
            (col_behind, row, "x+" if dx_i > 0 else "x-"),
            (col_ahead,  row, "x-" if dx_i > 0 else "x+"),
        ]
    else:
        col = max(0, min(SUB - 1, int(ax // sub)))
        row_boundary = int(round(ay / sub))
        row_behind = row_boundary - (1 if dy_i > 0 else 0)
        row_ahead = row_boundary - (0 if dy_i > 0 else 1)
        cand = [
            (col, row_behind, "y+" if dy_i > 0 else "y-"),
            (col, row_ahead,  "y-" if dy_i > 0 else "y+"),
        ]

    opened = False
    for (c, r, edge) in cand:
        if not (0 <= c < SUB and 0 <= r < SUB):
            continue
        if (c, r) not in plat_cells:
            continue
        new_entry = [c, r, edge]
        existing = target_plat.setdefault("open_sides", [])
        if any(isinstance(e, (list, tuple)) and list(e) == new_entry for e in existing):
            continue
        existing.append(new_entry)
        fixes.append(f"{tag}: opened anchor platform [{c},{r}] {edge} (§R4 egress)")
        opened = True
    return opened


def autofix_spec(spec):
    """Return (patched_spec_dict, [fix_messages]). Applies mechanical corrections
    that keep the spec in grammar: snap ramp length / stair steps to the nearest
    platform level, or add `landing: true` when terminus is mid-air."""
    patched = json.loads(json.dumps(spec))
    fixes = []
    defaults = patched.get("defaults", {})
    sub = defaults.get("cube_size_m", CUBE_SIZE) / defaults.get("subdivisions", SUB)
    step_rise = 0.30

    for f_idx, folie in enumerate(patched.get("folies", [])):
        cube = folie.get("cube", {}) or {}
        platforms = cube.get("platforms", []) or []
        platform_zs = sorted({p["level"] * sub for p in platforms if isinstance(p.get("level"), int)})
        attachments = folie.get("attachments", []) or []
        # Track stair relocations in this folie to prevent duplicate anchors (rule §10)
        used_stair_configs = set()

        for a_idx, a in enumerate(attachments):
            atype = a.get("type")
            tag = f"folie[{f_idx}].attach[{a_idx}]:{atype}"

            if atype == "ramp":
                tilt = a.get("tilt_deg")
                if tilt is None:
                    continue
                # Materialize length from target_z if missing (mirrors preprocess_spec).
                length = a.get("length_m")
                if length is None and a.get("target_z_m") is not None:
                    length = a["target_z_m"] / math.sin(math.radians(tilt))
                    a["length_m"] = round(length, 3)
                if length is None:
                    continue

                # 1) Length snap or landing (only if target_z_m not already set).
                if a.get("target_z_m") is None:
                    terminus_z = length * math.sin(math.radians(tilt))
                    if platform_zs:
                        nearest = min(platform_zs, key=lambda pz: abs(pz - terminus_z))
                        gap = abs(terminus_z - nearest)
                        if gap >= 0.05:
                            if gap < 2.0:
                                new_length = nearest / math.sin(math.radians(tilt))
                                if 6 <= new_length <= 18:
                                    old = a["length_m"]
                                    a["length_m"] = round(new_length, 3)
                                    a["target_z_m"] = nearest
                                    length = new_length
                                    fixes.append(f"{tag}: length_m {old}→{a['length_m']} (→ L{int(round(nearest/sub))}, z={nearest}m)")
                                elif not a.get("landing"):
                                    a["landing"] = True
                                    fixes.append(f"{tag}: landing:true added (terminus z={terminus_z:.2f}m, target unreachable)")
                            elif not a.get("landing"):
                                a["landing"] = True
                                fixes.append(f"{tag}: landing:true added (terminus z={terminus_z:.2f}m, no nearby platform)")
                    elif not a.get("landing"):
                        a["landing"] = True
                        fixes.append(f"{tag}: landing:true added (no platforms defined)")

                # 2) Anchor alignment: if direction is cardinal XY and ramp starts from
                #    ground (z=0), ensure horizontal run lands terminus exactly on the
                #    corresponding cube face.
                direction = a.get("direction") or [0, 0, 0]
                anchor = a.get("anchor_m")
                if (a.get("target_z_m") is not None and anchor is not None
                        and abs(direction[2]) < 0.5):
                    cube_size = defaults.get("cube_size_m", CUBE_SIZE)
                    run = length * math.cos(math.radians(tilt))
                    dx, dy = direction[0], direction[1]
                    expected = list(anchor)
                    if abs(dx) > abs(dy):
                        expected[0] = -run if dx > 0 else cube_size + run
                    else:
                        expected[1] = -run if dy > 0 else cube_size + run
                    expected[2] = 0.0  # ramps originate on ground
                    drift = math.sqrt(sum((anchor[i] - expected[i]) ** 2 for i in range(3)))
                    if drift > 0.05:
                        old = list(anchor)
                        a["anchor_m"] = [round(v, 3) for v in expected]
                        fixes.append(f"{tag}: anchor_m {old}→{a['anchor_m']} (align terminus to cube face)")

                # 3) Platform ingress (§R4): open the balustrade edge where the ramp terminus
                #    enters the platform, AND at the anchor (for elevated-start ramps),
                #    so the walker isn't blocked by a fence at either end.
                if (a.get("target_z_m") is not None and a.get("anchor_m") is not None
                        and a.get("length_m") is not None and abs(direction[2]) < 0.5):
                    cube_size = defaults.get("cube_size_m", CUBE_SIZE)
                    run = a["length_m"] * math.cos(math.radians(tilt))
                    dx, dy = direction[0], direction[1]
                    hdist = math.hypot(dx, dy)
                    if hdist > 1e-6:
                        ux, uy = dx / hdist, dy / hdist
                        anchor_now = a["anchor_m"]
                        terminus = [anchor_now[0] + ux * run, anchor_now[1] + uy * run,
                                    a["target_z_m"]]
                        _open_platform_ingress(cube, direction, terminus, a["target_z_m"],
                                                sub, cube_size, tag, fixes)
                        _open_platform_anchor(cube, direction, anchor_now,
                                               sub, cube_size, tag, fixes)

            elif atype == "stair_cantilever":
                rise = a.get("step_rise_m", step_rise)
                run = a.get("step_run_m", 0.30)
                anchor = a.get("anchor_m") or [0, 0, 0]
                anchor_z = anchor[2]
                steps = a.get("steps", 12)
                direction = a.get("direction") or [0, 0, 0]
                # 1) Steps snap for Z alignment (as before)
                if a.get("target_z_m") is None:
                    terminus_z = anchor_z + steps * rise
                    if platform_zs:
                        nearest = min(platform_zs, key=lambda pz: abs(pz - terminus_z))
                        gap = abs(terminus_z - nearest)
                        if 0.05 < gap < 2.0:
                            new_steps = round((nearest - anchor_z) / rise)
                            if 8 <= new_steps <= 20:
                                old = steps
                                a["steps"] = new_steps
                                steps = new_steps
                                a["target_z_m"] = nearest
                                fixes.append(f"{tag}: steps {old}→{new_steps} (→ L{int(round(nearest/sub))}, z={nearest}m)")
                # 2) Terminus-support check (rule §9a): if terminus lands on nothing,
                #    try to relocate anchor so terminus hits a platform cell at target_z.
                target_z = a.get("target_z_m")
                if target_z is None:
                    continue
                target_lvl = int(round(target_z / sub))
                # Terminus after current anchor+direction+steps
                dh = math.hypot(direction[0], direction[1])
                if dh < 1e-9:
                    continue
                dh_x, dh_y = direction[0] / dh, direction[1] / dh
                h_run = steps * run
                terminus = [anchor[0] + dh_x * h_run, anchor[1] + dh_y * h_run, target_z]
                # Is terminus inside any L-target platform cell?
                target_cells = [tuple(c) for p in cube.get("platforms", [])
                                if p.get("level") == target_lvl for c in p.get("cells", [])]
                cube_size = defaults.get("cube_size_m", CUBE_SIZE)

                def _in_cell(xy, c, r):
                    return (c * sub - 0.05 <= xy[0] <= (c + 1) * sub + 0.05
                            and r * sub - 0.05 <= xy[1] <= (r + 1) * sub + 0.05)

                lands_on_cell = any(_in_cell(terminus, c, r) for (c, r) in target_cells)
                if lands_on_cell or not target_cells:
                    if lands_on_cell:
                        _open_platform_ingress(cube, direction, terminus, target_z,
                                                sub, cube_size, tag, fixes)
                    # Also open at the anchor edge (§R4 — rails at both ends)
                    _open_platform_anchor(cube, direction, anchor,
                                           sub, cube_size, tag, fixes)
                    # Register the current config so subsequent stairs avoid duplicating it
                    used_stair_configs.add((round(anchor[0], 1), round(anchor[1], 1),
                                             round(direction[0]), round(direction[1])))
                    continue
                # Attempt relocation. Find any (anchor, direction) such that terminus
                # is in a target-level cell AND anchor is within the cube plan or on a cube face.
                anchor_z_target = anchor_z  # keep start z
                # Anchor must sit on a platform at its start z
                start_lvl = int(round(anchor_z / sub))
                start_cells = [tuple(c) for p in cube.get("platforms", [])
                               if p.get("level") == start_lvl for c in p.get("cells", [])]
                if not start_cells:
                    # Fallback: any cell within cube plan at start level
                    start_cells = [(c, r) for c in range(3) for r in range(3)]
                # Try relocating; pass used_stair_configs so duplicates are excluded
                config_rng = random.Random(hash(tag) & 0xffffffff)
                new_anchor, new_direction = _find_stair_config(
                    config_rng, start_cells, target_cells,
                    sub=sub, from_level=start_lvl, to_level=target_lvl,
                    n_steps=steps, step_run=run,
                    exclude_keys=used_stair_configs,
                )
                if new_anchor is not None:
                    old_anchor = list(anchor)
                    old_dir = list(direction)
                    a["anchor_m"] = [round(v, 3) for v in new_anchor]
                    a["direction"] = new_direction
                    key = (round(new_anchor[0], 1), round(new_anchor[1], 1),
                           round(new_direction[0]), round(new_direction[1]))
                    used_stair_configs.add(key)
                    fixes.append(
                        f"{tag}: anchor {old_anchor}→{a['anchor_m']}, dir {old_dir}→{new_direction} "
                        f"(relocate so terminus lands on L{target_lvl} cell)"
                    )
                    # Open ingress on the relocated terminus AND anchor
                    dh_new = math.hypot(new_direction[0], new_direction[1])
                    if dh_new > 1e-9:
                        ux, uy = new_direction[0] / dh_new, new_direction[1] / dh_new
                        new_terminus = [new_anchor[0] + ux * h_run,
                                        new_anchor[1] + uy * h_run, target_z]
                        _open_platform_ingress(cube, new_direction, new_terminus,
                                                target_z, sub, cube_size, tag, fixes)
                        _open_platform_anchor(cube, new_direction, new_anchor,
                                               sub, cube_size, tag, fixes)
                elif not a.get("landing"):
                    a["landing"] = True
                    fixes.append(f"{tag}: landing:true added (no non-duplicate L{target_lvl} relocation available)")

    return patched, fixes


# ---------------------------------------------------------------------------
# Validation — grammar compliance + accessibility + file integrity

def validate(spec, resolved, glb_path=None):
    """Run deterministic checks on a resolved spec + exported .glb.

    Returns a report dict with a pass/fail, summary counts, and a list of
    individual check results (status ∈ {ok, warn, error})."""
    defaults = resolved.get("defaults", {})
    cube_size = defaults.get("cube_size_m", CUBE_SIZE)
    subs = defaults.get("subdivisions", SUB)
    sub = cube_size / subs
    lod = defaults.get("lod", LOD_DEFAULT)

    checks = []

    def _point_supported(p, cube_size, platforms_by_level, sub, tol=0.15):
        """Cube-local point. Supported if on ground, a cube face, or a platform cell."""
        x, y, z = p[0], p[1], p[2]
        # Ground plane (anywhere in xy)
        if abs(z) <= tol:
            return "ground"
        # Cube faces
        in_xy = (-tol <= x <= cube_size + tol) and (-tol <= y <= cube_size + tol)
        in_yz = (-tol <= y <= cube_size + tol) and (-tol <= z <= cube_size + tol)
        in_xz = (-tol <= x <= cube_size + tol) and (-tol <= z <= cube_size + tol)
        if abs(z - cube_size) <= tol and in_xy:
            return "cube_top"
        if (abs(x) <= tol or abs(x - cube_size) <= tol) and in_yz:
            return "cube_face_x"
        if (abs(y) <= tol or abs(y - cube_size) <= tol) and in_xz:
            return "cube_face_y"
        # Platforms
        for level, cells in platforms_by_level.items():
            if abs(z - level * sub) > tol:
                continue
            for (c, r) in cells:
                if (c * sub - tol <= x <= (c + 1) * sub + tol
                        and r * sub - tol <= y <= (r + 1) * sub + tol):
                    return f"platform_L{level}"
        return None

    def _add(status, name, message, details=None):
        checks.append({"name": name, "status": status, "message": message,
                        "details": details or {}})

    ok = lambda n, m="", d=None: _add("ok", n, m, d)
    warn = lambda n, m, d=None: _add("warn", n, m, d)
    err = lambda n, m, d=None: _add("error", n, m, d)

    # Grammar invariants (constant, but verify)
    if cube_size != 10.8:
        err("grammar.cube_size", f"cube_size_m={cube_size}, grammar requires 10.8")
    if subs != 3:
        err("grammar.subdivisions", f"subdivisions={subs}, grammar requires 3")

    for f_idx, folie in enumerate(resolved.get("folies", [])):
        tag = f"folie[{f_idx}]@{folie.get('grid_pos')}"
        cube = folie.get("cube", {})
        attachments = folie.get("attachments", []) or []

        # Solid cells in [0,2]^3
        solid_cells = cube.get("solid_cells", [])
        bad = [c for c in solid_cells if not all(0 <= c[i] <= 2 for i in range(3))]
        if bad:
            err(f"{tag}.solid_cells", f"{len(bad)} cells out of [0,2]^3", {"bad": bad})
        else:
            ok(f"{tag}.solid_cells", f"{len(solid_cells)} valid")

        # Platforms
        platforms = cube.get("platforms", []) or []
        platform_levels = set()
        platform_cells_by_level = {}
        for p_idx, plat in enumerate(platforms):
            level = plat.get("level")
            if level not in (1, 2, 3):
                err(f"{tag}.platform[{p_idx}]", f"level={level}, must be 1|2|3")
                continue
            cells = plat.get("cells", [])
            for c in cells:
                if not (0 <= c[0] <= 2 and 0 <= c[1] <= 2):
                    err(f"{tag}.platform[{p_idx}]", f"cell {c} out of [0,2]^2")
            platform_levels.add(level)
            platform_cells_by_level.setdefault(level, set()).update(tuple(c) for c in cells)
            ok(f"{tag}.platform[{p_idx}]", f"L{level} × {len(cells)} cell(s)")

        # Build platforms_by_level for touchpoint checking
        platforms_by_level = {}
        for plat in platforms:
            lvl = plat.get("level")
            if lvl in (1, 2, 3):
                platforms_by_level.setdefault(lvl, set()).update(
                    tuple(c) for c in plat.get("cells", [])
                )

        # Attachment-level checks
        ground_reaching = False
        reached_levels = set()
        # Track each attachment's bbox (cube-local) for overlap detection below
        attachment_bboxes = []

        for a_idx, a in enumerate(attachments):
            atype = a.get("type")
            a_tag = f"{tag}.attach[{a_idx}]:{atype}"

            if atype == "ramp":
                length = a.get("length_m")
                tilt = a.get("tilt_deg")
                if length is None or tilt is None:
                    err(a_tag, "missing length_m or tilt_deg")
                    continue
                if not (6 <= length <= 18):
                    warn(a_tag, f"length {length}m outside grammar [6, 18]")
                if not (10 <= tilt <= 35):
                    warn(a_tag, f"tilt {tilt}° outside grammar [10, 35]")
                anchor = a.get("anchor_m", [0, 0, 0])
                if abs(anchor[2]) < 0.1:
                    ground_reaching = True
                target_z = length * math.sin(math.radians(tilt))
                level_match = None
                for lvl in (1, 2, 3):
                    if abs(target_z - lvl * sub) < 0.25:
                        level_match = lvl
                        break
                # Touchpoint check: both anchor AND terminus must be supported
                direction = a.get("direction", [0, 0, 0])
                run = length * math.cos(math.radians(tilt))
                # direction xy (horizontal component)
                dh = math.hypot(direction[0], direction[1])
                if dh > 1e-9:
                    dh_x, dh_y = direction[0] / dh, direction[1] / dh
                else:
                    dh_x, dh_y = 0, 0
                terminus = [anchor[0] + dh_x * run, anchor[1] + dh_y * run, anchor[2] + target_z]
                a_sup = _point_supported(anchor, cube_size, platforms_by_level, sub)
                t_sup = _point_supported(terminus, cube_size, platforms_by_level, sub)
                if a_sup is None:
                    warn(f"{a_tag}.anchor_support", f"anchor {anchor} not on ground/cube/platform")
                if t_sup is None:
                    warn(f"{a_tag}.terminus_support", f"terminus {[round(v,2) for v in terminus]} not on ground/cube/platform")
                # bbox for overlap (expanded to include full slab extent)
                xmin = min(anchor[0], terminus[0]) - 1.0
                xmax = max(anchor[0], terminus[0]) + 1.0
                ymin = min(anchor[1], terminus[1]) - 1.0
                ymax = max(anchor[1], terminus[1]) + 1.0
                zmin = min(anchor[2], terminus[2]) - 0.2
                zmax = max(anchor[2], terminus[2]) + 1.5  # include balustrade
                attachment_bboxes.append((a_tag, (xmin, ymin, zmin, xmax, ymax, zmax)))
                if level_match is not None:
                    reached_levels.add(level_match)
                    ok(a_tag, f"len={length}m tilt={tilt}° → z={target_z:.2f}m (L{level_match})")
                else:
                    msg = f"terminus z={target_z:.2f}m doesn't match L1/L2/L3"
                    if a.get("landing"):
                        ok(a_tag, f"{msg} — landing:true")
                    else:
                        warn(a_tag, f"{msg} and no landing:true (mid-air terminus)")

            elif atype == "stair_cantilever":
                steps = a.get("steps", 12)
                rise = a.get("step_rise_m", 0.30)
                run = a.get("step_run_m", 0.30)
                anchor = a.get("anchor_m", [0, 0, 0])
                direction = a.get("direction", [0, 0, 0])
                dh = math.hypot(direction[0], direction[1])
                dh_x, dh_y = (direction[0] / dh, direction[1] / dh) if dh > 1e-9 else (0, 0)
                terminus_z = anchor[2] + steps * rise
                terminus = [anchor[0] + dh_x * steps * run, anchor[1] + dh_y * steps * run, terminus_z]
                level_match = None
                for lvl in (1, 2, 3):
                    if abs(terminus_z - lvl * sub) < 0.3:
                        level_match = lvl
                        break
                if level_match is not None:
                    reached_levels.add(level_match)
                if not (8 <= steps <= 20):
                    warn(a_tag, f"steps={steps} outside grammar [8,20]")
                # Touchpoint check
                a_sup = _point_supported(anchor, cube_size, platforms_by_level, sub)
                t_sup = _point_supported(terminus, cube_size, platforms_by_level, sub)
                if a_sup is None:
                    warn(f"{a_tag}.anchor_support", f"anchor {anchor} not on ground/cube/platform")
                if t_sup is None:
                    warn(f"{a_tag}.terminus_support",
                         f"terminus {[round(v,2) for v in terminus]} not on ground/cube/platform (cantilever hanging)")
                # bbox for overlap
                xmin = min(anchor[0], terminus[0]) - 0.8
                xmax = max(anchor[0], terminus[0]) + 0.8
                ymin = min(anchor[1], terminus[1]) - 0.8
                ymax = max(anchor[1], terminus[1]) + 0.8
                zmin = min(anchor[2], terminus[2]) - 0.2
                zmax = max(anchor[2], terminus[2]) + 1.2
                attachment_bboxes.append((a_tag, (xmin, ymin, zmin, xmax, ymax, zmax)))
                if level_match is None and not a.get("landing"):
                    warn(a_tag, f"terminus z={terminus_z:.2f}m not at a platform and no landing:true")
                else:
                    ok(a_tag, f"{steps} steps → z={terminus_z:.2f}m" + (f" (L{level_match})" if level_match else ""))

            elif atype == "stair_helical":
                anchor = a.get("anchor_m", [0, 0, 0])
                top_z = a.get("top_z_m")
                radius = a.get("radius_m", 1.2)
                if abs(anchor[2]) < 0.1:
                    ground_reaching = True
                if top_z is None:
                    err(a_tag, "missing top_z_m")
                else:
                    total_rise = top_z - anchor[2]
                    if total_rise <= 0:
                        err(a_tag, f"top_z_m={top_z} must be above anchor z={anchor[2]}")
                    elif not (0.8 <= radius <= 2.0):
                        warn(a_tag, f"radius_m={radius} outside grammar [0.8, 2.0]")
                    else:
                        level_match = None
                        for lvl in (1, 2, 3):
                            if abs(top_z - lvl * sub) < 0.3:
                                level_match = lvl
                                break
                        if level_match is not None:
                            reached_levels.add(level_match)
                        # Support: bottom and top points (same xy, different z)
                        terminus = [anchor[0], anchor[1], top_z]
                        a_sup = _point_supported(anchor, cube_size, platforms_by_level, sub)
                        t_sup = _point_supported(terminus, cube_size, platforms_by_level, sub)
                        if a_sup is None:
                            warn(f"{a_tag}.anchor_support",
                                 f"axis base {anchor} not on ground/cube/platform")
                        if t_sup is None:
                            warn(f"{a_tag}.top_support",
                                 f"axis top {terminus} not on ground/cube/platform")
                        steps_count = max(1, int(round(total_rise / 0.18)))
                        revs = a.get("revolutions") or max(0.5, total_rise / 3.6)
                        ok(a_tag, f"helical rise {total_rise:.1f}m, r={radius}m, "
                                  f"{steps_count} steps, {revs:.1f} revolutions"
                                  + (f" → L{level_match}" if level_match else ""))
                        # Cylindrical bbox (axis at anchor xy, radius_m + 0.2 margin for balustrade)
                        bb = (anchor[0] - radius - 0.2, anchor[1] - radius - 0.2, anchor[2],
                              anchor[0] + radius + 0.2, anchor[1] + radius + 0.2, top_z)
                        attachment_bboxes.append((a_tag, bb))

            elif atype in ("cylinder_tower", "cylinder_drum"):
                r = a.get("radius_m")
                anchor = a.get("anchor_m") or [0, 0, 0]
                if atype == "cylinder_tower":
                    h = a.get("height_m")
                    if r is None or h is None:
                        err(a_tag, "missing radius_m or height_m")
                    else:
                        if not (0.5 <= r <= 2.5 and 2 <= h <= 14):
                            warn(a_tag, f"r={r} h={h} outside grammar")
                        else:
                            ok(a_tag, f"r={r}m h={h}m")
                        bb = (anchor[0] - r, anchor[1] - r, anchor[2],
                              anchor[0] + r, anchor[1] + r, anchor[2] + h)
                        attachment_bboxes.append((a_tag, bb))
                else:
                    l = a.get("length_m")
                    d = a.get("direction") or [0, 0, 0]
                    if r is None or l is None:
                        err(a_tag, "missing radius_m or length_m")
                    else:
                        ok(a_tag, f"r={r}m len={l}m")
                        # Drum: axis from anchor to anchor+direction*length; bbox around the cylinder
                        nd = math.sqrt(sum(di * di for di in d)) or 1
                        end = [anchor[i] + d[i] / nd * l for i in range(3)]
                        xs = [anchor[0], end[0]]; ys = [anchor[1], end[1]]; zs = [anchor[2], end[2]]
                        bb = (min(xs) - r, min(ys) - r, min(zs) - r,
                              max(xs) + r, max(ys) + r, max(zs) + r)
                        attachment_bboxes.append((a_tag, bb))

            elif atype in ("wedge", "curved_plane", "cantilever_beam", "canopy"):
                ok(a_tag, "present")
                # Coarse bbox — sufficient for overlap detection. Uses conservative extents.
                anchor = a.get("anchor_m") or [0, 0, 0]
                if atype == "wedge":
                    half_w = a.get("width_m", 3) / 2
                    length = a.get("length_m", 4)
                    h = a.get("height_m", 3)
                    bb = (anchor[0] - half_w - length, anchor[1] - half_w - length, anchor[2],
                          anchor[0] + half_w + length, anchor[1] + half_w + length, anchor[2] + h)
                    attachment_bboxes.append((a_tag, bb))
                elif atype == "curved_plane":
                    r = a.get("radius_m", 4)
                    h = a.get("height_m", 7.2)
                    bb = (anchor[0] - r, anchor[1] - r, anchor[2],
                          anchor[0] + r, anchor[1] + r, anchor[2] + h)
                    attachment_bboxes.append((a_tag, bb))
                elif atype == "canopy":
                    w = a.get("width_m", 4) / 2
                    d = a.get("depth_m", 2.5)
                    bb = (anchor[0] - w - d, anchor[1] - w - d, anchor[2] - 0.2,
                          anchor[0] + w + d, anchor[1] + w + d, anchor[2] + 0.2)
                    attachment_bboxes.append((a_tag, bb))
                # cantilever_beam skipped intentionally (thin line element, bbox near-zero volume)

            elif atype == "raw_beam":
                f = a.get("from_m")
                t = a.get("to_m")
                if f is None or t is None:
                    err(a_tag, "missing from_m or to_m")
                else:
                    length = math.sqrt(sum((t[i] - f[i]) ** 2 for i in range(3)))
                    if length > 15:
                        warn(a_tag, f"length {length:.1f}m > 15m — raw_beam is cantilever-by-design, keep short")
                    else:
                        ok(a_tag, f"raw beam {length:.1f}m")

            else:
                err(a_tag, f"unknown attachment type '{atype}'")

        # Overlap check — pairwise AABB overlap in cube-local coords.
        # Flag when two attachment bboxes overlap by >50% of the smaller bbox volume.
        def _bbox_overlap_ratio(a, b):
            ix = max(0.0, min(a[3], b[3]) - max(a[0], b[0]))
            iy = max(0.0, min(a[4], b[4]) - max(a[1], b[1]))
            iz = max(0.0, min(a[5], b[5]) - max(a[2], b[2]))
            inter_vol = ix * iy * iz
            if inter_vol <= 0:
                return 0.0
            vol_a = (a[3] - a[0]) * (a[4] - a[1]) * (a[5] - a[2])
            vol_b = (b[3] - b[0]) * (b[4] - b[1]) * (b[5] - b[2])
            return inter_vol / max(min(vol_a, vol_b), 1e-6)

        for i in range(len(attachment_bboxes)):
            for j in range(i + 1, len(attachment_bboxes)):
                tag_i, bb_i = attachment_bboxes[i]
                tag_j, bb_j = attachment_bboxes[j]
                ratio = _bbox_overlap_ratio(bb_i, bb_j)
                if ratio > 0.5:
                    warn(f"{tag}.overlap",
                         f"{tag_i.split('.')[-1]} and {tag_j.split('.')[-1]} overlap {ratio*100:.0f}% (may be intentional intersection)")

        # Accessibility (LOD 300 only). §R2: all platforms must be reachable — hard error.
        if lod >= 300 and platforms:
            if not ground_reaching:
                err(f"{tag}.accessibility",
                    "no attachment originates from ground (z≈0) — folie is unreachable from outside")
            unreached = platform_levels - reached_levels
            if unreached:
                err(f"{tag}.accessibility",
                    f"platform levels {sorted(unreached)} have no ramp/stair terminating there (§R2)")
            else:
                ok(f"{tag}.accessibility",
                   f"all platform levels {sorted(platform_levels)} reached by an attachment")

    # File-integrity / Y-up check
    if glb_path is not None:
        glb_path = Path(glb_path)
        if not glb_path.exists():
            err("export.file", f"{glb_path} missing after export")
        else:
            try:
                loaded = trimesh.load(str(glb_path))
                if loaded.geometry:
                    v = np.vstack([g.vertices for g in loaded.geometry.values()])
                    xext = v[:, 0].max() - v[:, 0].min()
                    yext = v[:, 1].max() - v[:, 1].min()
                    zext = v[:, 2].max() - v[:, 2].min()
                    details = {"x": float(xext), "y": float(yext), "z": float(zext)}
                    if defaults.get("export_yup", True):
                        # After Y-up conversion, "up" data sits in Y. Cube height (10.8) should
                        # appear in Y-extent; ramp/plan spread in Z-extent.
                        if yext < cube_size - 0.2:
                            err("export.yup", f"y-extent {yext:.2f}m < cube size {cube_size}m — Y-up conversion failed",
                                details)
                        else:
                            ok("export.yup", f"Y-up confirmed (y-ext {yext:.1f}m)", details)
                    else:
                        if zext < cube_size - 0.2:
                            err("export.zup", f"z-extent {zext:.2f}m < cube size — Z-up export failed", details)
                        else:
                            ok("export.zup", f"Z-up confirmed (z-ext {zext:.1f}m)", details)
            except Exception as e:
                err("export.readback", f"failed to re-read glb: {e}")

    n_ok = sum(1 for c in checks if c["status"] == "ok")
    n_warn = sum(1 for c in checks if c["status"] == "warn")
    n_err = sum(1 for c in checks if c["status"] == "error")
    return {
        "glb_path": str(glb_path) if glb_path else None,
        "passed": n_err == 0,
        "summary": {"total": len(checks), "ok": n_ok, "warn": n_warn, "error": n_err},
        "checks": checks,
    }


def serve_and_open(out_dir: Path, glb_path: Path, viewer_html: Path, port: int = 8765):
    import http.server, socketserver, threading, urllib.parse, webbrowser, time

    serve_root = viewer_html.parent
    rel_glb = glb_path.resolve().relative_to(serve_root.resolve())

    os.chdir(str(serve_root))
    handler = http.server.SimpleHTTPRequestHandler

    # Retry a few ports if the default is in use
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = socketserver.TCPServer(("", p), handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("Could not bind a local port for the viewer.", file=sys.stderr)
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://localhost:{port}/viewer.html?src={urllib.parse.quote(str(rel_glb))}"
    print(f"Viewer: {url}")
    webbrowser.open(url)
    print("Ctrl+C to stop the server.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")


def _run_once(spec, out_dir, name, write_glb=True):
    """Build + optionally export once. Returns (resolved, glb_path|None)."""
    scene, resolved = build_scene(spec)
    glb_path = out_dir / f"{name}.glb" if write_glb else None
    if glb_path is not None:
        scene.export(glb_path)
    return resolved, glb_path


def main():
    parser = argparse.ArgumentParser(description="Tschumi Folie Generator")
    parser.add_argument("--spec", required=True, help="Path to JSON spec")
    parser.add_argument("--out", default="./out", help="Output directory")
    parser.add_argument("--open", action="store_true", help="Open viewer after generation")
    parser.add_argument("--no-fix", action="store_true",
                        help="Disable the autofix feedback loop (default: enabled).")
    parser.add_argument("--max-iterations", type=int, default=5,
                        help="Max autofix iterations (default: 5).")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = (script_dir / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(spec_path) as f:
        spec = json.load(f)
    name = spec.get("name") or spec_path.stem

    # Pass 1: materialize random (seed-based) attachments into explicit spec form,
    # without writing the .glb. This gives autofix concrete attachments to patch.
    resolved_first, _ = _run_once(spec, out_dir, name, write_glb=False)
    working_spec = {
        "name": spec.get("name"),
        "defaults": spec.get("defaults", {}),
        "folies": [
            {"grid_pos": r["grid_pos"], "seed": r.get("seed"),
             "cube": r.get("cube", {}), "attachments": r.get("attachments", [])}
            for r in resolved_first.get("folies", [])
        ],
    }

    # Autofix loop on the materialized spec
    all_fixes = []
    if not args.no_fix:
        for i in range(args.max_iterations):
            patched, fixes = autofix_spec(working_spec)
            if not fixes:
                break
            working_spec = patched
            all_fixes.extend((i + 1, f) for f in fixes)

    # Pass 2: build from the (possibly autofixed) explicit spec, export .glb
    resolved, glb_path = _run_once(working_spec, out_dir, name, write_glb=True)
    spec = working_spec  # for validation below
    resolved_path = out_dir / f"{name}.spec.json"
    with open(resolved_path, "w") as f:
        json.dump(resolved, f, indent=2)

    print(f"Wrote: {glb_path}")
    print(f"Spec:  {resolved_path}")
    print(f"Folies: {len(resolved['folies'])}")

    if all_fixes:
        print(f"Autofix applied {len(all_fixes)} patch(es):")
        for iter_n, f in all_fixes:
            print(f"  [iter {iter_n}] {f}")

    report = validate(spec, resolved, glb_path=glb_path)
    validation_path = out_dir / f"{name}.validation.json"
    with open(validation_path, "w") as f:
        json.dump(report, f, indent=2)
    s = report["summary"]
    status_word = "PASS" if report["passed"] else "FAIL"
    print(f"Valid: {status_word}  ok={s['ok']} warn={s['warn']} error={s['error']}  → {validation_path}")
    for c in report["checks"]:
        if c["status"] in ("warn", "error"):
            sym = "!" if c["status"] == "warn" else "✗"
            print(f"  {sym} [{c['name']}] {c['message']}")

    if args.open:
        viewer_html = script_dir / "viewer.html"
        serve_and_open(out_dir, glb_path, viewer_html)


if __name__ == "__main__":
    main()
