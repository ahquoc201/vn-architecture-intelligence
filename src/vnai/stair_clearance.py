"""Continuous flat-surface clearance against explicit horizontal-bottom prisms."""

from math import fsum
from shapely.geometry import LineString
from shapely.ops import unary_union
from vnai.wall_topology import encode
from vnai.opening_hosts import shape_set
from vnai.stair_geometry import exact
from vnai.review_common import near_covers


def wall_prisms(source, levels):
    model = source["sources"]["wall_model"]
    spec = source["sources"]["input"]["specification"]
    scale = 1 if spec["units"] == "m" else 0.001
    verticals = {
        v["wall_id"]: v for v in spec["wall_verticals"] if v["confirmation"] == "confirmed"
    }
    records = []
    unknown = []
    for wall in model["walls"]:
        v = verticals.get(wall["id"])
        level = levels.get(wall["floor_id"])
        if v is None or level is None:
            unknown.append(wall["id"])
            continue
        from fractions import Fraction

        declared_scale = Fraction(1) if scale == 1 else Fraction(1, 1000)
        base_exact = level + exact(v["base"], declared_scale)
        base = float(base_exact)
        top = float(base_exact + exact(v["height"], declared_scale))
        cuts = []
        boundaries = {base, top}
        for o in source["openings"]:
            if o["host_wall_id"] != wall["id"] or not o["cut_accepted"]:
                continue
            low = o.get("sill_m") if o["type"].endswith("window") else o.get("bottom_m")
            high = o.get("head_m")
            if low is None or high is None:
                continue
            low = float(level + exact(low))
            high = float(level + exact(high))
            boundaries.update((max(base, min(top, low)), max(base, min(top, high))))
            cuts.append((low, high, shape_set(o["rough_cut"])))
        zs = sorted(boundaries)
        for low, high in zip(zs, zs[1:]):
            mid = (low + high) / 2
            g = shape_set(wall["geometry"]).difference(
                unary_union([p for a, b, p in cuts if a <= mid < b])
            )
            if not g.is_empty:
                records.append(
                    {
                        "id": wall["id"] + "@" + str(low),
                        "source_wall_id": wall["id"],
                        "kind": "wall",
                        "floor_id": wall["floor_id"],
                        "geometry": encode(g),
                        "bottom_m": low,
                        "top_m": high,
                    }
                )
    return records, unknown


