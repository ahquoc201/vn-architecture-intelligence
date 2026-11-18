"""Governed preliminary room geometry; no architectural approval or CAD writer."""

from copy import deepcopy
from decimal import Decimal
import math
from typing import Any

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from vnai.contracts import canonical_digest, new_report, schema_check, issue
from vnai.design_brief import area_m2
from vnai.floorplan_search import Budget, Placement, SearchLimit, adjacent, placements, search
from vnai.space_program import build_space_program
from vnai.spatial import validate_geometry
from vnai.zoning import validate_zoning

ALGORITHM = "bounded-grid-rect-v1"
EXIT_CODES = {
    "GENERATED": 0,
    "INVALID_INPUT": 1,
    "INCOMPLETE": 3,
    "INFEASIBLE": 4,
    "UNSUPPORTED": 5,
    "SEARCH_EXHAUSTED": 6,
}
DEFAULT_PARAMETERS = {"candidate_count": 3, "max_steps": 50000, "solution_limit": 32}
UNRESOLVED = [
    "CIRCULATION_CONNECTIVITY_NOT_VERIFIED",
    "DOORS_WINDOWS_NOT_GENERATED",
    "STAIR_GEOMETRY_NOT_GENERATED",
    "STRUCTURE_MEP_NOT_EVALUATED",
    "DAYLIGHT_VENTILATION_NOT_SIMULATED",
    "ACCESSIBILITY_EGRESS_NOT_VERIFIED",
    "ARCHITECT_REVIEW_REQUIRED",
]


def authorization_digest(spec: dict) -> str:
    """Authorize physical input and grid, independent of requested count/resource budget."""
    return canonical_digest(
        {
            "specification": {
                k: v for k, v in spec.items() if k not in {"authorization", "parameters"}
            },
            "grid_step": spec.get("parameters", {}).get("grid_step"),
        }
    )


def _problem(
    report: dict, status: str, code: str, path: str, message: str, refs: list[str] | None = None
) -> None:
    bucket = "missing_information" if status == "INCOMPLETE" else "errors"
    issue(report, bucket, code, path, message, refs)
    # Prefer invalid data over incomplete data; proofs/unsupported are only added after readiness.
    if report["status"] != "INVALID_INPUT" or status == "INVALID_INPUT":
        report["status"] = status


