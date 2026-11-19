"""Independent bounded constraint replay; never calls generation/search."""

from typing import Any
import math

from shapely.geometry import Polygon, box
from shapely.errors import GEOSException

from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.design_provenance import bounded_geometry, create_generation_provenance, geometry_context
from vnai.floorplan import ALGORITHM, authorization_digest
from vnai.review_common import candidate_digest, design_digest
from vnai.space_program import build_space_program
from vnai.spatial import validate_geometry
from vnai.zoning import validate_zoning

METHOD = "independent-rect-replay-v1"


def validate_replay(value: Any) -> dict:
    result = new_report("design-replay-v1")
    result.update(
        replay_status="INVALID_INPUT",
        candidate_digest=None,
        design_digest=None,
        specification_digest=None,
        provenance_digest=None,
        method=METHOD,
        checks=[],
        coverage={},
        blocking_issues=[],
        unsupported_checks=[],
        missing_dependencies=[],
        sources={},
        baseline_status="UNKNOWN",
        original_generation_evidence={},
        grid_search_reexecuted=False,
    )
    if not schema_check(value, "design-replay.schema.json", result):
        return result
    review = value["review"]
    candidate = review["candidate"]
    result.update(candidate_digest=candidate_digest(candidate), design_digest=design_digest(review))
    result["sources"]["review"] = review
    if not bounded_geometry(review):
        issue(
            result,
            "errors",
            "RESOURCE_LIMIT",
            "review",
            "At most 500 polygons, 10000 vertices and coordinate magnitude 1e9 supported.",
        )
        return result
    provenance = value.get("provenance")
    if not provenance:
        issue(
            result,
            "missing_information",
            "ORIGINAL_SPECIFICATION_REQUIRED",
            "provenance",
            "Legacy candidate: supply actual original generation specification/provenance; no reconstruction.",
        )
        result.update(
            replay_status="INCOMPLETE", missing_dependencies=["original_generation_provenance"]
        )
        return finish(result)
    result["sources"]["provenance"] = provenance
    result["provenance_digest"] = provenance["provenance_digest"]
    origin = provenance["origin_candidate"]
    result["original_generation_evidence"] = {
        "candidate_id": origin["candidate_id"],
        "candidate_digest": candidate_digest(origin),
        "stored_hard_validation": origin["hard_validation"],
        "trusted_as_replay": False,
    }
    spec = provenance["generation_specification"]
    try:
        expected = create_generation_provenance(spec, origin)
        valid_provenance = expected == provenance
    except ValueError:
        valid_provenance = False
    source = spec
    baseline_revision = value.get("baseline_revision")
    if baseline_revision:
        source = baseline_revision["specification"]
    result["sources"]["specification"] = source
    result["specification_digest"] = canonical_digest(source)
    result["baseline_status"] = "REVISED_CONFIRMED" if baseline_revision else "ORIGINAL"
    refs = [
        {"pointer": "/sources/review", "digest": canonical_digest(review)},
        {"pointer": "/sources/specification", "digest": canonical_digest(source)},
    ]

    refs.append({"pointer": "/sources/provenance", "digest": canonical_digest(provenance)})
    if baseline_revision:
        result["sources"]["baseline_revision"] = baseline_revision
        refs.append(
            {"pointer": "/sources/baseline_revision", "digest": canonical_digest(baseline_revision)}
        )

    def check(
        key: str,
        status: str,
        method: str,
        observed: Any = None,
        expected: Any = None,
        reqs: list[str] | None = None,
    ) -> None:
        result["checks"].append(
            {
                "id": key,
                "status": status,
                "method": method,
                "observed": observed,
                "expected": expected,
                "requirement_ids": reqs or [],
                "evidence_refs": refs,
            }
        )

    check(
        "provenance_integrity",
        "VERIFIED" if valid_provenance else "STALE",
        "Recompute every provenance digest/constraint register against immutable source and origin.",
    )
    if value["mode"] == "original":
        check(
            "origin_binding",
            "VERIFIED" if candidate == origin else "STALE",
            "Original mode requires exact original candidate content.",
        )
    else:
        check(
            "origin_binding",
            "VERIFIED",
            "Externally supplied revision; constraint validation does not assert it was regenerated or approved.",
        )
    if baseline_revision:
        valid = value["mode"] == "revision" and baseline_revision["confirmation"][
            "specification_digest"
        ] == canonical_digest(source)
        check(
            "baseline_confirmation",
            "VERIFIED" if valid else "STALE",
            "Explicit human-supplied confirmation bound to revised baseline; identity not authenticated.",
        )
    try:
        _replay_constraints(source, candidate, check, result)
    except (ValueError, OverflowError, GEOSException) as exc:
        check(
            "geometric_operations",
            "UNSUPPORTED",
            "Finite supported geometry operation could not complete: " + str(exc),
        )
    statuses = [c["status"] for c in result["checks"]]
    result["replay_status"] = (
        "FAILED"
        if "FAILED" in statuses
        else "STALE"
        if "STALE" in statuses
        else "UNSUPPORTED"
        if "UNSUPPORTED" in statuses
        else "INCOMPLETE"
        if "UNKNOWN" in statuses
        else "VERIFIED"
    )
    result["blocking_issues"] = [
        c["id"] for c in result["checks"] if c["status"] not in {"VERIFIED", "NOT_APPLICABLE"}
    ]
    result["unsupported_checks"] = [
        c["id"] for c in result["checks"] if c["status"] == "UNSUPPORTED"
    ]
    result["missing_dependencies"] = [c["id"] for c in result["checks"] if c["status"] == "UNKNOWN"]
    applicable = sum(s != "NOT_APPLICABLE" for s in statuses)
    evaluated = sum(s in {"VERIFIED", "FAILED"} for s in statuses)
    result["coverage"] = {
        "applicable": applicable,
        "evaluated": evaluated,
        "verified": statuses.count("VERIFIED"),
        "failed": statuses.count("FAILED"),
        "evaluation_fraction": evaluated / applicable if applicable else None,
    }
    for c in result["checks"]:
        if c["status"] in {"FAILED", "STALE", "UNKNOWN", "UNSUPPORTED"}:
            issue(
                result,
                "errors" if c["status"] == "FAILED" else "missing_information",
                "REPLAY_" + c["status"],
                c["id"],
                c["method"],
                c["requirement_ids"],
            )
    return finish(result)


