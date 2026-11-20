"""New immutable B4 synthetic benchmark inputs, not architectural standards."""

from copy import deepcopy
from floorplan_fixtures import synthetic_spec, approve_source
from vnai.zoning import create_zoning_proposal
from vnai.contracts import canonical_digest

NOTICE = "Synthetic B4 fixture inputs only; not a real architect approval or Vietnamese regulatory default."


def shape(x0, y0, x1, y1):
    return {
        "type": "PolygonSet",
        "units": "m",
        "polygons": [{"exterior": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "holes": []}],
    }


def _townhouse_v3():
    g = synthetic_spec(4, 16, groups=3)
    geo = g["geometry"]
    brief = geo["zoning"]["brief"]
    brief["project"]["id"] = "B4-SYNTHETIC-TOWNHOUSE"
    geo["project_id"] = brief["project"]["id"]
    brief["project"]["name"] = NOTICE
    brief["site"]["dimensions"]["value"].update(width=4, length=20)
    brief["building"]["storeys"]["value"] = 2
    brief["building"]["floors"] = [
        {"id": "F1", "label": "Synthetic ground", "elevation": {"value": 0, "unit": "m"}},
        {"id": "F2", "label": "Synthetic upper", "elevation": {"value": 3.3, "unit": "m"}},
    ]
    for r in brief["building"]["rooms"]:
        r.update(
            quantity=2 if r["id"] == "BED" else 1,
            floor_id="F2" if r["id"] == "BED" else "F1",
            area={"min": 20, "max": 24, "target": 24, "unit": "m2"},
        )
    for floor in brief["building"]["floors"]:
        floor.pop("elevation", None)
    zoning = create_zoning_proposal(brief, "B4-SYNTHETIC-ZONING")
    for a in zoning["assignments"]:
        a["zone"] = "synthetic declared functional zone"
    geo["zoning"] = zoning
    geo["floors"] = [{"id": "F1", "elevation_m": 0}, {"id": "F2", "elevation_m": 3.3}]

    def poly(key, role, floor, coords, kind=None):
        p = {
            "id": key,
            "role": role,
            "owner_id": floor or geo["project_id"],
            "frame_id": "LOCAL",
            "units": "m",
            "exterior": coords,
            "holes": [],
            "status": "proposed",
        }
        if floor:
            p["floor_id"] = floor
        if kind:
            p.update(
                reservation_kind=kind, provenance=NOTICE, requirement_id="REQ-internal_circulation"
            )
        return p

    geo["polygons"] = [
        poly("SITE", "site", None, [[0, 0], [4, 0], [4, 20], [0, 20]]),
        poly("FOOTPRINT", "footprint", None, [[0, 2], [4, 2], [4, 18], [0, 18]]),
    ]
    for f in ["F1", "F2"]:
        geo["polygons"] += [
            poly(
                "COR-" + f,
                "reservation",
                f,
                [[0, 8], [1.05, 8], [1.05, 12], [0, 12]],
                "circulation",
            ),
            poly(
                "SW-" + f,
                "reservation",
                f,
                [[1.05, 8], [3.8, 8], [3.8, 11], [1.05, 11]],
                "stairwell",
            ),
            poly(
                "SHAFT-" + f,
                "reservation",
                f,
                [[3.4, 11], [3.8, 11], [3.8, 12], [3.4, 12]],
                "service_shaft",
            ),
        ]
    g["room_dimensions"] = [
        {
            "room_id": a["room_id"],
            "requirement_id": a["requirement_id"],
            "width": {"min": 4, "max": 4},
            "depth": {"min": 5.5, "max": 6},
        }
        for a in zoning["assignments"]
    ]
    g["parameters"].update(grid_step=0.5, candidate_count=1, solution_limit=1, max_steps=100000)
    approve_source(g)

    def region(key, f, coords):
        return poly(key, "reservation", f, coords, "circulation")

    approach = region("APPROACH", "F1", [[0, 0], [4, 0], [4, 2], [0, 2]])
    obstacle = region("FIXED-CABINET", "F1", [[2.2, 2.3], [2.85, 2.3], [2.85, 3.1], [2.2, 3.1]])
    obstacle["reservation_kind"] = "other"
    exteriors = [
        {
            "id": "OUT",
            "floor_id": "F1",
            "boundary_id": "FOOTPRINT",
            "approach_id": "APPROACH",
            "provenance": NOTICE,
        },
        {"id": "OUT2", "floor_id": "F2", "boundary_id": "FOOTPRINT", "provenance": NOTICE},
    ]
    template = {
        "fixture_notice": NOTICE,
        "exteriors": exteriors,
        "openings": [],
        "openings_complete": True,
        "stairs": [],
        "stairs_complete": True,
        "fixed_obstacles": [obstacle],
        "fixed_obstacles_complete": True,
        "clearance_regions": [approach],
        "passages": [],
    }

    def profile(t, align, kind, fixed=False):
        return {
            "classification": kind,
            "thickness": {"value": t, "unit": "m"},
            "alignment": align,
            "fixed": fixed,
            "requirement_ids": [],
            "provenance": NOTICE,
            "confirmation": "confirmed",
            "approval_status": "proposed",
        }

    ws = {
        "id": "B4-WALLS",
        "boundary_semantics": "allocation_boundary",
        "default_treatment": "no_wall",
        "constraint_basis": {"area": "allocation", "dimensions": "allocation"},
        "treatments": [
            {
                "id": "EXTERIOR",
                "selector": {"kind": "exterior"},
                "action": "wall",
                "wall": profile(0.2, "inward", "exterior", True),
                "rationale": NOTICE,
            },
            {
                "id": "ROOM-RESERVED",
                "selector": {"kind": "room_reserved"},
                "action": "wall",
                "wall": profile(0.1, "toward_room", "interior_partition"),
                "rationale": NOTICE,
            },
        ],
        "special_walls": [],
    }
    ws["treatments"].append(
        {
            "id": "ROOM-UNALLOCATED",
            "selector": {"kind": "room_unallocated"},
            "action": "wall",
            "wall": profile(0.1, "toward_room", "interior_partition"),
            "rationale": NOTICE,
        }
    )
    for f in ["F1", "F2"]:
        ws["special_walls"].append(
            {
                "id": "STAIR-WALL-" + f,
                "floor_id": f,
                "frame_id": "LOCAL",
                "units": "m",
                "reference": {"start": [1.05, 8], "end": [1.05, 12]},
                "wall": profile(0.1, "left", "interior_partition", True),
                "rationale": NOTICE,
            }
        )
    op = {
        "id": "B4-OPENINGS",
        "units": "m",
        "frame_id": "LOCAL",
        "vertical_datum": "above_finished_floor",
        "plan_cut_height": 1.2,
        "wall_verticals": [],
        "openings": [],
        "openings_complete": True,
        "fixed_obstacles_complete": True,
        "stairs_complete": True,
        "room_area_policy": "exclude_thresholds",
        "clearance_regions": [approach],
        "additional_obstacles": [],
        "passages": [],
        "stairs": [],
        "exteriors": exteriors,
    }
    hosts = []

    def door(key, f, spaces, ref, offset, side, rotation, into, kind="interior", depth=0.1):
        cid = "CLEAR-" + key
        # Explicit conservative declared clearance region, never inferred by the engine.
        clear = region(cid, f, [[0, 0], [4, 0], [4, 20], [0, 20]])
        op["clearance_regions"].append(clear)
        op["openings"].append(
            {
                "id": key,
                "mark": key,
                "type": "hinged_door",
                "kind": kind,
                "floor_id": f,
                "offset": offset,
                "rough_width": 0.72,
                "rough_height": 2.2,
                "bottom": 0,
                "clear_width": 0.56,
                "clear_height": 2.1,
                "clear_start_offset": 0.08,
                "frame_inner_width": 0.64,
                "frame": {"jamb_width": 0.04, "depth": depth, "alignment": "centered_in_wall"},
                "leaf": {"width": 0.60, "thickness": 0.03, "hinge_offset": 0.06},
                "mount_side": side,
                "swing": {
                    "hinge": "start",
                    "rotation": rotation,
                    "angle_degrees": 90,
                    "opens_into": into,
                },
                "operating_state": "open",
                "space_ids": spaces,
                "clearance_id": cid,
                "requirement_ids": [],
                "provenance": NOTICE,
                "confirmation": "confirmed",
                "review_state": "proposed",
            }
        )
        hosts.append(
            {"opening_id": key, "floor_id": f, "references": [{"start": ref[0], "end": ref[1]}]}
        )

    door(
        "ENTRANCE",
        "F1",
        ["LIVING:1", "OUT"],
        [[0, 2], [4, 2]],
        2,
        "left",
        "ccw",
        "LIVING:1",
        "entrance",
        0.2,
    )
    for f, front, back in [("F1", "LIVING:1", "KITCHEN:1"), ("F2", "BED:1", "BED:2")]:
        door("FRONT-" + f, f, [front, "COR-" + f], [[0, 8], [1.05, 8]], 0.215, "right", "cw", front)
        door("REAR-" + f, f, [back, "COR-" + f], [[0, 12], [1.05, 12]], 0.215, "left", "ccw", back)
        door(
            "STAIR-" + f,
            f,
            ["COR-" + f, "SW-" + f],
            [[1.05, 8], [1.05, 11]],
            0.34 if f == "F1" else 1.34,
            "left",
            "ccw",
            "COR-" + f,
        )
        win = {
            "id": "WINDOW-" + f,
            "mark": "W-" + f,
            "type": "fixed_window",
            "kind": "window",
            "floor_id": f,
            "offset": 1.5,
            "rough_width": 0.8,
            "rough_height": 1,
            "sill": 0.9,
            "head": 1.9,
            "frame": {"jamb_width": 0.04, "depth": 0.2, "alignment": "centered_in_wall"},
            "space_ids": [back, "OUT" if f == "F1" else "OUT2"],
            "operating_state": "fixed",
            "requirement_ids": [],
            "provenance": NOTICE,
            "confirmation": "confirmed",
            "review_state": "proposed",
        }
        op["openings"].append(win)
        hosts.append(
            {
                "opening_id": win["id"],
                "floor_id": f,
                "references": [{"start": [0, 18], "end": [4, 18]}],
            }
        )

    def path(key, f, space, coords, ids):
        return {
            "id": key,
            "floor_id": f,
            "space_id": space,
            "frame_id": "LOCAL",
            "units": "m",
            "path": coords,
            "width": 0.5,
            "opening_ids": ids,
            "confirmation": "confirmed",
            "provenance": NOTICE,
        }

    for f, front, back, stairy in [
        ("F1", "LIVING:1", "KITCHEN:1", 8.7),
        ("F2", "BED:1", "BED:2", 9.7),
    ]:
        op["passages"] += [
            path("FRONT-PATH-" + f, f, front, [[0.575, 8], [0.575, 6.8]], ["FRONT-" + f]),
            path("REAR-PATH-" + f, f, back, [[0.575, 12], [0.575, 13]], ["REAR-" + f]),
            path(
                "COR-FRONT-" + f,
                f,
                "COR-" + f,
                [[0.575, 8], [0.575, stairy], [1.05, stairy]],
                ["FRONT-" + f, "STAIR-" + f],
            ),
            path(
                "COR-REAR-" + f,
                f,
                "COR-" + f,
                [[0.575, 12], [0.575, stairy], [1.05, stairy]],
                ["REAR-" + f, "STAIR-" + f],
            ),
        ]
    op["passages"] += [
        path(
            "ENTRANCE-INTERIOR",
            "F1",
            "LIVING:1",
            [[2.36, 2], [2.36, 6.8], [0.575, 6.8], [0.575, 8]],
            ["ENTRANCE", "FRONT-F1"],
        ),
        path("ENTRANCE-EXTERIOR", "F1", "OUT", [[2.36, 2], [2.36, 1]], ["ENTRANCE"]),
    ]
    connection = {
        "schema_version": 1,
        "id": "S1",
        "direction": "up",
        "frame_id": "LOCAL",
        "units": "m",
        "alignment_required": True,
        "confirmation": "confirmed",
        "review_status": "proposed",
        "provenance": NOTICE,
        "source": {
            "floor_id": "F1",
            "stairwell_id": "SW-F1",
            "space_id": "COR-F1",
            "point": [1.05, 8.7],
            "opening_id": "STAIR-F1",
        },
        "destination": {
            "floor_id": "F2",
            "stairwell_id": "SW-F2",
            "space_id": "COR-F2",
            "point": [1.05, 9.7],
            "opening_id": "STAIR-F2",
        },
    }
    op["stairs"] = [connection]
    template["stairs"] = [connection]
    ws["reservation_wall_contacts"] = [
        {
            "reservation_id": "COR-" + f,
            "floor_id": f,
            "geometry": {
                "type": "PolygonSet",
                "units": "m",
                "polygons": shape(0, 8, 0.2, 12)["polygons"] + shape(0.95, 8, 1.05, 12)["polygons"],
            },
            "confirmation": "confirmed",
            "provenance": NOTICE,
        }
        for f in ["F1", "F2"]
    ]
    stair = {
        "id": "B4-STAIRS",
        "units": "m",
        "frame_id": "LOCAL",
        "datum": "synthetic_ground_FFE_z0",
        "levels": [
            {
                "floor_id": f,
                "finished_elevation": z,
                "confirmation": "confirmed",
                "provenance": NOTICE,
            }
            for f, z in [("F1", 0), ("F2", 3.3)]
        ],
        "stairs": [
            {
                "id": "S1",
                "mark": "ST01",
                "type": "U",
                "source_floor": "F1",
                "destination_floor": "F2",
                "stairwell_ids": ["SW-F1", "SW-F2"],
                "envelope": shape(1.05, 8, 3.8, 11),
                "counting": "arrival_surface",
                "flights": [
                    {
                        "id": "FL1",
                        "origin": [1.05, 8.3],
                        "direction": "E",
                        "width": 0.8,
                        "risers": 10,
                        "tread_depth": 0.24,
                    },
                    {
                        "id": "FL2",
                        "origin": [3.21, 10.1],
                        "direction": "W",
                        "width": 0.8,
                        "risers": 10,
                        "tread_depth": 0.24,
                    },
                ],
                "landings": [
                    {
                        "id": "LAND",
                        "geometry": shape(3.21, 8.3, 3.8, 10.1),
                        "elevation": 1.65,
                        "walking_line": [[3.21, 8.7], [3.505, 8.7], [3.505, 9.7], [3.21, 9.7]],
                    }
                ],
                "turn": "left",
                "flight_separation": 0.2,
                "requirement_ids": [],
                "confirmation": "confirmed",
                "review_status": "proposed",
                "provenance": NOTICE,
            }
        ],
        "plan_cut_elevations": [
            {"floor_id": "F1", "elevation": 1.2},
            {"floor_id": "F2", "elevation": 4.5},
        ],
        "number_steps": True,
        "floor_openings": [
            {
                "id": "VOID-F2",
                "floor_id": "F2",
                "geometry": shape(1.05, 8, 3.8, 11),
                "stair_ids": ["S1"],
            }
        ],
        "slabs": [
            {
                "id": "SLAB-F2",
                "floor_id": "F2",
                "geometry": shape(0, 2, 4, 18),
                "underside": 3.1,
                "top": 3.3,
                "opening_ids": ["VOID-F2"],
            }
        ],
        "obstacles": [
            {
                "id": "CEILING",
                "kind": "ceiling",
                "geometry": shape(0, 2, 4, 18),
                "bottom": 6.3,
                "top": 6.5,
                "provenance": NOTICE,
            }
        ],
        "open_to_sky": [],
        "overhead_inventory_complete": True,
        "headroom_requirement": 2.1,
        "clear_width_requirement": 0.5,
        "connections": [connection],
        "stairs_complete": True,
    }
    updated = [deepcopy(p) for p in op["passages"] if p["id"].startswith("ENTRANCE-")]
    for p in updated:
        p["path"] = [[1.16 if x == 2.36 else x, y] for x, y in p["path"]]
    result = {
        "schema_version": 1,
        "id": "B4-TOWNHOUSE-4X20-v1",
        "provenance": NOTICE,
        "generation": g,
        "requirements_digest": canonical_digest(brief),
        "review_template": template,
        "wall_specification": ws,
        "wall_heights": [
            {
                "floor_id": f,
                "base": 0,
                "height": 3.3,
                "provenance": NOTICE,
                "confirmation": "confirmed",
            }
            for f in ["F1", "F2"]
        ],
        "opening_specification": op,
        "opening_hosts": hosts,
        "stair_specification": stair,
        "clear_requirements": [
            {
                "room_id": a["room_id"],
                "requirement_id": a["requirement_id"],
                "area_m2": {"min": 20, "max": 24},
                "width_m": {"min": 3.5, "max": 4},
                "depth_m": {"min": 5.5, "max": 6},
            }
            for a in zoning["assignments"]
        ],
        "placement_regions": [
            {
                "room_id": rid,
                "geometry": shape(
                    0,
                    2 if rid in ["LIVING:1", "BED:1"] else 12,
                    4,
                    8 if rid in ["LIVING:1", "BED:1"] else 18,
                ),
            }
            for rid in ["LIVING:1", "KITCHEN:1", "BED:1", "BED:2"]
        ],
        "fixed_room_ids": [],
        "refinements": [
            {
                "id": "MOVE-ENTRANCE",
                "type": "opening_offset",
                "opening_id": "ENTRANCE",
                "fixed": False,
                "interval": [0.8, 2],
                "offsets": [0.8, 2],
                "passage_alternatives": [{"offset": 0.8, "passages": updated}],
            }
        ],
        "search": {
            "max_steps": 100000,
            "max_evaluations": 16,
            "max_refinement_states": 4,
            "candidate_count": 1,
        },
    }
    for wall in ws["special_walls"]:
        wall.pop("rationale", None)
    result["id"] = "B4-TOWNHOUSE-4X20-v3"
    return result


