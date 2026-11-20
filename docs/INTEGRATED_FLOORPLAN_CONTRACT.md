# Integrated wall-aware floorplans v1 — engine 0.1.13

This deterministic concept-design workflow composes the existing brief/program, floor zoning,
finite-grid allocation solver, spatial replay, wall geometry, opening drafting, stair geometry
and explicit portal/path checks. One user-facing agent invokes it. It grants no architect,
structural, technical, Feng Shui, construction or CAD authority.

## Input and original requirements

`integrated-design-input.schema.json` references existing generation, wall, opening, stair,
review and evaluation contracts. Supply original generation specification and exact brief
requirements_digest, review_template (fixed obstacles, exterior approaches and known inventories),
wall_specification, explicit per-floor wall_heights, opening_specification, opening_hosts,
clear_requirements, refinements and search. Existing source governance and generation authorization
remain prerequisites. The supplied footprint is explicit; the lot is never substituted for it.

Clear requirements cite original confirmed mandatory requirement IDs and give independent m²/m
bounds for each room. Allocation requirements remain in the original generation contract; these
are independently replayed. Clear minima do not replace or relax allocation minima. Scalar
opening/stair dimensions keep their existing units and frames; canonical PolygonSet geometry
(including optional placement_regions) is in metres. Partition positions/intervals use original
candidate coordinate units; opening offsets use opening-specification units. No datum transform,
measurement, wall height, door/window dimension, stair or architectural minimum is inferred.

Missing critical information is INCOMPLETE. Unsupported methods/operations are UNSUPPORTED.
Original mandatory separation without a defined metric remains unsupported by the original solver.
Unknown fixed geometry, inconsistent source bindings and unsupported clear dimension methods
cannot produce an integrated-verified proposal. Nonrectangular clear room bounds are not treated
as proof of width/depth. Human review and specialist compliance remain separate.

## Generation and wall-aware verification

The original generator's default API and output are unchanged. The integrated module reuses its
_prepare, placements, Budget/search, layout signature and _candidate construction, not another
packing algorithm. Each initial candidate has an actual generation provenance sidecar. The
original spatial, room inventory, floor, area, dimension, relationship, reservation, envelope and
authorization checks apply. Optional placement_regions are explicit additional functional bounds.
A necessary pre-search bound rejects allocations smaller than their clear minima; it never
assumes a wall deduction or substitutes an estimate for verification. Actual B1 wall subtraction
and rectangular clear geometry measurements decide final clear-area/dimension eligibility.

Uniform floor wall heights are expanded only from supplied wall_heights. Opening hosts resolve
only against exact caller-permitted floor/reference segments (or existing explicitly bound host
IDs); adjacency never invents a door. B2 independently constructs cuts, jambs, frames, leaves,
travel and windows, then replays actual floor obstructions. B3 constructs supplied straight/L/U
stairs and checks levels, reservations, full portals, landings, floor openings and continuous
flat-surface headroom. No staircase optimization or automatic parameter change occurs.

## Intentional wall contacts and protected space

Optional B1 reservation_wall_contacts declares exact PolygonSet contact masks INSIDE a supplied
circulation allocation. Only confirmed caller input can distinguish these intentional allocation
contacts from encroachment. Unknown/duplicate floor/reservation references, invalid masks, or
attempts to exempt stairwells, shafts or fixed obstacles are errors. All residual wall intrusion
outside the mask remains a conflict. The physical wall is never deleted, clipped or removed from
B2 path/door checks. This opt-in contract preserves historical behavior when absent. It cannot
make an obstructed walking path pass. Wall accounting retains intentional overlap separately.

All generation reservations remain exclusions for room allocations. Fixed room IDs prohibit
partition edits. Fixed wall material unions per floor must remain exactly unchanged after a
refinement; benign topology noding does not count as wall movement. Per-profile source wall intent
is immutable during search. Openings are immutable unless an explicit editable permission applies.

## Bounded supported refinements

- `partition`: two adjacent axis-aligned rectangles on the same floor, sharing the entire edge,
  with supplied room_ids, x/y axis, allowed interval and finite positions. Their combined region
  is preserved. Original allocation and clear bounds, exterior/fixed walls and protected regions
  are replayed. No unrestricted boundary movement or whole-building redesign.
- `opening_offset`: supplied opening_id, fixed=false, interval and finite offsets. Dimensions,
  type, connected spaces, mount/swing/slide state remain unchanged. Dependent route/clearance
  geometry may change ONLY through caller-supplied passage_alternatives at that exact offset.
  No automatic route generation or hidden clearance enlargement.

