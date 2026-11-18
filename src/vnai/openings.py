"""Explicit boundary-hosted openings; adjacency never creates a door."""

from math import atan2, cos, sin, hypot, pi
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from vnai.contracts import finish, issue
from vnai.review_common import ReviewContext, build_context, near_covers, stage_report, valid_frame


def swing_sector(
    start: tuple[float, float], end: tuple[float, float], hinge: str, rotation: str
) -> Polygon:
    """Conservative tangent enclosure of a supplied 90-degree zero-thickness leaf sweep."""
    pivot, tip = (start, end) if hinge == "start" else (end, start)
    radius = hypot(tip[0] - pivot[0], tip[1] - pivot[1])
    base = atan2(tip[1] - pivot[1], tip[0] - pivot[0])
    delta = (pi / 2 / 32) * (1 if rotation == "ccw" else -1)
    points = [pivot, tip]
    for index in range(32):
        middle = base + (index + 0.5) * delta
        tangent_r = radius / cos(abs(delta) / 2)
        points.append((pivot[0] + tangent_r * cos(middle), pivot[1] + tangent_r * sin(middle)))
        angle = base + (index + 1) * delta
        if index == 31:
            vx, vy = tip[0] - pivot[0], tip[1] - pivot[1]
            points.append(
                (pivot[0] - vy, pivot[1] + vx)
                if rotation == "ccw"
                else (pivot[0] + vy, pivot[1] - vx)
            )
        else:
            points.append((pivot[0] + radius * cos(angle), pivot[1] + radius * sin(angle)))
    return Polygon(points)


