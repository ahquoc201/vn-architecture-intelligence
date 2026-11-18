# Candidate, openings, circulation and stair review v1

Engine 0.1.7 / R2 Batch 006-B. These tools evaluate explicit model data, not a complete
architectural design. No automatic door/stair placement, candidate ranking, CAD writes,
legal/Feng Shui rules, authentication or digital signatures are implemented.

## One immutable candidate, one review sidecar

`candidate-review.schema.json` accepts the actual `floorplan-candidate.schema.json`
contract from Batch 006-A. Do not copy room polygons into a competing room model.
The sidecar holds schema_version=1, candidate, optional exact selection, decisions,
exteriors, openings, stairs, fixed_obstacles, clearance_regions and passages.
All CLI commands below consume this same sidecar, so they share IDs and content.

The original candidate is never mutated. Current spatial validation is rerun, floor
metadata and stored area measurements are checked, and available source hard room-area
bounds are rechecked. A stored hard_validation.passed flag is not treated as a fresh
geometric verdict. Original solver dimensional constraints are not fully replayable
without the original generation specification; that limitation is reported explicitly.

`candidate_digest(candidate)` hashes canonical JSON including its original generation
metadata. Selection references both exact candidate_id and candidate_digest. A mismatch
stops all review tools. `design_digest(sidecar)` hashes every sidecar field except the
decision history. Changing an opening, route, stair, obstacle, completeness declaration
or the candidate makes prior design review records stale. Dictionary key order does not
change the digest; list order is retained. Keep immutable earlier versions/reports.

## Review states and provenance

A matching explicit selection is SELECTED; candidate-only data remains UNSELECTED and
INCOMPLETE. Selection itself never fabricates an actor or approval. Optional SELECTED
events record the supplied actor, role, timezone-qualified timestamp and provenance.

Allowed explicit transitions:

- SELECTED -> REVIEWED, REJECTED or SUPERSEDED
- REVIEWED -> APPROVED, REJECTED or SUPERSEDED
- APPROVED -> REJECTED or SUPERSEDED
- REJECTED/SUPERSEDED are terminal; create a new review/version rather than promote them

REVIEWED/APPROVED records require the declared architect role. All records require the
exact current design digest, unique event ID and nondecreasing valid timestamps. An
invalid event is diagnosed and does not promote state. Reports retain decision_history,
selection_record, provenance, timestamps and content digests. No actor identity is inferred.
`approval_record_valid` means an explicit content-bound APPROVED record passed these
checks, not that the actor's identity, credentials or professional judgment are verified.

The generated candidate's own approval_status remains PROPOSED. Human sidecar approval
is reported separately. An architect can record review of a concept that still lacks
technical information; the architectural report continues to show those missing checks.
Even APPROVED content never sets technical compliance to PASS or permits CAD writes.

## Geometry IDs, units and supplied regions

Candidate room nodes use source room instance IDs. Circulation/stairwell reservation
nodes use their existing geometry IDs. Exterior access IDs are explicit sidecar IDs.
Every opening/stair/path declares floor_id, frame_id and units matching the candidate.
Metric calculations use m and m2, following the geometry contract's boundary_m,
overlap_m2 and min_area_m2 tolerances. No frame transform, snapping or repair is applied.

Sidecar fixed_obstacles and clearance_regions reuse the existing geometry polygon
schema: floor-owned role=reservation with source requirement_id and provenance.
Their IDs cannot conflict with candidate geometry/floor/frame IDs. Invalid topology,
nonpositive/near-zero areas, unknown floors, ownership and unit mismatches are errors.
Fixed obstacles use reservation_kind other/service_shaft and stay inside their floor
envelope. Candidate non-circulation reservations are also treated as known fixed regions.

Exteriors declare id, floor_id, boundary_id and provenance. boundary_id references a
site/footprint/floor-outline outer ring, never a polygon hole. An optional approach_id
references an explicit clearance polygon outside the building interior on that floor.
An exterior node's geometry_id records its hosting boundary; the approach is separate
input geometry, not an inferred street or public right-of-way.

## Provisional boundary-hosted openings

`opening.schema.json` version 1 describes an explicit opening, not a complete wall:

