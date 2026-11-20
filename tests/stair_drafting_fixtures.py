"""Synthetic stair specifications reuse immutable B2 candidate/wall/opening inputs."""

from pathlib import Path
import json
from vnai.contracts import canonical_digest
from vnai.review_common import candidate_digest, design_digest
from vnai.walls import generate_walls
from vnai.opening_drafting import draft_openings

ROOT = Path(__file__).resolve().parents[1]
NOTICE = "Synthetic staircase dimensions and software oracles; no real architect/expert approval or normative prescription."


def geometry(x0, y0, x1, y1):
    return {
        "type": "PolygonSet",
        "units": "m",
        "polygons": [{"exterior": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "holes": []}],
    }


def base(kind="straight"):
    source = json.loads((ROOT / "examples/batch007b2/multiple-floors.json").read_text())
    review = source["source"]["source"]["replay"]["review"]
    g = review["candidate"]["geometry"]
    room2 = (
        [[9, 0], [13, 0], [13, 5], [9, 5]]
        if kind == "straight"
        else [[4, 8], [8, 8], [8, 13], [4, 13]]
        if kind == "L"
        else [[0, 0], [4, 0], [4, 5], [0, 5]]
    )
    for p in g["polygons"]:
        if p["role"] == "site":
            p["exterior"] = [[0, 0], [13, 0], [13, 20], [0, 20]]
        if p["role"] == "footprint":
            p["exterior"] = [[0, 0], [13, 0], [13, 13], [0, 13]]
        if p["role"] == "room" and p["floor_id"] == "F2":
            p["exterior"] = room2
    for f in g["floors"]:
        f["elevation_m"] = 0 if f["id"] == "F1" else 3.3
    template = next(p for p in g["polygons"] if p["role"] == "room")
    for floor in ["F1", "F2"]:
        p = {k: v for k, v in template.items() if k not in {"room_id", "requirement_ids"}}
        p.update(
            id="SW-" + floor,
            role="reservation",
            owner_id=floor,
            floor_id=floor,
            reservation_kind="stairwell",
            exterior=[[4, 0], [9, 0], [9, 8], [4, 8]],
            holes=[],
            provenance=NOTICE,
        )
        p["requirement_id"] = g["zoning"]["brief"]["requirements"][0]["id"]
        g["polygons"].append(p)
    # This is a separately authored synthetic site, not a revision of the 4x20 townhouse.
    from shapely.geometry import Polygon
    from vnai.zoning import decision_digest

    zoning = g["zoning"]
    site = Polygon(next(p["exterior"] for p in g["polygons"] if p["role"] == "site"))
    footprint = Polygon(next(p["exterior"] for p in g["polygons"] if p["role"] == "footprint"))
    zoning["brief"]["site"]["dimensions"]["value"].update(
        width=site.bounds[2] - site.bounds[0], length=site.bounds[3] - site.bounds[1]
    )
    zoning["brief"]["building"]["footprint"]["value"]["target"] = footprint.area
    zoning["proposal_id"] = "B3-SYNTHETIC-SOURCE-" + kind
    zoning["revision"] = 1
    for event in zoning["decisions"]:
        assignment = next(row for row in zoning["assignments"] if row["id"] == event["decision_id"])
        event["record"]["digest"] = decision_digest(zoning, assignment)
        event["record"]["actor"] = "SYNTHETIC_TEST_ARCHITECT_NOT_REAL_APPROVAL"
    review["fixture_notice"] = (
        NOTICE
        + " Separate declared 13x20 site and 13x13 footprint; synthetic source decision records are test data, not expert approval. Original generation replay remains unavailable."
    )
    review["candidate"]["candidate_id"] = "SYNTHETIC-B3-" + kind
    review["selection"]["candidate_id"] = review["candidate"]["candidate_id"]
    review["selection"]["candidate_digest"] = candidate_digest(review["candidate"])
    review["decisions"] = []
    review["stairs"] = []
    review["stairs_complete"] = False
    # A distinct synthetic source, with unchanged room dimensions and explicit no-wall intent.
    ws = source["source"]["wall_specification"]
    ws["default_treatment"] = "no_wall"
    ws["treatments"] = []
    ws["special_walls"] = []
    ws["source_candidate_digest"] = candidate_digest(review["candidate"])
    ws["source_design_digest"] = design_digest(review)
    model = generate_walls(source["source"])
    source["source_candidate_digest"] = model["source_candidate_digest"]
    source["source_wall_revision_id"] = model["wall_revision_id"]
    spec = source["specification"]
    spec.update(
        openings=[],
        wall_verticals=[],
        stairs=[],
        stairs_complete=False,
        openings_complete=False,
        fixed_obstacles_complete=True,
        passages=[],
        clearance_regions=[],
        additional_obstacles=[],
        exteriors=[],
    )
    src = draft_openings(source)
    first = {
        "id": "FL1",
        "origin": [4, 1],
        "direction": "E",
        "width": 1,
        "risers": 20 if kind == "straight" else 10,
        "tread_depth": 0.25,
    }
    flights = [first]
    landings = []
    arrival = None
    if kind == "straight":
        arrival = {"geometry": geometry(8.75, 1, 9, 2), "exit_point": [9, 1.5]}
    elif kind == "L":
        flights.append(
            {
                "id": "FL2",
                "origin": [7.25, 2],
                "direction": "N",
                "width": 1,
                "risers": 10,
                "tread_depth": 0.25,
            }
        )
        landings = [
            {
                "id": "LAND1",
                "geometry": geometry(6.25, 1, 7.25, 2),
                "elevation": 1.65,
                "walking_line": [[6.25, 1.5], [6.75, 1.5], [6.75, 2]],
            }
        ]
        arrival = {"geometry": geometry(6.25, 4.25, 7.25, 8), "exit_point": [6.75, 8]}
    else:
        flights.append(
            {
                "id": "FL2",
                "origin": [6.25, 3.2],
                "direction": "W",
                "width": 1,
                "risers": 10,
                "tread_depth": 0.25,
            }
        )
        landings = [
            {
                "id": "LAND1",
                "geometry": geometry(6.25, 1, 7.25, 3.2),
                "elevation": 1.65,
                "walking_line": [[6.25, 1.5], [6.75, 1.5], [6.75, 2.7], [6.25, 2.7]],
            }
        ]
    stair = {
        "id": "S1",
        "mark": "ST01",
        "type": kind,
        "source_floor": "F1",
        "destination_floor": "F2",
        "stairwell_ids": ["SW-F1", "SW-F2"],
        "envelope": geometry(4, 0, 9, 8),
        "counting": "arrival_surface",
        "flights": flights,
        "landings": landings,
        "requirement_ids": [],
        "confirmation": "confirmed",
        "review_status": "proposed",
        "provenance": NOTICE,
    }
    if arrival:
        stair["arrival"] = arrival
    if kind != "straight":
        stair["turn"] = "left"
    if kind == "U":
        stair["flight_separation"] = 0.2
    result = {
        "schema_version": 1,
        "source": source,
        "source_opening_revision_id": src["opening_revision_id"] or "unresolved",
        "source_opening_geometry_digest": src["opening_geometry_digest"] or "unresolved",
        "specification": {
            "id": "SYNTHETIC-B3-" + kind,
            "units": "m",
            "frame_id": g["frame"]["id"],
            "datum": "synthetic_finished_ground_floor_z0",
            "levels": [
                {
                    "floor_id": f,
                    "finished_elevation": z,
                    "confirmation": "confirmed",
                    "provenance": NOTICE,
                }
                for f, z in [("F1", 0), ("F2", 3.3)]
            ],
            "stairs": [stair],
            "plan_cut_elevations": [
                {"floor_id": "F1", "elevation": 1.2},
                {"floor_id": "F2", "elevation": 4.5},
            ],
            "number_steps": True,
            "floor_openings": [
                {
                    "id": "VOID-F2",
                    "floor_id": "F2",
                    "geometry": geometry(4, 0, 9, 8),
                    "stair_ids": ["S1"],
                }
            ],
            "slabs": [
                {
                    "id": "SLAB-F2",
                    "floor_id": "F2",
                    "geometry": geometry(0, 0, 13, 13),
                    "underside": 3.1,
                    "top": 3.3,
                    "opening_ids": ["VOID-F2"],
                }
            ],
            "obstacles": [
                {
                    "id": "CEILING",
                    "kind": "ceiling",
                    "geometry": geometry(0, 0, 13, 13),
                    "bottom": 6,
                    "top": 6.2,
                    "provenance": NOTICE,
                }
            ],
            "open_to_sky": [],
            "overhead_inventory_complete": True,
            "headroom_requirement": 2.1,
            "clear_width_requirement": 1,
            "connections": [],
            "stairs_complete": True,
        },
    }
    return result


