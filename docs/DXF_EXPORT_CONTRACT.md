# DXF Export & Semantic Round-Trip Contract (Batch 007-D / `v0.1.15`)

This contract defines how validated CAD-neutral Drawing IR v1 (`architectural-drafting-v1` from Batch 007-C) is exported into editable, dimensionally accurate DXF files, structurally audited, and semantically verified without mutating source architectural geometry or authorizing AutoCAD live CAD writes.

---

## 1. Governance & Non-Authorization Guarantees

- **No live AutoCAD writes**: `cad_writes_permitted: false`, `existing_cad_modification_permitted: false`.
- **Artifact export mode**: `EXPLICIT_NEW_DXF_ARTIFACT` only via explicit `--out <path>.dxf`. Protected repository sources, schemas, knowledge files, fixtures (`examples/batch005*`–`examples/batch007c*`, `examples/batch007d/*.json`), and input specs cannot be overwritten even with `--overwrite`. Existing target `.dxf` / `.manifest.json` files fail safely unless `--overwrite` is supplied.
- **No inherited approval**: `approval_inherited: false`, `architect_approval: "NOT_GRANTED"`, `standards_review: "NOT_EVALUATED"`, `fengshui_review: "NOT_EVALUATED"`, `construction_readiness: "NOT_FOR_CONSTRUCTION_CONCEPTUAL_ONLY"`.
- **Human AutoCAD acceptance**: `manual_autocad_acceptance_status: "PENDING_HUMAN_AUTOCAD_VERIFICATION"` on every generated artifact until an architect inspects it in AutoCAD/DWG viewer.
- **Legacy exporter untouched**: `src/vnai/dxf_adapter.py` and `vnai dxf` remain unchanged for backwards compatibility.

---

## 2. Supported Pipeline

```text
Validated Drawing IR v1 (+ optional dxf-export-spec-v1)
  → Drawing Unit Resolution (mm / m single Decimal conversion)
  → CAD Layer & Style Registration (vnai-cad-layers-v1 + VIEWPORTS + VNAI_VN_UNICODE + VNAI_DIM_<scale>)
  → DXF Entity Mapping (all 10 Drawing IR v1 primitives)
  → Native Dimension Rendering (ezdxf linear DIMENSION + rendered *D<n> block + actual_measurement)
  → Model Space 1:1 (+ explicit-only Paper Space VIEWPORT when paper_size_mm supplied)
  → Atomic DXF Serialization (R2010 / R2013 / R2018)
  → Independent Structural Audit (ezdxf audit_dxf_file)
  → Handle-Free Semantic Round-Trip Comparison (verify_dxf_roundtrip)
  → Export Manifest (dxf-export-manifest-v1) + Manual AutoCAD Acceptance Checklist
```

If any post-export audit (`audit_status != "CLEAN"`) or round-trip check (`equivalence_status not in {"LOSSLESS_EQUIVALENT", "NUMERICALLY_EQUIVALENT"}`) fails on the candidate DXF, temporary DXF output is withheld and the manifest records errors cleanly with exit code `1` or `4`.

---

## 3. Unit Resolution & Single Conversion Policy

- **Supported model units**: `"mm"` (`$INSUNITS = 4`, 3 decimal display precision unless configured) and `"m"` (`$INSUNITS = 6`, 3 decimal display precision by default).
- **Single Decimal conversion**: Source IR coordinates and scalar measurements are converted once from `source_units` to `target_units` using `Decimal` arithmetic (`vnai.drafting_styles.convert_length` with exact `1000` factor), avoiding floating-point scaling drift and double conversion.
- **Scale invariance**: Model Space DXF geometry is always `1:1` in `target_units`. Changing project paper scale (`1:50`, `1:100`) changes text/symbol annotation sizing and optional Paper Space viewport scale only — Model Space entity coordinates never change.
- **DXF Header Variables**: `$INSUNITS`, `$MEASUREMENT = 1` (metric), `$LUNITS = 2`, `$DIMSCALE = 1`, `$DWGCODEPAGE = "UTF-8"` (where supported).

