# Folie Spec Schema

JSON format consumed by `execution/generate_folie.py`.

## Top-level

```json
{
  "name": "optional-name-for-output-file",
  "defaults": {
    "lod": 300,
    "color": "#C8102E",
    "metallic": 0.2,
    "roughness": 0.45,
    "frame_section_m": 0.12,
    "panel_thickness_m": 0.05,
    "cube_size_m": 10.8,
    "subdivisions": 3,
    "grid_spacing_m": 120
  },
  "folies": [ /* array of folie objects */ ]
}
```

`lod` is either **200** (monolithic solid cells, no platforms/landings) or **300** (framed panels, platforms, landings, full balustrades). Default 300.

Only `folies` is required. All defaults have built-in values.

## Folie object

```json
{
  "grid_pos": [col, row],
  "seed": 42,
  "cube": { /* cube object */ },
  "attachments": [ /* array of attachment objects */ ]
}
```

- `grid_pos` — optional. `[col, row]` integer grid cell. Defaults to `[0, 0]` (world origin). Only meaningful in a multi-folie field; omit for a single folie unless you specifically want it offset on the 120 m park grid.
- `seed` — optional. If present and `cube`/`attachments` are omitted, they are generated stochastically from this seed.
- `cube` — optional. If omitted, generator fills from seed.
- `attachments` — optional. If omitted, generator fills from seed.

## Cube object

```json
{
  "show_subdivision_frame": true,
  "solid_cells": [[0,0,2], [1,1,0]],
  "platforms": [
    { "level": 1, "cells": [[1,0], [1,1]], "balustrade": true, "mid_rail": true }
  ],
  "dislocated_cells": [
    { "cell": [2,2,2], "offset_m": [1.5, 0, 0] }
  ],
  "absent_edges": []
}
```

- `show_subdivision_frame` — default true
- `solid_cells` — list of `[i,j,k]` with each index in `[0,2]`
- `platforms` (LOD 300) — list of `{ level, cells, balustrade?, mid_rail?, open_sides? }`
  - `level` — integer 1/2/3 (z = level × 3.6 m)
  - `cells` — list of `[col, row]` pairs at that level
  - `open_sides` — optional list of edges to leave without balustrade, e.g. `["x+"]` or `[[col, row, "y-"]]`
- `dislocated_cells` — list of objects with `cell` and `offset_m`
- `absent_edges` — list of edge indices to omit from the main frame (advanced; default empty)

## Attachment object

Common fields:
```json
{
  "type": "ramp",
  "anchor_m": [5.4, 0, 3.6],
  "direction": [0, -1, 0],
  "rotation_deg": 0,
  "tilt_deg": 18,
  "landing": true
}
```

For `ramp` and `stair_cantilever`, `landing: true` adds a 2.4×2.4 m platform at the terminus (LOD 300 only). Plus type-specific fields per `folie-grammar.md` §3.

`stair_helical` uses `anchor_m` + `top_z_m` instead of `anchor_m` + `direction` (the primitive is axial, not directional). Example:
```json
{
  "type": "stair_helical",
  "anchor_m": [5.4, 5.4, 0],
  "top_z_m": 10.8,
  "radius_m": 1.5,
  "revolutions": 2.0,
  "clockwise": true
}
```

## Example — minimal (random)

```json
{
  "folies": [
    { "grid_pos": [0, 0], "seed": 1 },
    { "grid_pos": [1, 0], "seed": 2 },
    { "grid_pos": [0, 1], "seed": 3 }
  ]
}
```

## Example — fully specified single folie

```json
{
  "name": "folie-gate",
  "folies": [{
    "grid_pos": [3, 3],
    "seed": 42,
    "cube": {
      "show_subdivision_frame": true,
      "solid_cells": [[0,0,0], [0,0,1], [2,2,2]],
      "dislocated_cells": []
    },
    "attachments": [
      {
        "type": "ramp",
        "anchor_m": [5.4, 0, 3.6],
        "direction": [0, -1, 0],
        "length_m": 12, "width_m": 1.8, "tilt_deg": 18
      },
      {
        "type": "cylinder_tower",
        "anchor_m": [10.8, 10.8, 10.8],
        "radius_m": 1.2, "height_m": 6
      },
      {
        "type": "stair_cantilever",
        "anchor_m": [10.8, 5.4, 3.6],
        "direction": [1, 0, 0],
        "steps": 12, "width_m": 1.2
      },
      {
        "type": "curved_plane",
        "anchor_m": [5.4, 10.8, 5.4],
        "direction": [0, 1, 0],
        "radius_m": 4, "height_m": 7.2, "sweep_deg": 90
      }
    ]
  }]
}
```
