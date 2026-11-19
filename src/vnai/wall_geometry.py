"""Constructive orthogonal wall bands and explicit finite junction cores."""

from itertools import combinations
import math
from typing import Any, Callable

from shapely.geometry import LineString, box
from shapely.ops import unary_union

from vnai.contracts import canonical_digest
from vnai.wall_topology import encode, line_parts, segment


def build_wall(
    boundary: dict,
    profile: dict,
    specification_ids: list[str],
    source: dict,
    semantics: str,
    problem: Callable,
) -> dict | None:
    key = boundary["id"]
    thickness = profile.get("thickness")
    alignment = profile.get("alignment")
    if not thickness or not alignment or not semantics:
        problem(
            "missing_information",
            "WALL_PARAMETERS_REQUIRED",
            key,
            "Explicit thickness, alignment and boundary semantics are required.",
        )
        return None
    t = thickness["value"] * (1 if thickness["unit"] == "m" else 0.001)
    offset = profile.get("offset", {"value": 0, "unit": "m"})
    shift = offset["value"] * (1 if offset["unit"] == "m" else 0.001)
    if max(abs(t), abs(shift)) > 1e9:
        problem(
            "unsupported",
            "WALL_NUMERIC_SCOPE",
            key,
            "Thickness/offset exceeds computational magnitude 1e9 m.",
        )
        return None
    side = boundary["envelope_interior_side"]
    reference_room = profile.get("reference_room_id")
    if alignment == "inward":
        if side is None:
            problem(
                "unsupported",
                "INWARD_REFERENCE_REQUIRED",
                key,
                "Inward alignment requires an exterior boundary with a known envelope side.",
            )
            return None
        alignment = side
    elif alignment == "toward_room":
        room_sides = boundary["room_sides"]
        if reference_room:
            side = room_sides.get(reference_room)
        else:
            sides = set(room_sides.values())
            side = next(iter(sides)) if len(sides) == 1 else None
        if side is None:
            problem(
                "missing_information",
                "REFERENCE_ROOM_REQUIRED",
                key,
                "Toward-room alignment needs an unambiguous source room side.",
            )
            return None
        alignment = side
    if semantics == "wall_centerline_reference" and profile["alignment"] != "centered":
        problem(
            "unsupported",
            "CENTERLINE_ALIGNMENT",
            key,
            "Declared centerline references require centered alignment; offset is an explicit centerline displacement.",
        )
        return None
    if semantics == "exterior_finished_face_reference":
        if boundary["kind"] != "exterior" or profile["alignment"] != "inward" or shift != 0:
            problem(
                "unsupported",
                "EXTERIOR_FACE_ALIGNMENT",
                key,
                "Exterior finished-face references require inward exterior walls without displacement.",
            )
            return None
    if semantics == "interior_finished_face_reference":
        room_side = boundary["room_sides"].get(reference_room)
        required_side = "right" if room_side == "left" else "left" if room_side == "right" else None
        if required_side is None:
            problem(
                "missing_information",
                "FINISHED_FACE_ROOM_REQUIRED",
                key,
                "Interior finished-face interpretation needs an exact adjacent reference_room_id.",
            )
            return None
        if alignment != required_side or shift != 0:
            problem(
                "unsupported",
                "INTERIOR_FACE_ALIGNMENT",
                key,
                "Wall material must remain away from the declared room finished face without displacement.",
            )
            return None
    low, high = (
        (-t / 2, t / 2) if alignment == "centered" else (0, t) if alignment == "left" else (-t, 0)
    )
    low, high = low + shift, high + shift
    a, b = boundary["reference"]["start"], boundary["reference"]["end"]
    horizontal = a[1] == b[1]
    normal = [0.0, 1.0] if horizontal else [-1.0, 0.0]
    band = (a[1] + low, a[1] + high) if horizontal else (a[0] - high, a[0] - low)
    if band[0] >= band[1]:
        problem(
            "unsupported",
            "WALL_PRECISION_COLLAPSE",
            key,
            "Wall thickness is not representable at the supplied coordinate magnitude; no repair applied.",
        )
        return None
    shape = box(a[0], band[0], b[0], band[1]) if horizontal else box(band[0], a[1], band[1], b[1])
    middle = (low + high) / 2
    center = segment(
        [a[i] + normal[i] * middle for i in (0, 1)], [b[i] + normal[i] * middle for i in (0, 1)]
    )
    identity = {"boundary_id": key, "specification_ids": sorted(specification_ids)}
    return {
        "id": "W-" + canonical_digest(identity),
        "boundary_id": key,
        "specification_ids": sorted(specification_ids),
        "floor_id": boundary["floor_id"],
        "source_candidate_id": source["candidate_id"],
        "source_candidate_digest": source["candidate_digest"],
        "related_room_ids": boundary["room_ids"],
        "affected_room_ids": [],
        "classification": profile["classification"],
        "reference": boundary["reference"],
        "centerline": center,
        "thickness_m": t,
        "measured_thickness_m": band[1] - band[0],
        "alignment": profile["alignment"],
        "offset_m": shift,
        "reference_semantics": semantics,
        "normal": normal,
        "normal_interval_m": [low, high],
        "geometry": encode(shape),
        "faces": [],
        "junction_ids": [],
        "fixed": profile["fixed"],
        "assembly_id": profile.get("assembly_id"),
        "requirement_ids": sorted(set(profile["requirement_ids"])),
        "provenance": [profile["provenance"]],
        "confirmation": profile["confirmation"],
        "declared_approval_status": profile["approval_status"],
        "approval_status": "PROPOSED",
        "area_m2": shape.area,
        "_shape": shape,
        "_horizontal": horizontal,
        "_band": band,
        "_patches": [],
        "_boundary": boundary,
    }


