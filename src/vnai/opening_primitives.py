"""Metric opening cuts and deterministic single-leaf drafting primitives."""

from fractions import Fraction
import math
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import unary_union
from vnai.wall_topology import encode, polygons


def area(shape) -> float:
    """Local-origin shoelace with explicit stable aggregation, including all holes."""

    def ring(coords):
        pairs = list(coords)
        ox, oy = min(pairs)
        return (
            abs(
                math.fsum(
                    (x - ox) * (ny - oy) - (nx - ox) * (y - oy)
                    for (x, y), (nx, ny) in zip(pairs, pairs[1:])
                )
            )
            / 2
        )

    return (
        math.fsum(
            ring(p.exterior.coords) - math.fsum(ring(h.coords) for h in p.interiors)
            for p in polygons(shape)
        )
        if not shape.is_empty
        else 0.0
    )


def rectangle(start, end, normal, lo, hi):
    return Polygon(
        [
            [p[i] + normal[i] * d for i in (0, 1)]
            for p, d in ((start, lo), (end, lo), (end, hi), (start, hi))
        ]
    )


def quarter_sweep(pivot, direction, radius, rotation):
    """Circumscribed 90-degree sector using rational unit-circle tangents.

    Analytic arc is separate. Exact rational sampling avoids platform libm trig in
    serialized clearance vertices; this is a conservative enclosure, not a curve.
    """
    samples = []
    for i in range(33):
        t = Fraction(i, 32)
        samples.append(((1 - t * t) / (1 + t * t), 2 * t / (1 + t * t)))
    local = [(Fraction(0), Fraction(0)), samples[0]]
    for (x, y), (xx, yy) in zip(samples, samples[1:]):
        determinant = x * yy - xx * y
        local.append(((yy - y) / determinant, (x - xx) / determinant))
    local.append(samples[-1])
    side = 1 if rotation == "ccw" else -1
    left = [-direction[1] * side, direction[0] * side]
    return Polygon(
        [
            [
                math.fsum((pivot[k], direction[k] * float(x) * radius, left[k] * float(y) * radius))
                for k in (0, 1)
            ]
            for x, y in local
        ]
    )


