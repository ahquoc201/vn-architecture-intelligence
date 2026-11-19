"""Resolve explicit drafting references against immutable B1 walls and 006-B spaces."""

import math
from shapely.geometry import LineString, Point, Polygon
from vnai.review_common import near_covers
from vnai.wall_topology import polygon


def shape_set(value: dict):
    from shapely.ops import unary_union

    return unary_union([polygon(p, 1) for p in value["polygons"]])


def resolve(row: dict, model: dict, ctx, spec: dict, problem) -> dict:
    key = row["id"]
    result = {
        "id": key,
        "mark": row["mark"],
        "type": row["type"],
        "kind": row["kind"],
        "floor_id": row["floor_id"],
        "space_ids": row["space_ids"],
        "host_wall_id": None,
        "host_wall_digest": None,
        "host_resolution": "NOT_RESOLVED",
        "legacy_opening_id": row.get("legacy_opening_id"),
        "issues": [],
        "geometry_status": "NOT_GENERATED",
        "approval_status": "PROPOSED",
        "declared_review_state": row["review_state"],
        "provenance": row["provenance"],
        "requirement_ids": sorted(set(row["requirement_ids"])),
        "confirmation": row["confirmation"],
        "rough_cut": None,
        "plan_cut_applied": False,
        "floor_cut_applied": False,
        "cut_accepted": False,
        "plan_interpretation": "INCOMPLETE_VERTICAL",
        "primitives": {},
        "graph_eligible": False,
        "physical_state": "NOT_VERIFIED",
        "clearance_status": "UNKNOWN",
        "movement_clearance_status": "NOT_VERIFIED",
        "opening_digest": None,
    }

    def bad(kind, code, message):
        result["issues"].append(code)
        problem(kind, code, key, message)

    declared_scale = 1.0 if spec["units"] == "m" else 0.001
    for name in (
        "rough_width",
        "rough_height",
        "bottom",
        "head",
        "clear_width",
        "clear_height",
        "frame_inner_width",
    ):
        if name in row:
            result[name + "_m"] = row[name] * declared_scale
    result["sill_m"] = row["sill"] * declared_scale if "sill" in row else None
    wall_id = row.get("host_wall_id")
    if not wall_id and row.get("legacy_opening_id"):
        matches = [
            m for m in model["opening_mappings"] if m["opening_id"] == row["legacy_opening_id"]
        ]
        if len(matches) != 1 or len(matches[0]["candidate_wall_ids"]) != 1:
            bad(
                "missing",
                "AMBIGUOUS_PROVISIONAL_HOST",
                "Legacy boundary reference has no unique current wall host; supply an explicit reviewed host, rough span and digest.",
            )
            return result
        wall_id = matches[0]["candidate_wall_ids"][0]
        result["host_resolution"] = "MIGRATED_UNAMBIGUOUS_REQUIRES_REVIEW"
        problem(
            "warning",
            "LEGACY_CLEARANCE_STALE",
            key,
            "Only the host reference is mapped; legacy width is not rough width and clearance/approval is not inherited.",
        )
    wall = next((w for w in model["walls"] if w["id"] == wall_id), None)
    if wall is None:
        bad(
            "invalid" if wall_id else "missing",
            "WALL_HOST_REQUIRED",
            "Supply an existing explicit host wall ID or a uniquely mapped provisional reference.",
        )
        return result
    result.update(host_wall_id=wall_id, host_wall_digest=wall["geometry_digest"])
    if result["host_resolution"] == "NOT_RESOLVED":
        result["host_resolution"] = "EXPLICIT"
    if row.get("source_wall_digest") != wall["geometry_digest"]:
        bad(
            "invalid" if row.get("source_wall_digest") else "missing",
            "STALE_OPENING_WALL_DIGEST",
            "Each opening must bind its exact current host geometry digest.",
        )
        return result
    if row["floor_id"] != wall["floor_id"]:
        bad("invalid", "OPENING_HOST_FLOOR", "Opening and wall belong to different floors.")
        return result
    if row["floor_id"] not in ctx.floors:
        bad("invalid", "OPENING_FLOOR", "Unknown opening floor.")
        return result
    wanted = {
        r["id"] for r in ctx.geometry.get("zoning", {}).get("brief", {}).get("requirements", [])
    }
    if not set(row["requirement_ids"]) <= wanted:
        bad(
            "invalid",
            "OPENING_REQUIREMENT_REFERENCE",
            "Opening requirements must refer to the source register.",
        )
    spaces = [ctx.spaces.get(s) for s in row["space_ids"]]
    if any(s is None or s.floor != row["floor_id"] for s in spaces):
        bad("invalid", "OPENING_SPACE_REFERENCE", "Opening spaces must exist on the host floor.")
        return result
    exterior = sum(s.kind == "exterior" for s in spaces)
    window = row["type"].endswith("window")
    if (window and row["kind"] != "window") or (
        not window
        and (row["kind"] == "window" or exterior != (1 if row["kind"] == "entrance" else 0))
    ):
        bad(
            "invalid",
            "OPENING_KIND",
            "Door/window kind must agree with the declared connected spaces.",
        )
    reference = LineString([wall["reference"]["start"], wall["reference"]["end"]])
    for space in spaces:
        region = ctx.shapes.get(space.geometry_id) if space.kind == "exterior" else space.shape
        boundary = region.boundary if region is not None else None
        if boundary is None or not near_covers(boundary, reference, ctx.tolerance):
            bad(
                "invalid",
                "WALL_SPACE_TOPOLOGY",
                "Declared space boundary does not match this wall reference.",
            )
    if (
        exterior
        and next(b for b in model["boundary_topology"] if b["id"] == wall["boundary_id"])["kind"]
        != "exterior"
    ):
        bad(
            "invalid",
            "EXTERIOR_WALL_SIDE",
            "Exterior openings require an actual envelope-side wall.",
        )
    if result["issues"]:
        return result
    scale = 1.0 if spec["units"] == "m" else 0.001
    if "rough_width" not in row:
        bad(
            "missing",
            "ROUGH_WIDTH_REQUIRED",
            "Explicit rough width is required; clear or leaf width is not substituted.",
        )
        return result
    width = row["rough_width"] * scale
    a = wall["reference"]["start"]
    b = wall["reference"]["end"]
    u = [1.0, 0.0] if a[1] == b[1] else [0.0, 1.0]
    offset = row.get("offset")
    if offset is not None:
        offset *= scale
    elif "start" in row:
        supplied = [v * scale for v in row["start"]]
        offset = math.fsum((supplied[i] - a[i]) * u[i] for i in (0, 1))
    else:
        bad(
            "missing",
            "OPENING_POSITION_REQUIRED",
            "Supply offset from canonical host start or explicit consistent endpoints.",
        )
        return result
    if max(abs(offset), width) > 1e9:
        bad("unsupported", "OPENING_NUMERIC_SCOPE", "Opening physical magnitudes exceed 1e9 m.")
        return result
    if offset < 0 or offset + width > reference.length:
        bad(
            "conflict",
            "OPENING_OUTSIDE_HOST",
            "Rough opening extends beyond the exact finite host interval; no clipping or movement.",
        )
        return result
    start = [a[i] + u[i] * offset for i in (0, 1)]
    end = [start[i] + u[i] * width for i in (0, 1)]
    for name, expected in (("start", start), ("end", end)):
        if name in row:
            supplied = [v * scale for v in row[name]]
            distance = Point(supplied).distance(Point(expected))
            if distance > ctx.tolerance:
                bad(
                    "invalid",
                    "OPENING_ENDPOINT_MISMATCH",
                    "Supplied endpoints disagree with the explicit canonical offset/rough width.",
                )
            elif distance > 0:
                problem(
                    "warning",
                    "ENDPOINT_WITHIN_TOLERANCE",
                    key,
                    "Offset is the declared positioning authority; redundant supplied endpoints were not snapped.",
                )
    normal = wall["normal"]
    low, high = wall["normal_interval_m"]
    corners = [
        [p[i] + normal[i] * d for i in (0, 1)]
        for p, d in ((start, low), (end, low), (end, high), (start, high))
    ]
    cut = Polygon(corners)
    host = shape_set(wall["geometry"])
    if not cut.is_valid or cut.area <= 0 or not host.covers(cut):
        bad(
            "unsupported",
            "UNSUPPORTED_WALL_CUT",
            "Rough cut must be positive, valid and fully contained in its intended host; no repair.",
        )
    for j in model["junctions"]:
        if j["floor_id"] == row["floor_id"] and wall_id in j["wall_ids"] and j["kind"] != "END":
            core = shape_set(j["geometry"])
            if cut.intersection(core).area > 0 or cut.intersects(Point(j["point"])):
                bad(
                    "unsupported",
                    "OPENING_JUNCTION_INTERFERENCE",
                    "Opening touches a joint node/core; junction-aware assemblies are outside this scope.",
                )
    for other in model["walls"]:
        if (
            other["floor_id"] == row["floor_id"]
            and other["id"] != wall_id
            and cut.intersection(shape_set(other["geometry"])).area > 0
        ):
            bad(
                "unsupported",
                "OPENING_ADJACENT_WALL_CUT",
                "Proposed cut would remove adjacent/intersecting wall material; it is not applied.",
            )
    result.update(
        _wall=wall,
        _cut=cut,
        _u=u,
        _normal=normal,
        _start=start,
        _end=end,
        _scale=scale,
        _row=row,
        reference={"start": start, "end": end},
        offset_m=offset,
        rough_width_m=width,
        thickness_m=wall["thickness_m"],
        normal_interval_m=[low, high],
    )
    return result
