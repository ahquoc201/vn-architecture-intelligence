# Zoning and 2D geometry contracts v1

Engine 0.1.5 / R2 Batch 005. Both contracts extend the Batch 004 brief/program
workflow without changing its input schema or room instance naming. They generate
no layouts, perform no CAD writes and apply no legal or Feng Shui rules.

## Sources, identity and unresolved information

`knowledge/architecture/zoning.schema.json` embeds the canonical Design Brief schema
by local reference. Python's local schema registry resolves that reference without
network requests. `create_zoning_proposal(brief, proposal_id)` builds the existing
space program, uses its `<group-id>:<index>` room IDs and source requirement IDs,
and copies only floor assignments already supplied in the brief. Missing floors
stay null; zone is `unresolved`. Multiple instances can receive separate decisions.
No optimizer or default mapping from room type to functional zone is provided.

The zoning document contains proposal_id, revision, source brief, floors, assignments,
constraints, assumptions and decision records. Floors may declare elevation with m/mm
units; no storey height is inferred. Zone is a nonblank, extensible client/architect
label (for example public/private/service/circulation); `unresolved` is reserved.
Each assignment records id, room_id, requirement_id, floor_id, zone, provenance,
confirmation (`proposed` or `confirmed`), status and optional rationale.

The source program is rebuilt and validated on every call; arbitrary serialized
program outputs are not trusted. A confirmed floor in the brief cannot be overridden
by a zoning proposal: revise the source brief explicitly. Rejected/superseded decisions
remain in history and do not assign a room. Missing room assignments, zones, approvals,
assumptions and source-brief questions remain structured missing information.

Floor constraints express hard/soft `require` or `exclude` decisions using instance IDs
and source requirement IDs. Hard constraints need confirmed mandatory provenance.
Contradictory floor constraints are diagnosed even before rooms are assigned.
Original adjacency/separation relationships and requirement IDs are carried through;
required adjacency on different floors is an error, a preferred one is a warning.
Separation is not treated as an invented metric distance requirement.

## Human approval and content binding

Assignment statuses: proposed, reviewed, approved, rejected, superseded.
Confirmation and approval are independent: confirming a floor is not architect approval.
Decision records contain an event ID, decision ID, action and architect record with
actor, role=architect, timezone-qualified ISO timestamp and SHA-256 digest.
Timestamp validation is built in (no optional format dependency), supports up to
six fractional-second digits and rejects leap seconds/invalid calendar dates.

Allowed transitions:

- proposed -> reviewed, rejected or superseded
- reviewed -> approved, rejected or superseded
- approved -> rejected or superseded
- rejected/superseded -> no further transitions; create a new revision/decision

History is ordered per assignment; timestamps must be nondecreasing. Declared status
must equal the state derived from history. Approval requires a confirmed, non-null
floor assignment and a resolved zone. `decision_digest` binds the entire source brief,
revision, floor metadata, all assignment contents, constraints and assumptions.
Status/event records are excluded from the content hash to avoid circularity.
Editing any bound content invalidates old review records. Keep earlier reports and
revisions; obtain a fresh review rather than rewriting approval history.

These records check **content integrity and explicit intent**, not professional
credentials, identity, signatures or authorization. A future trusted approval service
must authenticate the architect and protect append-only history. Tools do not grant
permission to write CAD. Example actors say SYNTHETIC and are not real approvals.

Zoning is VALID only when source data and all active assignments are complete and
approved with no errors. architect_approved remains false if any issue blocks this
gate; proposed/reviewed cases are INCOMPLETE. Warnings do not block this data gate.

## Geometry and coordinates

`geometry.schema.json` defines one common 2D frame: x east, y north, one homogeneous
unit (`m` or `mm`) and frame_id. All area reporting is m2. Each polygon explicitly
repeats frame_id/units to detect mismatched imports. No automatic coordinate conversion
or CRS reprojection occurs. Metric scaling to metres is used for validation only.

Frame kind is `local_site` or `world`. World coordinates require an explicit projected
CRS label; the tool does not verify/reproject that CRS. Local-site origin_world and
rotation_degrees, when supplied, must appear together and describe a future transform.
They do not cause geometry to be transformed. All coordinates in the document are
already in its declared frame. Do not mix world and local geometries in one document.

Floors carry IDs and optional elevation_m. Polygons contain id, role, owner_id,
frame_id, units, exterior, optional holes, status and optional approval record.
Roles are site, footprint, floor_outline, room. Exactly one site and at most one
footprint are supported; at most one outline per floor. Site/footprint belong directly
to project_id; floor/room polygons belong directly to floor_id. Rooms require the
source instance room_id and requirement_id. Geometry/floor IDs are unique and may
not reuse the project or frame ID. Duplicate room geometry is rejected.

Rings are arrays of [x,y], with at least three vertices; closure may be explicit or
implicit. Polygon holes are supported and subtracted from area. Shapely validates
self-intersections, invalid holes and topology. Zero/near-zero polygons are errors.
Expected winding is CCW exterior, CW holes; reversed winding produces a warning and
is never silently rewritten. No buffer(0), make_valid, snapping or topology repair
is applied. Multipart polygons, curves, 3D coordinates and disconnected room shapes
are unsupported and rejected; use a later version rather than discarding pieces.

