"""Constructive proposed wall revisions linked to immutable floorplan candidates."""

from copy import deepcopy
from typing import Any

from shapely.errors import GEOSException
from shapely.ops import unary_union

from vnai.cad_readiness import readiness_report
from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.design_provenance import bounded_geometry
from vnai.review_common import candidate_digest, design_digest
from vnai.wall_geometry import build_wall, junctions, faces
from vnai.wall_impact import assess
from vnai.wall_topology import extract, segment

EXIT_CODES = {"GENERATED": 0, "INVALID_INPUT": 1, "INCOMPLETE": 3, "CONFLICT": 4, "UNSUPPORTED": 5}


def normalize_spec(value: dict) -> dict:
    spec = deepcopy(value)
    spec["treatments"].sort(key=lambda r: r["id"])
    spec["special_walls"].sort(key=lambda r: r["id"])
    for rule in spec["treatments"]:
        for k in ("room_ids", "floor_ids", "boundary_ids"):
            if k in rule["selector"]:
                rule["selector"][k] = sorted(set(rule["selector"][k]))
    for row in [*spec["treatments"], *spec["special_walls"]]:
        if "wall" in row:
            row["wall"]["requirement_ids"] = sorted(set(row["wall"]["requirement_ids"]))
        if "reference" in row:
            row["reference"] = segment(row["reference"]["start"], row["reference"]["end"])
    return spec


def _without_approval(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_approval(v) for k, v in value.items() if k != "approval"}
    if isinstance(value, list):
        return [_without_approval(v) for v in value]
    return value


def generate_walls(value: Any, *, _cache=None) -> dict:
    if _cache is not None:
        return _cache.run("walls", value, lambda: _generate_walls(value, _cache))
    return _generate_walls(value, None)


