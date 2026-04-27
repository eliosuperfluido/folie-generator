#!/usr/bin/env python3
"""
Render a folie .glb to four orthographic PNG views so Claude (or anyone) can
see the output without opening a 3D viewer.

Outputs per .glb:
  <out>/<name>_axo-ne.png   — axonometric from upper SE (classic architectural 3/4 view)
  <out>/<name>_axo-sw.png   — axonometric from upper NW (opposite 3/4 view)
  <out>/<name>_elev-s.png   — south elevation, eye-level
  <out>/<name>_plan.png     — plan from directly above
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


RED = "#C8102E"
GROUND = "#E8E4DC"
EDGE = "#7A0A1D"


def concat_scene(scene: trimesh.Scene) -> trimesh.Trimesh:
    """Concatenate all geometry in a scene into one mesh with world-space vertices.

    The generator pre-rotates the scene -90° about X before .glb export so the file
    is genuinely Y-up (per glTF 2.0 spec). Trimesh loads it as-is (Z-up), which leaves
    the model rotated 90°. We reverse that here by rotating +90° about X so the
    vertical axis is Z again, matching spec-space coords.
    """
    if isinstance(scene, trimesh.Trimesh):
        mesh = scene.copy()
    else:
        meshes = []
        for node_name in scene.graph.nodes_geometry:
            transform, geometry_name = scene.graph[node_name]
            part = scene.geometry[geometry_name].copy()
            part.apply_transform(transform)
            meshes.append(part)
        if not meshes:
            return trimesh.Trimesh()
        mesh = trimesh.util.concatenate(meshes)

    # Y-up → Z-up: rotate +90° about X. (x, y, z) → (x, -z, y)
    restore_z_up = trimesh.transformations.rotation_matrix(
        angle=np.pi / 2, direction=[1, 0, 0], point=[0, 0, 0],
    )
    mesh.apply_transform(restore_z_up)
    return mesh


def frame_poly3d(ax, mesh, facecolor=RED, edgecolor=EDGE, alpha=0.95):
    tris = mesh.vertices[mesh.faces]
    coll = Poly3DCollection(
        tris, facecolors=facecolor, edgecolors=edgecolor,
        linewidths=0.15, alpha=alpha,
    )
    ax.add_collection3d(coll)


def render_view(mesh, view, out_path, resolution=2048, title=None):
    """Render one orthographic view."""
    fig = plt.figure(figsize=(resolution / 200, resolution / 200), dpi=200)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_proj_type("ortho")

    # Optional 2D ground tone: a figure-level rectangle in the lower half.
    # Drawn as a Figure-level patch (not a 3D polygon), so it cannot intersect
    # the folie — it's always behind the 3D scene regardless of camera angle.
    bounds = mesh.bounds
    cx = (bounds[0][0] + bounds[1][0]) / 2
    cy = (bounds[0][1] + bounds[1][1]) / 2
    span = max(bounds[1][0] - bounds[0][0], bounds[1][1] - bounds[0][1], 20)
    # 1.5× zoom vs. original — comfortable for a single folie and still leaves
    # a 4×4 field readable at the edges of the frame.
    half = span * 0.533 + 4

    frame_poly3d(ax, mesh)

    # Axis bounds
    size = half
    ax.set_xlim(cx - size, cx + size)
    ax.set_ylim(cy - size, cy + size)
    ax.set_zlim(0, max(15, bounds[1][2] + 2))
    ax.set_box_aspect((1, 1, (bounds[1][2] + 2) / (2 * size)))

    # Four corner axonometric views (NE, SE, SW, NW) + south elevation + plan.
    # matplotlib azim convention: 0° = looking from +x toward origin; +90° = from +y
    if view == "axo-ne":
        ax.view_init(elev=28, azim=45)
    elif view == "axo-se":
        ax.view_init(elev=28, azim=-45)
    elif view == "axo-sw":
        ax.view_init(elev=28, azim=-135)
    elif view == "axo-nw":
        ax.view_init(elev=28, azim=135)
    elif view == "elev-s":
        ax.view_init(elev=2, azim=-90)
    elif view == "plan":
        ax.view_init(elev=89.9, azim=-90)
    else:
        raise ValueError(f"unknown view: {view}")

    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=10, pad=0)

    fig.subplots_adjust(left=0, right=1, top=0.95 if title else 1, bottom=0)
    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)


def render_folie(glb_path: Path, out_dir: Path, resolution=2048):
    scene = trimesh.load(str(glb_path))
    mesh = concat_scene(scene)
    if len(mesh.vertices) == 0:
        print(f"! empty mesh: {glb_path}", file=sys.stderr)
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    name = glb_path.stem

    views = [
        ("axo-ne", f"{name} — axonometric NE"),
        ("axo-se", f"{name} — axonometric SE"),
        ("axo-sw", f"{name} — axonometric SW"),
        ("axo-nw", f"{name} — axonometric NW"),
        ("elev-s", f"{name} — south elevation"),
        ("plan",   f"{name} — plan"),
    ]
    paths = []
    for view, title in views:
        out_path = out_dir / f"{name}_{view}.png"
        render_view(mesh, view, out_path, resolution=resolution, title=title)
        paths.append(out_path)
        print(f"  rendered: {out_path}")
    return paths


def main():
    parser = argparse.ArgumentParser(description="Render folie .glb to 4 orthographic PNGs")
    parser.add_argument("--glb", required=True, type=Path, help="Path to .glb")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory (default: sibling 'renders/' of the .glb)")
    parser.add_argument("--resolution", type=int, default=1024)
    args = parser.parse_args()

    glb_path = args.glb.resolve()
    if not glb_path.exists():
        print(f"! not found: {glb_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out if args.out else glb_path.parent / "renders"
    render_folie(glb_path, out_dir, resolution=args.resolution)


if __name__ == "__main__":
    main()
