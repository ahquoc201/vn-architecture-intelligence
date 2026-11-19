"""Explicit synthetic opening assemblies; no normative dimensions or real review."""

import json
from copy import deepcopy
from pathlib import Path
from vnai.walls import generate_walls
from vnai.review_common import design_digest

ROOT = Path(__file__).resolve().parents[1]
NOTICE = (
    "Explicit synthetic drafting dimensions, not Vietnamese standards or expert-reviewed oracles."
)


def region(source, key, points, floor="F1"):
    g = source["source"]["replay"]["review"]["candidate"]["geometry"]
    req = g["zoning"]["brief"]["requirements"][0]["id"]
    return {
        "id": key,
        "role": "reservation",
        "status": "proposed",
        "owner_id": floor,
        "floor_id": floor,
        "frame_id": g["frame"]["id"],
        "units": g["units"],
        "exterior": points,
        "holes": [],
        "reservation_kind": "other",
        "provenance": NOTICE,
        "requirement_id": req,
    }


def bind(source):
    from vnai.review_common import candidate_digest

    review = source["source"]["replay"]["review"]
    source["wall_specification"]["source_candidate_digest"] = candidate_digest(review["candidate"])
    source["wall_specification"]["source_design_digest"] = design_digest(review)
    return source


def door(wall, room="BED:1", exterior="OUT", **extra):
    return {
        "id": "DOOR-1",
        "mark": "D01",
        "type": "hinged_door",
        "kind": "entrance" if exterior else "interior",
        "floor_id": wall["floor_id"],
        "host_wall_id": wall["id"],
        "source_wall_digest": wall["geometry_digest"],
        "offset": 1.5,
        "rough_width": 0.9,
        "rough_height": 2.1,
        "bottom": 0,
        "clear_width": 0.74,
        "clear_height": 2.0,
        "clear_start_offset": 0.1,
        "frame_inner_width": 0.82,
        "frame": {"jamb_width": 0.04, "depth": 0.2, "alignment": "centered_in_wall"},
        "leaf": {"width": 0.78, "thickness": 0.035, "hinge_offset": 0.06},
        "mount_side": "left",
        "swing": {"hinge": "start", "rotation": "ccw", "angle_degrees": 90, "opens_into": room},
        "operating_state": "open",
        "space_ids": [room, exterior] if exterior else list(wall["related_room_ids"]),
        "clearance_id": "DOOR-CLEAR",
        "requirement_ids": [],
        "provenance": NOTICE,
        "confirmation": "confirmed",
        "review_state": "proposed",
        **extra,
    }


def oracle():
    source = json.loads((ROOT / "examples/batch007b1/rectangle-inward.json").read_text())
    review = source["source"]["replay"]["review"]
    g = review["candidate"]["geometry"]
    footprint = next(r["id"] for r in g["polygons"] if r["role"] == "footprint")
    approach = region(source, "OUT-APPROACH", [[0, -2], [4, -2], [4, 0], [0, 0]])
    review["exteriors"] = [
        {
            "id": "OUT",
            "floor_id": "F1",
            "boundary_id": footprint,
            "approach_id": "OUT-APPROACH",
            "provenance": NOTICE,
        }
    ]
    review["clearance_regions"] = [approach]
    model = generate_walls(bind(source))
    bottom = next(
        b
        for b in model["boundary_topology"]
        if b["reference"] == {"start": [0.0, 0.0], "end": [4.0, 0.0]}
    )
    source["wall_specification"]["treatments"] = source["wall_specification"]["treatments"][:1]
    source["wall_specification"]["treatments"][0]["selector"]["boundary_ids"] = [bottom["id"]]
    model = generate_walls(source)
    assert model["wall_status"] == "GENERATED", model
    wall = model["walls"][0]
    clearance = region(source, "DOOR-CLEAR", [[1.6, -0.7], [2.34, -0.7], [2.34, 0.7], [1.6, 0.7]])
    spec = {
        "id": "SYNTHETIC-OPENING-SPEC",
        "units": "m",
        "frame_id": g["frame"]["id"],
        "vertical_datum": "above_finished_floor",
        "plan_cut_height": 1.2,
        "wall_verticals": [
            {
                "wall_id": w["id"],
                "base": 0,
                "height": 3,
                "provenance": NOTICE,
                "confirmation": "confirmed",
            }
            for w in model["walls"]
        ],
        "openings": [door(wall)],
        "openings_complete": True,
        "fixed_obstacles_complete": True,
        "clearance_regions": [approach, clearance],
        "passages": [],
        "stairs": [],
        "stairs_complete": True,
        "room_area_policy": "exclude_thresholds",
    }
    for sid, last in (("BED:1", [1.97, 2]), ("OUT", [1.97, -1])):
        spec["passages"].append(
            {
                "id": "PATH-" + sid,
                "space_id": sid,
                "floor_id": "F1",
                "frame_id": g["frame"]["id"],
                "units": "m",
                "path": [[1.97, 0], last],
                "width": 0.6,
                "opening_ids": ["DOOR-1"],
                "provenance": NOTICE,
                "confirmation": "confirmed",
            }
        )
    return {
        "schema_version": 1,
        "source": source,
        "source_candidate_digest": model["source_candidate_digest"],
        "source_wall_revision_id": model["wall_revision_id"],
        "specification": spec,
    }