def _generate_walls(value: Any, _cache) -> dict:
    result = new_report("architectural-walls-v1")
    result.update(
        wall_status="INVALID_INPUT",
        source_candidate_id=None,
        source_candidate_digest=None,
        source_design_digest=None,
        wall_specification_digest=None,
        derived_geometry_digest=None,
        wall_revision_id=None,
        method="orthogonal-wall-bands-v1",
        output_units="m",
        frame_id=None,
        source_units=None,
        boundary_topology=[],
        walls=[],
        junctions=[],
        floors=[],
        rooms=[],
        opening_mappings=[],
        constraint_impact={},
        evidence_impact={},
        specification_status="INCOMPLETE",
        geometry_status="NOT_GENERATED",
        drafting_readiness={},
        approval_inherited=False,
        architect_approval="NOT_GRANTED",
        sources={},
    )
    if not schema_check(value, "wall-input.schema.json", result):
        return result
    flags = set()

    def problem(kind: str, code: str, path: str, message: str) -> None:
        flags.add(kind)
        bucket = (
            "errors"
            if kind in {"invalid", "conflict"}
            else "warnings"
            if kind == "warnings"
            else "missing_information"
        )
        issue(result, bucket, code, path, message)

    review = value["source"]["replay"]["review"]
    candidate = review["candidate"]
    geometry = candidate["geometry"]
    spec = normalize_spec(value["wall_specification"])
    bound = {
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate_digest(candidate),
    }
    result.update(
        source_candidate_id=bound["candidate_id"],
        source_candidate_digest=bound["candidate_digest"],
        source_design_digest=design_digest(review),
        frame_id=geometry["frame"]["id"],
        source_units=geometry["units"],
        wall_specification_digest=canonical_digest(_without_approval(spec)),
    )
    normalized_input = deepcopy(value)
    normalized_input["wall_specification"] = spec
    result["sources"]["input"] = normalized_input
    if (
        not bounded_geometry(review)
        or len(geometry["floors"]) > 12
        or sum(r["role"] == "room" for r in geometry["polygons"]) > 12
    ):
        problem(
            "invalid",
            "WALL_RESOURCE_LIMIT",
            "source",
            "Wall scope: <=12 rooms/floors, <=500 polygons, <=10000 coordinate pairs and physical magnitudes <=1e9 source units.",
        )
        return finish(result)
    for key, actual in (
        ("source_candidate_digest", bound["candidate_digest"]),
        ("source_design_digest", design_digest(review)),
    ):
        if key not in spec:
            problem(
                "missing_information",
                "WALL_SOURCE_BINDING_REQUIRED",
                key,
                "Wall specification must bind the exact selected candidate and design sidecar.",
            )
        elif spec[key] != actual:
            problem(
                "invalid",
                "STALE_WALL_SOURCE",
                key,
                "Wall specification does not match current immutable source content.",
            )
    selection = review.get("selection")
    if not selection:
        problem(
            "missing_information",
            "WALL_CANDIDATE_SELECTION_REQUIRED",
            "source",
            "Select the exact source candidate before deriving architectural walls.",
        )
    elif (
        selection["candidate_id"] != candidate["candidate_id"]
        or selection["candidate_digest"] != bound["candidate_digest"]
    ):
        problem(
            "invalid",
            "WALL_SELECTION_MISMATCH",
            "source",
            "Selected candidate ID/digest does not match source content.",
        )
    if flags & {"invalid", "missing_information"}:
        result["wall_status"] = "INVALID_INPUT" if "invalid" in flags else "INCOMPLETE"
        return finish(result)
    readiness = readiness_report(value["source"])
    result["sources"]["source_readiness"] = readiness
    spatial = readiness.get("sources", {}).get("spatial")
    if spatial is None or spatial["status"] != "VALID":
        problem(
            "invalid",
            "SOURCE_GEOMETRY_INVALID",
            "source",
            "Current allocation geometry must independently validate before constructive wall derivation.",
        )
        return finish(result)
    if readiness["readiness_status"] != "READY_FOR_DRAFTING":
        problem(
            "warnings",
            "SOURCE_DRAFTING_LIMITATION",
            "source",
            "Existing readiness is "
            + readiness["readiness_status"]
            + "; wall geometry does not promote it.",
        )
    ids = [r["id"] for r in [*spec["treatments"], *spec["special_walls"]]]
    if len(ids) != len(set(ids)):
        problem(
            "invalid",
            "DUPLICATE_WALL_SPECIFICATION_ID",
            "wall_specification",
            "Treatment/special-wall IDs must be globally unique.",
        )
        return finish(result)
    requirements = {
        r["id"] for r in geometry.get("zoning", {}).get("brief", {}).get("requirements", [])
    }
    floor_ids = {f["id"] for f in geometry["floors"]}
    room_ids = {r["room_id"] for r in geometry["polygons"] if r["role"] == "room"}
    for row in [*spec["treatments"], *spec["special_walls"]]:
        if "floor_id" in row and row["floor_id"] not in floor_ids:
            problem(
                "invalid",
                "UNKNOWN_WALL_FLOOR",
                row["id"],
                "Special wall references an unknown floor.",
            )
        selector = row.get("selector", {})
        if (
            not set(selector.get("floor_ids", [])) <= floor_ids
            or not set(selector.get("room_ids", [])) <= room_ids
        ):
            problem(
                "invalid",
                "WALL_SELECTOR_REFERENCE",
                row["id"],
                "Wall selector references unknown room/floor IDs.",
            )
        profile = row.get("wall")
        if profile:
            if not set(profile["requirement_ids"]) <= requirements:
                problem(
                    "invalid",
                    "WALL_REQUIREMENT_REFERENCE",
                    row["id"],
                    "Wall requirements must reference the existing source register.",
                )
            if profile.get("reference_room_id") and profile["reference_room_id"] not in room_ids:
                problem(
                    "invalid", "WALL_ROOM_REFERENCE", row["id"], "Reference room does not exist."
                )
            if profile["approval_status"] in {"reviewed", "approved"}:
                approval = profile.get("approval")
                if (
                    not approval
                    or approval["digest"] != result["wall_specification_digest"]
                    or approval["role"] != "architect"
                ):
                    problem(
                        "missing_information",
                        "WALL_SPEC_REVIEW_RECORD_REQUIRED",
                        row["id"],
                        "Declared wall-spec review/approval requires a bound architect record; it never approves derived geometry.",
                    )
    if "invalid" in flags:
        return finish(result)
    try:
        boundaries, envelopes, shapes, rooms = extract(geometry, spec["special_walls"])
        result["boundary_topology"] = boundaries
        known_ids = {b["id"] for b in boundaries}
        for rule in spec["treatments"]:
            if not set(rule["selector"].get("boundary_ids", [])) <= known_ids:
                problem(
                    "invalid",
                    "UNKNOWN_WALL_BOUNDARY",
                    rule["id"],
                    "Boundary ID is stale/unknown under this exact source topology.",
                )
        walls = []
        for boundary in boundaries:
            choices = []
            for rule in spec["treatments"]:
                selector = rule["selector"]
                if selector["kind"] not in {boundary["kind"], "all"}:
                    continue
                if selector.get("floor_ids") and boundary["floor_id"] not in selector["floor_ids"]:
                    continue
                if selector.get("room_ids") and not set(selector["room_ids"]) <= set(
                    boundary["room_ids"]
                ):
                    continue
                if selector.get("boundary_ids") and boundary["id"] not in selector["boundary_ids"]:
                    continue
                priority = (
                    (4 if selector.get("boundary_ids") else 0)
                    + (2 if selector.get("room_ids") else 0)
                    + (1 if selector.get("floor_ids") else 0)
                )
                choices.append((priority, rule["id"], rule["action"], rule.get("wall")))
            choices += [
                (8, r["id"], "wall", r["wall"])
                for r in spec["special_walls"]
                if r["id"] in boundary["special_ids"]
            ]
            if choices:
                priority = max(c[0] for c in choices)
                choices = [c for c in choices if c[0] == priority]
                action = choices[0][2]
                equivalent = {canonical_digest([c[2], c[3]]) for c in choices}
                if len(equivalent) != 1:
                    problem(
                        "invalid",
                        "CONFLICTING_WALL_INTENT",
                        boundary["id"],
                        "Equally specific wall/no-wall profiles disagree; no arbitrary winner.",
                    )
                    boundary["treatment"] = "CONFLICT"
                    continue
            else:
                action = spec.get("default_treatment", "unresolved")
            boundary["treatment"] = action
            if action == "unresolved":
                problem(
                    "missing_information",
                    "UNRESOLVED_BOUNDARY_INTENT",
                    boundary["id"],
                    "No architectural wall/open-plan decision was supplied for this boundary.",
                )
            elif action == "wall":
                profile = choices[0][3]
                if profile is None:
                    problem(
                        "missing_information",
                        "WALL_PROFILE_REQUIRED",
                        boundary["id"],
                        "Wall intent has no thickness/alignment specification.",
                    )
                    continue
                semantics = profile.get("reference_semantics", spec.get("boundary_semantics"))
                wall = build_wall(
                    boundary, profile, [c[1] for c in choices], bound, semantics, problem
                )
                if wall:
                    walls.append(wall)
                    if profile["confirmation"] != "confirmed":
                        problem(
                            "missing_information",
                            "UNCONFIRMED_WALL_SPECIFICATION",
                            wall["id"],
                            "Geometry is proposed using unconfirmed wall information; areas are conditional.",
                        )
        result["junctions"] = junctions(walls, problem)
        unions = {
            f: unary_union([w["_shape"] for w in walls if w["floor_id"] == f]) for f in envelopes
        }
        for wall in walls:
            faces(wall, unions[wall["floor_id"]])
            wall["affected_room_ids"] = sorted(
                k
                for k, r in rooms.items()
                if r["floor_id"] == wall["floor_id"]
                and shapes[r["id"]].intersection(wall["_shape"]).area > 0
            )
        wall_information_verified = (
            all(b.get("treatment") not in {"unresolved", "CONFLICT"} for b in boundaries)
            and sum(b.get("treatment") == "wall" for b in boundaries) == len(walls)
            and all(j["status"] == "VERIFIED" for j in result["junctions"])
            and all(w["confirmation"] == "confirmed" for w in walls)
        )
        assess(
            normalized_input,
            result,
            envelopes,
            shapes,
            rooms,
            walls,
            unions,
            readiness,
            problem,
            wall_information_verified,
        )
        result["walls"] = [
            {k: v for k, v in w.items() if not k.startswith("_")}
            for w in sorted(walls, key=lambda w: w["id"])
        ]
        complete = all(
            b.get("treatment") not in {"unresolved", "CONFLICT"} for b in boundaries
        ) and sum(b.get("treatment") == "wall" for b in boundaries) == len(walls)
        connected = all(j["status"] == "VERIFIED" for j in result["junctions"])
        outside = any(f["wall_area_outside_envelope_m2"] > 0 for f in result["floors"])
        valid = all(w["_shape"].is_valid for w in walls)
        result["geometry_status"] = (
            "INVALID" if outside or not valid else "VALID" if complete and connected else "PARTIAL"
        )
        result["specification_status"] = (
            "INCOMPLETE"
            if not complete
            else "CONFIRMED"
            if all(w["confirmation"] == "confirmed" for w in walls)
            else "PROPOSED"
        )
        result["derived_geometry_digest"] = canonical_digest(
            {
                "walls": [[w["id"], w["geometry_digest"]] for w in result["walls"]],
                "floors": [[f["floor_id"], f["wall_footprint"]] for f in result["floors"]],
                "rooms": [[r["room_id"], r["clear_geometry"]] for r in result["rooms"]],
            }
        )
        result["wall_revision_id"] = "WR-" + canonical_digest(
            [
                result["source_design_digest"],
                result["wall_specification_digest"],
                result["derived_geometry_digest"],
            ]
        )
    except ValueError as exc:
        kind = "missing_information" if str(exc).startswith("INCOMPLETE:") else "unsupported"
        problem(kind, "WALL_GEOMETRY_SCOPE", "geometry", str(exc))
    except (GEOSException, OverflowError) as exc:
        problem("unsupported", "WALL_GEOMETRY_OPERATION", "geometry", str(exc))
    result["wall_status"] = (
        "INVALID_INPUT"
        if "invalid" in flags
        else "CONFLICT"
        if "conflict" in flags
        else "UNSUPPORTED"
        if "unsupported" in flags
        else "INCOMPLETE"
        if "missing_information" in flags
        else "GENERATED"
    )
    result["drafting_readiness"] = {
        "source_status": readiness["readiness_status"],
        "derived_status": "NOT_READY" if "conflict" in flags else "INCOMPLETE",
        "reason": "Fresh architect review and opening/clearance remapping are required for this separate proposed wall revision.",
        "wall_geometry_generated": bool(result["walls"]),
        "approval_granted": False,
        "cad_writes_permitted": False,
    }
    return finish(result)


