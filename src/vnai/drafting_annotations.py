"""Geometry extraction, room/opening/stair annotations and source-grounded reference symbols."""

from fractions import Fraction
import heapq
import math
from typing import Any

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from vnai.drafting_dimensions import _rect_exact_bounds_dec
from vnai.drafting_ir import arc_angles_deg, make_entity
from vnai.drafting_styles import convert_length, convert_point, convert_points, dec, format_measurement, zero_float
from vnai.opening_hosts import shape_set
from vnai.stair_clearance import wall_prisms
from vnai.stair_geometry import exact
from vnai.wall_topology import polygons


def _polylabel_interior(shape: Any) -> Point:
    """Return a strictly-interior point deterministically across OS and Python versions."""
    if shape.is_empty:
        return Point(0.0, 0.0)
    parts = polygons(shape)
    if not parts:
        return shape.representative_point()
    largest = max(
        parts,
        key=lambda p: (
            round(p.area, 9),
            round(p.bounds[0], 9),
            round(p.bounds[1], 9),
            round(p.bounds[2], 9),
            round(p.bounds[3], 9),
        ),
    )
    rect = _rect_exact_bounds_dec(largest)
    if rect is not None:
        rx0, ry0, rx1, ry1 = rect
        pt = Point(float((rx0 + rx1) / 2), float((ry0 + ry1) / 2))
        if largest.contains(pt):
            return pt

    minx, miny, maxx, maxy = largest.bounds
    cell_size = min(maxx - minx, maxy - miny)
    if cell_size <= 0:
        return largest.representative_point()

    def signed_dist(x: float, y: float) -> float:
        p = Point(x, y)
        d = float(largest.exterior.distance(p))
        for hole in largest.interiors:
            d = min(d, float(hole.distance(p)))
        return d if largest.contains(p) else -d

    h = cell_size / 2.0
    heap: list[tuple[float, float, float, float, float, float]] = []

    def push_cell(cx: float, cy: float, half: float) -> None:
        d = signed_dist(cx, cy)
        max_d = d + half * math.sqrt(2.0)
        heapq.heappush(
            heap, (-round(max_d, 10), round(cx, 10), round(cy, 10), round(half, 10), d, half)
        )

    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            push_cell(x + h, y + h, h)
            y += cell_size
        x += cell_size

    best_x, best_y = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    best_d = signed_dist(best_x, best_y)
    tol = min(0.01, cell_size * 0.02)
    pops = 0
    while heap and pops < 512:
        pops += 1
        neg_max, cx, cy, _, d, half = heapq.heappop(heap)
        if d > best_d + 1e-12:
            best_d, best_x, best_y = d, cx, cy
        if (-neg_max) - best_d <= tol:
            continue
        nh = half / 2.0
        for dx, dy in ((-nh, -nh), (nh, -nh), (-nh, nh), (nh, nh)):
            push_cell(cx + dx, cy + dy, nh)

    cand = Point(best_x, best_y)
    if largest.contains(cand):
        return cand
    return largest.representative_point()


def _resolve_north_orientation(context: dict[str, Any], raw_input: dict[str, Any]) -> dict[str, Any]:
    """Resolve confirmed true-north orientation or report explicitly unresolved."""
    override = raw_input.get("orientation_override")
    if override is not None:
        if override.get("confirmation") == "confirmed":
            return {
                "resolved": True,
                "north_degrees": float(override["north_degrees"]),
                "source": "orientation_override",
                "provenance": override["provenance"],
            }
        return {
            "resolved": False,
            "reason": "Supplied orientation_override is not confirmed.",
            "code": "NORTH_ORIENTATION_UNCONFIRMED",
        }
    brief = context.get("brief") or {}
    site = brief.get("site") or {}
    north_entry = site.get("north_degrees")
    if isinstance(north_entry, dict) and north_entry.get("value") is not None:
        req_id = north_entry.get("requirement_id")
        req = next((r for r in brief.get("requirements", []) if r.get("id") == req_id), None)
        if req and req.get("confirmation") == "confirmed":
            return {
                "resolved": True,
                "north_degrees": float(north_entry["value"]),
                "source": f"brief.site.north_degrees ({req_id})",
                "provenance": req.get("origin", "source_design_brief"),
            }
        return {
            "resolved": False,
            "reason": "Brief site.north_degrees lacks confirmed requirement record.",
            "code": "NORTH_ORIENTATION_UNCONFIRMED",
        }
    return {
        "resolved": False,
        "reason": "True-north orientation not confirmed in source brief or drafting override.",
        "code": "NORTH_ORIENTATION_UNRESOLVED",
    }


def _polygon_to_coords_draw(poly: Polygon, from_unit: str, to_unit: str) -> dict[str, Any]:
    return {
        "exterior": convert_points(list(poly.exterior.coords), from_unit, to_unit),
        "holes": [convert_points(list(h.coords), from_unit, to_unit) for h in poly.interiors],
        "closed": True,
    }


def _union_walls_by_class(
    walls_list: list[dict[str, Any]],
    cut_geoms: dict[str, Any],
) -> tuple[Any, Any]:
    """Compute non-overlapping exterior and interior wall unions to prevent duplicate seams."""
    ext_parts = []
    int_parts = []
    for w in walls_list:
        geom = cut_geoms.get(w["id"])
        if geom is None:
            geom = shape_set(w["geometry"])
        if geom.is_empty:
            continue
        if w.get("classification") == "exterior":
            ext_parts.append(geom)
        else:
            int_parts.append(geom)
    ext_union = unary_union(ext_parts) if ext_parts else Polygon()
    int_union = unary_union(int_parts) if int_parts else Polygon()
    if not ext_union.is_empty and not int_union.is_empty:
        int_union = int_union.difference(ext_union)
    return ext_union, int_union


