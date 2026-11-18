"""Helpers for synthetic Batch 005 fixtures, never real architectural approval."""

import json
from pathlib import Path

from vnai.spatial import geometry_digest
from vnai.zoning import decision_digest

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "examples/batch005" / (name + ".json")).read_text(encoding="utf-8"))


def resign_geometry(doc):
    for row in doc["polygons"] + doc["relationships"]:
        if row.get("approval"):
            row["approval"]["digest"] = geometry_digest(doc, row)
    return doc


def resign_zoning(doc):
    assignments = {row["id"]: row for row in doc["assignments"]}
    for event in doc["decisions"]:
        event["record"]["digest"] = decision_digest(doc, assignments[event["decision_id"]])
    return doc
