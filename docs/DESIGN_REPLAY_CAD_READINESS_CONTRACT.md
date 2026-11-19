# Design replay, revision and CAD readiness v1

Engine v0.1.9 / R3 Batch 007-A. These tools verify supplied revisions and report information readiness. They never search for replacements, create walls/doors/stairs, certify construction, authenticate an architect or authorize CAD writes. Existing candidate, brief, zoning, review and DXF contracts remain compatible.

## Baseline and architecture

Implementation started from main c1ada45, v0.1.8. The preceding baseline run observed 702 tests passing on Python 3.14.3 and Ruff passing. Regression counts are not architectural quality or expert oracles.

Modules: design_provenance records original inputs; design_replay measures current geometry independently; design_revision validates parent/child bindings and feedback; cad_readiness combines explicit drafting gates; architectural_benchmark exercises actual generation/review/evaluation without selection/approval; design_reports supplies exits and Markdown. Existing validators/metrics remain authoritative in their scope. No dependencies are added.

Schemas: generation-provenance, design-replay, design-revision, cad-readiness, architectural-benchmark (all .schema.json). Workflow schemas expose #/$defs/input and #/$defs/result; readiness also exposes policy/drafting definitions. They reference the existing candidate/review/geometry/brief/evaluation contracts, with no competing room/wall model. All are packaged by the canonical-data build hook.

## Explicit provenance

```powershell
vnai design floorplan generate examples/batch006a/two-room.json --provenance
vnai design replay validate examples/batch007a/replay/valid-provenance.json
vnai design replay report examples/batch007a/replay/valid-provenance.json --markdown outputs/replay-v0.1.9.md
```

The optional flag (API: include_provenance=True) adds generation_provenance sidecars. Default generation reports/candidates retain their behavior and normal current engine stamp. A sidecar records exact original generation_specification and origin_candidate using existing schemas; declared historical engine version; digests of brief, expanded program, zoning, fixed site/floor geometry context, complete specification, generation input and exact origin candidate; original algorithm, effective parameters/overrides, grid step/tolerances; rooms, dimensions, area requests, hard/soft relations and reservations. provenance_digest hashes every field except itself.

The generation_input digest reuses the solver formula: canonical_digest({specification, effective_parameters, algorithm}). Program digest includes project_id, rooms, relationships, areas and input_brief, excluding engine/validation metadata. Exact candidate digests include historical generation metadata. Geometry context excludes only polygon approval/status and sorts non-room polygon IDs; frames, units, floors, tolerances, points, segments and physical geometry remain bound.

create_generation_provenance requires actual matching source specification/parameters; it does not reconstruct dimensions from bounding boxes, invent authorization, authenticate history or certify geometry. Replay recomputes all dependencies/registers and the original input binding, not just the outer hash. Legacy candidates lacking original provenance remain INCOMPLETE. No historical fixtures/reports are rewritten.

## Independent replay

Input: {schema_version:1, review:<existing sidecar>, mode:original|revision, provenance?:<sidecar>, baseline_revision?:<revised specification and confirmation>}.

Original mode requires exact origin content. Revision mode supports externally edited room polygons under original hard constraints; no search, regeneration, grid snapping or identical layout is required. The recorded grid resolution describes search, not an invented architectural constraint for manual revisions.

Replay rebuilds the source program and validates source geometry/zoning. Missing room polygons in generation source cause expected ROOM_GEOMETRY_MISSING diagnostics, not source failure; other missing/invalid data remains blocking. Original dimensional records, fixed-inventory declaration and source generation authorization must be present. These source records are not candidate approval or CAD authorization.

Checks cover provenance/origin binding, stored floor metadata, exact room inventory/requirement traceability, original floor assignments, per-polygon units/frames, valid positive polygons, original envelopes, rectangular support, area bounds, axis-specific width/depth, same-floor overlap, every circulation/stairwell/shaft/other reservation and hard adjacency. Fresh areas are compared with stored measurements; inconsistent metadata becomes STALE. Stored passed flags and scores never override current observations.

