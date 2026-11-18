"""Bounded supplied-path clearance checks, with explicit unknown and blocked states."""

from shapely.geometry import LineString, Point

from vnai.contracts import finish, issue
from vnai.review_common import ReviewContext, near_covers, stage_report, valid_frame
from vnai.circulation import reachable


def _clearance_report(ctx: ReviewContext, openings: dict, stairs: dict, graph: dict) -> dict:
    result = stage_report(
        ctx,
        "circulation-clearance-v1",
        physical_status="NOT_VERIFIED",
        scope="SUPPLIED_PLANAR_PATHS_ONLY",
        passage_results=[],
        room_physical_access={},
        technical_compliance="NOT_EVALUATED",
    )
    if ctx.report["errors"] or ctx.geometry_status != "VALID":
        return result
    opened = {r["id"]: r for r in openings["opening_results"]}
    network: dict[str, set[str]] = {}
    interiors = set()
    exterior_origins = set()
    ids = set()
    known_conflicts = {
        "PASSAGE_WIDTH_OUTSIDE_SPACE",
        "PASSAGE_FIXED_COLLISION",
        "PASSAGE_OPENING_WIDTH",
    }

    def portal(space, opening):
        key = (space, opening)
        network.setdefault(key, set())
        return key

    for opening in opened.values():
        if opening["graph_eligible"] and opening["physical_state"] == "GEOMETRICALLY_TRAVERSABLE":
            a, b = (portal(space, opening["id"]) for space in opening["space_ids"])
            network[a].add(b)
            network[b].add(a)
    for passage in ctx.spec.get("passages", []):
        key, space = passage["id"], ctx.spaces.get(passage["space_id"])
        path = "passages." + key
        before = len(result["errors"])
        if key in ids:
            issue(result, "errors", "DUPLICATE_PASSAGE_ID", path, "Passage IDs must be unique.")
        ids.add(key)
        valid_frame(ctx, passage, result, path)
        if not space or space.kind == "stairwell" or space.floor != passage["floor_id"]:
            issue(
                result,
                "errors",
                "PASSAGE_SPACE",
                path,
                "Planar routes need an actual same-floor room/circulation/exterior-approach node.",
            )
            continue
        if space.shape is None:
            issue(
                result,
                "missing_information",
                "PASSAGE_SPACE_GEOMETRY_REQUIRED",
                path,
                "Supply the exterior approach polygon.",
            )
            continue
        line = LineString([ctx.xy(p) for p in passage["path"]])
        width = passage["width"] * ctx.scale
        if line.length <= 0 or not line.is_simple:
            issue(
                result,
                "errors",
                "PASSAGE_PATH",
                path,
                "Supply a positive-length simple path; no route is inferred.",
            )
            continue
        region = line.buffer(width / 2, cap_style=2, join_style=2)
        if not near_covers(space.shape, region, ctx.tolerance):
            issue(
                result,
                "errors",
                "PASSAGE_WIDTH_OUTSIDE_SPACE",
                path,
                "Declared path-width envelope extends outside its space.",
            )
        for oid, floor, obstacle in ctx.obstacles:
            if floor == space.floor and region.intersection(obstacle).area > ctx.area_tolerance:
                issue(
                    result,
                    "errors",
                    "PASSAGE_FIXED_COLLISION",
                    path,
                    f"Declared walking envelope intersects fixed geometry {oid}.",
                )
        references = [opened.get(k) for k in passage["opening_ids"]]
        if any(
            r is None or not r["graph_eligible"] or space.id not in r["space_ids"]
            for r in references
        ):
            issue(
                result,
                "errors",
                "PASSAGE_OPENING_REFERENCE",
                path,
                "Passage endpoints must reference actual verified openings incident to this node.",
            )
        else:
            centers = [
                LineString(r["segment_m"]).interpolate(0.5, normalized=True) for r in references
            ]
            first, last = Point(line.coords[0]), Point(line.coords[-1])
            if len(centers) == 1:
                matches = (
                    first.distance(centers[0]) <= ctx.tolerance and space.shape.contains(last)
                ) or (last.distance(centers[0]) <= ctx.tolerance and space.shape.contains(first))
            else:
                matches = (
                    first.distance(centers[0]) <= ctx.tolerance
                    and last.distance(centers[1]) <= ctx.tolerance
                ) or (
                    last.distance(centers[0]) <= ctx.tolerance
                    and first.distance(centers[1]) <= ctx.tolerance
                )
            if not matches:
                issue(
                    result,
                    "errors",
                    "PASSAGE_ENDPOINT",
                    path,
                    "Route must connect its declared opening midpoints, or one midpoint and an explicit interior destination.",
                )
            if any(width > r["clear_width_m"] + ctx.tolerance for r in references):
                issue(
                    result,
                    "errors",
                    "PASSAGE_OPENING_WIDTH",
                    path,
                    "Declared passage width exceeds an incident opening's supplied clear width.",
                )
        confirmed = passage["confirmation"] == "confirmed"
        if not confirmed:
            issue(
                result,
                "missing_information",
                "PASSAGE_UNCONFIRMED",
                path,
                "Proposed route cannot demonstrate bounded walking clearance.",
            )
        valid = len(result["errors"]) == before and confirmed
        result["passage_results"].append(
            {
                "id": key,
                "provenance": passage["provenance"],
                "confirmation": passage["confirmation"],
                "space_id": space.id,
                "width_m": width,
                "status": "GEOMETRICALLY_TRAVERSABLE"
                if valid
                else "BLOCKED"
                if any(e["code"] in known_conflicts for e in result["errors"][before:])
                else "NOT_VERIFIED",
            }
        )
        if valid:
            ports = [portal(space.id, oid) for oid in passage["opening_ids"]]
            if space.kind == "room":
                interiors.update(ports)
            if len(ports) == 2:
                network[ports[0]].add(ports[1])
                network[ports[1]].add(ports[0])
            elif space.kind == "room":
                interiors.add(ports[0])
            elif space.kind == "exterior":
                exterior_origins.add(ports[0])
    known_obstacles = ctx.spec.get("fixed_obstacles_complete") is True
    if not known_obstacles:
        issue(
            result,
            "missing_information",
            "FIXED_OBSTACLE_INFORMATION_REQUIRED",
            "fixed_obstacles_complete",
            "Unknown fixed geometry cannot become a clearance PASS.",
        )
    arrived = reachable(network, sorted(exterior_origins)) if known_obstacles else set()
    for key, space in sorted(ctx.spaces.items()):
        if space.kind != "room":
            continue
        paths = {p for p in interiors if p[0] == key}
        verified = bool(paths & arrived)
        result["room_physical_access"][key] = (
            "GEOMETRICALLY_TRAVERSABLE" if verified else "NOT_VERIFIED"
        )
        if not verified:
            issue(
                result,
                "missing_information",
                "WALKING_ROUTE_NOT_VERIFIED",
                key,
                "No complete chain of verified local opening clearances and supplied width-checked routes demonstrates access to this room.",
            )
    blocked = (
        any(r["physical_state"] == "BLOCKED" for r in openings["opening_results"])
        or any(e["code"] in known_conflicts for e in result["errors"])
        or graph["graph_status"] == "BLOCKED"
    )
    if blocked:
        result["physical_status"] = "BLOCKED"
        if not result["errors"]:
            issue(
                result,
                "errors",
                "KNOWN_CIRCULATION_BLOCKAGE",
                "clearance",
                "Known opening/graph blockage prevents a traversable circulation claim.",
            )
    elif (
        graph["graph_status"] == "GRAPH_CONNECTED"
        and result["room_physical_access"]
        and all(v == "GEOMETRICALLY_TRAVERSABLE" for v in result["room_physical_access"].values())
    ):
        result["physical_status"] = "GEOMETRICALLY_TRAVERSABLE"
    if (graph["errors"] or result["errors"]) and result["physical_status"] != "BLOCKED":
        result["physical_status"] = "NOT_VERIFIED"
        issue(
            result,
            "missing_information",
            "CONNECTION_CONFLICTS_UNRESOLVED",
            "clearance",
            "Resolve invalid connection information before claiming full bounded-route verification.",
        )
    if any(r["graph_eligible"] for r in stairs["stair_results"]):
        issue(
            result,
            "missing_information",
            "STAIR_WALKING_GEOMETRY_NOT_EVALUATED",
            "stairs",
            "Envelope/entry connectivity does not establish treads, risers, headroom or physical stair traversal.",
        )
        if result["physical_status"] != "BLOCKED":
            result["physical_status"] = "NOT_VERIFIED"
    return finish(result)