def build_floor_plan_view(
    *,
    floor_id: str,
    context: dict[str, Any],
    raw_input: dict[str, Any],
    unit_policy: dict[str, Any],
    style: dict[str, Any],
    floor_dimensions: list[dict[str, Any]],
    annotation_options: dict[str, Any],
) -> dict[str, Any]:
    """Extract CAD-neutral IR primitives and annotations for one floor plan view."""
    view_id = f"PLAN-{floor_id}"
    drawing_units = unit_policy["drawing_units"]
    precision = unit_policy["display_precision"]
    area_precision = unit_policy["display_precision_m2"]
    style_ref = style["name"]
    sizing = style["model_sizing"]
    src_rev_digest = context["source_revision_digest"]
    provenance = context["provenance"]

    candidate = context.get("candidate")
    walls_report = context.get("walls_report") or {}
    openings_report = context.get("openings_report") or {}
    stairs_report = context.get("stairs_report") or {}
    stair_spec = context.get("stair_specification") or {}
    fixed_obstacles = context.get("fixed_obstacles") or []
    conflicts = context.get("conflicts") or []
    room_labels = raw_input.get("room_labels") or {}

    entities: list[dict[str, Any]] = []
    room_ann_records: list[dict[str, Any]] = []
    opening_ann_records: list[dict[str, Any]] = []
    stair_ann_records: list[dict[str, Any]] = []
    symbol_records: dict[str, Any] = {
        "reference_grid": None,
        "level_marks": [],
        "section_markers": [],
        "scale_bar": None,
        "north_arrow": None,
    }
    unresolved_local: list[dict[str, Any]] = []

    def add(ent: dict[str, Any]) -> None:
        entities.append(ent)

    def pt_draw(pt: list[float] | tuple[float, float], from_unit: str = "m") -> list[float]:
        return convert_point(pt, from_unit, drawing_units)

    # 1. Site, Footprint, Floor Outline & Reservations (reference geometry)
    if candidate:
        c_units = candidate["geometry"]["units"]
        for p in candidate["geometry"]["polygons"]:
            if p.get("floor_id") not in (None, floor_id):
                continue
            role = p["role"]
            if role == "site":
                add(
                    make_entity(
                        entity_type="POLYLINE",
                        coordinates={
                            "exterior": convert_points(p["exterior"], c_units, drawing_units),
                            "holes": [],
                            "closed": True,
                        },
                        view_id=view_id,
                        floor_id=floor_id,
                        layer="A-GRID",
                        style_ref=style_ref,
                        source_geometry_id=p["id"],
                        source_revision_digest=src_rev_digest,
                        provenance=provenance,
                        key_tag="site_boundary",
                        metadata={"role": "site_boundary"},
                    )
                )
            elif role in {"footprint", "floor_outline"}:
                add(
                    make_entity(
                        entity_type="POLYLINE",
                        coordinates={
                            "exterior": convert_points(p["exterior"], c_units, drawing_units),
                            "holes": [],
                            "closed": True,
                        },
                        view_id=view_id,
                        floor_id=floor_id,
                        layer="A-GRID",
                        style_ref=style_ref,
                        source_geometry_id=p["id"],
                        source_revision_digest=src_rev_digest,
                        provenance=provenance,
                        key_tag=role,
                        metadata={"role": role},
                    )
                )

    # 2. Cut Walls (deduplicated unions by exterior vs interior -> zero duplicate edges!)
    floor_walls = [w for w in walls_report.get("walls", []) if w["floor_id"] == floor_id]
    op_floor = next(
        (f for f in openings_report.get("floors", []) if f["floor_id"] == floor_id), None
    )
    cut_geoms: dict[str, Any] = {}
    if op_floor:
        for w_entry in op_floor.get("walls", []):
            cut_geoms[w_entry["wall_id"]] = shape_set(w_entry["plan_geometry"])
    ext_union, int_union = _union_walls_by_class(floor_walls, cut_geoms)

    for layer, union_geom, tag in (
        ("A-WALL-EXT", ext_union, "wall_ext"),
        ("A-WALL-INT", int_union, "wall_int"),
    ):
        for idx, poly in enumerate(polygons(union_geom)):
            coords = _polygon_to_coords_draw(poly, "m", drawing_units)
            add(
                make_entity(
                    entity_type="POLYLINE",
                    coordinates=coords,
                    view_id=view_id,
                    floor_id=floor_id,
                    layer=layer,
                    style_ref=style_ref,
                    source_geometry_id=f"{floor_id}:{tag}:{idx}",
                    source_revision_digest=walls_report.get("wall_revision_id") or src_rev_digest,
                    provenance=provenance,
                    key_tag=f"{tag}_outline_{idx}",
                    metadata={"role": tag},
                )
            )
            if style.get("hatch_enabled", True):
                add(
                    make_entity(
                        entity_type="HATCH",
                        coordinates={"exterior": coords["exterior"], "holes": coords["holes"]},
                        view_id=view_id,
                        floor_id=floor_id,
                        layer="A-HATCH",
                        style_ref=style_ref,
                        source_geometry_id=f"{floor_id}:{tag}:{idx}",
                        source_revision_digest=walls_report.get("wall_revision_id") or src_rev_digest,
                        provenance=provenance,
                        key_tag=f"{tag}_hatch_{idx}",
                        metadata={"pattern": "ANSI31", "role": tag},
                    )
                )

    # 3. Fixed obstacles (explicitly on A-REVIEW)
    for obs in fixed_obstacles:
        if obs.get("floor_id") != floor_id:
            continue
        obs_units = obs.get("units", candidate["geometry"]["units"] if candidate else "m")
        pts_d = convert_points(obs["exterior"], obs_units, drawing_units)
        add(
            make_entity(
                entity_type="POLYLINE",
                coordinates={"exterior": pts_d, "holes": [], "closed": True},
                view_id=view_id,
                floor_id=floor_id,
                layer="A-REVIEW",
                style_ref=style_ref,
                source_geometry_id=obs["id"],
                source_revision_digest=src_rev_digest,
                provenance=provenance,
                key_tag="fixed_obstacle",
                metadata={"role": "fixed_obstacle"},
            )
        )

    # 4. Openings geometry & tags (analytic ARC preserved!)
    schedule_by_mark = {
        (s["mark"], s["floor_id"]): s for s in openings_report.get("schedule", [])
    }
    floor_openings = [
        o for o in openings_report.get("openings", []) if o["floor_id"] == floor_id
    ]
    for op in sorted(floor_openings, key=lambda o: o["id"]):
        is_window = op["type"].endswith("window")
        geom_layer = "A-WIND" if is_window else "A-DOOR"
        op_rev = openings_report.get("opening_revision_id") or src_rev_digest
        prims = op.get("primitives", {})
        for part_key in ("frame", "frame_outline", "open_leaf", "closed_leaf"):
            pset = prims.get(part_key)
            if isinstance(pset, dict) and pset.get("type") == "PolygonSet":
                for idx, poly in enumerate(polygons(shape_set(pset))):
                    add(
                        make_entity(
                            entity_type="POLYLINE",
                            coordinates=_polygon_to_coords_draw(poly, "m", drawing_units),
                            view_id=view_id,
                            floor_id=floor_id,
                            layer=geom_layer,
                            style_ref=style_ref,
                            source_geometry_id=op["id"],
                            source_revision_digest=op_rev,
                            provenance=op["provenance"],
                            key_tag=f"{part_key}_{idx}",
                            metadata={"opening_part": part_key, "opening_type": op["type"]},
                        )
                    )
        if "glazing" in prims and "start" in prims["glazing"]:
            g = prims["glazing"]
            add(
                make_entity(
                    entity_type="LINE",
                    coordinates={"start": pt_draw(g["start"]), "end": pt_draw(g["end"])},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-WIND",
                    style_ref=style_ref,
                    source_geometry_id=op["id"],
                    source_revision_digest=op_rev,
                    provenance=op["provenance"],
                    key_tag="glazing_line",
                    metadata={"role": "glazing"},
                )
            )
        if "track" in prims:
            tr = prims["track"]
            ts, te = pt_draw(tr["start"]), pt_draw(tr["end"])
            add(
                make_entity(
                    entity_type="LINE",
                    coordinates={"start": ts, "end": te},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-DOOR-SWING",
                    style_ref=style_ref,
                    source_geometry_id=op["id"],
                    source_revision_digest=op_rev,
                    provenance=op["provenance"],
                    key_tag="sliding_track",
                    metadata={"role": "sliding_track"},
                )
            )
            add(
                make_entity(
                    entity_type="SYMBOL",
                    coordinates={"insert": te, "direction_start": ts, "direction_end": te},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-DOOR-SWING",
                    style_ref=style_ref,
                    source_geometry_id=op["id"],
                    source_revision_digest=op_rev,
                    provenance=op["provenance"],
                    key_tag="sliding_arrow",
                    metadata={"symbol_kind": "slide_direction"},
                )
            )
        if "swing_arc" in prims:
            arc = prims["swing_arc"]
            center_d = pt_draw(arc["center"])
            start_d = pt_draw(arc["start"])
            end_d = pt_draw(arc["end"])
            radius_d = zero_float(convert_length(arc["radius_m"], "m", drawing_units))
            a0, a1 = arc_angles_deg(center_d, start_d, end_d)
            add(
                make_entity(
                    entity_type="ARC",
                    coordinates={
                        "center": center_d,
                        "radius": radius_d,
                        "start_angle_deg": a0,
                        "end_angle_deg": a1,
                        "start_point": start_d,
                        "end_point": end_d,
                        "rotation": arc["rotation"],
                    },
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-DOOR-SWING",
                    style_ref=style_ref,
                    source_geometry_id=op["id"],
                    source_revision_digest=op_rev,
                    provenance=op["provenance"],
                    key_tag="swing_arc",
                    metadata={"analytic": True, "angle_degrees": arc["angle_degrees"]},
                )
            )

        # Opening Tag annotation (grounded in actual opening & schedule)
        sched = schedule_by_mark.get((op["mark"], floor_id))
        ref = op.get("reference")
        if ref:
            mid_m = [
                (ref["start"][0] + ref["end"][0]) / 2.0,
                (ref["start"][1] + ref["end"][1]) / 2.0,
            ]
            dx_r = ref["end"][0] - ref["start"][0]
            dy_r = ref["end"][1] - ref["start"][1]
            r_len = math.hypot(dx_r, dy_r) or 1.0
            normal_m = (-dy_r / r_len, dx_r / r_len)
            # Default tag offset perpendicular to wall
            tag_off_m = 0.45 if is_window else 0.48
            insert_d = pt_draw([mid_m[0] + normal_m[0] * tag_off_m, mid_m[1] + normal_m[1] * tag_off_m])
        else:
            insert_d = [0.0, 0.0]

        dim_basis = annotation_options.get("opening_dimension_basis", "rough_and_clear")
        dim_sub = ""
        if annotation_options.get("show_opening_dimensions", True) and dim_basis != "none":
            r_str = (
                format_measurement(convert_length(op["rough_width_m"], "m", drawing_units), precision)[0]
                if op.get("rough_width_m") is not None
                else None
            )
            c_str = (
                format_measurement(convert_length(op["clear_width_m"], "m", drawing_units), precision)[0]
                if op.get("clear_width_m") is not None
                else None
            )
            if dim_basis == "rough" and r_str:
                dim_sub = f"R:{r_str}"
            elif dim_basis == "clear" and c_str:
                dim_sub = f"C:{c_str}"
            elif dim_basis == "rough_and_clear":
                if r_str and c_str:
                    dim_sub = f"R{r_str}/C{c_str}"
                elif r_str:
                    dim_sub = f"R{r_str}"

        block_name = "TAG_WINDOW" if is_window else "TAG_DOOR"
        tag_ent = make_entity(
            entity_type="BLOCK_REFERENCE",
            coordinates={"insert": insert_d, "scale": 1.0, "rotation_deg": 0.0},
            view_id=view_id,
            floor_id=floor_id,
            layer="A-OPENING-TAG",
            style_ref=style_ref,
            source_geometry_id=op["id"],
            source_revision_digest=op_rev,
            provenance=op["provenance"],
            key_tag="opening_tag_block",
            metadata={
                "block_name": block_name,
                "mark": op["mark"],
                "dimension_label": dim_sub,
                "rough_width_m": op.get("rough_width_m"),
                "leaf_width_m": prims.get("leaf_width_m"),
                "clear_width_m": op.get("clear_width_m"),
                "schedule_digest": sched["specification_digest"] if sched else None,
            },
        )
        add(tag_ent)
        opening_ann_records.append(
            {
                "entity_id": tag_ent["id"],
                "opening_id": op["id"],
                "mark": op["mark"],
                "type": op["type"],
                "floor_id": floor_id,
                "rough_width": zero_float(convert_length(op["rough_width_m"], "m", drawing_units))
                if op.get("rough_width_m") is not None
                else None,
                "leaf_width": zero_float(convert_length(prims["leaf_width_m"], "m", drawing_units))
                if prims.get("leaf_width_m") is not None
                else None,
                "clear_width": zero_float(convert_length(op["clear_width_m"], "m", drawing_units))
                if op.get("clear_width_m") is not None
                else None,
                "measurement_unit": drawing_units,
                "schedule_specification_digest": sched["specification_digest"] if sched else None,
                "anchor_wall_point": pt_draw(mid_m) if ref else insert_d,
                "normal_vec": list(normal_m) if ref else [0.0, 1.0],
                "placed_point": list(insert_d),
            }
        )

    # 5. Stair Plan Geometry & Annotations (reusing B3 surfaces, cut classifications, walking lines)
    stair_rev = stairs_report.get("stair_revision_id") or src_rev_digest
    number_steps = bool(
        annotation_options.get("number_steps", stair_spec.get("number_steps", False))
    )
    for stair in stairs_report.get("stairs", []):
        if floor_id not in (stair["source_floor"], stair["destination_floor"]):
            continue
        pv = next((v for v in stair.get("plan_views", []) if v["floor_id"] == floor_id), None)
        cut_elev = pv["cut_elevation_m"] if pv else None
        surf_classes = (
            {sc["surface_id"]: sc["classification"] for sc in pv.get("surface_classes", [])}
            if pv
            else {}
        )
        ascending = floor_id == stair["source_floor"]
        for surf in stair["surfaces"]:
            cls = surf_classes.get(surf["id"])
            above = cls == "ABOVE_CUT" or (
                cls is None and (cut_elev is None or surf["elevation_m"] > cut_elev)
            )
            layer = "A-STAIR-ABOVE" if above else "A-STAIR"
            for idx, poly in enumerate(polygons(shape_set(surf["geometry"]))):
                add(
                    make_entity(
                        entity_type="POLYLINE",
                        coordinates=_polygon_to_coords_draw(poly, "m", drawing_units),
                        view_id=view_id,
                        floor_id=floor_id,
                        layer=layer,
                        style_ref=style_ref,
                        source_geometry_id=surf["id"],
                        source_revision_digest=stair_rev,
                        provenance=stair.get("provenance", provenance),
                        key_tag=f"stair_surf_{idx}",
                        metadata={"surface_kind": surf["kind"], "above_cut": above},
                    )
                )
            if number_steps and surf["kind"] == "tread" and not above:
                tp_m = _polylabel_interior(shape_set(surf["geometry"]))
                fl = next(f for f in stair["flights"] if f["id"] == surf["flight_id"])
                u = fl["direction"]
                norm = (-u[1], u[0])
                np_d = pt_draw([tp_m.x + norm[0] * fl["width_m"] * 0.25, tp_m.y + norm[1] * fl["width_m"] * 0.25])
                add(
                    make_entity(
                        entity_type="TEXT",
                        coordinates={"insert": np_d},
                        view_id=view_id,
                        floor_id=floor_id,
                        layer=layer,
                        style_ref=style_ref,
                        source_geometry_id=surf["id"],
                        source_revision_digest=stair_rev,
                        provenance=stair.get("provenance", provenance),
                        key_tag="step_num",
                        metadata={
                            "text": surf["id"].rsplit("-T", 1)[-1],
                            "height": sizing["dim_text_height"] * 0.65,
                            "anchor": "middle",
                            "rotation_deg": 0.0,
                        },
                    )
                )

        # Walking line & UP/DOWN arrows
        direction_label = "UP" if ascending else "DOWN"
        for fl in stair["flights"]:
            pts = fl["walking_line"] if ascending else list(reversed(fl["walking_line"]))
            pts_d = convert_points(pts, "m", drawing_units)
            add(
                make_entity(
                    entity_type="POLYLINE",
                    coordinates={"exterior": pts_d, "holes": [], "closed": False},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-STAIR",
                    style_ref=style_ref,
                    source_geometry_id=fl["id"],
                    source_revision_digest=stair_rev,
                    provenance=stair.get("provenance", provenance),
                    key_tag="walking_line",
                    metadata={"direction": direction_label},
                )
            )
            add(
                make_entity(
                    entity_type="SYMBOL",
                    coordinates={
                        "insert": pts_d[-1],
                        "from_point": pts_d[-2],
                        "to_point": pts_d[-1],
                    },
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-STAIR",
                    style_ref=style_ref,
                    source_geometry_id=fl["id"],
                    source_revision_digest=stair_rev,
                    provenance=stair.get("provenance", provenance),
                    key_tag="stair_arrow",
                    metadata={"symbol_kind": "stair_direction_arrow", "direction": direction_label},
                )
            )

        # Stair text label centered inside footprint when possible
        st_fp = shape_set(stair["footprint"])
        st_centroid = st_fp.centroid
        st_pt = st_centroid if st_fp.contains(st_centroid) else _polylabel_interior(st_fp)
        st_ins = pt_draw([st_pt.x, st_pt.y])
        fl0 = stair["flights"][0]
        risers_total = sum(f["risers"] for f in stair["flights"])
        rh_str = format_measurement(convert_length(fl0["riser_height_m"], "m", drawing_units), precision)[0]
        td_str = format_measurement(convert_length(fl0["tread_depth_m"], "m", drawing_units), precision)[0]
        mark = stair.get("mark") or stair["id"]
        lines = [
            f"{mark} ({direction_label})",
            f"{risers_total}R x {rh_str} / T {td_str}",
        ]
        st_label = make_entity(
            entity_type="MTEXT",
            coordinates={"insert": st_ins},
            view_id=view_id,
            floor_id=floor_id,
            layer="A-STAIR",
            style_ref=style_ref,
            source_geometry_id=stair["id"],
            source_revision_digest=stair_rev,
            provenance=stair.get("provenance", provenance),
            key_tag="stair_callout",
            metadata={
                "lines": lines,
                "height": sizing["dim_text_height"] * 0.85,
                "anchor": "middle",
                "line_spacing": 1.25,
            },
        )
        add(st_label)
        stair_ann_records.append(
            {
                "entity_id": st_label["id"],
                "stair_id": stair["id"],
                "mark": mark,
                "floor_id": floor_id,
                "direction": direction_label,
                "risers": risers_total,
                "riser_height": zero_float(convert_length(fl0["riser_height_m"], "m", drawing_units)),
                "tread_depth": zero_float(convert_length(fl0["tread_depth_m"], "m", drawing_units)),
                "flight_ids": [f["id"] for f in stair["flights"]],
                "landing_elevations": [
                    zero_float(convert_length(s["elevation_m"], "m", drawing_units))
                    for s in stair["surfaces"]
                    if s["kind"] == "landing"
                ],
                "placed_point": list(st_ins),
            }
        )

    # Floor openings (stairwell void on destination floor)
    for fop in stair_spec.get("floor_openings", []):
        if fop["floor_id"] != floor_id:
            continue
        fop_unit = stair_spec.get("units", "m")
        for idx, poly in enumerate(polygons(shape_set(fop["geometry"]))):
            add(
                make_entity(
                    entity_type="POLYLINE",
                    coordinates=_polygon_to_coords_draw(poly, fop_unit, drawing_units),
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-STAIR-ABOVE",
                    style_ref=style_ref,
                    source_geometry_id=fop["id"],
                    source_revision_digest=stair_rev,
                    provenance=provenance,
                    key_tag=f"floor_void_{idx}",
                    metadata={"role": "floor_opening_void"},
                )
            )

    # 6. Room Labels (strict interior placement, Vietnamese Unicode, clear vs allocated)
    conflict_rooms = {
        eid
        for c in conflicts
        if c.get("severity") in {"FAILED", "UNKNOWN", "UNSUPPORTED"}
        for eid in c.get("entity_ids", [])
    }
    for room in sorted(walls_report.get("rooms", []), key=lambda r: r["room_id"]):
        if room["floor_id"] != floor_id:
            continue
        clear_poly = shape_set(room["clear_geometry"])
        use_poly = clear_poly if not clear_poly.is_empty else shape_set(room["allocation_geometry"])
        pt_m = _polylabel_interior(use_poly)
        ins_d = pt_draw([pt_m.x, pt_m.y])
        rid = room["room_id"]
        # Use explicitly supplied label or room_id; never fabricate room names.
        display_name = room_labels.get(rid, rid)
        clr_area_str, _, _ = format_measurement(dec(room["clear_area_m2"]), area_precision)
        lines = [display_name]
        if display_name != rid:
            lines.append(f"[{rid}]")
        lines.append(f"Clear: {clr_area_str} m\u00b2")
        if annotation_options.get("show_room_dimensions", True):
            rect = _rect_exact_bounds_dec(clear_poly)
            if rect is not None:
                rx0, ry0, rx1, ry1 = rect
                rw_str = format_measurement(convert_length(rx1 - rx0, "m", drawing_units), precision)[0]
                rl_str = format_measurement(convert_length(ry1 - ry0, "m", drawing_units), precision)[0]
                lines.append(f"{rw_str} x {rl_str} {drawing_units}")
        has_conflict = rid in conflict_rooms
        if has_conflict:
            lines.append("! CONFLICT")

        room_ent = make_entity(
            entity_type="MTEXT",
            coordinates={"insert": ins_d},
            view_id=view_id,
            floor_id=floor_id,
            layer="A-ROOM-TEXT",
            style_ref=style_ref,
            source_geometry_id=rid,
            source_revision_digest=walls_report.get("wall_revision_id") or src_rev_digest,
            provenance=provenance,
            key_tag="room_label",
            metadata={
                "lines": lines,
                "height": sizing["text_height"],
                "anchor": "middle",
                "line_spacing": 1.3,
                "clear_area_m2": room["clear_area_m2"],
                "allocation_area_m2": room["allocation_area_m2"],
                "area_basis": "clear_room_interior",
                "conflict_marker": has_conflict,
            },
        )
        add(room_ent)
        room_ann_records.append(
            {
                "entity_id": room_ent["id"],
                "room_id": rid,
                "display_name": display_name,
                "floor_id": floor_id,
                "clear_area_m2": room["clear_area_m2"],
                "allocation_area_m2": room["allocation_area_m2"],
                "area_basis": "clear_room_interior",
                "interior_point": list(ins_d),
                "centroid_inside_clear": bool(use_poly.contains(use_poly.centroid)),
                "interior_point_verified_inside": bool(use_poly.contains(pt_m)),
                "conflict_marker": has_conflict,
                "placed_point": list(ins_d),
                "used_leader": False,
            }
        )

    # 7. Dimension primitives for this floor view (chains + wall thicknesses; openings & rooms shown in tags/labels)
    for dim in floor_dimensions:
        if dim["dimension_type"] in {"linear_horizontal", "linear_vertical"} and dim["measurement_basis"] in {
            "dimension_chain_segment",
            "dimension_chain_overall",
            "wall_thickness_actual",
        }:
            # Emit linear CAD DIMENSION primitives for chains and wall thicknesses; keep interior metric records in IR.
            add(
                make_entity(
                    entity_type="DIMENSION",
                    coordinates={
                        "ref_point_1": dim["ref_point_1"],
                        "ref_point_2": dim["ref_point_2"],
                        "line_start": dim["dim_line_location"]["start"],
                        "line_end": dim["dim_line_location"]["end"],
                        "text_point": dim["dim_line_location"]["text_point"],
                        "extension_lines": dim["extension_lines"],
                    },
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-DIMS",
                    style_ref=style_ref,
                    source_geometry_id=dim["associated_entity_ids"][0],
                    source_revision_digest=dim["source_geometry_digest"],
                    provenance=provenance,
                    key_tag=dim["id"],
                    metadata={
                        "dimension_id": dim["id"],
                        "display_text": dim["display_text"],
                        "measurement_basis": dim["measurement_basis"],
                        "orientation": "horizontal"
                        if dim["dimension_type"] == "linear_horizontal"
                        else "vertical",
                        "height": sizing["dim_text_height"],
                        "tick_style": style["tick_style"],
                        "arrow_size": sizing["arrow_size"],
                        "tier": dim.get("tier"),
                    },
                )
            )

    # 8. Reference Symbols: Grid, Section Markers, Level Marks, Scale Bar, North Arrow
    env_poly = context["floor_envelopes"].get(floor_id)
    env_bounds = env_poly.bounds if env_poly is not None else (0.0, 0.0, 4.0, 10.0)
    ex0_d, ey0_d = pt_draw([env_bounds[0], env_bounds[1]])
    ex1_d, ey1_d = pt_draw([env_bounds[2], env_bounds[3]])

    ref_grid = raw_input.get("reference_grid")
    if ref_grid:
        c_units = candidate["geometry"]["units"] if candidate else "m"
        bubble_r = sizing["grid_bubble_radius"]
        grid_ext = sizing["dim_offset"] * 2.55
        grid_role = ref_grid.get("grid_role", "architectural_reference_grid")
        if grid_role == "supplied_structural_column_grid" and not ref_grid.get("provenance"):
            unresolved_local.append(
                {
                    "code": "STRUCTURAL_GRID_PROVENANCE_MISSING",
                    "floor_id": floor_id,
                    "message": "Structural column grid claimed without explicit provenance; downgraded to architectural reference grid.",
                }
            )
            grid_role = "architectural_reference_grid"
        for ax in ref_grid.get("x_axes", []):
            gx_d = zero_float(convert_length(ax["coord_source_units"], c_units, drawing_units))
            add(
                make_entity(
                    entity_type="LINE",
                    coordinates={"start": [gx_d, ey0_d - grid_ext * 0.6], "end": [gx_d, ey1_d + grid_ext]},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-GRID",
                    style_ref=style_ref,
                    source_geometry_id=f"GRID-X-{ax['label']}",
                    source_revision_digest=src_rev_digest,
                    provenance=ref_grid.get("provenance", provenance),
                    key_tag=f"grid_line_x_{ax['label']}",
                    metadata={"grid_role": grid_role, "axis_label": ax["label"]},
                )
            )
            bc = [gx_d, ey1_d + grid_ext + bubble_r]
            add(
                make_entity(
                    entity_type="CIRCLE",
                    coordinates={"center": bc, "radius": bubble_r},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-GRID",
                    style_ref=style_ref,
                    source_geometry_id=f"GRID-X-{ax['label']}",
                    source_revision_digest=src_rev_digest,
                    provenance=ref_grid.get("provenance", provenance),
                    key_tag=f"grid_bubble_x_{ax['label']}",
                    metadata={"grid_role": grid_role, "label": ax["label"]},
                )
            )
            add(
                make_entity(
                    entity_type="TEXT",
                    coordinates={"insert": bc},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-GRID",
                    style_ref=style_ref,
                    source_geometry_id=f"GRID-X-{ax['label']}",
                    source_revision_digest=src_rev_digest,
                    provenance=ref_grid.get("provenance", provenance),
                    key_tag=f"grid_label_x_{ax['label']}",
                    metadata={
                        "text": ax["label"],
                        "height": sizing["dim_text_height"],
                        "anchor": "middle",
                        "rotation_deg": 0.0,
                    },
                )
            )
        for ax in ref_grid.get("y_axes", []):
            gy_d = zero_float(convert_length(ax["coord_source_units"], c_units, drawing_units))
            add(
                make_entity(
                    entity_type="LINE",
                    coordinates={"start": [ex0_d - grid_ext, gy_d], "end": [ex1_d + grid_ext * 0.6, gy_d]},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-GRID",
                    style_ref=style_ref,
                    source_geometry_id=f"GRID-Y-{ax['label']}",
                    source_revision_digest=src_rev_digest,
                    provenance=ref_grid.get("provenance", provenance),
                    key_tag=f"grid_line_y_{ax['label']}",
                    metadata={"grid_role": grid_role, "axis_label": ax["label"]},
                )
            )
            bc = [ex0_d - grid_ext - bubble_r, gy_d]
            add(
                make_entity(
                    entity_type="CIRCLE",
                    coordinates={"center": bc, "radius": bubble_r},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-GRID",
                    style_ref=style_ref,
                    source_geometry_id=f"GRID-Y-{ax['label']}",
                    source_revision_digest=src_rev_digest,
                    provenance=ref_grid.get("provenance", provenance),
                    key_tag=f"grid_bubble_y_{ax['label']}",
                    metadata={"grid_role": grid_role, "label": ax["label"]},
                )
            )
            add(
                make_entity(
                    entity_type="TEXT",
                    coordinates={"insert": bc},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-GRID",
                    style_ref=style_ref,
                    source_geometry_id=f"GRID-Y-{ax['label']}",
                    source_revision_digest=src_rev_digest,
                    provenance=ref_grid.get("provenance", provenance),
                    key_tag=f"grid_label_y_{ax['label']}",
                    metadata={
                        "text": ax["label"],
                        "height": sizing["dim_text_height"],
                        "anchor": "middle",
                        "rotation_deg": 0.0,
                    },
                )
            )
        symbol_records["reference_grid"] = {
            "grid_role": grid_role,
            "x_axes": [a["label"] for a in ref_grid.get("x_axes", [])],
            "y_axes": [a["label"] for a in ref_grid.get("y_axes", [])],
        }

    # Section markers
    defined_sections = {f"SECT-{s['id']}" for s in stairs_report.get("stairs", [])}
    c_units = candidate["geometry"]["units"] if candidate else "m"
    for sm in raw_input.get("section_markers", []):
        if sm["floor_id"] != floor_id:
            continue
        p0_d = convert_point(sm["start"], c_units, drawing_units)
        p1_d = convert_point(sm["end"], c_units, drawing_units)
        ref_view = sm.get("referenced_view_id")
        is_defined = ref_view in defined_sections if ref_view else False
        effective_status = (
            "DEFINED_SECTION_VIEW"
            if is_defined and sm.get("status", "DEFINED_SECTION_VIEW") == "DEFINED_SECTION_VIEW"
            else "PROPOSED_SECTION_MARKER"
        )
        add(
            make_entity(
                entity_type="SYMBOL",
                coordinates={
                    "insert": p0_d,
                    "start": p0_d,
                    "end": p1_d,
                    "look_direction": sm["look_direction"],
                },
                view_id=view_id,
                floor_id=floor_id,
                layer="A-SECT",
                style_ref=style_ref,
                source_geometry_id=sm["id"],
                source_revision_digest=src_rev_digest,
                provenance=provenance,
                key_tag=f"sect_{sm['id']}",
                metadata={
                    "symbol_kind": "section_marker",
                    "label": sm["label"],
                    "referenced_view_id": ref_view,
                    "status": effective_status,
                },
            )
        )
        symbol_records["section_markers"].append(
            {
                "id": sm["id"],
                "label": sm["label"],
                "floor_id": floor_id,
                "referenced_view_id": ref_view,
                "status": effective_status,
            }
        )

    # Level marks from confirmed floor datum
    if annotation_options.get("show_level_marks", True):
        floor_elev_m = context["floor_elevations_m"].get(floor_id)
        if floor_elev_m is not None:
            lvl_pos = [ex1_d + sizing["dim_offset"] * 0.8, ey0_d - sizing["dim_offset"] * 0.6]
            elev_str = f"{floor_elev_m:+.3f} m" if floor_elev_m != 0 else "+0.000 m"
            add(
                make_entity(
                    entity_type="BLOCK_REFERENCE",
                    coordinates={"insert": lvl_pos, "scale": 1.0, "rotation_deg": 0.0},
                    view_id=view_id,
                    floor_id=floor_id,
                    layer="A-LEVEL",
                    style_ref=style_ref,
                    source_geometry_id=floor_id,
                    source_revision_digest=src_rev_digest,
                    provenance=provenance,
                    key_tag=f"level_{floor_id}",
                    metadata={
                        "block_name": "SYM_LEVEL_MARK",
                        "label": f"FFL {floor_id}: {elev_str}",
                        "elevation_m": floor_elev_m,
                    },
                )
            )
            symbol_records["level_marks"].append(
                {"floor_id": floor_id, "elevation_m": floor_elev_m, "label": elev_str}
            )
        else:
            unresolved_local.append(
                {
                    "code": "FLOOR_ELEVATION_UNRESOLVED",
                    "floor_id": floor_id,
                    "message": f"Confirmed finished floor elevation unavailable for {floor_id}.",
                }
            )

    # Scale bar
    if annotation_options.get("show_scale_bar", True):
        bar_len = 2000.0 if drawing_units == "mm" else 2.0
        sb_start = [ex0_d, ey0_d - sizing["dim_offset"] * 2.55]
        add(
            make_entity(
                entity_type="SYMBOL",
                coordinates={"insert": sb_start, "length": bar_len},
                view_id=view_id,
                floor_id=floor_id,
                layer="A-GRID",
                style_ref=style_ref,
                source_geometry_id=floor_id,
                source_revision_digest=src_rev_digest,
                provenance=provenance,
                key_tag="scale_bar",
                metadata={
                    "symbol_kind": "scale_bar",
                    "length": bar_len,
                    "units": drawing_units,
                    "scale_denominator": style["scale_denominator"],
                },
            )
        )
        symbol_records["scale_bar"] = {
            "length": bar_len,
            "units": drawing_units,
            "scale_label": f"1:{int(style['scale_denominator']) if float(style['scale_denominator']).is_integer() else style['scale_denominator']}",
        }

    # North arrow (only if confirmed!)
    north = _resolve_north_orientation(context, raw_input)
    if north["resolved"]:
        na_pos = [ex1_d + sizing["dim_offset"] * 2.2, ey1_d + sizing["dim_offset"] * 2.8]
        add(
            make_entity(
                entity_type="BLOCK_REFERENCE",
                coordinates={
                    "insert": na_pos,
                    "scale": 1.0,
                    "rotation_deg": north["north_degrees"],
                },
                view_id=view_id,
                floor_id=floor_id,
                layer="A-GRID",
                style_ref=style_ref,
                source_geometry_id="NORTH-ARROW",
                source_revision_digest=src_rev_digest,
                provenance=north["provenance"],
                key_tag="north_arrow",
                metadata={
                    "block_name": "SYM_NORTH_ARROW",
                    "north_degrees": north["north_degrees"],
                    "source": north["source"],
                },
            )
        )
        symbol_records["north_arrow"] = {
            "status": "CONFIRMED",
            "north_degrees": north["north_degrees"],
            "source": north["source"],
        }
    else:
        symbol_records["north_arrow"] = {"status": "UNRESOLVED", "reason": north["reason"]}
        unresolved_local.append(
            {
                "code": north["code"],
                "floor_id": floor_id,
                "message": north["reason"],
            }
        )

    return {
        "view_id": view_id,
        "view_kind": "floor_plan",
        "floor_id": floor_id,
        "title": f"Floor Plan {floor_id}",
        "section_kind": None,
        "source_revision_digest": src_rev_digest,
        "entities": entities,
        "room_annotations": room_ann_records,
        "opening_annotations": opening_ann_records,
        "stair_annotations": stair_ann_records,
        "symbols": symbol_records,
        "unresolved": unresolved_local,
    }