def add_window(value, **extra):
    value = deepcopy(value)
    door_row = value["specification"]["openings"][0]
    row = {
        "id": "WINDOW-1",
        "mark": "W01",
        "type": "fixed_window",
        "kind": "window",
        "floor_id": door_row["floor_id"],
        "host_wall_id": door_row["host_wall_id"],
        "source_wall_digest": door_row["source_wall_digest"],
        "offset": 0.25,
        "rough_width": 0.8,
        "rough_height": 1.0,
        "sill": 0.8,
        "head": 1.8,
        "frame": {"jamb_width": 0.04, "depth": 0.2, "alignment": "centered_in_wall"},
        "space_ids": list(door_row["space_ids"]),
        "operating_state": "fixed",
        "requirement_ids": [],
        "provenance": NOTICE,
        "confirmation": "confirmed",
        "review_state": "proposed",
        **extra,
    }
    value["specification"]["openings"].append(row)
    return value


def rebind_request(value):
    model = generate_walls(bind(value["source"]))
    value["source_wall_revision_id"] = model["wall_revision_id"]
    value["source_candidate_digest"] = model["source_candidate_digest"]
    for row in value["specification"]["openings"]:
        wall = next((w for w in model["walls"] if w["id"] == row.get("host_wall_id")), None)
        if wall:
            row["source_wall_digest"] = wall["geometry_digest"]
    value["specification"]["wall_verticals"] = [
        {
            "wall_id": w["id"],
            "base": 0,
            "height": 3,
            "provenance": NOTICE,
            "confirmation": "confirmed",
        }
        for w in model["walls"]
    ]
    return value