- id, floor_id, frame_id, units, provenance and proposed/confirmed state
- kind interior or entrance; exactly two connected space IDs
- door_type hinged, sliding or open_passage
- host.start/end and opening start/end points
- clear_width, positive in declared units and no greater than the geometric span
  beyond the declared boundary tolerance
- optional hinge/swing, local clearance_id and sliding_envelope_id

Host segments must lie on both compatible connected-space boundaries. The opening
must fit the host. Entrances connect exactly one explicit exterior node; interior
doors connect no exterior. Spaces must exist on the same floor. Duplicate IDs and
positive-length overlapping spans on the same floor are errors; shared endpoints alone
are not an overlapping opening. Unconfirmed openings cannot create verified graph edges.
Two rooms sharing a wall do not produce any opening automatically.

Hinged doors support explicit hinge=start/end, clockwise/counterclockwise rotation,
90-degree angle and opens_into one connected interior space. No direction is inferred.
The zero-thickness leaf radius is the supplied opening span, a conservative provisional
motion model rather than a detailed door leaf/hardware model. A 32-part tangent enclosure
bounds the quarter-circle sweep from outside; known collisions or sweeps outside the
space are reported. This can be conservative near corners; no automatic repair occurs.
Raw conservative geometry drives collision decisions. Reported swing display vertices
are rounded to 12 decimals for stable serialization and are not used to decide collisions.

Sliding motion requires an explicit sliding envelope on the same floor, consistent
with its opening and connected spaces. Open passages have no swing metadata. No
minimum door width, door-leaf thickness, sill height or hardware specification is invented.
Known positive-area swing/envelope collisions and conflicting door swings are diagnosed;
intersection thresholds use the caller's existing overlap tolerance.

Opening clearance regions must contain the opening and lie in its connected spaces.
An external approach polygon is required to assess outside clearance. Missing motion,
clearance or fixed-obstacle information remains NOT_VERIFIED/INCOMPLETE, never PASS.
A local opening can be GEOMETRICALLY_TRAVERSABLE only for the supplied bounded model;
that alone says nothing about walking through the rest of a room or corridor.

## Graph connectivity is a separate layer

`circulation-graph.schema.json` reports room, circulation, stairwell and exterior nodes.
Only confirmed geometrically valid opening connections create opening edges. Stair
edges require actual validated entry/exit opening references. Every edge preserves ID,
kind, connected spaces and an independent physical_state. A blocked swing may retain
its topological door edge while its physical_state is BLOCKED; topology is not access.

Traversal is deterministic: nodes/components/neighbors are ordered by stable IDs.
The report includes disconnected components, isolated rooms, entrance_status and each
room's graph reachability from explicit external origins. GRAPH_CONNECTED requires
one connected component, an actual entrance and reachability of all rooms. Separate
exterior-access components are still reported as disconnected, even if each has rooms.

When an inventory is explicitly complete, missing entrance chains or disconnected rooms
are known model conflicts. When opening/stair information is incomplete or unconfirmed,
undemonstrated access is NOT_VERIFIED, not automatically a blocked physical doorway.
Graph topology can be known while local clearance remains unknown. Connection errors
are also present in graph diagnostics/status rather than hidden by a connected graph.

## Supplied walking paths and clearance

A passage identifies space_id, floor/frame/units, path coordinates, positive required
width, one/two incident opening IDs, confirmation and provenance. The width is supplied
by the reviewer; it is never taken from an unverified normative minimum.

The checker buffers each explicit simple centerline by half its declared width, using
flat caps and mitre joins. This conservative planar envelope must stay inside its space
and avoid known obstacles. Width must fit each incident opening's declared clear width.
A two-opening route joins their midpoint portals. A one-opening route joins its midpoint
to an explicitly supplied interior destination. Coordinates/order may be reversed.
No path is inferred from a polygon centroid, adjacency or graph connectivity.

A separate portal graph connects locally clearance-verified doors through verified
same-space walking routes. Exterior origin routes must include a supplied approach
polygon and an explicit outside destination point. Room access must reach a validated
interior walking route, not merely a node in the simpler space graph. Tuple portal keys
avoid aliasing IDs containing separators.

