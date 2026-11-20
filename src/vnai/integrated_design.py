"""Bounded composition of existing architectural engines, without design authority."""

from copy import deepcopy
from math import fsum, isclose
from typing import Any

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from vnai.contracts import canonical_digest, new_report, schema_check, finish
from vnai.design_provenance import create_generation_provenance
from vnai.design_replay import validate_replay
from vnai.floorplan import (
    ALGORITHM,
    DEFAULT_PARAMETERS,
    _prepare,
    _candidate,
    layout_signature,
)
from vnai.floorplan_search import Budget, SearchLimit, placements, search
from vnai.opening_drafting import draft_openings
from vnai.opening_hosts import shape_set
from vnai.review_common import candidate_digest, design_digest
from vnai.stair_drafting import draft_stairs
from vnai.walls import generate_walls
from vnai.wall_topology import encode

EXIT_CODES = {
    "GENERATED": 0,
    "REFINED": 0,
    "INVALID_INPUT": 1,
    "INCOMPLETE": 3,
    "CONFLICT": 4,
    "INFEASIBLE": 4,
    "UNSUPPORTED": 5,
    "SEARCH_EXHAUSTED": 6,
}


def _review(candidate, template):
    value = deepcopy(template)
    value.update(
        schema_version=1,
        candidate=deepcopy(candidate),
        decisions=[],
        selection={
            "candidate_id": candidate["candidate_id"],
            "candidate_digest": candidate_digest(candidate),
        },
    )
    return value


def _revision(parent, child, provenance):
    return {
        "schema_version": 1,
        "parent_revision_id": "IR-" + design_digest(parent),
        "child_revision_id": "IR-" + design_digest(child),
        "parent_review": parent,
        "child_review": child,
        "parent_candidate_digest": candidate_digest(parent["candidate"]),
        "child_candidate_digest": candidate_digest(child["candidate"]),
        "parent_design_digest": design_digest(parent),
        "child_design_digest": design_digest(child),
        "change_origin": "ai_proposed",
        "change_rationale": "Explicitly permitted bounded integrated refinement.",
        "feedback": [],
        "provenance": provenance,
    }


def _readiness(review, origin, provenance):
    changed = candidate_digest(review["candidate"]) != candidate_digest(origin["candidate"])
    result = {
        "schema_version": 1,
        "replay": {
            "schema_version": 1,
            "mode": "revision" if changed else "original",
            "review": review,
            "provenance": provenance,
        },
        "policy": {
            "schema_version": 1,
            "policy_id": "integrated-measurement-v1",
            "requested_stages": ["room_geometry"],
            "required_review_state": "SELECTED",
            "require_openings": False,
            "require_graph": False,
            "require_clearance": False,
            "require_evaluation": False,
            "require_revision_review": changed,
        },
        "drafting_information": {},
    }
    if changed:
        result["revision"] = _revision(origin, review, provenance)
    return result


def _conflict(engine, status, code, entity, measured=None, required=None, refs=()):
    return {
        "id": "IC-" + canonical_digest([engine, code, entity, list(refs)]),
        "engine": engine,
        "code": code,
        "entity_ids": [entity],
        "requirement_ids": list(refs),
        "severity": status,
        "measured": measured,
        "required": required,
        "evidence_source": engine + ":" + entity,
    }


def _account(candidate, walls, openings, stairs, review):
    if not walls.get("floors"):
        return {
            "site_area_m2": None,
            "floors": [],
            "building_clear_room_union_m2": None,
            "regulatory_gross_floor_area": "NOT_EVALUATED",
            "accounting_status": "NO_VERIFIED_WALL_GEOMETRY",
        }
    geometry = candidate["geometry"]
    scale = 1 if geometry["units"] == "m" else 0.001

    def shape(p):
        return Polygon(
            [(x * scale, y * scale) for x, y in p["exterior"]],
            [[(x * scale, y * scale) for x, y in ring] for ring in p.get("holes", [])],
        )

    site = unary_union([shape(p) for p in geometry["polygons"] if p["role"] == "site"])
    footprint = unary_union([shape(p) for p in geometry["polygons"] if p["role"] == "footprint"])
    rows = []
    for floor in geometry["floors"]:
        fid = floor["id"]
        outlines = [
            shape(p)
            for p in geometry["polygons"]
            if p["role"] == "floor_outline" and p.get("floor_id") == fid
        ]
        envelope = unary_union(outlines) if outlines else footprint
        allocated = unary_union(
            [
                shape(p)
                for p in geometry["polygons"]
                if p["role"] == "room" and p.get("floor_id") == fid
            ]
        )
        wall = next(
            (shape_set(f["wall_footprint"]) for f in walls["floors"] if f["floor_id"] == fid),
            Polygon(),
        )
        opfloor = next((f for f in openings.get("floors", []) if f["floor_id"] == fid), {})
        obstruction = (
            shape_set(opfloor["floor_obstruction_with_door_assemblies"])
            if "floor_obstruction_with_door_assemblies" in opfloor
            else wall
        )
        thresholds = unary_union(
            [
                shape_set(o["rough_cut"])
                for o in openings.get("openings", [])
                if o["floor_id"] == fid
                and o.get("floor_cut_applied")
                and not o["type"].endswith("window")
                and o.get("rough_cut")
            ]
        )
        circulation = unary_union(
            [
                shape(p)
                for p in geometry["polygons"]
                if p.get("floor_id") == fid and p.get("reservation_kind") == "circulation"
            ]
        )
        stair = unary_union(
            [
                shape_set(s["footprint"])
                for s in stairs.get("stairs", [])
                if fid in (s["source_floor"], s["destination_floor"])
            ]
        )
        voids = unary_union(
            [
                shape_set(o["geometry"])
                for o in stairs.get("sources", {})
                .get("input", {})
                .get("specification", {})
                .get("floor_openings", [])
                if o["floor_id"] == fid
            ]
        )
        occupied = unary_union([allocated, wall, circulation, stair])
        clear = allocated.difference(wall)
        fixed = unary_union(
            [shape(p) for p in review.get("fixed_obstacles", []) if p.get("floor_id") == fid]
        )
        rows.append(
            {
                "floor_id": fid,
                "envelope_area_m2": envelope.area,
                "allocation_union_m2": allocated.area,
                "clear_room_union_m2": clear.area,
                "known_fixed_obstacle_m2": fixed.intersection(envelope).area,
                "unobstructed_room_floor_union_m2": clear.difference(fixed).area,
                "wall_union_m2": wall.intersection(envelope).area,
                "floor_obstruction_m2": obstruction.intersection(envelope).area,
                "door_threshold_union_m2": thresholds.intersection(envelope).area,
                "circulation_union_m2": circulation.area,
                "stair_landing_union_m2": stair.area,
                "floor_opening_union_m2": voids.area,
                "unallocated_m2": envelope.difference(occupied).area,
                "gross_floor_area_m2": None,
                "exclusive_partition": {
                    "room_clear_m2": clear.area,
                    "walls_m2": wall.intersection(envelope).area,
                    "other_m2": envelope.difference(unary_union([clear, wall])).area,
                },
                "overlap_note": "Category unions may overlap; only exclusive_partition is additive.",
            }
        )
    return {
        "site_area_m2": site.area,
        "floors": rows,
        "building_clear_room_union_m2": fsum(r["clear_room_union_m2"] for r in rows),
        "regulatory_gross_floor_area": "NOT_EVALUATED",
    }