def shared():
    base = oracle()
    source = json.loads((ROOT / "examples/batch007b1/shared-wall.json").read_text())
    review = source["source"]["replay"]["review"]
    g = review["candidate"]["geometry"]
    footprint = next(r["id"] for r in g["polygons"] if r["role"] == "footprint")
    app = region(source, "OUT-APPROACH", [[-2, 0], [0, 0], [0, 5], [-2, 5]])
    review["exteriors"] = [
        {
            "id": "OUT",
            "floor_id": "F1",
            "boundary_id": footprint,
            "approach_id": "OUT-APPROACH",
            "provenance": NOTICE,
        }
    ]
    review["clearance_regions"] = [app]
    model = generate_walls(bind(source))
    exterior = next(
        w for w in model["walls"] if w["reference"] == {"start": [0.0, 0.0], "end": [0.0, 5.0]}
    )
    inside = next(w for w in model["walls"] if w["classification"] == "shared_boundary")
    entrance = door(
        exterior,
        mount_side="right",
        swing={"hinge": "start", "rotation": "cw", "angle_degrees": 90, "opens_into": "BED:1"},
    )
    interior = door(
        inside,
        exterior=None,
        id="DOOR-2",
        mark="D02",
        frame={"jamb_width": 0.04, "depth": 0.1, "alignment": "centered_in_wall"},
        clearance_id="INNER-CLEAR",
        mount_side="right",
        swing={"hinge": "start", "rotation": "cw", "angle_degrees": 90, "opens_into": "LIVING:1"},
    )
    spec = deepcopy(base["specification"])
    spec["openings"] = [entrance, interior]
    spec["clearance_regions"] = [
        app,
        region(source, "DOOR-CLEAR", [[-0.7, 1.6], [0.7, 1.6], [0.7, 2.34], [-0.7, 2.34]]),
        region(source, "INNER-CLEAR", [[3.3, 1.6], [4.7, 1.6], [4.7, 2.34], [3.3, 2.34]]),
    ]
    spec["passages"] = []
    for sid, ids, path in (
        ("OUT", ["DOOR-1"], [[0, 1.97], [-1, 1.97]]),
        ("BED:1", ["DOOR-1", "DOOR-2"], [[0, 1.97], [4, 1.97]]),
        ("LIVING:1", ["DOOR-2"], [[4, 1.97], [6, 1.97]]),
    ):
        spec["passages"].append(
            {
                "id": "PATH-" + sid,
                "space_id": sid,
                "floor_id": "F1",
                "frame_id": g["frame"]["id"],
                "units": "m",
                "path": path,
                "width": 0.6,
                "opening_ids": ids,
                "provenance": NOTICE,
                "confirmation": "confirmed",
            }
        )
    return rebind_request(
        {
            "schema_version": 1,
            "source": source,
            "source_candidate_digest": model["source_candidate_digest"],
            "source_wall_revision_id": model["wall_revision_id"],
            "specification": spec,
        }
    )


def _base_scenarios():
    one = oracle()
    two = shared()
    fixed = add_window(one)
    reverse = deepcopy(one)
    reverse["specification"]["openings"][0]["swing"].update(hinge="end", rotation="cw")
    collision = deepcopy(one)
    collision["specification"]["additional_obstacles"] = [
        region(one["source"], "KNOWN-OBSTACLE", [[1.8, 0.5], [2.1, 0.5], [2.1, 0.8], [1.8, 0.8]])
    ]
    sliding = deepcopy(one)
    s = sliding["specification"]["openings"][0]
    s["type"] = "sliding_door"
    s.pop("swing")
    s.update(
        slide={"direction": "end", "travel": 0.9, "mode": "surface", "opens_into": "BED:1"},
        mount_offset=0.04,
    )
    insufficient = deepcopy(sliding)
    insufficient["specification"]["openings"][0]["slide"]["travel"] = 0.3
    high = add_window(one, sill=1.6, head=2.6)
    unknown = deepcopy(fixed)
    unknown["specification"]["openings"][1].pop("sill")
    outside = deepcopy(one)
    outside["specification"]["openings"][0]["offset"] = 3.8
    overlap = deepcopy(one)
    r = deepcopy(overlap["specification"]["openings"][0])
    r.update(id="DOOR-2", mark="D02", offset=1.8)
    overlap["specification"]["openings"].append(r)
    junction = deepcopy(one)
    junction["source"]["wall_specification"]["treatments"][0]["selector"].pop("boundary_ids")
    junction["specification"]["openings"][0]["offset"] = 0
    rebind_request(junction)
    missing = deepcopy(one)
    missing["specification"]["openings"][0].pop("rough_width")
    stale = deepcopy(one)
    stale["specification"]["openings"][0]["source_wall_digest"] = "stale-wall-digest"
    missing_clearance = deepcopy(one)
    missing_clearance["specification"]["openings"][0].pop("clearance_id")
    stale_evidence = deepcopy(one)
    stale_evidence["specification"]["openings"][0]["review_state"] = "approved"
    marks = deepcopy(fixed)
    marks["specification"]["openings"][1]["mark"] = "D01"
    operable = add_window(
        one,
        type="operable_window",
        operation="side_hung",
        operating_state="closed",
        leaf={"width": 0.68, "thickness": 0.025, "hinge_offset": 0.06},
        mount_side="left",
        swing={"hinge": "start", "rotation": "ccw", "angle_degrees": 90, "opens_into": "BED:1"},
    )
    cut_unknown = deepcopy(fixed)
    cut_unknown["specification"].pop("plan_cut_height")
    pocket = deepcopy(sliding)
    pocket["specification"]["openings"][0]["slide"]["mode"] = "pocket"
    angle = deepcopy(one)
    angle["specification"]["openings"][0]["swing"]["angle_degrees"] = 45
    return {
        "oracle-entrance": one,
        "interior-hinged": two,
        "hinge-end": reverse,
        "swing-fixed-collision": collision,
        "sliding-valid": sliding,
        "sliding-insufficient-travel": insufficient,
        "fixed-window": fixed,
        "window-above-cut": high,
        "window-missing-elevation": unknown,
        "window-no-graph-edge": deepcopy(fixed),
        "outside-host": outside,
        "overlapping-openings": overlap,
        "junction-interference": junction,
        "missing-dimensions": missing,
        "rough-vs-clear": deepcopy(one),
        "stale-wall-digest": stale,
        "two-room-connection": deepcopy(two),
        "missing-clearance": missing_clearance,
        "stale-approval-evidence": stale_evidence,
        "conflicting-marks": marks,
        "deterministic-repeat": deepcopy(fixed),
        "operable-window": operable,
        "missing-plan-cut": cut_unknown,
        "unsupported-pocket": pocket,
        "unsupported-angle": angle,
    }


