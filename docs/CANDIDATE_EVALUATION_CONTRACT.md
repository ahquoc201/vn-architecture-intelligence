# Batch 006-C: floorplan evaluation contract v1 (engine 0.1.8)

This layer measures supplied geometry and existing review evidence. It supports an architect's decision; it does not select, approve, optimize or modify a design. A policy score expresses declared preferences, never objective architectural quality. All dimensions/actors in the examples are synthetic.

## Input and commands

An evaluation request has `schema_version: 1`, an explicit `config`, and 1-8 `candidates` entries `{id, review}`. `review` is the unchanged Batch 006-B candidate-review sidecar, including the original Batch 006-A candidate. IDs identify alternatives; even different sidecars for one generated candidate need distinct IDs. Identical candidate+design bindings are rejected. Compare/rank require at least two alternatives. Optional `prior_evidence` contains coverage snapshots; their scores/claims are never imported.

```powershell
vnai design candidates evaluate examples/batch006c/verified-circulation.json
vnai design candidates compare examples/batch006c/three-candidates.json --markdown outputs/batch006c-comparison-v0.1.8.md
vnai design candidates rank examples/batch006c/three-candidates.json --markdown outputs/batch006c-ranking-v0.1.8.md
vnai design candidates rank examples/batch006c/ranking-withheld.json
```

JSON always goes to stdout. Markdown uses exclusive creation: existing reports and inputs cannot be overwritten. Inputs are never mutated. Exit codes: 0 = complete requested evaluation/comparison or RANKED/TIED; 1 = invalid schema/policy or fewer than two comparison alternatives; 2 = read/parse/write error; 3 = incomplete evaluation/comparison or RANKING_WITHHELD/PARTIALLY_COMPARABLE; 4 = NO_ELIGIBLE_CANDIDATES. Root VALID means successful scoped evaluation, not building approval. Ineligible single-candidate evaluation withholds scoring and exits 3; its verified failures are in `evidence.failed_checks`.

The canonical schemas under `knowledge/architecture` are `evaluation-config`, `metric-result`, `evidence-coverage`, `candidate-evaluation-input`, `candidate-evaluation`, `candidate-comparison` and `candidate-ranking` (all `.schema.json`, v1). They reuse the existing candidate-review, geometry and brief contracts. Old commands and old versioned golden reports remain supported. All schemas are packaged into the wheel.

## Measured facts

Each metric contains identifier/version, candidate/design/policy/evaluation digests, status, number or null, unit, method, coverage numerator/denominator, evidence references and limitations. References resolve relative to that evaluation object (`/sources/spatial`, `/sources/architectural`, `/sources/review`) and hash the exact referenced object. Current validators are rerun; stored solver pass flags, soft scores and stored measurements are not proof.

| Metric ID | Unit and method / denominator |
| --- | --- |
| allocated_room_area_m2 | m2; sum of room polygon unions independently per floor |
| floor_envelope_area_m2 | m2; sum of explicit outline/footprint/site fallback envelopes chosen by existing spatial validator; never legally usable floor area |
| reserved_circulation_area_m2 | m2; union of explicitly supplied circulation reservations per floor; explicit absence measures zero |
| geometric_residual_area_m2 | m2; envelope polygon difference with union of rooms and all reservations per floor; never inferred usable/unallocated space |
| area_target_deviation_m2 | m2; mean absolute measured-minus-target deviation over the entire source room inventory; missing targets are UNKNOWN; no targets at all is N/A |
| room_inventory_coverage | fraction; source instance IDs present / source room count; extra IDs separately fail the inventory check |
| floor_assignment_coverage | fraction; source rooms on their exact active source-assignment floors / source room count |
| required_adjacency_satisfaction | fraction; satisfied explicit hard instance pairs / applicable hard pairs |
| preferred_adjacency_satisfaction | fraction; satisfied explicit soft instance pairs / applicable soft pairs |
| room_connectivity_coverage, entrance_reachability | fraction; rooms graph-reachable from supplied exterior / source rooms; complete known disconnection is measurable, incomplete inventories are UNKNOWN |
| known_inaccessible_rooms | count; source room count minus reachable rooms, only when graph inventory is complete |
| circulation_clearance_coverage | fraction; rooms with complete supplied planar clearance proof / source rooms; incomplete proof is UNKNOWN with null value and factual partial counts |
| opening_validation | binary; 1 for current whole opening validation, 0 for supported verified physical/geometric conflict, null for missing/malformed reference context |
| stair_connectivity | fraction; 1 only when all supplied vertical graph links are verified; one floor plus explicit complete empty stair inventory is N/A; missing multi-floor links are UNKNOWN |
| known_geometric_conflicts | count; distinct supported geometric conflict codes, not incident count and not absence of all hazards |
| unresolved_checks | count; observed declared generator unresolved-check list length, never a confidence measure |