def townhouse():
    """v4: separately documented feasible portal/clearance specification revision."""
    value = _townhouse_v3()
    value["id"] = "B4-TOWNHOUSE-4X20-v4"
    geometry = value["generation"]["geometry"]
    geometry["tolerances"].update(boundary_m=1e-12, overlap_m2=1e-10)
    approve_source(value["generation"])
    op = value["opening_specification"]
    for row in op["openings"]:
        if row["id"].startswith("STAIR-"):
            row.update(
                type="sliding_door",
                rough_width=0.96,
                clear_width=0.8,
                frame_inner_width=0.88,
                offset=0.22 if row["floor_id"] == "F1" else 1.22,
                leaf={"width": 0.84, "thickness": 0.03, "hinge_offset": 0.06},
                mount_offset=0.02,
                slide={
                    "direction": "end",
                    "travel": 0.9,
                    "mode": "surface",
                    "opens_into": "COR-" + row["floor_id"],
                },
            )
            row.pop("swing")
        if row["type"].endswith("window"):
            continue
        clearance = next(c for c in op["clearance_regions"] if c["id"] == row["clearance_id"])
        start = row["offset"] + row["clear_start_offset"] - 0.001
        end = row["offset"] + row["clear_start_offset"] + row["clear_width"] + 0.001
        if row["id"].startswith("STAIR-"):
            g = shape(0.90, 8 + start, 1.10, 8 + end)
        else:
            y = 2 if row["kind"] == "entrance" else 8 if row["id"].startswith("FRONT-") else 12
            lo, hi = (1.95, 2.25) if y == 2 else (7.85, 8.05) if y == 8 else (11.95, 12.15)
            g = shape(start, lo, end, hi)
        clearance["exterior"] = g["polygons"][0]["exterior"]
    alternative = value["refinements"][0]["passage_alternatives"][0]
    clearance = deepcopy(next(c for c in op["clearance_regions"] if c["id"] == "CLEAR-ENTRANCE"))
    clearance["exterior"] = [[x - 1.2, y] for x, y in clearance["exterior"]]
    alternative["clearance_regions"] = [clearance]
    return value