All other operations (including automatic hinge choice, stair relocation and subdivision search)
are unsupported in this first implementation; fixed stair parameters remain unchanged. Every
attempt records parent candidate/revision, permission, values, affected entities, evaluated
constraints, resolved/introduced findings and invalidated evidence. A new hard violation or a
changed fixed wall union rejects the proposal. Original candidates are retained. Accepted
intermediate states can still have unresolved conflicts; only independently complete candidates
enter the valid proposals list. State hashes deduplicate equivalent candidate geometry/opening
specification. Fixed=true permissions never execute.

## Search and statuses

Ordering is stable; grid Budget and actual integrated evaluation caps are deterministic.
max_steps<=1,000,000, max_evaluations<=64, max_refinement_states<=32, candidate_count<=3;
existing 12-room and 256-cell-per-floor solver bounds also apply. Finite permission registers
are bounded. Count diversity is distinct physical/door state content, not fabricated alternatives.
Overall ranking is withheld without an explicit existing 006-C evaluation policy. Only hard-eligible
integrated candidates are sent to that engine; unavailable legacy metrics may still withhold ranking.
No default architectural/aesthetic weights or automatic selection/approval are introduced.

- GENERATED: supported geometric candidate found without refinement.
- REFINED: a supported, independently replayed child resolves the applicable geometric constraints.
- CONFLICT: a particular loaded candidate has measured hard violations; its reports retain them.
- INCOMPLETE: required information or a critical verification remains unknown/stale.
- UNSUPPORTED: a required operation/method is not implemented.
- INVALID_INPUT: schema, original binding, duplicate ID or permission inconsistency.
- SEARCH_EXHAUSTED: no verified candidate in the finite grid/evaluation/resource search; not a
  continuous infeasibility proof. Known individual candidate conflicts remain in originals/attempts.
- INFEASIBLE: only existing solver numerical contradiction proofs, e.g. total supplied minimum
  allocation areas exceed available floor area or supplied dimensions cannot possibly fit.

Exit codes: 0 GENERATED/REFINED; 1 invalid; 2 I/O/parse; 3 incomplete; 4 conflict/infeasible;
5 unsupported; 6 search exhausted. Search effort and cache counts are deterministic; runtime is
observed separately and excluded from content digests and golden projections.

## Independent replay, circulation and evidence

Every state reruns original generation provenance/replay, actual wall geometry/clear subtraction,
B2 openings and local width envelopes, and B3 geometry/headroom. A stored report is recomputed
from its exact input and refinement mode; altered success flags, geometry, search or measurement
reports are rejected. Source inputs are deep-copied. IR identifiers bind candidate, review/fixed
context, walls/heights, opening specification/routes, stair data, clear requirements and placement
constraints. No prior architect/evaluation/clearance verdict is inherited.

B4 composes only freshly verified B2 door portals and supplied width-checked path edges with B3
stair edges whose actual geometry, full interfaces, width and headroom are verified. It reuses
existing graph reachability and creates no competing geometric model. Each room needs an actual
verified path endpoint reachable from an explicit exterior approach. Windows never become edges.

Legacy 006-B cannot verify actual stair walking and retains its own NOT_VERIFIED verdict. B4
retains all upstream findings verbatim and records exactly which missing-only checks are replaced
by fresh B3 stair and composed route evidence, with a replacement digest. Known errors are never
suppressed. STAIR_REVIEW_REQUIRED remains a separate pending human review, not a geometric pass
or a technical approval. Final verification_coverage requires every supported required check
verified; unknown, stale or unsupported observations cannot be treated as zero violations.
Scope is supplied planar paths plus horizontal tread/landing/prism headroom: no full swept body,
turning-radius, handrail, structural, fire escape or accessibility certification.

## Loading existing candidates

Optional seed references the existing CAD-readiness/replay input and requires exact original
generation provenance. It replays its candidate unchanged, preserving original wall/opening
vertical records and known conflicts. Old geometry is never reverse-engineered into fabricated
source dimensions. Loaded-lineage refinement is currently unsupported; fresh generation/refinement
is the implemented path. This lets historical 4x20 inputs remain conflicting/stale honestly.

## Area accounting

Reports distinguish site, supplied floor envelope, allocation and clear room unions, combined
wall material, actual floor obstructions, door thresholds, supplied circulation, stair/landing,
upper floor void and unallocated plan area. Geometric union/intersection avoids shared wall
and overlapping region double counting. Category unions may overlap; only exclusive_partition
(room clear, wall, other) is additive to the envelope. Thresholds are displayed separately and
not credited to room area. Window cuts never increase usable floor area. Gross floor area is
null / NOT_EVALUATED because no verified regulatory calculation basis is supplied.

