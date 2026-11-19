# Wall-hosted architectural opening drafting v1 (engine 0.1.11)

This engine derives actual proposed door/window geometry from the existing wall model.
It does not change its selected floorplan, original room allocations or source walls.
A successful draft is not architectural approval, full building verification or CAD
write authorization. All supplied example dimensions/identities are synthetic; expert
architectural oracles remain pending.

## Source, bindings and coordinates

`opening-drafting-input.schema.json` embeds the existing `wall-input.schema.json` as
`source`. Its B1 model is recomputed, rather than trusting stored passed flags.
Bind the exact `source_candidate_digest` and `source_wall_revision_id`. Each opening
references the actual wall ID and its `source_wall_digest`. Stale bindings fail before
any accepted cut. Source B1 constraints, conflict reports and scoped readiness remain
visible. In particular the townhouse wall input is unchanged, including its hard area,
dimension, reservation and architect review requirements.

New specification coordinates/dimensions explicitly use m or mm and the same local
frame as the source walls. Output geometry is canonical local metres/m2. Fresh 006-B
sidecar polygons/routes use their own required original candidate frame/units; they
are not silently transformed. All vertical values use the explicitly declared datum
`above_finished_floor`, independently on each floor; no absolute floor elevation is
inferred. Positive offsets follow the canonical B1 reference direction (horizontal
west-to-east, vertical south-to-north). Start/end cross-checks use the existing source
boundary tolerance; the declared canonical offset/rough width remains authoritative.
No endpoint is snapped or moved.

`opening_hosts.py` checks host/floor/digest, source room/circulation/exterior boundaries,
finite interval containment and junction interference. An exterior side must reference
an actual compatible envelope-side wall and declared exterior space. Migration uses an
explicit `legacy_opening_id` only when B1 maps it to one wall. The actual host digest
and rough dimensions must still be supplied; legacy clear width is never substituted
for rough width, and legacy clearance/approval is never inherited. Missing/ambiguous
hosts require review; they are not moved to another wall.

## Explicit dimensions and state

The input preserves IDs/marks, floor, connected source space IDs, requirement IDs,
provenance, confirmation and declared review state. Rough width/height, frame inner
width, leaf width/thickness and clear width/height are separate measures. Unknowns
remain null in the schedule. A frame is drawn only from supplied jamb width/depth
and explicit `centered_in_wall` alignment. Its calculated inner width must agree with
any independently declared inner width. No material, manufacturer, hardware, pocket,
load-bearing status or construction detail is invented.

Position is an explicit offset or supplied endpoints plus rough width. Clear passage
position needs its own `clear_start_offset`, not a guessed centred span. Doors require
an explicit bottom, leaf, motion, mounting side and operating state. Mount left/right
uses the B1 canonical normal. The pivot is at the declared host face and leaf hinge
offset. A surface slider additionally requires stand-off and travel. Door clear width
must fit rough/frame bounds and the actual frame/open leaf at the mouth plane; no
unsupported inequality substitutes leaf width for measured passage width.

Window sill, rough height and head are checked for consistency. A missing head can be
calculated from explicit sill+height, but a missing sill/height is not filled with a
typical dimension. Supported host verticals have explicit confirmed base=0 and height;
raised-base assemblies require a separate floor-obstruction model and are unsupported.
No lintel design or structural feasibility follows from these geometric checks.

## Cuts, wall accounting and vertical interpretation

Each rough cut is a real rectangle crossing the known host thickness/alignment. It
must be valid, positive and wholly inside its intended finite wall. Touching a non-END
junction node/core, or removing any positive area of another wall, is unsupported.
There is no invented numeric setback from a junction. Overlapping proposed cuts are
reported and both are withheld; no arbitrary winner or naive sum/subtraction is used.
Stacked openings with disjoint vertical intervals but overlapping plan cuts are explicitly unsupported; an unknown vertical overlap remains unresolved. All proposed geometry remains inspectable. Accepted plan/floor removals use geometric
intersection/union, preserving wall identities and all valid disconnected components.
A full-width door normally splits a straight wall into two retained components.

