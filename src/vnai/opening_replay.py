"""Fresh 006-B graph/path/stair stages over B2 floor obstructions, not stale passes."""

from shapely.geometry import LineString
from shapely.ops import unary_union
from vnai.contracts import finish, issue
from vnai.review_common import near_covers, stage_report
from vnai.circulation import _graph_report
from vnai.clearance import _clearance_report
from vnai.stairs import _stair_report
from vnai.opening_hosts import shape_set


def replay(ctx, model, records, floor_obstructions, spec, problem) -> dict:
    frames = {
        f: unary_union(
            [
                r["_frame"]
                for r in records
                if r.get("cut_accepted")
                and r["floor_id"] == f
                and "_frame" in r
                and not r["type"].endswith("window")
            ]
        )
        for f in ctx.floors
    }
    for r in records:
        if r["type"].endswith("window"):
            r["physical_state"] = "NOT_APPLICABLE_WINDOW"
            r["clearance_status"] = "NOT_APPLICABLE_FLOOR_PASSAGE"
            if r["type"] == "fixed_window":
                r["movement_clearance_status"] = "NOT_APPLICABLE_FIXED_WINDOW"
        if not r.get("cut_accepted") or "_motion" not in r:
            continue
        row = r["_row"]
        window = r["type"].endswith("window")
        target_id = row.get("swing", row.get("slide", {})).get("opens_into")
        target = ctx.spaces.get(target_id)
        if target is None or target_id not in r["space_ids"] or target.kind == "exterior":
            r["_blocked"] = True
            r["issues"].append("MOTION_TARGET_SPACE")
            problem(
                "conflict",
                "MOTION_TARGET_SPACE",
                r["id"],
                "Leaf motion must enter a declared connected interior space.",
            )
            continue
        allowed = target.shape.difference(
            shape_set(
                next(f["wall_footprint"] for f in model["floors"] if f["floor_id"] == r["floor_id"])
            )
        ).union(r["_cut"])
        r["_blocked"] = False
        if not near_covers(allowed, r["_motion"], ctx.tolerance):
            r["_blocked"] = True
            problem(
                "conflict",
                "MOTION_OUTSIDE_CONNECTED_SPACE",
                r["id"],
                "Conservative leaf movement extends beyond its declared target clear space/threshold.",
            )
        if r["_motion"].intersection(frames[r["floor_id"]]).area > ctx.area_tolerance:
            r["_blocked"] = True
            problem(
                "conflict",
                "MOTION_FRAME_COLLISION",
                r["id"],
                "Leaf sweep intersects declared jamb frames.",
            )
        motion_wall = floor_obstructions[r["floor_id"]]
        if window:
            # Evaluate its moving leaf at the opening height, never at floor level.
            motion_wall = shape_set(
                next(f["wall_footprint"] for f in model["floors"] if f["floor_id"] == r["floor_id"])
            ).difference(r["_cut"])
        if r["_motion"].intersection(motion_wall).area > ctx.area_tolerance:
            r["_blocked"] = True
            problem(
                "conflict",
                "MOTION_WALL_COLLISION",
                r["id"],
                "Leaf movement intersects retained wall material.",
            )
        excluded_stairwells = {s for s in r["space_ids"] if ctx.spaces[s].kind == "stairwell"}
        for oid, floor, obstacle in ctx.obstacles:
            if (
                oid not in excluded_stairwells
                and floor == r["floor_id"]
                and r["_motion"].intersection(obstacle).area > ctx.area_tolerance
            ):
                r["_blocked"] = True
                problem(
                    "conflict",
                    "MOTION_FIXED_COLLISION",
                    r["id"],
                    "Conservative movement intersects known fixed geometry "
                    + oid
                    + "; this 2D projection is not a vertical clearance certification.",
                )
        for previous in records:
            if (
                previous["id"] >= r["id"]
                or previous["floor_id"] != r["floor_id"]
                or not previous.get("cut_accepted")
                or "_motion" not in previous
            ):
                continue
            if previous["_motion"].intersection(r["_motion"]).area > ctx.area_tolerance:
                r["_blocked"] = previous["_blocked"] = True
                problem(
                    "conflict",
                    "ADJACENT_LEAF_MOVEMENT_CONFLICT",
                    r["id"],
                    "Declared leaf movement envelopes intersect: " + previous["id"],
                )
        if window:
            continue
        if r.get("operating_state") != "open":
            problem(
                "missing",
                "CLOSED_DOOR_NO_CURRENT_PASSAGE",
                r["id"],
                "A closed leaf does not prove current physical traversal; graph topology is separate.",
            )
    for r in records:
        if r.get("cut_accepted") and "_motion" in r:
            r["movement_clearance_status"] = (
                "BLOCKED"
                if r.get("_blocked")
                else "VERIFIED_KNOWN_2D_PROJECTION"
                if spec.get("fixed_obstacles_complete") is True
                else "UNKNOWN_FIXED_INVENTORY"
            )
    # Existing source nodes are retained; only explicit fresh door thresholds join their usable planes.
    for key, space in ctx.spaces.items():
        if space.shape is None:
            continue
        thresholds = [
            r["_passage"].intersection(space.shape)
            for r in records
            if r.get("cut_accepted")
            and not r["type"].endswith("window")
            and key in r["space_ids"]
            and "_passage" in r
        ]
        space.shape = space.shape.difference(floor_obstructions.get(space.floor, unary_union([])))
        # Intersections above prevent a threshold being credited to an unrelated room.
        if thresholds:
            space.shape = space.shape.union(unary_union(thresholds))
    for floor, obstruction in floor_obstructions.items():
        ctx.obstacles.append(("B2-WALLS-" + floor, floor, obstruction))
    for r in records:
        if r.get("cut_accepted") and not r["type"].endswith("window"):
            for name in ("_frame", "_current_leaf"):
                if name in r:
                    ctx.obstacles.append((r["id"] + name, r["floor_id"], r[name]))
    stage = stage_report(
        ctx,
        "opening-validation-v1",
        opening_results=[],
        space_nodes=[s.record() for s in sorted(ctx.spaces.values(), key=lambda s: s.id)],
        door_information_complete=False,
    )
    adapted = []
    for r in records:
        if r["type"].endswith("window"):
            continue
        row = r.get("_row", {})
        eligible = (
            r.get("cut_accepted", False)
            and r.get("bottom_m") == 0
            and r["confirmation"] == "confirmed"
            and "_passage" in r
        )
        r["graph_eligible"] = eligible
        blocked = r.get("_blocked", False)
        clearance = ctx.clearances.get(row.get("clearance_id"))
        state = "BLOCKED" if blocked else "NOT_VERIFIED"
        if eligible:
            # Clear passage is the declared fully-open design span, independent of current state.
            for name in ("_frame", "_leaf_open"):
                mouth = r.get("clear_mouth_reference", r["clear_reference"])
                mouth_line = LineString([mouth["start"], mouth["end"]])
                if name in r and (
                    r["_passage"].intersection(r[name]).area > ctx.area_tolerance
                    or mouth_line.intersection(r[name]).length > ctx.tolerance
                ):
                    blocked = True
                    problem(
                        "conflict",
                        "DECLARED_CLEAR_PASSAGE_OBSTRUCTED",
                        r["id"],
                        "Declared clear width/offset intersects the actual frame or leaf at its declared state.",
                    )
        if eligible and clearance is not None:
            line = LineString([r["clear_reference"]["start"], r["clear_reference"]["end"]])
            if not near_covers(clearance, line, ctx.tolerance):
                blocked = True
                problem(
                    "conflict",
                    "CLEARANCE_MISSES_DRAFTED_PASSAGE",
                    r["id"],
                    "Fresh clearance envelope must contain the actual clear portal interval.",
                )
            spaces = [ctx.spaces[s] for s in r["space_ids"]]
            if any(s.shape is None for s in spaces):
                problem(
                    "missing",
                    "EXTERIOR_APPROACH_REQUIRED",
                    r["id"],
                    "Exterior clearance needs an explicitly supplied approach polygon.",
                )
            elif not near_covers(unary_union([s.shape for s in spaces]), clearance, ctx.tolerance):
                blocked = True
                problem(
                    "conflict",
                    "CLEARANCE_OUTSIDE_DRAFTED_SPACES",
                    r["id"],
                    "Fresh clearance extends outside connected clear rooms/actual threshold.",
                )
            for oid, floor, obstacle in ctx.obstacles:
                if (
                    floor == r["floor_id"]
                    and not (oid in r["space_ids"] and ctx.spaces[oid].kind == "stairwell")
                    and oid not in (r["id"] + "_current_leaf",)
                    and clearance.intersection(obstacle).area > ctx.area_tolerance
                ):
                    blocked = True
                    problem(
                        "conflict",
                        "DRAFTED_CLEARANCE_COLLISION",
                        r["id"],
                        "Opening clearance intersects retained wall/frame/fixed geometry " + oid,
                    )
            if (
                not blocked
                and all(s.shape is not None for s in spaces)
                and spec.get("fixed_obstacles_complete") is True
                and model["specification_status"] == "CONFIRMED"
                and r.get("operating_state") == "open"
            ):
                state = "GEOMETRICALLY_TRAVERSABLE"
        elif eligible:
            problem(
                "missing",
                "FRESH_OPENING_CLEARANCE_REQUIRED",
                r["id"],
                "Old boundary clearance is stale; supply a fresh wall-aware clearance region.",
            )
        if blocked:
            state = "BLOCKED"
        r["physical_state"] = state
        r["clearance_status"] = (
            "VERIFIED_SUPPLIED_2D_SCOPE"
            if state == "GEOMETRICALLY_TRAVERSABLE"
            else "BLOCKED"
            if state == "BLOCKED"
            else "UNKNOWN"
        )
        seg = r.get("clear_reference", r.get("reference"))
        stage["opening_results"].append(
            {
                "id": r["id"],
                "floor_id": r["floor_id"],
                "space_ids": r["space_ids"],
                "provenance": r["provenance"],
                "confirmation": r["confirmation"],
                "graph_eligible": eligible,
                "geometry_status": r["geometry_status"],
                "physical_state": state,
                "clear_width_m": r.get("clear_width_m"),
                "segment_m": [seg["start"], seg["end"]] if seg else None,
                "swing_polygon_m": None,
            }
        )
        if eligible:
            wall = r["_wall"]
            adapted.append(
                {
                    "id": r["id"],
                    "floor_id": r["floor_id"],
                    "start": [v / ctx.scale for v in seg["start"]],
                    "end": [v / ctx.scale for v in seg["end"]],
                    "space_ids": r["space_ids"],
                    "host": {
                        "start": [v / ctx.scale for v in wall["reference"]["start"]],
                        "end": [v / ctx.scale for v in wall["reference"]["end"]],
                    },
                    "clear_width": r["clear_width_m"] / ctx.scale,
                }
            )
    for entry in stage["opening_results"]:
        if entry["physical_state"] == "BLOCKED":
            issue(
                stage,
                "errors",
                "DRAFTED_OPENING_BLOCKED",
                entry["id"],
                "Known wall-aware opening/motion/clearance conflict; see the parent drafting diagnostics.",
            )
        elif entry["physical_state"] != "GEOMETRICALLY_TRAVERSABLE":
            issue(
                stage,
                "missing_information",
                "DRAFTED_OPENING_NOT_VERIFIED",
                entry["id"],
                "Required host, dimensions, state, inventory or clearance evidence is unresolved.",
            )
    finish(stage)
    ctx.spec["openings"] = adapted
    stage["door_information_complete"] = spec["openings_complete"] and all(
        r["graph_eligible"] for r in stage["opening_results"]
    )
    if not spec["openings_complete"]:
        problem(
            "missing",
            "OPENING_INVENTORY_INCOMPLETE",
            "specification",
            "Opening inventory is not declared complete.",
        )
    if stage["opening_results"] and spec.get("fixed_obstacles_complete") is not True:
        problem(
            "missing",
            "FIXED_INVENTORY_INCOMPLETE",
            "specification",
            "Unknown fixed obstacles cannot become collision-free clearance.",
        )
    stairs = _stair_report(ctx, stage)
    graph = _graph_report(ctx, stage, stairs)
    closed_ids = {
        r["id"]
        for r in records
        if r.get("operating_state") == "closed" and not r["type"].endswith("window")
    }
    eligible_ids = {
        r["id"]
        for r in stage["opening_results"]
        if r["graph_eligible"] and r["id"] not in closed_ids
    }
    deferred_paths = [
        p["id"] for p in ctx.spec.get("passages", []) if not set(p["opening_ids"]) <= eligible_ids
    ]
    ctx.spec["passages"] = [
        p for p in ctx.spec.get("passages", []) if p["id"] not in deferred_paths
    ]
    for path_id in deferred_paths:
        problem(
            "missing",
            "DRAFTED_ROUTE_DEPENDENCY_UNRESOLVED",
            path_id,
            "Supplied path cannot be replayed until its explicit wall-hosted opening references are valid; no route pass is inherited.",
        )
    paths = _clearance_report(ctx, stage, stairs, graph)
    paths["deferred_path_ids"] = deferred_paths
    for label, report in (("stairs", stairs), ("graph", graph), ("paths", paths)):
        for item in report["errors"]:
            problem("conflict", item["code"], label + "." + item["path"], item["message"])
        for item in report["missing_information"]:
            problem("missing", item["code"], label + "." + item["path"], item["message"])
    return {
        "opening_validity": finish(stage),
        "graph": graph,
        "clearance": paths,
        "stairs": stairs,
        "technical_compliance": "NOT_EVALUATED",
        "architectural_approval": "NOT_GRANTED",
        "scope": "SUPPLIED_WALL_AWARE_2D_DOORS_PATHS_AND_STAIR_INTERFACES_ONLY",
        "windows_create_edges": False,
        "source_boundary_evidence_reused_as_pass": False,
    }
