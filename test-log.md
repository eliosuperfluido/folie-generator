# Folie Generator — Test Log

Running log of generations, findings, and fixes. Update after each meaningful test session.

## How to use this log

- **Append, don't rewrite.** New sessions add entries at the top of "Sessions"; old entries stay for reference.
- **Findings** are observations that changed the grammar, generator, autofix, or validator.
- **Improvements** lists known gaps and next work — move items to "Sessions" once implemented.

---

## Sessions

### 2026-04-27 — Bug-hunt round on R3/R4 + viewer overlay system

A long iterative session that surfaced several engineering lessons now codified in SKILL.md's "Generator pitfalls" section.

**Sub-cell boundary snap.** The §9d ingress autofix appeared to work for ramps but silently no-op'd for the `stair_cantilever` in `folie-compound`. Cause: the terminus computation produced `7.199999…` (FP), and `int(7.2 // 3.6) == 1` rather than 2 — so the snap looked up cell `(1, 2)` on L2 (not present) instead of `(2, 2)`. Fixed with a direction-biased `_snap` helper that tolerates ~7 cm of slop and resolves boundary points to the cell the walker is *entering*. Lesson: any cell-index calculation that consumes an arithmetic result needs an explicit boundary-tolerance step.

**§R3 over-correction.** First implementation of "balustrade must not overlap cube face" dropped rails on every edge where `col ∈ {0, SUB-1}` or `row ∈ {0, SUB-1}`. The user immediately spotted the regression: cube faces *without* a solid cell at that level still need rails (fall protection at the cube perimeter). Refined: skip the rail only when a solid cell adjacent to the platform cell at the same level provides a wall. `solid_cells_3d` is now threaded through `make_platform`.

**Auto-roof reachability coupling.** The first version of R1 (auto-add L3 roof to every cube) made all the simpler showcase folies fail R2 — they had no attachment reaching z=10.8 so the new roof was unreachable. Refined: only auto-add the roof when an existing attachment's `target_z_m` or `top_z_m` is within 0.4 m of `cube_size`. Same lesson applies to any future "default-on" feature.

**Pac-man rotation.** The user requested the tongue rotated so one *edge* (not the centre) aligns with the last tread, then 90° in the opposite direction. Implemented as `tongue_center = last_angle ∓ tongue_half_rad` based on `clockwise`. The tongue now extends in the direction the spiral is winding, away from the descending-tread footprint.

**B2-IV hole rail.** Added a 270° fall-protection rail at the helical hole on the L3 roof, with the two rail ends terminating exactly at the tongue's flank edges. Two follow-up refinements: (1) the rail's post density was 96 (one per arc vertex from `_balustrade_segment`); fixed by separating the rail tessellation (48 segments, smooth curve) from the post sampling (5 posts at the project default 1.5 m spacing). (2) The top + mid rails now emit one short box-section per fine sample so the rail visually traces the round hole instead of a 5-sided polygon.

**Viewer overlay — labels.** Added two CSS2DRenderer toggles:
- **Edge labels** — 9 axis ticks at the cube perimeter (`A B C` columns cyan / `1 2 3` rows yellow / `I II III IV` heights magenta — IV is the roof slab).
- **Cell labels** — 27 layer-centre labels (`A1-I` … `C3-III`) plus 9 roof-slab labels (`A1-IV` … `C3-IV`) at z = 10.8 m.
Initial version had a coordinate-frame bug — labels placed using spec coordinates ended up east of the actual model. The exporter applies a Z-up → Y-up rotation, so the spec's Y axis (north–south) maps to the viewer's −Z; cell labels needed `(col+0.5)*sub, (layer+0.5)*sub, −(row+0.5)*sub`. Both toggles default to OFF and surface their state via an `.active` red-button class.

**SE / NW deck additions.** The user added cells `[2, 0]` (C1-II) and `[0, 2]` (A3-II) to the L1 platform — extending the central strip eastward and westward at the south and north edges respectively. The autofix automatically opened the stair_cantilever's anchor egress on both sides since the stair is now reachable from either A3 or B3.

**Process rule.** "Always render out views and validate the result" added to SKILL.md as a mandatory post-edit protocol. Validator catches grammar errors but not visual ones (post density, rail breaks, primitive overlap that passes bbox check); Reading at least one PNG before reporting done was the single highest-leverage discipline change to come out of this session.