def verify(stairs, spec, source, levels, ctx, scale, bad):
    tol, area_tol = ctx.tolerance, ctx.area_tolerance
    openings = {}
    slabs = []
    obstacles = []
    ids = set()
    for o in spec["floor_openings"]:
        if o["id"] in ids:
            bad("invalid", "DUPLICATE_FLOOR_OPENING", o["id"], "Floor opening IDs must be unique.")
        ids.add(o["id"])
        p = shape_set(o["geometry"])
        openings[o["id"]] = (o, p)
        if o["floor_id"] not in ctx.floors or not p.is_valid or p.is_empty:
            bad(
                "invalid",
                "FLOOR_OPENING_REFERENCE",
                o["id"],
                "Valid opening geometry and existing floor are required.",
            )
            continue
        if not near_covers(ctx.envelope(o["floor_id"]), p, tol):
            bad(
                "conflict",
                "FLOOR_OPENING_OUTSIDE_FLOOR",
                o["id"],
                "Floor opening leaves the actual permitted envelope.",
            )
        if not set(o["stair_ids"]) <= {s["id"] for s in spec["stairs"]}:
            bad(
                "invalid",
                "FLOOR_OPENING_STAIR_REFERENCE",
                o["id"],
                "Opening names an unknown generated stair.",
            )
    for slab in spec["slabs"]:
        floor = slab["floor_id"]
        footprint = shape_set(slab["geometry"])
        bottom = float(exact(slab["underside"], scale))
        top = float(exact(slab["top"], scale))
        holes = []
        if floor in ctx.floors and floor not in levels:
            bad(
                "missing",
                "SLAB_FLOOR_ELEVATION_REQUIRED",
                slab["id"],
                "Resolve this floor elevation before checking the slab interval.",
            )
            continue
        if floor not in levels or bottom >= top or top > float(levels.get(floor, 0)) + tol:
            bad(
                "invalid",
                "SLAB_VERTICAL_REFERENCE",
                slab["id"],
                "Slab needs a known floor, underside < top <= finished floor.",
            )
            continue
        if (
            not footprint.is_valid
            or footprint.is_empty
            or not near_covers(ctx.envelope(floor), footprint, tol)
        ):
            bad(
                "invalid",
                "SLAB_FOOTPRINT",
                slab["id"],
                "Slab footprint must be valid inside its floor.",
            )
            continue
        for oid in slab["opening_ids"]:
            if oid not in openings or openings[oid][0]["floor_id"] != floor:
                bad(
                    "invalid",
                    "SLAB_OPENING_REFERENCE",
                    slab["id"],
                    "Slab void must reference its same-floor declared opening.",
                )
                continue
            hole = openings[oid][1]
            if not near_covers(footprint, hole, tol):
                bad(
                    "conflict",
                    "SLAB_OPENING_CONTAINMENT",
                    oid,
                    "Opening extends outside the declared gross slab footprint.",
                )
            holes.append(hole)
        material = footprint.difference(unary_union(holes))
        record = {
            "id": slab["id"],
            "kind": "slab",
            "floor_id": floor,
            "geometry": encode(material),
            "bottom_m": bottom,
            "top_m": top,
            "opening_ids": slab["opening_ids"],
        }
        slabs.append(record)
        obstacles.append(record)
    for o in spec["obstacles"]:
        p = shape_set(o["geometry"])
        bottom = float(exact(o["bottom"], scale))
        top = float(exact(o["top"], scale))
        if not p.is_valid or p.is_empty or bottom >= top:
            bad(
                "invalid",
                "OBSTRUCTION_GEOMETRY",
                o["id"],
                "Supply a valid positive prism with bottom < top.",
            )
            continue
        obstacles.append(
            {
                "id": o["id"],
                "kind": o["kind"],
                "geometry": encode(p),
                "bottom_m": bottom,
                "top_m": top,
            }
        )
    walls, unknown = wall_prisms(source, levels)
    for wid in unknown:
        bad(
            "missing",
            "WALL_VERTICAL_COLLISION_UNKNOWN",
            wid,
            "Absolute retained wall intervals cannot be resolved.",
        )
    obstacles.extend(walls)
    shapes = [(o, shape_set(o["geometry"])) for o in obstacles]
    sky = unary_union([shape_set(g) for g in spec["open_to_sky"]])
    unresolved_upper = False
    measurements = []
    uncovered = []
    floor_assessment = []
    conflicts = []
    all_walk = []
    for stair in stairs:
        sid = stair["id"]
        poly = shape_set(stair["footprint"])
        for floor in [stair["source_floor"], stair["destination_floor"]]:
            reserved = [ctx.spaces.get(i) for i in stair["stairwell_ids"]]
            candidates = [
                s for s in reserved if s is not None and s.floor == floor and s.kind == "stairwell"
            ]
            if not candidates:
                bad(
                    "missing",
                    "STAIRWELL_RESERVATION_REQUIRED",
                    sid,
                    "Reference the existing stairwell reservation on each connected floor.",
                )
            elif not near_covers(unary_union([s.shape for s in candidates]), poly, tol):
                bad(
                    "conflict",
                    "STAIR_RESERVATION_FIT",
                    sid,
                    "Actual stair components exceed the unchanged source stairwell reservation.",
                )
        relevant_floors = sorted(
            floor
            for floor, z in levels.items()
            if stair["source_elevation_m"] < float(z) <= stair["destination_elevation_m"]
        )
        for destination in relevant_floors:
            applicable = [
                (o, p)
                for o, p in openings.values()
                if o["floor_id"] == destination and sid in o["stair_ids"]
            ]
            matching = [record for record in slabs if record["floor_id"] == destination]
            bound = bool(applicable and matching) and all(
                any(o["id"] in record["opening_ids"] for record in matching) for o, _ in applicable
            )
            if not applicable or not matching:
                bad(
                    "missing",
                    "SLAB_OPENING_INFORMATION_REQUIRED",
                    sid,
                    "Supply each crossed upper floor slab and its explicit stair opening; no slab thickness is invented.",
                )
            for opening, _ in applicable:
                if not any(opening["id"] in record["opening_ids"] for record in matching):
                    bad(
                        "missing",
                        "OPENING_NOT_BOUND_TO_SLAB",
                        opening["id"],
                        "An opening declaration without its slab binding cannot prove a void.",
                    )
            floor_assessment.append(
                {
                    "stair_id": sid,
                    "destination_floor": destination,
                    "opening_ids": [o["id"] for o, p in applicable],
                    "slab_ids": [record["id"] for record in matching],
                    "status": "MODELED" if bound else "INCOMPLETE",
                }
            )
        for surface in stair["surfaces"]:
            g = shape_set(surface["geometry"])
            z = surface["elevation_m"]
            all_walk.append(g)
            covered = sky.intersection(g)
            local = []
            for obs, p in shapes:
                overlap = g.intersection(p)
                # Geometry wholly below this surface does not obstruct its overhead.
                if overlap.area <= area_tol or obs["top_m"] <= z + tol:
                    continue
                clearance = float(exact(obs["bottom_m"]) - exact(z))
                covered = covered.union(overlap)
                pt = overlap.representative_point()
                item = {
                    "stair_id": sid,
                    "surface_id": surface["id"],
                    "obstruction_id": obs["id"],
                    "walking_elevation_m": z,
                    "underside_m": obs["bottom_m"],
                    "clearance_m": clearance,
                    "location_m": [pt.x, pt.y],
                    "region": encode(overlap),
                    "coverage": "CONTINUOUS_CONSTANT_HORIZONTAL_SURFACE_AND_PRISM",
                }
                measurements.append(item)
                local.append(item)
                if clearance < 0:
                    conflicts.append(
                        {
                            "stair_id": sid,
                            "surface_id": surface["id"],
                            "obstacle_id": obs["id"],
                            "geometry": encode(overlap),
                        }
                    )
                    bad(
                        "conflict",
                        "STAIR_WALL_COLLISION"
                        if obs["kind"] == "wall"
                        else "STAIR_PRISM_COLLISION",
                        surface["id"],
                        "Walking surface intersects explicit " + obs["id"] + ".",
                    )
                if "headroom_requirement" in spec and clearance + tol < float(
                    exact(spec["headroom_requirement"], scale)
                ):
                    bad(
                        "conflict",
                        "HEADROOM_BELOW_DECLARED_REQUIREMENT",
                        surface["id"],
                        "Known continuous clearance is below the supplied project requirement; this is not a normative threshold.",
                    )
            missing = g.difference(covered)
            if missing.area > area_tol:
                uncovered.append(
                    {"stair_id": sid, "surface_id": surface["id"], "region": encode(missing)}
                )
            for oid, floor, p in ctx.obstacles:
                if oid in stair["stairwell_ids"] or floor not in {
                    stair["source_floor"],
                    stair["destination_floor"],
                }:
                    continue
                    # 006-B fixed obstacles have no vertical interval; retain a conservative planar conflict.
                if g.intersection(p).area > area_tol:
                    bad(
                        "conflict",
                        "STAIR_FIXED_PLAN_COLLISION",
                        surface["id"],
                        "Plan projection intersects known fixed "
                        + oid
                        + "; its vertical extent is not inferred.",
                    )
        for riser in stair["risers_geometry"]:
            line = LineString(riser["line"])
            for obs, p in shapes:
                if (
                    min(riser["top_m"], obs["top_m"]) - max(riser["bottom_m"], obs["bottom_m"])
                    > tol
                    and line.intersection(p).length > tol
                    and line.relate_pattern(p, "T********")
                ):
                    bad(
                        "conflict",
                        "STAIR_RISER_PRISM_COLLISION",
                        riser["id"],
                        "Riser curtain intersects explicit prism " + obs["id"] + ".",
                    )
        for door in source["openings"]:
            if door["type"].endswith("window") or door["floor_id"] not in {
                stair["source_floor"],
                stair["destination_floor"],
            }:
                continue
            motion = door["primitives"].get("movement_envelope")
            if motion is not None and shape_set(motion).intersection(poly).area > area_tol:
                bad(
                    "conflict",
                    "DOOR_STAIR_MOVEMENT_COLLISION",
                    door["id"],
                    "Known door movement intersects the stair/landing plan; no door is moved.",
                )
        for other in stairs:
            if other["id"] <= sid:
                continue
            for first in stair["surfaces"]:
                for second in other["surfaces"]:
                    overlap = shape_set(first["geometry"]).intersection(
                        shape_set(second["geometry"])
                    )
                    if overlap.area <= area_tol:
                        continue
                    if abs(first["elevation_m"] - second["elevation_m"]) <= tol:
                        conflicts.append(
                            {
                                "stair_id": sid,
                                "surface_id": first["id"],
                                "obstacle_id": other["id"],
                                "geometry": encode(overlap),
                            }
                        )
                        bad(
                            "conflict",
                            "STAIR_STAIR_COLLISION",
                            sid,
                            "Distinct stair walking surfaces occupy the same plan region/elevation.",
                        )
                        continue
                    higher = first if first["elevation_m"] > second["elevation_m"] else second
                    modeled = any(
                        obs["kind"] == "upper_stair"
                        and abs(obs["top_m"] - higher["elevation_m"]) <= tol
                        and near_covers(polygon, overlap, tol)
                        for obs, polygon in shapes
                    )
                    if not modeled:
                        unresolved_upper = True
                        bad(
                            "missing",
                            "UPPER_STAIR_UNDERSIDE_REQUIRED",
                            sid,
                            "Overlapping upper walking geometry has no bound horizontal underside prism; a top surface does not prove headroom.",
                        )
    if uncovered:
        bad(
            "missing",
            "HEADROOM_COVERAGE_INCOMPLETE",
            "headroom",
            "Some walking regions have neither modeled overhead nor explicit open-to-sky evidence.",
        )
    if not spec["overhead_inventory_complete"]:
        bad(
            "missing",
            "OVERHEAD_INVENTORY_INCOMPLETE",
            "headroom",
            "Known local clearances do not exclude missing beams, ceilings or slabs.",
        )
    minimum = (
        min(
            measurements,
            key=lambda m: (m["clearance_m"], m["stair_id"], m["surface_id"], m["obstruction_id"]),
        )
        if measurements
        else None
    )
    unresolved_floors = sorted(
        {row["destination_floor"] for row in floor_assessment if row["status"] != "MODELED"}
        | (ctx.floors - set(levels))
    )
    floor_evidence_complete = not unresolved_floors and bool(floor_assessment)
    complete = (
        not uncovered
        and spec["overhead_inventory_complete"]
        and bool(stairs)
        and floor_evidence_complete
        and not unresolved_upper
    )
    failed = any(
        m["clearance_m"] < 0
        or (
            "headroom_requirement" in spec
            and m["clearance_m"] + tol < float(exact(spec["headroom_requirement"], scale))
        )
        for m in measurements
    )
    return {
        "floor_assessment": floor_assessment,
        "slab_material": slabs,
        "conflicts": conflicts,
        "headroom": {
            "status": "FAILED"
            if failed
            else "VERIFIED_MODELED_SCOPE"
            if complete
            else "INCOMPLETE",
            "scope": "CONTINUOUS_HORIZONTAL_WALKING_SURFACES_VS_HORIZONTAL_BOTTOM_PRISMS",
            "inventory_complete": spec["overhead_inventory_complete"],
            "coverage_complete": complete,
            "floor_opening_evidence_complete": floor_evidence_complete,
            "upper_stair_evidence_complete": not unresolved_upper,
            "unresolved_floor_ids": unresolved_floors,
            "minimum_verified_clearance_m": minimum["clearance_m"] if minimum else None,
            "minimum_location": minimum,
            "measurements": measurements,
            "uncovered_regions": uncovered,
            "walking_surface_area_m2": fsum(p.area for p in all_walk),
            "requirement_m": float(exact(spec["headroom_requirement"], scale))
            if "headroom_requirement" in spec
            else None,
            "technical_compliance": "NOT_EVALUATED",
        },
    }