def historical(ambiguous=False):
    source = json.loads((ROOT / "examples/batch007b1/historical-candidate.json").read_text())
    model = generate_walls(source)
    host_id = next(
        m["candidate_wall_ids"][0] for m in model["opening_mappings"] if m["opening_id"] == "DOOR"
    )
    host = next(w for w in model["walls"] if w["id"] == host_id)
    row = door(
        host,
        room="LIVING:1",
        exterior=None,
        id="DOOR",
        mark="D-H1",
        offset=1.0,
        frame={"jamb_width": 0.04, "depth": 0.1, "alignment": "centered_in_wall"},
        legacy_opening_id="DOOR",
    )
    row.pop("host_wall_id")
    row.pop("clearance_id")
    if ambiguous:
        profile = deepcopy(source["wall_specification"]["treatments"][-1]["wall"])
        profile.update(alignment="centered", classification="special", requirement_ids=[])
        source["wall_specification"]["special_walls"].append(
            {
                "id": "AMBIGUOUS-SPLITTER",
                "floor_id": "F1",
                "frame_id": model["frame_id"],
                "units": "m",
                "reference": {"start": [1.5, 0], "end": [1.5, 4]},
                "wall": profile,
            }
        )
        model = generate_walls(source)
    review = source["source"]["replay"]["review"]
    spec = {
        "id": "SYN-HISTORICAL-OPENING",
        "units": "m",
        "frame_id": model["frame_id"],
        "vertical_datum": "above_finished_floor",
        "plan_cut_height": 1.2,
        "wall_verticals": [
            {
                "wall_id": w["id"],
                "base": 0,
                "height": 3,
                "provenance": NOTICE,
                "confirmation": "confirmed",
            }
            for w in model["walls"]
        ],
        "openings": [row],
        "openings_complete": False,
        "fixed_obstacles_complete": False,
        "clearance_regions": [
            deepcopy(r) for r in review["clearance_regions"] if r["id"] == "APPROACH"
        ],
        "passages": [],
        "stairs": [],
        "stairs_complete": True,
        "room_area_policy": "exclude_thresholds",
    }
    return {
        "schema_version": 1,
        "source": source,
        "source_candidate_digest": model["source_candidate_digest"],
        "source_wall_revision_id": model["wall_revision_id"],
        "specification": spec,
    }


