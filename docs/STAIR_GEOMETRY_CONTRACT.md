# Stair geometry and sections v1 — engine 0.1.12

This deterministic proposed drafting tool consumes the existing B2 wall/opening input,
recomputes it, and binds its exact revision/geometry and candidate digests. It never
moves source walls, openings, rooms, reservations or slabs; no CAD writer, automatic
approval, regulatory/Feng Shui rule, structural stair/slab or reinforcement design is added.

## Input and identity

`stair-drafting-input.schema.json` references the existing opening-drafting input and
006-B stair-connection schema. `stair-drafting-result.schema.json` types generated
flights, treads, risers, landing/arrival surfaces, plan views, sections, headroom and schedule.
Source IDs remain the candidate's floor, room and stairwell IDs. B3 geometry has its
own `SR-...` proposed revision. A digest binds content, not reviewer identity.

Provide explicit source opening revision ID/geometry digest, frame, common named absolute
vertical datum, units, confirmed floor levels, stair specifications, drawing cuts,
slab/opening declarations, obstructions, headroom coverage inventory and fresh 006-B connections.
Missing floor levels, overhead/slab information, drawing policy or interfaces stay incomplete.
An explicit existing source floor elevation cannot be overridden by the new specification.

Scalar lengths, flight origins, walking lines, floor levels and drawing elevations use
specification m/mm. PolygonSet payloads reuse B1's canonical local **metres** contract
and declare `units: m`; they are not rescaled by the scalar specification unit.
006-B connection coordinates retain their existing candidate frame/units. Output is m/m2.
No coordinate or datum transformation is inferred. Confirm that all supplied overhead
bottom/top elevations use the same absolute datum as finished floor levels.

## Supported construction and counting

- Straight: one orthogonal rectangular flight, optionally an explicit rectangular upper
  arrival apron with a collinear exit. Section is a true longitudinal centreline section.
- L: two orthogonal flights, explicit rectangular intermediate landing and left/right turn.
- U: two opposite parallel flights, explicit landing, return side and measured flight gap.
- Multi-flight sections are explicitly **developed along the supplied landing walking line**;
  they are never described as true planar building sections.

For each flight under `counting: arrival_surface`, n risers produce n-1 ordinary treads.
The landing or upper floor is its final stepping surface. The first vertical riser is at
run zero; ordinary tread j is at elevation (j+1)*h and spans j*d to (j+1)*d. The last riser
is at horizontal run (n-1)*d. Landings and explicit arrival aprons are separate surfaces,
not extra ordinary treads. Flight pitch is atan(h/d), rather than total-rise / n-1-tread run.

Absent explicit riser heights, h = exact total rise / total allocated risers. Each absolute
elevation is calculated directly from rational values, not repeated floating additions.
Supplied per-flight/final riser heights are preserved. Fully explicit unequal flight heights
are allowed when their cumulative rise and supplied landings agree, with a review warning;
no unverified uniform-height rule is imposed. Missing heights retain the documented total-rise
allocation, and inconsistent mixed specifications are reported rather than redistributed. A differing explicit final riser is
reported; inconsistent flight/final levels conflict, never silently redistributed. Nonzero
closure residuals within source boundary tolerance are still disclosed.

Flight width, tread depth, riser allocations, origins/directions and landing geometry are
explicit. A landing elevation can be mathematically derived from its preceding flight;
a supplied elevation must agree. Connections cover the complete flight edges and the
explicit landing walking-line endpoints. Treads, riser reference lines, optional supplied
nosing lines/overhangs, direction vectors, elevations and IDs are actual model geometry.
Optional nosing does not imply a default finishing detail. Single-riser footprint models,
spirals, winders, curved/split-level stairs and non-collinear arrival sections are unsupported.

## Geometry, walls and floor openings

Components must fit the supplied stair envelope and unchanged same-floor source stairwell
reservations. Unexpected flight/landing overlaps conflict. Full-width shared boundary
contact is intentional; interior penetration is checked separately using polygon area and
riser-curtain interior intersection. No geometry is snapped, repaired or resized.