def junctions(walls: list[dict], problem: Callable) -> list[dict]:
    nodes: dict[tuple, list[dict]] = {}
    for wall in walls:
        for point in wall["reference"].values():
            nodes.setdefault((wall["floor_id"], *point), []).append(wall)
    records = []
    for node, incident in sorted(nodes.items()):
        floor, x, y = node
        incident.sort(key=lambda w: w["id"])
        horizontal = [w for w in incident if w["_horizontal"]]
        vertical = [w for w in incident if not w["_horizontal"]]
        count = len(incident)
        kind = (
            "END"
            if count == 1
            else "COLLINEAR"
            if not horizontal or not vertical
            else {2: "L", 3: "T", 4: "X"}.get(count, "UNSUPPORTED")
        )
        key = "WJ-" + canonical_digest([floor, x, y])
        cores = []
        core_shapes = []
        supported_node = kind != "UNSUPPORTED"
        if kind == "UNSUPPORTED":
            problem(
                "unsupported",
                "JUNCTION_DEGREE",
                key,
                "Only end, collinear, L, T and X reference junctions are supported.",
            )
        if kind == "COLLINEAR":
            for a, b in combinations(incident, 2):
                if max(a["_band"][0], b["_band"][0]) >= min(a["_band"][1], b["_band"][1]):
                    supported_node = False
                    problem(
                        "unsupported",
                        "COLLINEAR_OFFSET_GAP",
                        key,
                        "Collinear wall bands do not share a positive-width connection; no automatic bridge.",
                    )
        for h in horizontal:
            for v in vertical:
                patch = box(v["_band"][0], h["_band"][0], v["_band"][1], h["_band"][1])
                connected = all(
                    patch.intersection(w["_shape"]).area > 0
                    or patch.boundary.intersection(w["_shape"].boundary).length > 0
                    for w in (h, v)
                )
                if not connected:
                    supported_node = False
                    problem(
                        "unsupported",
                        "OFFSET_JUNCTION_DISCONNECTED",
                        key,
                        "Offset junction core cannot connect both finite incident bands; no geometric repair/extension across a gap.",
                    )
                    continue
                core_shapes.append(patch)
                for wall in (h, v):
                    wall["_patches"].append(patch)
                cores.append(
                    {
                        "wall_ids": sorted([h["id"], v["id"]]),
                        "geometry": encode(patch),
                        "area_m2": patch.area,
                    }
                )
        for wall in incident:
            wall["junction_ids"].append(key)
        combined = unary_union(core_shapes)
        records.append(
            {
                "id": key,
                "floor_id": floor,
                "point": [x, y],
                "kind": kind,
                "wall_ids": [w["id"] for w in incident],
                "geometry": encode(combined),
                "area_m2": combined.area,
                "pair_ownership": cores,
                "status": "VERIFIED" if supported_node else "UNSUPPORTED",
                "method": "FINITE_BAND_CORE_UNION_NO_SNAPPING",
            }
        )
    for wall in walls:
        wall["_shape"] = unary_union([wall["_shape"], *wall["_patches"]])
        wall["geometry"] = encode(wall["_shape"])
        wall["area_m2"] = wall["_shape"].area
        if not wall["_shape"].is_valid or wall["_shape"].geom_type != "Polygon":
            problem(
                "unsupported",
                "WALL_COMPONENTS",
                wall["id"],
                "Individual constructive wall must remain a valid connected polygon; all components are retained.",
            )
    return records


def faces(wall: dict, combined: Any) -> None:
    shape = wall["_shape"]
    x0, y0, x1, y1 = shape.bounds
    boundary = wall["_boundary"]
    for side, value in (
        ("right", wall["_band"][0 if wall["_horizontal"] else 1]),
        ("left", wall["_band"][1 if wall["_horizontal"] else 0]),
    ):
        supporting = (
            LineString([(x0, value), (x1, value)])
            if wall["_horizontal"]
            else LineString([(value, y0), (value, y1)])
        )
        exposed = combined.boundary.intersection(supporting).intersection(shape.boundary)
        lines = [segment(p.coords[0], p.coords[-1]) for p in line_parts(exposed) if p.length > 0]
        lines.sort(key=lambda r: (r["start"], r["end"]))
        role = (
            "interior"
            if boundary["kind"] != "exterior" or side == boundary["envelope_interior_side"]
            else "exterior"
        )
        room_ids = sorted(k for k, v in boundary["room_sides"].items() if v == side)
        wall["faces"].append(
            {
                "side": side,
                "role": role,
                "segments": lines,
                "length_m": sum(LineString([r["start"], r["end"]]).length for r in lines),
                "related_room_ids": room_ids or wall["related_room_ids"]
                if role == "interior"
                else [],
            }
        )
    measured = wall["measured_thickness_m"]
    bound = max(1e-12, 4 * max(math.ulp(v) for v in (*shape.bounds, measured)))
    wall["faces"][0]["floating_error_bound_m"] = bound
    wall["geometry_digest"] = canonical_digest(
        {"geometry": wall["geometry"], "faces": wall["faces"], "centerline": wall["centerline"]}
    )