def _prepare(spec: dict, report: dict) -> dict | None:
    geometry = spec.get("geometry")
    if not geometry:
        _problem(
            report,
            "INCOMPLETE",
            "GEOMETRY_REQUIRED",
            "geometry",
            "Supply site and usable footprint; no lot-to-footprint inference.",
        )
        return None
    spatial = validate_geometry(geometry)
    report["input_spatial_validation"] = spatial
    if spatial["errors"]:
        _problem(
            report,
            "INVALID_INPUT",
            "INVALID_GEOMETRY",
            "geometry",
            "Correct geometry errors before generation.",
        )
        return None
    zoning = geometry.get("zoning")
    if zoning is None:
        _problem(
            report,
            "INCOMPLETE",
            "ZONING_REQUIRED",
            "geometry.zoning",
            "Supply governed floor assignments.",
        )
        return None
    governed = validate_zoning(zoning)
    report["input_zoning_validation"] = governed
    if governed["errors"]:
        _problem(
            report,
            "INVALID_INPUT",
            "INVALID_ZONING",
            "geometry.zoning",
            "Correct source zoning first.",
        )
        return None
    if not governed["architect_approved"]:
        _problem(
            report,
            "INCOMPLETE",
            "ZONING_APPROVAL_REQUIRED",
            "geometry.zoning",
            "Source brief and zoning must be complete and architect-approved.",
        )
    if spec.get("fixed_elements_status") != "complete":
        _problem(
            report,
            "INCOMPLETE",
            "FIXED_ELEMENTS_UNKNOWN",
            "fixed_elements_status",
            "Explicitly declare the supplied fixed/reserved geometry complete, even when none exists.",
        )
    if "grid_step" not in spec.get("parameters", {}):
        _problem(
            report,
            "INCOMPLETE",
            "GRID_REQUIRED",
            "parameters",
            "Supply the search grid step in declared geometry units.",
        )
    auth = spec.get("authorization")
    if not auth:
        _problem(
            report,
            "INCOMPLETE",
            "GENERATION_AUTHORIZATION_REQUIRED",
            "authorization",
            "Obtain explicit authorization for preliminary generation using these physical constraints.",
        )
    elif auth["record"]["digest"] != authorization_digest(spec):
        _problem(
            report,
            "INVALID_INPUT",
            "STALE_GENERATION_AUTHORIZATION",
            "authorization",
            "Generation authorization does not match supplied physical constraints/grid.",
        )
    program = build_space_program(zoning["brief"])
    active = {
        r["room_id"]: r
        for r in zoning["assignments"]
        if r["status"] not in {"rejected", "superseded"}
    }
    rooms = []
    dimensions = {}
    requirements = {r["id"]: r for r in zoning["brief"]["requirements"]}
    for dim in spec.get("room_dimensions", []):
        if dim["room_id"] in dimensions:
            _problem(
                report,
                "INVALID_INPUT",
                "DUPLICATE_ROOM_DIMENSIONS",
                "room_dimensions",
                "Each room instance needs one dimensional constraint record.",
            )
        dimensions[dim["room_id"]] = dim
        req = requirements.get(dim["requirement_id"])
        if not req or req["type"] != "mandatory" or req["confirmation"] != "confirmed":
            _problem(
                report,
                "INVALID_INPUT",
                "DIMENSION_PROVENANCE",
                "room_dimensions",
                "Dimensional constraints need a confirmed mandatory source requirement.",
                [dim["requirement_id"]],
            )
        if any(dim[axis]["min"] > dim[axis]["max"] for axis in ("width", "depth")):
            _problem(
                report,
                "INVALID_INPUT",
                "DIMENSION_BOUNDS",
                "room_dimensions",
                "Dimension minimum exceeds maximum.",
            )
    for room in program["rooms"]:
        key = room["id"]
        if key not in dimensions:
            _problem(
                report,
                "INCOMPLETE",
                "ROOM_DIMENSIONS_REQUIRED",
                key,
                "Supply explicit width and depth bounds.",
                [room["requirement_id"]],
            )
        area = room["requested_area_m2"]
        if not area or "min" not in area or "max" not in area:
            _problem(
                report,
                "INCOMPLETE",
                "ROOM_AREA_RANGE_REQUIRED",
                key,
                "Solver requires an explicit hard area range; a soft target alone is insufficient.",
                [room["requirement_id"]],
            )
        floor = active.get(key, {}).get("floor_id")
        if floor is None:
            _problem(
                report,
                "INCOMPLETE",
                "ROOM_UNASSIGNED",
                key,
                "No floor assignment will be invented.",
                [room["requirement_id"]],
            )
        rooms.append(
            {
                **room,
                "floor_id": floor,
                "area": area,
                "dimensions": dimensions.get(key),
                "zone": active.get(key, {}).get("zone"),
            }
        )
    if set(dimensions) - {r["id"] for r in rooms}:
        _problem(
            report,
            "INVALID_INPUT",
            "UNKNOWN_ROOM_DIMENSIONS",
            "room_dimensions",
            "Dimensions reference an unknown program room instance.",
        )
    polygons = geometry["polygons"]
    footprints = [p for p in polygons if p["role"] == "footprint"]
    if not footprints:
        _problem(
            report,
            "INCOMPLETE",
            "FOOTPRINT_REQUIRED",
            "geometry.polygons",
            "An explicitly supplied building footprint is required; the site is not a substitute.",
        )
    if report["status"] != "READY":
        return None
    if any(p["role"] == "room" for p in polygons):
        _problem(
            report,
            "UNSUPPORTED",
            "EXISTING_ROOM_GEOMETRY",
            "geometry.polygons",
            "This version generates all program rooms; supplied room polygons cannot be silently discarded.",
        )
        return None
    if geometry["relationships"]:
        _problem(
            report,
            "UNSUPPORTED",
            "INPUT_GEOMETRY_RELATIONSHIPS",
            "geometry.relationships",
            "Pre-existing geometric overlap exemptions are not generation constraints.",
        )
        return None
    if len(rooms) > 12:
        _problem(
            report,
            "UNSUPPORTED",
            "ROOM_RESOURCE_LIMIT",
            "room_dimensions",
            "At most 12 total room instances supported by this initial solver.",
        )
        return None
    shapes = {p["id"]: Polygon(p["exterior"], p.get("holes", [])) for p in polygons}
    footprint = shapes[footprints[0]["id"]]
    outlines = {p["floor_id"]: shapes[p["id"]] for p in polygons if p["role"] == "floor_outline"}
    envelopes = {f["id"]: outlines.get(f["id"], footprint) for f in geometry["floors"]}
    for shape in [footprint, *envelopes.values()]:
        if shape.interiors or not shape.equals(box(*shape.bounds)):
            _problem(
                report,
                "UNSUPPORTED",
                "RECTANGLE_REQUIRED",
                "geometry.polygons",
                "Solver supports only axis-aligned rectangular footprint/floor envelopes without holes.",
            )
            return None
    scale = Decimal(1) if geometry["units"] == "m" else Decimal("0.001")
    requested_footprint = area_m2(zoning["brief"]["building"]["footprint"]["value"])
    measured_footprint = footprint.area * float(scale * scale)
    if (
        "min" in requested_footprint
        and measured_footprint < requested_footprint["min"]
        and not math.isclose(
            measured_footprint, requested_footprint["min"], rel_tol=1e-12, abs_tol=1e-12
        )
    ) or (
        "max" in requested_footprint
        and measured_footprint > requested_footprint["max"]
        and not math.isclose(
            measured_footprint, requested_footprint["max"], rel_tol=1e-12, abs_tol=1e-12
        )
    ):
        _problem(
            report,
            "INVALID_INPUT",
            "FOOTPRINT_SOURCE_BOUNDS_CONFLICT",
            "geometry.polygons",
            "Supplied footprint geometry conflicts with explicit source footprint area bounds.",
        )
        return None
    step = Decimal(str(spec["parameters"]["grid_step"]))
    reserved = {
        floor: [
            shapes[p["id"]]
            for p in polygons
            if p["role"] == "reservation" and p["floor_id"] == floor
        ]
        for floor in envelopes
    }
    for floor, envelope in envelopes.items():
        x0, y0, x1, y1 = (Decimal(str(v)) for v in envelope.bounds)
        width, depth = x1 - x0, y1 - y0
        if width / step > 256 or depth / step > 256 or (width / step) * (depth / step) > 256:
            _problem(
                report,
                "UNSUPPORTED",
                "GRID_RESOURCE_LIMIT",
                floor,
                "At most 256 grid cells per floor supported; choose a coarser search grid.",
            )
            return None
        area = envelope.difference(unary_union(reserved[floor])).area * float(scale * scale)
        lower = sum(Decimal(str(r["area"]["min"])) for r in rooms if r["floor_id"] == floor)
        if float(lower) > area and not math.isclose(
            float(lower), area, rel_tol=1e-12, abs_tol=1e-12
        ):
            _problem(
                report,
                "INFEASIBLE",
                "MINIMUM_AREA_EXCEEDS_AVAILABLE",
                floor,
                f"Sum of explicit minimum room areas {lower} m2 exceeds available envelope area {area} m2 (reservations removed).",
            )
            return None
    for room in rooms:
        envelope = envelopes[room["floor_id"]]
        x0, y0, x1, y1 = (Decimal(str(v)) for v in envelope.bounds)
        width, depth = x1 - x0, y1 - y0
        dim, area = room["dimensions"], room["area"]
        wmin, hmin = Decimal(str(dim["width"]["min"])), Decimal(str(dim["depth"]["min"]))
        wmax, hmax = Decimal(str(dim["width"]["max"])), Decimal(str(dim["depth"]["max"]))
        if (
            wmin > width
            or hmin > depth
            or wmin * hmin * scale * scale > Decimal(str(area["max"]))
            or wmax * hmax * scale * scale < Decimal(str(area["min"]))
        ):
            _problem(
                report,
                "INFEASIBLE",
                "ROOM_DIMENSIONS_IMPOSSIBLE",
                room["id"],
                "Explicit dimensional/area bounds cannot fit even before packing.",
                [room["requirement_id"]],
            )
            return None
    hard_pairs, soft_pairs = [], []
    for relation in program["relationships"]:
        if relation["relation"] != "adjacent":
            if relation["strength"] == "hard":
                _problem(
                    report,
                    "UNSUPPORTED",
                    "MANDATORY_SEPARATION_UNMODELED",
                    "relationships",
                    "Separation lacks an explicit metric in the existing contract; it is not guessed.",
                    [relation["requirement_id"]],
                )
                return None
            issue(
                report,
                "warnings",
                "SOFT_SEPARATION_UNMODELED",
                "relationships",
                "Separation preference is preserved but not scored.",
                [relation["requirement_id"]],
            )
            continue
        for left, right in relation["instance_pairs"]:
            (hard_pairs if relation["strength"] == "hard" else soft_pairs).append((left, right))
    report["unmodeled_architectural_requests"] = {
        key: deepcopy(zoning["brief"].get(key, {})) for key in ("site", "client")
    }
    report["unmodeled_building_requests"] = {
        key: deepcopy(value)
        for key, value in zoning["brief"]["building"].items()
        if key
        not in {
            "storeys",
            "floors",
            "rooms",
            "relationships",
            "excluded_room_types",
            "footprint",
            "gross_floor_area",
        }
    }
    report["unresolved_checks"] = list(UNRESOLVED)
    return {
        "rooms": rooms,
        "envelopes": envelopes,
        "reserved": reserved,
        "scale": scale,
        "step": step,
        "hard_pairs": hard_pairs,
        "soft_pairs": soft_pairs,
    }


