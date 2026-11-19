# Architectural wall geometry contract v1 (engine 0.1.10)

Batch 007-B1 derives a separate **PROPOSED** wall revision from an immutable selected
Batch 006 floorplan and its Batch 007-A replay/readiness input. It produces real 2D
wall polygons, exposed faces, centerlines, junction cores, union footprints and clear
room geometry. It does not draw CAD or establish construction readiness.

## Source and specification

`knowledge/architecture/wall-input.schema.json` reuses the existing cad-readiness
input as `source`, including replay mode, exact candidate selection, original
provenance and, for external edits, parent/child revision records. Existing room
polygons represent **allocations**; none establishes finished-face semantics by itself.
Historical candidates are accepted with explicit incomplete provenance diagnostics.
A geometrically valid legacy allocation cannot acquire reconstructed solver history.

`wall_specification` version 1 requires an ID, treatment list and explicit special-wall
list. Bind `source_candidate_digest` and `source_design_digest` to the exact existing
review. Declare `boundary_semantics`, wall intent and constraint bases. Missing
thickness, alignment, semantics or confirmation remains incomplete; no house-type
wall thickness, material, structure or direction is invented.

Each treatment has an ID, rationale, selector and action (`wall`, `no_wall`,
`unresolved`). Selectors use boundary kind and optional source floor, room and boundary
IDs. Most specific wins: boundary +4, room +2, floor +1. Explicit special profiles
have priority 8. Equal-priority incompatible actions/profiles are invalid. Equivalent
profiles merge intent ownership and produce one wall per boundary atom. Default is
unresolved; `default_treatment: no_wall` is an explicit architectural decision.
Unknown room/floor/boundary references are invalid; selectors that match no atom do not create walls.

Wall profiles carry classification, thickness and unit, alignment, optional signed
offset, optional per-wall semantics/reference room, supplied assembly ID, fixed/editable
state, source requirement IDs, provenance, confirmation and declared review state.
No load-bearing status is inferred. Approval declarations require an existing
content-bound architect record; validation checks consistency, not reviewer identity.
Every derived wall remains PROPOSED and wall revision approval remains NOT_GRANTED.
All examples and reviewer records in fixtures are synthetic, not professional advice.

## Coordinates, semantics and alignment

Supported source frames/units are the existing local Cartesian frame with m or mm;
all output coordinates/areas are m/m2. Special references must use the exact source
frame and unit. Convert once to metres; never interpret mm as m. Boundary endpoints
are lexicographically canonical: horizontal west-to-east, vertical south-to-north.
The left normal is respectively north `[0,1]` and west `[-1,0]`, independent of ring
winding or vertex start. Positive offset is along this left normal.

For thickness t and signed offset d the perpendicular band is:

| Alignment | Normal interval relative to reference |
| --- | --- |
| centered | [d-t/2, d+t/2] |
| left | [d, d+t] |
| right | [d-t, d] |
| inward | left/right determined by envelope interior |
| toward_room | left/right determined by associated room interior |

`allocation_boundary` permits explicit alignment/offset without relabeling source
allocations as finished faces. `wall_centerline_reference` requires centered alignment;
an explicit offset records displacement from that reference. `exterior_finished_face_reference`
requires an exterior boundary, inward alignment and zero displacement.
`interior_finished_face_reference` requires an unambiguous reference_room_id, wall on the opposite
side of that room and zero displacement. Incompatible interpretations are unsupported.
Ambiguous toward_room needs an explicit reference room. The actual centerline is the
midpoint of the resulting band; measured thickness is its declared perpendicular width.
Offsets are explicit design changes, not hidden corrections.

## Topology and constructive joints

`wall_topology.py` nodes envelope, room, reservation and special reference segments
using Shapely union, splits collinear overlaps/crossings and deduplicates canonical
atoms while preserving all owners. Shared boundaries carry both rooms. Boundary kinds
include exterior, shared, room_reserved, room_unallocated, reservation_only and special.
Extracted boundaries do not automatically become walls. Open-plan/circulation intent
requires explicit no_wall or a selected profile. Floors are processed independently.