The specification must declare `plan_cut_height`; no default cut elevation is used.
At that height, a wall is interrupted only where bottom/sill < cut < head. Confirmed walls entirely below/above the plane are absent from that wall section, while their floor footprint remains separately accounted. Reports include the wall-at-cut area before openings and wall area excluded by elevation. A cut exactly
at sill/head is unsupported because assembly-specific treatment is needed. Above/below
windows are explicitly shown as dashed projections, with their plane interpretation;
they leave the solid wall at the selected cut height. Missing vertical data leaves a
conditional preview and an INCOMPLETE interpretation, with no accepted cut.

The output separately reports:

- Immutable full source wall footprint and its area.
- Proposed and accepted rough cut unions.
- Removed geometry at the selected plan cut and the remaining plan wall geometry.
- Conservative floor wall obstruction: full B1 wall minus explicit floor-level door cuts.
- Door thresholds, actual clear portal geometry, frames and leaves at declared state.
- Original room allocation and B1 clear floor area, with threshold contribution separate.
- Per-wall open vertical bands, active rough void IDs and actual remaining wall polygons,
  retaining wall material below window sills and above opening heads.

Frames/glazing/leaf assemblies are distinct from rough wall voids. The vertical bands
represent wall material, not complete engineered assembly solids. A window never removes
the floor wall obstruction or creates an ordinary circulation edge, even when its plan
symbol interrupts a wall. No window area is credited to clear/usable room floor area.
The explicit room-area policy is `exclude_thresholds`; door thresholds also remain a
separate account rather than silently redefining historical B1 room areas as usable area.
These measures are not GFA/net usable area under a legal/national measurement convention.

## Door and window primitives

`opening_primitives.py` constructs jamb references, frame polygons, closed/open leaf
polygons, pivot, analytic SVG swing arc, slide track/positions and movement enclosure.
Only orthogonal 90-degree single-leaf hinged swings are supported. Their exact endpoint
rotation uses axis arithmetic. Collision enclosure follows the conservative sector
semantics of 006-B: rational unit-circle tangent intersections circumscribe the quarter
circle, expanded by a square bound for finite leaf thickness. This explicitly documented
over-approximation is used for collision checks; it is not claimed to be the exact swept
area. The visible arc is the actual radius/start/end circular arc. Rational samples avoid
platform libm sine/cosine variation in serialized geometry. Existing 006-B commands,
90-degree sweep function and historical reports remain unchanged.

Surface sliders use an explicit signed travel along the host tangent. The movement
envelope contains their real open/closed leaf polygons. Insufficient travel conflicts;
pocket assemblies and unsupported angles return diagnostics. No available travel or
wall pocket is inferred. Fixed windows have supplied frame outline/jambs and a declared
zero-thickness glazing symbol, not an invented glass assembly. Explicit side-hung
operable windows use the same finite-leaf/90-degree primitive convention. Their leaf
motion is evaluated at opening height, separately from floor-level wall obstruction.

## Fresh circulation and clearance replay

`opening_replay.py` reuses existing 006-B spaces, graph, supplied-width path and stair
interface stages. Only actual confirmed floor-level door portals are graph candidates.
Graph topology, local geometric traversal, supplied-route clearance, technical compliance
and architect approval remain separate statuses. Windows are excluded from graph edges.
Clear width is checked at the fully-open leaf; a closed declared operating state defers current walking rather than changing the design width. A closed leaf does not prove current passage. Known fixed, wall, frame, door movement and
adjacent movement conflicts are visible; an unknown fixed inventory never becomes a pass.
Conservative movement is checked against its declared connected clear target plus its
own rough threshold, not against an unrelated room allocation. Existing geometric
tolerances are preserved; no aggressive repair or tolerance increase hides conflicts.

Fresh opening clearance regions and routes must be supplied explicitly. Path-width
checks use actual retained wall obstructions plus frame/current-leaf geometry and the
clear portal interval. Source allocations remain immutable; a temporary replay context
contains the measured clear planes/thresholds. Paths whose opening dependencies are
unresolved are reported as deferred/NOT_VERIFIED, rather than inheriting a stale pass
or manufacturing a route. Stair links use fresh existing-format sidecars and supplied
entry/exit interfaces; no stair treads, headroom or physical stair traversal is inferred.

