"""Synthetic review fixtures built from real Batch 006-A generator candidates."""

from copy import deepcopy
import json
from pathlib import Path

from floorplan_fixtures import reservation_spec, synthetic_spec, approve_source, authorize
from vnai.floorplan import generate_floorplans
from vnai.candidate_review import candidate_digest, design_digest

ROOT = Path(__file__).resolve().parents[1]


def selection(spec):
    spec["selection"] = {
        "candidate_id": spec["candidate"]["candidate_id"],
        "candidate_digest": candidate_digest(spec["candidate"]),
    }
    return spec


def review_events(spec, states=("SELECTED",)):
    spec["decisions"] = []
    for index, state in enumerate(states):
        spec["decisions"].append(
            {
                "id": f"EVENT-{index + 1}",
                "state": state,
                "record": {
                    "actor": "SYNTHETIC_TEST_REVIEWER_NOT_A_REAL_ARCHITECT",
                    "role": "user" if state == "SELECTED" else "architect",
                    "recorded_at": f"2026-11-18T00:0{index}:00Z",
                    "digest": design_digest(spec),
                    "provenance": "Synthetic fixture record; not real approval",
                },
            }
        )
    return spec


def polygon(spec, key, coords, floor="F1", kind="circulation"):
    geometry = spec["candidate"]["geometry"]
    return {
        "id": key,
        "role": "reservation",
        "owner_id": floor,
        "floor_id": floor,
        "frame_id": geometry["frame"]["id"],
        "units": geometry["units"],
        "exterior": coords,
        "holes": [],
        "status": "proposed",
        "reservation_kind": kind,
        "provenance": "Synthetic supplied geometry",
        "requirement_id": "REQ-internal_circulation",
    }


def base(candidate):
    return selection(
        {
            "schema_version": 1,
            "fixture_notice": "All candidate decisions, geometry and actors are synthetic test data.",
            "candidate": deepcopy(candidate),
            "decisions": [],
            "exteriors": [],
            "openings": [],
            "openings_complete": True,
            "stairs": [],
            "stairs_complete": True,
            "fixed_obstacles": [],
            "fixed_obstacles_complete": True,
            "clearance_regions": [],
            "passages": [],
        }
    )


def opening(
    spec, key, spaces, start, end, host, kind="interior", door_type="open_passage", floor="F1"
):
    geometry = spec["candidate"]["geometry"]
    return {
        "schema_version": 1,
        "id": key,
        "kind": kind,
        "door_type": door_type,
        "floor_id": floor,
        "frame_id": geometry["frame"]["id"],
        "units": geometry["units"],
        "space_ids": spaces,
        "start": start,
        "end": end,
        "host": {"start": host[0], "end": host[1]},
        "clear_width": ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5,
        "provenance": "Synthetic architect-supplied opening, not inferred from adjacency",
        "confirmation": "confirmed",
    }


def two_rooms():
    historical = json.loads((ROOT / "tests/golden/batch006a-v0.1.6/alternatives.json").read_text())
    # This is an immutable actual generated candidate, not a hand-built parallel room model.
    candidate = next(
        c
        for c in historical["candidates"]
        if next(p for p in c["geometry"]["polygons"] if p.get("room_id") == "BED:1")["exterior"]
        == [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0]]
    )
    spec = base(candidate)
    spec["clearance_regions"].append(polygon(spec, "APPROACH", [[0, 4], [4, 4], [4, 6], [0, 6]]))
    spec["exteriors"] = [
        {
            "id": "EXT",
            "floor_id": "F1",
            "boundary_id": "FOOTPRINT",
            "approach_id": "APPROACH",
            "provenance": "Synthetic external access region",
        }
    ]
    entrance = opening(
        spec,
        "ENTRANCE",
        ["EXT", "LIVING:1"],
        [1, 4],
        [2, 4],
        [[0, 4], [4, 4]],
        "entrance",
        "hinged",
    )
    entrance["swing"] = {
        "hinge": "start",
        "rotation": "cw",
        "angle_degrees": 90,
        "opens_into": "LIVING:1",
    }
    internal = opening(
        spec, "DOOR", ["BED:1", "LIVING:1"], [1, 2], [2, 2], [[0, 2], [4, 2]], door_type="hinged"
    )
    internal["swing"] = {
        "hinge": "start",
        "rotation": "ccw",
        "angle_degrees": 90,
        "opens_into": "LIVING:1",
    }
    spec["openings"] = [entrance, internal]
    return review_events(spec)