Width stays along X and depth along Y; no implicit rotation. Nonrectangular geometry may be spatially valid but dimensional replay is UNSUPPORTED: a bounding box cannot prove room proportions. Qualitative hard separation and coordinate transformations remain UNSUPPORTED. Existing spatial tolerances are reported, while exact original containment/nonoverlap/reservation rules are also enforced; relaxing tolerance cannot bypass them. Dimensional/area comparisons reuse only the original solver's 1e-12 relative/absolute arithmetic-noise allowance.

Each check includes id, status, method, measured/expected values, requirement IDs and pointers/digests to exact review/specification/provenance and baseline confirmation. Pointers resolve relative to the replay report. Applicable coverage excludes N/A; evaluated = VERIFIED + FAILED. Missing/unsupported/stale never become passes or zeros. Stairwell exclusion is replayed; vertical links and detailed stair traversal belong to separate review.

Overall precedence: FAILED for a known violation; otherwise STALE bindings; otherwise UNSUPPORTED methods; otherwise INCOMPLETE dependencies; otherwise VERIFIED. Malformed contracts/resource violations are INVALID_INPUT. A valid digest does not prove a valid design.

## Governed feedback and external revisions

```powershell
vnai design revision compare examples/batch007a/revision/valid-manual-revision.json
vnai design revision compare examples/batch007a/revision/approval-invalidated.json
vnai design revision compare examples/batch007a/revision/changed-requirement-baseline.json
```

Revision input binds distinct parent_revision_id/child_revision_id, full immutable parent/child review sidecars, exact candidate/design digests, change_origin and rationale. revision_digest binds the complete relationship. Preserve previous documents/reports: this batch is not an authenticated append-only database, and changing a referenced document invalidates its relationship rather than updating history.

Origins distinguish user_confirmed_requirement_change, architect_requested, ai_proposed and unresolved_assumption. Diff reports added/removed/changed room entities, review sections, source baseline changes and conservatively affected constraints. Exact unchanged candidate geometry/source-brief dependencies may remain factual dependencies; entire parent approval/evaluation reports are never inherited.

Parent source provenance is independently checked. Optional parent_replay_context supports a parent already on a confirmed revised baseline and must bind the exact parent review. A physically defective parent can be repaired by the child; defects stay visible without making its lineage disappear. Unverifiable parent source bindings still block verification.

A changed brief/floor/assignment/constraint/assumption baseline needs explicit baseline_revision specification plus reviewer identity/role, confirmed=true, exact specification_digest and rationale, with user_confirmed_requirement_change origin. Governing zoning/authorization must also match revised content. Verification never signs those records or silently edits requirements.

Feedback records carry id, exact parent/child target candidate/design digests, human-supplied reviewer identity/role, optional date-time, category, affected room/geometry IDs, requirements, requested change/rationale, blocking flag, resolution and supersedes IDs. Categories include requirements, layout, dimensions, circulation, privacy, openings, stairs, style, technical review and other. Unknown references, duplicate IDs and supersession cycles are errors.

OPEN/ADDRESSED remain unresolved. VERIFIED/WITHDRAWN require an explicit architect resolution record bound to the child design. SUPERSEDED also needs a distinct replacement and resolution record; an open blocking replacement still blocks. AI edits do not auto-resolve feedback. Reviewer names/dates/approval are never invented; identities/roles are unauthenticated assertions.

Children are replayed independently. Relevant edits invalidate parent approval; copied REVIEWED/APPROVED event IDs do not promote a new proposal. Fresh child records use the existing state machine and current design digest. approval_inherited is always false; explicit valid child approval is separate.

## CAD readiness policy and stages

```powershell
vnai design readiness report examples/batch007a/readiness/room-geometry-ready.json --markdown outputs/readiness-v0.1.9.md
vnai design readiness report examples/batch007a/readiness/architectural-drafting-withheld.json
vnai design readiness report examples/batch007a/readiness/blocking-architect-feedback.json
```

Input includes replay context, explicit versioned policy and drafting_information, with optional revision/evaluation_config/prior_evidence using existing contracts. Policy declares policy_id, requested_stages, required_review_state (SELECTED/REVIEWED/APPROVED), require_openings, require_graph, require_clearance, require_evaluation and require_revision_review. No default architectural weights, dimensions or legal thresholds are supplied.