`wall_geometry.py` constructs finite rectangular bands. Endpoint topology identifies
END, COLLINEAR, L, T and X nodes. For each contacting horizontal/vertical pair, the
intersection of their infinite bands is an explicit rectangular junction core. Only
that pair owns its core; cores extend their contacting individual bands. This closes
supported corners without transferring a wider wall's thickness to every neighbor.
Core contact requires positive area or positive-length edge with both finite strips.
Disconnected offset cores and collinear bands without positive transverse overlap are
UNSUPPORTED; the engine never bridges a designed gap, clips a wall, snaps vertices,
uses buffer(0), or makes a validity repair. Each wall's final polygon must be connected
and valid. Unsupported output/components are retained with diagnostics.

Individual wall polygons and joint cores may overlap by design. Floor wall area uses
`unary_union(individual walls)` **once**, not their area sum. Reports expose individual
sum, union, overlap excluded from double counting, inside and outside envelope areas.
Any positive area outside the supplied floor outline/building footprint is a CONFLICT;
it is retained in both report and preview, never silently clipped. The lot is not a
replacement building envelope.

Faces are actual exposed portions of the combined footprint boundary on each wall's
two supporting face planes. Internal junction seams are excluded; exterior/interior
roles follow source room/envelope sides. Contacts can shorten or split faces. Shared
junction ownership may repeat a physical face fragment across individual owners, so
summing individual face lengths is not a global perimeter measure. Numerical face
comparison error bounds (max 1e-12 m or four coordinate ULPs) are reported; they do not
repair geometry or exempt outside/reservation area. Source spatial tolerances retain
the existing validator meaning. Aggregate area is not rounded for decision checks.

## Clear room geometry and requirement impact

`wall_impact.py` computes each original allocation intersect/difference with the floor
wall union. Reports retain allocation polygon/area, wall-occupied area, all clear
components/holes, component areas, signed area/percentage change and source requirement
references. Empty or disconnected clear space is blocking. Non-area remnants are
retained separately; no largest-component shortcut is used.

`allocation = occupied + clear` within floating precision. These measures are **not**
certified gross floor area or net usable area. No national area convention is inferred.
`constraint_basis.area` and `.dimensions` must explicitly be allocation, clear, both
or unresolved. Original bounds are replayed on allocations using 007-A. Do not silently
relabel them as clear bounds. Clear-bound failures conflict when clear/both is declared;
allocation-only reduction is reported separately with a basis warning. Missing or
unconfirmed walls leave clear-constraint results UNKNOWN even if a conditional shape
can be previewed. Full wall information means confirmed input declarations and supported
geometry, not authenticated expert sign-off.

Clear area is measurable for orthogonal polygons. Clear width/depth checks require a
single rectangular component without holes. Nonrectangular dimensions are UNSUPPORTED,
never proved with a bounding box. The L-room example has real valid wall geometry but
retains the existing 007-A rectangular-dimension replay limitation. Walls intersecting
known reservations/fixed obstacles produce visible conflicts. Rooms are never resized,
requirements relaxed or benchmark inputs altered to make the result pass.

## Bindings, invalidation and readiness

`walls.py` is the typed orchestration API (`generate_walls`, `validate_walls`). It reuses
existing source schema, bounded geometry, canonical digests, replay and readiness policy.
Boundary IDs depend on source ownership/reference, wall IDs also on explicit intent IDs;
changing thickness changes geometry/digests without changing the same logical wall ID.
Canonical ring winding/start, normalized unordered treatment/selector lists and sorted
records give reproducible output. Source digest retains exact source content semantics.
Derived digest binds physical walls/faces, footprints and clear rooms; wall revision binds
source design, specification and derived geometry. No original candidate is mutated.

