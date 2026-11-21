# Changelog

## 0.2.0 - 2026-11-21

- Add Claude Code skill installation from one canonical `skills/` source (`vnai skills list|check|install`, `vnai-skill-install-v1` digest marker; MISSING/STALE/MODIFIED/UNMANAGED states; no symlinks required; skills bundled in the wheel) and `vnai doctor`.
- Add resumable project workspace `vnai project init|import|step|decide|status` (`vnai-workflow-project-v1`): fixed-argv orchestration of existing commands with versioned outputs, SHA-256 ledger, exit-code categories and Vietnamese meanings, digest-bound human decisions, stale/superseded detection, and an export guard requiring a current `export_authorization` for new DXF files. `cad_modification` is refused.
- Restructure `vn-house-design` into an entry-point SKILL.md with progressive-disclosure references (`intake`, `stages`, `status-codes`); existing safeguards preserved; batch identifiers removed from permanent agent instructions; CLAUDE.md condensed.
- Add deterministic synthetic townhouse workflow demo (`scripts/demo_synthetic_townhouse.py`), live-eval case set (`evals/vn-house-design/cases.json`) with a transcript collector (`scripts/run_skill_evals.py`), negative/recovery tests, and architect/engineering documentation. Engines, goldens and fixtures unchanged.

## 0.1.15 - 2026-11-21

- Add production CAD DXF export and semantic round-trip verification (`vnai design dxf export|audit|verify|manifest`) built directly on Drawing IR v1 (`architectural-drafting-v1`) and `ezdxf` (`R2010`/`R2013`/`R2018`).
- Implement `src/vnai/dxf_export.py`, `src/vnai/dxf_roundtrip.py`, `src/vnai/dxf_manifest.py`, standalone contracts (`dxf-export-spec.schema.json`, `dxf-manifest.schema.json`), and `docs/DXF_EXPORT_CONTRACT.md`.
- Map all 10 IR primitives (`LINE`, `POLYLINE`, analytic `ARC`, `CIRCLE`, `TEXT`, `MTEXT`, native rendered `DIMENSION`, Shapely-validated `HATCH`, `BLOCK_REFERENCE` -> `INSERT`+`ATTRIB`, and explicit `SYMBOL`), enforce single `Decimal` unit conversion (`mm`/`m`, `$INSUNITS` `4`/`6`), register all 15 `vnai-cad-layers-v1` layers (+ non-plot `VIEWPORTS` when Paper Space is requested), preserve UTF-8 Vietnamese Unicode strings, and keep Paper Space opt-in only when explicit `paper_size_mm` is supplied.
- Add independent structural DXF audit (`CLEAN`, `RECOVERED_WITH_FIXES`, `CRITICAL_ERRORS`) separated from handle-free semantic round-trip equivalence verification (`LOSSLESS_EQUIVALENT`, `NUMERICALLY_EQUIVALENT`, `MISMATCH`), 6 mathematical oracles (Oracles A–F), exported townhouse DXF deliverables under `examples/batch007d/exports/`, CLI regression tests, and isolated wheel smoke coverage while keeping legacy `vnai dxf`, `cad_writes_permitted: false`, `architect_approval: NOT_GRANTED`, and `manual_autocad_acceptance_status: PENDING_HUMAN_AUTOCAD_VERIFICATION`.

## 0.1.14 - 2026-11-20

