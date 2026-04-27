# Folie Grammar — Formal Rule System

Canonical rule system for generating Tschumi-compliant folies. Every output must conform.

## 1. Base envelope (constants)

| Parameter | Value | Notes |
|---|---|---|
| Cube edge length | **10.8 m** | Never vary |
| Subdivisions per axis | **3** | Sub-cube = 3.6 m |
| Frame member section | **0.12 × 0.12 m** | Box section, steel |
| Panel thickness | **0.05 m** | For clad faces / solid cells |
| Primary colour | **#C8102E** (approx RAL 3020 family) | PBR: metallic 0.2, roughness 0.45 |
| Grid spacing (park) | **120 m** orthogonal | Folies at grid intersections |

## 2. Cube states

The reference cube can be expressed in three progressive states:

### 2a. Frame — `"frame"`
Outer 12 edges as box sections. Always present.

### 2b. Subdivision frame — `"subdivision_frame"`
A complete 3×3×3 skeleton outlining every sub-cube:
- Perimeter rings at each intermediate z-level (z = 3.6, 7.2 m)
- Vertical members on the 4 outer vertical faces at the 1/3 positions
- Grid on top and bottom faces at the 1/3 positions (both directions)
- **Interior crossbars** at each intermediate z-level threading through the cube (so empty cells still read as grid cells from any angle)
- **4 interior vertical columns** at the sub-grid intersections (3.6, 3.6), (3.6, 7.2), (7.2, 3.6), (7.2, 7.2) running the full height

This is the characteristic Tschumi cage. Default on; set `"show_subdivision_frame": false` for a minimalist folie.

### 2c. Solid cells — `"solid_cells"`
List of `(i, j, k)` cell indices in `[0, 2]^3` that are rendered as solid 3.6 m red volumes (clad on all faces). Every folie has between 0 and ~8 solid cells. More than ~10 loses the frame character.

### 2d. Dislocation
A cell can be shifted off the grid:
```json
{ "cell": [i,j,k], "offset_m": [dx, dy, dz] }
```
Magnitude typically 0.5–2.5 m. Dislocation is applied to the solid rendering of the cell only; the frame stays on the grid.

## 3. Attachment vocabulary