def validate_walls(value: Any) -> dict:
    """Validate input or independently recompute a stored generated wall report."""
    if not isinstance(value, dict) or value.get("contract") != "architectural-walls-v1":
        return generate_walls(value)
    check = new_report("stored-wall-contract")
    if not schema_check(value, "wall-result.schema.json", check):
        result = generate_walls({})
        result["errors"] = check["errors"]
        return finish(result)
    source_input = value.get("sources", {}).get("input")
    if source_input is None:
        result = generate_walls({})
        issue(
            result,
            "errors",
            "WALL_RECOMPUTE_INPUT_REQUIRED",
            "sources.input",
            "Original wall input is required to verify stored geometry.",
        )
        return finish(result)
    fresh = generate_walls(source_input)
    fields = (
        "source_candidate_digest",
        "source_design_digest",
        "wall_specification_digest",
        "derived_geometry_digest",
        "wall_revision_id",
        "walls",
        "floors",
        "rooms",
        "junctions",
        "opening_mappings",
        "wall_status",
        "geometry_status",
    )
    if any(value.get(k) != fresh.get(k) for k in fields):
        issue(
            fresh,
            "errors",
            "STORED_WALL_GEOMETRY_MISMATCH",
            "$",
            "Stored geometry/areas/bindings do not match independent recomputation; reported generated/pass states are not trusted.",
        )
        fresh["wall_status"] = "INVALID_INPUT"
        finish(fresh)
    return fresh
