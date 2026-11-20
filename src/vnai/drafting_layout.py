"""Bounded deterministic annotation placement and collision detection."""

import math
from typing import Any

from shapely.geometry import Polygon, box

from vnai.contracts import canonical_digest
from vnai.drafting_ir import make_entity


def _poly_from_coords(coords: dict[str, Any]) -> Polygon | None:
    ext = coords.get("exterior")
    if not ext or len(ext) < 4:
        return None
    holes = coords.get("holes", [])
    try:
        p = Polygon(ext, holes)
        return p if p.is_valid and not p.is_empty else p.buffer(0)
    except Exception:
        return None


def _estimate_entity_box(
    ent: dict[str, Any],
    style: dict[str, Any],
) -> tuple[Polygon, str] | None:
    """Compute approximate bounding box for text/tag/bubble primitives.

    Always reports method='APPROXIMATE_CHARACTER_METRIC_BOX'; never claims exact font glyph metrics.
    """
    sizing = style["model_sizing"]
    th = sizing["text_height"]
    dh = sizing["dim_text_height"]
    et = ent["entity_type"]
    coords = ent["coordinates"]
    meta = ent.get("metadata", {})

    if et == "TEXT":
        # Skip tiny step numbers inside stair treads from inter-annotation collisions.
        if ent.get("key_tag") == "step_num" or (ent.get("id") and meta.get("text", "").isdigit() and meta.get("height", th) < dh * 0.75):
            return None
        cx, cy = coords["insert"]
        h = float(meta.get("height", dh))
        text = str(meta.get("text", ""))
        w = max(len(text), 1) * h * 0.62
        bh = h * 1.25
        rot = float(meta.get("rotation_deg", 0.0)) % 180.0
        if abs(rot - 90.0) < 1e-3:
            w, bh = bh, w
        anchor = meta.get("anchor", "start")
        if anchor == "middle":
            b = box(cx - w / 2.0, cy - bh / 2.0, cx + w / 2.0, cy + bh / 2.0)
        elif anchor == "end":
            b = box(cx - w, cy - bh / 2.0, cx, cy + bh / 2.0)
        else:
            b = box(cx, cy - bh / 2.0, cx + w, cy + bh / 2.0)
        return b, "APPROXIMATE_TEXT_BOUNDS"

    if et == "MTEXT":
        cx, cy = coords["insert"]
        h = float(meta.get("height", th))
        ls = float(meta.get("line_spacing", 1.25))
        lines = [str(line) for line in meta.get("lines", [])] or [""]
        w = max((len(line) for line in lines), default=1) * h * 0.62
        bh = len(lines) * h * ls * 1.05
        anchor = meta.get("anchor", "middle")
        if anchor == "start":
            b = box(cx, cy - bh / 2.0, cx + w, cy + bh / 2.0)
        elif anchor == "end":
            b = box(cx - w, cy - bh / 2.0, cx, cy + bh / 2.0)
        else:
            b = box(cx - w / 2.0, cy - bh / 2.0, cx + w / 2.0, cy + bh / 2.0)
        return b, "APPROXIMATE_TEXT_BOUNDS"

    if et == "BLOCK_REFERENCE":
        cx, cy = coords["insert"]
        bname = meta.get("block_name", "")
        if bname in {"TAG_DOOR", "TAG_WINDOW"}:
            sub = str(meta.get("dimension_label", ""))
            mark = str(meta.get("mark", ""))
            chars = max(len(mark), len(sub), 3)
            w = max(th * 3.0, chars * dh * 0.56)
            bh = th * (2.6 if sub else 1.7)
            return box(cx - w / 2.0, cy - bh / 2.0, cx + w / 2.0, cy + bh / 2.0), "APPROXIMATE_TEXT_BOUNDS"
        if bname == "SYM_LEVEL_MARK":
            lbl = str(meta.get("label", ""))
            w = max(len(lbl), 4) * dh * 0.58 + th * 1.5
            bh = th * 1.8
            return box(cx, cy - bh / 2.0, cx + w, cy + bh / 2.0), "APPROXIMATE_TEXT_BOUNDS"
        if bname == "SYM_NORTH_ARROW":
            r = th * 2.8
            return box(cx - r, cy - r, cx + r, cy + r), "APPROXIMATE_TEXT_BOUNDS"

    if et == "DIMENSION":
        tx, ty = coords["text_point"]
        h = float(meta.get("height", dh))
        text = str(meta.get("display_text", ""))
        w = max(len(text), 2) * h * 0.62
        bh = h * 1.25
        if meta.get("orientation") == "vertical":
            w, bh = bh, w
        return box(tx - w / 2.0, ty - bh / 2.0, tx + w / 2.0, ty + bh / 2.0), "APPROXIMATE_TEXT_BOUNDS"

    if et == "CIRCLE" and ent.get("layer") == "A-GRID":
        cx, cy = coords["center"]
        r = float(coords["radius"])
        return box(cx - r, cy - r, cx + r, cy + r), "EXACT_GEOMETRIC"

    return None


