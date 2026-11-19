"""Union-based plan cuts versus floor obstructions and uncredited thresholds."""

from shapely.ops import unary_union
from vnai.opening_hosts import shape_set
from vnai.opening_primitives import area
from vnai.wall_topology import encode, polygons


def account(model: dict, records: list[dict], result: dict, spec: dict, problem) -> dict:
    floor_obstructions = {}
    for floor in model["floors"]:
        fid = floor["floor_id"]
        source = shape_set(floor["wall_footprint"])
        accepted = [r for r in records if r["floor_id"] == fid and r.get("cut_accepted")]
        thresholds = [
            r["_cut"]
            for r in accepted
            if not r["type"].endswith("window") and r.get("bottom_m") == 0
        ]
        floor_cut = source.intersection(unary_union(thresholds))
        obstruction = source.difference(floor_cut)
        floor_obstructions[fid] = obstruction
        wall_rows = []
        at_cut_sources = []
        at_cut_results = []
        vertical_complete = True
        for wall in model["walls"]:
            if wall["floor_id"] != fid:
                continue
            full = shape_set(wall["geometry"])
            own = [r for r in accepted if r["host_wall_id"] == wall["id"]]
            plan_removed = unary_union(
                [r["_cut"] for r in own if r["plan_interpretation"] == "INTERSECTS_OPENING"]
            )
            floor_removed = unary_union(
                [
                    r["_cut"]
                    for r in own
                    if not r["type"].endswith("window") and r.get("bottom_m") == 0
                ]
            )
            derived = full.difference(plan_removed)
            floor_wall = full.difference(floor_removed)
            if not derived.is_valid or not floor_wall.is_valid:
                problem(
                    "conflict",
                    "INVALID_DERIVED_WALL",
                    wall["id"],
                    "Wall cut produced invalid geometry; all components retained, no repair.",
                )
            vertical = next(
                (
                    v
                    for v in spec.get("wall_verticals", [])
                    if v["wall_id"] == wall["id"] and v["confirmation"] == "confirmed"
                ),
                None,
            )
            bands = []
            if vertical is not None:
                scale = 1.0 if spec["units"] == "m" else 0.001
                base_z = vertical["base"] * scale
                top_z = base_z + vertical["height"] * scale
                levels = sorted(
                    {
                        base_z,
                        top_z,
                        *[
                            r[k]
                            for r in own
                            for k in ("bottom_m", "head_m")
                            if r.get(k) is not None
                        ],
                    }
                )
                for bottom_z, head_z in zip(levels, levels[1:]):
                    if bottom_z < base_z or head_z > top_z or head_z <= bottom_z:
                        continue
                    active = [r for r in own if r["bottom_m"] <= bottom_z and r["head_m"] >= head_z]
                    band = full.difference(unary_union([r["_cut"] for r in active]))
                    bands.append(
                        {
                            "bottom_m": bottom_z,
                            "head_m": head_z,
                            "rough_void_opening_ids": [r["id"] for r in active],
                            "remaining_wall_geometry": encode(band),
                            "remaining_wall_area_m2": area(band),
                            "scope": "OPEN_VERTICAL_INTERVAL_ROUGH_VOIDS_ONLY_NOT_STRUCTURAL_ASSEMBLY",
                        }
                    )
            cut_source = full
            if vertical is not None and "plan_cut_height" in spec:
                cut_z = spec["plan_cut_height"] * scale
                if cut_z < base_z or cut_z > top_z:
                    cut_source = unary_union([])
                elif cut_z in (base_z, top_z):
                    vertical_complete = False
                    problem(
                        "unsupported",
                        "PLAN_CUT_ON_WALL_EDGE",
                        wall["id"],
                        "A cut exactly at wall base/top needs an explicit assembly-boundary convention.",
                    )
            else:
                vertical_complete = False
            derived = cut_source.difference(plan_removed)
            at_cut_sources.append(cut_source)
            at_cut_results.append(derived)
            wall_rows.append(
                {
                    "wall_id": wall["id"],
                    "source_geometry_digest": wall["geometry_digest"],
                    "plan_geometry": encode(derived),
                    "floor_obstruction_geometry": encode(floor_wall),
                    "plan_component_count": len(polygons(derived)),
                    "floor_component_count": len(polygons(floor_wall)),
                    "vertical_bands": bands,
                    "vertical_geometry_known": vertical is not None,
                    "component_policy": "ALL_COMPONENTS_RETAINED; split straight walls are expected after full-width cuts",
                }
            )
        before_openings = unary_union(at_cut_sources)
        remaining = unary_union(at_cut_results)
        plan_cut = before_openings.difference(remaining)
        frames = unary_union(
            [r["_frame"] for r in accepted if "_frame" in r and not r["type"].endswith("window")]
        )
        current_leaves = unary_union(
            [
                r["_current_leaf"]
                for r in accepted
                if "_current_leaf" in r and not r["type"].endswith("window")
            ]
        )
        all_proposed = unary_union(
            [r["_cut"] for r in records if r["floor_id"] == fid and "_cut" in r]
        )
        if not abs(area(before_openings) - area(plan_cut) - area(remaining)) <= max(
            1e-12, area(before_openings) * 1e-12
        ):
            problem(
                "conflict",
                "OPENING_AREA_CONSERVATION",
                fid,
                "Wall area at the declared cut plane must equal union opening cut plus remaining plan wall area.",
            )
        result["floors"].append(
            {
                "floor_id": fid,
                "source_wall_footprint": encode(source),
                "source_wall_area_m2": area(source),
                "wall_at_cut_before_openings": encode(before_openings),
                "wall_area_at_cut_before_openings_m2": area(before_openings),
                "wall_area_outside_cut_elevation_m2": area(source.difference(before_openings)),
                "proposed_cut_union": encode(all_proposed),
                "proposed_cut_union_area_m2": area(all_proposed),
                "accepted_rough_cut_union": encode(unary_union([r["_cut"] for r in accepted])),
                "plan_cut_geometry": encode(plan_cut),
                "plan_cut_area_m2": area(plan_cut),
                "wall_plan_at_cut": encode(remaining),
                "remaining_wall_plan_area_m2": area(remaining),
                "floor_wall_obstruction": encode(obstruction),
                "floor_wall_obstruction_area_m2": area(obstruction),
                "door_threshold_geometry": encode(floor_cut),
                "door_threshold_area_m2": area(floor_cut),
                "frame_obstruction": encode(frames),
                "leaf_obstruction_at_declared_state": encode(current_leaves),
                "floor_obstruction_with_door_assemblies": encode(
                    unary_union([obstruction, frames, current_leaves])
                ),
                "plan_cut_complete": vertical_complete
                and all(
                    r["cut_accepted"] and r["plan_interpretation"] != "INCOMPLETE_VERTICAL"
                    for r in records
                    if r["floor_id"] == fid
                ),
                "walls": wall_rows,
                "area_scope": "WALL_PLAN_AND_UNCREDITED_THRESHOLDS_NOT_GFA_OR_CERTIFIED_USABLE_AREA",
            }
        )
        for room in model["rooms"]:
            if room["floor_id"] != fid:
                continue
            result["rooms"].append(
                {
                    "room_id": room["room_id"],
                    "floor_id": fid,
                    "allocation_area_m2": room["allocation_area_m2"],
                    "clear_floor_area_m2": room["clear_area_m2"],
                    "clear_floor_geometry": room["clear_geometry"],
                    "door_threshold_contribution_m2": area(
                        floor_cut.intersection(shape_set(room["allocation_geometry"]))
                    ),
                    "room_area_policy": "exclude_thresholds",
                    "window_cut_added_to_room_area": False,
                    "source_wall_conflicts_resolved": False,
                }
            )
    return floor_obstructions