- Add CAD-neutral Drawing Intermediate Representation (`architectural-drafting-v1`) with 10 primitives (`LINE`, `POLYLINE`, `ARC`, `CIRCLE`, `TEXT`, `MTEXT`, `DIMENSION`, `HATCH`, `SYMBOL`, `BLOCK_REFERENCE`), analytic swing-arc preservation, deduplicated wall unions, and separated model-space vs paper-space settings.
- Add deterministic architectural dimension engine (`vnai.drafting_dimensions`) supporting overall envelope/outline dimensions, orthogonal horizontal/vertical dimension chains with exact `Decimal` closure vs display-rounding discrepancy tracking, clear room interior dimensions, wall thicknesses, rough vs clear opening widths, orthogonal circulation strip widths, stair flight/landing/opening spans, and vertical elevations/headroom.
- Add explicit `Decimal` unit conversion guard (`mm`/`m`) and project drawing scale independence (`1:50`, `1:100`) verified by invariant `geometry_and_dimensions_digest`.
- Add Vietnamese Unicode room annotations using strictly interior `polylabel` placement, B2 opening tags/schedule consistency, B3 stair callouts/sections, and source-grounded reference symbols (confirmed-only north arrows, architectural reference grids, level marks, section markers, scale bars).
- Add configurable versioned CAD layer policy (`vnai-cad-layers-v1`) with `ezdxf_mapping`, monochrome/color architectural styles, bounded placement/leader callouts, and `EXACT_GEOMETRIC` vs `APPROXIMATE_TEXT_BOUNDS` collision detection (`A-REVIEW` markers).
- Add `vnai design drafting` CLI (`generate`, `validate`, `report`, `preview`, `layers`), 8 Batch 007-C fixtures, 9 actual SVG previews including the complete 6-room two-storey townhouse benchmark (48/48 unchanged geometric checks preserved), independent mathematical oracles, documentation, and wheel/CI coverage.
- Preserve immutable source geometry, historical golden fixtures/reports, separate technical/Feng Shui layers, `architect_approval: NOT_GRANTED`, and `cad_writes_permitted: false`.


## 0.1.13 - 2026-11-20

- Classify incomplete modeling inventories/cut datum before search; never label missing critical data as search exhaustion.

- Compose existing finite-grid generation, wall-aware clear measurements, hosted openings,
  actual stairs, source replay and verified portal/path chains into proposed integrated revisions.
- Add bounded explicitly permitted partition/opening-offset refinement, fixed-geometry protection,
  exact dependency caching per invocation and before/after/floor/section SVG review.
- Add opt-in declared circulation/wall contact masks; retain actual obstructions and prohibit
  stair/shaft/fixed exemptions. Historical default behavior and versioned goldens are preserved.
- Add independently checked synthetic multi-storey townhouse, retained failed fixture revisions,
  mathematical area/partition/clearance oracles, CLI/schema/wheel coverage and documentation.
- Freeze B3 CLI golden comparisons at their historical 0.1.12 metadata; retain every assertion.
- Keep unknown/unsupported evidence, specialist reviews and architect approval separate;
  cad_writes_permitted remains false. No production CAD exporter or automatic approval.


## 0.1.12 - 2026-11-19

- Pin B2 CLI historical golden comparisons to their 0.1.11 engine metadata; preserve full hashes, geometric assertions and all historical fixtures.

- Add deterministic wall/opening-bound straight, L and U stair geometry, exact riser/tread
  counting and level closure, explicit landing/arrival surfaces and true/developed sections.
- Add read-only slab/opening, known collision, full portal/landing-width and continuous
  flat-surface headroom checks with uncovered regions and fresh 006-B interface replay.
- Keep scoped physical traversal unverified without explicit project width/headroom criteria.
- Add typed schemas, CLI, schedules, actual SVG plans/sections, synthetic independent
  oracles/goldens, unchanged townhouse benchmark and clean wheel checks on Python 3.11/3.14.
- Preserve historical geometry/contracts/goldens, source provenance, no inherited approval,
  advisory standards/Feng Shui layers and cad_writes_permitted=false.

## [0.1.11] - R3/BATCH-007-B2 wall-hosted opening drafting (2026-11-19)

- Generate actual digest-bound rough wall cuts, frames/glazing, hinged leaf/arc geometry and explicit surface-sliding motion from existing B1 walls; preserve source candidates/walls.
- Separate selected plan-cut geometry, floor wall obstructions, uncredited thresholds and vertical wall bands; windows never create circulation edges or usable floor area.
- Reuse 006-B graph, supplied-width routes and stair interfaces over actual retained walls/frames/leaves; missing evidence stays unknown and known collisions remain visible.
- Add typed drafting schemas, exclusive JSON/Markdown/SVG CLI, deterministic opening schedule/marks, conservative rational swing enclosures and independent numerical oracles.
- Preserve original townhouse constraints/conflicts, historic contracts/goldens and schematic DXF; extend CI, wheel smoke and the existing house-design skill. Expert review/approval remains pending and CAD writes remain false.
- Record durable cross-version numerical guidance; retain the B1 accurate-summation/empty-zero fix and Python 3.11/3.14 CI matrix.