---

### 2026-04-23 — Hard accessibility rules R1–R4

User flagged four accessibility issues in `folie-compound` screenshots and framed them as general rules:

- **R1.** Every cube has a platform on top → auto-add full 3×3 L3 roof in `preprocess_spec` when any attachment already reaches `z ≈ cube_size` (ramp `target_z_m`, helical `top_z_m`). Opt-out `cube.skip_auto_roof: true`; force-on `cube.force_auto_roof: true`.
- **R2.** Every platform is reachable → the validator's unreached-platform and no-ground-attachment checks are now **hard errors**, not warnings. Chains are accepted (ground → L1 → L2 → L3 via any combination of ramp/stair/helical).
- **R3.** Balustrades do not overlap cube faces → `make_platform` skips edges where `col ∈ {0, SUB-1}` or `row ∈ {0, SUB-1}`. The cube frame already terminates that edge; a rail there doubled up.
- **R4.** Ramps and stairs influence railings at **both** ends → new helper `_open_platform_anchor` mirrors §9d's `_open_platform_ingress`. Autofix now opens both the terminus edge and the anchor edge for every ramp / stair_cantilever that sits on a platform.

Regenerated all six showcase folies — all still PASS. `folie-compound` receives both new autofix entries (ramp ingress at [1,0] y-, stair anchor egress at [1,2] x-). `folie-field-4x4` picked up one stair-anchor egress at folie[12]. No existing spec broke.

Tests: `pytest tests/` → 3/3 pass.

---

### 2026-04-23 — One-module stairs + helical pac-man landing

Two grammar refinements driven by user feedback on `folie-compound` v2.

**`stair_cantilever` → one-module default.** Previously 0.18 m rise × 0.28 m run, 20 steps to cover a 3.6 m tier — the horizontal run was 5.6 m (longer than a sub-cell). Changed defaults to 0.30 m × 0.30 m × 12 steps = 3.6 m × 3.6 m, matching exactly one sub-cell footprint. A stair now always starts on one platform cell and ends on the adjacent-cell platform one tier up, no more fitting math. Stair is ~45°, which is architecturally steep but Villette-appropriate. Regenerated `folie-compound`, `folie-field-4x4[0, 0]` and `[0, 3]` — all still PASS.

**`stair_helical.landing: true`.** Emits a pac-man landing deck at the helical top: a 3.6 m square cell centred on the axis, with a 3/4 annular void around the axis and a 1/4 "tongue" aligned with the last tread. The walker steps from the last tread onto the tongue and from there onto the surrounding platform. Fixes the v2 issue where the helical terminated into the L3 deck's underside.

**`platform.cutout_cells`.** New field. Cells in this list are part of the platform's connectivity (no balustrades on shared edges) but no deck plate is rendered — lets another primitive (like the helical landing) fill that cell with custom geometry. `folie-compound` v3 uses `cutout_cells: [[1,1]]` at L3, and the helical emits the landing there, so the deck reads continuously.

Deps added: `shapely>=2.0`, `mapbox-earcut>=1.0` (trimesh needs a triangulation engine for `extrude_polygon`).

---

### 2026-04-23 — Grammar extension: `stair_helical` (§3j, §9e)

Web search confirmed: the Belvedere folie at Parc de la Villette has a signature spiral staircase (sources: lavillette.com, travelfranceonline.com, tschumi.com). Our grammar only had `ramp` and `stair_cantilever` — both strictly linear. Added a third primitive.

`stair_helical` is axial: `anchor_m` + `top_z_m` (not direction). Fixed step rise 0.18 m. Revolutions default to 1/3.6 m of rise. Balustrade rendered as a step-polyline on the outer radius (approximates a helical rail without needing a true sweep).

Counts as a **single attachment** regardless of total rise — this is the whole point. A single helical can go ground→L3 (10.8 m), which no ramp (max ~7.6 m lift at 25°, 18 m cap) or `stair_cantilever` (max 16 × 0.18 = 2.88 m) can do.

Validator extended (§9e): axis base and axis top must each be supported. Accessibility check now also acknowledges helical stairs originating at z=0 as satisfying "ground-reaching."

