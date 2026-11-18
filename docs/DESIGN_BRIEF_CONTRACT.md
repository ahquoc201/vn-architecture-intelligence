# Design brief and space program contract v1

Engine 0.1.4 / R2 Batch 004. These are workflow data contracts, not architectural
standards, measured surveys, construction approval or a layout generator.

## Inputs and governance

`knowledge/architecture/design-brief.schema.json` is Draft 2020-12, used directly
by Python through jsonschema. Structural errors are INVALID, including unknown keys,
unsupported schema versions, invalid types/units and numeric ranges. JSON constants
NaN/Infinity and duplicate object keys are rejected by the design CLI.

`schema_version`, `project` and `requirements` are structurally required. Site,
building and client fields can be collected progressively. Every fact is an object
with `requirement_id` and `value`; room groups, relationships and exclusions also
reference the central requirement register. IDs are case-sensitive, globally unique
across requirements, room groups, floors and relationships. Priority is descriptive;
it never overrides a hard requirement or grants authority.

Requirement types:

- `mandatory`: client/architect requirement; hard constraints must reference one
  with `confirmation=confirmed`.
- `preference`: optional client preference, never silently upgraded to a hard rule.
- `assumption`: proposed, unconfirmed information; confirmation must be `unconfirmed`.
  Reclassify explicitly when confirmed.
- `question`: unresolved decision; confirmation must be `unknown`.

Origins are descriptive provenance supplied by the caller, not source verification.
Confirmation does not assert bibliographic, expert or technical approval.

Field semantics:

- Absent field: not collected; no value or applicability inferred.
- `unknown`: explicitly unknown; fact value must be null.
- `unconfirmed`: a candidate value (or null), excluded from confirmed area totals.
- `confirmed`: fact value must be present and non-null.
- `not_applicable`: explicitly excluded; fact value must be null. This satisfies
  only gates that permit non-applicability, such as site constraints or single-storey
  circulation. It cannot substitute for dimensions, footprint, north or room requests.

No defaults are supplied for architectural facts. `project.type` and phase describe
identity; architect notes are optional. Site fields support rectangle dimensions or a
geometry reference, road access, frontage description/bearing, true north bearing,
adjacent buildings, constraints and unverified measurements. Numeric bearings mean
clockwise degrees from true north in [0,360); no compass or magnetic conversion is inferred.
Budget has amount, currency (VND/USD) and a scope; it is never used to infer room areas.
Client fields include occupants, priorities, privacy, style and optional Feng Shui requests.
Building facts include circulation, stairs, daylight, ventilation, skylight, courtyard
and accessibility. These requests are retained, not simulated or evaluated from text.

## Planning readiness and issue categories

Errors make the brief INVALID; missing_information makes it INCOMPLETE if there are
no errors. Only VALID has `ready_for_planning=true`. Warnings and recommendations do
not block that data gate. Layout generation still needs explicit architect approval.

The current conservative workflow requires:

- Confirmed rectangular dimensions (or a geometry reference that still needs resolution).
  References are preserved but never opened, so a reference alone remains INCOMPLETE.
- Confirmed road access, frontage description, true north and site constraints
  (constraints may explicitly be not_applicable).
- Confirmed storey count, matching floor designations and a footprint target/bound.
- Internal/vertical circulation decisions; stairs for multiple storeys. Multi-storey
  stairs and vertical circulation cannot be not_applicable.
- At least one room, an explicit floor per room group, and a supplied area target
  or bound per room group. Groups on different floors must be separate group IDs.
- Resolution of all unknown/unconfirmed requirements, including optional questions,
  and any explicitly declared unverified measurements.

These gates are software workflow policy, documented in `design-constraints.yaml`,
not QCVN/TCVN minima. Hard contradictions, duplicate IDs, dangling references,
storey-count mismatches, unsupported room types and impossible area bounds are errors.
Hard adjacency means same-storey adjacency; `separate` leaves distance/construction
unresolved. Opposing hard relations are errors; any soft conflict is a warning.
Hard exclusions conflict with mandatory room requests; optional conflicts warn.
The engine never infers facts or resolves conflicts by matching free text.

A data-valid brief is not evidence that constraints are geometrically satisfiable.
Room type `other` requires notes. Vocabulary YAML contains no default room sizes,
relationship prescriptions or approved specialist rules.

## Program and quantities

Room groups declare `quantity`; instance IDs are `<group-id>:<1-based-index>`.
A group's area request is **per instance**, not a group total; split groups when
instances have different areas/floors. Instance records retain the governance record
and source requirement ID. Relationships refer to group IDs and apply to every pair
of instances across both groups; this expansion is explicit in the result.

Lengths support `m` and `mm`; areas support `m2` and `mm2`. Values must be finite and
positive. Arithmetic uses Decimal conversion and returns finite JSON numbers.
No conversion or fallback is inferred from ambiguous units. `target`, `min`, `max`
are independently optional but at least one is required, with consistent bounds.
A target is not silently treated as a guaranteed minimum or maximum.

- Lot area: only calculated from confirmed, explicitly rectangular dimensions.
- Building footprint: only the independently supplied confirmed area request.
- Gross floor area: only the independently supplied confirmed area request;
  never footprint multiplied by storey count.
- Requested net room area: sums only explicitly supplied confirmed values, separately
  for target/min/max; includes coverage count, known partial sum and complete total.
  Missing areas or unconfirmed requests leave a complete total null.
- Unallocated area: always null until compatible geometry/area definitions exist.
  Subtracting net room targets from GFA does not establish usable unallocated space.

Targets are requests, not measured areas. No claim of feasibility follows from totals.
Instance expansion is capped at 10000 rooms and 100000 relationship pairs per brief
as implementation resource limits, not architectural constraints.

## CLI/API and preservation

`validate_design_brief` returns structured errors, warnings, missing_information and
recommendations; each issue includes a stable code, path and requirement IDs where
applicable. `DesignBrief.from_dict` snapshots structurally/semantically non-invalid
briefs, including incomplete ones. `build_space_program` revalidates and returns no
partial rooms or areas when INVALID. Report/program output retains supplied facts
and provenance; it must be handled as potentially private project data.

All design commands read UTF-8 and emit ASCII-escaped JSON to stdout (Unicode text
round-trips safely on legacy Windows consoles), with report schema/engine version stamps:

```bash
vnai design brief validate examples/townhouse_4x20_brief.json
vnai design brief report examples/townhouse_4x20_brief.json
vnai design program build examples/townhouse_4x20_brief.json
```

Exit codes: 0 VALID, 1 INVALID data, 2 input/read/parse error, 3 INCOMPLETE.
Parser usage errors use argparse's conventional exit 2. Brief report adds input_brief;
program adds rooms, relationships, distinct areas and the validation report.
Commands write no files; the design dispatch never calls CAD export. Preserve reports with
versioned filenames using the calling workflow; never overwrite earlier reports.
The example is synthetic, has no customer identity and intentionally returns exit 3.

## Limits and Batch 005

This checkout/editable-install workflow loads schemas/YAML from the repository,
consistent with existing knowledge tools; standalone wheel data bundling is pending.
Geometry references, polygon sites, survey verification, per-instance floor allocation,
wall/opening/stair geometry, circulation feasibility, climate, budget costing and
code/Feng Shui reviews are outside this batch. Free-text constraints are preserved
without asserting they were checked. Batch 005 should introduce architect-approved
zoning decisions and tested geometry contracts before attempting any floorplan generator.