---

## 4. Primitive Mapping (10 IR Primitives -> Native DXF)

Every IR entity is tagged with custom XDATA under AppID `VNAI_IR` containing JSON metadata (`ir_id`, `ir_type`, `source_geometry_id`, `part`, etc.) so round-trip verification matches entities semantically without relying on mutable DXF handles.

| IR Primitive | Native DXF Output | Preservation & Refusal Notes |
| --- | --- | --- |
| `LINE` | `LINE` | Exact start/end endpoints in Model Space. |
| `POLYLINE` | `LWPOLYLINE` (exterior + per-hole loops) | Strips redundant duplicate closing vertex when `closed=true`; refuses `< 2` (open) or `< 3` (closed) vertices. |
| `ARC` | `ARC` | Preserves analytic center, radius, and start/end angles; swaps CW IR angles into DXF CCW convention cleanly without polyline tessellation. |
| `CIRCLE` | `CIRCLE` | Preserves analytic center and positive radius. |
| `TEXT` | `TEXT` (`style="VNAI_VN_UNICODE"`) | Preserves alignment anchor (`top_left`..`bottom_right`), height, rotation, UTF-8 Unicode text. |
| `MTEXT` | `MTEXT` (`style="VNAI_VN_UNICODE"`) | Joins multi-line strings with `\P`, preserves attachment point, `char_height`, and `line_spacing_factor` clamped to `[0.25, 4.0]`. |
| `DIMENSION` | Native `DIMENSION` (via `msp.add_linear_dim(..., render=True)`) | Supports `"horizontal"` and `"vertical"` aligned spans; sets explicit `actual_measurement`, `dimdsep=ord(".")`, `dimzin=0`, `dimdec`; verifies span against recorded `measured_value`. |
| `HATCH` | `HATCH` (`set_pattern_fill`, e.g. `ANSI31`) | Validates Shapely polygon validity (no self-intersections, non-empty, positive area) for exterior + holes; refuses invalid boundaries (`INVALID_HATCH_BOUNDARY`, exit `4`). |
| `BLOCK_REFERENCE` | `INSERT` + attached `ATTRIB`s | References pre-registered reusable blocks (`TAG_DOOR`, `TAG_WINDOW`, `SYM_LEVEL_MARK`, `SYM_NORTH_ARROW`), preserving scale, rotation, and attribute tag values. |
| `SYMBOL` | `INSERT` (`scale_bar`) or multi-part native primitives (`section_marker`, `stair_direction_arrow`, `slide_direction`) | Explicitly mapped by `symbol_kind`; unknown symbol kinds fail with `UNSUPPORTED_SYMBOL_KIND` (exit `5`). |

---

## 5. Layers, Styles, Dimensions & Unicode Caveats

- **CAD Layer Registration**: Registers all 15 `vnai-cad-layers-v1` layers using each entry's `ezdxf_mapping` (`color`, `linetype`, `lineweight`, `plot`). Any IR entity referencing an unregistered layer is refused (`UNMAPPED_ENTITY_LAYER`, exit `1`) — never silently dumped to layer `"0"`. When Paper Space is active, a non-plotting `"VIEWPORTS"` layer (`plot=0`) is also registered so `VIEWPORT` references audit cleanly.
- **Lineweights**: Registered per layer (`int(round(lineweight_mm * 100))`) from explicit policy config, preserved across export.
- **Native Dimension Rendering & Display Caveats**:
  - `ezdxf` creates native `DIMENSION` entities backed by anonymous `*D<n>` geometry blocks and stores `actual_measurement` (`42`).
  - Dimension override variables (`dimdsep=ord(".")`, `dimzin=0`, `dimdec`) ensure consistent decimal formatting across viewers, though AutoCAD/LibreCAD/BricsCAD text rendering inside regenerated dimensions depends on host CAD DIMSTYLE override evaluation.
  - Dimension lines are never faked as decorative `LINE` + `TEXT` pairs.
