"""Exact orthogonal boundary noding and canonical metric polygon serialization."""

from typing import Any

from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from vnai.contracts import canonical_digest


def polygon(row: dict, scale: float) -> Polygon:
    return Polygon(
        [(x * scale, y * scale) for x, y in row["exterior"]],
        [[(x * scale, y * scale) for x, y in ring] for ring in row.get("holes", [])],
    )


def orthogonal(shape: Polygon) -> bool:
    return (
        shape.is_valid
        and not shape.interiors
        and all(
            a[0] == b[0] or a[1] == b[1]
            for a, b in zip(shape.exterior.coords, list(shape.exterior.coords)[1:])
        )
    )


def segment(a: Any, b: Any) -> dict:
    a, b = sorted((tuple(a), tuple(b)))
    return {
        "start": [0.0 if v == 0 else float(v) for v in a],
        "end": [0.0 if v == 0 else float(v) for v in b],
    }


def line_parts(shape: Any) -> list:
    if shape.is_empty:
        return []
    if shape.geom_type in {"LineString", "LinearRing"}:
        return [shape]
    return [line for part in getattr(shape, "geoms", []) for line in line_parts(part)]


def polygons(shape: Any) -> list[Polygon]:
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    return [p for child in getattr(shape, "geoms", []) for p in polygons(child)]


def encode(shape: Any) -> dict:
    def ring(coords: Any) -> list[list[float]]:
        points = [tuple(0.0 if v == 0 else float(v) for v in p) for p in coords[:-1]]
        # GEOS may retain collinear nodes; remove only mathematically redundant points.
        changed = True
        while changed and len(points) > 3:
            changed = False
            for i in range(len(points)):
                a, b, c = points[i - 1], points[i], points[(i + 1) % len(points)]
                if (a[0] == b[0] == c[0] or a[1] == b[1] == c[1]) and a != c:
                    points.pop(i)
                    changed = True
                    break
        first = min(range(len(points)), key=lambda i: points[i])
        points = points[first:] + points[:first]
        return [list(p) for p in [*points, points[0]]]

    result = []
    for part in polygons(shape):
        part = orient(part, sign=1)
        result.append(
            {
                "exterior": ring(list(part.exterior.coords)),
                "holes": sorted([ring(list(h.coords)) for h in part.interiors]),
            }
        )
    result.sort(key=lambda p: (p["exterior"], p["holes"]))
    return {"type": "PolygonSet", "units": "m", "polygons": result}