Source allocation/brief/original replay/wall geometry and unchanged known fixed geometry
remain applicable to those exact dependencies. Source opening/circulation/clearance,
evaluation and architectural approval are stale for this child. New geometry/specification
and revision digests bind the exact source wall model. Review records are consistency
checked against the exact specification digest, without authenticating reviewer identity.
Derived geometry/schedule always remains PROPOSED, approval NOT_GRANTED and CAD false.

## Schedule and output contracts

`opening_schedule.py` groups only equivalent declared dimensions/type/handing/assembly.
Each row retains mark, floor, host, quantity, opening IDs, independent dimensions,
sill/head, supplied material reference, provenance, review state and unresolved fields.
Equal marks with incompatible specifications conflict. Different positions do not make
otherwise equal assemblies a different mark; no manufacturer/material is supplied by
code. `opening-drafting-result.schema.json` reuses B1 PolygonSet and common diagnostics,
with typed opening primitives, per-floor/per-wall geometry, vertical bands and schedule.

`draft_openings` recomputes B1, resolves hosts, builds primitives, accounts cuts, replays
circulation and emits a separate opening revision. `validate_drafting` accepts input or
a stored report; it recomputes geometry/schedule/evidence instead of trusting stored flags.
Input and source candidate/walls are never mutated.

## CLI and previews

```powershell
vnai design openings draft examples/batch007b2/oracle-entrance.json
vnai design openings drafting-validate examples/batch007b2/fixed-window.json
vnai design openings schedule examples/batch007b2/interior-hinged.json --markdown outputs/opening-schedule-v0.1.11.md
vnai design openings preview examples/batch007b2/townhouse-benchmark.json --out outputs/townhouse-openings-v0.1.11.svg
```

Existing `design openings validate` remains the historical boundary-host contract.
New commands print deterministic JSON. Exits: GENERATED0, INVALID_INPUT1, read/parse/output
error2, INCOMPLETE3, CONFLICT4, UNSUPPORTED5. Preview/schedule can inspect incomplete or
conflicting proposals while retaining their nonzero domain code. Files are written only
when requested and use exclusive creation; no previous artifact is overwritten.

`opening_preview.py` extends the actual B1 SVG layers with cut wall polygons, actual
leaf/frame/glazing/track geometry, analytic arcs, marks, known obstacles and conflict
annotations. Scale/aspect remain uniform across floors; metadata binds the original wall
and new opening revision. Outside-plane windows use labelled dashed projections. These
are proposed drafting previews, not construction drawings or production CAD exports.

## Numerical checks and limits

Precision-sensitive aggregations use math.fsum, with stable metre outputs, canonical
ordering and digest serialization. Existing B1 empty-inventory integer-zero behavior
and all historical goldens are preserved. A 4m x .2m synthetic wall has .8m2 plan area;
a .9m rough door removes .18m2, leaving .62m2. A separate .8m window at the chosen cut
removes .16m2 from that wall plan, while floor obstruction still remains .62m2. Vertical
bands retain .62/.46/.62/.8m2 through the explicit example levels 0/.8/1.8/2.1/3m.
These are independent mathematical fixture dimensions, not Vietnamese regulations.

Processing is bounded by existing B1 limits plus <=64 openings, <=512 vertical wall
records and <=10000 fresh-sidecar coordinate pairs. Physical magnitudes are <=1e9m.
No new runtime dependencies are added. Curves, nonorthogonal walls, junction assemblies,
pocket doors, unsupported swing angles, raised wall bases, structural engineering,
production DXF/DWG, automatic placement/redesign, full lighting/ventilation/egress and
regulatory/Feng Shui certification are excluded. Expert review remains outstanding.
Recommended next scope: explicit staircase geometry/interfaces, then governed annotation
and exporter preparation, with fresh physical evidence and architect review.