- **Vietnamese Unicode Handling & Font Caveats**:
  - DXF releases `R2010`, `R2013`, and `R2018` store native UTF-8 text (`$DWGCODEPAGE` and `DXF R2007+ UTF-8 encoding`), preserving NFC Vietnamese diacritics (`Phòng khách`, `Trục 1`, `Cầu thang`, `m²`, `±0.00`).
  - Default style `VNAI_VN_UNICODE` references `--font Arial.ttf` without bundling proprietary font binaries. Code-point equality is mathematically verified during round-trip (`unicode_text_verification.all_codepoints_match`), while physical glyph rendering on an architect's workstation remains `UNVERIFIED_EXTERNAL_WORKSTATION_FONT` until opened in AutoCAD.

---

## 6. Model Space vs Explicit-Only Paper Space Composition

- **Default exports** compose **Model Space `1:1`** only, recording `paper_space_composition.status: "NOT_GENERATED_NO_PAPER_SIZE_SUPPLIED"`. Sheet sizes (A1/A2/A3/A4) are never guessed or invented.
- When `paper_size_mm` is explicitly supplied (`--paper-size 420x297` or `paper_space_layout.paper_size_mm`), the exporter configures the Paper Space layout page setup, draws a border polyline on `A-GRID`, adds a locked Model Space `VIEWPORT` scaled to `paper_space.scale_denominator`, and verifies viewport scale & paper size during round-trip.
- Passing `--require-paper-space` (or `paper_space_layout.require_paper_space: true`) without explicit `paper_size_mm` returns `INCOMPLETE` (`PAPER_SIZE_NOT_SUPPLIED`, exit `3`).

---

## 7. Structural Audit vs Semantic Round-Trip Verification

1. **Structural Audit (`audit_dxf_file`)**:
   - Reopens the DXF via `ezdxf.readfile(...)` + `doc.audit()`, plus custom reference & geometry checks for missing layer, block, text style, and dimension dimstyle/geometry block references, non-finite coordinates, degenerate polylines, and invalid hatch polygons (`$INSUNITS` and `VNAI_META` are verified separately during `verify_dxf_roundtrip` and `extract_manifest_from_dxf`).
   - Classifies file hygiene strictly into: `CLEAN` (`critical_error_count == 0` and `fix_count == 0` and `custom_issue_count == 0`), `RECOVERED_WITH_FIXES` (`fix_count > 0` with no critical errors; sets `lossless_eligible: false`), or `CRITICAL_ERRORS`.
   - Note: an empty or semantically corrupted DXF can still be structurally `CLEAN` — therefore audit success alone never implies geometric correctness.

2. **Semantic Round-Trip Verification (`verify_dxf_roundtrip`)**:
   - Compares reopened DXF Model Space (and optional Paper Space) entities against the validated Drawing IR view using `VNAI_IR` XDATA mappings, ignoring mutable DXF handles/UUIDs/timestamps.
   - Measures `max_numeric_error` across endpoints, polyline rings (vertex-order independent cyclic alignment), circle/arc radii and angles, native `DIMENSION.get_measurement()`, hatch rings, `INSERT` + `ATTRIB` pairs, and `SYMBOL` components.
   - Equivalence classifications:
     - `LOSSLESS_EQUIVALENT`: `audit_status == "CLEAN"`, zero missing/extra/mismatched entities, zero Unicode code-point loss, and `max_numeric_error <= lossless_tolerance` (`1e-9` mm / `1e-12` m).
     - `NUMERICALLY_EQUIVALENT`: `audit_status == "CLEAN"`, zero missing/extra/mismatched entities, zero Unicode code-point loss, and `lossless_tolerance < max_numeric_error <= coord_tolerance` (`1e-5` mm / `1e-8` m).
     - `MISMATCH`: any missing, extra, untagged, or drifted entity, Unicode mismatch, wrong `$INSUNITS`, missing Paper Space viewport, or non-`CLEAN` audit (`RECOVERED_WITH_FIXES` or `CRITICAL_ERRORS` blocks lossless equivalence).