def _opening_report(ctx: ReviewContext) -> dict:
    result = stage_report(
        ctx,
        "opening-validation-v1",
        opening_results=[],
        space_nodes=[s.record() for s in sorted(ctx.spaces.values(), key=lambda s: s.id)],
        door_information_complete=False,
    )
    if ctx.report["errors"] or ctx.geometry_status != "VALID":
        return result
    confirmed = True
    identifiers = set()
    lines = {}
    raw_swings = {}
    for row in ctx.spec.get("openings", []):
        path, key = "openings." + row["id"], row["id"]
        before = len(result["errors"])
        if key in identifiers:
            issue(result, "errors", "DUPLICATE_OPENING_ID", path, "Opening IDs must be unique.")
            for previous in result["opening_results"]:
                if previous["id"] == key:
                    previous["graph_eligible"] = False
        identifiers.add(key)
        valid_frame(ctx, row, result, path)
        if row["floor_id"] not in ctx.floors:
            issue(result, "errors", "OPENING_FLOOR", path, "Unknown opening floor.")
        spaces = [ctx.spaces.get(space) for space in row["space_ids"]]
        if any(s is None for s in spaces):
            issue(result, "errors", "OPENING_SPACE", path, "Opening references an unknown space.")
        elif any(s.floor != row["floor_id"] for s in spaces):
            issue(
                result,
                "errors",
                "OPENING_SPACE_FLOOR",
                path,
                "An opening cannot connect different floor planes.",
            )
        exterior_count = sum(s is not None and s.kind == "exterior" for s in spaces)
        if exterior_count != (1 if row["kind"] == "entrance" else 0):
            issue(
                result,
                "errors",
                "OPENING_KIND",
                path,
                "Entrances connect one exterior; interior openings connect no exterior.",
            )
        start, end = ctx.xy(row["start"]), ctx.xy(row["end"])
        line = LineString((start, end))
        host = LineString((ctx.xy(row["host"]["start"]), ctx.xy(row["host"]["end"])))
        width = row["clear_width"] * ctx.scale
        if line.length <= 0 or host.length <= 0:
            issue(
                result,
                "errors",
                "ZERO_LENGTH_OPENING",
                path,
                "Opening and host segment need positive lengths.",
            )
        elif width > line.length + ctx.tolerance:
            issue(
                result,
                "errors",
                "OPENING_WIDTH",
                path,
                "Clear opening width exceeds its supplied geometric span.",
            )
        if line.length > 0 and host.length > 0 and not near_covers(host, line, ctx.tolerance):
            issue(
                result,
                "errors",
                "OPENING_OUTSIDE_HOST",
                path,
                "Opening extends beyond the host segment.",
            )
        if all(s is not None for s in spaces):
            for space in spaces:
                if space.kind == "exterior":
                    boundary = ctx.shapes.get(space.geometry_id)
                    compatible = (
                        LineString(boundary.exterior.coords) if boundary is not None else None
                    )
                else:
                    compatible = space.shape.boundary
                if compatible is None or not near_covers(compatible, host, ctx.tolerance):
                    issue(
                        result,
                        "errors",
                        "HOST_BOUNDARY_MISMATCH",
                        path,
                        f"Host is not on the compatible boundary of {space.id}.",
                    )
                elif not compatible.covers(host):
                    issue(
                        result,
                        "warnings",
                        "HOST_WITHIN_BOUNDARY_TOLERANCE",
                        path,
                        "Host is within declared boundary tolerance; no geometry was snapped.",
                    )
        valid_boundary = len(result["errors"]) == before
        if row["confirmation"] != "confirmed":
            confirmed = False
            issue(
                result,
                "missing_information",
                "OPENING_UNCONFIRMED",
                path,
                "Proposed opening cannot establish a verified graph edge.",
            )
        detail = {
            "id": key,
            "floor_id": row["floor_id"],
            "space_ids": row["space_ids"],
            "provenance": row["provenance"],
            "confirmation": row["confirmation"],
            "graph_eligible": valid_boundary and row["confirmation"] == "confirmed",
            "geometry_status": "VALID" if valid_boundary else "INVALID",
            "physical_state": "NOT_VERIFIED",
            "clear_width_m": width,
            "segment_m": [list(start), list(end)],
            "swing_polygon_m": None,
        }
        result["opening_results"].append(detail)
        lines[key] = line
        if not valid_boundary:
            continue
        physical_before = len(result["errors"])
        excluded_stairwells = {s.id for s in spaces if s.kind == "stairwell"}
        obstacles = [
            (oid, shape)
            for oid, floor, shape in ctx.obstacles
            if floor == row["floor_id"] and oid not in excluded_stairwells
        ]
        for oid, shape in obstacles:
            if line.intersection(shape).length > ctx.tolerance or shape.contains(
                line.interpolate(0.5, normalized=True)
            ):
                issue(
                    result,
                    "errors",
                    "OPENING_FIXED_COLLISION",
                    path,
                    f"Opening intersects fixed geometry {oid}.",
                )
        motion_known = row["door_type"] == "open_passage"
        if row["door_type"] == "hinged":
            if "swing" not in row:
                issue(
                    result,
                    "missing_information",
                    "SWING_GEOMETRY_REQUIRED",
                    path,
                    "Supply hinge and swing direction; no swing is inferred.",
                )
            else:
                swing = row["swing"]
                target = ctx.spaces.get(swing["opens_into"])
                if target is None or target.id not in row["space_ids"] or target.kind == "exterior":
                    issue(
                        result,
                        "errors",
                        "SWING_SPACE",
                        path,
                        "Hinged swing must enter one connected interior space.",
                    )
                else:
                    sector = swing_sector(start, end, swing["hinge"], swing["rotation"])
                    raw_swings[key] = sector
                    # Derived display coordinates only; collision decisions use the raw conservative sector.
                    detail["swing_polygon_m"] = [
                        [round(x, 12), round(y, 12)] for x, y in sector.exterior.coords
                    ]
                    motion_known = True
                    if not near_covers(target.shape, sector, ctx.tolerance):
                        issue(
                            result,
                            "errors",
                            "SWING_OUTSIDE_SPACE",
                            path,
                            "The supplied hinge/direction sweeps outside its connected space.",
                        )
                    for oid, shape in obstacles:
                        if sector.intersection(shape).area > ctx.area_tolerance:
                            issue(
                                result,
                                "errors",
                                "SWING_FIXED_COLLISION",
                                path,
                                f"Conservative swing envelope intersects {oid}.",
                            )
        elif "swing" in row:
            issue(
                result,
                "errors",
                "UNEXPECTED_SWING",
                path,
                "Only hinged doors have hinge/swing metadata.",
            )
        if row["door_type"] != "sliding" and "sliding_envelope_id" in row:
            issue(
                result,
                "errors",
                "UNEXPECTED_SLIDING_ENVELOPE",
                path,
                "Sliding motion metadata is only supported for sliding doors.",
            )
        if row["door_type"] == "sliding":
            sliding = ctx.clearances.get(row.get("sliding_envelope_id", ""))
            if sliding is None:
                issue(
                    result,
                    "missing_information" if "sliding_envelope_id" not in row else "errors",
                    "SLIDING_ENVELOPE_REQUIRED",
                    path,
                    "Sliding motion needs an explicitly supplied envelope.",
                )
            else:
                if ctx.rows[row["sliding_envelope_id"]].get("floor_id") != row["floor_id"]:
                    issue(
                        result,
                        "errors",
                        "SLIDING_ENVELOPE_FLOOR",
                        path,
                        "Sliding envelope and opening belong to different floors.",
                    )
                connected = unary_union([s.shape for s in spaces if s.shape is not None])
                if not near_covers(connected, sliding, ctx.tolerance) or not near_covers(
                    sliding, line, ctx.tolerance
                ):
                    issue(
                        result,
                        "errors",
                        "SLIDING_ENVELOPE",
                        path,
                        "Sliding motion envelope is inconsistent with the opening/spaces.",
                    )
                for oid, shape in obstacles:
                    if sliding.intersection(shape).area > ctx.area_tolerance:
                        issue(
                            result,
                            "errors",
                            "SLIDING_FIXED_COLLISION",
                            path,
                            f"Sliding envelope intersects {oid}.",
                        )
                motion_known = True
        clearance = ctx.clearances.get(row.get("clearance_id", ""))
        clearance_known = clearance is not None
        if clearance is None:
            issue(
                result,
                "errors" if "clearance_id" in row else "missing_information",
                "OPENING_CLEARANCE_REQUIRED",
                path,
                "Supply an opening clearance envelope for a bounded clearance assessment.",
            )
        else:
            clearance_row = ctx.rows[row["clearance_id"]]
            if clearance_row.get("floor_id") != row["floor_id"]:
                issue(
                    result,
                    "errors",
                    "CLEARANCE_FLOOR",
                    path,
                    "Clearance and opening belong to different floors.",
                )
            if not near_covers(clearance, line, ctx.tolerance):
                issue(
                    result,
                    "errors",
                    "CLEARANCE_MISSES_OPENING",
                    path,
                    "Clearance envelope must contain the opening span.",
                )
            if any(s.shape is None for s in spaces):
                clearance_known = False
                issue(
                    result,
                    "missing_information",
                    "EXTERIOR_APPROACH_REQUIRED",
                    path,
                    "An exterior approach polygon is needed to assess outside clearance.",
                )
            elif not near_covers(unary_union([s.shape for s in spaces]), clearance, ctx.tolerance):
                issue(
                    result,
                    "errors",
                    "CLEARANCE_OUTSIDE_SPACES",
                    path,
                    "Opening clearance lies outside its declared connected spaces.",
                )
            for oid, shape in obstacles:
                if clearance.intersection(shape).area > ctx.area_tolerance:
                    issue(
                        result,
                        "errors",
                        "CLEARANCE_FIXED_COLLISION",
                        path,
                        f"Opening clearance intersects {oid}.",
                    )
        physical_errors = result["errors"][physical_before:]
        known_conflicts = {
            "OPENING_FIXED_COLLISION",
            "SWING_OUTSIDE_SPACE",
            "SWING_FIXED_COLLISION",
            "SLIDING_ENVELOPE",
            "SLIDING_FIXED_COLLISION",
            "CLEARANCE_MISSES_OPENING",
            "CLEARANCE_OUTSIDE_SPACES",
            "CLEARANCE_FIXED_COLLISION",
        }
        if any(e["code"] in known_conflicts for e in physical_errors):
            detail["physical_state"] = "BLOCKED"
        elif physical_errors:
            detail["physical_state"] = "NOT_VERIFIED"
        elif (
            motion_known
            and clearance_known
            and ctx.spec.get("fixed_obstacles_complete") is True
            and row["confirmation"] == "confirmed"
        ):
            detail["physical_state"] = "GEOMETRICALLY_TRAVERSABLE"
    for index, left in enumerate(result["opening_results"]):
        for right in result["opening_results"][:index]:
            if (
                left["floor_id"] == right["floor_id"]
                and lines[left["id"]].intersection(lines[right["id"]]).length > ctx.tolerance
            ):
                issue(
                    result,
                    "errors",
                    "OVERLAPPING_OPENINGS",
                    "openings",
                    f"Openings {left['id']} and {right['id']} overlap.",
                )
                left["graph_eligible"] = right["graph_eligible"] = False
    for index, left in enumerate(result["opening_results"]):
        for right in result["opening_results"][:index]:
            if (
                left["floor_id"] != right["floor_id"]
                or not left["swing_polygon_m"]
                or not right["swing_polygon_m"]
            ):
                continue
            if (
                raw_swings[left["id"]].intersection(raw_swings[right["id"]]).area
                > ctx.area_tolerance
            ):
                issue(
                    result,
                    "errors",
                    "SWING_ENVELOPE_CONFLICT",
                    "openings",
                    f"Known swing envelopes {left['id']} and {right['id']} conflict.",
                )
                left["physical_state"] = right["physical_state"] = "BLOCKED"
    if ctx.spec.get("openings_complete") is not True:
        issue(
            result,
            "missing_information",
            "OPENING_INFORMATION_INCOMPLETE",
            "openings_complete",
            "Opening inventory is unknown or incomplete; absence is not a verified blockage.",
        )
    if ctx.spec.get("openings") and ctx.spec.get("fixed_obstacles_complete") is not True:
        issue(
            result,
            "missing_information",
            "FIXED_OBSTACLE_INFORMATION_REQUIRED",
            "fixed_obstacles_complete",
            "Unknown fixed geometry cannot become a clearance PASS.",
        )
    result["door_information_complete"] = (
        ctx.spec.get("openings_complete") is True
        and confirmed
        and all(r["geometry_status"] == "VALID" for r in result["opening_results"])
    )
    return finish(result)


def validate_openings(value: Any) -> dict:
    return _opening_report(build_context(value))