def evaluate_state(
    value, candidate, provenance, origin, opening_spec, cache=None, readiness_override=None
):
    """Rebuild all dependent engines; never import a stored success verdict."""
    review = _review(candidate, value["review_template"])
    ready = (
        deepcopy(readiness_override)
        if readiness_override
        else _readiness(review, origin, provenance)
    )
    ws = deepcopy(value["wall_specification"])
    ws.update(
        source_candidate_digest=candidate_digest(candidate),
        source_design_digest=design_digest(review),
    )
    wall_input = {"schema_version": 1, "source": ready, "wall_specification": ws}
    walls = generate_walls(wall_input, _cache=cache)
    conflicts = []
    checks = []
    for polygon in candidate["geometry"]["polygons"]:
        if polygon["role"] == "room":
            region = next(
                (
                    r
                    for r in value.get("placement_regions", [])
                    if r["room_id"] == polygon["room_id"]
                ),
                None,
            )
            if region and not shape_set(region["geometry"]).covers(
                Polygon(
                    [
                        (
                            x * (1 if candidate["geometry"]["units"] == "m" else 0.001),
                            y * (1 if candidate["geometry"]["units"] == "m" else 0.001),
                        )
                        for x, y in polygon["exterior"]
                    ]
                )
            ):
                conflicts.append(
                    _conflict("placement", "FAILED", "ROOM_PLACEMENT_REGION", polygon["room_id"])
                )
    for room in walls["rooms"]:
        req = next(
            (r for r in value["clear_requirements"] if r["room_id"] == room["room_id"]), None
        )
        if req is None:
            conflicts.append(
                _conflict("clear", "UNKNOWN", "CLEAR_REQUIREMENT_MISSING", room["room_id"])
            )
            continue
        clear = shape_set(room["clear_geometry"])
        bounds = clear.bounds
        rectangular = (
            not clear.is_empty
            and clear.geom_type == "Polygon"
            and not clear.interiors
            and clear.equals(box(*bounds))
        )
        quantities = {
            "area_m2": room["clear_area_m2"],
            "width_m": bounds[2] - bounds[0] if rectangular else None,
            "depth_m": bounds[3] - bounds[1] if rectangular else None,
        }
        for key, observed in quantities.items():
            bound = req[key]
            passed = observed is not None and all(
                (observed >= b or isclose(observed, b, rel_tol=1e-12, abs_tol=1e-12))
                if k == "min"
                else (observed <= b or isclose(observed, b, rel_tol=1e-12, abs_tol=1e-12))
                for k, b in bound.items()
            )
            checks.append(
                {
                    "id": room["room_id"] + ":" + key,
                    "status": "VERIFIED"
                    if passed
                    else "UNSUPPORTED"
                    if observed is None
                    else "FAILED",
                    "measured": observed,
                    "required": bound,
                    "requirement_ids": [req["requirement_id"]],
                    "method": "B1_ACTUAL_CLEAR_POLYGON",
                }
            )
            if not passed:
                conflicts.append(
                    _conflict(
                        "clear",
                        "UNSUPPORTED" if observed is None else "FAILED",
                        "CLEAR_" + key.upper() + "_VIOLATION",
                        room["room_id"],
                        observed,
                        bound,
                        [req["requirement_id"]],
                    )
                )
    spec = deepcopy(opening_spec)
    # Caller supplies exact permitted references, not an inferred wall from adjacency.
    for row in spec["openings"]:
        selector = next((h for h in value["opening_hosts"] if h["opening_id"] == row["id"]), None)
        if selector:
            matches = [
                w
                for w in walls["walls"]
                if w["floor_id"] == selector["floor_id"]
                and w["reference"] in selector["references"]
            ]
            if len(matches) == 1:
                row.update(
                    host_wall_id=matches[0]["id"], source_wall_digest=matches[0]["geometry_digest"]
                )
            else:
                row.pop("host_wall_id", None)
                row.pop("source_wall_digest", None)
    spec["wall_verticals"] = (
        deepcopy(opening_spec.get("wall_verticals", [])) if readiness_override else []
    )
    for w in [] if readiness_override else walls["walls"]:
        vertical = next((r for r in value["wall_heights"] if r["floor_id"] == w["floor_id"]), None)
        if vertical:
            spec["wall_verticals"].append(
                {
                    "wall_id": w["id"],
                    **{k: vertical[k] for k in ("base", "height", "provenance", "confirmation")},
                }
            )
    opening_input = {
        "schema_version": 1,
        "source": wall_input,
        "source_candidate_digest": walls["source_candidate_digest"],
        "source_wall_revision_id": walls["wall_revision_id"] or "unresolved",
        "specification": spec,
    }
    openings = draft_openings(opening_input, _cache=cache)
    stairs = {}
    if value.get("stair_specification"):
        stairs = draft_stairs(
            {
                "schema_version": 1,
                "source": opening_input,
                "source_opening_revision_id": openings["opening_revision_id"] or "unresolved",
                "source_opening_geometry_digest": openings["opening_geometry_digest"]
                or "unresolved",
                "specification": deepcopy(value["stair_specification"]),
            },
            _cache=cache,
        )
    replay = validate_replay(ready["replay"])
    from vnai.integrated_circulation import compose_circulation

    integrated_access = compose_circulation(
        candidate, spec, openings, value.get("stair_specification", {}), stairs
    )
    superseded = []
    for engine, report in [
        ("allocation", replay),
        ("walls", walls),
        ("openings", openings),
        ("stairs", stairs),
    ]:
        for bucket, severity in [("errors", "FAILED"), ("missing_information", "UNKNOWN")]:
            for row in report.get(bucket, []):
                # Proposed architect review is deliberately a separate non-geometric gate.
                if row["code"] == "STAIR_REVIEW_REQUIRED":
                    continue
                if bucket == "missing_information" and engine == "openings":
                    stair_verified = (
                        stairs.get("circulation", {}).get("physical_status")
                        == "GEOMETRICALLY_TRAVERSABLE"
                    )
                    room = row["path"].removeprefix("paths.")
                    if (
                        row["code"] == "STAIR_WALKING_GEOMETRY_NOT_EVALUATED" and stair_verified
                    ) or (
                        row["code"] == "WALKING_ROUTE_NOT_VERIFIED"
                        and integrated_access["room_access"].get(room)
                        == "GEOMETRICALLY_TRAVERSABLE"
                    ):
                        superseded.append(
                            {
                                "engine": engine,
                                "finding": deepcopy(row),
                                "replacement": "FRESH_B3_AND_B4_PORTAL_PATH_COMPOSITION",
                                "replacement_digest": canonical_digest(integrated_access),
                            }
                        )
                        continue
                conflicts.append(
                    _conflict(
                        engine,
                        severity,
                        row["code"],
                        row["path"],
                        refs=row.get("requirement_ids", []),
                    )
                )
    if len(candidate["floor_ids"]) > 1 and not stairs:
        conflicts.append(_conflict("stairs", "UNKNOWN", "STAIR_SPECIFICATION_REQUIRED", "stairs"))
    for check in replay.get("checks", []):
        if check["status"] in {"FAILED", "STALE", "UNSUPPORTED", "MISSING", "INCOMPLETE"}:
            conflicts.append(
                _conflict(
                    "allocation",
                    "FAILED"
                    if check["status"] == "FAILED"
                    else "UNSUPPORTED"
                    if check["status"] == "UNSUPPORTED"
                    else "UNKNOWN",
                    check["id"],
                    check["id"],
                    check.get("measured"),
                    check.get("expected"),
                    check.get("requirement_ids", []),
                )
            )
    if integrated_access["status"] != "GEOMETRICALLY_TRAVERSABLE":
        conflicts.append(
            _conflict(
                "circulation",
                "UNKNOWN",
                "GRAPH_NOT_VERIFIED",
                "graph",
                integrated_access["status"],
            )
        )
    if stairs and stairs.get("headroom", {}).get("status") != "VERIFIED_MODELED_SCOPE":
        conflicts.append(
            _conflict(
                "headroom",
                "FAILED" if stairs.get("headroom", {}).get("status") == "FAILED" else "UNKNOWN",
                "HEADROOM_NOT_VERIFIED",
                "stairs",
            )
        )

    def evidence(name, passed, measured, expected, method):
        checks.append(
            {
                "id": name,
                "status": "VERIFIED" if passed else "UNKNOWN",
                "measured": measured,
                "required": expected,
                "method": method,
                "requirement_ids": [],
            }
        )

    evidence(
        "allocation",
        replay.get("replay_status") == "VERIFIED",
        replay.get("replay_status"),
        "VERIFIED",
        "007A_INDEPENDENT_ORIGINAL_REQUIREMENTS",
    )
    evidence(
        "walls",
        walls.get("geometry_status") == "VALID"
        and walls.get("specification_status") == "CONFIRMED",
        [walls.get("geometry_status"), walls.get("specification_status")],
        ["VALID", "CONFIRMED"],
        "B1_GENERATED_WALLS",
    )
    evidence(
        "opening_inventory",
        spec.get("openings_complete") is True,
        spec.get("openings_complete"),
        True,
        "EXPLICIT_CALLER_INVENTORY",
    )
    for opening in openings.get("openings", []):
        valid = (
            opening.get("cut_accepted")
            and opening.get("geometry_status") == "VALID"
            and (
                opening["type"].endswith("window")
                or opening.get("physical_state") == "GEOMETRICALLY_TRAVERSABLE"
            )
        )
        evidence(
            "opening:" + opening["id"],
            valid,
            [
                opening.get("cut_accepted"),
                opening.get("geometry_status"),
                opening.get("physical_state"),
            ],
            "ACTUAL_HOST_CUT_FRAME_AND_APPLICABLE_CLEARANCE",
            "B2_GEOMETRY_AND_MOVEMENT",
        )
    for path in openings.get("circulation", {}).get("clearance", {}).get("passage_results", []):
        evidence(
            "path:" + path["id"],
            path["status"] == "GEOMETRICALLY_TRAVERSABLE",
            path["status"],
            "GEOMETRICALLY_TRAVERSABLE",
            "B2_SUPPLIED_WIDTH_ENVELOPE",
        )
    if stairs:
        evidence(
            "stairs",
            stairs.get("geometry_status") == "VALID"
            and stairs.get("circulation", {}).get("physical_status") == "GEOMETRICALLY_TRAVERSABLE",
            [stairs.get("geometry_status"), stairs.get("circulation", {}).get("physical_status")],
            ["VALID", "GEOMETRICALLY_TRAVERSABLE"],
            "B3_FLIGHTS_LANDINGS_INTERFACES_HEADROOM",
        )
    evidence(
        "integrated_portal_chains",
        integrated_access["status"] == "GEOMETRICALLY_TRAVERSABLE",
        integrated_access["room_access"],
        "EVERY_ROOM_REACHED_THROUGH_VERIFIED_PORTALS_PATHS_STAIRS",
        "B2_B3_EDGE_COMPOSITION",
    )
    for check in checks:
        if check["status"] != "VERIFIED" and check["method"] != "B1_ACTUAL_CLEAR_POLYGON":
            conflicts.append(
                _conflict(
                    "coverage",
                    "UNKNOWN",
                    "REQUIRED_CHECK_NOT_VERIFIED",
                    check["id"],
                    check["measured"],
                    check["required"],
                )
            )
    unique = {c["id"]: c for c in conflicts}
    conflicts = [unique[k] for k in sorted(unique)]
    state_id = "IR-" + canonical_digest(
        {
            "candidate": candidate,
            "review": review,
            "opening_specification": opening_spec,
            "wall_specification": value["wall_specification"],
            "wall_heights": value["wall_heights"],
            "stairs": value.get("stair_specification"),
            "clear_requirements": value["clear_requirements"],
            "requirements_digest": value["requirements_digest"],
            "placement_regions": value.get("placement_regions", []),
            "fixed_room_ids": value.get("fixed_room_ids", []),
        }
    )
    for c in conflicts:
        c["revision_digest"] = state_id
        c["supported_operations"] = [r["id"] for r in value["refinements"] if not r["fixed"]]
    failures = [c for c in conflicts if c["severity"] == "FAILED"]
    unknown = [c for c in conflicts if c["severity"] != "FAILED"]
    return {
        "revision_id": state_id,
        "candidate_digest": candidate_digest(candidate),
        "candidate": candidate,
        "checks": checks,
        "verification_coverage": {
            "required_checks": len(checks),
            "verified": sum(c["status"] == "VERIFIED" for c in checks),
            "unresolved": sum(c["status"] != "VERIFIED" for c in checks),
            "all_required_verified": all(c["status"] == "VERIFIED" for c in checks),
            "scope": "SUPPORTED_GEOMETRY_EXCLUDING_HUMAN_APPROVAL_AND_TECHNICAL_CERTIFICATION",
        },
        "opening_specification": opening_spec,
        "verification_status": "CONFLICT"
        if failures
        else "INCOMPLETE"
        if unknown
        else "VERIFIED_SUPPORTED_GEOMETRY",
        "hard_violations": len(failures),
        "required_unknown": len(unknown),
        "conflicts": conflicts,
        "engines": {"walls": walls, "openings": openings, "stairs": stairs, "allocation": replay},
        "review": review,
        "integrated_circulation": integrated_access,
        "superseded_missing_checks": superseded,
        "upstream_findings_retained": {
            name: {k: deepcopy(r.get(k, [])) for k in ["errors", "missing_information", "warnings"]}
            for name, r in [("walls", walls), ("openings", openings), ("stairs", stairs)]
        },
        "accounting": _account(candidate, walls, openings, stairs, review),
        "approval_status": "PROPOSED",
        "architect_approval": "NOT_GRANTED",
        "cad_writes_permitted": False,
        "approval_inherited": False,
    }


