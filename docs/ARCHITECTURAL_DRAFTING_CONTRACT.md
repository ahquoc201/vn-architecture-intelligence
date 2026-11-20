# Architectural Dimensions, Annotation & CAD Layer Contract v1 (Batch 007-C / Engine 0.1.14)

This contract turns verified Batch 007-B1..B4 architectural geometry (walls, hosted openings, stairs, and integrated concepts) into a deterministic, CAD-neutral **Drawing Intermediate Representation (IR)** with source-grounded dimensions, annotations, reference symbols, configurable CAD layers, bounded collision checks, and scale-consistent SVG previews. One user-facing agent controls the workflow. No automatic CAD writes, construction approval, or standards/Feng Shui certification are granted.

## 1. Drawing Intermediate Representation (`architectural-drafting-v1`)

Schema: `knowledge/architecture/drafting-ir.schema.json` (input wrapper: `knowledge/architecture/drafting-input.schema.json`).

### 1.1 Primitives & Analytic Geometry Preservation
Model-space primitives live inside `model_space.views[]` (units: `mm` or `m`) and use 10 CAD-neutral entity types:
- `LINE`: finite segment (`start`, `end`).
- `POLYLINE`: closed/open loops (`exterior`, `holes`, `closed`). Wall cut unions are grouped by `A-WALL-EXT` and `A-WALL-INT` (`int_union.difference(ext_union)`) so shared boundaries are never duplicated.
- `ARC`: exact analytic circular arc (`center`, `radius`, `start_angle_deg`, `end_angle_deg`, `start_point`, `end_point`, `rotation`). Door swing arcs are **never** approximated as polylines.
- `CIRCLE`: exact center and radius (grid bubbles).
- `TEXT` / `MTEXT`: UTF-8 text supporting full Vietnamese Unicode diacritics (`Phòng khách`, `Bếp - Ăn`, `Hành lang chữ L`, etc.).
- `DIMENSION`: reference points, dimension line start/end, text point, extension lines, and explicit `measurement_basis`.
- `HATCH`: closed boundary loops with hatch pattern metadata.
- `SYMBOL`: scale bar, section markers, stair direction arrows, sliding track arrows.
- `BLOCK_REFERENCE`: references reusable definitions in `model_space.blocks` (`TAG_DOOR`, `TAG_WINDOW`, `SYM_LEVEL_MARK`, `SYM_NORTH_ARROW`).

Every primitive carries:
- `id`: deterministic `DE-<sha256[:16]>` derived from `[view_id, entity_type, layer, source_geometry_id, key_tag]`.
- `entity_type`, `coordinates`, `view_id`, `floor_id`, `layer`, `style_ref`, `source_geometry_id`, `source_revision_digest`, and `provenance`.

### 1.2 Model-Space vs Paper-Space Separation
- `model_space` stores true architectural dimensions and geometry in `drawing_units` (`mm` default, or `m`).
- `paper_space` stores project presentation preferences (`scale_denominator`, e.g., `50` or `100`, `scale_authority: "project_drawing_preference"`, sheet border/title block settings).
- Changing paper scale (`1:50` vs `1:100`) changes paper-space representation and annotation sizing **only**; real-world coordinates, measured dimensions, and `geometry_and_dimensions_digest` remain strictly unchanged.

## 2. Measurement Bases & Dimension Engine (`vnai.drafting_dimensions`)

Every emitted dimension carries `measured_vs_required: "actual_measured"`, an explicit `measurement_basis`, `ref_point_1`, `ref_point_2`, `measured_value`, `source_measured_value`, `measurement_unit`, `display_text`, `displayed_numeric`, `rounding_discrepancy`, and `source_geometry_digest`.

Supported measurement bases:
- **Overall**: `building_envelope`, `floor_outline`, `dimension_chain_overall`.
- **Dimension chain segments**: `dimension_chain_segment` (`wall_face`, `partition_reference`, `opening_jamb`, `reference_grid`).
- **Clear room dimensions**: `clear_room_interior` — generated **only** when a room's B1 `clear_geometry` is a strict axis-aligned rectangle (`symmetric_difference(box(*bounds)).area <= 1e-12`). Non-rectangular, holed, or multi-component rooms emit an explicit `AMBIGUOUS_IRREGULAR_ROOM_SPAN` record in `unsupported_dimensions` instead of fabricating a scalar width/length. Allocation bounds are never labeled as clear dimensions.
- **Walls**: `wall_thickness_actual` (measured from actual B1 wall polygons).
- **Openings**: `opening_rough_width` (`reference`), `opening_clear_passage_width` (`clear_reference`). Leaf width (`leaf_width`) is kept distinct in opening schedule/tag metadata and never confused with rough or clear passage width.
- **Circulation**: `circulation_clear_width` (computed by subtracting floor walls from circulation reservation polygons and decomposing orthogonal clear corridors into axis-aligned strips; non-orthogonal circulation emits `UNSUPPORTED_NONORTHOGONAL_CIRCULATION_WIDTH`).
- **Stairs & floor openings**: `stair_flight_width`, `stair_flight_run`, `stair_landing_width`, `stair_landing_depth`, `floor_opening_width`, `floor_opening_length`.
- **Vertical**: `supplied_wall_height`, `floor_to_floor_height`, `stair_landing_elevation`, `stair_riser_height`, `stair_tread_depth`, `stair_verified_local_headroom`, `opening_sill_elevation`, `opening_head_elevation` (only where explicitly supplied).