def corridor(verified=False):
    generation = reservation_spec()
    reserve = generation["geometry"]["polygons"][-1]
    reserve.update(
        id="CORRIDOR", reservation_kind="circulation", requirement_id="REQ-internal_circulation"
    )
    for dims in generation["room_dimensions"]:
        dims["width"] = {"min": 4, "max": 4}
        dims["depth"] = {"min": 2, "max": 2}
    generated = generate_floorplans(authorize(generation))
    assert generated["status"] == "GENERATED", generated
    candidate = next(
        c
        for c in generated["candidates"]
        if next(p for p in c["geometry"]["polygons"] if p.get("room_id") == "BED:1")["exterior"]
        == [[1.0, 0.0], [5.0, 0.0], [5.0, 2.0], [1.0, 2.0]]
    )
    spec = base(candidate)
    spec["clearance_regions"].append(polygon(spec, "APPROACH", [[0, 4], [1, 4], [1, 6], [0, 6]]))
    spec["exteriors"] = [
        {
            "id": "EXT",
            "floor_id": "F1",
            "boundary_id": "FOOTPRINT",
            "approach_id": "APPROACH",
            "provenance": "Synthetic external access",
        }
    ]
    spec["openings"] = [
        opening(
            spec, "ENTRANCE", ["EXT", "CORRIDOR"], [0.1, 4], [0.9, 4], [[0, 4], [1, 4]], "entrance"
        ),
        opening(spec, "DOOR-BED", ["CORRIDOR", "BED:1"], [1, 0.5], [1, 1.5], [[1, 0], [1, 2]]),
        opening(
            spec, "DOOR-LIVING", ["CORRIDOR", "LIVING:1"], [1, 2.5], [1, 3.5], [[1, 2], [1, 4]]
        ),
    ]
    if verified:
        regions = [
            ("C-ENTRY", [[0.1, 3.6], [0.9, 3.6], [0.9, 4.4], [0.1, 4.4]]),
            ("C-BED", [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5]]),
            ("C-LIVING", [[0.5, 2.5], [1.5, 2.5], [1.5, 3.5], [0.5, 3.5]]),
        ]
        for row, (key, coords) in zip(spec["openings"], regions):
            spec["clearance_regions"].append(polygon(spec, key, coords))
            row["clearance_id"] = key
        routes = [
            ("P-OUT", "EXT", [[0.5, 4], [0.5, 5]], ["ENTRANCE"]),
            ("P-C1", "CORRIDOR", [[0.5, 4], [0.5, 3], [1, 3]], ["ENTRANCE", "DOOR-LIVING"]),
            ("P-C2", "CORRIDOR", [[1, 1], [0.5, 1], [0.5, 3], [1, 3]], ["DOOR-BED", "DOOR-LIVING"]),
            ("P-BED", "BED:1", [[1, 1], [2, 1]], ["DOOR-BED"]),
            ("P-LIVING", "LIVING:1", [[1, 3], [2, 3]], ["DOOR-LIVING"]),
        ]
        for key, space, path, doors in routes:
            spec["passages"].append(
                {
                    "id": key,
                    "space_id": space,
                    "floor_id": "F1",
                    "frame_id": "LOCAL",
                    "units": "m",
                    "path": path,
                    "width": 0.4,
                    "opening_ids": doors,
                    "provenance": "Explicit synthetic route/width, not a standard",
                    "confirmation": "confirmed",
                }
            )
    return review_events(spec)


def multi_floor():
    generation = synthetic_spec()
    z = generation["geometry"]["zoning"]
    z["brief"]["building"]["storeys"]["value"] = 2
    z["brief"]["building"]["floors"].append({"id": "F2", "label": "Synthetic second floor"})
    z["floors"].append({"id": "F2"})
    z["brief"]["building"]["rooms"][1]["floor_id"] = "F2"
    z["assignments"][1]["floor_id"] = "F2"
    generation["geometry"]["floors"] = [
        {"id": "F1", "elevation_m": 0},
        {"id": "F2", "elevation_m": 3},
    ]
    for floor in ("F1", "F2"):
        generation["geometry"]["polygons"].append(
            {
                "id": "SW-" + floor,
                "role": "reservation",
                "owner_id": floor,
                "floor_id": floor,
                "frame_id": "LOCAL",
                "units": "m",
                "exterior": [[0, 0], [1, 0], [1, 4], [0, 4]],
                "holes": [],
                "status": "proposed",
                "reservation_kind": "stairwell",
                "provenance": "Synthetic aligned stairwell box",
                "requirement_id": "Q-STAIR",
            }
        )
    generated = generate_floorplans(approve_source(generation))
    assert generated["status"] == "GENERATED", generated
    # Choose the placement immediately adjacent to both explicitly supplied stairwell boundaries.
    candidate = next(
        c
        for c in generated["candidates"]
        if all(
            next(p for p in c["geometry"]["polygons"] if p.get("room_id") == room)["exterior"][0][0]
            == 1
            for room in ("BED:1", "LIVING:1")
        )
    )
    spec = base(candidate)
    spec["clearance_regions"].append(polygon(spec, "APPROACH", [[1, 4], [3, 4], [3, 6], [1, 6]]))
    spec["exteriors"] = [
        {
            "id": "EXT",
            "floor_id": "F1",
            "boundary_id": "FOOTPRINT",
            "approach_id": "APPROACH",
            "provenance": "Synthetic entrance",
        }
    ]
    spec["openings"] = [
        opening(
            spec, "ENTRANCE", ["EXT", "BED:1"], [1.5, 4], [2.5, 4], [[1, 4], [3, 4]], "entrance"
        ),
        opening(spec, "STAIR-ENTRY", ["BED:1", "SW-F1"], [1, 1.5], [1, 2.5], [[1, 0], [1, 4]]),
        opening(
            spec,
            "STAIR-EXIT",
            ["LIVING:1", "SW-F2"],
            [1, 1.5],
            [1, 2.5],
            [[1, 0], [1, 4]],
            floor="F2",
        ),
    ]
    spec["stairs"] = [
        {
            "schema_version": 1,
            "id": "STAIR-1",
            "source": {
                "floor_id": "F1",
                "stairwell_id": "SW-F1",
                "space_id": "BED:1",
                "point": [1, 2],
                "opening_id": "STAIR-ENTRY",
            },
            "destination": {
                "floor_id": "F2",
                "stairwell_id": "SW-F2",
                "space_id": "LIVING:1",
                "point": [1, 2],
                "opening_id": "STAIR-EXIT",
            },
            "direction": "up",
            "frame_id": "LOCAL",
            "units": "m",
            "alignment_required": True,
            "confirmation": "confirmed",
            "review_status": "reviewed",
            "provenance": "Synthetic endpoint/envelope review, not full stair design",
        }
    ]
    return review_events(spec)