def area_oracle():
    from wall_fixtures import request

    wall = request()
    ready = wall["source"]
    generation = deepcopy(ready["replay"]["provenance"]["generation_specification"])
    review = ready["replay"]["review"]
    value = {
        "schema_version": 1,
        "id": "ORACLE-A",
        "provenance": NOTICE,
        "generation": generation,
        "requirements_digest": canonical_digest(generation["geometry"]["zoning"]["brief"]),
        "review_template": {
            k: deepcopy(v)
            for k, v in review.items()
            if k not in {"candidate", "selection", "decisions", "schema_version"}
        },
        "wall_specification": deepcopy(wall["wall_specification"]),
        "wall_heights": [
            {
                "floor_id": "F1",
                "base": 0,
                "height": 3,
                "confirmation": "confirmed",
                "provenance": NOTICE,
            }
        ],
        "opening_specification": {
            "id": "ORACLE-OPENINGS",
            "units": "m",
            "frame_id": "LOCAL",
            "vertical_datum": "above_finished_floor",
            "plan_cut_height": 1.2,
            "openings": [],
            "openings_complete": True,
            "fixed_obstacles_complete": True,
            "stairs_complete": True,
            "passages": [],
            "clearance_regions": [],
            "room_area_policy": "exclude_thresholds",
        },
        "opening_hosts": [],
        "refinements": [],
        "clear_requirements": [
            {
                "room_id": "BED:1",
                "requirement_id": "REQ-BED",
                "area_m2": {"min": 18, "max": 20},
                "width_m": {"min": 3, "max": 4},
                "depth_m": {"min": 4, "max": 5},
            }
        ],
        "search": {
            "max_steps": 20000,
            "max_evaluations": 1,
            "max_refinement_states": 0,
            "candidate_count": 1,
        },
    }
    value["wall_specification"]["constraint_basis"] = {
        "area": "allocation",
        "dimensions": "allocation",
    }
    return value


