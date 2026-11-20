"""Proposed staircase child revision of the existing wall/opening pipeline."""

from copy import deepcopy
from fractions import Fraction
from typing import Any
from shapely.geometry import Point, LineString
from shapely.errors import GEOSException
from vnai.contracts import new_report, issue, finish, schema_check, canonical_digest
from vnai.opening_drafting import draft_openings
from vnai.review_common import build_context, near_covers
from vnai.stairs import _stair_report
from vnai.circulation import _graph_report
from vnai.stair_geometry import construct, exact
from vnai.stair_clearance import verify

EXIT_CODES = {"GENERATED": 0, "INVALID_INPUT": 1, "INCOMPLETE": 3, "CONFLICT": 4, "UNSUPPORTED": 5}


def draft_stairs(value: Any) -> dict:
    result = new_report("stair-drafting-v1")
    result.update(
        drafting_status="INVALID_INPUT",
        geometry_status="NOT_GENERATED",
        source_opening_revision_id=None,
        source_candidate_digest=None,
        specification_digest=None,
        stair_revision_id=None,
        frame_id=None,
        datum=None,
        units="m",
        stairs=[],
        floor_openings=[],
        headroom={},
        circulation={},
        schedule=[],
        source_conflicts=[],
        evidence_impact={},
        sources={},
        approval_inherited=False,
        architect_approval="NOT_GRANTED",
    )
    if not schema_check(value, "stair-drafting-input.schema.json", result):
        return finish(result)
    value = deepcopy(value)
    spec = value["specification"]
    flags = set()
    seen = set()

    def bad(kind, code, path, message):
        if kind != "warning":
            flags.add(kind)
        signature = (kind, code, path, message)
        if signature in seen:
            return
        seen.add(signature)
        issue(
            result,
            "errors"
            if kind in {"invalid", "conflict"}
            else "warnings"
            if kind == "warning"
            else "missing_information",
            code,
            path,
            message,
        )

    def bounded(v):
        if isinstance(v, (float, int)) and not isinstance(v, bool):
            return abs(v) <= 1e9
        if isinstance(v, dict):
            return all(bounded(x) for x in v.values())
        if isinstance(v, list):
            return all(bounded(x) for x in v)
        return True

    def coordinate_count(item):
        if isinstance(item, list):
            if len(item) == 2 and all(isinstance(v, (int, float)) for v in item):
                return 1
            return sum(coordinate_count(v) for v in item)
        if isinstance(item, dict):
            return sum(coordinate_count(v) for v in item.values())
        return 0

    if coordinate_count(spec) > 20000:
        bad(
            "unsupported",
            "STAIR_COORDINATE_LIMIT",
            "specification",
            "At most 20000 new coordinate pairs per request.",
        )
        result["drafting_status"] = "UNSUPPORTED"
        return finish(result)
    if not bounded(spec):
        bad(
            "unsupported",
            "STAIR_NUMERIC_SCOPE",
            "specification",
            "Numeric magnitudes must be <=1e9 before unit conversion.",
        )
        result["drafting_status"] = "UNSUPPORTED"
        return finish(result)
    for k in [
        "levels",
        "stairs",
        "floor_openings",
        "slabs",
        "obstacles",
        "connections",
        "plan_cut_elevations",
    ]:
        spec[k].sort(key=lambda r: r.get("id", r.get("floor_id", "")))
        keys = [r.get("id", r.get("floor_id")) for r in spec[k]]
        if len(keys) != len(set(keys)):
            bad(
                "invalid", "DUPLICATE_STAIR_SPEC_ID", k, "IDs must be unique within their register."
            )
    for s in spec["stairs"]:
        s["stairwell_ids"] = sorted(set(s["stairwell_ids"]))
        s["requirement_ids"] = sorted(set(s["requirement_ids"]))
        if sum(f["risers"] for f in s["flights"]) > 256:
            bad("unsupported", "STAIR_STEP_LIMIT", s["id"], "At most 256 risers per staircase.")
    if sum(f["risers"] for s in spec["stairs"] for f in s["flights"]) > 512:
        bad("unsupported", "STAIR_TOTAL_STEP_LIMIT", "stairs", "At most 512 risers per request.")
    if flags:
        result["drafting_status"] = "INVALID_INPUT" if "invalid" in flags else "UNSUPPORTED"
        return finish(result)
    result["sources"]["input"] = value
    source = draft_openings(value["source"])
    result["sources"]["opening_model"] = source
    result.update(
        source_opening_revision_id=source["opening_revision_id"],
        source_candidate_digest=source["source_candidate_digest"],
        frame_id=source["frame_id"],
        datum=spec["datum"],
        specification_digest=canonical_digest(spec),
    )
    if (
        value["source_opening_revision_id"] != source["opening_revision_id"]
        or value["source_opening_geometry_digest"] != source["opening_geometry_digest"]
    ):
        bad(
            "invalid",
            "STALE_SOURCE_OPENING_DRAFT",
            "source",
            "Bind the exact recomputed B2 revision and geometry digest.",
        )
    if spec["frame_id"] != source["frame_id"]:
        bad(
            "invalid",
            "STAIR_COORDINATE_FRAME",
            "frame_id",
            "Use the source local frame; no implicit transform.",
        )
    if not spec["datum"].strip():
        bad("invalid", "STAIR_DATUM", "datum", "Supply a common absolute elevation datum.")
    if source["drafting_status"] == "INVALID_INPUT":
        bad("invalid", "SOURCE_OPENING_INVALID", "source", "The source B2 input is invalid.")
    if "invalid" in flags:
        result["drafting_status"] = "INVALID_INPUT"
        return finish(result)
    if source["drafting_status"] == "CONFLICT":
        result["source_conflicts"] = deepcopy(source["errors"]) + deepcopy(
            source["source_conflicts"]
        )
        bad(
            "conflict",
            "SOURCE_DRAFTING_CONFLICTS_RETAINED",
            "source",
            "The original source conflicts remain unresolved; no rooms/walls/openings are changed.",
        )
    elif source["drafting_status"] == "UNSUPPORTED":
        bad(
            "missing",
            "SOURCE_DRAFTING_LIMITATIONS",
            "source",
            "Unsupported source drafting geometry is not promoted by this child revision.",
        )
    elif source["drafting_status"] == "INCOMPLETE":
        for entry in source["missing_information"]:
            if entry["path"].startswith(("stairs.", "graph.", "paths.")):
                continue  # these parent checks are stale and freshly replayed below
            bad("missing", entry["code"], "source_openings." + entry["path"], entry["message"])
        bad(
            "warning",
            "PARENT_CIRCULATION_REPLAYED",
            "source",
            "Original parent stair/graph/path verdicts remain in the source report; fresh scoped B3 evidence is reported separately.",
        )
    review = deepcopy(value["source"]["source"]["source"]["replay"]["review"])
    review["exteriors"] = value["source"]["specification"].get(
        "exteriors", review.get("exteriors", [])
    )
    ctx = build_context(review)
    if ctx.report["errors"] or ctx.geometry_status != "VALID":
        bad(
            "invalid",
            "STAIR_SOURCE_GEOMETRY",
            "source",
            "The shared candidate context must be geometrically valid.",
        )
        result["drafting_status"] = "INVALID_INPUT"
        return finish(result)
    for extra in value["source"]["specification"].get("additional_obstacles", []):
        ctx.obstacles.append((extra["id"], extra["floor_id"], ctx.polygon(extra)))
    scale = Fraction(1) if spec["units"] == "m" else Fraction(1, 1000)
    levels = {}
    requirements = {
        r["id"] for r in ctx.geometry.get("zoning", {}).get("brief", {}).get("requirements", [])
    }
    for level in spec["levels"]:
        floor = level["floor_id"]
        if floor not in ctx.floors:
            bad("invalid", "STAIR_LEVEL_FLOOR_REFERENCE", floor, "Use existing source floor IDs.")
            continue
        if "finished_elevation" not in level or level["confirmation"] != "confirmed":
            bad(
                "missing",
                "FLOOR_ELEVATION_REQUIRED",
                floor,
                "Supply confirmed finished floor elevation and provenance.",
            )
            continue
        z = exact(level["finished_elevation"], scale)
        levels[floor] = z
        gfloor = next(f for f in ctx.geometry["floors"] if f["id"] == floor)
        supplied = gfloor.get("elevation_m")
        zoning = next(
            (f for f in ctx.geometry.get("zoning", {}).get("floors", []) if f["id"] == floor), {}
        )
        if supplied is None and "elevation" in zoning:
            supplied = zoning["elevation"]["value"] * (
                1 if zoning["elevation"]["unit"] == "m" else 0.001
            )
        if supplied is not None and abs(float(z) - supplied) > ctx.tolerance:
            bad(
                "invalid",
                "SOURCE_FLOOR_ELEVATION_MISMATCH",
                floor,
                "Stair datum levels contradict an explicit existing floor elevation.",
            )
        gfloor["elevation_m"] = float(
            z
        )  # isolated replay context only; original input/candidate is immutable
    if "invalid" in flags:
        result["drafting_status"] = "INVALID_INPUT"
        return finish(result)
    cuts = {}
    for c in spec["plan_cut_elevations"]:
        if c["floor_id"] not in ctx.floors:
            bad(
                "invalid",
                "PLAN_CUT_FLOOR_REFERENCE",
                c["floor_id"],
                "Drawing plane references an unknown source floor.",
            )
        cuts[c["floor_id"]] = float(exact(c["elevation"], scale))
    if not spec["stairs"]:
        bad(
            "missing",
            "STAIR_SPECIFICATION_REQUIRED",
            "stairs",
            "Supply explicit staircase specifications.",
        )
    component_ids = []
    for row in spec["stairs"]:
        component_ids.extend(f["id"] for f in row["flights"])
        component_ids.extend(record_item["id"] for record_item in row["landings"])
        if not set(row["requirement_ids"]) <= requirements:
            bad(
                "invalid",
                "STAIR_REQUIREMENT_REFERENCE",
                row["id"],
                "Requirement IDs must exist in the original source register.",
            )
        if row["confirmation"] != "confirmed":
            bad(
                "missing",
                "STAIR_SPEC_UNCONFIRMED",
                row["id"],
                "Supplied dimensions remain proposed.",
            )
        if row["review_status"] != "proposed":
            bad(
                "missing",
                "STAIR_CHILD_REVIEW_REQUIRED",
                row["id"],
                "Declared review is preserved in input; this new geometry requires its own child-bound architect review. No identity is inferred.",
            )
        try:
            geometry_issues = []

            def geometry_bad(kind, code, path, message):
                if kind in {"invalid", "conflict"}:
                    geometry_issues.append(code)
                bad(kind, code, path, message)

            stair = construct(row, levels, scale, ctx.tolerance, ctx.area_tolerance, geometry_bad)
            if stair is None:
                continue
            stair["geometry_status"] = "INVALID" if geometry_issues else "VALID"
            stair["plan_views"] = []
            for floor in [stair["source_floor"], stair["destination_floor"]]:
                if floor not in cuts:
                    bad(
                        "missing",
                        "STAIR_PLAN_CUT_REQUIRED",
                        floor,
                        "Supply an absolute plan cut elevation; no drawing default is inferred.",
                    )
                stair["plan_views"].append(
                    {
                        "floor_id": floor,
                        "cut_elevation_m": cuts.get(floor),
                        "surface_classes": [
                            {
                                "surface_id": s["id"],
                                "classification": "UNKNOWN"
                                if floor not in cuts
                                else "ABOVE_CUT"
                                if s["elevation_m"] > cuts[floor]
                                else "AT_CUT"
                                if s["elevation_m"] == cuts[floor]
                                else "BELOW_CUT",
                            }
                            for s in stair["surfaces"]
                        ],
                    }
                )
            if "clear_width_requirement" in spec and any(
                f["width_m"] + ctx.tolerance < float(exact(spec["clear_width_requirement"], scale))
                for f in stair["flights"]
            ):
                bad(
                    "conflict",
                    "STAIR_DECLARED_WIDTH",
                    row["id"],
                    "A flight is narrower than the explicit project clearance requirement.",
                )
            result["stairs"].append(stair)
        except (GEOSException, ValueError, OverflowError) as exc:
            bad("invalid", "STAIR_GEOMETRY_CONSTRUCTION", row["id"], str(exc))
    if len(component_ids) != len(set(component_ids)):
        bad(
            "invalid",
            "DUPLICATE_STAIR_COMPONENT_ID",
            "stairs",
            "Flight/landing IDs must be unique across this request.",
        )
    try:
        assessment = verify(result["stairs"], spec, source, levels, ctx, scale, bad)
    except (GEOSException, ValueError, OverflowError) as exc:
        bad("invalid", "STAIR_CLEARANCE_GEOMETRY", "specification", str(exc))
        result["drafting_status"] = "INVALID_INPUT"
        return finish(result)
    result["floor_openings"] = assessment["floor_assessment"]
    result["headroom"] = assessment["headroom"]
    result["sources"]["slab_material"] = assessment["slab_material"]
    result["sources"]["collision_regions"] = assessment["conflicts"]
    connections = deepcopy(spec["connections"])
    byid = {s["id"]: s for s in result["stairs"]}
    valid_connections = []
    for connection in connections:
        stair = byid.get(connection["id"])
        if stair is None:
            bad(
                "invalid",
                "STAIR_CONNECTION_ID",
                connection["id"],
                "Connection must reference a generated stair ID.",
            )
            continue
        valid = True
        for k, expected in [("source", "source_floor"), ("destination", "destination_floor")]:
            e = connection[k]
            if "point" not in e:
                bad(
                    "missing",
                    "STAIR_ENTRY_EXIT_REQUIRED",
                    connection["id"] + "." + k,
                    "Supply the actual endpoint point; no interface position is invented.",
                )
                valid = False
                continue
            wanted = stair["entry_point"] if k == "source" else stair["exit_point"]
            if (
                e["floor_id"] != stair[expected]
                or e["stairwell_id"] not in stair["stairwell_ids"]
                or Point(ctx.xy(e["point"])).distance(Point(wanted)) > ctx.tolerance
            ):
                bad(
                    "conflict",
                    "STAIR_DRAFTED_ENDPOINT",
                    connection["id"] + "." + k,
                    "006-B connection must coincide with the actual generated entry/arrival interface.",
                )
                valid = False
        for side in ("source", "destination"):
            endpoint = connection[side]
            door = next(
                (
                    o
                    for o in source["openings"]
                    if o["id"] == endpoint.get("opening_id") and not o["type"].endswith("window")
                ),
                None,
            )
            if door is None:
                bad(
                    "missing",
                    "STAIR_DOOR_INTERFACE_REQUIRED",
                    connection["id"] + "." + side,
                    "Require an actual current B2 door at this stair interface.",
                )
                valid = False
                continue
            clear = door.get("clear_reference")
            edge = stair["entry_edge"] if side == "source" else stair["exit_edge"]
            if clear is None or not near_covers(
                LineString([clear["start"], clear["end"]]), LineString(edge), ctx.tolerance
            ):
                bad(
                    "conflict",
                    "STAIR_PORTAL_EDGE_WIDTH",
                    door["id"],
                    "The full generated entry/exit edge must fit the actual clear portal, not only its midpoint.",
                )
                valid = False
            if "headroom_requirement" in spec and (
                door.get("clear_height_m") is None
                or door["clear_height_m"] + ctx.tolerance
                < float(exact(spec["headroom_requirement"], scale))
            ):
                bad(
                    "missing" if door.get("clear_height_m") is None else "conflict",
                    "STAIR_DOOR_VERTICAL_CLEARANCE",
                    door["id"],
                    "Explicit door clear height must resolve the supplied project headroom at the landing interface.",
                )
                valid = False
        if valid:
            valid_connections.append(connection)
    if set(byid) - {c["id"] for c in valid_connections}:
        bad(
            "missing",
            "STAIR_CONNECTION_EVIDENCE_REQUIRED",
            "connections",
            "Supply fresh exact 006-B floor/space/opening interfaces for every generated stair.",
        )
    ctx.spec["stairs"] = valid_connections
    ctx.spec["stairs_complete"] = spec["stairs_complete"]
    opening_stage = deepcopy(source["circulation"]["opening_validity"])
    width_checks = []
    if "clear_width_requirement" in spec:
        from vnai.opening_hosts import shape_set
        from vnai.wall_topology import encode

        width = float(exact(spec["clear_width_requirement"], scale))
        for stair in result["stairs"]:
            usable = shape_set(stair["footprint"])
            for surface in stair["surfaces"]:
                if surface["kind"] != "landing":
                    continue
                corridor = LineString(surface["walking_line"]).buffer(
                    width / 2, cap_style=2, join_style=2
                )
                fits = near_covers(usable, corridor, ctx.tolerance)
                width_checks.append(
                    {
                        "stair_id": stair["id"],
                        "landing_id": surface["id"],
                        "width_m": width,
                        "corridor": encode(corridor),
                        "status": "VERIFIED_SUPPLIED_PLANAR_SCOPE" if fits else "FAILED",
                    }
                )
                if not fits:
                    bad(
                        "conflict",
                        "STAIR_LANDING_CLEARANCE",
                        surface["id"],
                        "Supplied landing walking line and width leave the actual connected stair footprint.",
                    )
    result["sources"]["width_checks"] = width_checks
    replay = _stair_report(ctx, opening_stage)
    graph = _graph_report(ctx, opening_stage, replay)
    for label, stage in (("stairs", replay), ("graph", graph)):
        for bucket, kind in [("errors", "conflict"), ("missing_information", "missing")]:
            for entry in stage[bucket]:
                bad(kind, entry["code"], label + "." + entry["path"], entry["message"])
    collision_codes = {
        "STAIR_PRISM_COLLISION",
        "STAIR_STAIR_COLLISION",
        "STAIR_WALL_COLLISION",
        "STAIR_RISER_PRISM_COLLISION",
        "DOOR_STAIR_MOVEMENT_COLLISION",
        "STAIR_FIXED_PLAN_COLLISION",
        "STAIR_RESERVATION_FIT",
        "STAIR_DECLARED_WIDTH",
        "STAIR_LANDING_CLEARANCE",
        "STAIR_PORTAL_EDGE_WIDTH",
        "STAIR_DRAFTED_ENDPOINT",
        "STAIR_DOOR_VERTICAL_CLEARANCE",
    }
    horizontal_failed = any(e["code"] in collision_codes for e in result["errors"]) or any(
        s["geometry_status"] == "INVALID" for s in result["stairs"]
    )
    interfaces_known = (
        bool(result["stairs"])
        and len(valid_connections) == len(result["stairs"])
        and all(all(e["entry_exit_valid"]) for e in replay["stair_results"])
    )
    referenced = {
        e.get("opening_id") for c in valid_connections for e in (c["source"], c["destination"])
    }
    doors_known = bool(referenced) and all(
        o["physical_state"] == "GEOMETRICALLY_TRAVERSABLE"
        for o in source["openings"]
        if o["id"] in referenced
    )
    horizontal_known = (
        interfaces_known
        and doors_known
        and value["source"]["specification"].get("fixed_obstacles_complete") is True
        and not any(
            e["code"] == "WALL_VERTICAL_COLLISION_UNKNOWN" for e in result["missing_information"]
        )
    )
    clearance_status = (
        "FAILED"
        if horizontal_failed
        else "VERIFIED_MODELED_SCOPE"
        if horizontal_known
        else "INCOMPLETE"
    )
    physical = (
        "BLOCKED"
        if horizontal_failed or result["headroom"]["status"] == "FAILED"
        else "GEOMETRICALLY_TRAVERSABLE"
        if horizontal_known
        and result["headroom"]["status"] == "VERIFIED_MODELED_SCOPE"
        and "headroom_requirement" in spec
        and "clear_width_requirement" in spec
        else "NOT_VERIFIED"
    )
    result["circulation"] = {
        "stairs": replay,
        "graph": graph,
        "geometry_validity": "NOT_VERIFIED",
        "clearance_status": clearance_status,
        "physical_status": physical,
        "technical_compliance": "NOT_EVALUATED",
        "architectural_approval": "NOT_GRANTED",
        "scope": "MODELED_STAIRS_AND_FRESH_006B_INTERFACES_NOT_WHOLE_BUILDING_ACCESS",
    }
    if not spec["stairs_complete"]:
        bad(
            "missing",
            "STAIR_INVENTORY_INCOMPLETE",
            "stairs_complete",
            "Unknown stair inventory does not become complete.",
        )
    for s in result["stairs"]:
        result["schedule"].append(
            {
                k: s[k]
                for k in [
                    "id",
                    "mark",
                    "type",
                    "source_floor",
                    "destination_floor",
                    "source_elevation_m",
                    "destination_elevation_m",
                    "rise_m",
                    "final_elevation_m",
                    "closure_residual_m",
                    "review_status",
                ]
            }
            | {
                "flights": [
                    {
                        k: f[k]
                        for k in [
                            "id",
                            "risers",
                            "ordinary_treads",
                            "riser_height_m",
                            "last_riser_height_m",
                            "riser_height_origin",
                            "tread_depth_m",
                            "width_m",
                            "run_m",
                            "pitch_degrees",
                        ]
                    }
                    for f in s["flights"]
                ],
                "landings": [
                    {
                        k: record_item[k]
                        for k in ["id", "elevation_m", "dimensions_m", "elevation_origin"]
                    }
                    for record_item in s["surfaces"]
                    if record_item["kind"] == "landing"
                ],
                "opening_ids": [
                    o["id"] for o in spec["floor_openings"] if s["id"] in o["stair_ids"]
                ],
                "headroom_status": result["headroom"]["status"],
                "minimum_verified_headroom_m": min(
                    (
                        m["clearance_m"]
                        for m in result["headroom"]["measurements"]
                        if m["stair_id"] == s["id"]
                    ),
                    default=None,
                ),
                "provenance": s["provenance"],
                "unresolved_codes": sorted({i["code"] for i in result["missing_information"]}),
            }
        )
    from vnai.opening_hosts import shape_set

    affected_rooms = {
        e["space_id"]
        for c in valid_connections
        for e in (c["source"], c["destination"])
        if ctx.spaces.get(e["space_id"]) and ctx.spaces[e["space_id"]].kind == "room"
    }
    affected_walls = set()
    affected_openings = set()
    for stair in result["stairs"]:
        footprint = shape_set(stair["footprint"])
        floors = {stair["source_floor"], stair["destination_floor"]}
        for room in source["rooms"]:
            if (
                room["floor_id"] in floors
                and shape_set(room["clear_floor_geometry"]).intersection(footprint).area
                > ctx.area_tolerance
            ):
                affected_rooms.add(room["room_id"])
        for wall in source["sources"]["wall_model"]["walls"]:
            if wall["floor_id"] in floors and shape_set(wall["geometry"]).intersects(footprint):
                affected_walls.add(wall["id"])
        for opening in source["openings"]:
            if opening["floor_id"] in floors and (
                opening["host_wall_id"] in affected_walls
                or opening.get("rough_cut")
                and shape_set(opening["rough_cut"]).intersects(footprint)
            ):
                affected_openings.add(opening["id"])
    result["evidence_impact"] = {
        "affected_room_ids": sorted(affected_rooms),
        "affected_wall_ids": sorted(affected_walls),
        "affected_opening_ids": sorted(affected_openings),
        "affected_floor_ids": sorted(
            {
                f
                for stair in result["stairs"]
                for f in (stair["source_floor"], stair["destination_floor"])
            }
        ),
        "source_candidate_unchanged": True,
        "source_wall_opening_geometry_unchanged": True,
        "preserved": [
            "original_brief",
            "allocation_geometry",
            "original_wall_revision",
            "original_opening_revision",
        ],
        "stale": [
            "source_stair_connectivity",
            "circulation_clearance",
            "candidate_evaluation",
            "architect_approval",
        ],
        "fresh": ["stair_geometry", "floor_openings", "modeled_headroom", "006B_stair_interfaces"],
        "approval_inherited": False,
    }
    result["drafting_status"] = (
        "INVALID_INPUT"
        if "invalid" in flags
        else "CONFLICT"
        if "conflict" in flags
        else "UNSUPPORTED"
        if "unsupported" in flags
        else "INCOMPLETE"
        if "missing" in flags
        else "GENERATED"
    )
    result["geometry_status"] = (
        "INVALID"
        if any(s["geometry_status"] == "INVALID" for s in result["stairs"])
        else "VALID"
        if result["stairs"]
        else "NOT_GENERATED"
    )
    result["circulation"]["geometry_validity"] = result["geometry_status"]
    result["stair_revision_id"] = "SR-" + canonical_digest(
        {
            "source": source["opening_revision_id"],
            "specification": result["specification_digest"],
            "geometry": result["stairs"],
            "headroom": result["headroom"],
        }
    )
    return finish(result)


def validate_drafting(value: Any) -> dict:
    if isinstance(value, dict) and value.get("contract") == "stair-drafting-v1":
        check = new_report("stair-drafting-v1")
        if schema_check(value, "stair-drafting-result.schema.json", check):
            current = draft_stairs(value.get("sources", {}).get("input"))
            if canonical_digest(current) == canonical_digest(value):
                return current
        current = draft_stairs(value.get("sources", {}).get("input"))
        issue(
            current,
            "errors",
            "STAIR_STORED_REPORT_MISMATCH",
            "report",
            "Stored geometry, schedule, source or evidence differs from recomputed input.",
        )
        current["drafting_status"] = "INVALID_INPUT"
        current["geometry_status"] = "INVALID"
        return finish(current)
    return draft_stairs(value)