def _shift_entity_box(b: Polygon, dx: float, dy: float) -> Polygon:
    minx, miny, maxx, maxy = b.bounds
    return box(minx + dx, miny + dy, maxx + dx, maxy + dy)


def _annotation_category(ent: dict[str, Any]) -> str:
    layer = ent.get("layer", "")
    if layer == "A-ROOM-TEXT":
        return "room_label"
    if layer == "A-OPENING-TAG":
        return "opening_tag"
    if layer == "A-DIMS":
        return "dimension_label"
    if layer == "A-STAIR":
        return "stair_annotation"
    if layer == "A-GRID":
        return "grid_or_north_symbol"
    if layer == "A-LEVEL":
        return "level_mark"
    if layer == "A-SECT":
        return "section_annotation"
    return "annotation"


def resolve_view_layout(
    *,
    view: dict[str, Any],
    context: dict[str, Any],
    style: dict[str, Any],
    placement_options: dict[str, Any],
    room_records: list[dict[str, Any]] | None = None,
    opening_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run bounded deterministic placement and exact/approximate collision checks for a view."""
    allow_repo = bool(placement_options.get("allow_reposition", True))
    allow_leader = bool(placement_options.get("allow_leader_callout", True))
    max_attempts = int(placement_options.get("max_attempts", 12))
    sizing = style["model_sizing"]
    th = sizing["text_height"]
    dh = sizing["dim_text_height"]
    dim_offset = sizing["dim_offset"]
    entities = view["entities"]
    view_id = view["view_id"]
    floor_id = view.get("floor_id")
    src_rev = view["source_revision_digest"]

    # Build immutable building geometry obstacles for this view.
    geom_obstacles: list[tuple[str, Polygon]] = []
    for ent in entities:
        layer = ent["layer"]
        et = ent["entity_type"]
        if layer in {"A-WALL-EXT", "A-WALL-INT"} and et == "POLYLINE" and ent["coordinates"].get("closed"):
            p = _poly_from_coords(ent["coordinates"])
            if p is not None:
                geom_obstacles.append((ent["id"], p))
        elif layer in {"A-DOOR", "A-WIND"} and et == "POLYLINE" and ent["coordinates"].get("closed"):
            p = _poly_from_coords(ent["coordinates"])
            if p is not None:
                geom_obstacles.append((ent["id"], p))
        elif layer == "A-REVIEW" and et == "POLYLINE" and ent["coordinates"].get("closed"):
            p = _poly_from_coords(ent["coordinates"])
            if p is not None:
                geom_obstacles.append((ent["id"], p))
        elif layer in {"A-STAIR", "A-STAIR-ABOVE"} and et == "POLYLINE" and ent["coordinates"].get("closed"):
            p = _poly_from_coords(ent["coordinates"])
            if p is not None:
                geom_obstacles.append((ent["id"], p))

    # Map clear room polygons by room_id for interior checks.
    clear_room_polys: dict[str, Polygon] = {}
    if floor_id and context.get("walls_report"):
        from vnai.opening_hosts import shape_set
        from vnai.drafting_styles import UNIT_TO_MM

        scale_to_draw = float(UNIT_TO_MM["m"] / UNIT_TO_MM[style["model_sizing"]["units"]])
        from shapely.affinity import scale as shp_scale

        for r in context["walls_report"].get("rooms", []):
            if r["floor_id"] == floor_id:
                s = shape_set(r["clear_geometry"])
                if not s.is_empty:
                    clear_room_polys[r["room_id"]] = shp_scale(
                        s, xfact=scale_to_draw, yfact=scale_to_draw, origin=(0, 0)
                    )

    # Compute building envelope drawing extent in drawing units for clean leader callouts.
    env_poly = context["floor_envelopes"].get(floor_id) if floor_id else None
    if env_poly is not None:
        from vnai.drafting_styles import UNIT_TO_MM

        factor = float(UNIT_TO_MM["m"] / UNIT_TO_MM[style["model_sizing"]["units"]])
        _, _, ex1, ey1 = (v * factor for v in env_poly.bounds)
    else:
        _, _, ex1, ey1 = (0.0, 0.0, 4000.0, 4000.0)

    placed_boxes: list[tuple[dict[str, Any], Polygon, str]] = []
    adjustments: list[dict[str, Any]] = []
    leader_entities: list[dict[str, Any]] = []

    def overlaps_any(cand_box: Polygon, *, allow_geom: set[str] | None = None, ignore_layers: set[str] | None = None) -> bool:
        for oid, gp in geom_obstacles:
            if allow_geom and oid in allow_geom:
                continue
            if cand_box.intersects(gp) and cand_box.intersection(gp).area > 1e-6:
                return True
        for other_ent, ob, _ in placed_boxes:
            if ignore_layers and other_ent["layer"] in ignore_layers:
                continue
            if cand_box.intersects(ob) and cand_box.intersection(ob).area > 1e-6:
                return True
        return False

    # Categorize movable annotation entities in deterministic placement priority order.
    grid_fixed = [
        e for e in entities
        if e["layer"] in {"A-GRID", "A-LEVEL", "A-SECT"}
        and _estimate_entity_box(e, style) is not None
        and not (e["entity_type"] == "TEXT" and e["layer"] == "A-GRID")
    ]
    dim_ents = [e for e in entities if e["entity_type"] == "DIMENSION"]
    stair_ents = [e for e in entities if e["entity_type"] == "MTEXT" and e["layer"] == "A-STAIR"]
    room_ents = [e for e in entities if e["entity_type"] == "MTEXT" and e["layer"] == "A-ROOM-TEXT"]
    opening_ents = [
        e for e in entities if e["entity_type"] == "BLOCK_REFERENCE" and e["layer"] == "A-OPENING-TAG"
    ]

    # Stair annotations do not collide against their own stair treads.
    stair_surface_ids = {
        e["id"] for e in entities if e["layer"] in {"A-STAIR", "A-STAIR-ABOVE"} and e["entity_type"] == "POLYLINE"
    }

    # 1. Fixed grid bubbles / level marks / section annotations
    for ent in grid_fixed:
        est = _estimate_entity_box(ent, style)
        if est:
            placed_boxes.append((ent, est[0], est[1]))

    # 2. Dimensions (stagger text_point if adjacent chain texts or walls overlap)
    for ent in dim_ents:
        est = _estimate_entity_box(ent, style)
        if not est:
            continue
        base_box, kind = est
        tx, ty = ent["coordinates"]["text_point"]
        if not allow_repo or not overlaps_any(base_box):
            placed_boxes.append((ent, base_box, kind))
            continue
        orient = ent.get("metadata", {}).get("orientation", "horizontal")
        step = dh * 1.25
        shifts = (
            [
                (0.0, 0.0),
                (0.0, step),
                (0.0, -step),
                (0.0, 2.0 * step),
                (0.0, -2.0 * step),
                (step * 1.5, 0.0),
                (-step * 1.5, 0.0),
            ]
            if orient == "horizontal"
            else [
                (0.0, 0.0),
                (-step, 0.0),
                (step, 0.0),
                (-2.0 * step, 0.0),
                (2.0 * step, 0.0),
                (0.0, step * 1.5),
                (0.0, -step * 1.5),
            ]
        )[:max_attempts]
        chosen_box = base_box
        for idx, (dx, dy) in enumerate(shifts):
            cand = _shift_entity_box(base_box, dx, dy)
            if not overlaps_any(cand):
                chosen_box = cand
                if idx > 0:
                    ent["coordinates"]["text_point"] = [tx + dx, ty + dy]
                    adjustments.append(
                        {
                            "entity_id": ent["id"],
                            "view_id": view_id,
                            "category": "dimension_label",
                            "original_point": [tx, ty],
                            "placed_point": [tx + dx, ty + dy],
                            "attempt": idx + 1,
                            "used_leader": False,
                        }
                    )
                break
        placed_boxes.append((ent, chosen_box, kind))

    # 3. Stair callouts
    for ent in stair_ents:
        est = _estimate_entity_box(ent, style)
        if not est:
            continue
        base_box, kind = est
        ix, iy = ent["coordinates"]["insert"]
        if not allow_repo or not overlaps_any(base_box, allow_geom=stair_surface_ids):
            placed_boxes.append((ent, base_box, kind))
            continue
        shifts = [
            (0.0, 0.0),
            (0.0, th * 1.5),
            (0.0, -th * 1.5),
            (-th * 2.0, 0.0),
            (th * 2.0, 0.0),
            (-th * 3.5, 0.0),
            (-th * 5.0, 0.0),
            (th * 3.5, 0.0),
        ][:max_attempts]
        chosen_box = base_box
        for idx, (dx, dy) in enumerate(shifts):
            cand = _shift_entity_box(base_box, dx, dy)
            if not overlaps_any(cand, allow_geom=stair_surface_ids):
                chosen_box = cand
                if idx > 0:
                    ent["coordinates"]["insert"] = [ix + dx, iy + dy]
                    adjustments.append(
                        {
                            "entity_id": ent["id"],
                            "view_id": view_id,
                            "category": "stair_annotation",
                            "original_point": [ix, iy],
                            "placed_point": [ix + dx, iy + dy],
                            "attempt": idx + 1,
                            "used_leader": False,
                        }
                    )
                break
        placed_boxes.append((ent, chosen_box, kind))

    # 4. Room labels (bounded interior shifts, optional leader callout if room is narrow)
    room_by_eid = {r["entity_id"]: r for r in (room_records or [])}
    callout_y_cursor_right = ey1 - th * 2.0
    for ent in room_ents:
        est = _estimate_entity_box(ent, style)
        if not est:
            continue
        base_box, kind = est
        ix, iy = ent["coordinates"]["insert"]
        rid = ent["source_geometry_id"]
        c_poly = clear_room_polys.get(rid)
        if not allow_repo:
            placed_boxes.append((ent, base_box, kind))
            continue

        # Generate interior candidate shifts within room bounds
        r_w = (c_poly.bounds[2] - c_poly.bounds[0]) if c_poly else th * 4.0
        r_h = (c_poly.bounds[3] - c_poly.bounds[1]) if c_poly else th * 4.0
        interior_shifts = [
            (0.0, 0.0),
            (0.0, r_h * 0.14),
            (0.0, -r_h * 0.14),
            (r_w * 0.12, 0.0),
            (-r_w * 0.12, 0.0),
            (0.0, r_h * 0.24),
            (0.0, -r_h * 0.24),
        ]
        found_interior = False
        chosen_box = base_box
        for idx, (dx, dy) in enumerate(interior_shifts[:max_attempts]):
            cand = _shift_entity_box(base_box, dx, dy)
            pt_ok = True if c_poly is None else c_poly.contains(cand.centroid)
            if pt_ok and not overlaps_any(cand):
                chosen_box = cand
                found_interior = True
                if idx > 0:
                    ent["coordinates"]["insert"] = [ix + dx, iy + dy]
                    if ent["id"] in room_by_eid:
                        room_by_eid[ent["id"]]["placed_point"] = [ix + dx, iy + dy]
                    adjustments.append(
                        {
                            "entity_id": ent["id"],
                            "view_id": view_id,
                            "category": "room_label",
                            "original_point": [ix, iy],
                            "placed_point": [ix + dx, iy + dy],
                            "attempt": idx + 1,
                            "used_leader": False,
                        }
                    )
                break

        if not found_interior and allow_leader:
            # Place clean outside callout beyond outer dimension chains with leader line.
            bw = base_box.bounds[2] - base_box.bounds[0]
            bh = base_box.bounds[3] - base_box.bounds[1]
            tx = ex1 + dim_offset + sizing["chain_spacing"] + dh * 2.5 + bw * 0.5
            for attempt_k in range(max_attempts):
                ty = iy + (attempt_k // 2) * (bh + th) * (1 if attempt_k % 2 == 0 else -1)
                if ty > ey1:
                    ty = callout_y_cursor_right
                cand = _shift_entity_box(base_box, tx - ix, ty - iy)
                if not overlaps_any(cand):
                    chosen_box = cand
                    ent["coordinates"]["insert"] = [tx, ty]
                    if ent["id"] in room_by_eid:
                        room_by_eid[ent["id"]]["placed_point"] = [tx, ty]
                        room_by_eid[ent["id"]]["used_leader"] = True
                    leader_entities.append(
                        make_entity(
                            entity_type="LINE",
                            coordinates={"start": [ix, iy], "end": [tx - bw * 0.5, ty]},
                            view_id=view_id,
                            floor_id=floor_id,
                            layer="A-ROOM-TEXT",
                            style_ref=ent["style_ref"],
                            source_geometry_id=rid,
                            source_revision_digest=src_rev,
                            provenance=ent["provenance"],
                            key_tag=f"room_leader_{rid}",
                            metadata={"role": "annotation_leader"},
                        )
                    )
                    adjustments.append(
                        {
                            "entity_id": ent["id"],
                            "view_id": view_id,
                            "category": "room_label",
                            "original_point": [ix, iy],
                            "placed_point": [tx, ty],
                            "attempt": len(interior_shifts) + attempt_k + 1,
                            "used_leader": True,
                        }
                    )
                    found_interior = True
                    break
            callout_y_cursor_right -= bh + th * 1.2

        placed_boxes.append((ent, chosen_box, kind))

    # 5. Opening tags (try +normal, -normal, tangent shifts, optional margin leader)
    op_by_eid = {r["entity_id"]: r for r in (opening_records or [])}
    for ent in opening_ents:
        est = _estimate_entity_box(ent, style)
        if not est:
            continue
        base_box, kind = est
        ix, iy = ent["coordinates"]["insert"]
        if not allow_repo or not overlaps_any(base_box):
            placed_boxes.append((ent, base_box, kind))
            continue

        rec = op_by_eid.get(ent["id"])
        anchor = rec["anchor_wall_point"] if rec else [ix, iy]
        nx, ny = rec["normal_vec"] if rec else [0.0, 1.0]
        tx_vec, ty_vec = -ny, nx
        d0 = math.hypot(ix - anchor[0], iy - anchor[1]) or th * 2.0
        candidates: list[tuple[float, float]] = [(ix, iy)]
        for mult in (1.0, -1.0, 1.85, -1.85):
            for tang in (0.0, 1.6 * th, -1.6 * th, 3.2 * th, -3.2 * th):
                px = anchor[0] + nx * (d0 * mult) + tx_vec * tang
                py = anchor[1] + ny * (d0 * mult) + ty_vec * tang
                candidates.append((px, py))

        chosen_box = base_box
        placed_ok = False
        for idx, (cx, cy) in enumerate(candidates[:max_attempts]):
            cand = _shift_entity_box(base_box, cx - ix, cy - iy)
            if not overlaps_any(cand):
                chosen_box = cand
                placed_ok = True
                if idx > 0:
                    ent["coordinates"]["insert"] = [cx, cy]
                    if rec:
                        rec["placed_point"] = [cx, cy]
                    adjustments.append(
                        {
                            "entity_id": ent["id"],
                            "view_id": view_id,
                            "category": "opening_tag",
                            "original_point": [ix, iy],
                            "placed_point": [cx, cy],
                            "attempt": idx + 1,
                            "used_leader": False,
                        }
                    )
                break

        if not placed_ok and allow_leader:
            bw = base_box.bounds[2] - base_box.bounds[0]
            cx = ex1 + dim_offset + sizing["chain_spacing"] + dh * 2.5 + bw * 0.5
            for k in range(max_attempts):
                cy = anchor[1] + (k // 2) * (th * 2.8) * (1 if k % 2 == 0 else -1)
                cand = _shift_entity_box(base_box, cx - ix, cy - iy)
                if not overlaps_any(cand):
                    chosen_box = cand
                    ent["coordinates"]["insert"] = [cx, cy]
                    if rec:
                        rec["placed_point"] = [cx, cy]
                    leader_entities.append(
                        make_entity(
                            entity_type="LINE",
                            coordinates={"start": anchor, "end": [cx - bw * 0.5, cy]},
                            view_id=view_id,
                            floor_id=floor_id,
                            layer="A-OPENING-TAG",
                            style_ref=ent["style_ref"],
                            source_geometry_id=ent["source_geometry_id"],
                            source_revision_digest=src_rev,
                            provenance=ent["provenance"],
                            key_tag=f"op_leader_{ent['source_geometry_id']}",
                            metadata={"role": "annotation_leader"},
                        )
                    )
                    adjustments.append(
                        {
                            "entity_id": ent["id"],
                            "view_id": view_id,
                            "category": "opening_tag",
                            "original_point": [ix, iy],
                            "placed_point": [cx, cy],
                            "attempt": max_attempts + k + 1,
                            "used_leader": True,
                        }
                    )
                    break

        placed_boxes.append((ent, chosen_box, kind))

    entities.extend(leader_entities)

    # 6. Final deterministic collision audit pass (never hides unresolved overlaps!)
    collisions: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    attempted_count = max_attempts if allow_repo else 1

    # Annotation vs building geometry obstacles
    for ent, abox, _ in placed_boxes:
        if ent["entity_type"] == "CIRCLE" and ent["layer"] == "A-GRID":
            continue
        is_stair_ann = ent["layer"] == "A-STAIR" and ent["entity_type"] == "MTEXT"
        for oid, gpoly in geom_obstacles:
            if is_stair_ann and oid in stair_surface_ids:
                continue
            if abox.intersects(gpoly):
                inter = abox.intersection(gpoly)
                if inter.area > 1e-6:
                    pair = tuple(sorted((ent["id"], oid)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    b = [round(v, 4) for v in inter.bounds]
                    collisions.append(
                        {
                            "id": "COL-" + canonical_digest([view_id, pair[0], pair[1]])[:12],
                            "view_id": view_id,
                            "collision_kind": "EXACT_GEOMETRIC",
                            "category": f"{_annotation_category(ent)}_vs_geometry",
                            "entity_a": ent["id"],
                            "entity_b": oid,
                            "overlap_box": b,
                            "attempted_placements": attempted_count,
                            "status": "UNRESOLVED",
                        }
                    )

    # Annotation vs annotation (approximate text bounds)
    for i in range(len(placed_boxes)):
        ent_a, box_a, kind_a = placed_boxes[i]
        for j in range(i + 1, len(placed_boxes)):
            ent_b, box_b, kind_b = placed_boxes[j]
            if box_a.intersects(box_b):
                inter = box_a.intersection(box_b)
                if inter.area > 1e-6:
                    pair = tuple(sorted((ent_a["id"], ent_b["id"])))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    b = [round(v, 4) for v in inter.bounds]
                    ckind = (
                        "EXACT_GEOMETRIC"
                        if kind_a == "EXACT_GEOMETRIC" and kind_b == "EXACT_GEOMETRIC"
                        else "APPROXIMATE_TEXT_BOUNDS"
                    )
                    collisions.append(
                        {
                            "id": "COL-" + canonical_digest([view_id, pair[0], pair[1]])[:12],
                            "view_id": view_id,
                            "collision_kind": ckind,
                            "category": f"{_annotation_category(ent_a)}_vs_{_annotation_category(ent_b)}",
                            "entity_a": ent_a["id"],
                            "entity_b": ent_b["id"],
                            "overlap_box": b,
                            "attempted_placements": attempted_count,
                            "status": "UNRESOLVED",
                        }
                    )

    # Emit visible A-REVIEW highlight boxes for every unresolved collision
    for col in collisions:
        x0, y0, x1, y1 = col["overlap_box"]
        pad = dh * 0.15
        entities.append(
            make_entity(
                entity_type="POLYLINE",
                coordinates={
                    "exterior": [
                        [x0 - pad, y0 - pad],
                        [x1 + pad, y0 - pad],
                        [x1 + pad, y1 + pad],
                        [x0 - pad, y1 + pad],
                        [x0 - pad, y0 - pad],
                    ],
                    "holes": [],
                    "closed": True,
                },
                view_id=view_id,
                floor_id=floor_id,
                layer="A-REVIEW",
                style_ref=style["name"],
                source_geometry_id=col["id"],
                source_revision_digest=src_rev,
                provenance="collision_audit",
                key_tag=f"collision_box_{col['id']}",
                metadata={"role": "unresolved_collision_marker", "collision_id": col["id"]},
            )
        )

    return collisions, adjustments