def layout_signature(placed: dict[str, Placement], rooms: list[dict]) -> str:
    """Identical instances in one source group/zone/dimension class are interchangeable."""
    values = []
    for room in rooms:
        dim = {k: v for k, v in room["dimensions"].items() if k != "room_id"}
        group = [room["room_group_id"], room["floor_id"], room["requirement_id"], room["zone"], dim]
        values.append([canonical_digest(group), list(placed[room["id"]].shape.bounds)])
    return canonical_digest(sorted(values))


def _score(placed: dict[str, Placement], prepared: dict) -> dict:
    rooms = {r["id"]: r for r in prepared["rooms"]}
    pairs = prepared["soft_pairs"]
    adj = (
        sum(
            1
            for a, b in pairs
            if rooms[a]["floor_id"] == rooms[b]["floor_id"] and adjacent(placed[a], placed[b])
        )
        / len(pairs)
        if pairs
        else 1.0
    )
    targets = [(r["id"], r["area"]["target"]) for r in prepared["rooms"] if "target" in r["area"]]
    area = (
        sum(max(0.0, 1 - abs(placed[key].area_m2 - target) / target) for key, target in targets)
        / len(targets)
        if targets
        else 1.0
    )
    return {
        "preferred_adjacency": adj,
        "preferred_area": area,
        "total": (adj + area) / 2,
        "weights": {"preferred_adjacency": 0.5, "preferred_area": 0.5},
    }


