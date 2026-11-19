"""Measured allocation/clear impacts and conservative post-wall evidence dependencies."""

import math
from typing import Callable

from shapely.geometry import LineString, box
from shapely.ops import unary_union

from vnai.contracts import canonical_digest
from vnai.design_replay import _within
from vnai.wall_topology import encode, polygon, polygons, non_area_components


def assess(
    value: dict,
    result: dict,
    envelopes: dict,
    shapes: dict,
    rooms: dict,
    walls: list[dict],
    unions: dict,
    readiness: dict,
    problem: Callable,
    wall_information_verified: bool,
) -> None:
    review = value["source"]["replay"]["review"]
    geometry = review["candidate"]["geometry"]
    scale = 1 if geometry["units"] == "m" else 0.001
    spec = value["wall_specification"]
    basis = spec.get("constraint_basis", {"area": "unresolved", "dimensions": "unresolved"})
    if "unresolved" in basis.values():
        problem(
            "missing_information",
            "CONSTRAINT_BASIS_REQUIRED",
            "constraint_basis",
            "Declare whether original area/dimension requirements apply to allocation, clear geometry or both.",
        )
    program = readiness["sources"].get("program") or {"rooms": []}
    requests = {r["id"]: r for r in program["rooms"]}
    replay = readiness["sources"]["replay"]
    allocation_state = replay["replay_status"]
    if allocation_state != "VERIFIED":
        problem(
            "conflict" if allocation_state == "FAILED" else "missing_information",
            "ALLOCATION_REPLAY_" + allocation_state,
            "source.replay",
            "Original allocation replay is " + allocation_state + "; no history is inferred.",
        )
    source_spec = value["source"]["replay"].get("baseline_revision", {}).get("specification")
    if source_spec is None:
        source_spec = (
            value["source"]["replay"].get("provenance", {}).get("generation_specification", {})
        )
    dimensions = {d["room_id"]: d for d in source_spec.get("room_dimensions", [])}
    checks = []
    for key, row in sorted(rooms.items()):
        allocation = shapes[row["id"]]
        union = unions[row["floor_id"]]
        occupied = allocation.intersection(union)
        clear = allocation.difference(union)
        components = polygons(clear)
        non_area = non_area_components(clear)
        if non_area:
            problem(
                "unsupported",
                "NON_AREA_CLEAR_COMPONENT",
                key,
                "Unexpected line/point remnants are retained and cannot be treated as usable room area.",
            )
        if clear.is_empty or clear.area <= 0:
            problem(
                "conflict",
                "CLEAR_ROOM_EMPTY",
                key,
                "Wall subtraction leaves no positive-area room geometry.",
            )
        elif len(components) != 1:
            problem(
                "conflict",
                "CLEAR_ROOM_DISCONNECTED",
                key,
                "Wall subtraction creates disconnected clear components; all components are retained.",
            )
        if not clear.is_valid:
            problem(
                "conflict",
                "INVALID_CLEAR_GEOMETRY",
                key,
                "Derived clear polygon is invalid; no repair applied.",
            )
        request = requests.get(key, {})
        area = request.get("requested_area_m2")
        status = "NOT_EVALUATED_ALLOCATION_ONLY"
        if (
            area
            and "min" in area
            and clear.area < area["min"]
            and not math.isclose(clear.area, area["min"], rel_tol=1e-12, abs_tol=1e-12)
        ):
            if basis["area"] in {"clear", "both"} and wall_information_verified:
                problem(
                    "conflict",
                    "CLEAR_AREA_BELOW_MINIMUM",
                    key,
                    "Measured clear area is below the explicitly clear-applicable original minimum.",
                )
            else:
                problem(
                    "warnings",
                    "CLEAR_BELOW_ALLOCATION_MINIMUM",
                    key,
                    "Clear area is below the original allocation minimum; this is not relabeled a clear-area rule without an explicit basis.",
                )
        if basis["area"] in {"clear", "both"} and wall_information_verified:
            if area and any(k in area for k in ("min", "max")):
                valid = _within(clear.area, area.get("min", 0), area.get("max", math.inf))
                status = "VERIFIED" if valid else "FAILED"
                checks.append(
                    {
                        "id": key + ":clear_area",
                        "status": status,
                        "observed_m2": clear.area,
                        "expected_m2": area,
                        "requirement_id": request.get("requirement_id"),
                    }
                )
                if not valid and not ("min" in area and clear.area < area["min"]):
                    problem(
                        "conflict",
                        "CLEAR_AREA_BOUND",
                        key,
                        "Clear area violates an explicit applicable bound.",
                    )
            else:
                status = "UNKNOWN"
                problem(
                    "missing_information",
                    "CLEAR_AREA_REQUIREMENT_MISSING",
                    key,
                    "No explicit hard area bounds are available to re-evaluate as clear-area constraints.",
                )
        dimension_status = "NOT_EVALUATED_ALLOCATION_ONLY"
        bounds = None
        if basis["dimensions"] in {"clear", "both"} and wall_information_verified:
            dim = dimensions.get(key)
            if dim is None:
                dimension_status = "UNKNOWN"
                problem(
                    "missing_information",
                    "DIMENSION_HISTORY_REQUIRED",
                    key,
                    "Actual original dimensional records are required; geometry is not used to fabricate them.",
                )
            elif (
                len(components) != 1
                or components[0].interiors
                or not clear.equals(box(*clear.bounds))
            ):
                dimension_status = "UNSUPPORTED"
                problem(
                    "unsupported",
                    "CLEAR_DIMENSION_METHOD_UNSUPPORTED",
                    key,
                    "A nonrectangular/disconnected clear room cannot satisfy width/depth bounds from its bounding box alone.",
                )
            else:
                x0, y0, x1, y1 = clear.bounds
                bounds = {"width_m": x1 - x0, "depth_m": y1 - y0}
                valid = True
                for axis, measured in (("width", x1 - x0), ("depth", y1 - y0)):
                    lo, hi = dim[axis]["min"] * scale, dim[axis]["max"] * scale
                    passed = _within(measured, lo, hi)
                    checks.append(
                        {
                            "id": key + ":clear_" + axis,
                            "status": "VERIFIED" if passed else "FAILED",
                            "observed_m": measured,
                            "minimum_m": lo,
                            "maximum_m": hi,
                            "requirement_id": dim["requirement_id"],
                        }
                    )
                    valid &= passed
                dimension_status = "VERIFIED" if valid else "FAILED"
                if not valid:
                    problem(
                        "conflict",
                        "CLEAR_DIMENSION_BOUND",
                        key,
                        "Wall-adjusted clear width/depth violates explicit clear-applicable original bounds.",
                    )
        if not wall_information_verified:
            status = dimension_status = "UNKNOWN_INCOMPLETE_OR_UNCONFIRMED_WALLS"
        if not math.isclose(
            allocation.area, occupied.area + clear.area, rel_tol=1e-12, abs_tol=1e-12
        ):
            problem(
                "conflict",
                "AREA_CONSERVATION",
                key,
                "Allocation area must equal occupied wall union plus clear area.",
            )
        result["rooms"].append(
            {
                "room_id": key,
                "geometry_id": row["id"],
                "floor_id": row["floor_id"],
                "allocation_geometry": encode(allocation),
                "allocation_area_m2": allocation.area,
                "wall_occupied_area_m2": occupied.area,
                "clear_area_m2": clear.area,
                "area_difference_m2": clear.area - allocation.area,
                "area_difference_percent": 100 * (clear.area - allocation.area) / allocation.area
                if allocation.area
                else None,
                "clear_geometry": encode(clear),
                "component_count": len(components),
                "non_area_components": non_area,
                "remaining_components": [
                    {"area_m2": c.area, "geometry": encode(c)} for c in components
                ],
                "source_area_requirements_m2": area,
                "area_requirement_basis": basis["area"],
                "clear_area_constraint_status": status,
                "dimension_requirement_basis": basis["dimensions"],
                "clear_dimension_constraint_status": dimension_status,
                "clear_dimensions_m": bounds,
                "measurement_scope": "PROPOSED_WALL_REVISION_ONLY_NOT_VERIFIED_USABLE_AREA",
                "wall_information_verified": wall_information_verified,
            }
        )
    for floor, envelope in sorted(envelopes.items()):
        union = unions[floor]
        floor_walls = [w for w in walls if w["floor_id"] == floor]
        outside = union.difference(envelope).area
        if outside > 0:
            problem(
                "conflict",
                "WALL_OUTSIDE_PERMITTED_ENVELOPE",
                floor,
                "Generated wall geometry extends outside the exact source permitted footprint/outline; it was not clipped.",
            )
        reservations = [
            r
            for r in geometry["polygons"]
            if r["role"] == "reservation" and r.get("floor_id") == floor
        ]
        reservations += [r for r in review.get("fixed_obstacles", []) if r.get("floor_id") == floor]
        collisions = []
        for row in reservations:
            region = shapes.get(row["id"])
            if region is None:
                region = polygon(row, scale)
            overlap = union.intersection(region).area
            if overlap > 0:
                collisions.append(
                    {
                        "geometry_id": row["id"],
                        "kind": row.get("reservation_kind"),
                        "wall_overlap_m2": overlap,
                    }
                )
                problem(
                    "conflict",
                    "WALL_RESERVED_REGION_ENCROACHMENT",
                    row["id"],
                    "Wall material encroaches into a supplied reserved/fixed region; no region is resized.",
                )
        allocated = unary_union([shapes[r["id"]] for r in rooms.values() if r["floor_id"] == floor])
        inside = union.intersection(envelope)
        # Explicit accurate accumulation is stable across Python sum() versions.
        # Preserve the established integer-zero serialization for an empty inventory.
        individual_area_sum = math.fsum(w["area_m2"] for w in floor_walls) if floor_walls else 0
        result["floors"].append(
            {
                "floor_id": floor,
                "permitted_envelope": encode(envelope),
                "envelope_area_m2": envelope.area,
                "wall_footprint": encode(union),
                "wall_union_area_m2": union.area,
                "individual_wall_area_sum_m2": individual_area_sum,
                "wall_overlap_not_double_counted_m2": individual_area_sum - union.area,
                "wall_area_within_envelope_m2": inside.area,
                "wall_area_outside_envelope_m2": outside,
                "non_wall_envelope_area_m2": envelope.difference(union).area,
                "allocated_room_union_area_m2": allocated.area,
                "reservation_impacts": collisions,
                "area_scope": "POLYGON_ACCOUNTING_NOT_GFA_OR_NET_USABLE_AREA",
            }
        )
    result["constraint_impact"] = {
        "basis": basis,
        "allocation_replay_status": allocation_state,
        "allocation_replay_digest": canonical_digest(replay),
        "clear_checks": checks,
        "re_evaluate": [
            "clear_area",
            "clear_dimensions",
            "reservations",
            "openings",
            "circulation",
            "clearance",
            "architect_review",
        ],
    }
    for opening in sorted(review.get("openings", []), key=lambda o: o["id"]):
        line = LineString(
            [(v[0] * scale, v[1] * scale) for v in (opening["start"], opening["end"])]
        )
        matching = [
            w
            for w in walls
            if w["floor_id"] == opening["floor_id"]
            and set(opening["space_ids"]) - {x["id"] for x in review.get("exteriors", [])}
            <= set(w["related_room_ids"])
            and LineString([w["reference"]["start"], w["reference"]["end"]]).covers(line)
        ]
        status = (
            "MAPPED_REQUIRES_REVIEW"
            if len(matching) == 1
            else "AMBIGUOUS"
            if matching
            else "NO_UNAMBIGUOUS_WALL_HOST"
        )
        result["opening_mappings"].append(
            {
                "opening_id": opening["id"],
                "status": status,
                "candidate_wall_ids": [w["id"] for w in matching],
                "wall_geometry_digests": [w["geometry_digest"] for w in matching],
                "opening_geometry_created": False,
                "wall_cut_performed": False,
                "clearance_evidence_status": "STALE_FOR_WALL_REVISION",
            }
        )
    result["evidence_impact"] = {
        "allocation_geometry_unchanged": True,
        "source_design_unchanged": True,
        "preserved_dependencies": [
            "source_allocation_geometry",
            "source_brief",
            "original_allocation_replay",
        ],
        "stale_for_wall_revision": [
            "boundary_hosted_openings",
            "circulation_graph",
            "opening_clearance",
            "walking_clearance",
            "candidate_evaluation",
            "architect_approval",
        ],
        "source_records_valid_only_for_original_content": True,
        "new_architect_review_required": True,
        "openings_created": False,
        "openings_cut": False,
    }
