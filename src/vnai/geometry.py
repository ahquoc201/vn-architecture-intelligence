"""Validated 2D polygons in millimetres. No inference from CAD layers."""

import math
from collections.abc import Sequence

from shapely.geometry import Polygon
from shapely.validation import explain_validity

MM2_PER_M2 = 1_000_000.0


def polygon_mm(points: Sequence[Sequence[float]], name: str) -> Polygon:
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise ValueError(f"{name}: polygon needs 3+ vertices")
    for vertex in points:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise ValueError(f"{name}: every vertex must have two coordinates")
        if any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in vertex):
            raise ValueError(f"{name}: coordinates must be numbers")
        if any(not math.isfinite(c) for c in vertex):
            raise ValueError(f"{name}: coordinates must be finite")
    shape = Polygon(points)
    if not shape.is_valid:
        raise ValueError(f"{name}: invalid polygon: {explain_validity(shape)}")
    if shape.area < 1.0:
        raise ValueError(f"{name}: zero/near-zero polygon area")
    return shape


def area_m2(shape: Polygon) -> float:
    return shape.area / MM2_PER_M2


def validate_plan_structure(plan: dict) -> None:
    if plan.get("schema_version") != 1:
        raise ValueError("Only schema_version=1 is supported")
    if plan.get("units") != "mm":
        raise ValueError("Only millimetres (units=mm) are supported")
    if not isinstance(plan.get("site"), dict):
        raise ValueError("site object required")
    if not isinstance(plan.get("levels"), list) or not plan["levels"]:
        raise ValueError("At least one level required")
    site_polygon = plan["site"].get("outline_mm")
    polygon_mm(site_polygon, "site.outline_mm")
    level_ids: set[str] = set()
    room_ids: set[str] = set()
    for level in plan["levels"]:
        if not isinstance(level, dict) or not isinstance(level.get("rooms"), list):
            raise ValueError("Every level needs rooms array")
        level_id = level.get("id")
        if not isinstance(level_id, str) or not level_id:
            raise ValueError("Every level needs nonblank id")
        if level_id in level_ids:
            raise ValueError(f"Duplicate level ID: {level_id}")
        level_ids.add(level_id)
        for room in level["rooms"]:
            if not isinstance(room, dict):
                raise ValueError("Room must be an object")
            room_id = room.get("id")
            if not isinstance(room_id, str) or not room_id:
                raise ValueError("Every room needs nonblank id")
            if room_id in room_ids:
                raise ValueError(f"Duplicate room ID: {room_id}")
            room_ids.add(room_id)
            polygon_mm(room.get("polygon_mm"), f"room.{room_id}.polygon_mm")
            target = room.get("target_area_m2")
            if target is not None and (
                isinstance(target, bool)
                or not isinstance(target, (int, float))
                or not math.isfinite(target)
                or target <= 0
            ):
                raise ValueError(f"room.{room_id}: target_area_m2 must be positive")