First showcase: `generated/folie-belvedere-spiral/` — 2 ground piers + full L3 roof deck + one helical stair ground→L3 at 2 revolutions. PASS 5/0/0. South elevation is the photogenic view — the two S-curves of the helix read as Tschumi's Belvedere literally. Cites P3 + P7.

---

### 2026-04-23 — Hybrid repo structure (human + agent conventions)

Added standard GitHub conventions alongside the Anthropic-skill conventions: `README.md`, `LICENSE`, `CONTRIBUTING.md`, `pyproject.toml`, `requirements.txt`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/ci.yml`, `tests/test_smoke.py`. `CLAUDE.md` auto-loads for agent sessions and explains the hybrid layout. No renames to agent-facing files (`SKILL.md`, `references/`, `test-log.md` all unchanged).

The two audiences only overlap at the root and have no filename collisions. CI runs `pytest` + regenerates the showcase and fails if any folie stops validating.

Also applied the "public" cleanup: removed absolute paths from resolved `validation.json` files.

---

### 2026-04-21 — Cleanup: removed benchmark/ and trimmed examples/

Retired the `benchmark/` folder (5 archetype folies + `folie-villette-freeform` Level 2 example + `ref/` placeholder dirs + `README.md`). The archetypes were duplicated in spirit by the new `generated/` folies (threshold, slipped, beacon); the Level 2 example stays documented in the 2026-04-18 session below and in `SKILL.md` § Authorship levels, but its .glb artifact is gone.

Trimmed `examples/` from 5 to 2 (`folie-cloven.json`, `folie-field.json`). Removed the three redundant single-folie templates (`folie-basic`, `folie-belvedere`, `folie-passage`) — all superseded by specs in `generated/`.

`SKILL.md` § Running the generator now points at `../examples/folie-cloven.json` (was `../examples/folie-basic.json`). The Level 2 section no longer names the now-deleted `benchmark/folie-villette-freeform/build.py` — it redirects to this log instead.

---

### 2026-04-21 — Flat-shading fix (normals at shared vertices)

Rhino and Unreal showed a diagonal-seam gradient across every flat box panel (frame members, panels, solid cells, stair treads). Cause: `trimesh.creation.box()` creates 8 vertices shared between 6 faces, then glTF export writes vertex normals computed by averaging adjacent face normals — at a cube corner the average points along (±1,±1,±1)/√3, so Phong shading interpolates across the face and reveals the triangulation.

Fix: call `mesh.unmerge_vertices()` in `apply_red()` before assigning the PBR material. Each face now has its own vertex set and its own face-aligned normal → proper flat shading downstream. Verified: verts/face ratio went from ~0.67 (shared) to 3.00 (fully split) on a box.

Regenerated `folie-threshold`, `folie-slipped`, `folie-beacon`. All still PASS validation.

---

### 2026-04-21 — Platform ingress autofix (§9d)

Platforms default to a full-perimeter balustrade, which blocks the walker from stepping off a ramp or stair onto the deck — fence right at the ingress. Visible in the viewer on `folie-threshold`: the ramp landed on the L2 bridge but a rail ran across where the user arrives.

Fix: new autofix rule. When a ramp or stair with a known `target_z_m` has a terminus that lands inside a platform cell, derive the ingress edge from the attachment's direction (dx=-1 → `x+`, dx=+1 → `x-`, etc.) and append `[col, row, edge]` to that platform's `open_sides`. Runs for both the original and any relocated stair anchor. Only cardinal directions are handled; diagonal directions fall through.

Also fixed a latent bug in `make_platform`: `set(open_sides or [])` crashed when entries were list-form `[col, row, "edge"]` (unhashable). Now normalises to hashable tuples before the set build.

Documented as new grammar rule §9d. Autofix fires silently when needed; authors no longer need to compute `open_sides` for ramp/stair arrivals.

---

### 2026-04-21 — Viewer: IBL + tone mapping + don't overwrite PBR

`viewer.html` was overwriting the .glb's PBR material with a hardcoded flat red (`metalness 0.25, roughness 0.45`) on every load, and had no environment map, so anything with `metallic > 0` rendered matte. Fixed: removed the override (GLTFLoader already maps glTF PBR → `MeshStandardMaterial`); added `PMREMGenerator + RoomEnvironment` for IBL reflections; set `outputColorSpace = SRGBColorSpace` and `toneMapping = ACESFilmicToneMapping`. Now metallic/roughness overrides in the spec actually read.

---

### 2026-04-21 — Real PBR material (was flat face colour)

SKILL.md advertised a PBR material (metallic 0.2, roughness 0.45), but `apply_red` used `ColorVisuals` with uniform face colours — there was no metallic or roughness channel in the exported glb. Replaced with `PBRMaterial` via `TextureVisuals`, exposed `metallic` and `roughness` on `spec.defaults` (defaults 0.2 / 0.45 — unchanged canonical look). Verified in the exported `.glb`: `pbrMetallicRoughness.baseColorFactor`, `metallicFactor`, `roughnessFactor` are now present and correct.

First use: `folie-threshold` overrides to `color #FF0000`, `metallic 0.2`, `roughness 0.2`.

