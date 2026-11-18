"""Envelope and endpoint checks for declared stairs, never full staircase design."""

from typing import Any
from shapely.geometry import Point, LineString

from vnai.contracts import finish, issue
from vnai.review_common import ReviewContext, build_context, stage_report, valid_frame, near_covers
from vnai.openings import _opening_report


def _stair_report(ctx: ReviewContext, openings: dict) -> dict:
    result = stage_report(
        ctx,
        "stair-validation-v1",
        stair_results=[],
        stair_information_complete=False,
        technical_stair_design="NOT_EVALUATED",
    )
    if ctx.report["errors"] or ctx.geometry_status != "VALID":
        return result
    opening_map = {row["id"]: row for row in openings["opening_results"]}
    elevations = {f["id"]: f.get("elevation_m") for f in ctx.geometry["floors"]}
    for floor in ctx.geometry.get("zoning", {}).get("floors", []):
        if elevations.get(floor["id"]) is None and "elevation" in floor:
            meta = floor["elevation"]
            elevations[floor["id"]] = meta["value"] * (1 if meta["unit"] == "m" else 0.001)
    ids = set()
    for row in ctx.spec.get("stairs", []):
        path = "stairs." + row["id"]
        before_errors, before_missing = len(result["errors"]), len(result["missing_information"])
        if row["id"] in ids:
            issue(result, "errors", "DUPLICATE_STAIR_ID", path, "Stair IDs must be unique.")
        if row["id"] in ids:
            for previous in result["stair_results"]:
                if previous["id"] == row["id"]:
                    previous["graph_eligible"] = False
        ids.add(row["id"])
        valid_frame(ctx, row, result, path)
        source, destination = row["source"], row["destination"]
        if source["floor_id"] == destination["floor_id"]:
            issue(
                result,
                "errors",
                "STAIR_SAME_FLOOR",
                path,
                "Vertical connections need distinct source/destination floors.",
            )
        checked = []
        for endpoint in (source, destination):
            floor, stair_id, space_id = (
                endpoint["floor_id"],
                endpoint["stairwell_id"],
                endpoint["space_id"],
            )
            stair = ctx.spaces.get(stair_id)
            space = ctx.spaces.get(space_id)
            valid = True
            if (
                floor not in ctx.floors
                or not stair
                or stair.kind != "stairwell"
                or stair.floor != floor
            ):
                issue(
                    result,
                    "errors",
                    "STAIR_ENVELOPE_REFERENCE",
                    path,
                    "Stair endpoint must reference its floor's supplied stairwell reservation.",
                )
                valid = False
            if not space or space.kind not in {"room", "circulation"} or space.floor != floor:
                issue(
                    result,
                    "errors",
                    "STAIR_SPACE_REFERENCE",
                    path,
                    "Entry/exit must connect to a real same-floor room/circulation node.",
                )
                valid = False
            if valid and not near_covers(ctx.envelope(floor), stair.shape, ctx.tolerance):
                issue(
                    result,
                    "errors",
                    "STAIR_OUTSIDE_ENVELOPE",
                    path,
                    "Stair envelope lies outside its permitted floor region.",
                )
                valid = False
            if valid:
                for oid, obstacle_floor, obstacle in ctx.obstacles:
                    if (
                        obstacle_floor == floor
                        and oid != stair_id
                        and stair.shape.intersection(obstacle).area > ctx.area_tolerance
                    ):
                        issue(
                            result,
                            "errors",
                            "STAIR_FIXED_COLLISION",
                            path,
                            f"Supplied stair envelope intersects fixed geometry {oid}.",
                        )
                        valid = False
            if "point" not in endpoint or "opening_id" not in endpoint:
                issue(
                    result,
                    "missing_information",
                    "STAIR_ENTRY_EXIT_REQUIRED",
                    path,
                    "Entry/exit point and verified opening reference are required; envelope fit alone is insufficient.",
                )
                valid = False
            elif valid:
                point = Point(ctx.xy(endpoint["point"]))
                opening = opening_map.get(endpoint["opening_id"])
                if (
                    not opening
                    or not opening["graph_eligible"]
                    or opening["floor_id"] != floor
                    or set(opening["space_ids"]) != {space_id, stair_id}
                ):
                    issue(
                        result,
                        "errors",
                        "STAIR_OPENING_REFERENCE",
                        path,
                        "Stair entry/exit needs an actual validated opening to its space.",
                    )
                    valid = False
                else:
                    line = LineString(opening["segment_m"])
                    if (
                        point.distance(line) > ctx.tolerance
                        or point.distance(stair.shape.boundary) > ctx.tolerance
                        or point.distance(space.shape.boundary) > ctx.tolerance
                    ):
                        issue(
                            result,
                            "errors",
                            "STAIR_CONNECTION_POINT",
                            path,
                            "Stair connection point must lie on its opening and both boundaries.",
                        )
                        valid = False
                if "landing_id" in endpoint:
                    landing = ctx.spaces.get(endpoint["landing_id"])
                    if (
                        not landing
                        or landing.kind != "circulation"
                        or landing.floor != floor
                        or landing.id != space_id
                        or not near_covers(landing.shape, point, ctx.tolerance)
                    ):
                        issue(
                            result,
                            "errors",
                            "STAIR_LANDING_REFERENCE",
                            path,
                            "Landing must reference a same-floor circulation region containing the endpoint.",
                        )
                        valid = False
            checked.append(valid)
        rise = None
        a, b = elevations.get(source["floor_id"]), elevations.get(destination["floor_id"])
        if a is not None and b is not None:
            rise = b - a
            if (row["direction"] == "up" and rise <= 0) or (
                row["direction"] == "down" and rise >= 0
            ):
                issue(
                    result,
                    "errors",
                    "STAIR_DIRECTION",
                    path,
                    "Declared direction contradicts supplied floor elevations.",
                )
        else:
            issue(
                result,
                "missing_information",
                "STAIR_ELEVATIONS_REQUIRED",
                path,
                "Rise/direction cannot be verified without supplied floor elevations.",
            )
        alignment = "NOT_REQUIRED"
        if row["alignment_required"]:
            first, second = (
                ctx.spaces.get(source["stairwell_id"]),
                ctx.spaces.get(destination["stairwell_id"]),
            )
            if first and second:
                if first.shape.equals(second.shape) or (
                    ctx.tolerance > 0
                    and first.shape.hausdorff_distance(second.shape) <= ctx.tolerance
                ):
                    alignment = "VALID"
                else:
                    alignment = "INVALID"
                    issue(
                        result,
                        "errors",
                        "STAIR_ALIGNMENT",
                        path,
                        "Stairwell footprints do not align within the declared boundary tolerance.",
                    )
        if row["confirmation"] != "confirmed":
            issue(
                result,
                "missing_information",
                "STAIR_UNCONFIRMED",
                path,
                "Proposed stair connection cannot create a verified graph edge.",
            )
        if row["review_status"] != "reviewed":
            issue(
                result,
                "missing_information",
                "STAIR_REVIEW_REQUIRED",
                path,
                "Stair-envelope review is pending; it is not approval of staircase technical design.",
            )
        result["stair_results"].append(
            {
                "id": row["id"],
                "provenance": row["provenance"],
                "confirmation": row["confirmation"],
                "review_status": row["review_status"],
                "source_floor": source["floor_id"],
                "destination_floor": destination["floor_id"],
                "space_ids": [source["stairwell_id"], destination["stairwell_id"]],
                "entry_exit_valid": checked,
                "rise_m": rise,
                "alignment_status": alignment,
                "graph_eligible": all(checked)
                and len(result["errors"]) == before_errors
                and row["confirmation"] == "confirmed",
                "physical_state": "NOT_VERIFIED",
                "details_complete": len(result["missing_information"]) == before_missing,
            }
        )
    if len(ctx.floors) > 1 and ctx.spec.get("stairs_complete") is not True:
        issue(
            result,
            "missing_information",
            "STAIR_INFORMATION_INCOMPLETE",
            "stairs_complete",
            "Supply stair connection information, or explicitly declare the inventory complete.",
        )
    result["stair_information_complete"] = (
        (len(ctx.floors) == 1 and not ctx.spec.get("stairs"))
        or ctx.spec.get("stairs_complete") is True
        and all(r["graph_eligible"] and r["details_complete"] for r in result["stair_results"])
    )
    return finish(result)


def validate_stairs(value: Any) -> dict:
    ctx = build_context(value)
    return _stair_report(ctx, _opening_report(ctx))