## 3. Dimension Chains & Closure Verification

- Reference points along an axis are sorted deterministically and deduplicated within documented tolerance (`1e-9 mm` / `1e-12 m`).
- Segments are computed from exact `Decimal` differences (`coord[i+1] - coord[i]`), guaranteeing exact telescoping sum in `Decimal`.
- Closure verification distinguishes three states:
  1. `GEOMETRIC_CLOSED_EXACT`: exact segment sum equals overall span AND displayed rounded segment labels sum to the displayed overall label.
  2. `GEOMETRIC_CLOSED_DISPLAY_ROUNDING_DISCREPANCY`: exact geometry closes within tolerance, while rounded display text differs (e.g., `333 + 333 + 333 = 999` vs `1000`). **Segment labels are never silently altered to hide rounding discrepancies.**
  3. `GEOMETRIC_CLOSURE_MISMATCH`: exact segment sum differs from the overall span beyond tolerance (reported as an error / `CONFLICT`).

## 4. Drawing Units, Styles & CAD Layer Policy (`vnai.drafting_styles`)

- **Unit policy**: converts from `source_units` (`m` or `mm`) to `drawing_units` (`mm` or `m`) exactly once using exact `Decimal` factors (`1 m = 1000 mm`), tagging `unit_conversion_applied` and `double_conversion_guard: "EXPLICIT_SOURCE_TO_DRAWING_ONCE"`.
- **Default project CAD layer convention** (`vnai-cad-layers-v1`, advisory project convention — not a mandatory Vietnamese CAD standard):
  `A-WALL-EXT`, `A-WALL-INT`, `A-DOOR`, `A-DOOR-SWING`, `A-WIND`, `A-STAIR`, `A-STAIR-ABOVE`, `A-ROOM-TEXT`, `A-OPENING-TAG`, `A-DIMS`, `A-GRID`, `A-LEVEL`, `A-SECT`, `A-HATCH`, `A-REVIEW`.
  Every layer defines `entity_category`, `aci_color` (1..255), `svg_color`, `linetype`, `lineweight_mm`, `visible`, `plottable`, and a precomputed `ezdxf_mapping` dictionary. Overrides are validated for illegal CAD characters, uniqueness, color bounds, valid linetypes, and positive lineweights.
- **Styles**: `arch-mono-v1` (default readable monochrome architectural style) and `arch-color-v1`, with customizable Unicode font family stack (`Noto Sans, Segoe UI, Arial, sans-serif`; no proprietary fonts redistributed) and paper-space sizing (`paper_text_height_mm`, `paper_dim_text_height_mm`, `paper_arrow_size_mm`, offsets, tick style).

## 5. Room, Opening, Stair & Reference Annotations (`vnai.drafting_annotations`)

- **Rooms**: interior anchor uses exact rectangle center or deterministic quadtree pole-of-inaccessibility (strictly verified inside `clear_geometry`; never blindly trusts polygon centroid). Preserves Vietnamese diacritics, separates `clear_area_m2` from `allocation_area_m2`, adds `! CONFLICT` if unresolved room conflicts exist, and never invents room names or finish specifications.
- **Openings**: reuses B2 marks, swing arcs, sliding tracks, and schedule digests; inconsistent repeated marks trigger `CONFLICTING_OPENING_MARK`.
- **Stairs**: reuses B3 flights, risers, treads, cut classifications (`BELOW_CUT` on `A-STAIR`, `ABOVE_CUT` on `A-STAIR-ABOVE`), `UP`/`DOWN` arrows, optional step numbering, and explicitly distinguishes `TRUE_STRAIGHT_SECTION` from `DEVELOPED_EXPLICIT_WALKING_LINE`.
- **Reference symbols**:
  - **North arrow**: emitted **only** when `north_degrees` is backed by a `confirmed` requirement or `orientation_override`; otherwise flagged `NORTH_ORIENTATION_UNRESOLVED`.
  - **Reference grid**: tagged `architectural_reference_grid` unless `supplied_structural_column_grid` carries explicit provenance.
  - **Section markers**: verified against actual section views (`DEFINED_SECTION_VIEW`) or marked `PROPOSED_SECTION_MARKER`.
  - **Elevations**: level marks use confirmed floor/stair elevations only; building elevations are never fabricated.