def build(record: dict, spec: dict, problem) -> None:
    if "_cut" not in record or set(record["issues"]) - {
        "OPENING_SPEC_UNCONFIRMED",
        "OPENING_REVIEW_RECORD_REQUIRED",
    }:
        return
    row = record["_row"]
    scale = record["_scale"]
    key = row["id"]

    def bad(kind, code, message):
        record["issues"].append(code)
        problem(kind, code, key, message)

    wall = record["_wall"]
    cut = record["_cut"]
    normal = record["_normal"]
    u = record["_u"]
    start, end = record["_start"], record["_end"]
    width = record["rough_width_m"]

    def point(t, d):
        return [math.fsum((start[i], u[i] * t, normal[i] * d)) for i in (0, 1)]

    low, high = wall["normal_interval_m"]
    window = row["type"].endswith("window")
    bottom = row.get("sill") if window else row.get("bottom")
    height = row.get("rough_height")
    head = row.get("head")
    bottom = bottom * scale if bottom is not None else None
    height = height * scale if height is not None else None
    head = head * scale if head is not None else None
    if bottom is None or height is None:
        bad(
            "missing",
            "OPENING_VERTICAL_REQUIRED",
            "Supply explicit door bottom/window sill and rough height; no floor-height or cut-plane default.",
        )
    else:
        calculated = bottom + height
        if head is not None and not math.isclose(head, calculated, rel_tol=1e-12, abs_tol=1e-12):
            bad(
                "conflict",
                "OPENING_HEAD_HEIGHT",
                "Declared head must agree with sill/bottom plus rough height.",
            )
        head = calculated if head is None else head
    vertical = [v for v in spec.get("wall_verticals", []) if v["wall_id"] == wall["id"]]
    if len(vertical) != 1:
        bad(
            "missing" if not vertical else "invalid",
            "WALL_VERTICAL_REQUIRED",
            "Supply one explicit base/height record for this host; no lintel or wall height is inferred.",
        )
    elif vertical[0]["confirmation"] != "confirmed":
        bad("missing", "WALL_VERTICAL_UNCONFIRMED", "Host vertical dimensions remain unconfirmed.")
    elif bottom is not None and head is not None:
        base = vertical[0]["base"] * scale
        top = base + vertical[0]["height"] * scale
        if base != 0:
            bad(
                "unsupported",
                "RAISED_WALL_BASE_UNSUPPORTED",
                "Raised wall bases require an explicit elevated-wall floor-obstruction model.",
            )
        if bottom < base or head > top:
            bad(
                "conflict",
                "OPENING_OUTSIDE_WALL_HEIGHT",
                "Opening vertical interval extends outside the supplied wall base/top.",
            )
        record["wall_vertical_m"] = {
            "base": base,
            "top": top,
            "wall_below_opening": bottom - base,
            "wall_above_opening": top - head,
        }
    record.update(
        rough_height_m=height,
        bottom_m=bottom,
        head_m=head,
        sill_m=bottom if window else None,
        clear_width_m=row.get("clear_width") * scale if "clear_width" in row else None,
        clear_height_m=row.get("clear_height") * scale if "clear_height" in row else None,
        frame_inner_width_m=row.get("frame_inner_width") * scale
        if "frame_inner_width" in row
        else None,
    )
    if (
        record["clear_height_m"] is not None
        and height is not None
        and record["clear_height_m"] > height
    ):
        bad("conflict", "CLEAR_HEIGHT_EXCEEDS_ROUGH", "Clear height cannot exceed rough height.")
    if "plan_cut_height" not in spec:
        bad(
            "missing",
            "PLAN_CUT_HEIGHT_REQUIRED",
            "Declare the architectural plan cut elevation above finished floor.",
        )
    elif bottom is not None and head is not None:
        z = spec["plan_cut_height"] * scale
        record["plan_interpretation"] = (
            "INTERSECTS_OPENING"
            if bottom < z < head
            else "ABOVE_CUT_PLANE"
            if z <= bottom
            else "BELOW_CUT_PLANE"
        )
        if z in (bottom, head):
            bad(
                "unsupported",
                "PLAN_CUT_AT_OPENING_EDGE",
                "A cut exactly on sill/head requires assembly-specific interpretation.",
            )
    record["rough_cut"] = encode(cut)
    record["rough_cut_area_m2"] = area(cut)
    record["primitives"]["jamb_references"] = [
        [point(0, low), point(0, high)],
        [point(width, low), point(width, high)],
    ]
    frame = row.get("frame")
    if frame:
        jamb, depth = frame["jamb_width"] * scale, frame["depth"] * scale
        if 2 * jamb >= width or depth > wall["thickness_m"]:
            bad(
                "unsupported",
                "FRAME_DIMENSIONS",
                "Frame must fit this straight rough opening and known wall depth.",
            )
        else:
            inner = width - 2 * jamb
            if record["frame_inner_width_m"] is not None and not math.isclose(
                record["frame_inner_width_m"], inner, rel_tol=1e-12, abs_tol=1e-12
            ):
                bad(
                    "conflict",
                    "FRAME_INNER_WIDTH_MISMATCH",
                    "Supplied inner frame width disagrees with explicit jamb dimensions.",
                )
            record["frame_inner_width_m"] = inner
            middle = (low + high) / 2
            frame_shape = unary_union(
                [
                    rectangle(
                        point(0, 0), point(jamb, 0), normal, middle - depth / 2, middle + depth / 2
                    ),
                    rectangle(
                        point(width - jamb, 0),
                        point(width, 0),
                        normal,
                        middle - depth / 2,
                        middle + depth / 2,
                    ),
                ]
            )
            record["_frame"] = frame_shape
            record["primitives"]["frame"] = encode(frame_shape)
            record["primitives"]["frame_outline"] = encode(
                rectangle(start, end, normal, middle - depth / 2, middle + depth / 2)
            )
            if window:
                record["primitives"]["glazing"] = {
                    "start": point(jamb, middle),
                    "end": point(width - jamb, middle),
                    "representation": "ZERO_THICKNESS_SYMBOL_NOT_GLASS_ASSEMBLY",
                }
    elif window:
        bad(
            "missing",
            "WINDOW_FRAME_DIMENSIONS_REQUIRED",
            "Frame/glazing drafting requires explicit frame jamb width/depth.",
        )
    clear = record["clear_width_m"]
    if clear is not None:
        if clear > width or (
            record["frame_inner_width_m"] is not None and clear > record["frame_inner_width_m"]
        ):
            bad(
                "conflict",
                "CLEAR_WIDTH_EXCEEDS_FRAME",
                "Rough, frame and clear widths are distinct; clear span must fit.",
            )
        if "clear_start_offset" in row:
            c = row["clear_start_offset"] * scale
            if c + clear > width:
                bad(
                    "conflict",
                    "CLEAR_INTERVAL_OUTSIDE_ROUGH",
                    "Explicit clear passage interval extends beyond the rough opening.",
                )
            record["clear_reference"] = {"start": point(c, 0), "end": point(c + clear, 0)}
            if "mount_side" in row:
                mouth = high if row["mount_side"] == "left" else low
                record["clear_mouth_reference"] = {
                    "start": point(c, mouth),
                    "end": point(c + clear, mouth),
                }
            record["_passage"] = rectangle(point(c, 0), point(c + clear, 0), normal, low, high)
    if not window and (clear is None or "clear_start_offset" not in row):
        bad(
            "missing",
            "CLEAR_PASSAGE_DIMENSIONS_REQUIRED",
            "Supply clear passage width and its start offset independently from rough/frame/leaf widths.",
        )
    if row["type"] == "operable_window" and row.get("operation") != "side_hung":
        bad(
            "missing" if "operation" not in row else "unsupported",
            "WINDOW_OPERATION_REQUIRED",
            "Explicit side-hung operation is required; no other window mechanism is assumed.",
        )
        record["geometry_status"] = "PARTIAL"
        return
    needs_leaf = not window or row["type"] == "operable_window"
    if needs_leaf:
        leaf = row.get("leaf")
        motion = row.get("swing") if row["type"] != "sliding_door" else row.get("slide")
        if not leaf or not motion or "mount_side" not in row:
            bad(
                "missing",
                "LEAF_MOTION_REQUIRED",
                "Explicit leaf width/thickness/offset, mount side and hinge/swing or sliding travel are required.",
            )
        else:
            lw, lt, off = (leaf[k] * scale for k in ("width", "thickness", "hinge_offset"))
            if lw > width or off + lw > width:
                bad(
                    "conflict",
                    "LEAF_OUTSIDE_OPENING",
                    "Closed leaf dimensions/offset do not fit the rough span.",
                )
            side = 1 if row["mount_side"] == "left" else -1
            face = high if side == 1 else low
            hinge = motion.get("hinge", "start")
            origin = off if hinge == "start" else width - off
            direction = u if hinge == "start" else [-x for x in u]
            if row["type"] == "sliding_door":
                if motion["mode"] != "surface":
                    bad(
                        "unsupported",
                        "POCKET_DOOR_UNSUPPORTED",
                        "Pocket wall assembly is not inferred from a sliding leaf.",
                    )
                    record["geometry_status"] = "PARTIAL"
                    return
                if "mount_offset" not in row:
                    bad(
                        "missing",
                        "SLIDING_MOUNT_OFFSET_REQUIRED",
                        "Declare surface leaf stand-off; no pocket or available travel is inferred.",
                    )
                    record["geometry_status"] = "PARTIAL"
                    return
                face += side * (row.get("mount_offset", 0) * scale + lt / 2)
            pivot = point(origin, face)
            tip = [pivot[i] + direction[i] * lw for i in (0, 1)]
            closed = rectangle(pivot, tip, normal, -lt / 2, lt / 2)
            record["primitives"].update(
                closed_leaf=encode(closed),
                hinge_point=pivot,
                closed_leaf_reference={"start": pivot, "end": tip},
                leaf_width_m=lw,
                leaf_thickness_m=lt,
            )
            if row["type"] == "sliding_door":
                travel = motion["travel"] * scale
                sign = 1 if motion["direction"] == "end" else -1
                shifted = [
                    [p[i] + u[i] * travel * sign for i in (0, 1)] for p in closed.exterior.coords
                ]
                opened = Polygon(shifted)
                sweep = unary_union([closed, opened]).convex_hull
                if travel < lw:
                    bad(
                        "conflict",
                        "INSUFFICIENT_SLIDING_TRAVEL",
                        "Declared travel does not fully displace the supplied leaf width.",
                    )
                record["primitives"].update(
                    track={
                        "start": pivot,
                        "end": [pivot[i] + u[i] * travel * sign for i in (0, 1)],
                    },
                    travel_m=travel,
                    sliding_mode=motion["mode"],
                )
            elif motion["angle_degrees"] != 90:
                bad(
                    "unsupported",
                    "SWING_ANGLE_UNSUPPORTED",
                    "Only explicit orthogonal 90-degree single-leaf swings are supported.",
                )
                record["geometry_status"] = "PARTIAL"
                return
            else:
                rotate = 1 if motion["rotation"] == "ccw" else -1

                def rotated(p):
                    x, y = p[0] - pivot[0], p[1] - pivot[1]
                    return [pivot[0] - rotate * y, pivot[1] + rotate * x]

                opened = Polygon([rotated(p) for p in closed.exterior.coords])
                sector = quarter_sweep(pivot, direction, lw, motion["rotation"])
                sweep = MultiPoint(
                    [
                        (x + dx, y + dy)
                        for x, y in sector.exterior.coords
                        for dx in (-lt / 2, lt / 2)
                        for dy in (-lt / 2, lt / 2)
                    ]
                ).convex_hull
                record["primitives"]["swing_arc"] = {
                    "center": pivot,
                    "radius_m": lw,
                    "start": tip,
                    "end": rotated(tip),
                    "rotation": motion["rotation"],
                    "angle_degrees": 90,
                }
                record["primitives"]["sweep_method"] = (
                    "RATIONAL_CIRCUMSCRIBED_90_SECTOR_PLUS_SQUARE_LEAF_THICKNESS_BOUND"
                )
            record["_motion"] = sweep
            record["_leaf_open"] = opened
            record["_leaf_closed"] = closed
            record["primitives"].update(
                open_leaf=encode(opened),
                movement_envelope=encode(sweep),
                movement_envelope_area_m2=area(sweep),
            )
            state = row.get("operating_state")
            if state not in {"open", "closed"}:
                bad(
                    "missing",
                    "OPERATING_STATE_REQUIRED",
                    "Declare open/closed state; both drafting positions remain visible.",
                )
            record["_current_leaf"] = opened if state == "open" else closed
            record["operating_state"] = state
            if window and row.get("operation") != "side_hung":
                bad(
                    "unsupported",
                    "WINDOW_OPERATION_UNSUPPORTED",
                    "Only explicitly specified side-hung operable windows are supported.",
                )
    elif row.get("operating_state") not in (None, "fixed"):
        bad(
            "invalid",
            "FIXED_WINDOW_OPERATION",
            "A fixed window cannot declare an operable leaf state.",
        )
    record["geometry_status"] = "VALID" if not record["issues"] else "PARTIAL"