def _candidate(
    spec: dict,
    prepared: dict,
    placed: dict[str, Placement],
    digest: str,
    parameters: dict,
    signature: str,
) -> dict | None:
    geometry = deepcopy(spec["geometry"])
    # Source approvals bind input geometry, not the newly generated layout. Never re-sign them.
    for polygon in geometry["polygons"]:
        polygon["status"] = "proposed"
        polygon.pop("approval", None)
    used_ids = (
        {p["id"] for p in geometry["polygons"]}
        | {f["id"] for f in geometry["floors"]}
        | {geometry["project_id"], geometry["frame"]["id"]}
        | {p["id"] for p in geometry["points"]}
        | {s["id"] for s in geometry["segments"]}
    )
    for index, room in enumerate(prepared["rooms"], 1):
        shape = placed[room["id"]].shape
        x0, y0, x1, y1 = shape.bounds
        key = f"GENERATED-ROOM-{index}"
        while key in used_ids:
            key += "-R"
        used_ids.add(key)
        geometry["polygons"].append(
            {
                "id": key,
                "role": "room",
                "owner_id": room["floor_id"],
                "floor_id": room["floor_id"],
                "room_id": room["id"],
                "requirement_id": room["requirement_id"],
                "frame_id": geometry["frame"]["id"],
                "units": geometry["units"],
                "exterior": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                "holes": [],
                "status": "proposed",
            }
        )
    spatial = validate_geometry(geometry)
    if spatial["status"] != "VALID":
        return None
    # Independently recheck hard constraints in measured geometry, not merely search bookkeeping.
    for room in prepared["rooms"]:
        p = placed[room["id"]]
        measured = p.shape.area * float(prepared["scale"] ** 2)
        if any(
            value < lower
            and not math.isclose(value, lower, rel_tol=1e-12, abs_tol=1e-12)
            or value > upper
            and not math.isclose(value, upper, rel_tol=1e-12, abs_tol=1e-12)
            for value, lower, upper in [
                (measured, room["area"]["min"], room["area"]["max"]),
                (p.width, room["dimensions"]["width"]["min"], room["dimensions"]["width"]["max"]),
                (p.depth, room["dimensions"]["depth"]["min"], room["dimensions"]["depth"]["max"]),
            ]
        ):
            return None
        if any(p.shape.intersection(r).area > 0 for r in prepared["reserved"][room["floor_id"]]):
            return None
    if any(not adjacent(placed[a], placed[b]) for a, b in prepared["hard_pairs"]):
        return None
    floors = sorted(prepared["envelopes"])
    result = {
        "schema_version": 1,
        "candidate_id": "FP-" + canonical_digest([digest, signature]),
        "input_digest": digest,
        "algorithm": ALGORITHM,
        "parameters": parameters,
        "floor_id": floors[0] if len(floors) == 1 else None,
        "floor_ids": floors,
        "geometry": geometry,
        "room_areas_m2": {
            r["id"]: placed[r["id"]].shape.area * float(prepared["scale"] ** 2)
            for r in prepared["rooms"]
        },
        "hard_validation": {
            "passed": True,
            "checks": [
                "SOURCE_INVENTORY_TRACEABILITY",
                "AREA_BOUNDS",
                "DIMENSION_BOUNDS",
                "ENVELOPE_CONTAINMENT",
                "NO_UNINTENDED_OVERLAP",
                "RESERVATIONS_RESPECTED",
                "MANDATORY_ADJACENCY",
                "SPATIAL_VALIDATOR_VALID",
            ],
            "spatial_report": spatial,
        },
        "soft_scores": _score(placed, prepared),
        "unresolved_checks": list(UNRESOLVED),
        "generation_status": "GENERATED",
        "approval_status": "PROPOSED",
        "cad_writes_permitted": False,
    }
    check = new_report("candidate-v1")
    if not schema_check(result, "floorplan-candidate.schema.json", check):
        raise RuntimeError("Generated candidate violates its output schema")
    return result