def _neighbors(value, state):
    for permission in sorted(value["refinements"], key=lambda r: r["id"]):
        if permission["fixed"]:
            continue
        if permission["type"] == "opening_offset":
            for offset in sorted(set(permission["offsets"])):
                candidate, openings = (
                    deepcopy(state["candidate"]),
                    deepcopy(state["opening_specification"]),
                )
                row = next(
                    (r for r in openings["openings"] if r["id"] == permission["opening_id"]), None
                )
                if (
                    row
                    and row["offset"] != offset
                    and permission["interval"][0] <= offset <= permission["interval"][1]
                ):
                    old = row["offset"]
                    dependent_before = {
                        k: deepcopy(openings.get(k, [])) for k in ["passages", "clearance_regions"]
                    }
                    row["offset"] = offset
                    alternative = next(
                        (
                            a
                            for a in permission.get("passage_alternatives", [])
                            if a["offset"] == offset
                        ),
                        None,
                    )
                    if alternative:
                        regions = {p["id"]: p for p in alternative.get("clearance_regions", [])}
                        openings["clearance_regions"] = [
                            deepcopy(regions.get(p["id"], p))
                            for p in openings.get("clearance_regions", [])
                        ]
                        updates = {p["id"]: p for p in alternative["passages"]}
                        openings["passages"] = [
                            deepcopy(updates.get(p["id"], p)) for p in openings.get("passages", [])
                        ]
                    yield (
                        candidate,
                        openings,
                        {
                            "permission_id": permission["id"],
                            "type": "opening_offset",
                            "affected_entities": [row["id"]],
                            "original": old,
                            "proposed": offset,
                            "dependent_before": dependent_before,
                            "dependent_proposed": {
                                k: deepcopy(openings.get(k, []))
                                for k in ["passages", "clearance_regions"]
                            },
                        },
                    )
        elif permission["type"] == "partition":
            candidate = state["candidate"]
            rows = [
                p
                for p in candidate["geometry"]["polygons"]
                if p.get("room_id") in permission["room_ids"]
            ]
            if len(rows) != 2 or rows[0]["floor_id"] != rows[1]["floor_id"]:
                continue
            axis = 0 if permission["axis"] == "x" else 1
            ordered = sorted(rows, key=lambda p: Polygon(p["exterior"]).bounds[axis])
            a, b = (Polygon(p["exterior"]) for p in ordered)
            if (
                a.bounds[axis + 2] != b.bounds[axis]
                or a.bounds[1 - axis :: 2] != b.bounds[1 - axis :: 2]
            ):
                continue
            for position in sorted(set(permission["positions"])):
                if (
                    not permission["interval"][0] <= position <= permission["interval"][1]
                    or position == a.bounds[axis + 2]
                ):
                    continue
                changed = deepcopy(candidate)
                for row in changed["geometry"]["polygons"]:
                    if row["id"] == ordered[0]["id"]:
                        coords = list(a.bounds)
                        coords[axis + 2] = position
                        if coords[axis] >= position:
                            break
                        row["exterior"] = [list(p) for p in box(*coords).exterior.coords[:-1]]
                    if row["id"] == ordered[1]["id"]:
                        coords = list(b.bounds)
                        coords[axis] = position
                        if position >= coords[axis + 2]:
                            break
                        row["exterior"] = [list(p) for p in box(*coords).exterior.coords[:-1]]
                else:
                    changed["room_areas_m2"] = {
                        p["room_id"]: Polygon(p["exterior"]).area
                        * (1 if candidate["geometry"]["units"] == "m" else 0.000001)
                        for p in changed["geometry"]["polygons"]
                        if p["role"] == "room"
                    }
                    changed["candidate_id"] = "FP-IR-" + canonical_digest(changed["geometry"])
                    yield (
                        changed,
                        deepcopy(state["opening_specification"]),
                        {
                            "permission_id": permission["id"],
                            "type": "partition",
                            "affected_entities": permission["room_ids"],
                            "original": a.bounds[axis + 2],
                            "proposed": position,
                        },
                    )