---

### 2026-04-21 — Default position changed to origin

Single-folie default was D4 (`grid_pos = [3, 3]` → world origin at (360, 360, 0)). For standalone use — Rhino/Unreal import, moodboards, one-off study — the 120m grid offset is just noise. Changed the skill's workflow default (SKILL.md §Workflow Q2) and made `grid_pos` optional in `spec-schema.md` (code already defaulted to `[0, 0]` at line 1136). `grid_pos` is still asked — and required in practice — only for multi-folie fields, where the positions carry meaning.

Regenerated `folie-threshold` without `grid_pos`; cube now sits at (0,0,0)–(10.8,10.8,10.8).

---

### 2026-04-18 — Level 2 free-form authorship experiment + accessibility audit

Two connected findings in one session. First, an accessibility audit of the 5 archetype benchmarks uncovered a new failure mode. Second, an experimental Level 2 (free Python, no grammar) folie surfaced a finding about what the grammar is actually contributing.

**Accessibility audit — a new class of failure**

Walked each of the 5 archetype folies as a pedestrian. Three of five have real accessibility violations the structural validator doesn't catch:

| Folie | Issue |
|---|---|
| folie-belvedere-tower | ramp terminus lands on cube south face, but L1 platform starts 3.6m north — unwalkable gap |
| folie-curved-plane | same 3.6m ramp-to-platform gap |
| folie-heavy-subtraction | ramp lands on -x face; platform is at cell (2,0) — 7.2m gap across unwalkable frame |
| folie-cantilever-wedge | ok |
| folie-ramp-ascent | ramps land on platforms but L1 and L2 disconnected (ambiguous: intent or failure) |

The grammar's support rule (§9a) only checks that terminus is *structurally supported* (on cube face, ground, or platform). It does not require **path continuity** — that the terminus xy-cell is actually walkable from the rest of the folie. Candidate new rule for §9: *every ramp/stair terminus cell must be part of a platform at the terminus z-level, or the terminus is at ground*.

**Level 2 experiment — folie-villette-freeform**

Tested whether the LLM can produce a folie by writing trimesh Python directly, bypassing `generate_folie.py` entirely. Villette references: the wrap-ramp belvedere folies, and folie L6's cantilevered horizontal cylinder.

Artifacts:
- `benchmark/folie-villette-freeform/build.py` — 170-line self-contained script, 42 geometry parts, no reference to the generator
- `benchmark/folie-villette-freeform/folie-villette-freeform.rationale.md` — markdown (not JSON — Level 2 is outside the schema)
- `benchmark/folie-villette-freeform/folie-villette-freeform.glb` — output, rendered via the existing render script

**Three gestures Level 2 enabled (grammar cannot express atomically)**

1. **Continuous wrap ramp** — 4 face segments + 3 corner landings + roof bridge, read as one spiral ascent from ground to roof in one revolution.
2. **Full-perforation drum** — horizontal cylinder piercing the cube at mid-height with a visible 5 m west cantilever. The grammar's `cylinder_drum` is a one-sided face attachment; full perforation violates the overlap rule.
3. **Corner landings at off-grid z-levels** — landings at z = 2.7, 5.4, 8.1 (between sub-grid levels 3.6, 7.2, 10.8). Grammar's `platforms` only live at multiples of 3.6 m.

**Four failures Level 2 revealed**

