"""Synthetic generation specifications; sizes and approval records are test data only."""

from design_fixtures import valid_brief
from vnai.zoning import create_zoning_proposal, decision_digest
from vnai.floorplan import authorization_digest


def approve_source(doc):
    zoning = doc["geometry"]["zoning"]
    zoning["decisions"] = []
    for row in zoning["assignments"]:
        row["status"] = "approved"
    for row in zoning["assignments"]:
        for action, stamp in (("reviewed", "00:00:00"), ("approved", "00:01:00")):
            zoning["decisions"].append(
                {
                    "id": row["id"] + "-" + action,
                    "decision_id": row["id"],
                    "action": action,
                    "record": {
                        "actor": "SYNTHETIC_TEST_ARCHITECT_NOT_REAL_APPROVAL",
                        "role": "architect",
                        "recorded_at": "2026-11-18T" + stamp + "Z",
                        "digest": decision_digest(zoning, row),
                    },
                }
            )
    return authorize(doc)


def authorize(doc):
    doc["authorization"] = {
        "purpose": "preliminary_generation_only",
        "record": {
            "actor": "SYNTHETIC_TEST_ARCHITECT_NOT_REAL_APPROVAL",
            "role": "architect",
            "recorded_at": "2026-11-18T00:02:00Z",
            "digest": authorization_digest(doc),
        },
    }
    return doc


def synthetic_spec(width=4, depth=4, groups=2):
    brief = valid_brief()
    brief["project"]["id"] = "SYNTHETIC-FLOORPLAN"
    brief["project"]["name"] = "Synthetic solver fixture; not a client layout"
    brief["building"]["storeys"]["value"] = 1
    brief["building"]["floors"] = [{"id": "F1", "label": "Synthetic floor"}]
    brief["building"]["footprint"]["value"] = {"target": width * depth, "unit": "m2"}
    brief["building"]["rooms"] = brief["building"]["rooms"][:groups]
    for room in brief["building"]["rooms"]:
        room["quantity"] = 1
        room["area"] = {"min": 8, "max": 8, "target": 8, "unit": "m2"}
    zoning = create_zoning_proposal(brief, "SYNTHETIC-GENERATION")
    for row in zoning["assignments"]:
        row["zone"] = "private" if row["room_id"].startswith("BED") else "public"

    def polygon(key, role, x0, y0, x1, y1):
        return {
            "id": key,
            "role": role,
            "owner_id": brief["project"]["id"],
            "frame_id": "LOCAL",
            "units": "m",
            "exterior": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "holes": [],
            "status": "proposed",
        }

    geometry = {
        "schema_version": 1,
        "project_id": brief["project"]["id"],
        "fixture_notice": "Synthetic coordinates and approval records only; not client-confirmed architecture.",
        "units": "m",
        "frame": {"id": "LOCAL", "kind": "local_site", "axes": "x_east_y_north"},
        "tolerances": {
            "boundary_m": 0,
            "overlap_m2": 0,
            "min_area_m2": 0.000001,
            "target_area_m2": 0.01,
        },
        "floors": [{"id": "F1"}],
        "polygons": [
            polygon("SITE", "site", 0, 0, max(width, 4), max(depth, 20)),
            polygon("FOOTPRINT", "footprint", 0, 0, width, depth),
        ],
        "points": [],
        "segments": [],
        "relationships": [],
        "zoning": zoning,
    }
    spec = {
        "schema_version": 1,
        "geometry": geometry,
        "fixed_elements_status": "complete",
        "room_dimensions": [
            {
                "room_id": a["room_id"],
                "requirement_id": a["requirement_id"],
                "width": {"min": 2, "max": 2},
                "depth": {"min": 4, "max": 4},
            }
            for a in zoning["assignments"]
        ],
        "parameters": {
            "grid_step": 1,
            "candidate_count": 3,
            "max_steps": 50000,
            "solution_limit": 32,
        },
    }
    return approve_source(spec)


def reservation_spec():
    doc = synthetic_spec(width=5)
    doc["geometry"]["polygons"].append(
        {
            "id": "FIXED-STAIR",
            "role": "reservation",
            "reservation_kind": "stairwell",
            "provenance": "Synthetic supplied fixed envelope",
            "requirement_id": "Q-STAIR",
            "owner_id": "F1",
            "floor_id": "F1",
            "frame_id": "LOCAL",
            "units": "m",
            "exterior": [[0, 0], [1, 0], [1, 4], [0, 4]],
            "holes": [],
            "status": "proposed",
        }
    )
    return authorize(doc)


def alternatives_spec():
    doc = synthetic_spec()
    for dim in doc["room_dimensions"]:
        dim["width"] = {"min": 1, "max": 4}
        dim["depth"] = {"min": 1, "max": 4}
    return authorize(doc)


def multizone_spec():
    doc = synthetic_spec(width=6, depth=2, groups=3)
    for room in doc["geometry"]["zoning"]["brief"]["building"]["rooms"]:
        room["area"] = {"min": 4, "max": 4, "target": 4, "unit": "m2"}
    for dim in doc["room_dimensions"]:
        dim["width"] = {"min": 2, "max": 2}
        dim["depth"] = {"min": 2, "max": 2}
    req = {
        "id": "PREF-ADJACENCY",
        "type": "preference",
        "origin": "synthetic_test",
        "confirmation": "confirmed",
        "priority": "medium",
    }
    doc["geometry"]["zoning"]["brief"]["requirements"].append(req)
    doc["geometry"]["zoning"]["brief"]["building"]["relationships"] = [
        {
            "id": "REL-ADJACENCY",
            "requirement_id": req["id"],
            "room_ids": ["BED", "KITCHEN"],
            "relation": "adjacent",
            "strength": "soft",
        }
    ]
    return approve_source(doc)
