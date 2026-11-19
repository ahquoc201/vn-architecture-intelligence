"""Explicit synthetic wall dimensions and actual candidate/provenance contracts."""

from copy import deepcopy
from pathlib import Path

from circulation_fixtures import base, selection
from design_fixtures import add_requirement
from floorplan_fixtures import synthetic_spec, approve_source
from replay_fixtures import policy, revision_request
from vnai.contracts import canonical_digest
from vnai.floorplan import generate_floorplans
from vnai.review_common import candidate_digest, design_digest


def profile(thickness=0.2, alignment="inward", classification="exterior", unit="m", **extra):
    return {
        "classification": classification,
        "thickness": {"value": thickness, "unit": unit},
        "alignment": alignment,
        "fixed": False,
        "requirement_ids": ["SYN-WALL-DIMENSIONS"],
        "provenance": "Explicit synthetic wall dimensions; not a Vietnamese standard or expert-approved prescription.",
        "confirmation": "confirmed",
        "approval_status": "proposed",
        **extra,
    }


def source(width=4, depth=5, layouts=None, floors=1, reservations=None):
    layouts = layouts or [("F1", [[0, 0], [width, 0], [width, depth], [0, depth]])]
    spec = synthetic_spec(width, depth, groups=len(layouts))
    brief = spec["geometry"]["zoning"]["brief"]
    brief["site"]["dimensions"]["value"].update(width=max(width, 4), length=max(depth, 20))
    brief["building"]["storeys"]["value"] = floors
    brief["building"]["floors"] = [
        {"id": "F" + str(i), "label": "Synthetic wall floor " + str(i)}
        for i in range(1, floors + 1)
    ]
    add_requirement(brief, "SYN-WALL-DIMENSIONS")
    brief["requirements"][-1]["notes"] = (
        "Synthetic architectural wall specification supplies dimensions; no structural/regulatory inference."
    )
    dims = []
    for room, (floor, coords) in zip(brief["building"]["rooms"], layouts):
        w = max(x for x, y in coords) - min(x for x, y in coords)
        h = max(y for x, y in coords) - min(y for x, y in coords)
        room.update(floor_id=floor, area={"min": 1, "max": w * h, "target": w * h, "unit": "m2"})
        dims.append(
            {
                "room_id": room["id"] + ":1",
                "requirement_id": room["requirement_id"],
                "width": {"min": w, "max": w},
                "depth": {"min": h, "max": h},
            }
        )
    from vnai.zoning import create_zoning_proposal

    zoning = create_zoning_proposal(brief, "SYNTHETIC-WALL-ZONING")
    for row in zoning["assignments"]:
        row["zone"] = "private" if row["room_id"].startswith("BED") else "public"
    spec["geometry"]["zoning"] = zoning
    spec["geometry"]["floors"] = [{"id": "F" + str(i)} for i in range(1, floors + 1)]
    spec["room_dimensions"] = dims
    spec["parameters"].update(candidate_count=1, solution_limit=1, max_steps=20000)
    if reservations:
        spec["geometry"]["polygons"] += deepcopy(reservations)
    approve_source(spec)
    generated = generate_floorplans(spec, include_provenance=True)
    assert generated["status"] == "GENERATED", generated
    original = base(generated["candidates"][0])
    original["openings_complete"] = False
    original["stairs_complete"] = floors == 1
    current = deepcopy(original)
    for row, (_, coords) in zip(
        [r for r in current["candidate"]["geometry"]["polygons"] if r["role"] == "room"], layouts
    ):
        row["exterior"] = deepcopy(coords)
    from replay_fixtures import refresh

    refresh(current)
    result = {
        "schema_version": 1,
        "replay": {
            "schema_version": 1,
            "review": current,
            "mode": "original",
            "provenance": generated["generation_provenance"][0],
        },
        "policy": policy(),
        "drafting_information": {},
    }
    if candidate_digest(current["candidate"]) != candidate_digest(original["candidate"]):
        current["candidate"]["candidate_id"] = "SYNTHETIC-WALL-REV-" + canonical_digest(layouts)
        selection(current)
        result["replay"]["mode"] = "revision"
        parent = {"review": original, "provenance": generated["generation_provenance"][0]}
        result["revision"] = revision_request(parent, {"review": current})
    return result