Absolute retained wall prisms are resolved from confirmed B2 wall verticals plus B3 floor
levels. Accepted B2 cuts are applied only through their actual bottom/head intervals;
a drawing-plane cut is not substituted for a physical void. Treads and riser curtains
are checked against known prisms. Known door movement and fixed obstacle plan collisions
are reported. Fixed 006-B geometry without heights receives a conservative planar check;
its vertical extent is not invented.

Slabs have explicit gross footprint, underside/top and same-floor opening references.
Their derived material geometry subtracts only the explicitly declared voids. This is a
read-only interpretation of supplied slab/opening data, not authorization to cut a slab.
Openings must fit the actual floor and gross slab and refer to existing stairs. Material
intersections at tread or riser elevations conflict; mere shared opening-edge contact
is distinct from penetration. Missing slab/opening information remains incomplete.
Slab support, structural suitability and load paths are not evaluated.

## Continuous headroom and local clearance

Supported walking regions are flat ordinary treads, intermediate landings and supplied
arrival surfaces. Supported overheads are explicit horizontal-bottom vertical prisms:
slab, beam, ceiling, upper stair or fixed geometry. A walking top surface does not imply
a structural stair underside; overlapping higher stairs need explicit underside evidence.

Area coverage uses the original overlap tolerance. Isolated zero-area edge/point tangencies
are not vertical-clearance measurements; portal clear height is a separate supplied check.
Full body/head sweeps at nosing/door interfaces require expert review.

For every surface/prism intersection of positive area, vertical clearance is constant:
underside minus walking elevation. Its whole intersection region is evaluated, with
minimum value and a representative witness location reported. This is continuous coverage
for this supported piecewise-constant model, not finite sampling. Riser curtains receive
separate known-material collision checks. Approach rooms, structural stair solids, guards,
sloping ceilings/soffits, accessibility and whole-building headroom are outside this scope.

All walking regions need modeled overhead or explicit open-to-sky evidence, and the
caller must declare the overhead inventory complete. Slab/opening evidence is required
for every crossed upper floor. Unknown upper-flight undersides prevent complete verification,
even when another higher ceiling is modeled. Known measurements do not fill
uncovered regions. Known failure remains FAILED even when other overhead evidence is
missing; `coverage_complete`, missing regions and inventory are reported independently.
With no finite obstruction, minimum verified clearance remains null, not a fabricated value.
Compare only with a supplied project requirement. No mandatory headroom is assumed.

An explicit clear-width requirement checks flight widths and the buffered supplied
landing walking line inside connected actual stair footprints. Full entry/exit edges
must fit actual B2 clear portals, not just their midpoints. Supplied door clear heights
are checked at landing interfaces. No minimum landing size is imported from a standard.

Geometry validity, local clearance, headroom, graph connectivity and proposed architect
review are separate. Fresh `_stair_report`/`_graph_report` stages retain 006-B behavior.
B3 can report geometric traversal only for its modeled stair scope when geometry,
known obstacles, full portal interfaces, local width and continuous headroom are verified.
Geometric traversal also requires the explicitly supplied project width and headroom
criteria. Without either criterion, measurements remain available and scoped physical
traversal stays NOT_VERIFIED; no zero or normative minimum is silently chosen.
A graph edge alone never proves that result or whole-building physical access.
Existing 006-B results remain independently scoped and unchanged.

## Drawing representations and schedule

Each floor plan needs an explicit absolute cut elevation. Above/at/below-cut classifications
never delete physical treads. SVG uses actual treads, landings, arrows/UP-DOWN labels,
configured numbering, B2 walls/doors, floor openings, elevations and conflict regions.
No automatic break-line convention or production annotation is invented. Scale is uniform
across panels. True/developed section views use actual riser/tread profiles and supplied
landing paths, levels, known slab/overhead regions and headroom witnesses.

JSON and Markdown schedules retain counts per flight, rise, supplied/derived riser height,
last riser, going/run/width, landing dimensions/elevations, opening references, known
headroom, provenance, PROPOSED review and unresolved codes. Materials are not invented.