def landing_stairs():
    generation = synthetic_spec()
    z = generation["geometry"]["zoning"]
    z["brief"]["building"]["storeys"]["value"] = 2
    z["brief"]["building"]["floors"].append({"id": "F2", "label": "Synthetic second floor"})
    z["floors"].append({"id": "F2"})
    z["brief"]["building"]["rooms"][1]["floor_id"] = "F2"
    z["assignments"][1]["floor_id"] = "F2"
    generation["geometry"]["floors"] = [
        {"id": "F1", "elevation_m": 0},
        {"id": "F2", "elevation_m": 3},
    ]
    for floor in ("F1", "F2"):
        for key, kind, x0, x1 in [("SW-", "stairwell", 0, 1), ("LAND-", "circulation", 1, 2)]:
            generation["geometry"]["polygons"].append(
                {
                    "id": key + floor,
                    "role": "reservation",
                    "owner_id": floor,
                    "floor_id": floor,
                    "frame_id": "LOCAL",
                    "units": "m",
                    "exterior": [[x0, 0], [x1, 0], [x1, 4], [x0, 4]],
                    "holes": [],
                    "status": "proposed",
                    "reservation_kind": kind,
                    "provenance": "Synthetic supplied landing/stair box",
                    "requirement_id": "REQ-internal_circulation",
                }
            )
    generated = generate_floorplans(approve_source(generation))
    assert generated["status"] == "GENERATED", generated
    spec = base(generated["candidates"][0])
    spec["clearance_regions"] = [polygon(spec, "APPROACH", [[1, 4], [2, 4], [2, 6], [1, 6]])]
    spec["exteriors"] = [
        {
            "id": "EXT",
            "floor_id": "F1",
            "boundary_id": "FOOTPRINT",
            "approach_id": "APPROACH",
            "provenance": "Synthetic exterior",
        }
    ]
    spec["openings"] = [
        opening(
            spec, "ENTRANCE", ["EXT", "LAND-F1"], [1.1, 4], [1.9, 4], [[1, 4], [2, 4]], "entrance"
        )
    ]
    for floor, room in [("F1", "BED:1"), ("F2", "LIVING:1")]:
        spec["openings"].append(
            opening(
                spec,
                "ST-" + floor,
                ["LAND-" + floor, "SW-" + floor],
                [1, 1.5],
                [1, 2.5],
                [[1, 0], [1, 4]],
                floor=floor,
            )
        )
        spec["openings"].append(
            opening(
                spec,
                "RM-" + floor,
                ["LAND-" + floor, room],
                [2, 1.5],
                [2, 2.5],
                [[2, 0], [2, 4]],
                floor=floor,
            )
        )
    spec["stairs"] = [
        {
            "schema_version": 1,
            "id": "STAIR",
            "source": {
                "floor_id": "F1",
                "stairwell_id": "SW-F1",
                "space_id": "LAND-F1",
                "landing_id": "LAND-F1",
                "point": [1, 2],
                "opening_id": "ST-F1",
            },
            "destination": {
                "floor_id": "F2",
                "stairwell_id": "SW-F2",
                "space_id": "LAND-F2",
                "landing_id": "LAND-F2",
                "point": [1, 2],
                "opening_id": "ST-F2",
            },
            "direction": "up",
            "frame_id": "LOCAL",
            "units": "m",
            "alignment_required": True,
            "confirmation": "confirmed",
            "review_status": "reviewed",
            "provenance": "Synthetic reviewed endpoints",
        }
    ]
    return review_events(spec)
