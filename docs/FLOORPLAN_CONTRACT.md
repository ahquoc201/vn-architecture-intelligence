# Preliminary floorplan generation contract v1

Engine 0.1.6 / Batch 006-A, algorithm `bounded-grid-rect-v1`. This is a finite search
for preliminary rectangular room polygons, not a complete architectural design or
construction approval. No CAD writer, optimizer, structural/code/Feng Shui rule or
automatic approval is introduced.

## Pipeline and input

`floorplan-input.schema.json` references the existing geometry v1 schema, which links
the governed zoning and canonical Design Brief. The source program is rebuilt using
Batch 004, zoning is validated using Batch 005, and all input/generated geometry is
checked by the existing spatial validator. There are no parallel room or floor IDs.

Input fields:

- schema_version: integer 1
- geometry: geometry v1 with site, explicitly supplied building footprint, floor IDs,
  optional floor outlines, reservations and embedded zoning
- fixed_elements_status: complete or unknown; complete explicitly declares that all
  known fixed/non-allocatable regions have been supplied, including the case of none
- room_dimensions: one record per source room instance, with original room_id, a
  confirmed mandatory requirement_id, and width/depth min/max in geometry units
- parameters: grid_step in geometry units, optional candidate_count (1..3), max_steps
  (1..200000), solution_limit (1..64)
- authorization: purpose=preliminary_generation_only and an architect record using
  Batch 005 actor/role/timestamp/digest semantics

Missing architectural inputs return INCOMPLETE. Malformed values/references are
INVALID_INPUT. The generator requires explicit room min/max area bounds in the
source brief (m2/mm2 through the existing program converter). A preferred target alone
is not a hard area range. No room area, width, depth, floor or footprint is inferred.
The original 4x20 lot is never substituted for an unknown building footprint.

Source brief and zoning must be complete and architect-approved. Active assignments
and floor constraints remain authoritative. Rooms stay on their approved floors; the
solver does not redistribute them. Optional floor envelopes must be axis-aligned
rectangles without holes; site boundaries and reservations may be non-rectangular
valid polygons supported by geometry v1. Different floors are solved in separate 2D
planes and assembled into complete building candidates. Empty source floors remain
explicit; no circulation or vertical coordination is inferred.

Existing room polygons or geometry overlap exemptions in the input are UNSUPPORTED;
the generator does not silently discard supplied design geometry. Explicit source
footprint min/max area bounds cannot conflict with supplied footprint geometry.

## Generation authorization and proposal safety

`authorization_digest(spec)` binds the exact physical input (geometry including zoning,
dimensions, fixed-elements declaration) and grid step. Resource limits and requested
candidate count are excluded from this authorization hash so CLI exploration does not
require rewriting a physical approval. The full input digest still includes those
resolved generation parameters, algorithm ID and supplied authorization record.

Authorization is required for preliminary generation with those constraints. It is not
approval of a generated candidate or permission to write CAD. As in Batch 005, record
checks establish explicit content binding, not identity, professional credentials or
cryptographic authentication. Only a real authorized human may supply a real record;
all fixture actors/records are marked synthetic.

The source geometry's approvals bind its original content. Adding rooms changes that
content, so output polygon statuses are PROPOSED and old polygon approval records are
not copied or re-signed. Original source zoning records remain intact for traceability.
The spatial report's architectural_approval describes **source zoning only**; candidate
approval_status always remains PROPOSED. Architect review is required before adoption.

## Fixed and reserved geometry

Geometry v1 is additively extended with role=reservation and reservation_kind:
circulation, stairwell, service_shaft or other. Every reservation has owning floor,
requirement_id and explicit provenance; it has no program room_id. Its polygon follows
the same frame/units/topology/approval conventions as other geometry.

Reservations must be inside their floor envelope. The spatial validator diagnoses
rooms intersecting reservations. Generation is stricter: any positive room/reservation
intersection is rejected, with boundary contact allowed. Multiple reservations may
intersect each other; their union is subtracted when evaluating available area, avoiding
double subtraction. Only supplied reservations are enforced. A stairwell box is not a
stair design and a circulation reservation is not demonstrated room connectivity.

## Algorithm, constraints and finite search

The envelope's minimum X/Y is the grid origin. Positive grid_step is explicit, not an
architectural minimum dimension. Each room is an axis-aligned rectangle, with width
along X and depth along Y. No automatic rotation swaps the declared dimension bounds.
Grid sizes/areas use Decimal arithmetic; Shapely measures/checks the resulting polygons.
The measured floating-point recheck allows only 1e-12 absolute/relative arithmetic
noise; this is not a design clearance or a way to enlarge allowed geometry.

The solver enumerates every rectangle on that origin-aligned grid satisfying its
width, depth and area bounds and avoiding reservations. Shape choices are ordered by
closeness to the supplied preferred target, then by coordinates. Backtracking chooses
rooms in ascending domain size, floor ID and source room ID, using exact integer cell
masks for same-floor overlap pruning. Mandatory adjacency prunes placements as soon
as both rooms are available. No stochastic operation or random seed is used.

Every completed, non-equivalent layout is independently rechecked for hard area and
dimension bounds, reservations and required adjacency, then passed through spatial
validation and the candidate JSON Schema. Invalid candidates are rejected regardless
of preference scores. Spatial tolerances are caller-supplied and retained, but the
search never deliberately places rooms outside exact envelopes or overlapping rooms.

Supported hard relations: adjacency means positive shared edge length on the same
floor. Corner contact is insufficient; no door or minimum opening is inferred.
Mandatory separation is UNSUPPORTED because Batch 004's qualitative separation request
has no explicit metric/construction definition. Soft separation is reported as unmodeled
and not scored. Do not silently convert it to a numeric clearance.