def multiple_floors():
    source = json.loads((ROOT / "examples/batch007b1/multiple-floors.json").read_text())
    model = generate_walls(source)
    g = source["source"]["replay"]["review"]["candidate"]["geometry"]
    spec = deepcopy(oracle()["specification"])
    spec.update(openings=[], clearance_regions=[], passages=[], exteriors=[], stairs_complete=False)
    footprint = next(p["id"] for p in g["polygons"] if p["role"] == "footprint")
    for floor in g["floors"]:
        fid = floor["id"]
        room = next(
            p["room_id"] for p in g["polygons"] if p["role"] == "room" and p["floor_id"] == fid
        )
        wall = next(
            w
            for w in model["walls"]
            if w["floor_id"] == fid and w["reference"] == {"start": [0.0, 0.0], "end": [4.0, 0.0]}
        )
        ext = "OUT-" + fid
        oid = "DOOR-" + fid
        cid = "CLEAR-" + fid
        aid = "APPROACH-" + fid
        spec["exteriors"].append(
            {
                "id": ext,
                "floor_id": fid,
                "boundary_id": footprint,
                "approach_id": aid,
                "provenance": NOTICE,
            }
        )
        spec["clearance_regions"] += [
            region(source, aid, [[0, -2], [4, -2], [4, 0], [0, 0]], fid),
            region(source, cid, [[1.6, -0.7], [2.34, -0.7], [2.34, 0.7], [1.6, 0.7]], fid),
        ]
        spec["openings"].append(door(wall, room=room, exterior=ext, id=oid, clearance_id=cid))
        for sid, last in ((room, [1.97, 2]), (ext, [1.97, -1])):
            spec["passages"].append(
                {
                    "id": "PATH-" + sid,
                    "space_id": sid,
                    "floor_id": fid,
                    "frame_id": model["frame_id"],
                    "units": "m",
                    "path": [[1.97, 0], last],
                    "width": 0.6,
                    "opening_ids": [oid],
                    "provenance": NOTICE,
                    "confirmation": "confirmed",
                }
            )
    return rebind_request(
        {
            "schema_version": 1,
            "source": source,
            "source_candidate_digest": model["source_candidate_digest"],
            "source_wall_revision_id": model["wall_revision_id"],
            "specification": spec,
        }
    )


def townhouse():
    source = json.loads((ROOT / "examples/batch007b1/townhouse-benchmark.json").read_text())
    model = generate_walls(source)
    g = source["source"]["replay"]["review"]["candidate"]["geometry"]
    footprint = next(p["id"] for p in g["polygons"] if p["role"] == "footprint")
    spec = {
        "id": "UNCHANGED-TOWNHOUSE-BENCHMARK-SYNTHETIC-OPENINGS",
        "units": "m",
        "frame_id": model["frame_id"],
        "vertical_datum": "above_finished_floor",
        "plan_cut_height": 1.2,
        "wall_verticals": [
            {
                "wall_id": w["id"],
                "base": 0,
                "height": 3,
                "provenance": NOTICE,
                "confirmation": "confirmed",
            }
            for w in model["walls"]
        ],
        "openings": [],
        "openings_complete": False,
        "fixed_obstacles_complete": False,
        "clearance_regions": [],
        "passages": [],
        "exteriors": [],
        "stairs": [],
        "stairs_complete": False,
        "room_area_policy": "exclude_thresholds",
    }
    for floor in g["floors"]:
        fid = floor["id"]
        ext = "OUT-" + fid
        spec["exteriors"].append(
            {"id": ext, "floor_id": fid, "boundary_id": footprint, "provenance": NOTICE}
        )
        choices = [
            w
            for w in model["walls"]
            if w["floor_id"] == fid
            and w["classification"] == "exterior"
            and w["related_room_ids"]
            and w["reference"]["start"][0] == w["reference"]["end"][0]
        ]
        choices.sort(
            key=lambda w: (-abs(w["reference"]["end"][1] - w["reference"]["start"][1]), w["id"])
        )
        host = choices[0]
        room = host["related_room_ids"][0]
        side = next(
            b["envelope_interior_side"]
            for b in model["boundary_topology"]
            if b["id"] == host["boundary_id"]
        )
        row = door(
            host,
            room=room,
            exterior=ext,
            id="TOWN-DOOR-" + fid,
            mark="D-" + fid,
            offset=0.5,
            mount_side=side,
            swing={
                "hinge": "start",
                "rotation": "ccw" if side == "left" else "cw",
                "angle_degrees": 90,
                "opens_into": room,
            },
        )
        row.pop("clearance_id")
        spec["openings"].append(row)
        winhost = next(
            w
            for w in choices[1:]
            if abs(w["reference"]["end"][1] - w["reference"]["start"][1]) > 1.2
        )
        spec["openings"].append(
            {
                "id": "TOWN-WINDOW-" + fid,
                "mark": "W-" + fid,
                "type": "fixed_window",
                "kind": "window",
                "floor_id": fid,
                "host_wall_id": winhost["id"],
                "source_wall_digest": winhost["geometry_digest"],
                "offset": 0.3,
                "rough_width": 0.8,
                "rough_height": 1.0,
                "sill": 0.8,
                "head": 1.8,
                "frame": {"jamb_width": 0.04, "depth": 0.2, "alignment": "centered_in_wall"},
                "space_ids": [winhost["related_room_ids"][0], ext],
                "operating_state": "fixed",
                "requirement_ids": [],
                "provenance": NOTICE,
                "confirmation": "confirmed",
                "review_state": "proposed",
            }
        )
    return {
        "schema_version": 1,
        "source": source,
        "source_candidate_digest": model["source_candidate_digest"],
        "source_wall_revision_id": model["wall_revision_id"],
        "specification": spec,
    }