def generate_floorplans(
    value: Any, *, candidate_count: int | None = None, max_steps: int | None = None
) -> dict:
    report = new_report("floorplan-generation-v1")
    report.update(
        {
            "status": "READY",
            "algorithm": ALGORITHM,
            "candidates": [],
            "search": {"steps": 0, "termination": "NOT_STARTED", "optimality_proven": False},
            "approval_status": "PROPOSED",
            "unresolved_checks": list(UNRESOLVED),
        }
    )
    spec = deepcopy(value)
    if isinstance(spec, dict):
        if candidate_count is not None or max_steps is not None:
            spec.setdefault("parameters", {})
            if isinstance(spec["parameters"], dict):
                if candidate_count is not None:
                    spec["parameters"]["candidate_count"] = candidate_count
                if max_steps is not None:
                    spec["parameters"]["max_steps"] = max_steps
    if not schema_check(spec, "floorplan-input.schema.json", report):
        report["status"] = "INVALID_INPUT"
        return report
    report["status"] = "READY"
    prepared = _prepare(spec, report)
    if prepared is None:
        return report
    parameters = {**DEFAULT_PARAMETERS, **spec["parameters"]}
    digest = canonical_digest(
        {"specification": spec, "effective_parameters": parameters, "algorithm": ALGORITHM}
    )
    report["input_digest"] = digest
    report["parameters"] = parameters
    budget = Budget(parameters["max_steps"])
    domains: dict[str, list[Placement]] = {}
    found, seen = [], set()
    termination = "GRID_SPACE_EXHAUSTED"

    def accept(placed: dict[str, Placement]) -> None:
        signature = layout_signature(placed, prepared["rooms"])
        if signature in seen:
            return
        seen.add(signature)
        budget.tick()
        candidate = _candidate(spec, prepared, placed, digest, parameters, signature)
        if candidate:
            found.append(candidate)

    try:
        for room in sorted(prepared["rooms"], key=lambda r: r["id"]):
            domains[room["id"]] = placements(
                room,
                prepared["envelopes"][room["floor_id"]],
                prepared["reserved"][room["floor_id"]],
                prepared["step"],
                prepared["scale"],
                budget,
            )
        search(
            prepared["rooms"],
            domains,
            prepared["hard_pairs"],
            budget,
            accept,
            lambda: len(found) >= parameters["solution_limit"],
        )
        if len(found) >= parameters["solution_limit"]:
            termination = "SOLUTION_LIMIT"
    except SearchLimit:
        termination = "STEP_LIMIT"
    found.sort(key=lambda c: (-c["soft_scores"]["total"], c["candidate_id"]))
    report["candidates"] = found[: parameters["candidate_count"]]
    report["search"].update(
        steps=budget.steps,
        termination=termination,
        distinct_solutions_evaluated=len(found),
        equivalent_layouts_deduplicated=True,
    )
    if found:
        report["status"] = "GENERATED"
        if termination != "GRID_SPACE_EXHAUSTED":
            issue(
                report,
                "warnings",
                "PARTIAL_SEARCH",
                "search",
                "Candidates ranked only within the bounded discovered set; no global optimum claimed.",
            )
        if len(report["candidates"]) < parameters["candidate_count"]:
            issue(
                report,
                "warnings",
                "FEWER_CANDIDATES",
                "candidates",
                "Fewer distinct validated layouts found than requested; alternatives are not fabricated.",
            )
    else:
        report["status"] = "SEARCH_EXHAUSTED"
        issue(
            report,
            "warnings",
            "NO_VALID_GRID_CANDIDATE",
            "search",
            "No validated candidate found in this grid/budget; continuous infeasibility is not proven.",
        )
    return report
