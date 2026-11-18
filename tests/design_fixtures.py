"""Synthetic test briefs; numeric fixtures are not architectural guidance."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def incomplete_brief():
    return json.loads((ROOT / "examples/townhouse_4x20_brief.json").read_text(encoding="utf-8"))


def valid_brief():
    doc = incomplete_brief()
    values = {"Q-NORTH": 0, "Q-FRONTAGE": "test frontage", "Q-ROAD": "test road access",
              "Q-SITE-LIMITS": ["Synthetic site limits provided by test client"],
              "Q-STAIR": "Test client requests stairs, detailed design pending",
              "Q-FOOTPRINT": {"target": 60, "unit": "m2"}, "Q-OCCUPANTS": 4}
    for req in doc["requirements"]:
        if req["type"] == "question":
            req["type"] = "mandatory"
            req["confirmation"] = "confirmed"
    for section in ("site", "building", "client"):
        for fact in doc[section].values():
            if isinstance(fact, dict) and fact.get("requirement_id") in values:
                fact["value"] = values[fact["requirement_id"]]
    doc["building"]["floors"] = [{"id": f"F{i}", "label": f"Test floor {i}"} for i in (1, 2, 3)]
    for room in doc["building"]["rooms"]:
        room["floor_id"] = "F1"
        room["area"] = {"target": 10, "unit": "m2"}
    for name in ("internal_circulation", "vertical_circulation"):
        key = "REQ-" + name
        add_requirement(doc, key)
        doc["building"][name] = {"requirement_id": key, "value": "Test circulation request"}
    return doc


def add_requirement(doc, key, kind="mandatory", confirmation="confirmed"):
    doc["requirements"].append({"id": key, "type": kind, "origin": "synthetic_test_client",
                                "confirmation": confirmation, "priority": "high"})


def add_relationship(doc, key="REL1", relation="adjacent", strength="hard", pair=None):
    add_requirement(doc, "REQ-" + key, "mandatory" if strength == "hard" else "preference")
    row = {"id": key, "requirement_id": "REQ-" + key, "room_ids": pair or ["LIVING", "KITCHEN"],
           "relation": relation, "strength": strength}
    doc["building"].setdefault("relationships", []).append(row)
    return row