GEOMETRICALLY_TRAVERSABLE is restricted to complete chains of these supplied planar
width checks with fixed_obstacles_complete=true. Missing local envelopes, paths, origins
or known-obstacle declarations remain NOT_VERIFIED. Known collisions/width conflicts
are BLOCKED. Invalid references remain data errors with NOT_VERIFIED physical state;
a bad ID alone is not proof of a physical obstruction. This is not a full-body, turning-radius, furniture, headroom, accessibility
or egress certification; unsupported evaluations remain visible. Geometry tolerances
are conditional on the caller's data, not surveyed/expert validation.

## Stair connectivity

`stair-connection.schema.json` version 1 references existing stairwell reservation
polygons, not invented tread geometry. Source/destination records identify floor,
stairwell_id and connected space_id, optional landing_id, actual opening_id and point.
Direction up/down, alignment_required, confirmation, review_status and provenance are explicit.

Floors must exist and differ. Entry/exit point and opening data are required for a
verified graph edge. Each point lies on the validated opening and both space/stairwell
boundaries. A landing reference must identify the actual same-floor circulation node
connected at that endpoint. Envelopes stay within the floor region and cannot intersect
known fixed obstacles. Alignment is checked only when explicitly requested. Direction
is compared with supplied elevations; missing elevations are reported, never guessed
from a floor name. Endpoint geometry can establish graph connectivity even when rise
metadata remains unresolved, but cannot establish physical stair traversal.

Stair review is not architect approval. No riser height, tread width, headroom, slope,
load or safety limit is generated or certified. Any graph with an active stair link
retains NOT_VERIFIED for whole-route physical circulation in this batch. Technical
stair design remains NOT_EVALUATED regardless of an envelope/entry check passing.

## Architectural report, statuses and commands

`architectural-review.schema.json` combines independent candidate_review, opening_validation,
circulation_graph, stair_validation and clearance results, plus blocking_issues, missing
information, unsupported_evaluations and next actions. Candidate ID/digests are preserved.
Geometry, graph, physical_circulation_status, technical_compliance and architectural_approval
are separate fields. fully_verified and cad_writes_permitted are always false.

Stage status/exit codes: VALID/0, INVALID/1, read/parse/usage error/2, INCOMPLETE/3.
VALID means the stated stage's bounded checks are satisfied. For example a SELECTED
record may be VALID without approval, and a GRAPH_CONNECTED graph may have unknown
walking clearance. The combined architectural report is INCOMPLETE if required supplied
checks remain missing, INVALID for known errors, otherwise VALID for this limited scope.
Even a scope-valid report is not a fully verified house or construction approval.

```powershell
vnai design candidate review examples/batch006b/selected-only.json
vnai design openings validate examples/batch006b/corridor-clearance.json
vnai design circulation analyze examples/batch006b/corridor-graph-only.json
vnai design stairs validate examples/batch006b/stairs-connected.json
vnai design architectural-review examples/batch006b/corridor-clearance.json
```

All commands read UTF-8, emit deterministic ASCII-escaped JSON and write no files.
No input/candidate mutation or CAD export occurs. Preserve report snapshots under
versioned names in the calling workflow, rather than overwriting earlier reports.

## Fixtures, verification and limitations

examples/batch006b contains 13 explicitly synthetic review sidecars, starting from real
Batch 006-A candidates. They cover no-door adjacency, valid doors, host errors, swing
collisions, disconnected rooms, unknown opening data, corridor graph-only versus supplied
planar clearance, connected/missing-entry stairs, selected-only, approved-content and
stale-approval records. Golden reports are stamped under tests/golden/batch006b-v0.1.7.
Historical Batch 005/006-A snapshots are preserved; replay tests retain their recorded
metadata while exercising current implementations. New tests check the current engine.

The wheel bundles all new schemas from their canonical source paths. The fresh-venv
smoke script runs old/new CLI checks outside the repo and verifies code/data bytes.
All examples and actor identities are synthetic; never treat their records as real approval.

Remaining limits: provisional boundary hosts without full walls, 90-degree zero-thickness
swing model, explicit sliding envelopes/paths only, no automatic placement or ranking,
no stair walking verification, no complete accessibility/egress/structure/MEP review,
no authenticated architect identity/signatures, and no QCVN/TCVN or Feng Shui enforcement.
Batch 006-C should compare candidates using declared coverage and unresolved issues,
add reviewed design decisions and address these geometry/model gaps before broader ranking.