---

## 8. CLI Commands, Exit Codes & Explicit Refusals

```powershell
vnai design dxf export <input.json> --out <out.dxf> [--view ID | --floor ID] [--units mm|m] [--dxf-version R2010|R2013|R2018] [--font Arial.ttf] [--paper-size WxH] [--require-paper-space] [--manifest <out.manifest.json>] [--markdown <out.md>] [--overwrite]
vnai design dxf audit <file.dxf> [--markdown <out.md>]
vnai design dxf verify <input.json> --dxf <file.dxf> [--view ID | --floor ID] [--units mm|m] [--markdown <out.md>]
vnai design dxf manifest <file.dxf> [--sidecar <manifest.json>] [--markdown <out.md>]
```

| Exit Code | Meaning |
| --- | --- |
| `0` | `EXPORTED` / `CLEAN` / `VERIFIED` (`LOSSLESS_EQUIVALENT` or `NUMERICALLY_EQUIVALENT`) |
| `1` | `INVALID_INPUT` / `AUDIT_ERROR` / `CRITICAL_ERRORS` (e.g. unmapped layer, invalid DXF/IR schema, missing file, ambiguous multi-view export without `--view`/`--floor`) |
| `2` | `INPUT_ERROR` (malformed JSON, protected path overwrite, existing output without `--overwrite`, path aliasing, non-`.dxf` output extension) |
| `3` | `INCOMPLETE` (`PAPER_SIZE_NOT_SUPPLIED` when `require_paper_space=True`, incomplete source IR) |
| `4` | `CONFLICT` / `MISMATCH` / `RECOVERED_WITH_FIXES` (stale source digests, IR collisions if unacknowledged, invalid hatch boundary, dimension span mismatch, semantic round-trip mismatch, audit fixes needed) |
| `5` | `UNSUPPORTED` (`UNSUPPORTED_PRIMITIVE`, `UNSUPPORTED_DXF_VERSION`, unknown `symbol_kind`, unsupported `DIMENSION` orientation) |

---

## 9. Manual AutoCAD Acceptance Checklist (`PENDING_HUMAN_AUTOCAD_VERIFICATION`)

Before marking any exported DXF accepted for CAD drafting use, the human architect must manually verify:

1. **Units & Scale**: Open `.dxf` in AutoCAD (`UNITS` command) and confirm insertion scale matches `$INSUNITS` (`Millimeters` or `Meters`) and Model Space geometry is `1:1`.
2. **Dimension Associativity & Values**: Inspect `A-DIMS` native `DIMENSION` entities using `DIMSTYLE` / `PROPERTIES`; confirm displayed values match measured spans without manual text overrides masking wrong geometry.
3. **Vietnamese Unicode Rendering**: Confirm `VNAI_VN_UNICODE` resolves `Arial.ttf` (or workstation Vietnamese TTF/SHX substitution) and renders `Phòng khách`, `m²`, `±`, and axis bubbles cleanly without `???` or tofu glyphs.
4. **Layer & Plot Policy**: Inspect `LA` (`LAYER`) manager for all 15 `vnai-cad-layers-v1` layers, colors, linetypes, lineweights, and non-plot flags (`A-ANNO-COLLISION` / `VIEWPORTS`).
5. **Analytic Arcs & Hatches**: Confirm door swings select as true `ARC` entities (not tessellated polylines) and structural/wall `HATCH` boundaries display cleanly without boundary gaps.
6. **Review Flags & Disclaimers**: Inspect `A-REVIEW` markers and confirm architectural approval, QCVN/TCVN standards compliance, and Feng Shui review remain independently checked.