def projection(report):
    from vnai.stair_preview import stair_svg
    import hashlib

    return {
        "drafting_status": report["drafting_status"],
        "geometry_status": report["geometry_status"],
        "full_report_sha256": canonical_digest(report),
        "stair_revision_id": report["stair_revision_id"],
        "stairs": report["stairs"],
        "schedule": report["schedule"],
        "headroom": report["headroom"],
        "floor_openings": report["floor_openings"],
        "codes": {
            k: sorted({r["code"] for r in report[k]})
            for k in ["errors", "warnings", "missing_information"]
        },
        "plan_svg_sha256": hashlib.sha256(stair_svg(report, "plan").encode()).hexdigest(),
        "section_svg_sha256": hashlib.sha256(stair_svg(report, "section").encode()).hexdigest(),
    }


def rebind(value):
    source = value["source"]
    review = source["source"]["source"]["replay"]["review"]
    review["selection"]["candidate_id"] = review["candidate"]["candidate_id"]
    review["selection"]["candidate_digest"] = candidate_digest(review["candidate"])
    ws = source["source"]["wall_specification"]
    ws["source_candidate_digest"] = candidate_digest(review["candidate"])
    ws["source_design_digest"] = design_digest(review)
    model = generate_walls(source["source"])
    source["source_candidate_digest"] = model["source_candidate_digest"]
    source["source_wall_revision_id"] = model["wall_revision_id"]
    for o in source["specification"]["openings"]:
        wall = next((w for w in model["walls"] if w["id"] == o["host_wall_id"]), None)
        if wall:
            o["source_wall_digest"] = wall["geometry_digest"]
    result = draft_openings(source)
    value["source_opening_revision_id"] = result["opening_revision_id"] or "unresolved"
    value["source_opening_geometry_digest"] = result["opening_geometry_digest"] or "unresolved"
    return value