1. **Drum overscale.** Radius 1.5 m (diameter 3 m) dominates the cube; within grammar parameter bounds but outside what I'd self-choose in Level 3.
2. **Ramp slope reads flat.** 14° rise over 10.8 m segments plus uniform red = the slabs look like decks, not ramps. Grammar's default 18–25° tilt would have been clearer.
3. **Sub-grid rhythm broken.** 2.7 m rise per segment is 3/4 of a sub-cube, not a sub-grid multiple. Principle-level loss (P5).
4. **Over-authored.** 42 parts; a canonical Villette folie carries 3–4 moves. No forcing function to stop adding.

**Meta-finding**

The grammar is not just structural enforcement — it is **authorship discipline**. Parameter bounds, anchor sets, and the closed attachment vocabulary force the LLM to pick proportions a human Tschumi-like designer would pick. Removing them reveals what each party was contributing: the grammar was constraining scale and complexity; the LLM was making the combinatorial choices within that envelope. Neither is sufficient alone.

Implication for the framing: the research claim is not "AI generates architecture" (too strong; the free-form output over-reaches). It is closer to **"AI generates architecture when paired with a formal grammar that disciplines its tendency to over-reach"** — grammar and LLM as co-authors.

**Practical outcome**

Added an Authorship Levels section to `SKILL.md`. Default stays Level 3. Level 2 documented as available for gestures the grammar can't express, with explicit guidance: cap ~8 parts, stay within grammar parameter bounds even when not enforced, audit against P4/P5 after geometry is built.

---

### 2026-04-18 — Sprint 4 feedback loop + benchmark review pass

Built `execution/render_folie.py` (matplotlib orthographic, 6 views per folie: 4 corner axonometrics + south elevation + plan). This is the first version where Claude can actually see the output and critique it against the rationale.

**Findings from building the renderer**

1. **glTF Y-up round-trip.** The generator pre-rotates the scene -90° about X before `.glb` export (per glTF 2.0 spec). Trimesh loads it as-is and treats Z as vertical, so the model appears rotated 90°. Fix: render script rotates +90° about X on load to restore spec-space Z-up coords. Only matters for non-symmetric elements (cylinders, wedges) — boxy elements don't visibly rotate.
2. **Output path gotcha.** `generate_folie.py --out` resolves relative to the script's CWD-at-import, which is `execution/`, not the invocation CWD. Workaround for now: move output files after generation, or pass absolute paths. Worth fixing in the generator.

**Feedback-loop pass on the 5 archetype benchmarks**

| Folie | Verdict | Revision? |
|---|---|---|
| folie-belvedere-tower | pass | no |
| folie-ramp-ascent | revised-then-pass | yes — single ramp read as cube + attachment; revised to 2 opposite ramps at different levels so ascent reads from any angle |
| folie-cantilever-wedge | pass-with-caveat | no — wedge's triangularity doesn't project well in 2D; would need raster render or east elevation to verify |
| folie-curved-plane | pass | no |
| folie-heavy-subtraction | pass | no — strongest expression in the set |

**What the feedback loop caught that the grammar didn't**

The ramp-ascent issue (cube + attachment rather than ramp-as-subject) was grammar-legal and zero warnings. The validator can't tell whether a composition reads against its rationale; the render-plus-review loop can. Evidence the feedback layer does work distinct from the validator — it catches *intent failures*, not *grammar failures*.

**What the feedback loop missed**

Matplotlib 2D orthographic projection flattens geometry such that non-axis-aligned features (wedges, curved planes at non-cardinal sweeps, rotated cylinders) lose distinctness. Not a rendering bug — a limitation of the chosen approach. Upgrade path: pyrender + GPU shading, or blender headless. Worth doing if we commit to Option A (reverse-engineering against photos).

---

### 2026-04-18 — Sprint 1 + Sprint 2 benchmark (Option B)

Sprint 1 added the reasoning layer: `references/tschumi-principles.md` (P1–P8), `references/rationale-schema.md`, and a rationale-before-spec step in `SKILL.md`. Sprint 2 ran the Option B path — archetype folies rather than true reverse-engineering against reference images (which was deferred pending photo references).

**Folies generated — benchmark/ (Option B archetypes, rationale-driven)**

