"""CAD-neutral Drawing Intermediate Representation (IR) primitives and validators."""

import math
from typing import Any

from vnai.contracts import canonical_digest

PRIMITIVE_TYPES = frozenset(
    {
        "LINE",
        "POLYLINE",
        "ARC",
        "CIRCLE",
        "TEXT",
        "MTEXT",
        "DIMENSION",
        "HATCH",
        "SYMBOL",
        "BLOCK_REFERENCE",
    }
)


def _clean_point(pt: list[float] | tuple[float, float]) -> list[float]:
    return [0.0 if float(v) == 0.0 else float(v) for v in pt[:2]]


def make_entity_id(
    view_id: str,
    entity_type: str,
    layer: str,
    source_geometry_id: str,
    key_tag: str,
) -> str:
    """Create a deterministic, content-addressed entity ID."""
    return "DE-" + canonical_digest([view_id, entity_type, layer, source_geometry_id, key_tag])[:16]


def make_entity(
    *,
    entity_type: str,
    coordinates: dict[str, Any],
    view_id: str,
    floor_id: str | None,
    layer: str,
    style_ref: str,
    source_geometry_id: str,
    source_revision_digest: str,
    provenance: str,
    key_tag: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a CAD-neutral drawing primitive with full provenance."""
    if entity_type not in PRIMITIVE_TYPES:
        raise ValueError(f"Unsupported IR primitive type: {entity_type}")
    entity: dict[str, Any] = {
        "id": make_entity_id(view_id, entity_type, layer, source_geometry_id, key_tag),
        "entity_type": entity_type,
        "coordinates": coordinates,
        "view_id": view_id,
        "floor_id": floor_id,
        "layer": layer,
        "style_ref": style_ref,
        "source_geometry_id": source_geometry_id,
        "source_revision_digest": source_revision_digest or "unresolved",
        "provenance": provenance,
    }
    if metadata is not None:
        entity["metadata"] = metadata
    return entity


def arc_angles_deg(
    center: list[float],
    start: list[float],
    end: list[float],
) -> tuple[float, float]:
    """Compute start/end angles in degrees for analytic ARC representation."""
    a0 = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0])) % 360.0
    a1 = math.degrees(math.atan2(end[1] - center[1], end[0] - center[0])) % 360.0
    return (0.0 if a0 == 0.0 else float(a0), 0.0 if a1 == 0.0 else float(a1))


def default_blocks(model_sizing: dict[str, Any]) -> dict[str, Any]:
    """Define reusable CAD blocks in model_space.blocks for BLOCK_REFERENCE entities."""
    th = model_sizing["text_height"]
    r_tag = th * 1.4
    return {
        "TAG_DOOR": {
            "kind": "opening_tag_capsule",
            "radius": r_tag,
            "width": th * 4.2,
            "height": th * 2.1,
            "description": "Rounded capsule mark tag for door openings",
        },
        "TAG_WINDOW": {
            "kind": "opening_tag_hex",
            "radius": r_tag,
            "width": th * 3.8,
            "height": th * 2.1,
            "description": "Hexagonal/diamond mark tag for window openings",
        },
        "SYM_LEVEL_MARK": {
            "kind": "elevation_triangle_datum",
            "size": th * 1.2,
            "description": "Architectural finished floor/landing elevation marker",
        },
        "SYM_NORTH_ARROW": {
            "kind": "true_north_compass",
            "radius": th * 2.8,
            "description": "True north directional arrow grounded in confirmed orientation",
        },
    }


def _extract_points(item: Any, out: list[list[float]]) -> None:
    if isinstance(item, list):
        if (
            len(item) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in item)
        ):
            out.append(_clean_point(item))
        else:
            for sub in item:
                _extract_points(sub, out)
    elif isinstance(item, dict):
        if "center" in item and "radius" in item and isinstance(item["radius"], (int, float)):
            cx, cy = item["center"]
            r = float(item["radius"])
            out.append([cx - r, cy - r])
            out.append([cx + r, cy + r])
        for v in item.values():
            _extract_points(v, out)


def compute_view_bounds(entities: list[dict[str, Any]]) -> dict[str, float]:
    """Compute finite model-space bounding box across a view's entities."""
    pts: list[list[float]] = []
    for ent in entities:
        _extract_points(ent["coordinates"], pts)
    if not pts:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0}
    return {
        "min_x": min(p[0] for p in pts),
        "min_y": min(p[1] for p in pts),
        "max_x": max(p[0] for p in pts),
        "max_y": max(p[1] for p in pts),
    }


def _all_numbers_finite(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_all_numbers_finite(v) for v in value)
    if isinstance(value, dict):
        return all(_all_numbers_finite(v) for v in value.values())
    return True


def validate_ir_entities(model_space: dict[str, Any], layer_policy: dict[str, Any]) -> list[str]:
    """Validate all IR entities against layer policy, primitive types and block definitions."""
    issues: list[str] = []
    valid_layers = {row["name"] for row in layer_policy.get("layers", [])}
    blocks = model_space.get("blocks", {})
    seen_ids: set[str] = set()
    for view in model_space.get("views", []):
        vid = view.get("view_id")
        for ent in view.get("entities", []):
            eid = ent.get("id", "")
            if eid in seen_ids:
                issues.append(f"Duplicate IR entity ID across views: {eid}")
            seen_ids.add(eid)
            if ent.get("entity_type") not in PRIMITIVE_TYPES:
                issues.append(f"Invalid entity_type on {eid}: {ent.get('entity_type')}")
            if ent.get("view_id") != vid:
                issues.append(f"Entity {eid} view_id mismatches parent view {vid}")
            if ent.get("layer") not in valid_layers:
                issues.append(f"Entity {eid} uses undeclared layer {ent.get('layer')}")
            if not _all_numbers_finite(ent.get("coordinates")):
                issues.append(f"Entity {eid} contains non-finite coordinates")
            if ent.get("entity_type") == "ARC":
                coords = ent.get("coordinates", {})
                if "center" not in coords or "radius" not in coords or coords["radius"] <= 0:
                    issues.append(f"ARC entity {eid} missing valid analytic center/radius")
            if ent.get("entity_type") == "BLOCK_REFERENCE":
                bname = ent.get("metadata", {}).get("block_name")
                if bname not in blocks:
                    issues.append(f"BLOCK_REFERENCE {eid} references missing block {bname}")
    return issues