Always assess brief/program completeness, current zoning, geometry, original hard replay, exact selection/review, known circulation conflicts and required multi-floor stair information. Revision mode requires bound revision review even if policy omits require_revision_review. Blocking feedback cannot be bypassed by omitting a scoring criterion. Verified physical failures disqualify; scores cannot compensate.

Required opening/graph/clearance checks use the existing independent reports. Graph connectivity does not prove clearance. Multiple floors need confirmed vertical graph links and complete stair information even for preliminary room-geometry readiness; reservations never substitute for links. A single floor reports inter-floor stairs as NOT_APPLICABLE.

Required evaluation (or supplied prior evidence) recomputes metrics under the explicit policy. Required checks/criteria must be available; score magnitude is not a readiness threshold. Prior bindings must match; cached values are not imported. Unsupported requirements remain explicit, and malformed semantic evaluation policy is an input error.

| Stage | Current supported readiness scope |
| --- | --- |
| room_geometry | May be READY_FOR_DRAFTING only for supplied room polygons after all applicable replay/review/policy/feedback gates. |
| architectural_walls_openings | INCOMPLETE without information; UNSUPPORTED when external information is declared available because this batch cannot validate full thickness/assembly/hosting/schedule contracts. Never silently READY. |
| stairs | N/A for a single floor; otherwise INCOMPLETE without detailed information or UNSUPPORTED when externally supplied. No tread/riser/headroom drafting contract is invented. |
| annotations | Information readiness for explicitly supplied sheet title/scale and exact units/frame/floors/complete room labels; no annotation generation or certification of a dimensioned drawing. |

Missing future wall/stair/annotation fields do not block room_geometry-only policy. Their prerequisites remain visible in stage results. External references are availability declarations, not validated detailed geometry. Top-level scope names requested stages. Known failure -> NOT_READY; unsupported required stage/method -> UNSUPPORTED; missing/stale critical data -> INCOMPLETE; otherwise READY_FOR_DRAFTING. Invalid input -> INVALID_INPUT.

Always retain cad_writes_permitted=false, construction_readiness=NOT_EVALUATED, approval_granted=false, standards_review=NOT_EVALUATED and fengshui_review=NOT_EVALUATED. Readiness grants neither CAD operation authorization nor construction readiness. No AutoCAD MCP, DWG changes, new DXF features, structural/MEP checking or unverified rules are added.

## CLI, reproducibility and resources

New commands emit deterministic ASCII-escaped JSON; --markdown exclusively creates a new UTF-8 file. Inputs and previous reports cannot be overwritten. APIs do not mutate inputs and create no default output/CAD files.

Exit codes: 0 verified/ready or successful benchmark generation; 1 known hard failure/not ready/invalid input; 2 read/parse/write error; 3 incomplete dependencies; 4 stale replay/revision (benchmark retains existing INFEASIBLE=4); 5 unsupported; 6 benchmark search exhausted. An unsupported benchmark is a completed valid report but exits 5. Root VALID/INCOMPLETE/INVALID stays distinct from domain states.

Bounds: <=12 replay rooms, <=500 combined polygons, <=10000 supplied coordinate pairs, physical coordinate/dimension magnitude <=1e9 declared units, <=128 relationships/256 expanded pairs, <=64 feedback items with bounded acyclic supersession. Existing schemas bound openings/stairs/routes; original search budgets remain authoritative. These are implementation limits, not architectural requirements or infeasibility proofs.

Eighteen synthetic replay/revision/readiness examples and four benchmark cases live in examples/batch007a. Critical-result oracles plus full-report digests are versioned under tests/golden/batch007a-v0.1.9. Historical Batch 005/006 snapshots remain unchanged. Tests cover replay without search, physical failures, manual edits, stale approval/evidence, confirmed baselines, scoped readiness, repeated results, CLI exits/input preservation and legacy compatibility. Fresh-wheel smoke runs outside the checkout, including the unchanged schematic DXF command with the CAD extra installed.

See ARCHITECTURAL_BENCHMARK_PROTOCOL.md for actual expert-review prerequisites. Recommended Batch 007-B: explicit wall assemblies/thicknesses, hosted opening schedules and detailed stair information contracts with expert-reviewed positive/negative/edge fixtures before any new drafting exporter. Legal/Feng Shui review and CAD authorization remain separate.
