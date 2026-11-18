"""2D geometry contract and spatial diagnostics, with no geometry repair or CAD writes."""

from typing import Any
import math

from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity

from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.zoning import validate_zoning
from vnai.space_program import build_space_program


def geometry_digest(doc: dict, entity: dict) -> str:
    """Bind approval to geometry, coordinate/tolerance policy and linked zoning."""
    return canonical_digest(
        {
            "project_id": doc["project_id"],
            "units": doc["units"],
            "frame": doc["frame"],
            "tolerances": doc["tolerances"],
            "floors": doc["floors"],
            "zoning": doc.get("zoning"),
            "points": doc["points"],
            "segments": doc["segments"],
            "relationships": [
                {k: v for k, v in r.items() if k not in {"status", "approval"}}
                for r in doc["relationships"]
            ],
            "polygons": [
                {k: v for k, v in p.items() if k not in {"status", "approval"}}
                for p in doc["polygons"]
            ],
            "entity": {k: v for k, v in entity.items() if k not in {"status", "approval"}},
        }
    )


def validate_geometry(doc: Any) -> dict:
    report = new_report("geometry-v1")
    report.update(
        {
            "polygon_areas_m2": {},
            "floor_areas": [],
            "site_area_m2": None,
            "footprint_area_m2": None,
            "gross_floor_area_m2": None,
            "envelope_approval": {},
            "architectural_approval": "NOT_EVALUATED",
            "buildability": "NOT_EVALUATED",
        }
    )
    if not schema_check(doc, "geometry.schema.json", report):
        return report
    if len(doc["polygons"]) > 500:
        issue(
            report,
            "errors",
            "RESOURCE_LIMIT",
            "polygons",
            "At most 500 polygons supported per document.",
        )
        return finish(report)
    frame = doc["frame"]
    if frame["kind"] == "world" and not frame.get("world_crs"):
        issue(
            report,
            "errors",
            "WORLD_CRS_REQUIRED",
            "frame",
            "Supply an explicit projected world CRS label.",
        )
    if frame["kind"] == "world" and ("origin_world" in frame or "rotation_degrees" in frame):
        issue(
            report,
            "errors",
            "FRAME_CONFLICT",
            "frame",
            "Local-to-world transform metadata belongs to local_site.",
        )
    if ("origin_world" in frame) != ("rotation_degrees" in frame):
        issue(
            report,
            "errors",
            "FRAME_TRANSFORM_INCOMPLETE",
            "frame",
            "Supply origin and rotation together.",
        )
    ids: set[str] = {doc["project_id"], frame["id"]}
    if doc["project_id"] == frame["id"]:
        issue(
            report, "errors", "DUPLICATE_GEOMETRY_ID", "frame", "Project and frame IDs must differ."
        )
    floor_ids: set[str] = set()

    def register(key: str, path: str) -> None:
        if key in ids:
            issue(
                report,
                "errors",
                "DUPLICATE_GEOMETRY_ID",
                path,
                f"Duplicate geometry identifier: {key}",
            )
        ids.add(key)

    for floor in doc["floors"]:
        register(floor["id"], "floors")
        floor_ids.add(floor["id"])
    rows = {row["id"]: row for row in doc["polygons"]}
    owners = set(rows) | floor_ids | {doc["project_id"]}
    shapes: dict[str, Polygon] = {}
    site_ids, footprint_ids = [], []
    floor_outlines: dict[str, str] = {}
    room_instances: set[str] = set()
    scale = 1.0 if doc["units"] == "m" else 0.001
    approved: dict[str, bool] = {}
    for row in doc["polygons"]:
        path = "polygons." + row["id"]
        register(row["id"], path)
        if row["units"] != doc["units"] or row["frame_id"] != frame["id"]:
            issue(
                report,
                "errors",
                "COORDINATE_MISMATCH",
                path,
                "All geometry must use the declared document frame and units; no conversion inferred.",
            )
        if row["owner_id"] not in owners or row["owner_id"] == row["id"]:
            issue(report, "errors", "GEOMETRY_OWNER", path, "Unknown or self-owned geometry.")
        if row["role"] in {"site", "footprint"}:
            if row["owner_id"] != doc["project_id"] or "floor_id" in row or "room_id" in row:
                issue(
                    report,
                    "errors",
                    "GEOMETRY_ROLE",
                    path,
                    "Site/footprint must be project-owned without floor/room IDs.",
                )
            (site_ids if row["role"] == "site" else footprint_ids).append(row["id"])
        else:
            if row.get("floor_id") not in floor_ids or row["owner_id"] != row.get("floor_id"):
                issue(
                    report,
                    "errors",
                    "UNKNOWN_FLOOR",
                    path,
                    "Floor/room polygon needs a valid owning floor.",
                )
            if row["role"] == "floor_outline":
                if "room_id" in row or "requirement_id" in row:
                    issue(
                        report,
                        "errors",
                        "GEOMETRY_ROLE",
                        path,
                        "Floor outline cannot claim a room identity.",
                    )
                if row.get("floor_id") in floor_outlines:
                    issue(
                        report,
                        "errors",
                        "DUPLICATE_FLOOR_OUTLINE",
                        path,
                        "Only one outline per floor supported.",
                    )
                floor_outlines[row.get("floor_id", "")] = row["id"]
            elif row["role"] == "room":
                if not row.get("room_id") or not row.get("requirement_id"):
                    issue(
                        report,
                        "errors",
                        "ROOM_TRACEABILITY",
                        path,
                        "Room polygons require instance and requirement IDs.",
                    )
                if row.get("room_id") in room_instances:
                    issue(
                        report,
                        "errors",
                        "DUPLICATE_ROOM_GEOMETRY",
                        path,
                        "Room instance has multiple polygons.",
                    )
                room_instances.add(row.get("room_id", ""))
            elif (
                not row.get("reservation_kind")
                or not row.get("requirement_id")
                or not row.get("provenance")
                or "room_id" in row
            ):
                issue(
                    report,
                    "errors",
                    "RESERVATION_METADATA",
                    path,
                    "Reservations require kind, requirement provenance and no room identity.",
                )
        approval = row.get("approval")
        valid_approval = bool(approval and approval["digest"] == geometry_digest(doc, row))
        approved[row["id"]] = row["status"] == "approved" and valid_approval
        if (row["status"] == "approved" and not valid_approval) or (
            approval and not valid_approval
        ):
            issue(
                report,
                "errors",
                "GEOMETRY_APPROVAL_RECORD",
                path,
                "Missing or stale architect approval record.",
            )
        if row["status"] != "approved" and approval:
            issue(
                report,
                "errors",
                "GEOMETRY_APPROVAL_STATE",
                path,
                "Approval record conflicts with proposed status.",
            )
        report["envelope_approval"][row["id"]] = approved[row["id"]]
        try:
            shell = [(float(x) * scale, float(y) * scale) for x, y in row["exterior"]]
            holes = [
                [(float(x) * scale, float(y) * scale) for x, y in ring]
                for ring in row.get("holes", [])
            ]
            shape = Polygon(shell, holes)
            if not shape.is_valid:
                issue(report, "errors", "INVALID_POLYGON", path, explain_validity(shape))
            if not math.isfinite(shape.area) or shape.area <= doc["tolerances"]["min_area_m2"]:
                issue(
                    report,
                    "errors",
                    "NEAR_ZERO_AREA",
                    path,
                    "Polygon area must exceed the explicit minimum tolerance.",
                )
                continue
            if not shape.is_valid:
                continue
            if not shape.exterior.is_ccw or any(ring.is_ccw for ring in shape.interiors):
                issue(
                    report,
                    "warnings",
                    "RING_ORIENTATION",
                    path,
                    "Expected CCW exterior and CW holes; geometry retained without rewriting.",
                )
            shapes[row["id"]] = shape
            report["polygon_areas_m2"][row["id"]] = shape.area
        except (ValueError, OverflowError, GEOSException) as exc:
            issue(report, "errors", "GEOMETRY_CONSTRUCTION", path, str(exc))
    if len(site_ids) != 1 or len(footprint_ids) > 1:
        issue(
            report,
            "errors",
            "ENVELOPE_COUNT",
            "polygons",
            "Exactly one site and at most one footprint supported.",
        )
    # Avoid ambiguous ownership cycles: project/floor ownership is the supported model.
    for row in doc["polygons"]:
        expected_owner = (
            doc["project_id"] if row["role"] in {"site", "footprint"} else row.get("floor_id")
        )
        if row["owner_id"] != expected_owner:
            issue(
                report,
                "errors",
                "GEOMETRY_OWNER",
                row["id"],
                "Polygon must belong directly to project or floor.",
            )
    point_rows = {p["id"]: p for p in doc["points"]}
    for point in doc["points"]:
        register(point["id"], "points")
        if point["owner_id"] not in owners:
            issue(report, "errors", "GEOMETRY_OWNER", "points", "Unknown point owner.")
    for segment in doc["segments"]:
        register(segment["id"], "segments")
        a, b = point_rows.get(segment["start"]), point_rows.get(segment["end"])
        if not a or not b or segment["owner_id"] not in owners:
            issue(
                report, "errors", "SEGMENT_REFERENCE", "segments", "Unknown point or segment owner."
            )
        elif a["owner_id"] != segment["owner_id"] or b["owner_id"] != segment["owner_id"]:
            issue(
                report,
                "errors",
                "SEGMENT_OWNER",
                "segments",
                "Segment endpoints must share the owner.",
            )
        elif a["xy"] == b["xy"]:
            issue(
                report, "errors", "ZERO_LENGTH_SEGMENT", "segments", "Segment endpoints coincide."
            )
    intentional: set[frozenset[str]] = set()
    relation_pairs: set[frozenset[str]] = set()
    for relation in doc["relationships"]:
        register(relation["id"], "relationships")
        pair = frozenset(relation["geometry_ids"])
        if pair in relation_pairs:
            issue(
                report,
                "errors",
                "DUPLICATE_RELATIONSHIP",
                "relationships",
                "Duplicate relationship pair.",
            )
        relation_pairs.add(pair)
        left, right = (rows.get(key) for key in relation["geometry_ids"])
        if (
            not left
            or not right
            or left["role"] != "room"
            or right["role"] != "room"
            or left.get("floor_id") != right.get("floor_id")
        ):
            issue(
                report,
                "errors",
                "RELATIONSHIP_REFERENCE",
                "relationships",
                "Overlap declaration needs two rooms on one floor.",
            )
            continue
        approval = relation.get("approval")
        if relation["status"] == "approved":
            if not approval or approval["digest"] != geometry_digest(doc, relation):
                issue(
                    report,
                    "errors",
                    "GEOMETRY_APPROVAL_RECORD",
                    "relationships",
                    "Missing/stale intentional-overlap approval.",
                )
            else:
                intentional.add(pair)
        elif approval:
            issue(
                report,
                "errors",
                "GEOMETRY_APPROVAL_STATE",
                "relationships",
                "Proposed relationship cannot carry approval.",
            )
    if report["errors"]:
        return finish(report)
    site_id = site_ids[0]
    site = shapes[site_id]
    footprint_id = footprint_ids[0] if footprint_ids else None
    report["site_area_m2"] = site.area
    report["footprint_area_m2"] = shapes[footprint_id].area if footprint_id else None
    boundary_tol = doc["tolerances"]["boundary_m"]

    def contain(child_id: str, parent_id: str) -> None:
        child, parent = shapes[child_id], shapes[parent_id]
        if parent.covers(child):
            return
        if boundary_tol and parent.buffer(boundary_tol).covers(child):
            issue(
                report,
                "warnings",
                "BOUNDARY_WITHIN_TOLERANCE",
                child_id,
                f"Outside exact envelope {parent_id}, within declared boundary tolerance.",
            )
        else:
            issue(
                report,
                "errors",
                "OUTSIDE_ENVELOPE",
                child_id,
                f"Polygon extends beyond envelope {parent_id}; approved={approved[parent_id]}.",
            )

    try:
        if footprint_id:
            contain(footprint_id, site_id)
        for floor_id, outline in floor_outlines.items():
            contain(outline, footprint_id or site_id)
        for floor_id in sorted(floor_ids):
            room_ids = [
                r["id"]
                for r in doc["polygons"]
                if r["role"] == "room" and r["floor_id"] == floor_id
            ]
            envelope_id = floor_outlines.get(floor_id) or footprint_id or site_id
            for i, room_id in enumerate(room_ids):
                contain(room_id, envelope_id)
                for previous in room_ids[:i]:
                    area = shapes[room_id].intersection(shapes[previous]).area
                    if area > 0 and frozenset((room_id, previous)) in intentional:
                        issue(
                            report,
                            "diagnostics",
                            "INTENTIONAL_OVERLAP",
                            room_id,
                            f"Explicitly approved overlap with {previous}: {area} m2.",
                        )
                    elif area > doc["tolerances"]["overlap_m2"]:
                        issue(
                            report,
                            "errors",
                            "ROOM_OVERLAP",
                            room_id,
                            f"Same-floor overlap with {previous}: {area} m2.",
                        )
                    elif area > 0:
                        issue(
                            report,
                            "warnings",
                            "OVERLAP_WITHIN_TOLERANCE",
                            room_id,
                            f"Positive overlap within declared tolerance: {area} m2.",
                        )
            reserved_ids = [
                r["id"]
                for r in doc["polygons"]
                if r["role"] == "reservation" and r["floor_id"] == floor_id
            ]
            for reserved_id in reserved_ids:
                contain(reserved_id, envelope_id)
                for room_id in room_ids:
                    if (
                        shapes[room_id].intersection(shapes[reserved_id]).area
                        > doc["tolerances"]["overlap_m2"]
                    ):
                        issue(
                            report,
                            "errors",
                            "ROOM_IN_RESERVED_REGION",
                            room_id,
                            f"Room intersects supplied reservation {reserved_id}.",
                        )
            union = unary_union([shapes[key] for key in room_ids])
            report["floor_areas"].append(
                {
                    "floor_id": floor_id,
                    "envelope_id": envelope_id,
                    "envelope_area_m2": shapes[envelope_id].area,
                    "envelope_approved": approved[envelope_id],
                    "net_room_polygon_sum_m2": sum(shapes[key].area for key in room_ids),
                    "net_room_polygon_union_m2": union.area,
                    "geometric_residual_m2": shapes[envelope_id].difference(union).area,
                    "note": "Polygon accounting only; residual is not verified usable area or GFA.",
                }
            )
        if set(floor_outlines) == floor_ids:
            report["gross_floor_area_m2"] = sum(shapes[key].area for key in floor_outlines.values())
    except (ValueError, OverflowError, GEOSException) as exc:
        issue(report, "errors", "SPATIAL_OPERATION", "polygons", str(exc))
    if "zoning" in doc:
        zoning = validate_zoning(doc["zoning"])
        report["zoning_validation"] = zoning
        if zoning["status"] == "INVALID":
            issue(report, "errors", "INVALID_ZONING", "zoning", "Linked zoning is invalid.")
        else:
            if doc["zoning"]["brief"]["project"]["id"] != doc["project_id"]:
                issue(
                    report,
                    "errors",
                    "PROJECT_MISMATCH",
                    "zoning",
                    "Geometry and zoning project IDs differ.",
                )
            if {f["id"] for f in doc["zoning"]["floors"]} != floor_ids:
                issue(
                    report,
                    "errors",
                    "FLOOR_SET_CONFLICT",
                    "zoning",
                    "Geometry and zoning floors differ.",
                )
            geometry_floors = {f["id"]: f for f in doc["floors"]}
            for floor in doc["zoning"]["floors"]:
                if "elevation" in floor and floor["id"] in geometry_floors:
                    meta = floor["elevation"]
                    expected = meta["value"] * (1 if meta["unit"] == "m" else 0.001)
                    supplied = geometry_floors[floor["id"]].get("elevation_m")
                    if supplied is not None and supplied != expected:
                        issue(
                            report,
                            "errors",
                            "ELEVATION_CONFLICT",
                            "floors",
                            "Geometry/zoning elevations differ.",
                        )
            requirements = {r["id"] for r in doc["zoning"]["brief"]["requirements"]}
            for relation in doc["relationships"]:
                if relation["requirement_id"] not in requirements:
                    issue(
                        report,
                        "errors",
                        "RELATIONSHIP_TRACEABILITY",
                        "relationships",
                        "Overlap declaration references an unknown source requirement.",
                    )
            report["architectural_approval"] = (
                "APPROVED" if zoning["architect_approved"] else "PENDING"
            )
            if not zoning["architect_approved"]:
                issue(
                    report,
                    "missing_information",
                    "ZONING_APPROVAL_REQUIRED",
                    "zoning",
                    "Resolve and approve zoning first.",
                )
            program = build_space_program(doc["zoning"]["brief"])
            program_rooms = {r["id"]: r for r in program["rooms"]}
            active = {
                r["room_id"]: r
                for r in doc["zoning"]["assignments"]
                if r["status"] not in {"rejected", "superseded"}
            }
            for row in doc["polygons"]:
                if row["role"] == "reservation" and row["requirement_id"] not in requirements:
                    issue(
                        report,
                        "errors",
                        "RESERVATION_TRACEABILITY",
                        row["id"],
                        "Reservation references an unknown source requirement.",
                    )
                if row["role"] != "room":
                    continue
                room, assignment = program_rooms.get(row["room_id"]), active.get(row["room_id"])
                if not room or room["requirement_id"] != row["requirement_id"]:
                    issue(
                        report,
                        "errors",
                        "ROOM_TRACEABILITY",
                        row["id"],
                        "Geometry must reference its original program requirement.",
                    )
                    continue
                if not assignment or assignment["floor_id"] != row["floor_id"]:
                    issue(
                        report,
                        "errors",
                        "ZONING_FLOOR_CONFLICT",
                        row["id"],
                        "Geometry floor differs from active assignment.",
                    )
                area = room["requested_area_m2"]
                if area and room["confirmed"]:
                    actual = shapes[row["id"]].area
                    tol = doc["tolerances"]["target_area_m2"]
                    if (
                        ("target" in area and abs(actual - area["target"]) > tol)
                        or ("min" in area and actual < area["min"] - tol)
                        or ("max" in area and actual > area["max"] + tol)
                    ):
                        issue(
                            report,
                            "warnings",
                            "ROOM_AREA_TARGET_MISMATCH",
                            row["id"],
                            f"Measured polygon area {actual} m2 differs from supplied room area request.",
                            [room["requirement_id"]],
                        )
            for room_id, room in program_rooms.items():
                if room_id not in room_instances:
                    issue(
                        report,
                        "missing_information",
                        "ROOM_GEOMETRY_MISSING",
                        room_id,
                        "Program room has no supplied polygon.",
                        [room["requirement_id"]],
                    )
    return finish(report)