## 6. Bounded Placement & Collision Detection (`vnai.drafting_layout`)

- Placement order (building geometry and drawing border are **immutable**): fixed grid/level symbols -> dimension label staggering -> stair callouts -> room labels (interior shifts + optional outside margin leader callout) -> opening tags (`+normal`, `-normal`, tangent shifts, optional margin leader callout).
- Distinguishes:
  - `EXACT_GEOMETRIC`: intersections against wall polygons, doors, windows, stairs, fixed obstacles, or circles.
  - `APPROXIMATE_TEXT_BOUNDS`: character-count/line-count bounding estimates (`method: "APPROXIMATE_CHARACTER_METRIC_BOX"`, Vietnamese vertical factor `1.25`). Exact pixel/glyph font metrics are **not** claimed unless actual font metrics are supplied.
- Any unresolved collision is recorded in `collisions[]` (`status: "UNRESOLVED"`) and drawn on layer `A-REVIEW`.

## 7. Source Digests & Immutability

Four independent SHA-256 digests are emitted:
- `geometry_and_dimensions_digest`: real-world geometry + measured dimensions + chains (strictly invariant to `scale_denominator`).
- `model_space_digest`: complete model-space IR entities and blocks.
- `presentation_digest`: paper scale, style, and layer policy.
- `drawing_ir_digest`: combined canonical content digest.

Stored reports (`architectural-drafting-v1`) are re-validated by checking schemas, layer policies, entity layers, chain closures, and recomputing all four digests against source inputs.

## 8. CLI Examples & Exit Codes

```powershell
vnai design drafting generate examples/batch007c/townhouse-6rooms-drafting.json --out outputs/townhouse-drafting.json --markdown outputs/townhouse-drafting.md
vnai design drafting validate outputs/townhouse-drafting.json
vnai design drafting report examples/batch007c/townhouse-6rooms-drafting.json --markdown outputs/townhouse-drafting-report.md
vnai design drafting layers examples/batch007c/townhouse-6rooms-drafting.json --markdown outputs/townhouse-layers.md
vnai design drafting preview outputs/townhouse-drafting.json --floor F1 --out outputs/townhouse-F1.svg
vnai design drafting preview examples/batch007c/townhouse-6rooms-drafting.json --view sheet --scale 50 --out outputs/townhouse-sheet-1to50.svg
```

Exit codes: `0` GENERATED, `1` INVALID_INPUT, `2` I/O/parse/exclusive-output error, `3` INCOMPLETE, `4` CONFLICT, `5` UNSUPPORTED.
Governance fields remain locked: `cad_writes_permitted: false`, `approval_inherited: false`, `architect_approval: "NOT_GRANTED"`, `standards_review: "NOT_EVALUATED"`, `fengshui_review: "NOT_EVALUATED"`.

## 9. Batch 007-D DXF Export Strategy

Batch 007-D can translate `architectural-drafting-v1` deterministically into DXF via `ezdxf` without re-deriving geometry:
1. Validate IR via `validate_drafting` (checking digests, layers, and explicit human authorization outside this engine before enabling any write flag).
2. Configure DXF `$INSUNITS` (`4` for `mm`, `6` for `m`) from `unit_policy.drawing_units` and `$DIMSCALE` from `paper_space.scale_denominator`.
3. Create DXF layers directly from `layer_policy.layers[].ezdxf_mapping` and block definitions from `model_space.blocks`.
4. Emit 1:1 primitive mappings into DXF ModelSpace:
   - `LINE` -> `msp.add_line`
   - `POLYLINE` -> `msp.add_lwpolyline` (with explicit island/hole polylines)
   - `ARC` -> `msp.add_arc(center, radius, start_angle, end_angle)` (analytic, zero tessellation!)
   - `CIRCLE` -> `msp.add_circle`
   - `HATCH` -> `msp.add_hatch` with exterior + hole boundary paths
   - `TEXT` / `MTEXT` -> `msp.add_text` / `msp.add_mtext` using a UTF-8 Unicode DXF font style
   - `DIMENSION` -> `msp.add_linear_dim` anchored at `ref_point_1`, `ref_point_2`, and `dim_line_location` with explicit `dimstyle` overrides matching `style`
   - `BLOCK_REFERENCE` -> `msp.add_blockref` with attributes (`mark`, `dimension_label`, `label`)
5. Create PaperSpace layouts (`LAYOUT`) with viewport scale `1:scale_denominator` and sheet title block separated from ModelSpace.
6. Verify round-trip by reopening the generated `.dxf` with `ezdxf.readfile`, asserting layer tables, entity counts, analytic arc radii/angles, dimension measurements, and zero silent mutation.