def extract(geometry: dict, special: list[dict]) -> tuple[list[dict], dict, dict, dict]:
    scale = 1 if geometry["units"] == "m" else 0.001
    rows = geometry["polygons"]
    shapes = {r["id"]: polygon(r, scale) for r in rows}
    footprint = next((r for r in rows if r["role"] == "footprint"), None)
    if footprint is None:
        raise ValueError("INCOMPLETE: explicit footprint is required; site is not a wall envelope.")
    envelopes, boundaries = {}, []
    for floor in sorted(f["id"] for f in geometry["floors"]):
        envelope_row = next(
            (r for r in rows if r["role"] == "floor_outline" and r.get("floor_id") == floor),
            footprint,
        )
        envelope = shapes[envelope_row["id"]]
        if not orthogonal(envelope) or not envelope.equals(box(*envelope.bounds)):
            raise ValueError(
                "UNSUPPORTED: wall envelopes must be valid axis-aligned rectangles without holes."
            )
        envelopes[floor] = envelope
        edges = []
        active = [(envelope_row, "envelope")]
        active += [
            (r, r["role"])
            for r in rows
            if r.get("floor_id") == floor and r["role"] in {"room", "reservation"}
        ]
        for row, role in active:
            shape = shapes[row["id"]]
            if not orthogonal(shape):
                raise ValueError(
                    "UNSUPPORTED: nonorthogonal, invalid or holed allocation/reservation boundary: "
                    + row["id"]
                )
            coords = list(orient(shape, sign=1).exterior.coords)
            for a, b in zip(coords, coords[1:]):
                if a == b:
                    continue
                ref = segment(a, b)
                forward = list(a) == ref["start"]
                edges.append(
                    {
                        "line": LineString([ref["start"], ref["end"]]),
                        "role": role,
                        "id": row["id"],
                        "room_id": row.get("room_id"),
                        "side": "left" if forward else "right",
                    }
                )
        for item in special:
            if item["floor_id"] != floor:
                continue
            if item["units"] != geometry["units"] or item["frame_id"] != geometry["frame"]["id"]:
                raise ValueError(
                    "UNSUPPORTED: special references must use the exact source frame and coordinate units."
                )
            a, b = (tuple(v * scale for v in item["reference"][k]) for k in ("start", "end"))
            if any(abs(v) > 1e9 for point in (a, b) for v in point):
                raise ValueError(
                    "UNSUPPORTED: special reference exceeds coordinate magnitude 1e9 m."
                )
            if a == b or (a[0] != b[0] and a[1] != b[1]):
                raise ValueError(
                    "UNSUPPORTED: special wall references must be positive straight orthogonal segments."
                )
            ref = segment(a, b)
            edges.append(
                {
                    "line": LineString([ref["start"], ref["end"]]),
                    "role": "special",
                    "id": item["id"],
                }
            )
        if len(edges) > 256:
            raise ValueError("UNSUPPORTED: at most 256 source edges per floor are supported.")
        noded = unary_union([e["line"] for e in edges])
        atoms = {}
        for part in line_parts(noded):
            coords = list(part.coords)
            for a, b in zip(coords, coords[1:]):
                if a != b:
                    ref = segment(a, b)
                    atoms[canonical_digest(ref)] = ref
        for ref in sorted(atoms.values(), key=lambda r: (r["start"], r["end"])):
            line = LineString([ref["start"], ref["end"]])
            owners = [e for e in edges if e["line"].covers(line)]
            room_sides = {e["room_id"]: e["side"] for e in owners if e["role"] == "room"}
            reservations = sorted(e["id"] for e in owners if e["role"] == "reservation")
            specials = sorted(e["id"] for e in owners if e["role"] == "special")
            envelope_side = next((e["side"] for e in owners if e["role"] == "envelope"), None)
            if envelope_side:
                kind = "exterior"
            elif len(room_sides) >= 2:
                kind = "shared"
            elif room_sides:
                kind = "room_reserved" if reservations else "room_unallocated"
            else:
                kind = "special" if specials else "reservation_only"
            related = set(room_sides)
            if specials:
                related.update(
                    r["room_id"]
                    for r in rows
                    if r["role"] == "room"
                    and r.get("floor_id") == floor
                    and shapes[r["id"]].intersection(line).length > 0
                )
            record = {
                "floor_id": floor,
                "kind": kind,
                "reference": ref,
                "room_ids": sorted(related),
                "room_sides": dict(sorted(room_sides.items())),
                "reservation_ids": reservations,
                "source_geometry_ids": sorted(set(e["id"] for e in owners)),
                "special_ids": specials,
                "envelope_interior_side": envelope_side,
                "length_m": line.length,
            }
            record["id"] = "WB-" + canonical_digest(
                {k: record[k] for k in ("floor_id", "reference", "room_ids", "source_geometry_ids")}
            )
            boundaries.append(record)
            if len(boundaries) > 512:
                raise ValueError(
                    "UNSUPPORTED: at most 512 normalized wall boundary atoms are supported."
                )
    return boundaries, envelopes, shapes, {r["room_id"]: r for r in rows if r["role"] == "room"}


def non_area_components(shape: Any) -> list[dict]:
    from shapely.geometry import mapping

    if shape.is_empty or shape.geom_type == "Polygon":
        return []
    if hasattr(shape, "geoms"):
        return [p for child in shape.geoms for p in non_area_components(child)]
    return [dict(mapping(shape))]