## [0.1.10] - R3/BATCH-007-B1 architectural wall geometry (2026-11-19)

- Fix Python 3.11/3.14 wall-area summary reproducibility with explicit accurate summation and an exact-rational regression oracle; preserve union geometry, tolerances and frozen goldens.

- Derive real, source-bound orthogonal wall polygons, centerlines and exposed faces from explicit wall intent, semantics, thickness, alignment and offset; preserve original candidates.
- Node/deduplicate shared boundaries and construct owned L/T/X/collinear junctions, including mixed thickness; account for wall area by union, retaining outside-envelope conflicts.
- Calculate complete clear-room geometry/area, independently replay original allocation constraints and assess declared clear requirements, reservations and fixed obstacles without resizing rooms.
- Mark wall-dependent opening/circulation/evaluation/approval evidence stale, provide conservative opening-host mappings and keep CAD writes disabled.
- Add wall schemas, JSON/Markdown/SVG CLI, actual uniformly scaled previews, 27 versioned fixture oracles, analytical/negative/CLI tests, CI and isolated wheel checks; preserve earlier goldens and DXF.
- Update the existing single-agent house-design skill and wall geometry contract. Synthetic dimensions/reviews are not professional standards or expert approval.

## [0.1.9] - R3/BATCH-007-A design replay and CAD readiness (2026-11-19)

- Add opt-in original generation provenance with exact specification, solver parameters and candidate snapshots; preserve default generation and DXF behavior.
- Independently replay inventory, dimensions/area/floor bounds, topology, exact reservations and hard adjacency without search or stored pass flags.
- Add digest-bound external revisions, feedback/supersession/resolution, confirmed baselines and fresh child review; no approval inheritance or identity authentication.
- Add explicit scoped readiness for room polygons, wall/opening information, stairs and annotation availability; missing/unsupported stages remain visible and CAD writes stay disabled.
- Add three synthetic residential benchmarks, honest unsupported/exhausted outcomes, separate timing observations, human review protocol/template, schemas/oracles, CLI and fresh-wheel/DXF checks.
- Update single-agent house-design guidance and preserve historical contracts/goldens. Actual expert architectural review and oracles remain pending.


## [0.1.8] - R2/BATCH-006-C evidence-based candidate evaluation (2026-11-19)

- Recompute deterministic, digest-bound geometry, room inventory, adjacency, opening, graph, planar-clearance and stair metrics using established review contracts.
- Separate evidence coverage/input declarations, hard eligibility and explicit Decimal preference scoring; missing values are never imputed, known failures cannot be compensated.
- Add scoped pairwise trade-offs and conditional ranking with explicit normalization, optional/N/A denominator policies, precision, tolerance, ties and withholding.
- Add versioned input/metric/evidence/report schemas, JSON/Markdown CLI, 18 synthetic scenario oracles, negative/contract/permutation/regression tests and isolated wheel command coverage.
- Preserve historical versioned reports and tests. Keep architect decisions, standards/Feng Shui review and CAD permissions separate; update house-design guidance and contracts.


## [0.1.7] - R2/BATCH-006-B circulation, openings and stairs (2026-11-18)

- Add immutable candidate selection and content-bound review/approval history; stale IDs/digests and invalid promotions are rejected.
- Validate explicit boundary-hosted hinged/sliding/passage openings, conservative swing geometry, clearances and known fixed collisions without inventing doors or width standards.
- Add deterministic space/portal graphs, supplied passage-width checks and explicit stairwell/landing/entry/elevation/alignment checks.
- Separate graph reachability, bounded planar traversal, technical compliance and architect records; no complete verification or CAD authorization is inferred.
- Add versioned schemas, synthetic fixtures/golden reports, negative/CLI tests and fresh-wheel coverage for every new command. Preserve historical 0.1.5/0.1.6 golden snapshots.