def partition_oracle():

    value = area_oracle()
    generation = synthetic_spec(4, 10, groups=2)
    from design_fixtures import add_requirement

    add_requirement(generation["geometry"]["zoning"]["brief"], "SYN-WALL-DIMENSIONS")
    brief = generation["geometry"]["zoning"]["brief"]
    for room in brief["building"]["rooms"]:
        room["area"] = {"min": 16, "max": 24, "target": 20, "unit": "m2"}
    for d in generation["room_dimensions"]:
        d["width"] = {"min": 4, "max": 4}
        d["depth"] = {"min": 4, "max": 6}
    generation["parameters"].update(grid_step=1, candidate_count=1, solution_limit=1)
    approve_source(generation)
    value.update(
        id="ORACLE-B",
        generation=generation,
        requirements_digest=canonical_digest(brief),
        clear_requirements=[
            {
                "room_id": rid,
                "requirement_id": req,
                "area_m2": {"min": minimum, "max": 24},
                "width_m": {"min": 3.5, "max": 4},
                "depth_m": {"min": 4, "max": 6},
            }
            for rid, req, minimum in [("BED:1", "REQ-BED", 18), ("LIVING:1", "REQ-LIVING", 14.4)]
        ],
        refinements=[
            {
                "id": "SHIFT-SHARED",
                "type": "partition",
                "room_ids": ["BED:1", "LIVING:1"],
                "axis": "y",
                "interval": [4.5, 5.5],
                "positions": [4.5, 5.5],
                "fixed": False,
            }
        ],
        search={
            "max_steps": 50000,
            "max_evaluations": 3,
            "max_refinement_states": 2,
            "candidate_count": 1,
        },
    )
    value["review_template"]["exteriors"] = []
    value["review_template"]["fixed_obstacles"] = []
    value["review_template"]["clearance_regions"] = []
    value["review_template"]["passages"] = []
    for t in value["wall_specification"]["treatments"]:
        if t["selector"]["kind"] == "exterior":
            t["wall"]["fixed"] = True
    value["placement_regions"] = [
        {"room_id": "BED:1", "geometry": shape(0, 0, 4, 5.5)},
        {"room_id": "LIVING:1", "geometry": shape(0, 4.5, 4, 10)},
    ]
    return value