Every attachment has:
- `type` — from the enumeration below
- `anchor` — a point on/near the cube in cube-local coordinates (metres, origin at cube's lower corner)
- `direction` — a 3-vector (outward) specifying which way the attachment grows
- `rotation_deg` — rotation about the direction axis (usually 0, 45, or 90)
- `tilt_deg` — tilt from the natural orientation (0–30)

### 3a. `ramp`
Inclined plane on trusses.
- `length_m` — 6 to 18
- `width_m` — 1.2 to 2.4
- `tilt_deg` — 15 to 25 (ramp slope)
- `balustrade` — boolean, default true

### 3b. `stair_cantilever`
Open-tread stair cantilevered off a face. The default is a **one-module stair**: 12 steps × 0.30 m rise × 0.30 m run = 3.6 m × 3.6 m (exactly one sub-cell footprint). This lets the stair run from one platform cell directly to the adjacent platform cell one level up.
- `steps` — 8 to 16
- `width_m` — 0.9 to 1.5
- `step_rise_m` — 0.30 (fixed; was 0.18 pre-2026-04-23)
- `step_run_m` — 0.30 (fixed; was 0.28 pre-2026-04-23)
- `balustrade` — boolean, default true

A stair is ~45° — architecturally steep, but Villette's cantilevered stairs are typically steep. The 1-module geometry means stairs always start on a platform and end on the adjacent-cell platform at the next sub-tier — no more calibration math for authors.

### 3j. `stair_helical`
Spiral staircase wrapping a vertical axis. Villette signature move (the Belvedere folie).
- `anchor_m` — `[x, y, z_bottom]`, the axis base. Must be on ground or a platform cell.
- `top_z_m` — absolute z of the top. Must be supported (platform cell at that z, or cube top `z = 10.8`).
- `radius_m` — 0.8 to 2.0 (outer radius; inner is a fixed 0.15 m central post).
- `revolutions` — float, optional. Defaults to `(top_z_m - anchor[2]) / 3.6` (one revolution per 3.6 m of rise).
- `clockwise` — boolean, default true (viewed from above).
- `central_post` — boolean, default true.
- `balustrade`, `mid_rail` — booleans, default true. Rail is a step-polyline on the outer radius (approximates a true helical rail).
- `landing` — boolean, default false. If true, emits a **pac-man landing deck** at `top_z_m`: a 3.6 m square (one sub-cell footprint) centred on the axis, with a 3/4 annular void cut around the axis. The remaining 1/4 "tongue" is oriented at the last tread's angular position, so the walker steps from the last tread onto the tongue and then onto the surrounding deck. Pair with `platforms.cutout_cells` on the enclosing platform so the surrounding cells treat this one as continuous (no balustrade across the shared edge).
- Step rise fixed at 0.18 m (matches the helical's own convention, not `stair_cantilever`); step count is derived from total rise.

Counts as a **single attachment** regardless of rise, so one helical stair can do ground→L3 (10.8 m) — a move no ramp or `stair_cantilever` can make in one flight.

### 3c. `cylinder_tower`
Vertical cylinder, anchored to top or corner.
- `radius_m` — 0.8 to 1.8
- `height_m` — 4 to 12
- `hollow` — boolean, if true render as ring (wall thickness 0.1 m)

### 3d. `cylinder_drum`
Horizontal cylinder, anchored to a face.
- `radius_m` — 1.2 to 2.4
- `length_m` — 3 to 8
- `hollow` — boolean

### 3e. `wedge`
Triangular prism. Right-triangle cross-section, extruded along direction.
- `length_m` — 3 to 8 (extrusion)
- `width_m` — 2 to 5 (base of triangle)
- `height_m` — 3 to 6 (rise of triangle)

### 3f. `curved_plane`
Partial-cylindrical wall attached to a cube face.
- `anchor_m` is the **chord midpoint on the face** (not the arc's center)
- `direction` is the outward face normal
- The arc's two chord endpoints sit exactly on the face plane; the arc bulges outward by the sagitta `radius × (1 − cos(sweep/2))`
- `radius_m` — 3 to 6
- `height_m` — 3.6 to 10.8
- `sweep_deg` — 45 to 180 (90° ≈ 1.17 m bulge at radius 4)
- `wall_thickness_m` — 0.1

### 3g. `cantilever_beam`
Projecting beam.
- `length_m` — 3 to 8
- `section_m` — [0.2, 0.3] typical

### 3h. `canopy`
Horizontal overhanging plane, typically over an entry.
- `width_m` — 2 to 6
- `depth_m` — 1.5 to 4
- `thickness_m` — 0.1

### 3i. `raw_beam` — the untyped primitive
Escape hatch from the typed vocabulary. A beam between two arbitrary points in space. Use when you need a sculptural extrusion, a structural link between dislocated pieces, or any linear element that doesn't fit the named attachment types.

```json
{ "type": "raw_beam", "from_m": [x1, y1, z1], "to_m": [x2, y2, z2], "section_m": 0.12 }
```

- No anchor/direction semantics — just two endpoints
- Exempt from the touchpoint rule (§9a) — raw_beam is a cantilever-by-design primitive
- Length cap — 15 m
- Use sparingly. If you reach for `raw_beam` repeatedly it probably means a new typed attachment should exist in the grammar.

### Grouped dislocation

`dislocated_cells` accepts two forms:

Single cell:
```json
{ "cell": [2, 2, 2], "offset_m": [1.5, 0, 0] }
```

Group (many cells share one offset — use for dislocating an entire tier or slab):
```json
{ "cells": [[0,0,2],[1,0,2],[2,0,2],[0,1,2],[1,1,2],[2,1,2],[0,2,2],[1,2,2],[2,2,2]],
  "offset_m": [1.8, 0, 0] }
```

At LOD 300 the group is rendered with boundary-dedup (internal faces between adjacent group members are skipped), producing a clean slab-shaped volume rather than 9 overlapping panels.

## 4. Valid anchor points on cube

Given cube at origin with edge size 10.8 m, valid anchor points are:

### Face centres (6)
```
(5.4, 5.4, 0)     bottom
(5.4, 5.4, 10.8)  top
(0, 5.4, 5.4)     -x face
(10.8, 5.4, 5.4)  +x face
(5.4, 0, 5.4)     -y face
(5.4, 10.8, 5.4)  +y face
```

### Corners (8)
All combinations of `{0, 10.8}` in each axis.

### Edge midpoints (12)
Midpoints of the 12 outer cube edges.

### Subdivision nodes (available but less common)
Intersections on cube faces at 1/3 spacing: e.g. `(3.6, 0, 3.6)` on the -y face.

## 5. Transformation rules

An attachment may be transformed by:
- **Rotate about its direction axis** — angles from `{0, 45, 90, 180}`
- **Tilt off its natural orientation** — 0–30° (e.g. a cantilever beam tilted down 15°)
- **Offset along direction** — 0 to 2 m away from anchor (for elements that don't touch the cube)

## 6. Assembly rules

- A single folie contains: 1 cube (always) + 0 to ~10 solid cells + 2 to 6 attachments.
- Attachments should not occupy the same anchor point (de-duplicate).
- Attachments should be distributed across multiple faces for visual variety — no more than 2 attachments per face.
- At least one attachment should interact with the cube's ground plane (ramp lands on ground, stair reaches ground, cylinder tower stands on ground, etc.).

## 7. Field rules

When generating multiple folies on the park grid:
- Each folie occupies a distinct `grid_pos = (col, row)` where `col, row ∈ Z`
- Folie origin in world coordinates = `(col * 120, row * 120, 0)`
- No two folies share a grid position
- The user selects which grid positions to occupy

## 8. Level of detail & accessibility

The generator supports two LOD modes, controlled by `defaults.lod` in the spec. Default is **300**.

### LOD 200 — massing / field-scale
- Solid cells rendered as monolithic 3.6m cubes
- Simple balustrade (top rail + posts)
- No platforms, no landings
- Solid-plate stair treads
- ~1,500 triangles per folie; use for 20+ folie fields or AI training data

### LOD 300 — accessible visualisation (default)
- **Framed panels**: solid cells become 6 thin (50mm) panels on boundary faces only (internal faces between adjacent solid cells are deduped). Panels are inset 80mm from the frame so the frame is visible around each panel.
- **Platforms**: horizontal decks at subdivision Z levels (3.6, 7.2, 10.8 m), occupying 1–9 sub-cells in plan. Perimeter automatically gets a full balustrade.
- **Landings**: 2.4×2.4 m platform at the terminus of a ramp or stair (opt-in via `landing: true`).
- **Full balustrades**: top rail at 1.0 m + mid rail at 0.5 m + posts every 1.5 m on ramps, stairs, platforms, landings. Open on the ingress/egress edge of each landing.
- ~3,000 triangles per folie.

### Accessibility rules (LOD 300)
- At least one platform must be reachable from the ground via a ramp or stair. The random generator enforces this; user specs should include it explicitly.
- Every ramp and stair with `landing: true` is treated as "accessible" — it terminates on a walkable deck with edge protection, with the approach edge left open.
- Platform edges automatically get balustrades on all unshared perimeter segments.
- Ramps and stairs have balustrades on both sides.

### Dimensional honesty at LOD 300
- Stair tread 280mm, rise 180mm (typical building code range)
- Ramp slopes 15–25° for z=3.6 terminus, 25–30° for z=7.2 (steeper than code but Tschumi-authentic)
- Handrail height 1.0 m, mid rail 0.5 m
- Deck thickness 100mm
- Panel thickness 50mm
- Posts 1.5 m on centre on every rail in the project (straight or curved). Rails follow the geometry of the boundary they protect: on straight edges they are straight; on curved edges (e.g. the 270° arc around a helical hole) they are tessellated finely (≤15 cm per segment) so the rail reads as round, while posts remain sampled at the 1.5 m project default — never one post per tessellation vertex.

## 9. Support requirements

Every attachment must be physically plausible — i.e. visibly supported by the ground, the cube, or a platform. A "supported point" is any point that is:

- At `z = 0` (on the ground plane, anywhere in xy), or
- On a cube face (one of `x=0`, `x=10.8`, `y=0`, `y=10.8`, `z=0`, `z=10.8`, with the other two coordinates within cube bounds), or
- Within a platform cell at the platform's z-level.

### 9a. Linear attachments — both ends must be supported
Applies to: **ramp**, **stair_cantilever**.

Both the anchor and the terminus must be supported points. If the terminus is in mid-air (outside the cube AND not on ground AND not on a platform), the attachment is structurally impossible. Adding `landing: true` does NOT satisfy this — a landing is itself an unsupported deck unless it sits on the cube or ground.

### 9b. Cantilever-by-design — free-end allowance with length caps
Applies to: **cantilever_beam**, **canopy**.

These are cantilever elements by definition; the free end is the point. Keep them short so the cantilever reads as plausible:
- `cantilever_beam.length_m` ≤ 6
- `canopy.depth_m` ≤ 4

### 9c. Volumetric attachments — base contact
Applies to: **cylinder_tower**, **cylinder_drum**, **wedge**, **curved_plane**.

These sit against a cube face (drum, wedge, curved_plane) or on a cube face / ground (tower). The contact surface itself is the support.

### 9d. Platform ingress — balustrade must open at the arrival edge
Applies to: **ramp**, **stair_cantilever** whose terminus lands on a platform cell.

A platform's default balustrade wraps its whole perimeter, which would block a ramp or stair walker from stepping onto the deck. The edge of the target cell aligned with the attachment's arrival direction must be listed in the platform's `open_sides` (format `[col, row, "x+"|"x-"|"y+"|"y-"]`). The autofix derives the ingress edge from the attachment's terminus and direction and adds it automatically — authors do not need to compute `open_sides` manually for ramp/stair arrivals.

### 9e. Helical axis support
Applies to: **stair_helical**.

The axis base (`anchor_m`) and the axis top (`[x, y, top_z_m]`) must each be supported — on ground, on a cube face, or inside a platform cell at the matching z. The validator flags unsupported helical endpoints; no autofix relocates them (the axial nature of the primitive means relocation changes the composition's meaning).

## 9bis. Accessibility rules (hard)

These are validation errors, not warnings — a folie that violates them does not build.

### R1. Every cube has a platform on top
The `preprocess_spec` step auto-adds a full 3×3 L3 roof to any cube that has at least one attachment reaching `z ≈ cube_size` (ramp/stair `target_z_m` or helical `top_z_m`). Authors can force a roof with `cube.force_auto_roof: true`, or opt out with `cube.skip_auto_roof: true` (for intentional open-topped variants).

The reachability precondition is required by R2 — auto-adding a roof when no attachment reaches it would create an unreachable platform and the build would fail. This pattern (auto-feature must validate its own preconditions) generalises to any future "default-on" injection in `preprocess_spec`.

### R2. Every platform is reachable
Each platform level (1, 2, 3) present in a cube must be the terminus of at least one ramp, stair, or helical. The validator raises a hard error if a platform has no attachment landing on it. An attachment originating at `z ≈ 0` must also exist so the folie is reachable from outside. Chains are allowed: ground → L1 ramp → L1→L2 stair → L2→L3 helical covers all three.

### R3. Balustrades do not overlap cube faces
A platform cell whose outer edge coincides with a cube face (col=0, col=SUB-1, row=0, row=SUB-1) does **not** emit a balustrade on that edge — the cube's structural frame already terminates the floor, and a rail hugging the wall reads as a double wall. `make_platform` skips those edges unconditionally.

### R4. Stairs and ramps influence railings at BOTH ends
The autofix opens the platform balustrade at the **terminus** (ingress, §9d) AND at the **anchor** (egress) of every ramp and stair_cantilever that sits on a platform. At the anchor side the opened edge is the cell face adjacent to the anchor point and perpendicular to the direction of travel, so the walker can step off the platform onto the stair/ramp without colliding with a rail.

## 10. Non-overlap rule

Attachments should not occupy substantially the same volume. The validator uses an axis-aligned bounding-box check and flags pairs whose bbox overlap exceeds 50% of the smaller bbox volume.

**Intentional intersections are allowed and common:**
- A ramp passing through a cube frame member (the frame is thin, ramp bbox contains it trivially)
- A cylinder drum that clips into the cube (signature Villette look)
- A curved plane intersecting a balustrade post

The 50% threshold targets gross collisions — e.g. two independent ramps picking the same face at the same height, or two stairs stacked in identical space.

## 11. Banned operations

These are outside the grammar:
- Cube sizes other than 10.8 m
- Subdivisions other than 3
- Non-red primary material
- Glazing systems, furniture, handrails outside the balustrade vocabulary
- Organic/curved primary forms (curved planes are allowed only as attachments, not as replacements for the cube)
- Off-grid placement in a multi-folie field