## [0.1.6] - R2/BATCH-006-A deterministic floorplan generation (2026-11-18)

- Add bounded grid rectangle search using explicit area/dimension constraints, source zoning and content-bound generation authorization.
- Generate up to three distinct spatially validated proposals with stable digests/IDs, traceability, hard checks and normalized soft scores.
- Add supplied circulation/stairwell/shaft reservation polygons to geometry v1 without changing existing reports for older geometry.
- Distinguish incomplete/invalid/unsupported inputs, proven area/dimension contradictions and bounded search exhaustion; no automatic approval or CAD writes.
- Add CLI, synthetic fixtures, versioned golden reports, negative tests and generator coverage in the fresh-wheel smoke test. Preserve Batch 005 golden snapshots with their historical version stamps.


## [0.1.5] - R2/BATCH-005 Zoning and Geometry Contract (2026-11-18)

- Reuse Design Brief/Space Program instances in versioned floor zoning with explicit provenance, unresolved decisions and digest-bound architect decision history.
- Add a 2D polygon/point/segment contract with frames, units, holes, ownership and explicit tolerances; validate envelopes, floor-specific overlaps and area targets without repairing input.
- Add read-only zoning/geometry CLI commands, synthetic approval examples, golden reports and regression/negative tests.
- Bundle canonical authored runtime schemas/YAML in wheels and add a fresh-venv smoke test outside the checkout.
- Keep CAD writing disabled and specialist rules unapproved; no optimizer or buildability certification.


## [0.1.4] - R2/BATCH-004 Design Brief & Space Program (2026-11-18)

- Add shared JSON Schema v1/Python validation, requirement provenance and explicit planning-data gates.
- Add deterministic room instances, client-supplied hard/soft relationships, contradiction checks and independent area aggregates.
- Add read-only `vnai design brief validate/report` and `vnai design program build` with JSON output and documented exit codes.
- Include synthetic 4x20 m brief, contract, skill instructions and regression/negative tests.
- No layout generation, CAD writes, normative room minima or executable specialist rules.

## [0.1.3] — R1/BATCH-003 bibliographic research guards (2026-11-16)

- Track six **catalog claims** (not full-book attestations) across Bát Trạch Minh Kính and Dương Trạch Tam Yếu.
- Flag unresolved 2016 Dương Trạch edition page-count mismatch for the same published barcode.
- Add eight input-clarification terms and four non-executable research rule questions.
- Add `vnai fengshui knowledge validate` and `report`; fail closed if candidate rules claim approval, provenance or CAD write rights.
- Expand source-linked tests and CI; no traditional numerical judgments or technical compliance claims.

## 0.1.2 — R1 Batch 002 (orientation engineering foundation)

- Add true-north drawing-vector orientation calculator, uncertainty-aware octant boundary results and read-only CLI.
- Add documented JSON input schema, demo, edition review queue and research evidence note.
- Add tests for geometric edge cases, validation, CLI and non-executable feng shui guardrails.
- Bát Trạch/Dương Trạch numerical rules **remain unapproved**; no CAD writes or technical compliance claims.

## [0.1.1] — R1/BATCH-001 evidence corpus (2026-11-16)

- Add distinct Nguyễn Tiến Đích 2014 revised edition and Tạp chí Kiến trúc 2022 worship-space source.
- Add five attributed, **non-executable** insights based on directly checked public article sections and official scope metadata.
- Add `vnai knowledge validate`, provenance checks, nine protective tests and CI gate.
- Record source audit and explicit blockers for paid full-text review/expert approval.
- **No approved Bát Trạch/Dương Trạch computation or legal compliance rule was added.**

## 0.1.0 — research foundation
- Seeded 11 source references with provenance, priority and rights status.
- Introduced strict separation of geometric measurement, Feng Shui advisory, and standards-review outputs.
- Added validated polygon geometry, room area diagnostics, orientation octants, preliminary DXF export.
- Added 3 Claude Code skills, CLI, sample townhouse geometry, regression tests, GitHub Actions CI.
- Added review governance and watchlist for later source monitoring.
- No approved Feng Shui or QCVN/TCVN executable rules.