def residential():
    """Additional six-room residential project; v4 oracle remains immutable."""
    from design_fixtures import add_requirement

    value = townhouse()
    value["id"] = "B4-RESIDENTIAL-6ROOMS-4X20"
    generation = value["generation"]
    g = generation["geometry"]
    brief = g["zoning"]["brief"]
    brief["project"]["name"] = "Synthetic two-storey six-room residential concept; no real approval"
    brief["building"]["footprint"]["value"] = {"target": 72, "unit": "m2"}
    for rid, fid in [("BATH-G", "F1"), ("BATH-U", "F2")]:
        add_requirement(brief, "REQ-" + rid)
        brief["building"]["rooms"].append(
            {
                "id": rid,
                "type": "bathroom",
                "quantity": 1,
                "floor_id": fid,
                "requirement_id": "REQ-" + rid,
                "area": {"min": 4, "max": 4, "target": 4, "unit": "m2"},
                "notes": NOTICE,
            }
        )
    zoning = create_zoning_proposal(brief, "B4-SIX-ROOM-SYNTHETIC-ZONING")
    for a in zoning["assignments"]:
        a["zone"] = "explicit synthetic functional region"
    g["zoning"] = zoning
    for poly in g["polygons"]:
        if poly["role"] == "footprint":
            poly["exterior"] = [[0, 1], [4, 1], [4, 19], [0, 19]]
        if poly.get("reservation_kind") == "circulation":
            poly["exterior"] = [[0, 7], [1.05, 7], [1.05, 11], [2, 11], [2, 13], [0, 13]]
        if poly.get("reservation_kind") == "stairwell":
            poly["exterior"] = [[1.05, 7], [3.8, 7], [3.8, 10.3], [1.05, 10.3]]
        if poly.get("reservation_kind") == "service_shaft":
            poly["exterior"] = [[3.4, 10.3], [3.8, 10.3], [3.8, 11], [3.4, 11]]
    for a in zoning["assignments"]:
        if a["room_id"].startswith("BATH"):
            generation["room_dimensions"].append(
                {
                    "room_id": a["room_id"],
                    "requirement_id": a["requirement_id"],
                    "width": {"min": 2, "max": 2},
                    "depth": {"min": 2, "max": 2},
                }
            )
            value["clear_requirements"].append(
                {
                    "room_id": a["room_id"],
                    "requirement_id": a["requirement_id"],
                    "area_m2": {"min": 3, "max": 4},
                    "width_m": {"min": 1.6, "max": 2},
                    "depth_m": {"min": 1.8, "max": 2},
                }
            )
    generation["parameters"]["grid_step"] = 1
    approve_source(generation)
    value["requirements_digest"] = canonical_digest(brief)
    value["placement_regions"] = [
        {
            "room_id": rid,
            "geometry": shape(
                0,
                1 if rid in ["LIVING:1", "BED:1"] else 13,
                4,
                7 if rid in ["LIVING:1", "BED:1"] else 19,
            ),
        }
        for rid in ["LIVING:1", "KITCHEN:1", "BED:1", "BED:2"]
    ] + [{"room_id": rid, "geometry": shape(2, 11, 4, 13)} for rid in ["BATH-G:1", "BATH-U:1"]]
    ws = value["wall_specification"]
    for wall in ws["special_walls"]:
        wall["reference"] = {"start": [1.05, 7], "end": [1.05, 11]}
    for contact in ws["reservation_wall_contacts"]:
        contact["geometry"] = {
            "type": "PolygonSet",
            "units": "m",
            "polygons": shape(0, 7, 0.2, 13)["polygons"] + shape(0.95, 7, 1.05, 11)["polygons"],
        }
    for fid, room in [("F1", "KITCHEN:1"), ("F2", "BED:2")]:
        profile = deepcopy(next(t["wall"] for t in ws["treatments"] if t["id"] == "ROOM-RESERVED"))
        profile["reference_room_id"] = room
        ws["treatments"].append(
            {
                "id": "BATH-SHARED-" + fid,
                "selector": {"kind": "shared", "room_ids": [room]},
                "action": "wall",
                "wall": profile,
                "rationale": NOTICE,
            }
        )
    op = value["opening_specification"]
    for region in [*value["review_template"]["clearance_regions"], *op["clearance_regions"]]:
        if region["id"] == "APPROACH":
            region["exterior"] = [[0, 0], [4, 0], [4, 1], [0, 1]]
    value["review_template"]["fixed_obstacles"][0]["exterior"] = [
        [2.2, 1.3],
        [2.85, 1.3],
        [2.85, 2.1],
        [2.2, 2.1],
    ]
    for host in value["opening_hosts"]:
        key = host["opening_id"]
        if key == "ENTRANCE":
            host["references"] = [{"start": [0, 1], "end": [4, 1]}]
        elif key.startswith("FRONT-"):
            host["references"] = [{"start": [0, 7], "end": [1.05, 7]}]
        elif key.startswith("REAR-"):
            host["references"] = [{"start": [0, 13], "end": [2, 13]}]
        elif key.startswith("STAIR-"):
            host["references"] = [{"start": [1.05, 7], "end": [1.05, 10.3]}]
        elif key.startswith("WINDOW-"):
            host["references"] = [{"start": [0, 19], "end": [4, 19]}]
    for row in op["openings"]:
        if row["id"].startswith("STAIR-"):
            row["offset"] += 1
    for path in op["passages"]:
        for point in path["path"]:
            if point[1] == 8:
                point[1] = 7
            elif point[1] == 12:
                point[1] = 13
            elif point[1] == 13:
                point[1] = 14
            elif point[1] == 6.8:
                point[1] = 5.8
            elif point[1] == 2:
                point[1] = 1
            elif path["id"] == "ENTRANCE-EXTERIOR" and point[1] == 1:
                point[1] = 0.5
    for fid, rid in [("F1", "BATH-G:1"), ("F2", "BATH-U:1")]:
        row = deepcopy(next(r for r in op["openings"] if r["id"] == "REAR-" + fid))
        row.update(
            id="BATH-DOOR-" + fid,
            mark="BATH-DOOR-" + fid,
            offset=0.64,
            space_ids=[rid, "COR-" + fid],
            mount_side="right",
            swing={"hinge": "start", "rotation": "cw", "angle_degrees": 90, "opens_into": rid},
            clearance_id="CLEAR-BATH-" + fid,
        )
        op["openings"].append(row)
        value["opening_hosts"].append(
            {
                "opening_id": row["id"],
                "floor_id": fid,
                "references": [{"start": [2, 11], "end": [2, 13]}],
            }
        )
        template = deepcopy(op["clearance_regions"][1])
        template.update(id=row["clearance_id"], floor_id=fid, owner_id=fid)
        op["clearance_regions"].append(template)
        base = {
            "floor_id": fid,
            "frame_id": "LOCAL",
            "units": "m",
            "width": 0.5,
            "provenance": NOTICE,
            "confirmation": "confirmed",
        }
        op["passages"].append(
            {
                **base,
                "id": "BATH-IN-" + fid,
                "space_id": rid,
                "path": [[2, 12], [3, 12]],
                "opening_ids": [row["id"]],
            }
        )
        op["passages"].append(
            {
                **base,
                "id": "COR-BATH-" + fid,
                "space_id": "COR-" + fid,
                "path": [
                    [1.05, 8.7 if fid == "F1" else 9.7],
                    [0.575, 8.7 if fid == "F1" else 9.7],
                    [0.575, 12],
                    [2, 12],
                ],
                "opening_ids": ["STAIR-" + fid, row["id"]],
            }
        )
    # Explicit local portal strips for this separate project's wall references.
    for row in op["openings"]:
        if row["type"].endswith("window"):
            continue
        ref = next(
            h["references"][0] for h in value["opening_hosts"] if h["opening_id"] == row["id"]
        )
        start = row["offset"] + row["clear_start_offset"] - 0.001
        end = row["offset"] + row["clear_start_offset"] + row["clear_width"] + 0.001
        if ref["start"][0] == ref["end"][0]:
            x = ref["start"][0]
            y = ref["start"][1]
            lo, hi = (0.90, 1.10) if x == 1.05 else (1.95, 2.15)
            points = shape(lo, y + start, hi, y + end)["polygons"][0]["exterior"]
        else:
            y = ref["start"][1]
            lo, hi = (0.95, 1.25) if y == 1 else (6.85, 7.05) if y == 7 else (12.95, 13.15)
            points = shape(start, lo, end, hi)["polygons"][0]["exterior"]
        next(c for c in op["clearance_regions"] if c["id"] == row["clearance_id"])["exterior"] = (
            points
        )
    stairs = value["stair_specification"]
    stairs["stairs"][0]["envelope"] = shape(1.05, 7, 3.8, 10.3)
    stairs["floor_openings"][0]["geometry"] = shape(1.05, 7, 3.8, 10.3)
    stairs["slabs"][0]["geometry"] = shape(0, 1, 4, 19)
    stairs["obstacles"][0]["geometry"] = shape(0, 1, 4, 19)
    alternative = value["refinements"][0]["passage_alternatives"][0]
    alternative["passages"] = [
        deepcopy(p) for p in op["passages"] if p["id"].startswith("ENTRANCE-")
    ]
    for path in alternative["passages"]:
        for point in path["path"]:
            if point[0] == 2.36:
                point[0] = 1.16
    alternative["clearance_regions"] = [
        deepcopy(next(c for c in op["clearance_regions"] if c["id"] == "CLEAR-ENTRANCE"))
    ]
    alternative["clearance_regions"][0]["exterior"] = [
        [x - 1.2, y] for x, y in alternative["clearance_regions"][0]["exterior"]
    ]
    return value