Original allocation evidence remains applicable to the original allocation. Fresh
allocation replay is recorded. Opening/graph/clearance/evaluation evidence and architect
approval do not certify the wall revision. Opening references map only when exactly one
wall reference segment covers their boundary with compatible floor/space associations.
Mapped hosts still REQUIRE_REVIEW, bound to wall ID/geometry digest. Ambiguous or absent
hosts remain explicit. No doors/windows are created, no wall openings cut and no old
boundary-based clearance retained as verified physical traversal.

Geometry status, specification confirmation, source readiness, derived readiness and
architect approval are separate. Source READY_FOR_DRAFTING for room_geometry cannot
promote this revision into complete architectural drafting. Conflicts yield NOT_READY;
otherwise fresh wall/opening/circulation review remains INCOMPLETE. CAD permission and
approval inheritance are always false; QCVN/TCVN and Feng Shui are NOT_EVALUATED.

## CLI and reports

```powershell
vnai design walls generate examples/batch007b1/rectangle-inward.json
vnai design walls validate examples/batch007b1/shared-wall.json
vnai design walls report examples/batch007b1/t-junction.json --markdown outputs/walls-v0.1.10.md
vnai design walls preview examples/batch007b1/townhouse-benchmark.json --out outputs/townhouse-walls-v0.1.10.svg
```

All actions print deterministic JSON with domain `wall_status`. Exit codes:
GENERATED 0, INVALID_INPUT 1, operational/input-read error 2, INCOMPLETE 3, CONFLICT 4,
UNSUPPORTED 5. `validate` accepts a specification or stored wall report; stored report
validation recomputes and checks derived content/bindings instead of trusting pass flags.
Only requested --markdown/--out files are created, exclusively (existing files preserved).
Preview can be generated for inspectable conflicts/incomplete geometry with the same
nonzero domain code. Invalid inputs without floor geometry create no SVG.

`wall_preview.py` renders **actual result polygons**, original allocation dashes,
reservations, wall/room IDs and scale bars. All panels have the same uniform local-metre
scale and correct y-axis inversion/aspect ratio. Metadata binds engine/source/specification/
derived/revision digests. Preview is proposed geometry, not a construction drawing.
Committed SVG examples: `examples/batch007b1/previews/` (rectangle, shared, T, X, townhouse).
Full wall records are defined in `wall-result.schema.json`, with reusable metric PolygonSet.

## Verification and scope

27 versioned fixture projections in `tests/golden/batch007b1-v0.1.10` bind complete report
hashes and deterministic SVG hashes. Independent elementary oracles cover 4x5 inward
walls: clear 3.6x4.6 = 16.56 m2; envelope20 minus clear = wall3.44 m2. Shared-wall union
5.5, T6.375, X6.75, L6.84, mixed-thickness X11.28 and L7.44 m2 are independently tested.
Tests also protect collinear deduplication, offset/envelope failures, no_wall, missing data,
empty/disconnected clear geometry, reservations, stale evidence, multi-floor isolation,
historical compatibility, mm conversion, semantics, approval, CLI and stored tampering.
The townhouse uses unchanged benchmark A generation specification and reports its new
clear/reservation conflicts honestly; expert review remains pending.

Scope: rectangular floor envelopes, valid orthogonal source room polygons without source
holes, straight orthogonal references, bounded coordinates, explicit profiles. Curves,
slopes/diagonal walls, source holes, ambiguous directions, unsupported offset joints and
nonrectangular clear-dimension proof produce diagnostics. Existing resource limits apply
(12 rooms/floors, bounded source polygons/coordinates); wall topology additionally caps
256 source edges per floor, 512 atoms, 128 treatments and 64 special walls. No new runtime
dependency beyond existing Shapely is introduced. Python >=3.11, verified on 3.14.3.

Recommended 007-B2: content-bound opening hosts and remapping review, explicit door/window
parameters and wall cuts, updated physical clearance/circulation evidence, fresh architect
review and deterministic previews. Detailed stairs, structural design, MEP, annotations,
production CAD/DWG output and regulatory certification remain outside this batch.