Points use id/owner_id/xy in the document's frame; segments reference start/end point
IDs and owner_id. Segment endpoints must have the same owner and distinct positions.
Optional wall_refs/opening_refs are opaque future references, preserved but not
resolved or treated as actual walls/openings in this batch.

## Tolerances, spatial relationships and area accounting

Tolerances are explicit caller-supplied workflow values, never architectural minima:

- boundary_m: allowed envelope distance slack
- overlap_m2: tolerated positive same-floor intersection area
- min_area_m2: polygons must exceed this area
- target_area_m2: absolute room target/bounds mismatch reporting tolerance

No architectural tolerance defaults are inferred. Geometry fixtures supply illustrative
values only. Exact covers() includes shared boundaries. Beyond an exact envelope but
within buffer(boundary_m) is a warning; beyond tolerance is an error. Buffers are
used only to test containment; original polygons and their areas remain unchanged.
Footprints must lie inside the site; outlines inside footprint/site; rooms inside
floor outline, otherwise footprint, otherwise site. Envelope approval flags are
reported independently, so validation against a proposed boundary never implies approval.

Rooms are compared only on the same floor. Zero shared-boundary area is not overlap.
Positive overlap above the declared threshold is an error; below it is a tolerance
warning. Intentional overlaps require an explicit relationship with source requirement,
provenance, rationale and a current architect approval record. A proposed overlap
exemption does not suppress an overlap error. Area accounting reports both room sum
and polygon union so intentional overlap is not hidden or double-counted as net union.

Geometry approval hashes bind polygons, point/segment references and coordinates,
relationships, frame, units, tolerances, floor metadata and linked zoning. Mutation
makes records stale. They provide record integrity, not identity authentication.

Reports separate site area, footprint area, per-floor envelope area, room polygon sum,
room union and geometric residual. Residual is envelope minus supplied room union,
not verified usable unallocated space. GFA is reported only as the sum of all explicitly
supplied floor outlines when every floor has one; it is never footprint times storeys.
Room polygon areas are not guaranteed finished clear areas. Polygon accounting does
not verify circulation, construction, room function, structural safety or legal compliance.

Optional embedded zoning links geometry to approved decisions and source area requests.
It checks project/floor IDs, elevations when supplied in both layers, source room IDs,
requirement IDs, floor decisions, missing polygons and supplied room-area targets/bounds.
Area mismatches are warnings, consistent with existing geometry review behavior.
Geometry without zoning can be spatially VALID while architectural_approval remains
NOT_EVALUATED. A linked incomplete zoning returns INCOMPLETE. Valid spatial checks
never establish buildability, and cad_writes_permitted is always false.

Resource limits: 500 polygons per geometry document, plus existing program expansion
limits (10000 room instances/100000 relationship pairs). These protect execution and
are not design or regulatory requirements. Spatial algorithms reuse Shapely; no geometry
optimization, polygon subdivision or floorplan generation is implemented.

## CLI, fixtures and reproducible verification

All new commands emit deterministic ASCII-escaped JSON and read UTF-8, without changing
inputs or writing output files. Reports include schema/engine version stamps and separate
errors, warnings, missing_information and diagnostics. Exit codes: 0 VALID, 1 INVALID,
2 read/parse/usage error, 3 INCOMPLETE. Legacy CLI outputs remain unchanged.

```powershell
vnai design zoning validate examples/batch005/zoning-proposed.json
vnai design zoning report examples/batch005/zoning-approved.json
vnai geometry validate examples/batch005/geometry-valid.json
vnai geometry report examples/batch005/geometry-linked-approved.json
python -m pytest -q
ruff check .
python scripts/smoke_wheel.py
```

`examples/batch005/` contains synthetic unresolved, proposed, approved, valid, overlap,
outside-footprint, invalid-polygon and multistorey cases. `tests/golden/batch005/` contains
full deterministic reports stamped 0.1.5. These are test oracles for the stated contracts,
not architectural standards or approved customer designs. Preserve historical snapshots
when evolving contracts; do not erase earlier reports just to accept a regression.

## Wheel packaging and remaining limits

Canonical authored data stays in knowledge/ and sources/. setup.py's build hook copies
only the allowlisted runtime schemas/YAML into vnai/_data inside the wheel. MANIFEST.in
includes those files in source distributions. Resource lookup uses canonical checkout
data for development, packaged data for normal wheel installs; it does not depend on cwd.
There are no hand-maintained duplicate data copies in version control.

The smoke script builds a wheel, verifies packaged data bytes, installs it in a fresh
virtualenv and runs 12 existing/new command checks outside the checkout using isolated
Python with UTF-8 enabled. It verifies vnai imports from that virtualenv and saves
versioned evidence in outputs/wheel-smoke/. It needs pip dependency access/cache.
Ordinary extracted wheel installs are supported; zipimport/frozen executable packaging
and authenticated approval storage remain future work.

Batch 006 should accept only explicitly reviewed inputs, create reproducible candidate
layouts with decision provenance, and add door/stair/circulation/clearance geometry tests.
Keep candidate generation separate from approval and CAD writing. Do not add a claim of
construction readiness or enable unverified legal/Feng Shui constraints.