Adjacency requires same floor and positive shared-boundary length beyond declared geometry boundary tolerance. Point contact is not adjacency; no doors are inferred. Architectural `separate` intent is UNSUPPORTED here, avoiding an invented separation distance or privacy rule. Single-valued metrics use 1/1 for a measurement; ratio/mean metrics disclose their actual item counts. No original solver dimension input is present in candidate v1: dimension replay is UNSUPPORTED if requested, and no whole-solver feasibility claim is made.

## Evidence and hard eligibility

VERIFIED means the specified predicate/measurement is demonstrated. A verified numeric zero is possible. FAILED means a supported hard predicate is demonstrably violated. UNKNOWN means insufficient or conflicting information, with no imputation. NOT_EVALUATED is explicitly unrun work. NOT_APPLICABLE is demonstrated exclusion from scope, not missing data. UNSUPPORTED is outside the implemented methods.

Always-required checks are candidate_integrity, spatial_geometry, room_inventory, floor_assignments, room_area_bounds and required_relationships. Configuration adds required checks; it cannot remove these gates. Supported additional checks are opening_validity, entrance_reachability, circulation_clearance and stair_connectivity. Every known supported hard failure disqualifies the candidate even if that check was not requested. Source min/max areas are hard; room targets are preferences. Metadata/stale-record/reference errors remain UNKNOWN, distinct from observed overlap, outside-envelope, opening collision, width or stair alignment failure.

Priority: any FAILED -> INELIGIBLE; otherwise required UNSUPPORTED -> UNSUPPORTED; otherwise required UNKNOWN/NOT_EVALUATED -> PENDING_VERIFICATION; otherwise ELIGIBLE. N/A required checks do not block. Eligibility means only this scoped check set, not architectural fitness. Geometry-only policy can score while non-required circulation remains UNKNOWN; require entrance_reachability and circulation_clearance for a circulation-gated decision, as demonstrated by the strict fixtures. Search exhaustion never proves infeasibility.

Coverage denominator = all implemented/requested checks minus N/A checks. Evaluated count = VERIFIED + FAILED. `evaluation_coverage` and `verified_coverage` use that denominator; empty applicable set yields null. `input_completeness` separately counts four declarations (source brief present, openings complete, stairs complete, obstacles complete); it cannot prove those data were verified. Example: corridor-clearance has 10 checks, 2 N/A, 8 verified (8/8 applicable); corridor-graph-only still declares all four sections complete but lacks clearance verification. These are coverage ratios, never confidence estimates.

## Bindings and invalidation

Candidate digest hashes the exact immutable candidate, including its generation metadata. Design digest reuses Batch 006-B's exact sidecar binding (all fields except decision history). Policy digest hashes normalized config (criteria/check IDs/scope lists sorted). Evaluation digest hashes those bindings plus metric definition version. Editing brief, geometry, openings, stairs, paths or policy invalidates the matching binding. Decision records are separately revalidated by the review engine and cannot silently promote approval.

Supplied prior evidence for the same candidate must match every binding or candidate_integrity becomes UNKNOWN and scoring is withheld. Unbound candidate IDs are rejected. With several sidecars for one candidate, supply only exact applicable snapshots: conflicting snapshots conservatively block that candidate's alternatives. Raw facts are recomputed even with stale selection metadata; stale evidence is never evidence of physical failure. Digests detect changes, not authenticity; reviewer identities/signatures are not authenticated.

## Explicit scoring

Every criterion supplies stable id, metric_id, direction, positive weight, required flag and numeric lower/upper bounds. Target direction also requires an interior target; other directions prohibit a target. Duplicate IDs, nonfinite numbers, invalid bounds, zero weights and incomplete explicit scope are invalid. No default preferences, criteria, weights or architectural thresholds are supplied.

For x in [lo,hi], maximize = (x-lo)/(hi-lo), minimize = (hi-x)/(hi-lo). Target normalization ramps from 0 at lo to 1 at target and back to 0 at hi, with separate linear slopes on each side. All values clip to [0,1]. Decimal arithmetic uses 50 digits; final normalized scores, contributions, effective weights and aggregate use explicit score_precision (0-12 digits), ROUND_HALF_EVEN. Aggregate uses unrounded normalized values and weight ratios, then rounds once. The displayed effective weights can sum slightly differently due to display rounding.