| Name | Principles | Outcome | Notes |
|---|---|---|---|
| `folie-belvedere-tower` | P3, P4 | PASS 9 ok / 0 warn | 1 autofix: stair anchor relocated to land on L2 |
| `folie-ramp-ascent` | P6, P7 | PASS 5 ok / 0 warn after revise | first draft had 23.3m ramp (over cap); simplified to single tilt-25° ramp |
| `folie-cantilever-wedge` | P4, P8 | PASS 8 ok / 0 warn | clean first-time |
| `folie-curved-plane` | P1, P5 | PASS 7 ok / 0 warn after revise | first draft had stair terminus past -x face; removed stair |
| `folie-heavy-subtraction` | P4, P5 | PASS 5 ok / 0 warn | 1 autofix: ramp anchor relocated to align terminus |

**Findings**

1. **The rationale layer disciplines spec writing.** Committing to 1–3 principles up front made each spec converge on a smaller, clearer set of attachments. Two of the five archetypes were simplified *after* reviewing the rationale against the draft spec — removing elements that weren't serving the cited principles.
2. **Relation-to-predecessors forces variation.** Writing `relation_to_predecessors` for folies 2–5 explicitly stated how each differed from the prior one. Without that field the five would likely have converged toward a mean Tschumi folie.
3. **Grammar caps are a useful forcing function for reasoning.** The 18m ramp cap rejected the "two-ramp ascent" in folie-ramp-ascent and pushed us toward a single dominant move — which better served the rationale's claim that "the ramp IS the folie."
4. **Random mode unaffected.** Sprint 1 left random mode alone by design — no rationale required for stochastic fills. This keeps random mode available as a negative control for Sprint 5 evaluation.

**Tension identified**

Option B (archetypes) produces grammar-legal folies with provenance but does not test reverse-engineering. To convert the benchmark set into a research artifact we'd need Option A — reference images for each named Tschumi folie, then reasoning constrained to match. Current benchmark/ is a starting scaffold; `ref/` folders remain empty. Upgrade path documented in `benchmark/README.md`.

---

### 2026-04-18 — First pass on the whole system

Built the skill from scratch, iterated through multiple folies, and arrived at a working feedback loop.

**Folies generated**

| Name | Author | Outcome | Notes |
|---|---|---|---|
| `folie-basic` | user-specified | PASS after 6 autofixes | ramp overshoot, stair step count, stair anchor relocation, landing fallback |
| `folie-field-3x3` | seeded random × 9 | PASS, 0 autofixes after random-generator hardening | 71 ok / 0 warn once mandatory-access-ramp + step-snapping were in place |
| `folie-seed-test` | seed 7 | PASS clean first-time | 9 ok / 0 warn |
| `folie-belvedere` | Claude-authored | PASS first-time | intentional design using named vocabulary |
| `folie-cloven` | Claude-authored | PASS, used `raw_beam` + grouped dislocation | demonstrates the escape-hatch primitives |
| `folie-passage` | Claude-authored | PASS after 3 spec fixes | wedge base off-face, stair-drum overlap, missing canopy |

**Findings that changed the system**

1. **glTF axis convention** — trimesh exports vertex data as-is. The glTF 2.0 spec mandates +Y up. Z-up data written as-is is interpreted as Y-up by importers (Rhino, three.js, Unreal), rotating the model 90°. Fix: pre-rotate scene -90° about X before export so the file is genuinely Y-up. Importers reverse this automatically.
2. **Subdivision frame must be a full 3×3×3 skeleton** — earlier version only drew the grid on outer faces, so empty cells read as a hollow cube. Added interior crossbars at each sub-tier and 4 interior vertical columns.
3. **Curved plane anchor semantics** — had anchor = arc centre (wall floated 4m from cube). Changed to anchor = chord midpoint on the cube face; arc bulges outward by the sagitta. Now attaches cleanly.
4. **Hollow cylinders via trimesh boolean fail silently** without a manifold engine. Fix: build the hollow shell directly from vertices (outer + inner surface + annular rims).
5. **Stair can't start at ground in the random generator** — stairs cantilever off cube faces. Restrict z_start to face heights (3.6, 7.2). Ground access is always a ramp.
6. **Stair relocation beats landing** — earlier autofix added `landing: true` when a stair's terminus was mid-air, but a floating landing isn't actually supported either. Better: relocate the anchor + direction so the terminus lands on a real platform cell. Landings remain as the fallback.
7. **Ramp anchor alignment matters** — snapping length to a target z without also adjusting the anchor's xy leaves the ramp ending 0.9m short of the cube face.
8. **Grouped dislocation needs boundary-dedup** — listing 9 cells with the same offset should render as one slab, not 9 overlapping panels.
9. **`raw_beam` reopens the freedom** — when `ramp/stair/tower/...` don't fit, a two-point untyped beam is the honest escape hatch. No type semantics, length cap 15m, exempt from touchpoint rule.
10. **Touchpoint rule** (every ramp/stair has two non-adjacent supports) caught an entire class of "physically impossible" folies the grammar hadn't previously encoded.
11. **Overlap rule** — bbox-based at 50% threshold with a documented carveout for intentional intersections. Current limitation: line-vs-cylinder cases slip through (see Improvements).
12. **Wedge base must sit entirely on a cube face** — spanning a corner gives only an edge contact ("one touchpoint"). Caught visually, not yet by validator.

