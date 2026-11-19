"""Measured facts from immutable geometry and existing bounded review engines."""

from typing import Any
import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from vnai.architectural_review import architectural_review
from vnai.contracts import canonical_digest
from vnai.spatial import validate_geometry
from vnai.space_program import build_space_program

GEOMETRIC_FAILURES = {
    "INVALID_POLYGON",
    "NEAR_ZERO_AREA",
    "OUTSIDE_ENVELOPE",
    "ROOM_OVERLAP",
    "ROOM_IN_RESERVED_REGION",
}
PHYSICAL_FAILURES = {
    "OPENING_OUTSIDE_HOST",
    "HOST_BOUNDARY_MISMATCH",
    "ZERO_LENGTH_OPENING",
    "OPENING_WIDTH",
    "OVERLAPPING_OPENINGS",
    "OPENING_FIXED_COLLISION",
    "SWING_OUTSIDE_SPACE",
    "SWING_FIXED_COLLISION",
    "SLIDING_ENVELOPE",
    "SLIDING_FIXED_COLLISION",
    "CLEARANCE_MISSES_OPENING",
    "CLEARANCE_OUTSIDE_SPACES",
    "CLEARANCE_FIXED_COLLISION",
    "SWING_ENVELOPE_CONFLICT",
}
LIMITS = [
    "Supplied planar geometry only; no buildability or technical certification.",
    "No original solver dimension replay; no wall/structure/MEP evaluation.",
]