Required unavailable criteria withhold aggregate. Optional unavailable criteria can be excluded only when optional_criteria=exclude_unavailable. N/A exclusion requires not_applicable_criteria=exclude, including for required criteria, since it is outside scope. Both policies otherwise withhold. Excluded criteria have no effective weight, contribute nothing, and are removed from the disclosed active denominator. No remaining criterion means aggregate null, never zero. All non-ELIGIBLE candidates have null aggregate regardless of favorable observed metrics.

## Comparison and ranking

Strict baseline compares exact brief (including requirements), fixed site/floor/frame/tolerance/non-room geometry context, source assignments/inventory, metric definition version and shared policy. This is conservative: semantically equivalent but differently encoded coordinate conventions may require explicit scope. Room layout alternatives are allowed, fixed reservations are part of the context. Original solver dimension constraints cannot be compared/replayed from candidate v1.

explicit_metric_basis requires named baseline digests, permitted metric IDs and rationale. Only those metrics are compared; ratio/target-mean denominators must match. A numeric scope does not assert whole-design equivalence. Observed strengths/weaknesses are tied to declared preferences; pairwise facts remain available without scores. Aggregate comparison additionally requires equal active criterion IDs and comparability of every active metric; missing optional evidence cannot silently yield differently weighted ranked scores.

All alternatives are sorted by stable ID before evaluation. Scores sort descending; ties use the declared tolerance against the highest rounded score in each group (no transitive tie chaining). Competition ranks are 1,1,3. IDs order the presentation within ties and never break ties into winners.

- RANKED: all non-ineligible alternatives are eligible, scored and comparable within declared scope, one top leader. winner_id names a policy leader, never an architect selection.
- TIED: same evidence gates, multiple top leaders within tolerance; winner_id is null.
- RANKING_WITHHELD: unresolved critical checks/criteria or incompatible comparisons; no ranking/winner.
- PARTIALLY_COMPARABLE: allow_partial_ranking explicitly permits ordering at least two fully scored, mutually comparable eligible alternatives while other alternatives await evidence; only conditional_order is populated, definitive=false, no global winner.
- NO_ELIGIBLE_CANDIDATES: every submitted alternative has verified hard failures; no claim about all possible designs.

Known ineligible alternatives remain visible. Incompatible baselines block overall ranking even if one candidate is ineligible. A global rank never compensates for hard failure. Comparison status separately indicates COMPARABLE, PARTIALLY_COMPARABLE, INCOMPARABLE or INVALID_INPUT. Root safeguards always preserve standards_review=NOT_EVALUATED, fengshui_review=NOT_EVALUATED, architect_selection=NOT_PERFORMED, architect_approval=NOT_GRANTED_BY_EVALUATION and cad_writes_permitted=false. Observed selection/review states and valid prior approval records remain visible as independent facts.

## Reproduction and scope limits

`examples/batch006c` supplies 18 immutable scenarios. `tests/golden/batch006c-v0.1.8` pins critical statuses, numeric metrics, decisions, coverage, evidence references and the canonical digest of each complete report (including Markdown). Tests pin historical engine stamps without rewriting older oracles. Unit/CLI tests also cover permutations, exact repeat output, input preservation, invalid policy, target normalization, unsupported checks, optional denominators and exclusive Markdown writes. `scripts/smoke_wheel.py` verifies every canonical code/schema byte and all command families in a fresh isolated venv outside the repository.

Bounded inputs: 1-8 alternatives, <=24 criteria, <=32 requested checks, <=16 prior snapshots; each design <=500 combined source/sidecar polygons, <=10000 polygon vertices, coordinate magnitude <=1e9 declared units. Policy magnitudes <=1e100. These are computational scope limits, never architectural thresholds or infeasibility proofs. Existing review schemas further bound openings, stairs and route inventories.

No optimizer, generated openings/stairs, wall model, legal/code/Feng Shui rule, structure/MEP, aesthetic quality metric, CAD integration or approval authority is added. Recommended Batch 007: capture explicit architect trade-off feedback and revised briefs with digest-bound review history, preserve original solver constraints for replay, and obtain expert-reviewed positive/negative/edge evaluation oracles before broadening measured claims. Continue separate source-governed technical/Feng Shui review.