def scenarios():
    values = _base_scenarios()
    reverse = values["hinge-end"]
    reverse["specification"]["openings"][0]["clear_start_offset"] = 0.06
    reverse["specification"]["clearance_regions"][1] = region(
        reverse["source"], "DOOR-CLEAR", [[1.56, -0.7], [2.3, -0.7], [2.3, 0.7], [1.56, 0.7]]
    )
    for p in reverse["specification"]["passages"]:
        p["path"] = [[1.93, y] for _, y in p["path"]]
    values.update(
        {
            "historical-opening": historical(),
            "ambiguous-provisional-host": historical(True),
            "multiple-floors": multiple_floors(),
            "townhouse-benchmark": townhouse(),
        }
    )
    repeated = deepcopy(values["oracle-entrance"])
    extra = deepcopy(repeated["specification"]["openings"][0])
    extra.update(id="DOOR-2", offset=0.2, clearance_id="DOOR-CLEAR-2")
    repeated["specification"]["openings"].append(extra)
    clearance = deepcopy(repeated["specification"]["clearance_regions"][1])
    clearance.update(
        id="DOOR-CLEAR-2", exterior=[[0.3, -0.7], [1.04, -0.7], [1.04, 0.7], [0.3, 0.7]]
    )
    repeated["specification"]["clearance_regions"].append(clearance)
    values["repeated-mark-quantity"] = repeated
    return values


def projection(report):
    import hashlib
    from vnai.contracts import canonical_digest
    from vnai.opening_preview import opening_svg

    r = {
        "full_report_sha256": canonical_digest(report),
        "drafting_status": report["drafting_status"],
        "geometry_status": report["geometry_status"],
        "source_candidate_digest": report["source_candidate_digest"],
        "source_wall_revision_id": report["source_wall_revision_id"],
        "opening_geometry_digest": report["opening_geometry_digest"],
        "opening_revision_id": report["opening_revision_id"],
        "openings": report["openings"],
        "floors": report["floors"],
        "rooms": report["rooms"],
        "schedule": report["schedule"],
        "graph_status": report["circulation"].get("graph", {}).get("graph_status"),
        "clearance_status": report["circulation"].get("clearance", {}).get("physical_status"),
        "graph_edges": report["circulation"].get("graph", {}).get("edges", []),
        "error_codes": [d["code"] for d in report["errors"]],
        "missing_codes": [d["code"] for d in report["missing_information"]],
    }
    if report["floors"]:
        r["svg_sha256"] = hashlib.sha256(opening_svg(report).encode()).hexdigest()
    return r