Textual building/site/client requests are preserved in unmodeled request registers and
unresolved_checks, not interpreted by text matching as satisfied design constraints.
Any unrepresented architectural, specialist or safety requirement still needs review.

Resource bounds:

- At most 12 total room instances and 256 grid cells per floor (also at most 256 steps
  on either axis); these are implementation limits, not architectural constraints.
- Default max_steps=50000, hard maximum 200000. Domain enumeration, placement attempts,
  recursion and candidate acceptance consume deterministic operation steps.
- Default solution_limit=32 distinct valid layouts, maximum 64. Search stops at this
  limit even if further layouts may exist. Default requested candidate_count=3.
- Time is not used as a stopping condition, preserving exact repeated output. Work is
  finite; expensive topology/schema checks are bounded by the operation and room limits.

The grid may omit feasible continuous positions/sizes, especially when its step does
not divide an envelope or area request. No global optimum or continuous completeness
is claimed, including after the finite grid has been fully examined.

## Candidate diversity, scoring and output

`floorplan-candidate.schema.json` embeds geometry v1. Each candidate includes stable
candidate_id, input_digest, algorithm/schema version, effective parameters, floor_id
(single-floor only) and floor_ids, full room geometry, measured room_areas_m2,
hard_validation with spatial_report, soft_scores, unresolved_checks, generation_status,
approval_status=PROPOSED and cad_writes_permitted=false.

A layout signature is the sorted set of room equivalence classes and rectangular
bounds. Instances with the same source room group, floor, requirement, functional zone
and dimensional constraints are interchangeable for diversity purposes. Swapping two
such labels does not create another candidate. Distinct source groups/constraints remain
distinguishable. Rotations/reflections relative to declared coordinates are different
physical placements; reordering ring vertices or dictionary keys is not diversity.
Candidate IDs hash the input digest and layout signature. No index-only alternative IDs.

Scores in [0,1], with fixed weights 0.5 adjacency + 0.5 area:

- Preferred adjacency: fraction of explicitly supplied preferred instance pairs sharing
  a positive edge on the same floor. No preferred pairs gives neutral satisfaction 1.
- Preferred area: mean max(0, 1 - abs(actual-target)/target) for supplied positive targets.
  No target gives neutral satisfaction 1. Min/max bounds remain hard constraints.

Only discovered valid candidates are ranked by descending total, then candidate ID for
stable tie-breaking. Return at most the requested count and explain fewer alternatives.
Scores are not architectural quality or buildability scores. No claim of finding the
best candidate outside the bounded explored set is made.

## Status and CLI contracts

```powershell
vnai design floorplan generate examples/batch006a/alternatives.json --candidates 3
vnai design floorplan generate examples/batch006a/fixed-stair.json --out outputs/new-proposals.json
vnai design floorplan generate examples/batch006a/search-budget.json
```

Statuses/exit codes:

- GENERATED / 0: at least one distinct validated candidate; warnings disclose partial
  search, unmet requested count or unmodeled preferences.
- INVALID_INPUT / 1: schema/type/reference/provenance/topology errors or stale approval.
- Input read/parse/output/usage errors / 2: machine-readable INPUT_ERROR for operational
  failures; argparse retains conventional usage diagnostics.
- INCOMPLETE / 3: missing data, unapproved zoning, unknown fixed elements or missing
  explicit generation authorization. No candidates are fabricated.
- INFEASIBLE / 4: analytic necessary-condition proof, such as total minimum area exceeding
  envelope minus reserved union, or dimensional/area bounds impossible even before packing.
- UNSUPPORTED / 5: constraints/shapes/resource scope not implemented by this solver.
- SEARCH_EXHAUSTED / 6: no candidate found in the specified finite grid/budget; termination
  distinguishes STEP_LIMIT from GRID_SPACE_EXHAUSTED, neither proves continuous infeasibility.

No infeasible/incomplete/invalid result contains candidates. A partial search that found
valid layouts returns GENERATED with PARTIAL_SEARCH. Search metadata never claims
optimality_proven. The original input file and all source models remain unchanged.

CLI emits deterministic ASCII-escaped JSON to stdout. --candidates overrides count;
--max-steps overrides the operation budget. --out writes an explicitly requested **new**
UTF-8 JSON file using exclusive creation; existing files (including inputs and prior
reports) are never overwritten. No output file is written by default; no CAD writes occur.

## Evidence, packaging and next batch

`examples/batch006a/` contains synthetic two-room, alternative-layout, multizone,
fixed-stair, missing-footprint, insufficient-area and budget-exhaustion specifications.
All numerical constraints and approval records are explicitly synthetic. Versioned full
golden reports live in tests/golden/batch006a-v0.1.6/. Batch 005 snapshots remain untouched;
replay tests use their historical version stamps while exercising current implementations.
Separate tests verify the current 0.1.6 engine stamp and all unchanged regression assertions.

The existing wheel build hook bundles the new schemas automatically from their canonical
source locations. `python scripts/smoke_wheel.py` verifies code/data bytes and installs a
fresh wheel outside the checkout, covering successful generation, incomplete inputs and
search exhaustion alongside the previous CLI checks.

Remaining limits: no non-rectangular room search, rotations of dimension axes, optimizer,
doors/windows, full stairs, inter-floor coordination, circulation/accessibility/egress
verification, structure/MEP or legal/Feng Shui compliance. Source approval record identity
still needs a trusted external service. Batch 006-B should add reviewed candidate adoption,
circulation/connectivity and opening/stair/clearance geometry contracts before CAD output.