def request(source_input=None, exterior=0.2, interior=0.1):
    src = source_input or source()
    review = src["replay"]["review"]
    return {
        "schema_version": 1,
        "source": deepcopy(src),
        "wall_specification": {
            "id": "SYNTHETIC-WALL-SPEC",
            "source_candidate_digest": candidate_digest(review["candidate"]),
            "source_design_digest": design_digest(review),
            "boundary_semantics": "allocation_boundary",
            "default_treatment": "no_wall",
            "constraint_basis": {"area": "clear", "dimensions": "allocation"},
            "treatments": [
                {
                    "id": "EXTERIOR",
                    "selector": {"kind": "exterior"},
                    "action": "wall",
                    "wall": profile(exterior),
                    "rationale": "Explicit synthetic inward exterior walls.",
                },
                {
                    "id": "SHARED",
                    "selector": {"kind": "shared"},
                    "action": "wall",
                    "wall": profile(interior, "centered", "shared_boundary"),
                    "rationale": "One explicitly requested partition per shared boundary.",
                },
            ],
            "special_walls": [],
        },
    }


def rebind(value):
    review = value["source"]["replay"]["review"]
    value["wall_specification"].update(
        source_candidate_digest=candidate_digest(review["candidate"]),
        source_design_digest=design_digest(review),
    )
    return value


def special(value, key, start, end, thickness=0.2, offset=0):
    geometry = value["source"]["replay"]["review"]["candidate"]["geometry"]
    value["wall_specification"]["special_walls"].append(
        {
            "id": key,
            "floor_id": "F1",
            "frame_id": geometry["frame"]["id"],
            "units": geometry["units"],
            "reference": {"start": start, "end": end},
            "wall": profile(
                thickness, "centered", "special", offset={"value": offset, "unit": "m"}
            ),
        }
    )
    return value


def legacy():
    from circulation_fixtures import two_rooms

    src = {
        "schema_version": 1,
        "replay": {"schema_version": 1, "mode": "original", "review": two_rooms()},
        "policy": policy(),
        "drafting_information": {},
    }
    value = request(src)
    value["wall_specification"]["constraint_basis"] = {
        "area": "allocation",
        "dimensions": "allocation",
    }
    for rule in value["wall_specification"]["treatments"]:
        rule["wall"]["requirement_ids"] = []
    return value


def townhouse():
    import json

    root = Path(__file__).resolve().parents[1]
    benchmark = json.loads((root / "examples/batch007a/benchmark/benchmark-a.json").read_text())
    generated = generate_floorplans(benchmark["generation_specification"], include_provenance=True)
    review = base(generated["candidates"][0])
    review["openings_complete"] = False
    review["stairs_complete"] = False
    src = {
        "schema_version": 1,
        "replay": {
            "schema_version": 1,
            "review": review,
            "mode": "original",
            "provenance": generated["generation_provenance"][0],
        },
        "policy": deepcopy(benchmark["readiness_policy"]),
        "drafting_information": {},
    }
    value = request(src)
    value["wall_specification"]["constraint_basis"] = {"area": "both", "dimensions": "both"}
    for rule in value["wall_specification"]["treatments"]:
        rule["wall"]["requirement_ids"] = []
    for kind in ("room_unallocated", "room_reserved"):
        item = {
            "id": kind.upper(),
            "selector": {"kind": kind},
            "action": "wall",
            "wall": profile(0.1, "toward_room", "interior_partition"),
            "rationale": "Explicit synthetic wall treatment; original benchmark requirements unchanged.",
        }
        item["wall"]["requirement_ids"] = []
        value["wall_specification"]["treatments"].append(item)
    return value