def build_stair_section_view(
    *,
    stair: dict[str, Any],
    context: dict[str, Any],
    unit_policy: dict[str, Any],
    style: dict[str, Any],
    section_dimensions: list[dict[str, Any]],
    annotation_options: dict[str, Any],
) -> dict[str, Any]:
    """Extract CAD-neutral IR primitives and annotations for one B3 staircase section."""
    view_id = f"SECT-{stair['id']}"
    drawing_units = unit_policy["drawing_units"]
    precision = unit_policy["display_precision"]
    style_ref = style["name"]
    sizing = style["model_sizing"]
    stairs_report = context["stairs_report"]
    stair_rev = stairs_report.get("stair_revision_id") or context["source_revision_digest"]
    provenance = stair.get("provenance", context["provenance"])
    stair_spec = context.get("stair_specification") or {}
    openings_model = stairs_report.get("sources", {}).get("opening_model", {})

    entities: list[dict[str, Any]] = []

    def add(ent: dict[str, Any]) -> None:
        entities.append(ent)

    def pt_draw(pt: list[float] | tuple[float, float]) -> list[float]:
        return convert_point(pt, "m", drawing_units)

    # 1. Stepped profile from B3 sections (exact true or developed section preserved!)
    all_x: list[float] = []
    for sec in stair.get("sections", []):
        pts_d = convert_points(sec["profile"], "m", drawing_units)
        all_x.extend(p[0] for p in pts_d)
        add(
            make_entity(
                entity_type="POLYLINE",
                coordinates={"exterior": pts_d, "holes": [], "closed": False},
                view_id=view_id,
                floor_id=None,
                layer="A-STAIR",
                style_ref=style_ref,
                source_geometry_id=sec["id"],
                source_revision_digest=stair_rev,
                provenance=provenance,
                key_tag=f"section_profile_{sec['id']}",
                metadata={"section_kind": stair["section_kind"]},
            )
        )

    min_x_d = min(all_x) if all_x else 0.0
    max_x_d = max(all_x) if all_x else 1.0

    # 2. Modeled slab/wall/obstacle projections onto section paths (reusing B3 wall_prisms)
    from shapely.geometry import LineString

    scalar = Fraction(1) if stair_spec.get("units", "m") == "m" else Fraction(1, 1000)
    levels = {
        r["floor_id"]: exact(r["finished_elevation"], scalar)
        for r in stair_spec.get("levels", [])
        if "finished_elevation" in r and r.get("confirmation") == "confirmed"
    }
    walls_prisms, _ = wall_prisms(openings_model, levels) if openings_model and levels else ([], [])
    obstructions = (
        stairs_report.get("sources", {}).get("slab_material", [])
        + walls_prisms
        + [
            {
                "id": o["id"],
                "geometry": o["geometry"],
                "bottom_m": float(exact(o["bottom"], scalar)),
                "top_m": float(exact(o["top"], scalar)),
            }
            for o in stair_spec.get("obstacles", [])
            if o["bottom"] < o["top"]
        ]
    )
    paths = []
    for fl in stair["flights"]:
        paths.append((fl["id"], LineString(fl["walking_line"]), fl["section_profile"][0][0]))
    for surf in stair["surfaces"]:
        if surf["kind"] == "landing":
            sec = next(s for s in stair["sections"] if s["id"] == surf["id"])
            paths.append((surf["id"], LineString(surf["walking_line"]), sec["profile"][0][0]))
    for pid, path, start_s in paths:
        for obs in obstructions:
            hit = path.intersection(shape_set(obs["geometry"]))
            pieces = list(hit.geoms) if hasattr(hit, "geoms") else [hit]
            for idx, g in enumerate(pieces):
                if g.is_empty or g.geom_type != "LineString":
                    continue
                ends = sorted(path.project(Point(p)) for p in (g.coords[0], g.coords[-1]))
                lo_m, hi_m = start_s + ends[0], start_s + ends[1]
                if hi_m > lo_m:
                    rect_poly = box(lo_m, obs["bottom_m"], hi_m, obs["top_m"])
                    coords = _polygon_to_coords_draw(rect_poly, "m", drawing_units)
                    add(
                        make_entity(
                            entity_type="POLYLINE",
                            coordinates=coords,
                            view_id=view_id,
                            floor_id=None,
                            layer="A-WALL-INT",
                            style_ref=style_ref,
                            source_geometry_id=obs["id"],
                            source_revision_digest=stair_rev,
                            provenance=provenance,
                            key_tag=f"sec_obs_{pid}_{idx}",
                            metadata={"role": "modeled_obstruction"},
                        )
                    )
                    if style.get("hatch_enabled", True):
                        add(
                            make_entity(
                                entity_type="HATCH",
                                coordinates={"exterior": coords["exterior"], "holes": []},
                                view_id=view_id,
                                floor_id=None,
                                layer="A-HATCH",
                                style_ref=style_ref,
                                source_geometry_id=obs["id"],
                                source_revision_digest=stair_rev,
                                provenance=provenance,
                                key_tag=f"sec_obs_hatch_{pid}_{idx}",
                                metadata={"pattern": "ANSI31", "role": "modeled_obstruction"},
                            )
                        )

    # 3. FFL Level Lines & Level Marks
    level_marks: list[dict[str, Any]] = []
    max_z_m = float(stair["destination_elevation_m"])
    for obs in obstructions:
        max_z_m = max(max_z_m, float(obs["top_m"]))
    for fid, elev_m in (
        (stair["source_floor"], stair["source_elevation_m"]),
        (stair["destination_floor"], stair["destination_elevation_m"]),
    ):
        z_d = zero_float(convert_length(elev_m, "m", drawing_units))
        add(
            make_entity(
                entity_type="LINE",
                coordinates={"start": [min_x_d - sizing["dim_offset"] * 2.6, z_d], "end": [max_x_d + sizing["dim_offset"], z_d]},
                view_id=view_id,
                floor_id=None,
                layer="A-LEVEL",
                style_ref=style_ref,
                source_geometry_id=fid,
                source_revision_digest=stair_rev,
                provenance=provenance,
                key_tag=f"sec_ffl_line_{fid}",
                metadata={"role": "level_datum_line", "elevation_m": elev_m},
            )
        )
        elev_str = f"{elev_m:+.3f} m" if elev_m != 0 else "+0.000 m"
        add(
            make_entity(
                entity_type="BLOCK_REFERENCE",
                coordinates={"insert": [min_x_d - sizing["dim_offset"] * 2.5, z_d], "scale": 1.0, "rotation_deg": 0.0},
                view_id=view_id,
                floor_id=None,
                layer="A-LEVEL",
                style_ref=style_ref,
                source_geometry_id=fid,
                source_revision_digest=stair_rev,
                provenance=provenance,
                key_tag=f"sec_ffl_mark_{fid}",
                metadata={"block_name": "SYM_LEVEL_MARK", "label": f"FFL {fid}: {elev_str}", "elevation_m": elev_m},
            )
        )
        level_marks.append({"floor_id": fid, "elevation_m": elev_m, "label": elev_str})

    # 4. Step numbers in section if requested
    if annotation_options.get("number_steps", stair_spec.get("number_steps", False)):
        step_idx = 0
        for fl in stair["flights"]:
            for j, tread in enumerate(fl["treads"]):
                step_idx += 1
                tx_m = fl["section_profile"][0][0] + (j + 0.5) * fl["tread_depth_m"]
                tz_m = tread["elevation_m"]
                add(
                    make_entity(
                        entity_type="TEXT",
                        coordinates={"insert": pt_draw([tx_m, tz_m])},
                        view_id=view_id,
                        floor_id=None,
                        layer="A-STAIR",
                        style_ref=style_ref,
                        source_geometry_id=tread["id"],
                        source_revision_digest=stair_rev,
                        provenance=provenance,
                        key_tag=f"sec_step_{step_idx}",
                        metadata={
                            "text": str(step_idx),
                            "height": sizing["dim_text_height"] * 0.65,
                            "anchor": "middle",
                            "rotation_deg": 0.0,
                        },
                    )
                )

    # 5. Dimension entities in section (floor-to-floor, headroom clearance, riser/tread)
    for dim in section_dimensions:
        if dim["dimension_type"] in {"linear_horizontal", "linear_vertical", "vertical_clearance"}:
            add(
                make_entity(
                    entity_type="DIMENSION",
                    coordinates={
                        "ref_point_1": dim["ref_point_1"],
                        "ref_point_2": dim["ref_point_2"],
                        "line_start": dim["dim_line_location"]["start"],
                        "line_end": dim["dim_line_location"]["end"],
                        "text_point": dim["dim_line_location"]["text_point"],
                        "extension_lines": dim["extension_lines"],
                    },
                    view_id=view_id,
                    floor_id=None,
                    layer="A-DIMS",
                    style_ref=style_ref,
                    source_geometry_id=dim["associated_entity_ids"][0],
                    source_revision_digest=dim["source_geometry_digest"],
                    provenance=provenance,
                    key_tag=dim["id"],
                    metadata={
                        "dimension_id": dim["id"],
                        "display_text": dim["display_text"]
                        + (" min CLR" if dim["measurement_basis"] == "stair_verified_local_headroom" else ""),
                        "measurement_basis": dim["measurement_basis"],
                        "orientation": "horizontal"
                        if dim["dimension_type"] == "linear_horizontal"
                        else "vertical",
                        "height": sizing["dim_text_height"],
                        "tick_style": style["tick_style"],
                        "arrow_size": sizing["arrow_size"],
                    },
                )
            )

    # 6. Section title annotation distinguishing true vs developed section
    kind_desc = (
        f"TRUE SECTION ({stair['section_kind']})"
        if stair["section_kind"] in {"TRUE_LONGITUDINAL", "TRUE_STRAIGHT_SECTION"}
        else f"DEVELOPED WALKING-LINE SECTION ({stair['section_kind']} — NOT TRUE PLANAR CUT)"
    )
    mark = stair.get("mark") or stair["id"]
    risers_total = sum(f["risers"] for f in stair["flights"])
    fl0 = stair["flights"][0]
    rh_str = format_measurement(convert_length(fl0["riser_height_m"], "m", drawing_units), precision)[0]
    td_str = format_measurement(convert_length(fl0["tread_depth_m"], "m", drawing_units), precision)[0]
    add(
        make_entity(
            entity_type="MTEXT",
            coordinates={"insert": [(min_x_d + max_x_d) / 2.0, zero_float(convert_length(max_z_m + 0.85, "m", drawing_units))]},
            view_id=view_id,
            floor_id=None,
            layer="A-SECT",
            style_ref=style_ref,
            source_geometry_id=stair["id"],
            source_revision_digest=stair_rev,
            provenance=provenance,
            key_tag="section_header",
            metadata={
                "lines": [
                    f"STAIR {mark} SECTION — {kind_desc}",
                    f"{risers_total} Risers x {rh_str} {drawing_units} / Tread {td_str} {drawing_units}",
                ],
                "height": sizing["text_height"] * 0.9,
                "anchor": "middle",
                "line_spacing": 1.3,
            },
        )
    )

    return {
        "view_id": view_id,
        "view_kind": "stair_section",
        "floor_id": None,
        "title": f"Stair Section {mark}",
        "section_kind": stair["section_kind"],
        "source_revision_digest": stair_rev,
        "entities": entities,
        "stair_annotations": [
            {
                "stair_id": stair["id"],
                "mark": mark,
                "section_kind": stair["section_kind"],
                "risers": risers_total,
                "riser_height": zero_float(convert_length(fl0["riser_height_m"], "m", drawing_units)),
                "tread_depth": zero_float(convert_length(fl0["tread_depth_m"], "m", drawing_units)),
                "source_elevation_m": stair["source_elevation_m"],
                "destination_elevation_m": stair["destination_elevation_m"],
                "headroom_status": stairs_report.get("headroom", {}).get("status", "UNKNOWN"),
            }
        ],
        "level_marks": level_marks,
    }