def _replay_constraints(spec: dict, candidate: dict, check: Any, result: dict) -> None:
    source_geometry = spec.get("geometry")
    if not source_geometry or not source_geometry.get("zoning"):
        check("source_dependencies", "UNKNOWN", "Source geometry and governed zoning are required.")
        return
    if not bounded_geometry({"candidate": {"geometry": source_geometry}}):
        check("source_limits", "UNSUPPORTED", "Original source exceeds geometry limits.")
        return
    source_spatial = validate_geometry(source_geometry)
    source_zoning = validate_zoning(source_geometry["zoning"])
    result["sources"].update(source_spatial=source_spatial, source_zoning=source_zoning)
    check(
        "source_validity",
        "VERIFIED"
        if not source_spatial["errors"]
        and all(d["code"] == "ROOM_GEOMETRY_MISSING" for d in source_spatial["missing_information"])
        and source_zoning["architect_approved"]
        else "UNKNOWN",
        "Source geometry/zoning must independently validate; source authorization is not candidate approval.",
    )
    check(
        "fixed_inventory",
        "VERIFIED" if spec.get("fixed_elements_status") == "complete" else "UNKNOWN",
        "All supplied fixed/reserved geometry must be explicitly declared complete.",
    )
    auth = spec.get("authorization")
    check(
        "source_authorization",
        "VERIFIED"
        if auth and auth["record"]["digest"] == authorization_digest(spec)
        else "UNKNOWN",
        "Original preliminary-generation authorization is content bound, not permission to write CAD.",
    )
    if candidate["algorithm"] != ALGORITHM:
        check(
            "algorithm",
            "UNSUPPORTED",
            "Only bounded-grid-rect-v1 constraint semantics are implemented.",
        )
    geometry = candidate["geometry"]
    floor_ids = sorted(f["id"] for f in geometry["floors"])
    metadata_ok = (
        sorted(candidate["floor_ids"]) == floor_ids
        and len(candidate["floor_ids"]) == len(floor_ids)
        and candidate["floor_id"] == (floor_ids[0] if len(floor_ids) == 1 else None)
    )
    check(
        "candidate_floor_metadata",
        "VERIFIED" if metadata_ok else "STALE",
        "Stored floor IDs must match current explicit geometry floors.",
    )
    spatial = validate_geometry(geometry)
    result["sources"]["spatial"] = spatial
    geometric_codes = {
        "INVALID_POLYGON",
        "NEAR_ZERO_AREA",
        "OUTSIDE_ENVELOPE",
        "ROOM_OVERLAP",
        "ROOM_IN_RESERVED_REGION",
    }
    errors = {e["code"] for e in spatial["errors"]}
    check(
        "spatial_geometry",
        "FAILED"
        if errors & geometric_codes
        else "VERIFIED"
        if spatial["status"] == "VALID"
        else "UNKNOWN",
        "Existing spatial validator is rerun, including declared boundary/overlap tolerances.",
        sorted(errors),
    )
    coordinate_match = all(
        geometry[k] == source_geometry[k]
        for k in ("project_id", "units", "frame", "floors", "tolerances")
    )
    check(
        "coordinate_context",
        "VERIFIED" if coordinate_match else "UNSUPPORTED",
        "Original frames, units, floors and tolerances must match exactly; no implicit transforms.",
    )
    check(
        "fixed_context",
        "UNSUPPORTED"
        if not coordinate_match
        else "VERIFIED"
        if geometry_context(geometry) == geometry_context(source_geometry)
        else "FAILED",
        "Original non-room site, envelopes, points, segments, reservations and overlap declarations cannot disappear/change silently.",
    )
    check(
        "requirement_baseline",
        "VERIFIED" if geometry.get("zoning") == source_geometry["zoning"] else "STALE",
        "Changed source brief/zoning needs an explicitly confirmed revised baseline.",
    )
    program = build_space_program(source_geometry["zoning"]["brief"])
    result["sources"]["program"] = program
    if program["status"] != "VALID":
        check("program", "UNKNOWN", "A complete source space program is required.")
        return
    if (
        len(program["relationships"]) > 128
        or sum(len(r["instance_pairs"]) for r in program["relationships"]) > 256
    ):
        check(
            "relationship_scope",
            "UNSUPPORTED",
            "Replay supports at most 128 relationships and 256 expanded instance pairs.",
        )
        return
    expected = {r["id"]: r for r in program["rooms"]}
    if len(expected) > 12:
        check("room_scope", "UNSUPPORTED", "Original solver scope is at most twelve source rooms.")
        return
    rows = [r for r in geometry["polygons"] if r["role"] == "room"]
    rooms = {r.get("room_id"): r for r in rows}
    check(
        "room_inventory",
        "VERIFIED" if set(rooms) == set(expected) and len(rows) == len(rooms) else "FAILED",
        "Exact source room-instance inventory; duplicates/extras cannot replace missing instances.",
        sorted(rooms),
        sorted(expected),
    )
    assignments = {
        r["room_id"]: r["floor_id"]
        for r in source_geometry["zoning"]["assignments"]
        if r["status"] not in {"rejected", "superseded"}
    }
    dimensions = {d["room_id"]: d for d in spec.get("room_dimensions", [])}
    check(
        "dimension_inventory",
        "VERIFIED"
        if len(dimensions) == len(spec.get("room_dimensions", []))
        and set(dimensions) == set(expected)
        else "UNKNOWN",
        "Original width/depth records must cover every source instance exactly once.",
    )
    requirements = {r["id"]: r for r in source_geometry["zoning"]["brief"]["requirements"]}
    source_shapes = {
        r["id"]: Polygon(r["exterior"], r.get("holes", [])) for r in source_geometry["polygons"]
    }
    unsupported_source_shapes = any(
        p["role"] == "room"
        or (
            p["role"] in {"footprint", "floor_outline"}
            and (
                source_shapes[p["id"]].interiors
                or not source_shapes[p["id"]].equals(box(*source_shapes[p["id"]].bounds))
            )
        )
        for p in source_geometry["polygons"]
    )
    if unsupported_source_shapes or source_geometry["relationships"]:
        check(
            "original_solver_scope",
            "UNSUPPORTED",
            "Original solver requires rectangular envelopes, no pre-existing source rooms and no overlap exemptions.",
        )
    footprint = next((r for r in source_geometry["polygons"] if r["role"] == "footprint"), None)
    if footprint is None:
        check(
            "footprint", "UNKNOWN", "Explicit original footprint required; site is not substituted."
        )
        return
    scale = 1 if source_geometry["units"] == "m" else 0.001
    shapes = {}
    placements = {}
    for key in sorted(set(expected) & set(rooms)):
        row, request = rooms[key], expected[key]
        shape = Polygon(row["exterior"], row.get("holes", []))
        shapes[key] = shape
        prefix = "room:" + key + ":"
        refs = [request["requirement_id"]]
        check(
            prefix + "traceability",
            "VERIFIED" if row.get("requirement_id") == request["requirement_id"] else "FAILED",
            "Source requirement identifier must be preserved.",
            row.get("requirement_id"),
            request["requirement_id"],
            refs,
        )
        check(
            prefix + "floor",
            "UNKNOWN"
            if key not in assignments
            else "VERIFIED"
            if row.get("floor_id") == assignments[key]
            else "FAILED",
            "Original active source floor assignment.",
            row.get("floor_id"),
            assignments.get(key),
            refs,
        )
        check(
            prefix + "frame",
            "VERIFIED"
            if row["units"] == geometry["units"] and row["frame_id"] == geometry["frame"]["id"]
            else "UNSUPPORTED",
            "Per-polygon coordinate metadata must match the declared frame/units.",
        )
        check(
            prefix + "validity",
            "VERIFIED"
            if shape.is_valid and math.isfinite(shape.area) and shape.area > 0
            else "FAILED",
            "Current valid positive-area polygon, with no repair.",
        )
        if not shape.is_valid or not math.isfinite(shape.area) or not coordinate_match:
            continue
        floor = assignments.get(key)
        envelope_row = next(
            (
                r
                for r in source_geometry["polygons"]
                if r["role"] == "floor_outline" and r.get("floor_id") == floor
            ),
            footprint,
        )
        envelope = source_shapes[envelope_row["id"]]
        check(
            prefix + "containment",
            "VERIFIED" if envelope.covers(shape) else "FAILED",
            "Exact original solver envelope containment; boundary tolerance never expands an original hard envelope.",
        )
        rectangle = not shape.interiors and shape.equals(box(*shape.bounds))
        check(
            prefix + "rectangle",
            "VERIFIED" if rectangle else "UNSUPPORTED",
            "Explicit width along X/depth along Y replay supports axis-aligned rectangles; bounding boxes never prove arbitrary room proportions.",
        )
        dim = dimensions.get(key)
        area = request["requested_area_m2"]
        if area and "min" in area and "max" in area:
            actual = shape.area * scale * scale
            check(
                prefix + "area",
                "VERIFIED" if _within(actual, area["min"], area["max"]) else "FAILED",
                "Recomputed m2 against original hard min/max; targets are soft.",
                actual,
                area,
                refs,
            )
        else:
            check(prefix + "area", "UNKNOWN", "Explicit original hard area range is missing.")
        if dim and rectangle:
            req = requirements.get(dim["requirement_id"], {})
            if req.get("type") != "mandatory" or req.get("confirmation") != "confirmed":
                check(
                    prefix + "dimension_provenance",
                    "UNKNOWN",
                    "Dimension bounds require original confirmed mandatory source provenance.",
                )
            else:
                x0, y0, x1, y1 = shape.bounds
                for axis, measured in (("width", x1 - x0), ("depth", y1 - y0)):
                    check(
                        prefix + axis,
                        "VERIFIED"
                        if _within(measured, dim[axis]["min"], dim[axis]["max"])
                        else "FAILED",
                        "Original axis-specific dimensional bounds; no rotation or arithmetic resizing inferred.",
                        measured,
                        dim[axis],
                        [dim["requirement_id"]],
                    )
        for reservation in source_geometry["polygons"]:
            if reservation["role"] == "reservation" and reservation.get("floor_id") == row.get(
                "floor_id"
            ):
                overlap = shape.intersection(source_shapes[reservation["id"]]).area
                check(
                    prefix + "reservation:" + reservation["id"],
                    "VERIFIED" if overlap == 0 else "FAILED",
                    "Exact original reservation exclusion; boundary contact allowed, positive overlap forbidden.",
                    overlap * scale * scale,
                    0,
                    [reservation["requirement_id"]],
                )
        for previous, other in shapes.items():
            if (
                previous != key
                and other.is_valid
                and rooms[previous].get("floor_id") == row.get("floor_id")
            ):
                overlap = shape.intersection(other).area
                check(
                    prefix + "overlap:" + previous,
                    "VERIFIED" if overlap == 0 else "FAILED",
                    "Exact original solver same-floor nonoverlap, independently of relaxed spatial tolerances.",
                    overlap * scale * scale,
                    0,
                )
        placements[key] = shape
    for relation in program["relationships"]:
        if relation["strength"] != "hard":
            continue
        if relation["relation"] != "adjacent":
            check(
                "relation:" + relation["id"],
                "UNSUPPORTED",
                "Qualitative mandatory separation has no executable distance/privacy definition.",
            )
            continue
        for a, b in relation["instance_pairs"]:
            status = "UNKNOWN"
            if a in placements and b in placements:
                ok = (
                    rooms[a]["floor_id"] == rooms[b]["floor_id"]
                    and placements[a].boundary.intersection(placements[b].boundary).length > 0
                )
                status = "VERIFIED" if ok else "FAILED"
            check(
                "relation:" + relation["id"] + ":" + a + ":" + b,
                status,
                "Original mandatory positive shared-edge adjacency; no door is inferred.",
                reqs=[relation["requirement_id"]],
            )
    measured = {
        k: s.area * scale * scale for k, s in shapes.items() if s.is_valid and math.isfinite(s.area)
    }
    stored = candidate["room_areas_m2"]
    check(
        "stored_measurements",
        "VERIFIED"
        if set(stored) == set(measured)
        and all(
            math.isclose(stored[k], v, rel_tol=1e-12, abs_tol=1e-12) for k, v in measured.items()
        )
        else "STALE",
        "Stored room areas are compared to fresh measurements, never trusted.",
    )


def _within(value: float, lower: float, upper: float) -> bool:
    return (value >= lower or math.isclose(value, lower, rel_tol=1e-12, abs_tol=1e-12)) and (
        value <= upper or math.isclose(value, upper, rel_tol=1e-12, abs_tol=1e-12)
    )