def scenarios():
    one = request()
    two = request(
        source(
            8,
            5,
            [("F1", [[0, 0], [4, 0], [4, 5], [0, 5]]), ("F1", [[4, 0], [8, 0], [8, 5], [4, 5]])],
        )
    )
    tee = request(
        source(
            8,
            6,
            [
                ("F1", [[0, 0], [4, 0], [4, 6], [0, 6]]),
                ("F1", [[4, 0], [8, 0], [8, 3], [4, 3]]),
                ("F1", [[4, 3], [8, 3], [8, 6], [4, 6]]),
            ],
        )
    )
    cross = request(
        source(
            8,
            6,
            [
                ("F1", [[0, 0], [4, 0], [4, 3], [0, 3]]),
                ("F1", [[4, 0], [8, 0], [8, 3], [4, 3]]),
                ("F1", [[0, 3], [4, 3], [4, 6], [0, 6]]),
                ("F1", [[4, 3], [8, 3], [8, 6], [4, 6]]),
            ],
        )
    )
    large = request(source(8, 6))
    ell = special(deepcopy(large), "SPECIAL-H", [2, 2], [6, 2])
    special(ell, "SPECIAL-V", [2, 2], [2, 5])
    offset = special(deepcopy(large), "OFFSET", [2, 2], [6, 2], offset=0.3)
    missing_thickness = deepcopy(one)
    missing_thickness["wall_specification"]["treatments"][0]["wall"].pop("thickness")
    missing_semantics = deepcopy(one)
    missing_semantics["wall_specification"].pop("boundary_semantics")
    outside = deepcopy(one)
    outside["wall_specification"]["treatments"][0]["wall"]["alignment"] = "centered"
    area_violation = deepcopy(one)
    area_violation["wall_specification"]["constraint_basis"]["area"] = "both"
    # Original source minimum is explicitly 20m2 for this separate synthetic requirement fixture.
    spec = deepcopy(area_violation["source"]["replay"]["provenance"]["generation_specification"])
    spec["geometry"]["zoning"]["brief"]["building"]["rooms"][0]["area"]["min"] = 20
    approve_source(spec)
    generated = generate_floorplans(spec, include_provenance=True)
    review = base(generated["candidates"][0])
    review["openings_complete"] = False
    area_violation["source"]["replay"] = {
        "schema_version": 1,
        "mode": "original",
        "review": review,
        "provenance": generated["generation_provenance"][0],
    }
    area_violation = rebind(area_violation)
    disconnected = special(deepcopy(one), "ROOM-DIVIDER", [0, 2.5], [4, 2.5])
    region = {
        "id": "RESERVED",
        "role": "reservation",
        "reservation_kind": "circulation",
        "owner_id": "F1",
        "floor_id": "F1",
        "frame_id": "LOCAL",
        "units": "m",
        "exterior": [[0, 0], [1, 0], [1, 6], [0, 6]],
        "holes": [],
        "status": "proposed",
        "requirement_id": "REQ-internal_circulation",
        "provenance": "Explicit synthetic reserved circulation.",
    }
    reserved = request(
        source(6, 6, [("F1", [[1, 0], [5, 0], [5, 4], [1, 4]])], reservations=[region])
    )
    open_plan = deepcopy(two)
    open_plan["wall_specification"]["treatments"][1] = {
        "id": "OPEN-PLAN",
        "selector": {"kind": "shared"},
        "action": "no_wall",
        "rationale": "Explicit open-plan decision; no partition.",
    }
    mixed = deepcopy(cross)
    mixed["wall_specification"]["treatments"][0]["wall"]["thickness"]["value"] = 0.3
    mixed["wall_specification"]["treatments"][1]["wall"]["thickness"]["value"] = 0.2
    mixed["wall_specification"]["treatments"].append(
        {
            "id": "THICK-HORIZONTAL",
            "selector": {"kind": "shared", "room_ids": ["BED:1", "KITCHEN:1"]},
            "action": "wall",
            "wall": profile(0.4, "centered", "shared_boundary"),
            "rationale": "Explicit unequal-thickness X joint.",
        }
    )
    different = deepcopy(ell)
    different["wall_specification"]["special_walls"][1]["wall"]["thickness"]["value"] = 0.4
    duplicate = deepcopy(two)
    duplicate["wall_specification"]["treatments"].append(
        {**deepcopy(duplicate["wall_specification"]["treatments"][1]), "id": "SHARED-EQUIVALENT"}
    )
    multiple = request(
        source(
            4,
            5,
            [("F1", [[0, 0], [4, 0], [4, 5], [0, 5]]), ("F2", [[0, 0], [4, 0], [4, 5], [0, 5]])],
            floors=2,
        )
    )
    unconfirmed = deepcopy(one)
    unconfirmed["wall_specification"]["treatments"][0]["wall"]["confirmation"] = "proposed"
    return {
        "rectangle-inward": one,
        "shared-wall": two,
        "t-junction": tee,
        "x-junction": cross,
        "l-junction": ell,
        "different-exterior-interior": deepcopy(two),
        "different-junction-thickness": different,
        "mixed-x-thickness": mixed,
        "explicit-offset": offset,
        "shared-wall-deduplication": duplicate,
        "open-plan": open_plan,
        "missing-thickness": missing_thickness,
        "missing-semantics": missing_semantics,
        "outside-envelope": outside,
        "clear-area-violation": area_violation,
        "disconnected-clear-room": disconnected,
        "reservation-encroachment": reserved,
        "stale-opening-evidence": legacy(),
        "multiple-floors": multiple,
        "repeatable": deepcopy(one),
        "historical-candidate": legacy(),
        "empty-clear-room": request(source(), exterior=3),
        "unconfirmed-wall-spec": unconfirmed,
        "nonorthogonal-special": special(deepcopy(one), "SKEW", [1, 1], [2, 2]),
        "townhouse-benchmark": townhouse(),
    }