def interfaces(value):
    from vnai.stair_geometry import construct, exact
    from fractions import Fraction
    from shapely.geometry import LineString, Point
    from opening_drafting_fixtures import door, region

    spec = value["specification"]
    stair = spec["stairs"][0]
    built = construct(
        stair, {"F1": exact(0), "F2": exact(3.3)}, Fraction(1), 0, 0, lambda *args: None
    )
    source = value["source"]
    ws = source["source"]["wall_specification"]
    model = generate_walls(source["source"])
    endpoints = []
    for floor, p in [("F1", built["entry_point"]), ("F2", built["exit_point"])]:
        boundary = next(
            b
            for b in model["boundary_topology"]
            if b["floor_id"] == floor
            and b["kind"] == "room_reserved"
            and LineString([b["reference"]["start"], b["reference"]["end"]]).distance(Point(p))
            < 1e-12
        )
        endpoints.append((floor, p, boundary))
        ws["treatments"].append(
            {
                "id": "PORTAL-" + floor,
                "selector": {"kind": "all", "boundary_ids": [boundary["id"]]},
                "action": "wall",
                "wall": {
                    "classification": "interior_partition",
                    "thickness": {"value": 0.1, "unit": "m"},
                    "alignment": "toward_room",
                    "fixed": False,
                    "requirement_ids": [],
                    "provenance": NOTICE,
                    "confirmation": "confirmed",
                    "approval_status": "proposed",
                },
                "rationale": "Explicit synthetic room-side wall; stair reservation unchanged.",
            }
        )
    model = generate_walls(source["source"])
    rows = []
    clear = []
    connection = {
        "schema_version": 1,
        "id": stair["id"],
        "direction": "up",
        "frame_id": spec["frame_id"],
        "units": "m",
        "alignment_required": True,
        "confirmation": "confirmed",
        "review_status": "proposed",
        "provenance": NOTICE,
    }
    for index, (floor, p, boundary) in enumerate(endpoints):
        wall = next(w for w in model["walls"] if w["boundary_id"] == boundary["id"])
        room = boundary["room_ids"][0]
        sw = "SW-" + floor
        side = boundary["room_sides"][room]
        start = wall["reference"]["start"]
        axis = 0 if wall["reference"]["end"][0] != start[0] else 1
        oid = "PORTAL-" + floor
        cid = "CLEAR-" + floor
        row = door(wall, room)
        row.update(
            id=oid,
            mark="D-" + floor,
            kind="interior",
            space_ids=[room, sw],
            offset=p[axis] - start[axis] - 0.6,
            rough_width=1.2,
            rough_height=2.2,
            clear_width=1.04,
            clear_height=2.1,
            clear_start_offset=0.08,
            frame_inner_width=1.12,
            frame={"jamb_width": 0.04, "depth": 0.1, "alignment": "centered_in_wall"},
            leaf={"width": 1.08, "thickness": 0.03, "hinge_offset": 0.06},
            mount_side=side,
            swing={
                "hinge": "start",
                "rotation": "ccw" if side == "left" else "cw",
                "angle_degrees": 90,
                "opens_into": room,
            },
            clearance_id=cid,
        )
        rows.append(row)
        points = (
            [
                [p[0] - 0.52, p[1] - 0.4],
                [p[0] + 0.52, p[1] - 0.4],
                [p[0] + 0.52, p[1] + 0.4],
                [p[0] - 0.52, p[1] + 0.4],
            ]
            if axis == 0
            else [
                [p[0] - 0.4, p[1] - 0.52],
                [p[0] + 0.4, p[1] - 0.52],
                [p[0] + 0.4, p[1] + 0.52],
                [p[0] - 0.4, p[1] + 0.52],
            ]
        )
        clear.append(region(source["source"], cid, points, floor))
        connection["source" if index == 0 else "destination"] = {
            "floor_id": floor,
            "stairwell_id": sw,
            "space_id": room,
            "point": p,
            "opening_id": oid,
        }
    source["specification"]["openings"] = rows
    source["specification"]["clearance_regions"] = clear
    source["specification"]["wall_verticals"] = [
        {
            "wall_id": w["id"],
            "base": 0,
            "height": 3.3,
            "confirmation": "confirmed",
            "provenance": NOTICE,
        }
        for w in model["walls"]
    ]
    spec["connections"] = [connection]
    return rebind(value)