def integrated_design(value: Any, *, refine=True) -> dict:
    result = new_report("integrated-design-v1")
    result.update(
        integrated_status="INVALID_INPUT",
        refinement_enabled=refine,
        candidates=[],
        originals=[],
        evaluated_revisions=[],
        attempts=[],
        search={
            "termination": "NOT_STARTED",
            "evaluations": 0,
            "steps": 0,
            "duplicate_states_skipped": 0,
        },
        ranking_status="WITHHELD_NO_EVALUATION_POLICY",
        approval_inherited=False,
        architect_approval="NOT_GRANTED",
        sources={"input": deepcopy(value)},
    )
    if not schema_check(value, "integrated-design-input.schema.json", result):
        return finish(result)
    required = [
        "generation",
        "requirements_digest",
        "review_template",
        "wall_specification",
        "wall_heights",
        "opening_specification",
        "opening_hosts",
        "clear_requirements",
        "refinements",
        "search",
    ]
    missing = [k for k in required if k not in value]
    if missing:
        result["integrated_status"] = "INCOMPLETE"
        result["missing_information"].append(
            {
                "code": "INTEGRATED_INPUT_REQUIRED",
                "path": ",".join(missing),
                "message": "Supply explicit original requirements and modeling/refinement information.",
                "requirement_ids": [],
            }
        )
        return finish(result)
    value = deepcopy(value)
    from vnai.engine_cache import EngineCache

    cache = EngineCache()
    generation = value["generation"]
    brief = generation.get("geometry", {}).get("zoning", {}).get("brief")
    if value["requirements_digest"] != canonical_digest(brief):
        result["errors"].append(
            {
                "code": "STALE_REQUIREMENTS",
                "path": "requirements_digest",
                "message": "Original brief digest differs.",
                "requirement_ids": [],
            }
        )
        return finish(result)
    requirements = {r["id"]: r for r in brief["requirements"]}
    if any(
        r["requirement_id"] not in requirements
        or requirements[r["requirement_id"]]["type"] != "mandatory"
        or requirements[r["requirement_id"]]["confirmation"] != "confirmed"
        for r in value["clear_requirements"]
    ):
        result["errors"].append(
            {
                "code": "CLEAR_REQUIREMENT_PROVENANCE",
                "path": "clear_requirements",
                "message": "Clear bounds require original confirmed mandatory requirement IDs.",
                "requirement_ids": [],
            }
        )
        return finish(result)
    if value.get("seed"):
        ready = value["seed"]
        provenance = ready["replay"].get("provenance")
        if not provenance or canonical_digest(
            provenance["generation_specification"]
        ) != canonical_digest(generation):
            result["integrated_status"] = "INCOMPLETE"
            result["missing_information"].append(
                {
                    "code": "SEED_ORIGINAL_PROVENANCE_REQUIRED",
                    "path": "seed",
                    "message": "Load exact original generation context; no dimension/history reconstruction.",
                    "requirement_ids": [],
                }
            )
            return finish(result)
        candidate = deepcopy(ready["replay"]["review"]["candidate"])
        state = evaluate_state(
            value,
            candidate,
            provenance,
            ready["replay"]["review"],
            value["opening_specification"],
            cache,
            readiness_override=ready,
        )
        result["originals"] = [state]
        result["search"].update(
            termination="EXISTING_CANDIDATE_REPLAY", evaluations=1, steps=0, refinement_attempts=0
        )
        if state["verification_status"] == "VERIFIED_SUPPORTED_GEOMETRY":
            result["candidates"] = [state]
            result["integrated_status"] = "GENERATED"
        else:
            result["integrated_status"] = state["verification_status"]
        if refine and any(not p["fixed"] for p in value["refinements"]):
            result["missing_information"].append(
                {
                    "code": "LOADED_LINEAGE_REFINEMENT_UNSUPPORTED",
                    "path": "seed",
                    "message": "Loaded candidates are replayed unchanged; bounded refinement currently starts from freshly generated origins.",
                    "requirement_ids": [],
                }
            )
            if result["integrated_status"] != "CONFLICT":
                result["integrated_status"] = "UNSUPPORTED"
        return finish(result)
    prepared_report = new_report("floorplan-generation-v1")
    prepared_report["status"] = "READY"
    prepared = _prepare(generation, prepared_report)
    result["sources"]["generation_validation"] = prepared_report
    result["sources"]["generation_execution"] = {
        "allocation_kernel": ALGORITHM,
        "orchestrator": "wall-aware-bounded-search-v1",
        "original_parameters": deepcopy(generation.get("parameters", {})),
        "integrated_limits": deepcopy(value["search"]),
        "acceptance": "INDEPENDENT_INTEGRATED_REPLAY_NOT_ALLOCATION_SUCCESS_ALONE",
    }
    if prepared is None:
        result["integrated_status"] = prepared_report["status"]
        return finish(result)
    room_ids = {r["id"] for r in prepared["rooms"]}

    def stop(status, code, path, message):
        result["integrated_status"] = status
        result[
            "missing_information" if status in {"INCOMPLETE", "UNSUPPORTED"} else "errors"
        ].append({"code": code, "path": path, "message": message, "requirement_ids": []})
        return finish(result)

    opening_model = value["opening_specification"]
    stair_model = value.get("stair_specification")
    if (
        opening_model.get("openings_complete") is not True
        or opening_model.get("fixed_obstacles_complete") is not True
        or value["review_template"].get("fixed_obstacles_complete") is not True
        or (
            stair_model
            and (
                stair_model.get("stairs_complete") is not True
                or stair_model.get("overhead_inventory_complete") is not True
            )
        )
    ):
        return stop(
            "INCOMPLETE",
            "INTEGRATED_INVENTORY_REQUIRED",
            "model_inventories",
            "Confirm opening, fixed-obstacle and applicable stair/overhead inventories before search; missing evidence is not search exhaustion.",
        )
    if "plan_cut_height" not in opening_model:
        return stop(
            "INCOMPLETE",
            "INTEGRATED_PLAN_CUT_REQUIRED",
            "opening_specification.plan_cut_height",
            "Supply an explicit drawing cut datum before integrated generation.",
        )
    opening_ids = {r["id"] for r in value["opening_specification"]["openings"]}
    if (
        not set(value.get("fixed_room_ids", [])) <= room_ids
        or not {r["room_id"] for r in value.get("placement_regions", [])} <= room_ids
    ):
        return stop(
            "INVALID_INPUT",
            "INTEGRATED_ROOM_REFERENCE",
            "fixed_room_ids/placement_regions",
            "Use existing original room IDs; unknown fixed geometry is not silently ignored.",
        )
    if not {h["opening_id"] for h in value["opening_hosts"]} <= opening_ids or any(
        (p["type"] == "opening_offset" and p["opening_id"] not in opening_ids)
        or (p["type"] == "partition" and not set(p["room_ids"]) <= room_ids)
        for p in value["refinements"]
    ):
        return stop(
            "INVALID_INPUT",
            "REFINEMENT_ENTITY_REFERENCE",
            "refinements/opening_hosts",
            "Permissions and hosts must reference actual input entities.",
        )
    if any(
        p["type"] not in {"partition", "opening_offset"} and not p["fixed"]
        for p in value["refinements"]
    ):
        return stop(
            "UNSUPPORTED",
            "REFINEMENT_OPERATION_UNSUPPORTED",
            "refinements",
            "Only declared partition positions and opening offsets/routes are implemented.",
        )
    if any(
        any(
            x < p["interval"][0] or x > p["interval"][1]
            for x in p.get("offsets", p.get("positions", []))
        )
        for p in value["refinements"]
        if p["type"] in {"partition", "opening_offset"}
    ):
        return stop(
            "INVALID_INPUT",
            "REFINEMENT_OUTSIDE_PERMISSION",
            "refinements",
            "Every declared alternative must remain inside its explicit permission interval.",
        )
    if len(prepared["envelopes"]) > 1 and not value.get("stair_specification"):
        return stop(
            "INCOMPLETE",
            "STAIR_SPECIFICATION_REQUIRED",
            "stair_specification",
            "Multiple floors require explicit actual stair geometry and interfaces.",
        )
    if any(
        s["type"] not in {"straight", "L", "U"}
        for s in value.get("stair_specification", {}).get("stairs", [])
    ):
        return stop(
            "UNSUPPORTED",
            "STAIR_TYPE_UNSUPPORTED",
            "stair_specification",
            "Only the existing straight/L/U construction is supported.",
        )
    if set(prepared["envelopes"]) != {h["floor_id"] for h in value["wall_heights"]}:
        return stop(
            "INCOMPLETE",
            "WALL_HEIGHTS_REQUIRED",
            "wall_heights",
            "Every supplied floor needs explicit vertical wall information.",
        )
    for key, idfield in [
        ("clear_requirements", "room_id"),
        ("opening_hosts", "opening_id"),
        ("wall_heights", "floor_id"),
        ("refinements", "id"),
        ("placement_regions", "room_id"),
    ]:
        ids = [r[idfield] for r in value.get(key, [])]
        if len(ids) != len(set(ids)):
            return stop(
                "INVALID_INPUT",
                "DUPLICATE_INTEGRATED_ID",
                key,
                "IDs must be unique within each register.",
            )
    if any(
        b["min"] > b["max"]
        for r in value["clear_requirements"]
        for b in [r["area_m2"], r["width_m"], r["depth_m"]]
    ):
        return stop(
            "INVALID_INPUT",
            "CLEAR_BOUNDS_ORDER",
            "clear_requirements",
            "Minimum cannot exceed maximum.",
        )
    if any(p["interval"][0] > p["interval"][1] for p in value["refinements"]):
        return stop(
            "INVALID_INPUT",
            "REFINEMENT_INTERVAL_ORDER",
            "refinements",
            "Explicit operation interval is inverted.",
        )
    if {r["room_id"] for r in value["clear_requirements"]} != room_ids:
        return stop(
            "INCOMPLETE",
            "CLEAR_INVENTORY_REQUIRED",
            "clear_requirements",
            "Each room needs its own explicit clear requirements.",
        )
    if any(
        set(p.get("room_ids", [])) & set(value.get("fixed_room_ids", []))
        for p in value["refinements"]
        if not p["fixed"]
    ):
        result["errors"].append(
            {
                "code": "FIXED_EDIT_PERMISSION",
                "path": "refinements",
                "message": "A fixed room cannot be editable.",
                "requirement_ids": [],
            }
        )
        return finish(result)
    parameters = {**DEFAULT_PARAMETERS, **generation["parameters"]}
    digest = canonical_digest(
        {"specification": generation, "effective_parameters": parameters, "algorithm": ALGORITHM}
    )
    budget = Budget(value["search"]["max_steps"])
    domains = {}
    seen = set()
    found = []
    cap = value["search"]["max_evaluations"]

    def accept(placed):
        if result["search"]["evaluations"] >= cap:
            raise SearchLimit
        budget.tick()
        candidate = _candidate(
            generation,
            prepared,
            placed,
            digest,
            parameters,
            layout_signature(placed, prepared["rooms"]),
        )
        if candidate is None:
            return
        provenance = create_generation_provenance(generation, candidate)
        origin = _review(candidate, value["review_template"])
        queue = [(candidate, deepcopy(value["opening_specification"]), None, None)]
        parent_states = {}
        while queue and result["search"]["evaluations"] < cap:
            c, o, parent, operation = queue.pop(0)
            key = canonical_digest([c["geometry"], o])
            if key in seen:
                result["search"]["duplicate_states_skipped"] += 1
                continue
            seen.add(key)
            state = evaluate_state(value, c, provenance, origin, o, cache)
            result["search"]["evaluations"] += 1
            result["evaluated_revisions"].append(
                {
                    "revision_id": state["revision_id"],
                    "parent_revision_id": parent,
                    "candidate": c,
                    "verification_status": state["verification_status"],
                    "conflicts": state["conflicts"],
                    "room_measurements": state["engines"]["walls"]["rooms"],
                    "accounting": state["accounting"],
                    "engine_digests": {
                        name: canonical_digest(report) for name, report in state["engines"].items()
                    },
                }
            )
            accepted = True
            if parent:
                prior = parent_states[parent]
                old_fail = {x["id"] for x in prior["conflicts"] if x["severity"] == "FAILED"}
                new_fail = {x["id"] for x in state["conflicts"] if x["severity"] == "FAILED"}
                fixed_before = [w for w in prior["engines"]["walls"]["walls"] if w["fixed"]]
                fixed_after = [w for w in state["engines"]["walls"]["walls"] if w["fixed"]]

                def physical(rows):
                    return [
                        (
                            f,
                            encode(
                                unary_union(
                                    [shape_set(w["geometry"]) for w in rows if w["floor_id"] == f]
                                )
                            ),
                        )
                        for f in sorted({w["floor_id"] for w in rows})
                    ]

                accepted = not (new_fail - old_fail) and physical(fixed_before) == physical(
                    fixed_after
                )
                result["attempts"].append(
                    {
                        **operation,
                        "parent_revision_id": parent,
                        "parent_candidate_digest": prior["candidate_digest"],
                        "proposed_revision_id": state["revision_id"],
                        "accepted": accepted,
                        "reason": "Resolve measured conflicts within explicit permission.",
                        "conflicts_resolved": sorted(old_fail - new_fail),
                        "conflicts_introduced": sorted(new_fail - old_fail),
                        "conflicts_after": state["conflicts"],
                        "constraints_evaluated": [
                            "original_allocation",
                            "clear_geometry",
                            "fixed_geometry",
                            "walls",
                            "openings",
                            "stairs",
                            "circulation",
                        ],
                        "evidence_invalidated": [
                            "parent_circulation",
                            "parent_evaluation",
                            "parent_approval",
                        ],
                    }
                )
            else:
                result["originals"].append(state)
            if not accepted:
                continue
            parent_states[state["revision_id"]] = state
            state["parent_revision_id"] = parent
            if state["verification_status"] == "VERIFIED_SUPPORTED_GEOMETRY":
                found.append(state)
                if len(found) >= value["search"]["candidate_count"]:
                    return
            if refine and len(parent_states) <= value["search"]["max_refinement_states"]:
                for nc, no, op in _neighbors(value, state):
                    queue.append((nc, no, state["revision_id"], op))

    termination = "GRID_SPACE_EXHAUSTED"
    try:
        for room in prepared["rooms"]:
            rows = placements(
                room,
                prepared["envelopes"][room["floor_id"]],
                prepared["reserved"][room["floor_id"]],
                prepared["step"],
                prepared["scale"],
                budget,
            )
            clear = next(r for r in value["clear_requirements"] if r["room_id"] == room["id"])
            region = next(
                (r for r in value.get("placement_regions", []) if r["room_id"] == room["id"]), None
            )
            if region:
                from shapely.affinity import scale as scale_shape

                rows = [
                    p
                    for p in rows
                    if shape_set(region["geometry"]).covers(
                        scale_shape(
                            p.shape,
                            xfact=float(prepared["scale"]),
                            yfact=float(prepared["scale"]),
                            origin=(0, 0),
                        )
                    )
                ]
            domains[room["id"]] = [
                p
                for p in rows
                if p.area_m2 >= clear["area_m2"].get("min", 0)
                and p.width * float(prepared["scale"]) >= clear["width_m"].get("min", 0)
                and p.depth * float(prepared["scale"]) >= clear["depth_m"].get("min", 0)
            ]
        search(
            prepared["rooms"],
            domains,
            prepared["hard_pairs"],
            budget,
            accept,
            lambda: (
                len(found) >= value["search"]["candidate_count"]
                or result["search"]["evaluations"] >= cap
            ),
        )
        if found:
            termination = (
                "REQUESTED_COUNT_REACHED"
                if len(found) >= value["search"]["candidate_count"]
                else "GRID_SPACE_EXHAUSTED"
            )
        elif result["search"]["evaluations"] >= cap:
            termination = "EVALUATION_LIMIT"
    except SearchLimit:
        termination = "BUDGET_LIMIT"
    result["search"]["cache"] = {
        "hits": cache.hits,
        "misses": cache.misses,
        "scope": "ONE_SEARCH_INVOCATION_FULL_INPUT_DIGEST",
    }
    result["candidates"] = found[: value["search"]["candidate_count"]]
    result["search"]["requested_candidate_count"] = value["search"]["candidate_count"]
    if 0 < len(found) < value["search"]["candidate_count"]:
        result["warnings"].append(
            {
                "code": "FEWER_VERIFIED_CANDIDATES",
                "path": "search",
                "message": "Only genuinely verified distinct proposals are returned; requested count not manufactured.",
                "requirement_ids": [],
            }
        )
    result["search"].update(
        termination=termination,
        steps=budget.steps,
        distinct_states=len(seen),
        valid_proposed_candidates=len(result["candidates"]),
        refinement_attempts=len(result["attempts"]),
        optimality_proven=False,
    )
    result["integrated_status"] = (
        ("REFINED" if any(s.get("parent_revision_id") for s in found) else "GENERATED")
        if found
        else "SEARCH_EXHAUSTED"
    )
    if value.get("evaluation_policy") and found:
        from vnai.candidate_ranking import rank_candidates

        result["evaluation"] = rank_candidates(
            {
                "schema_version": 1,
                "config": value["evaluation_policy"],
                "candidates": [{"id": s["revision_id"], "review": s["review"]} for s in found],
            }
        )
        result["ranking_status"] = result["evaluation"]["ranking_status"]
        if result["evaluation"]["errors"]:
            result["integrated_status"] = "INVALID_INPUT"
            result["errors"].append(
                {
                    "code": "EVALUATION_POLICY_INVALID",
                    "path": "evaluation_policy",
                    "message": "Existing evaluation engine rejected the supplied policy; see evaluation.errors.",
                    "requirement_ids": [],
                }
            )
    return finish(result)


def validate_integrated(value: Any) -> dict:
    if isinstance(value, dict) and value.get("contract") == "integrated-design-v1":
        report = integrated_design(
            value.get("sources", {}).get("input"), refine=value.get("refinement_enabled", True)
        )
        if canonical_digest(report) != canonical_digest(value):
            report["integrated_status"] = "INVALID_INPUT"
            report["errors"].append(
                {
                    "code": "INTEGRATED_STORED_REPORT_MISMATCH",
                    "path": "report",
                    "message": "Recomputed source, search, geometry or evidence differs.",
                    "requirement_ids": [],
                }
            )
        return finish(report)
    return integrated_design(value)