def orthogonal_room():
    from replay_fixtures import refresh

    value = request(source(8, 6))
    parent = deepcopy(value["source"]["replay"]["review"])
    child = value["source"]["replay"]["review"]
    row = next(r for r in child["candidate"]["geometry"]["polygons"] if r["role"] == "room")
    row["exterior"] = [[0, 0], [8, 0], [8, 2], [4, 2], [4, 6], [0, 6]]
    child["candidate"]["candidate_id"] = "SYNTHETIC-ORTHOGONAL-ROOM-REVISION"
    refresh(child)
    value["source"]["replay"]["mode"] = "revision"
    value["source"]["revision"] = revision_request(
        {"review": parent, "provenance": value["source"]["replay"]["provenance"]}, {"review": child}
    )
    value["wall_specification"]["treatments"].append(
        {
            "id": "L-ROOM-FACES",
            "selector": {"kind": "room_unallocated"},
            "action": "wall",
            "wall": profile(0.1, "toward_room", "interior_partition"),
            "rationale": "Explicit wall intent on orthogonal concave room boundaries.",
        }
    )
    return rebind(value)


def millimeter_coordinates():
    original = source()
    spec = deepcopy(original["replay"]["provenance"]["generation_specification"])
    spec["geometry"]["units"] = "mm"
    for row in spec["geometry"]["polygons"]:
        row["units"] = "mm"
        row["exterior"] = [[1000 * x, 1000 * y] for x, y in row["exterior"]]
        row["holes"] = [[[1000 * x, 1000 * y] for x, y in ring] for ring in row.get("holes", [])]
    for row in spec["room_dimensions"]:
        for axis in ("width", "depth"):
            row[axis] = {k: 1000 * v for k, v in row[axis].items()}
    spec["parameters"]["grid_step"] *= 1000
    approve_source(spec)
    generated = generate_floorplans(spec, include_provenance=True)
    assert generated["status"] == "GENERATED", generated
    review = base(generated["candidates"][0])
    review["openings_complete"] = False
    value = request(
        {
            "schema_version": 1,
            "replay": {
                "schema_version": 1,
                "review": review,
                "mode": "original",
                "provenance": generated["generation_provenance"][0],
            },
            "policy": policy(),
            "drafting_information": {},
        }
    )
    value["wall_specification"]["treatments"][0]["wall"]["thickness"] = {"value": 200, "unit": "mm"}
    return value


def projection(report):
    from vnai.wall_preview import wall_svg
    import hashlib

    result = {
        "full_report_sha256": canonical_digest(report),
        "wall_status": report["wall_status"],
        "geometry_status": report["geometry_status"],
        "source_candidate_digest": report["source_candidate_digest"],
        "wall_specification_digest": report["wall_specification_digest"],
        "derived_geometry_digest": report["derived_geometry_digest"],
        "wall_revision_id": report["wall_revision_id"],
        "floors": report["floors"],
        "rooms": report["rooms"],
        "junctions": report["junctions"],
        "opening_mappings": report["opening_mappings"],
        "error_codes": [e["code"] for e in report["errors"]],
        "missing_codes": [e["code"] for e in report["missing_information"]],
    }
    if report["floors"]:
        result["svg_sha256"] = hashlib.sha256(wall_svg(report).encode()).hexdigest()
    return result