**Tension we identified**

Accumulating rules to close off every bad case risks squeezing out authorial voice. Useful distinction: *possibility rules* (physics / grammar / structural) get enforced strictly; *intent rules* (Tower here vs there, open vs closed, cantilever vs enclosed) stay as the designer's choice. Now marked in SKILL.md.

---

## Improvements / next work

### High impact

1. **Path continuity as a validator rule**
   Identified in the 2026-04-18 audit and still open. The ingress-edge autofix (§9d) presumes the terminus lands on a platform cell. When it lands on a supported-but-disconnected cell (the audit's three archetypes), §9d silently does nothing. Validator should flag terminus cells not continuous with the rest of the folie's walkable graph — or autofix should relocate the ramp/stair.

2. **Line-segment vs cylinder overlap check**
   Current bbox check missed the stair-drum intersection in `folie-passage`. For stair/ramp × drum/tower pairs, compute min distance from the stair's axis segment to the cylinder's axis, flag if < radius. Much more accurate than bbox for thin-vs-thin cases.

3. **Wedge base containment check**
   Validator rule + autofix: wedge's base rectangle (determined by anchor + width + length + direction) must lie fully within one cube face's bounds. If not, snap anchor toward face centre.

4. **Headroom check for stairs**
   Opt-in accessibility rule: 2 m vertical clearance above every tread. Currently a Tschumi folie at L1→L2 has its L2 deck at z=7.2 acting as the "ceiling" over the rising stair, violating code. Add as `defaults.enforce_headroom: true`.

### Medium

4. **Dislocation with LOD 300 framed panels for single cells**
   Currently only grouped dislocation uses panel-dedup. A single dislocated cell still uses the monolithic box — inconsistent with the rest of LOD 300.

5. **Program marker (Rule 6)**
   Optional `folie.program` field: `"cafe" | "kiosk" | "belvedere" | "daycare" | "first_aid" | null`. Doesn't render anything visible — purely semantic metadata on the `.spec.json`, satisfies disjunction by being explicit and separate from form.

6. **Concrete plinth (Rule 5)**
   Add an optional concrete ground slab at grid position, 11 × 11 × 0.3 m, grey PBR. Missing visual element from the Villette original.

7. **Headless render hook**
   Generate N PNG previews per folie (e.g. NE, SW, top, east elevations) at `--open` time. I can read them in the next turn and comment without the user having to screenshot.

### Low / nice-to-have

8. **Batch generator**: one command emits all 26 folies as one .glb + 26 individual files, stamped on the 120m point grid.
9. **Intent-vs-possibility flag** baked into each rule entry in `folie-grammar.md` — like the SKILL.md table but at the rule level.
10. **Repetition operation as first-class** — currently achievable by listing N identical attachments at shifted anchors; could be declared `{"op": "repeat", "along": "x", "count": 3, "attachment": {...}}`.

### Known limitations (documented, not yet fixed)

- Overlap detection is bbox-based; thin diagonal elements vs cylinders produce false negatives.
- No visual regression test — relying on user screenshots.
- Stair balustrade at the ramp-foot end appears visually floating because the slab is only 15 cm thick and the post is 1 m tall; not actually broken, but reads oddly in screenshots.