def measure(review: dict, bound: dict, requested: list[str]) -> dict[str, Any]:
    candidate = review["candidate"]
    geometry = candidate["geometry"]
    spatial = validate_geometry(geometry)
    architecture = architectural_review(review)
    sources = {"spatial": spatial, "architectural": architecture, "review": review}
    refs = [
        {"kind": k, "pointer": "/sources/" + k, "digest": canonical_digest(v)}
        for k, v in sources.items()
    ]
    metrics: dict[str, dict] = {}
    checks: dict[str, dict] = {}

    def metric(
        key: str,
        status: str,
        value: float | None,
        unit: str,
        method: str,
        numerator: int = 1,
        denominator: int = 1,
    ) -> None:
        metrics[key] = {
            **bound,
            "metric_id": key,
            "metric_version": 1,
            "status": status,
            "value": value,
            "unit": unit,
            "method": method,
            "coverage": {"numerator": numerator, "denominator": denominator},
            "evidence_refs": refs,
            "limitations": LIMITS,
        }

    def check(key: str, status: str, reason: str, n: int = 1, d: int = 1) -> None:
        checks[key] = {
            **bound,
            "check_id": key,
            "check_version": 1,
            "status": status,
            "reason": reason,
            "coverage": {"numerator": n, "denominator": d},
            "evidence_refs": refs,
        }

    codes = {e["code"] for e in spatial["errors"]}
    check(
        "spatial_geometry",
        "FAILED"
        if codes & GEOMETRIC_FAILURES
        else "VERIFIED"
        if spatial["status"] == "VALID"
        else "UNKNOWN",
        "Current spatial validation, with metadata errors distinguished from physical conflicts.",
    )
    integrity_codes = {e["code"] for e in architecture["candidate_review"]["errors"]}
    check(
        "candidate_integrity",
        "UNKNOWN" if integrity_codes else "VERIFIED",
        "Exact selection, source records, stored measurements and current candidate context.",
    )
    scale = 1 if geometry["units"] == "m" else 0.001
    shapes = {
        r["id"]: Polygon(
            [(x * scale, y * scale) for x, y in r["exterior"]],
            [[(x * scale, y * scale) for x, y in ring] for ring in r.get("holes", [])],
        )
        for r in geometry["polygons"]
    }
    safe = all(s.is_valid and math.isfinite(s.area) for s in shapes.values()) and not (
        codes - GEOMETRIC_FAILURES
    )
    rooms = {r["room_id"]: r for r in geometry["polygons"] if r["role"] == "room"}
    zoning = geometry.get("zoning")
    program = build_space_program(zoning["brief"]) if zoning else {"rooms": [], "relationships": []}
    expected = {r["id"]: r for r in program["rooms"]}
    inventory_known = bool(zoning and program.get("status") == "VALID")
    matching = set(expected) & set(rooms)
    inventory_ok = inventory_known and set(expected) == set(rooms)
    inv_status = "VERIFIED" if inventory_ok else "FAILED" if inventory_known else "UNKNOWN"
    check(
        "room_inventory",
        inv_status,
        "Exact source room-instance inventory.",
        len(matching),
        len(expected),
    )
    metric(
        "room_inventory_coverage",
        "VERIFIED" if inventory_known else "UNKNOWN",
        len(matching) / len(expected) if inventory_known and expected else None,
        "fraction",
        "Intersection of supplied and source room IDs / source room count.",
        len(matching),
        len(expected),
    )
    assignments = (
        {
            r["room_id"]: r["floor_id"]
            for r in zoning.get("assignments", [])
            if r["status"] not in {"rejected", "superseded"}
        }
        if zoning
        else {}
    )
    assigned = sum(rooms[k]["floor_id"] == assignments.get(k) for k in matching)
    assignment_fail = any(
        (k in assignments and rooms[k]["floor_id"] != assignments[k])
        or (
            expected[k].get("floor_id") is not None
            and rooms[k]["floor_id"] != expected[k]["floor_id"]
        )
        for k in matching
    )
    for constraint in zoning.get("constraints", []) if zoning else []:
        if constraint["strength"] != "hard":
            continue
        for room_id in constraint["room_ids"]:
            if room_id in rooms:
                floor = rooms[room_id]["floor_id"]
                assignment_fail |= (
                    floor != constraint["floor_id"]
                    if constraint["kind"] == "require"
                    else floor == constraint["floor_id"]
                )
    assignment_status = (
        "FAILED"
        if assignment_fail
        else "VERIFIED"
        if inventory_ok and assigned == len(expected)
        else "UNKNOWN"
    )
    check(
        "floor_assignments",
        assignment_status,
        "Original source room-to-floor assignments.",
        assigned,
        len(expected),
    )
    metric(
        "floor_assignment_coverage",
        "VERIFIED" if inventory_known else "UNKNOWN",
        assigned / len(expected) if inventory_known and expected else None,
        "fraction",
        "Correctly assigned source rooms / source room count.",
        assigned,
        len(expected),
    )
    if safe:

        def area_union(rows: list[dict]) -> float:
            return sum(
                unary_union([shapes[r["id"]] for r in rows if r.get("floor_id") == f["id"]]).area
                for f in geometry["floors"]
            )

        allocated = area_union(list(rooms.values()))
        reservations = [r for r in geometry["polygons"] if r["role"] == "reservation"]
        for key, value, method in (
            (
                "allocated_room_area_m2",
                allocated,
                "Sum of room polygon unions per floor; overlaps never double counted.",
            ),
            (
                "reserved_circulation_area_m2",
                area_union([r for r in reservations if r.get("reservation_kind") == "circulation"]),
                "Union of explicit circulation reservations per floor; explicit absence is measured zero.",
            ),
        ):
            metric(key, "VERIFIED", value, "m2", method)
        floors = spatial["floor_areas"]
        complete = len(floors) == len(geometry["floors"]) and bool(floors)
        envelope = sum(f["envelope_area_m2"] for f in floors) if complete else None
        metric(
            "floor_envelope_area_m2",
            "VERIFIED" if complete else "UNKNOWN",
            envelope,
            "m2",
            "Sum of declared bounded floor envelopes; not legally usable floor area.",
        )
        residual = (
            sum(
                shapes[f["envelope_id"]]
                .difference(
                    unary_union(
                        [
                            shapes[r["id"]]
                            for r in list(rooms.values()) + reservations
                            if r.get("floor_id") == f["floor_id"]
                        ]
                    )
                )
                .area
                for f in floors
            )
            if complete
            else None
        )
        metric(
            "geometric_residual_area_m2",
            "VERIFIED" if complete else "UNKNOWN",
            residual,
            "m2",
            "Envelope area minus union of rooms and all reservations; not usable unallocated space.",
        )
    for key in (
        "allocated_room_area_m2",
        "reserved_circulation_area_m2",
        "floor_envelope_area_m2",
        "geometric_residual_area_m2",
    ):
        if key not in metrics:
            metric(key, "UNKNOWN", None, "m2", "No valid measurable polygon context.", 0, 1)
    areas = {k: shapes[r["id"]].area for k, r in rooms.items()} if safe else {}
    bounds = [
        (k, r["requested_area_m2"])
        for k, r in expected.items()
        if r.get("requested_area_m2") and any(x in r["requested_area_m2"] for x in ("min", "max"))
    ]
    bound_fail = any(
        k in areas
        and (
            ("min" in a and areas[k] < a["min"] - 1e-12)
            or ("max" in a and areas[k] > a["max"] + 1e-12)
        )
        for k, a in bounds
    )
    check(
        "room_area_bounds",
        "FAILED"
        if bound_fail
        else "UNKNOWN"
        if not inventory_ok or not safe
        else "VERIFIED"
        if bounds
        else "NOT_APPLICABLE",
        "Only explicit source min/max area bounds are hard constraints.",
        sum(k in areas for k, _ in bounds),
        len(bounds),
    )
    targets = [
        (k, r["requested_area_m2"]["target"])
        for k, r in expected.items()
        if r.get("requested_area_m2") and "target" in r["requested_area_m2"]
    ]
    deviations = [abs(areas[k] - t) for k, t in targets if k in areas]
    target_status = (
        "NOT_APPLICABLE"
        if inventory_known and not targets
        else (
            "VERIFIED"
            if inventory_ok and len(targets) == len(expected) and len(deviations) == len(targets)
            else "UNKNOWN"
        )
    )
    metric(
        "area_target_deviation_m2",
        target_status,
        sum(deviations) / len(deviations) if target_status == "VERIFIED" else None,
        "m2",
        "Mean absolute deviation across all source room targets; partial targets are not imputed.",
        len(deviations),
        len(expected),
    )
    for strength, metric_id in (
        ("hard", "required_adjacency_satisfaction"),
        ("soft", "preferred_adjacency_satisfaction"),
    ):
        relations = [r for r in program["relationships"] if r["strength"] == strength]
        pairs = [(r, a, b) for r in relations for a, b in r["instance_pairs"]]
        unsupported_relation = any(r["relation"] != "adjacent" for r in relations)
        observed = []
        for relation, a, b in pairs:
            if relation["relation"] != "adjacent" or a not in rooms or b not in rooms or not safe:
                continue
            ra, rb = rooms[a], rooms[b]
            sa, sb = shapes[ra["id"]], shapes[rb["id"]]
            adjacent = (
                ra["floor_id"] == rb["floor_id"]
                and sa.boundary.intersection(sb.boundary).length
                > geometry["tolerances"]["boundary_m"]
            )
            observed.append(adjacent if relation["relation"] == "adjacent" else not adjacent)
        status = (
            "UNSUPPORTED"
            if unsupported_relation
            else "NOT_APPLICABLE"
            if inventory_known and not pairs
            else "VERIFIED"
            if len(observed) == len(pairs) and inventory_known
            else "UNKNOWN"
        )
        metric(
            metric_id,
            status,
            sum(observed) / len(pairs) if status == "VERIFIED" else None,
            "fraction",
            "Explicit instance-pair positive shared-boundary adjacency; architectural separation intent unsupported.",
            len(observed),
            len(pairs),
        )
        if strength == "hard":
            check(
                "required_relationships",
                "FAILED" if False in observed else status,
                "Explicit hard adjacency instance pairs; no door/path inference, separation intent unsupported.",
                len(observed),
                len(pairs),
            )
    graph = architecture["circulation_graph"]
    graph_status = graph["graph_status"]
    reachable = sum(x["graph_reachable"] for x in graph["room_access"].values())
    graph_known = graph_status in {"GRAPH_CONNECTED", "BLOCKED"} and inventory_ok
    for key in ("room_connectivity_coverage", "entrance_reachability"):
        metric(
            key,
            "VERIFIED" if graph_known else "UNKNOWN",
            reachable / len(expected) if graph_known and expected else None,
            "fraction",
            "Rooms reachable from supplied exterior entrance / source rooms; topology only.",
            reachable,
            len(expected),
        )
    metric(
        "known_inaccessible_rooms",
        "VERIFIED" if graph_known else "UNKNOWN",
        len(expected) - reachable if graph_known else None,
        "count",
        "Known non-reachable rooms only when graph inventories are complete.",
        reachable,
        len(expected),
    )
    check(
        "entrance_reachability",
        "VERIFIED"
        if graph_status == "GRAPH_CONNECTED"
        else "FAILED"
        if graph_status == "BLOCKED"
        else "UNKNOWN",
        "Graph reachability does not prove clearance.",
        reachable,
        len(expected),
    )
    physical = architecture["physical_circulation_status"]
    traversable = sum(
        v == "GEOMETRICALLY_TRAVERSABLE"
        for v in architecture["clearance"]["room_physical_access"].values()
    )
    metric(
        "circulation_clearance_coverage",
        "VERIFIED" if physical == "GEOMETRICALLY_TRAVERSABLE" and inventory_ok else "UNKNOWN",
        traversable / len(expected)
        if physical == "GEOMETRICALLY_TRAVERSABLE" and inventory_ok and expected
        else None,
        "fraction",
        "Explicit bounded planar passage/clearance proof / source rooms; missing routes are not zero.",
        traversable,
        len(expected),
    )
    check(
        "circulation_clearance",
        "VERIFIED"
        if physical == "GEOMETRICALLY_TRAVERSABLE"
        else "FAILED"
        if physical == "BLOCKED"
        else "UNKNOWN",
        "Supplied planar clearance proof only; stairs walking geometry is outside this proof.",
        traversable,
        len(expected),
    )
    opening_report = architecture["opening_validation"]
    opening_errors = {e["code"] for e in opening_report["errors"]}
    opening_status = (
        "FAILED"
        if opening_errors & PHYSICAL_FAILURES
        else "UNKNOWN"
        if opening_report["status"] != "VALID"
        else "VERIFIED"
    )
    check(
        "opening_validity",
        opening_status,
        "Current opening validation; missing/invalid references need resolution.",
    )
    metric(
        "opening_validation",
        "VERIFIED" if opening_status in {"VERIFIED", "FAILED"} else "UNKNOWN",
        1 if opening_status == "VERIFIED" else 0 if opening_status == "FAILED" else None,
        "binary",
        "Current whole supplied opening inventory validation; physical failure is observable zero.",
    )
    stairs = architecture["stair_validation"]
    stair_results = stairs["stair_results"]
    stair_na = (
        len(geometry["floors"]) == 1
        and not review.get("stairs")
        and review.get("stairs_complete") is True
    )
    stair_verified = (
        bool(stair_results)
        and stairs["status"] == "VALID"
        and review.get("stairs_complete") is True
    )
    stair_failures = {e["code"] for e in stairs["errors"]} & {
        "STAIR_OUTSIDE_ENVELOPE",
        "STAIR_FIXED_COLLISION",
        "STAIR_ALIGNMENT",
        "STAIR_DIRECTION",
        "STAIR_CONNECTION_POINT",
        "STAIR_SAME_FLOOR",
    }
    stair_status = (
        "FAILED"
        if stair_failures
        else "NOT_APPLICABLE"
        if stair_na
        else "VERIFIED"
        if stair_verified
        else "UNKNOWN"
    )
    check(
        "stair_connectivity",
        stair_status,
        "Confirmed supplied vertical graph links; no tread/riser/headroom certification.",
        sum(r["graph_eligible"] for r in stair_results),
        len(stair_results),
    )
    metric(
        "stair_connectivity",
        stair_status,
        1 if stair_verified else None,
        "fraction",
        "All supplied stair graph links verified; single floor with explicit empty inventory is N/A.",
        sum(r["graph_eligible"] for r in stair_results),
        len(stair_results),
    )
    conflicts = (
        len(codes & GEOMETRIC_FAILURES)
        + len(opening_errors & PHYSICAL_FAILURES)
        + len(stair_failures)
    )
    metric(
        "known_geometric_conflicts",
        "VERIFIED" if safe else "UNKNOWN",
        conflicts if safe else None,
        "count",
        "Count of distinct supported conflict codes, not number of incidents or absence of all hazards.",
    )
    metric(
        "unresolved_checks",
        "VERIFIED",
        len(candidate["unresolved_checks"]),
        "count",
        "Count of declared generator unresolved checks; not a completeness or quality score.",
    )
    for key in requested:
        if key not in metrics:
            metric(
                key,
                "UNSUPPORTED",
                None,
                "unknown",
                "Metric is outside the versioned supported catalog.",
                0,
                1,
            )
    return {"metrics": [metrics[k] for k in sorted(metrics)], "checks": checks, "sources": sources}