CASES = (
    "townhouse-4x20-v4",
    "residential-4x20-six-rooms",
    "oracle-area",
    "oracle-partition",
    "historical-4x20-loaded",
    "historical-8x15-separation",
)


def projection(report):
    import hashlib
    from vnai.integrated_preview import integrated_svg

    svg = {}
    if report["originals"]:
        svg["comparison"] = hashlib.sha256(integrated_svg(report).encode()).hexdigest()
    if report["candidates"]:
        for fid in report["candidates"][0]["candidate"]["floor_ids"]:
            svg["after-" + fid] = hashlib.sha256(
                integrated_svg(report, view="after", floor=fid).encode()
            ).hexdigest()
    chosen = report["candidates"] or report["originals"]
    if chosen and chosen[0]["engines"]["stairs"].get("stairs"):
        svg["section"] = hashlib.sha256(integrated_svg(report, view="section").encode()).hexdigest()
    return {
        "integrated_status": report["integrated_status"],
        "full_report_sha256": canonical_digest(report),
        "search": report["search"],
        "svg_sha256": svg,
        "proposals": [
            {
                "revision_id": s["revision_id"],
                "candidate_digest": s["candidate_digest"],
                "coverage": s["verification_coverage"],
                "room_areas_m2": {
                    r["room_id"]: r["clear_area_m2"] for r in s["engines"]["walls"]["rooms"]
                },
            }
            for s in report["candidates"]
        ],
        "original_findings": [
            [(c["severity"], c["code"], c["entity_ids"]) for c in s["conflicts"]]
            for s in report["originals"]
        ],
    }