## Numerical behavior and limits

Decimal input strings become Fractions for elevations, counts and orthogonal coordinates.
Decimal at precision 50 computes atan/pitch by convergent half-angle series and path square
roots; no platform libm trig enters serialized report vertices or pitch. Final public values
are IEEE binary64 floats. Precision-sensitive float aggregations use math.fsum. Existing
boundary/overlap tolerances and canonical ordering/digests are retained. Rendering uses
12-significant-digit coordinate text for display; report measurements are not rounded to
force golden equality. Empty identities and historical B1/B2 serialization remain unchanged.

Limits: at most 16 stairs, 256 risers per stair / 512 per request, four declared flights
(two supported), 128 slab/opening/obstacle rows each, 64 floor records and 20000 new
coordinate pairs. Input numeric magnitudes <=1e9. Canonical B1/B2 processing limits also
apply. No new runtime dependencies. Unsupported geometry returns diagnostics.

The arithmetic fixtures use a separately authored 13x20m synthetic site, 13x13m footprint
and explicit reservations; their brief dimensions and mock source decision digests agree.
The mock actor is explicitly SYNTHETIC_TEST_ARCHITECT_NOT_REAL_APPROVAL. Original generation
provenance is retained but stale for the authored source revision; ALLOCATION_REPLAY_STALE
is preserved rather than inventing new solver history or a source-constraint pass. The 4x20 townhouse source is
embedded unchanged and is independent of these oracle site dimensions.

Independent synthetic oracle A: 3300mm / 20 =165mm, 19 ordinary treads, 4750mm run,
pitch approximately 33.42 degrees, exact final 3300mm. Oracle B: 10+10 risers, nine
ordinary treads / 2250mm run per flight, landing at1650mm. Oracle C: known flat walking
surface1200mm below underside3400mm gives2200mm at that region only. Oracle D uses
non-integral rise/count and offset datums. Fixtures are software oracles, not expert reviews.

## CLI and revision states

```powershell
vnai design stairs draft examples/batch007b3/straight.json
vnai design stairs drafting-validate examples/batch007b3/u-shaped.json
vnai design stairs section examples/batch007b3/l-shaped.json
vnai design stairs schedule examples/batch007b3/u-shaped.json --markdown outputs/stair-schedule-v0.1.12.md
vnai design stairs preview examples/batch007b3/straight.json --view plan --out outputs/stair-plan-v0.1.12.svg
vnai design stairs preview examples/batch007b3/l-shaped.json --view section --out outputs/stair-section-v0.1.12.svg
```

All commands print deterministic JSON. Files are created exclusively only on request;
existing artifacts are not overwritten. Section output includes the actual typed profiles.
Stored report validation recomputes the complete source, geometry, schedule and evidence.
Existing `design stairs validate` keeps its historical 006-B meaning.

Domain exits: GENERATED0, INVALID_INPUT1, I/O/parse2, INCOMPLETE3, CONFLICT4, UNSUPPORTED5.
Synthetic valid-geometry examples intentionally remain INCOMPLETE where original B2 or
fresh source/architect/interface evidence is unresolved. Inspect geometry/local evidence
separately; absence of approval does not erase measurable generated geometry.

The townhouse input embeds **exactly** its original B2 specification. Its supplied upper
floor is3.0m, not the3300mm arithmetic oracle. Explicit example stair dimensions are not
shrunk to fit: unchanged reservations, room areas, walls, openings and original conflicts
remain visible alongside new collisions and missing overhead/slab information.

Unchanged source allocation/brief/wall/opening records remain bound to those dependencies.
Stair/circulation/evaluation/architect approval is stale for the new revision. All geometry
and schedules remain proposed; approval NOT_GRANTED, CAD false, standards/Feng Shui
NOT_EVALUATED. Real architect review and any technical source/expert gates remain pending.
Recommended next batch: governed drawing annotation/layer/dimension contracts and read-only
export preparation, after architects review these real plan/section conflicts; no automatic
production CAD export or design optimization.