## Benchmarks, independent expectations and preview

`examples/batch007b4/townhouse-4x20-v4.json` is the separately authored two-storey synthetic benchmark.
Its independent reference and all earlier failed specification revisions are retained beside it.
No synthetic actor/confirmation is real architect approval. All measurements and choices are
fixture inputs, not Vietnamese defaults. The solver does not read the reference drawing or
coordinates of an expected output; it searches the original dimensional/functional constraints.

Independent examples: inward 0.2m walls on4x5m allocation ->3.6x4.6=16.56m² clear and3.44m² wall;
clear minimum18m² fails. Two4m-wide rooms at a y5m partition have17.1m² clear each; permitted
shift to5.5m yields18.9/15.3m² while preserving fixed exterior walls and original allocation bounds.
The townhouse reference has24m² allocation and20.52m² clear per room, two10-riser flights,
0.165m rise,2.16m run,1.65m landing,4.518m² stair footprint and exact3.3m final elevation.

The supplied 1e-12m /1e-10m² numerical tolerances are justified for binary64 operations at20m
coordinate magnitude in FIXTURE_REVISIONS.md; no historical tolerance or assertion is changed.
Full-precision measurements remain in JSON. Preview formatting rounds display text only.

Before/after comparison and per-floor plans use actual B1/B2/B3 geometry: wall cuts, hinged arcs,
sliding leaves/tracks, windows, treads/landings, UP/DOWN, voids, room clear areas, fixed obstacles,
circulation and conflict labels. Sections reuse B3 true/developed drawing. Missing source geometry
cannot be replaced with a manual illustration. Human review remains pending.

## Practical architect walkthrough

Collect and confirm brief, footprint, source zoning, fixed inventory and explicit dimensional
requirements. Supply wall intent, room clear bounds, doors/windows, routes, stair/levels/overhead
information and permitted changes. Resolve missing data; keep Feng Shui and legal review separate.

```powershell
vnai design integrated refine examples/batch007b4/residential-4x20-six-rooms.json --out outputs/integrated-v0.1.13.json
vnai design integrated validate outputs/integrated-v0.1.13.json
vnai design integrated report outputs/integrated-v0.1.13.json --markdown outputs/integrated-v0.1.13.md
vnai design integrated preview outputs/integrated-v0.1.13.json --view comparison --out outputs/comparison-v0.1.13.svg
vnai design integrated preview outputs/integrated-v0.1.13.json --view after --floor F1 --out outputs/F1-v0.1.13.svg
vnai design integrated preview outputs/integrated-v0.1.13.json --view after --floor F2 --out outputs/F2-v0.1.13.svg
vnai design integrated preview outputs/integrated-v0.1.13.json --view section --out outputs/stair-section-v0.1.13.svg
```

Review exact changes and every unresolved finding, compare only fairly verifiable candidates,
and request actual architect review. Retain versioned outputs. File creation is exclusive;
no existing input/report is overwritten. Preparing a concept for later drafting never authorizes
CAD writes. Recommended 007-C: reviewed annotation, dimensions/layer contracts and controlled
read-only export preparation; production DWG/DXF and external CAD writes remain separate work.


## Additional six-room residential benchmark

`examples/batch007b4/residential-4x20-six-rooms.json` is the primary practical end-to-end
case; `RESIDENTIAL_REFERENCE.md` was authored before its first search. It is a separate
synthetic project with an explicitly supplied4x18m envelope on the4x20m lot, two bedrooms,
living, kitchen/dining and one bathroom per floor. No unverified setback requirement is
implied. The earlier4x16m/four-room v4 oracle and all failed predecessors remain unchanged.
The same four main-room bounds and actual stair dimensions apply; bathrooms add explicit
4m? allocation /3m? minimum clear bounds, two hosted doors and width-checked routes.
Generation still uses the original finite-grid solver (declared1m grid), not a hardcoded
reference layout. Observed main-room clear areas20.52m? and bathroom clear areas3.23m?
match the independent expectations. Building wall-clear rooms sum88.54m?. Known fixed
cabinet footprint is accounted separately as unobstructed room floor, not silently removed
from wall-clear dimensions. Exact observed runtime/results belong in versioned verification
artifacts, not these deterministic contracts. Human architectural/habitability, structural,
MEP, environmental, fire and accessibility review remain pending.
