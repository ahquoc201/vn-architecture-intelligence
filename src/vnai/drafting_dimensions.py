"""Deterministic architectural dimension engine and chain closure verifier."""

from decimal import Decimal
from typing import Any

from shapely.geometry import Point, Polygon, box

from vnai.contracts import canonical_digest
from vnai.drafting_styles import (
    UNIT_TO_MM,
    convert_length,
    convert_point,
    dec,
    format_measurement,
    zero_float,
)
from vnai.opening_hosts import shape_set
from vnai.wall_topology import orthogonal, polygons


def _dedup_decimals(values: list[Decimal], tol: Decimal) -> list[Decimal]:
    ordered = sorted(values)
    out: list[Decimal] = []
    for val in ordered:
        if not out or abs(val - out[-1]) > tol:
            out.append(val)
    return out


def _coord_tol(units: str) -> Decimal:
    # 1e-12 m == 1e-9 mm documented boundary tolerance across B1..B4.
    return Decimal("1e-12") if units == "m" else Decimal("1e-9")


def _rect_exact_bounds_dec(shape: Polygon, tol_m: float = 1e-12) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """Return exact Decimal (min_x, min_y, max_x, max_y) if shape is a single axis-aligned rectangle."""
    if shape.is_empty or shape.geom_type != "Polygon" or shape.interiors:
        return None
    env = box(*shape.bounds)
    if shape.symmetric_difference(env).area > tol_m:
        return None
    coords = list(shape.exterior.coords)
    xs = [dec(c[0]) for c in coords]
    ys = [dec(c[1]) for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def _format_unit_label(text: str, drawing_units: str) -> str:
    return text if drawing_units == "mm" else f"{text} m"


def _make_dimension_record(
    *,
    view_id: str,
    floor_id: str | None,
    dimension_type: str,
    measurement_basis: str,
    ref_point_1_draw: list[float],
    ref_point_2_draw: list[float],
    measured_dec_draw: Decimal,
    source_measured_dec: Decimal,
    drawing_units: str,
    precision: int,
    dim_line_start: list[float],
    dim_line_end: list[float],
    text_point: list[float],
    extension_lines: list[dict[str, list[float]]],
    associated_entity_ids: list[str],
    source_geometry_digest: str,
    chain_id: str | None = None,
    tier: str | None = None,
    key_tag: str = "",
) -> dict[str, Any]:
    text, disp_dec, disc_dec = format_measurement(measured_dec_draw, precision)
    dim_id = "DIM-" + canonical_digest(
        [
            view_id,
            floor_id,
            dimension_type,
            measurement_basis,
            chain_id,
            tier,
            associated_entity_ids,
            key_tag,
            ref_point_1_draw,
            ref_point_2_draw,
        ]
    )[:16]
    return {
        "id": dim_id,
        "view_id": view_id,
        "floor_id": floor_id,
        "dimension_type": dimension_type,
        "measurement_basis": measurement_basis,
        "measured_vs_required": "actual_measured",
        "ref_point_1": [0.0 if v == 0.0 else float(v) for v in ref_point_1_draw],
        "ref_point_2": [0.0 if v == 0.0 else float(v) for v in ref_point_2_draw],
        "measured_value": zero_float(measured_dec_draw),
        "source_measured_value": zero_float(source_measured_dec),
        "measurement_unit": drawing_units,
        "display_format": f"fixed_{precision}_decimal" if precision > 0 else "integer_rounded",
        "display_text": text,
        "displayed_numeric": zero_float(disp_dec),
        "rounding_discrepancy": zero_float(disc_dec),
        "dim_line_location": {
            "start": [0.0 if v == 0.0 else float(v) for v in dim_line_start],
            "end": [0.0 if v == 0.0 else float(v) for v in dim_line_end],
            "text_point": [0.0 if v == 0.0 else float(v) for v in text_point],
        },
        "extension_lines": extension_lines,
        "associated_entity_ids": list(associated_entity_ids),
        "source_geometry_digest": source_geometry_digest or "unresolved",
        "chain_id": chain_id,
        "tier": tier,
    }


def verify_dimension_chain_closure(
    segments_dec: list[Decimal],
    overall_dec: Decimal,
    precision: int,
    drawing_units: str,
) -> dict[str, Any]:
    """Independently check exact geometric closure vs displayed rounding closure."""
    tol = _coord_tol(drawing_units)
    exact_sum = sum(segments_dec, Decimal("0"))
    geom_err = exact_sum - overall_dec
    geom_closed = abs(geom_err) <= tol

    disp_segs = [format_measurement(s, precision)[1] for s in segments_dec]
    disp_overall = format_measurement(overall_dec, precision)[1]
    disp_sum = sum(disp_segs, Decimal("0"))
    disp_disc = disp_sum - disp_overall
    disp_closed = disp_disc == Decimal("0")

    if not geom_closed:
        status = "GEOMETRIC_CLOSURE_MISMATCH"
    elif not disp_closed:
        status = "GEOMETRIC_CLOSED_DISPLAY_ROUNDING_DISCREPANCY"
    else:
        status = "GEOMETRIC_CLOSED_EXACT"

    return {
        "exact_segments_sum": zero_float(exact_sum),
        "exact_overall": zero_float(overall_dec),
        "geometric_closure_error": zero_float(geom_err),
        "geometric_closed": geom_closed,
        "displayed_segments_sum": zero_float(disp_sum),
        "displayed_overall": zero_float(disp_overall),
        "display_rounding_discrepancy": zero_float(disp_disc),
        "display_closed": disp_closed,
        "closure_status": status,
    }


def build_dimension_chain(
    *,
    axis: str,
    stations: list[tuple[Decimal, float, list[str], str]],
    line_coord: float,
    overall_line_coord: float,
    side: str,
    ext_offset: float,
    ext_overshoot: float,
    source_units: str,
    drawing_units: str,
    precision: int,
    source_geometry_digest: str,
    view_id: str,
    floor_id: str | None,
    chain_id: str,
    dim_text_height: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build deterministic horizontal or vertical segment + overall dimension chain.

    stations: sequence of (coord_in_source_units, witness_perp_in_drawing_units, entity_ids, basis).
    """
    tol_draw = _coord_tol(drawing_units)
    converted: list[tuple[Decimal, float, list[str], str]] = []
    for coord_src, witness_perp, eids, basis in stations:
        coord_draw = convert_length(coord_src, source_units, drawing_units)
        converted.append((coord_draw, witness_perp, list(eids), basis))
    converted.sort(key=lambda item: item[0])

    deduped: list[tuple[Decimal, float, list[str], str]] = []
    for coord_draw, witness_perp, eids, basis in converted:
        if not deduped or abs(coord_draw - deduped[-1][0]) > tol_draw:
            deduped.append((coord_draw, witness_perp, eids, basis))
        else:
            prev_c, prev_w, prev_ids, prev_basis = deduped[-1]
            merged_ids = sorted(set(prev_ids + eids))
            # Keep outer witness nearer the dimension line for clean extension start.
            chosen_w = (
                min(prev_w, witness_perp)
                if side in {"bottom", "left"}
                else max(prev_w, witness_perp)
            )
            deduped[-1] = (prev_c, chosen_w, merged_ids, prev_basis)

    if len(deduped) < 2:
        raise ValueError(f"Dimension chain {chain_id} requires at least 2 distinct stations.")

    sign = -1.0 if side in {"bottom", "left"} else 1.0
    dims: list[dict[str, Any]] = []
    seg_values_dec: list[Decimal] = []
    factor_to_source = UNIT_TO_MM[drawing_units] / UNIT_TO_MM[source_units]

    def make_ext(coord_val: float, witness_perp: float, target_line: float) -> dict[str, list[float]]:
        start_perp = witness_perp + sign * ext_offset
        end_perp = target_line + sign * ext_overshoot
        if axis == "x":
            return {"start": [coord_val, start_perp], "end": [coord_val, end_perp]}
        return {"start": [start_perp, coord_val], "end": [end_perp, coord_val]}

    dim_type = "linear_horizontal" if axis == "x" else "linear_vertical"
    for i in range(len(deduped) - 1):
        c0, w0, ids0, b0 = deduped[i]
        c1, w1, ids1, b1 = deduped[i + 1]
        seg_dec = c1 - c0
        seg_values_dec.append(seg_dec)
        src_seg = seg_dec * factor_to_source
        x0, x1 = zero_float(c0), zero_float(c1)
        mid = (x0 + x1) / 2.0
        span = abs(x1 - x0)
        text_est_w = max(len(format_measurement(seg_dec, precision)[0]), 2) * dim_text_height * 0.72
        # Deterministic CAD text fit: narrow end segments tuck cleanly outside the tick.
        text_coord = mid
        if span < text_est_w * 1.15:
            if i == 0:
                text_coord = x0 - dim_text_height * 1.15
            elif i == len(deduped) - 2:
                text_coord = x1 + dim_text_height * 1.15
        if axis == "x":
            rp1, rp2 = [x0, w0], [x1, w1]
            ls, le = [x0, line_coord], [x1, line_coord]
            tp = [text_coord, line_coord - dim_text_height * 0.35 if side == "bottom" else line_coord + dim_text_height * 0.85]
        else:
            rp1, rp2 = [w0, x0], [w1, x1]
            ls, le = [line_coord, x0], [line_coord, x1]
            tp = [line_coord - dim_text_height * 0.45 if side == "left" else line_coord + dim_text_height * 0.85, text_coord]
        ext = [make_ext(x0, w0, line_coord), make_ext(x1, w1, line_coord)]
        combined_ids = sorted(set(ids0 + ids1)) or [f"{chain_id}:seg_{i}"]
        dims.append(
            _make_dimension_record(
                view_id=view_id,
                floor_id=floor_id,
                dimension_type=dim_type,
                measurement_basis="dimension_chain_segment",
                ref_point_1_draw=rp1,
                ref_point_2_draw=rp2,
                measured_dec_draw=seg_dec,
                source_measured_dec=src_seg,
                drawing_units=drawing_units,
                precision=precision,
                dim_line_start=ls,
                dim_line_end=le,
                text_point=tp,
                extension_lines=ext,
                associated_entity_ids=combined_ids,
                source_geometry_digest=source_geometry_digest,
                chain_id=chain_id,
                tier="intermediate",
                key_tag=f"seg_{i}",
            )
        )

    c_start, w_start, ids_start, _ = deduped[0]
    c_end, w_end, ids_end, _ = deduped[-1]
    overall_dec = c_end - c_start
    src_overall = overall_dec * factor_to_source
    xs0, xs1 = zero_float(c_start), zero_float(c_end)
    mid_all = (xs0 + xs1) / 2.0
    if axis == "x":
        rp1, rp2 = [xs0, w_start], [xs1, w_end]
        ls, le = [xs0, overall_line_coord], [xs1, overall_line_coord]
        tp = [mid_all, overall_line_coord - dim_text_height * 0.35 if side == "bottom" else overall_line_coord + dim_text_height * 0.85]
    else:
        rp1, rp2 = [w_start, xs0], [w_end, xs1]
        ls, le = [overall_line_coord, xs0], [overall_line_coord, xs1]
        tp = [overall_line_coord - dim_text_height * 0.45 if side == "left" else overall_line_coord + dim_text_height * 0.85, mid_all]
    overall_ext = [
        make_ext(xs0, w_start, overall_line_coord),
        make_ext(xs1, w_end, overall_line_coord),
    ]
    overall_dim = _make_dimension_record(
        view_id=view_id,
        floor_id=floor_id,
        dimension_type=dim_type,
        measurement_basis="dimension_chain_overall",
        ref_point_1_draw=rp1,
        ref_point_2_draw=rp2,
        measured_dec_draw=overall_dec,
        source_measured_dec=src_overall,
        drawing_units=drawing_units,
        precision=precision,
        dim_line_start=ls,
        dim_line_end=le,
        text_point=tp,
        extension_lines=overall_ext,
        associated_entity_ids=sorted(set(ids_start + ids_end)) or [chain_id],
        source_geometry_digest=source_geometry_digest,
        chain_id=chain_id,
        tier="overall",
        key_tag="overall",
    )
    dims.append(overall_dim)

    closure = verify_dimension_chain_closure(
        seg_values_dec, overall_dec, precision, drawing_units
    )
    chain_record = {
        "chain_id": chain_id,
        "view_id": view_id,
        "floor_id": floor_id,
        "axis": axis,
        "side": side,
        "measurement_unit": drawing_units,
        "reference_coordinates": [zero_float(item[0]) for item in deduped],
        "segment_dimension_ids": [d["id"] for d in dims[:-1]],
        "overall_dimension_id": overall_dim["id"],
        **closure,
    }
    return dims, chain_record


def _orthogonal_circulation_spans(
    circ_shape: Polygon,
    wall_shape: Polygon,
) -> tuple[bool, list[tuple[str, float, float, float, float]]]:
    """Extract clean axis-aligned corridor strip spans from clear circulation geometry."""
    clear = circ_shape.difference(wall_shape) if not wall_shape.is_empty else circ_shape
    if clear.is_empty:
        return True, []
    strips: list[tuple[str, float, float, float, float]] = []
    for part in polygons(clear):
        if not orthogonal(part):
            return False, []
        xs = sorted({round(c[0], 9) for c in part.exterior.coords})
        ys = sorted({round(c[1], 9) for c in part.exterior.coords})
        if len(xs) < 2 or len(ys) < 2:
            continue
        # Horizontal bands across Y slices capture X corridor widths.
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            cy = (y0 + y1) / 2.0
            run_start: float | None = None
            for i in range(len(xs) - 1):
                x0, x1 = xs[i], xs[i + 1]
                inside = part.contains(Point((x0 + x1) / 2.0, cy))
                if inside and run_start is None:
                    run_start = x0
                elif not inside and run_start is not None:
                    strips.append(("x", run_start, x0, y0, y1))
                    run_start = None
            if run_start is not None:
                strips.append(("x", run_start, xs[-1], y0, y1))
        # Vertical bands across X slices capture Y corridor widths.
        for i in range(len(xs) - 1):
            x0, x1 = xs[i], xs[i + 1]
            cx = (x0 + x1) / 2.0
            run_start_y: float | None = None
            for j in range(len(ys) - 1):
                y0, y1 = ys[j], ys[j + 1]
                inside = part.contains(Point(cx, (y0 + y1) / 2.0))
                if inside and run_start_y is None:
                    run_start_y = y0
                elif not inside and run_start_y is not None:
                    strips.append(("y", x0, x1, run_start_y, y0))
                    run_start_y = None
            if run_start_y is not None:
                strips.append(("y", x0, x1, run_start_y, ys[-1]))
    # Pick distinct meaningful strip widths (width <= length, width >= 0.2 m).
    chosen: list[tuple[str, float, float, float, float]] = []
    seen_spans: set[tuple[str, float]] = set()
    for axis, x0, x1, y0, y1 in strips:
        dx, dy = x1 - x0, y1 - y0
        width = dx if axis == "x" else dy
        length = dy if axis == "x" else dx
        if width < 0.2 or length < 0.2 or width > length + 1e-9:
            continue
        key = (axis, round(width, 4))
        if key not in seen_spans:
            seen_spans.add(key)
            chosen.append((axis, x0, x1, y0, y1))
    return True, chosen


def _is_orthogonal_rect_endpoints(p1: list[float], p2: list[float]) -> str | None:
    dx = abs(p2[0] - p1[0])
    dy = abs(p2[1] - p1[1])
    if dx > 1e-9 and dy <= 1e-9:
        return "x"
    if dy > 1e-9 and dx <= 1e-9:
        return "y"
    return None


def extract_dimensions(
    context: dict[str, Any],
    unit_policy: dict[str, Any],
    style: dict[str, Any],
    annotation_options: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate actual geometry-grounded dimensions, chains and unsupported diagnostics."""
    dimensions: list[dict[str, Any]] = []
    chains: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    missing_info: list[dict[str, Any]] = []

    source_units = unit_policy["source_units"]
    drawing_units = unit_policy["drawing_units"]
    precision = unit_policy["display_precision"]
    sizing = style["model_sizing"]
    dim_offset = sizing["dim_offset"]
    chain_spacing = sizing["chain_spacing"]
    ext_offset = sizing["extension_offset"]
    ext_overshoot = sizing["extension_overshoot"]
    dim_text_h = sizing["dim_text_height"]

    src_rev_digest = context["source_revision_digest"]
    candidate = context.get("candidate")
    walls_report = context.get("walls_report") or {}
    openings_report = context.get("openings_report") or {}
    stairs_report = context.get("stairs_report") or {}
    stair_spec = context.get("stair_specification") or {}
    wall_heights = context.get("wall_heights") or []
    ref_grid = context.get("reference_grid") or {}

    candidate_units = candidate["geometry"]["units"] if candidate else source_units

    def to_draw_pt(pt: list[float], from_unit: str = source_units) -> list[float]:
        return convert_point(pt, from_unit, drawing_units)

    def to_draw_val(val: int | float | Decimal, from_unit: str = source_units) -> Decimal:
        return convert_length(val, from_unit, drawing_units)

    # 1. Floor plan dimensions
    for floor_id in context["floor_ids"]:
        view_id = f"PLAN-{floor_id}"
        # Envelope bounds (in model_m = metres)
        env_poly_src = context["floor_envelopes"].get(floor_id)
        if env_poly_src is None:
            unsupported.append(
                {
                    "code": "MISSING_FLOOR_ENVELOPE",
                    "entity_id": floor_id,
                    "floor_id": floor_id,
                    "basis": "building_envelope",
                    "reason": "Floor envelope polygon unavailable for overall dimensioning.",
                }
            )
            continue

        # Exact envelope coordinates in candidate/envelope units (always metres inside walls_report).
        env_rect = _rect_exact_bounds_dec(env_poly_src)
        if env_rect is None:
            unsupported.append(
                {
                    "code": "NONRECTANGULAR_ENVELOPE_SPAN",
                    "entity_id": floor_id,
                    "floor_id": floor_id,
                    "basis": "building_envelope",
                    "reason": "Overall width/length not emitted for non-rectangular envelope.",
                }
            )
            continue
        ex0_m, ey0_m, ex1_m, ey1_m = env_rect
        ex0_d, ey0_d = zero_float(to_draw_val(ex0_m, "m")), zero_float(to_draw_val(ey0_m, "m"))
        ex1_d, ey1_d = zero_float(to_draw_val(ex1_m, "m")), zero_float(to_draw_val(ey1_m, "m"))

        # Check floor_outline vs footprint distinction
        floor_outline_poly = (
            next(
                (
                    p
                    for p in candidate["geometry"]["polygons"]
                    if p["role"] == "floor_outline" and p.get("floor_id") == floor_id
                ),
                None,
            )
            if candidate
            else None
        )
        envelope_basis = "floor_outline" if floor_outline_poly else "building_envelope"

        floor_walls = [w for w in walls_report.get("walls", []) if w["floor_id"] == floor_id]
        floor_openings = [
            o for o in openings_report.get("openings", []) if o["floor_id"] == floor_id
        ]
        floor_rooms = [r for r in walls_report.get("rooms", []) if r["floor_id"] == floor_id]

        # Build external horizontal chain (South / bottom):
        # Include envelope corners + exterior wall inner faces + south exterior openings + reference grid X axes.
        tol_m = Decimal("1e-9")
        south_stations: list[tuple[Decimal, float, list[str], str]] = [
            (ex0_m, ey0_d, [f"{floor_id}:env_west"], envelope_basis),
            (ex1_m, ey0_d, [f"{floor_id}:env_east"], envelope_basis),
        ]
        north_stations: list[tuple[Decimal, float, list[str], str]] = [
            (ex0_m, ey1_d, [f"{floor_id}:env_west"], envelope_basis),
            (ex1_m, ey1_d, [f"{floor_id}:env_east"], envelope_basis),
        ]
        west_stations: list[tuple[Decimal, float, list[str], str]] = [
            (ey0_m, ex0_d, [f"{floor_id}:env_south"], envelope_basis),
            (ey1_m, ex0_d, [f"{floor_id}:env_north"], envelope_basis),
        ]
        east_stations: list[tuple[Decimal, float, list[str], str]] = [
            (ey0_m, ex1_d, [f"{floor_id}:env_south"], envelope_basis),
            (ey1_m, ex1_d, [f"{floor_id}:env_north"], envelope_basis),
        ]

        # Add vertical/horizontal wall boundaries along exterior facades and main partition stations.
        for w in floor_walls:
            r = w["reference"]
            p0, p1 = r["start"], r["end"]
            orient = _is_orthogonal_rect_endpoints(p0, p1)
            w_rect = _rect_exact_bounds_dec(shape_set(w["geometry"]))
            if orient == "y" and w_rect is not None:
                wx0, wy0, wx1, wy1 = w_rect
                if abs(wy0 - ey0_m) <= Decimal("0.25") or w["classification"] == "exterior":
                    south_stations.append((wx0, ey0_d, [w["id"]], "wall_face"))
                    south_stations.append((wx1, ey0_d, [w["id"]], "wall_face"))
                if abs(wy1 - ey1_m) <= Decimal("0.25") or w["classification"] == "exterior":
                    north_stations.append((wx0, ey1_d, [w["id"]], "wall_face"))
                    north_stations.append((wx1, ey1_d, [w["id"]], "wall_face"))
            elif orient == "x" and w_rect is not None:
                wx0, wy0, wx1, wy1 = w_rect
                # Add major bay reference points (wall centerline or reference) along west/east sides
                # without crowding thin 100mm partition faces into exterior chain.
                ref_y = dec(p0[1])
                if w["classification"] == "exterior":
                    west_stations.append((wy0, ex0_d, [w["id"]], "wall_face"))
                    west_stations.append((wy1, ex0_d, [w["id"]], "wall_face"))
                    east_stations.append((wy0, ex1_d, [w["id"]], "wall_face"))
                    east_stations.append((wy1, ex1_d, [w["id"]], "wall_face"))
                else:
                    west_stations.append((ref_y, ex0_d, [w["id"]], "partition_reference"))

        # Add exterior wall openings to corresponding exterior chain
        for op in floor_openings:
            ref = op.get("reference")
            if not ref:
                continue
            p0, p1 = ref["start"], ref["end"]
            orient = _is_orthogonal_rect_endpoints(p0, p1)
            if orient == "x":
                op_y = dec(p0[1])
                x0_op, x1_op = sorted([dec(p0[0]), dec(p1[0])])
                if abs(op_y - ey0_m) <= Decimal("0.25"):
                    south_stations.append((x0_op, ey0_d, [op["id"]], "opening_jamb"))
                    south_stations.append((x1_op, ey0_d, [op["id"]], "opening_jamb"))
                elif abs(op_y - ey1_m) <= Decimal("0.25"):
                    north_stations.append((x0_op, ey1_d, [op["id"]], "opening_jamb"))
                    north_stations.append((x1_op, ey1_d, [op["id"]], "opening_jamb"))
            elif orient == "y":
                op_x = dec(p0[0])
                y0_op, y1_op = sorted([dec(p0[1]), dec(p1[1])])
                if abs(op_x - ex0_m) <= Decimal("0.25"):
                    west_stations.append((y0_op, ex0_d, [op["id"]], "opening_jamb"))
                    west_stations.append((y1_op, ex0_d, [op["id"]], "opening_jamb"))
                elif abs(op_x - ex1_m) <= Decimal("0.25"):
                    east_stations.append((y0_op, ex1_d, [op["id"]], "opening_jamb"))
                    east_stations.append((y1_op, ex1_d, [op["id"]], "opening_jamb"))

        # Include reference grid stations if supplied
        grid_unit_factor = (
            Decimal("1")
            if candidate_units == "m"
            else Decimal("0.001")
        )
        for ax in ref_grid.get("x_axes", []):
            gx_m = dec(ax["coord_source_units"]) * grid_unit_factor
            if ex0_m - tol_m <= gx_m <= ex1_m + tol_m:
                south_stations.append((gx_m, ey0_d, [f"GRID-{ax['label']}"], "reference_grid"))
        for ax in ref_grid.get("y_axes", []):
            gy_m = dec(ax["coord_source_units"]) * grid_unit_factor
            if ey0_m - tol_m <= gy_m <= ey1_m + tol_m:
                west_stations.append((gy_m, ex0_d, [f"GRID-{ax['label']}"], "reference_grid"))

        chain_specs = [
            ("x", "bottom", south_stations, ey0_d - dim_offset, ey0_d - dim_offset - chain_spacing, f"CHAIN-{floor_id}-X-SOUTH"),
            ("y", "left", west_stations, ex0_d - dim_offset, ex0_d - dim_offset - chain_spacing, f"CHAIN-{floor_id}-Y-WEST"),
        ]
        # Only emit north/east exterior chains if north/east differ meaningfully (> 2 stations) from simple overall
        if len(_dedup_decimals([s[0] for s in north_stations], tol_m)) > 2:
            chain_specs.append(
                ("x", "top", north_stations, ey1_d + dim_offset, ey1_d + dim_offset + chain_spacing, f"CHAIN-{floor_id}-X-NORTH")
            )
        if len(_dedup_decimals([s[0] for s in east_stations], tol_m)) > 2:
            chain_specs.append(
                ("y", "right", east_stations, ex1_d + dim_offset, ex1_d + dim_offset + chain_spacing, f"CHAIN-{floor_id}-Y-EAST")
            )

        for axis, side, stations, lc, olc, cid in chain_specs:
            cdims, crecord = build_dimension_chain(
                axis=axis,
                stations=stations,
                line_coord=lc,
                overall_line_coord=olc,
                side=side,
                ext_offset=ext_offset,
                ext_overshoot=ext_overshoot,
                source_units="m",
                drawing_units=drawing_units,
                precision=precision,
                source_geometry_digest=src_rev_digest,
                view_id=view_id,
                floor_id=floor_id,
                chain_id=cid,
                dim_text_height=dim_text_h,
            )
            dimensions.extend(cdims)
            chains.append(crecord)

        # 2. Clear room width & length dimensions (strict rectangular check!)
        for room in sorted(floor_rooms, key=lambda r: r["room_id"]):
            clear_poly = shape_set(room["clear_geometry"])
            rect = _rect_exact_bounds_dec(clear_poly)
            if rect is None:
                unsupported.append(
                    {
                        "code": "AMBIGUOUS_IRREGULAR_ROOM_SPAN",
                        "entity_id": room["room_id"],
                        "floor_id": floor_id,
                        "basis": "clear_room_interior",
                        "reason": (
                            "Clear room polygon is non-rectangular, multi-component, or holed; "
                            "refusing to fabricate a single clear width/length."
                        ),
                    }
                )
                continue
            rx0_m, ry0_m, rx1_m, ry1_m = rect
            w_m = rx1_m - rx0_m
            l_m = ry1_m - ry0_m
            w_d = convert_length(w_m, "m", drawing_units)
            l_d = convert_length(l_m, "m", drawing_units)
            x0_d, y0_d = zero_float(to_draw_val(rx0_m, "m")), zero_float(to_draw_val(ry0_m, "m"))
            x1_d, y1_d = zero_float(to_draw_val(rx1_m, "m")), zero_float(to_draw_val(ry1_m, "m"))
            y_dim = y0_d + (y1_d - y0_d) * 0.16
            x_dim = x0_d + (x1_d - x0_d) * 0.14
            dimensions.append(
                _make_dimension_record(
                    view_id=view_id,
                    floor_id=floor_id,
                    dimension_type="linear_horizontal",
                    measurement_basis="clear_room_interior",
                    ref_point_1_draw=[x0_d, y_dim],
                    ref_point_2_draw=[x1_d, y_dim],
                    measured_dec_draw=w_d,
                    source_measured_dec=w_m,
                    drawing_units=drawing_units,
                    precision=precision,
                    dim_line_start=[x0_d, y_dim],
                    dim_line_end=[x1_d, y_dim],
                    text_point=[(x0_d + x1_d) / 2.0, y_dim + dim_text_h * 0.4],
                    extension_lines=[],
                    associated_entity_ids=[room["room_id"]],
                    source_geometry_digest=src_rev_digest,
                    key_tag="clear_width",
                )
            )
            dimensions.append(
                _make_dimension_record(
                    view_id=view_id,
                    floor_id=floor_id,
                    dimension_type="linear_vertical",
                    measurement_basis="clear_room_interior",
                    ref_point_1_draw=[x_dim, y0_d],
                    ref_point_2_draw=[x_dim, y1_d],
                    measured_dec_draw=l_d,
                    source_measured_dec=l_m,
                    drawing_units=drawing_units,
                    precision=precision,
                    dim_line_start=[x_dim, y0_d],
                    dim_line_end=[x_dim, y1_d],
                    text_point=[x_dim - dim_text_h * 0.4, (y0_d + y1_d) / 2.0],
                    extension_lines=[],
                    associated_entity_ids=[room["room_id"]],
                    source_geometry_digest=src_rev_digest,
                    key_tag="clear_length",
                )
            )

        # 3. Wall thickness dimensions (one clean representative per wall thickness & classification)
        if annotation_options.get("show_wall_thickness_dims", True):
            seen_wall_classes: set[tuple[str, int]] = set()
            for w in sorted(floor_walls, key=lambda x: x["id"]):
                w_rect = _rect_exact_bounds_dec(shape_set(w["geometry"]))
                if w_rect is None:
                    continue
                wx0_m, wy0_m, wx1_m, wy1_m = w_rect
                dx_m, dy_m = wx1_m - wx0_m, wy1_m - wy0_m
                is_horiz_wall = dx_m >= dy_m
                thick_m = dy_m if is_horiz_wall else dx_m
                thick_mm_key = int(round(float(thick_m * Decimal("1000"))))
                sig = (w["classification"], thick_mm_key)
                if sig in seen_wall_classes:
                    continue
                seen_wall_classes.add(sig)
                thick_d = convert_length(thick_m, "m", drawing_units)
                wx0_d, wy0_d = zero_float(to_draw_val(wx0_m, "m")), zero_float(to_draw_val(wy0_m, "m"))
                wx1_d, wy1_d = zero_float(to_draw_val(wx1_m, "m")), zero_float(to_draw_val(wy1_m, "m"))
                if is_horiz_wall:
                    xm = (wx0_d + wx1_d) / 2.0
                    rp1, rp2 = [xm, wy0_d], [xm, wy1_d]
                    tp = [xm, wy1_d + dim_text_h * 1.6]
                    dim_t = "linear_vertical"
                else:
                    ym = (wy0_d + wy1_d) / 2.0
                    rp1, rp2 = [wx0_d, ym], [wx1_d, ym]
                    tp = [wx1_d + dim_text_h * 1.8, ym]
                    dim_t = "linear_horizontal"
                dimensions.append(
                    _make_dimension_record(
                        view_id=view_id,
                        floor_id=floor_id,
                        dimension_type=dim_t,
                        measurement_basis="wall_thickness_actual",
                        ref_point_1_draw=rp1,
                        ref_point_2_draw=rp2,
                        measured_dec_draw=thick_d,
                        source_measured_dec=thick_m,
                        drawing_units=drawing_units,
                        precision=precision,
                        dim_line_start=rp1,
                        dim_line_end=rp2,
                        text_point=tp,
                        extension_lines=[],
                        associated_entity_ids=[w["id"]],
                        source_geometry_digest=w["geometry_digest"],
                        key_tag=f"wall_thick_{w['classification']}",
                    )
                )

        # 4. Opening rough & clear passage width dimensions
        for op in sorted(floor_openings, key=lambda x: x["id"]):
            ref = op.get("reference")
            if ref and op.get("rough_width_m") is not None:
                p0, p1 = ref["start"], ref["end"]
                orient = _is_orthogonal_rect_endpoints(p0, p1)
                if orient:
                    p0_dec = [dec(p0[0]), dec(p0[1])]
                    p1_dec = [dec(p1[0]), dec(p1[1])]
                    rough_m = abs(p1_dec[0] - p0_dec[0]) if orient == "x" else abs(p1_dec[1] - p0_dec[1])
                    rough_d = convert_length(rough_m, "m", drawing_units)
                    dp0, dp1 = to_draw_pt(p0, "m"), to_draw_pt(p1, "m")
                    dimensions.append(
                        _make_dimension_record(
                            view_id=view_id,
                            floor_id=floor_id,
                            dimension_type="linear_horizontal" if orient == "x" else "linear_vertical",
                            measurement_basis="opening_rough_width",
                            ref_point_1_draw=dp0,
                            ref_point_2_draw=dp1,
                            measured_dec_draw=rough_d,
                            source_measured_dec=rough_m,
                            drawing_units=drawing_units,
                            precision=precision,
                            dim_line_start=dp0,
                            dim_line_end=dp1,
                            text_point=[(dp0[0] + dp1[0]) / 2.0, (dp0[1] + dp1[1]) / 2.0],
                            extension_lines=[],
                            associated_entity_ids=[op["id"]],
                            source_geometry_digest=op.get("opening_digest") or src_rev_digest,
                            key_tag="opening_rough",
                        )
                    )
            cref = op.get("clear_reference")
            if cref and op.get("clear_width_m") is not None:
                p0, p1 = cref["start"], cref["end"]
                orient = _is_orthogonal_rect_endpoints(p0, p1)
                if orient:
                    p0_dec = [dec(p0[0]), dec(p0[1])]
                    p1_dec = [dec(p1[0]), dec(p1[1])]
                    clr_m = abs(p1_dec[0] - p0_dec[0]) if orient == "x" else abs(p1_dec[1] - p0_dec[1])
                    clr_d = convert_length(clr_m, "m", drawing_units)
                    dp0, dp1 = to_draw_pt(p0, "m"), to_draw_pt(p1, "m")
                    dimensions.append(
                        _make_dimension_record(
                            view_id=view_id,
                            floor_id=floor_id,
                            dimension_type="linear_horizontal" if orient == "x" else "linear_vertical",
                            measurement_basis="opening_clear_passage_width",
                            ref_point_1_draw=dp0,
                            ref_point_2_draw=dp1,
                            measured_dec_draw=clr_d,
                            source_measured_dec=clr_m,
                            drawing_units=drawing_units,
                            precision=precision,
                            dim_line_start=dp0,
                            dim_line_end=dp1,
                            text_point=[(dp0[0] + dp1[0]) / 2.0, (dp0[1] + dp1[1]) / 2.0],
                            extension_lines=[],
                            associated_entity_ids=[op["id"]],
                            source_geometry_digest=op.get("opening_digest") or src_rev_digest,
                            key_tag="opening_clear",
                        )
                    )
            # Supplied sill & head elevations
            for elev_key, basis in (("sill_m", "opening_sill_elevation"), ("head_m", "opening_head_elevation")):
                val_m = op.get(elev_key)
                if val_m is not None:
                    v_m = dec(val_m)
                    v_d = convert_length(v_m, "m", drawing_units)
                    anchor = to_draw_pt(op["reference"]["start"], "m") if op.get("reference") else [0.0, 0.0]
                    dimensions.append(
                        _make_dimension_record(
                            view_id=view_id,
                            floor_id=floor_id,
                            dimension_type="vertical_elevation",
                            measurement_basis=basis,
                            ref_point_1_draw=anchor,
                            ref_point_2_draw=[anchor[0], anchor[1]],
                            measured_dec_draw=v_d,
                            source_measured_dec=v_m,
                            drawing_units=drawing_units,
                            precision=precision,
                            dim_line_start=anchor,
                            dim_line_end=anchor,
                            text_point=anchor,
                            extension_lines=[],
                            associated_entity_ids=[op["id"]],
                            source_geometry_digest=op.get("opening_digest") or src_rev_digest,
                            key_tag=basis,
                        )
                    )

        # 5. Circulation clear widths
        if annotation_options.get("show_circulation_dims", True) and candidate:
            circ_polys = [
                p
                for p in candidate["geometry"]["polygons"]
                if p.get("floor_id") == floor_id and p.get("reservation_kind") == "circulation"
            ]
            floor_wall_record = next(
                (f for f in walls_report.get("floors", []) if f["floor_id"] == floor_id), None
            )
            wall_union = (
                shape_set(floor_wall_record["wall_footprint"]) if floor_wall_record else Polygon()
            )
            c_scale = 1.0 if candidate_units == "m" else 0.001
            for cp in circ_polys:
                c_poly = Polygon([(x * c_scale, y * c_scale) for x, y in cp["exterior"]])
                ok, spans = _orthogonal_circulation_spans(c_poly, wall_union)
                if not ok:
                    unsupported.append(
                        {
                            "code": "UNSUPPORTED_NONORTHOGONAL_CIRCULATION_WIDTH",
                            "entity_id": cp["id"],
                            "floor_id": floor_id,
                            "basis": "circulation_clear_width",
                            "reason": "Non-orthogonal circulation polygon width is unsupported.",
                        }
                    )
                    continue
                for idx, (axis, x0, x1, y0, y1) in enumerate(spans):
                    if axis == "x":
                        w_m = dec(x1) - dec(x0)
                        rp1_m, rp2_m = [x0, (y0 + y1) / 2.0], [x1, (y0 + y1) / 2.0]
                        dt = "linear_horizontal"
                    else:
                        w_m = dec(y1) - dec(y0)
                        rp1_m, rp2_m = [(x0 + x1) / 2.0, y0], [(x0 + x1) / 2.0, y1]
                        dt = "linear_vertical"
                    w_d = convert_length(w_m, "m", drawing_units)
                    dp1, dp2 = to_draw_pt(rp1_m, "m"), to_draw_pt(rp2_m, "m")
                    dimensions.append(
                        _make_dimension_record(
                            view_id=view_id,
                            floor_id=floor_id,
                            dimension_type=dt,
                            measurement_basis="circulation_clear_width",
                            ref_point_1_draw=dp1,
                            ref_point_2_draw=dp2,
                            measured_dec_draw=w_d,
                            source_measured_dec=w_m,
                            drawing_units=drawing_units,
                            precision=precision,
                            dim_line_start=dp1,
                            dim_line_end=dp2,
                            text_point=[(dp1[0] + dp2[0]) / 2.0, (dp1[1] + dp2[1]) / 2.0],
                            extension_lines=[],
                            associated_entity_ids=[cp["id"]],
                            source_geometry_digest=src_rev_digest,
                            key_tag=f"circ_w_{idx}",
                        )
                    )

        # 6. Stair plan dimensions & floor openings
        for stair in stairs_report.get("stairs", []):
            if floor_id not in (stair["source_floor"], stair["destination_floor"]):
                continue
            for fl in stair["flights"]:
                fw_m = dec(fl["width_m"])
                fr_m = dec(fl["run_m"])
                fw_d = convert_length(fw_m, "m", drawing_units)
                fr_d = convert_length(fr_m, "m", drawing_units)
                wl = fl["walking_line"]
                u = fl["direction"]
                n_vec = (-u[1], u[0])
                mid_wl = [(wl[0][0] + wl[-1][0]) / 2.0, (wl[0][1] + wl[-1][1]) / 2.0]
                wp1 = to_draw_pt(
                    [mid_wl[0] - n_vec[0] * fl["width_m"] / 2.0, mid_wl[1] - n_vec[1] * fl["width_m"] / 2.0],
                    "m",
                )
                wp2 = to_draw_pt(
                    [mid_wl[0] + n_vec[0] * fl["width_m"] / 2.0, mid_wl[1] + n_vec[1] * fl["width_m"] / 2.0],
                    "m",
                )
                rp1 = to_draw_pt(wl[0], "m")
                rp2 = to_draw_pt(wl[-1], "m")
                dimensions.append(
                    _make_dimension_record(
                        view_id=view_id,
                        floor_id=floor_id,
                        dimension_type="linear_horizontal" if abs(n_vec[0]) >= abs(n_vec[1]) else "linear_vertical",
                        measurement_basis="stair_flight_width",
                        ref_point_1_draw=wp1,
                        ref_point_2_draw=wp2,
                        measured_dec_draw=fw_d,
                        source_measured_dec=fw_m,
                        drawing_units=drawing_units,
                        precision=precision,
                        dim_line_start=wp1,
                        dim_line_end=wp2,
                        text_point=[(wp1[0] + wp2[0]) / 2.0, (wp1[1] + wp2[1]) / 2.0],
                        extension_lines=[],
                        associated_entity_ids=[stair["id"], fl["id"]],
                        source_geometry_digest=src_rev_digest,
                        key_tag=f"stair_fw_{fl['id']}",
                    )
                )
                dimensions.append(
                    _make_dimension_record(
                        view_id=view_id,
                        floor_id=floor_id,
                        dimension_type="linear_horizontal" if abs(u[0]) >= abs(u[1]) else "linear_vertical",
                        measurement_basis="stair_flight_run",
                        ref_point_1_draw=rp1,
                        ref_point_2_draw=rp2,
                        measured_dec_draw=fr_d,
                        source_measured_dec=fr_m,
                        drawing_units=drawing_units,
                        precision=precision,
                        dim_line_start=rp1,
                        dim_line_end=rp2,
                        text_point=[(rp1[0] + rp2[0]) / 2.0, (rp1[1] + rp2[1]) / 2.0],
                        extension_lines=[],
                        associated_entity_ids=[stair["id"], fl["id"]],
                        source_geometry_digest=src_rev_digest,
                        key_tag=f"stair_run_{fl['id']}",
                    )
                )
            for surf in stair["surfaces"]:
                if surf["kind"] != "landing":
                    continue
                l_rect = _rect_exact_bounds_dec(shape_set(surf["geometry"]))
                if l_rect is None:
                    unsupported.append(
                        {
                            "code": "AMBIGUOUS_IRREGULAR_LANDING_SPAN",
                            "entity_id": surf["id"],
                            "floor_id": floor_id,
                            "basis": "stair_landing_dimensions",
                            "reason": "Non-rectangular stair landing span is ambiguous.",
                        }
                    )
                    continue
                lx0_m, ly0_m, lx1_m, ly1_m = l_rect
                ldx_m, ldy_m = lx1_m - lx0_m, ly1_m - ly0_m
                lx0_d, ly0_d = zero_float(to_draw_val(lx0_m, "m")), zero_float(to_draw_val(ly0_m, "m"))
                lx1_d, ly1_d = zero_float(to_draw_val(lx1_m, "m")), zero_float(to_draw_val(ly1_m, "m"))
                dimensions.append(
                    _make_dimension_record(
                        view_id=view_id,
                        floor_id=floor_id,
                        dimension_type="linear_horizontal",
                        measurement_basis="stair_landing_width",
                        ref_point_1_draw=[lx0_d, ly0_d],
                        ref_point_2_draw=[lx1_d, ly0_d],
                        measured_dec_draw=convert_length(ldx_m, "m", drawing_units),
                        source_measured_dec=ldx_m,
                        drawing_units=drawing_units,
                        precision=precision,
                        dim_line_start=[lx0_d, ly0_d],
                        dim_line_end=[lx1_d, ly0_d],
                        text_point=[(lx0_d + lx1_d) / 2.0, ly0_d],
                        extension_lines=[],
                        associated_entity_ids=[stair["id"], surf["id"]],
                        source_geometry_digest=src_rev_digest,
                        key_tag=f"landing_x_{surf['id']}",
                    )
                )
                dimensions.append(
                    _make_dimension_record(
                        view_id=view_id,
                        floor_id=floor_id,
                        dimension_type="linear_vertical",
                        measurement_basis="stair_landing_depth",
                        ref_point_1_draw=[lx1_d, ly0_d],
                        ref_point_2_draw=[lx1_d, ly1_d],
                        measured_dec_draw=convert_length(ldy_m, "m", drawing_units),
                        source_measured_dec=ldy_m,
                        drawing_units=drawing_units,
                        precision=precision,
                        dim_line_start=[lx1_d, ly0_d],
                        dim_line_end=[lx1_d, ly1_d],
                        text_point=[lx1_d, (ly0_d + ly1_d) / 2.0],
                        extension_lines=[],
                        associated_entity_ids=[stair["id"], surf["id"]],
                        source_geometry_digest=src_rev_digest,
                        key_tag=f"landing_y_{surf['id']}",
                    )
                )

        if annotation_options.get("show_floor_opening_dims", True):
            stair_unit = stair_spec.get("units", "m")
            for fop in stair_spec.get("floor_openings", []):
                if fop["floor_id"] != floor_id:
                    continue
                fo_rect = _rect_exact_bounds_dec(shape_set(fop["geometry"]))
                if fo_rect is None:
                    unsupported.append(
                        {
                            "code": "AMBIGUOUS_IRREGULAR_FLOOR_OPENING",
                            "entity_id": fop["id"],
                            "floor_id": floor_id,
                            "basis": "floor_opening_dimensions",
                            "reason": "Non-rectangular floor opening span is ambiguous.",
                        }
                    )
                    continue
                fx0, fy0, fx1, fy1 = fo_rect
                for dt, basis, m_val, rp1_s, rp2_s in (
                    ("linear_horizontal", "floor_opening_width", fx1 - fx0, [zero_float(fx0), zero_float(fy1)], [zero_float(fx1), zero_float(fy1)]),
                    ("linear_vertical", "floor_opening_length", fy1 - fy0, [zero_float(fx1), zero_float(fy0)], [zero_float(fx1), zero_float(fy1)]),
                ):
                    dp1 = to_draw_pt(rp1_s, stair_unit)
                    dp2 = to_draw_pt(rp2_s, stair_unit)
                    dimensions.append(
                        _make_dimension_record(
                            view_id=view_id,
                            floor_id=floor_id,
                            dimension_type=dt,
                            measurement_basis=basis,
                            ref_point_1_draw=dp1,
                            ref_point_2_draw=dp2,
                            measured_dec_draw=convert_length(m_val, stair_unit, drawing_units),
                            source_measured_dec=m_val,
                            drawing_units=drawing_units,
                            precision=precision,
                            dim_line_start=dp1,
                            dim_line_end=dp2,
                            text_point=[(dp1[0] + dp2[0]) / 2.0, (dp1[1] + dp2[1]) / 2.0],
                            extension_lines=[],
                            associated_entity_ids=[fop["id"]],
                            source_geometry_digest=src_rev_digest,
                            key_tag=f"fop_{fop['id']}_{basis}",
                        )
                    )

    # 7. Vertical dimensions (floor-to-floor height + staircase sections)
    for wh in sorted(wall_heights, key=lambda x: x["floor_id"]):
        h_m = dec(wh["height"])
        dimensions.append(
            _make_dimension_record(
                view_id=f"PLAN-{wh['floor_id']}",
                floor_id=wh["floor_id"],
                dimension_type="vertical_elevation",
                measurement_basis="supplied_wall_height",
                ref_point_1_draw=[0.0, 0.0],
                ref_point_2_draw=[0.0, 0.0],
                measured_dec_draw=convert_length(h_m, "m", drawing_units),
                source_measured_dec=h_m,
                drawing_units=drawing_units,
                precision=precision,
                dim_line_start=[0.0, 0.0],
                dim_line_end=[0.0, 0.0],
                text_point=[0.0, 0.0],
                extension_lines=[],
                associated_entity_ids=[wh["floor_id"]],
                source_geometry_digest=src_rev_digest,
                key_tag=f"wall_height_{wh['floor_id']}",
            )
        )

    for stair in stairs_report.get("stairs", []):
        s_view = f"SECT-{stair['id']}"
        src_z_m = dec(stair["source_elevation_m"])
        dst_z_m = dec(stair["destination_elevation_m"])
        rise_m = dst_z_m - src_z_m
        src_z_d = convert_length(src_z_m, "m", drawing_units)
        dst_z_d = convert_length(dst_z_m, "m", drawing_units)
        rise_d = convert_length(rise_m, "m", drawing_units)
        prof_pts = [p for sec in stair.get("sections", []) for p in sec.get("profile", [])]
        max_x_d = zero_float(convert_length(max(p[0] for p in prof_pts), "m", drawing_units)) if prof_pts else 0.0
        min_x_d = zero_float(convert_length(min(p[0] for p in prof_pts), "m", drawing_units)) if prof_pts else 0.0
        dim_x = max_x_d + dim_offset * 1.4

        dimensions.append(
            _make_dimension_record(
                view_id=s_view,
                floor_id=None,
                dimension_type="linear_vertical",
                measurement_basis="floor_to_floor_height",
                ref_point_1_draw=[max_x_d, zero_float(src_z_d)],
                ref_point_2_draw=[max_x_d, zero_float(dst_z_d)],
                measured_dec_draw=rise_d,
                source_measured_dec=rise_m,
                drawing_units=drawing_units,
                precision=precision,
                dim_line_start=[dim_x, zero_float(src_z_d)],
                dim_line_end=[dim_x, zero_float(dst_z_d)],
                text_point=[dim_x + dim_text_h * 0.5, zero_float(src_z_d + dst_z_d) / 2.0],
                extension_lines=[
                    {"start": [max_x_d + ext_offset, zero_float(src_z_d)], "end": [dim_x + ext_overshoot, zero_float(src_z_d)]},
                    {"start": [max_x_d + ext_offset, zero_float(dst_z_d)], "end": [dim_x + ext_overshoot, zero_float(dst_z_d)]},
                ],
                associated_entity_ids=[stair["id"], stair["source_floor"], stair["destination_floor"]],
                source_geometry_digest=src_rev_digest,
                key_tag="floor_to_floor",
            )
        )

        # Landings & flights in section view
        for surf in stair.get("surfaces", []):
            if surf["kind"] != "landing":
                continue
            lz_m = dec(surf["elevation_m"])
            lz_d = convert_length(lz_m, "m", drawing_units)
            sec = next((s for s in stair["sections"] if s["id"] == surf["id"]), None)
            lx_d = zero_float(convert_length(sec["profile"][0][0], "m", drawing_units)) if sec else min_x_d
            dimensions.append(
                _make_dimension_record(
                    view_id=s_view,
                    floor_id=None,
                    dimension_type="vertical_elevation",
                    measurement_basis="stair_landing_elevation",
                    ref_point_1_draw=[lx_d, zero_float(src_z_d)],
                    ref_point_2_draw=[lx_d, zero_float(lz_d)],
                    measured_dec_draw=lz_d,
                    source_measured_dec=lz_m,
                    drawing_units=drawing_units,
                    precision=precision,
                    dim_line_start=[lx_d, zero_float(lz_d)],
                    dim_line_end=[lx_d, zero_float(lz_d)],
                    text_point=[lx_d, zero_float(lz_d) + dim_text_h * 0.6],
                    extension_lines=[],
                    associated_entity_ids=[stair["id"], surf["id"]],
                    source_geometry_digest=src_rev_digest,
                    key_tag=f"landing_elev_{surf['id']}",
                )
            )

        for fl in stair["flights"]:
            rh_m = dec(fl["riser_height_m"])
            td_m = dec(fl["tread_depth_m"])
            sp = fl.get("section_profile") or [[0.0, 0.0], [fl["tread_depth_m"], fl["riser_height_m"]]]
            step_pt = sp[min(8, max(len(sp) - 3, 0))]
            p_base = to_draw_pt(step_pt, "m")
            p_riser_top = to_draw_pt([step_pt[0], step_pt[1] + fl["riser_height_m"]], "m")
            p_tread_end = to_draw_pt([step_pt[0] + fl["tread_depth_m"], step_pt[1] + fl["riser_height_m"]], "m")
            dimensions.append(
                _make_dimension_record(
                    view_id=s_view,
                    floor_id=None,
                    dimension_type="linear_vertical",
                    measurement_basis="stair_riser_height",
                    ref_point_1_draw=p_base,
                    ref_point_2_draw=p_riser_top,
                    measured_dec_draw=convert_length(rh_m, "m", drawing_units),
                    source_measured_dec=rh_m,
                    drawing_units=drawing_units,
                    precision=precision,
                    dim_line_start=p_base,
                    dim_line_end=p_riser_top,
                    text_point=[p_base[0] - dim_text_h * 1.3, (p_base[1] + p_riser_top[1]) / 2.0],
                    extension_lines=[],
                    associated_entity_ids=[stair["id"], fl["id"]],
                    source_geometry_digest=src_rev_digest,
                    key_tag=f"riser_{fl['id']}",
                )
            )
            dimensions.append(
                _make_dimension_record(
                    view_id=s_view,
                    floor_id=None,
                    dimension_type="linear_horizontal",
                    measurement_basis="stair_tread_depth",
                    ref_point_1_draw=p_riser_top,
                    ref_point_2_draw=p_tread_end,
                    measured_dec_draw=convert_length(td_m, "m", drawing_units),
                    source_measured_dec=td_m,
                    drawing_units=drawing_units,
                    precision=precision,
                    dim_line_start=p_riser_top,
                    dim_line_end=p_tread_end,
                    text_point=[(p_riser_top[0] + p_tread_end[0]) / 2.0, p_riser_top[1] + dim_text_h * 1.1],
                    extension_lines=[],
                    associated_entity_ids=[stair["id"], fl["id"]],
                    source_geometry_digest=src_rev_digest,
                    key_tag=f"tread_{fl['id']}",
                )
            )

        # Verified local headroom witness measurement
        measures = [
            m
            for m in stairs_report.get("headroom", {}).get("measurements", [])
            if m["stair_id"] == stair["id"]
        ]
        if measures:
            minimum = min(measures, key=lambda m: (m["clearance_m"], m["surface_id"], m["obstruction_id"]))
            clr_m = dec(minimum["clearance_m"])
            walk_z_d = zero_float(convert_length(minimum["walking_elevation_m"], "m", drawing_units))
            under_z_d = zero_float(convert_length(minimum["underside_m"], "m", drawing_units))
            # Locate X on section profile via surface walking line projection
            from shapely.geometry import LineString

            surface = next((s for s in stair["surfaces"] if s["id"] == minimum["surface_id"]), None)
            x_sec_d = (min_x_d + max_x_d) / 2.0
            if surface:
                wanted = surface["flight_id"] if surface["kind"] == "tread" else surface["id"]
                sec_rec = next((s for s in stair["sections"] if s["id"] == wanted), None)
                fl_rec = next((f for f in stair["flights"] if f["id"] == wanted), None)
                wl_pts = fl_rec["walking_line"] if fl_rec else surface.get("walking_line")
                if sec_rec and wl_pts:
                    proj = LineString(wl_pts).project(Point(minimum["location_m"]))
                    x_sec_d = zero_float(convert_length(sec_rec["profile"][0][0] + proj, "m", drawing_units))
            dimensions.append(
                _make_dimension_record(
                    view_id=s_view,
                    floor_id=None,
                    dimension_type="vertical_clearance",
                    measurement_basis="stair_verified_local_headroom",
                    ref_point_1_draw=[x_sec_d, walk_z_d],
                    ref_point_2_draw=[x_sec_d, under_z_d],
                    measured_dec_draw=convert_length(clr_m, "m", drawing_units),
                    source_measured_dec=clr_m,
                    drawing_units=drawing_units,
                    precision=precision,
                    dim_line_start=[x_sec_d, walk_z_d],
                    dim_line_end=[x_sec_d, under_z_d],
                    text_point=[x_sec_d + dim_text_h * 0.6, (walk_z_d + under_z_d) / 2.0],
                    extension_lines=[],
                    associated_entity_ids=[stair["id"], minimum["surface_id"], minimum["obstruction_id"]],
                    source_geometry_digest=src_rev_digest,
                    key_tag="headroom_min",
                )
            )
        else:
            missing_info.append(
                {
                    "code": "HEADROOM_MEASUREMENTS_UNAVAILABLE",
                    "path": stair["id"],
                    "message": "No verified local headroom measurement available for stair section.",
                    "requirement_ids": [],
                }
            )

    return dimensions, chains, unsupported, missing_info
