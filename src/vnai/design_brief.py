"""Versioned design-brief validation; workflow gates, never design standards."""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import yaml

from vnai import __version__

ARCHITECTURE = Path(__file__).resolve().parents[2] / "knowledge" / "architecture"
MAX_ROOM_INSTANCES = 10000  # Resource limit, not an architectural requirement.


def load_architecture(name: str) -> dict:
    with (ARCHITECTURE / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def area_m2(value: dict) -> dict[str, float]:
    factor = Decimal(1) if value["unit"] == "m2" else Decimal("0.000001")
    return {key: float(Decimal(str(value[key])) * factor)
            for key in ("target", "min", "max") if key in value}


def confirmed(requirements: dict[str, dict], requirement_id: str) -> bool:
    item = requirements[requirement_id]
    return item["confirmation"] == "confirmed" and item["type"] not in {"assumption", "question"}


def _facts(doc: dict) -> list[tuple[str, dict]]:
    return [(f"{section}.{key}", value)
            for section in ("site", "building", "client")
            for key, value in doc.get(section, {}).items()
            if isinstance(value, dict) and "requirement_id" in value]


def _nonfinite(value: Any, path: str = "$") -> list[str]:
    if isinstance(value, float) and not math.isfinite(value):
        return [path]
    if isinstance(value, dict):
        return [p for key, child in value.items() for p in _nonfinite(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [p for i, child in enumerate(value) for p in _nonfinite(child, f"{path}[{i}]")]
    return []


def validate_design_brief(doc: Any) -> dict:
    """Return deterministic issues. Only VALID is data-ready, never layout approval."""
    result = {"report_schema_version": 1, "engine_version": __version__,
              "brief_schema_version": doc.get("schema_version") if isinstance(doc, dict) else None,
              "project_id": None, "status": "INVALID", "ready_for_planning": False,
              "errors": [], "warnings": [], "missing_information": [], "recommendations": [],
              "cad_writes_permitted": False, "architect_approval_required": True,
              "standards_review": "NOT_EVALUATED", "fengshui_review": "NOT_EVALUATED"}

    def issue(bucket: str, code: str, path: str, message: str,
              requirement_ids: list[str] | None = None) -> None:
        result[bucket].append({"code": code, "path": path, "message": message,
                               "requirement_ids": requirement_ids or []})

    for path in _nonfinite(doc):
        issue("errors", "NONFINITE_NUMBER", path, "Numbers must be finite JSON values.")
    schema = json.loads((ARCHITECTURE / "design-brief.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(doc), key=lambda e: (str(list(e.path)), e.message)):
        path = "$" + "".join(f"[{v}]" if isinstance(v, int) else f".{v}" for v in error.path)
        code = "SCHEMA_VERSION" if list(error.path) == ["schema_version"] else "SCHEMA"
        issue("errors", code, path, error.message)
    if result["errors"]:
        return result
    result["project_id"] = doc["project"]["id"]
    requirements: dict[str, dict] = {}
    all_ids: set[str] = set()

    def register(key: str, path: str) -> None:
        if key in all_ids:
            issue("errors", "DUPLICATE_ID", path, f"Duplicate identifier: {key}")
        all_ids.add(key)

    for i, row in enumerate(doc["requirements"]):
        path = f"requirements[{i}]"
        register(row["id"], path)
        requirements[row["id"]] = row
        if row["type"] == "assumption" and row["confirmation"] != "unconfirmed":
            issue("errors", "ASSUMPTION_STATUS", path,
                  "Assumptions must remain unconfirmed; reclassify after confirmation.", [row["id"]])
        if row["type"] == "question" and row["confirmation"] != "unknown":
            issue("errors", "QUESTION_STATUS", path, "Questions must remain unknown.", [row["id"]])
        if row["confirmation"] in {"unconfirmed", "unknown"}:
            issue("missing_information", "REQUIREMENT_UNRESOLVED", path,
                  "Confirm, resolve or explicitly mark this requirement not applicable.", [row["id"]])

    def check_ref(key: str, path: str) -> bool:
        if key not in requirements:
            issue("errors", "UNKNOWN_REQUIREMENT", path, f"Unknown requirement: {key}", [key])
            return False
        return True

    facts = dict(_facts(doc))
    for path, fact in facts.items():
        key = fact["requirement_id"]
        if not check_ref(key, path):
            continue
        state = requirements[key]["confirmation"]
        if (state == "confirmed" and fact["value"] is None) or (
                state in {"unknown", "not_applicable"} and fact["value"] is not None):
            issue("errors", "VALUE_STATUS_CONFLICT", path,
                  "Confirmed facts need values; unknown/not_applicable facts need null.", [key])

    def available(path: str, allow_na: bool = False) -> bool:
        fact = facts.get(path)
        if not fact or fact["requirement_id"] not in requirements:
            return False
        req = requirements[fact["requirement_id"]]
        return (allow_na and req["confirmation"] == "not_applicable") or (
            confirmed(requirements, req["id"]) and fact["value"] is not None)

    def need(path: str, allow_na: bool = False) -> None:
        if not available(path, allow_na):
            fact = facts.get(path)
            issue("missing_information", "PLANNING_DATA_MISSING", path,
                  "Confirmed data required before downstream planning.",
                  [fact["requirement_id"]] if fact else [])

    if not available("site.dimensions") and not available("site.geometry_ref"):
        need("site.dimensions")
    gates = load_architecture("design-constraints.yaml")
    for name in gates["planning_critical_site_fields"]:
        need(f"site.{name}", allow_na=name == "constraints")
    for name in gates["planning_critical_building_fields"]:
        need(f"building.{name}", allow_na=True)
    need("building.storeys")
    need("building.footprint")
    if available("site.geometry_ref") and not available("site.dimensions"):
        issue("missing_information", "GEOMETRY_REFERENCE_UNRESOLVED", "site.geometry_ref",
              "Reference is preserved, not loaded; verified dimensions/geometry are still needed.",
              [facts["site.geometry_ref"]["requirement_id"]])
    if available("site.unverified_measurements"):
        issue("missing_information", "MEASUREMENTS_UNVERIFIED", "site.unverified_measurements",
              "Resolve the explicitly listed unverified measurements.",
              [facts["site.unverified_measurements"]["requirement_id"]])

    building = doc.get("building", {})
    floors = building.get("floors", [])
    floor_ids = {floor["id"] for floor in floors}
    for floor in floors:
        register(floor["id"], "building.floors")
    if not floors:
        issue("missing_information", "FLOORS_MISSING", "building.floors", "Supply floor designations.")
    if available("building.storeys"):
        count = building["storeys"]["value"]
        if floors and len(floors) != count:
            issue("errors", "STOREY_COUNT_CONFLICT", "building.floors",
                  "Floor designations must match the declared storey count.",
                  [building["storeys"]["requirement_id"]])
        if count > 1:
            need("building.stairs")
            for name in ("stairs", "vertical_circulation"):
                fact = facts.get(f"building.{name}")
                if fact and fact["requirement_id"] in requirements and requirements[
                        fact["requirement_id"]]["confirmation"] == "not_applicable":
                    issue("errors", "MULTISTOREY_CIRCULATION", f"building.{name}",
                          "Multi-storey circulation cannot be marked not applicable.",
                          [fact["requirement_id"]])

    room_rows = building.get("rooms", [])
    rooms = {room["id"]: room for room in room_rows}
    room_types = load_architecture("room-types.yaml")["room_types"]
    if not rooms:
        issue("missing_information", "ROOMS_MISSING", "building.rooms", "Supply required rooms.")
    if sum(room["quantity"] for room in room_rows) > MAX_ROOM_INSTANCES:
        issue("errors", "RESOURCE_LIMIT", "building.rooms",
              f"At most {MAX_ROOM_INSTANCES} room instances supported per brief (resource guard).")
    for room in room_rows:
        path = f"building.rooms.{room['id']}"
        register(room["id"], path)
        check_ref(room["requirement_id"], path)
        if room["type"] not in room_types:
            issue("errors", "ROOM_TYPE", path, "Unknown room type; use other with notes.")
        if room["type"] == "other" and not room.get("notes", "").strip():
            issue("errors", "ROOM_TYPE_NOTES", path, "Describe client-defined room type in notes.")
        if room["requirement_id"] in requirements and requirements[
                room["requirement_id"]]["confirmation"] in {"unknown", "not_applicable"}:
            issue("errors", "ROOM_STATUS_CONFLICT", path,
                  "A concrete room request cannot be unknown/not applicable.", [room["requirement_id"]])
        floor = room.get("floor_id")
        if floor is None:
            issue("missing_information", "ROOM_FLOOR_MISSING", path,
                  "Assign room instances to a floor after architect review.", [room["requirement_id"]])
        elif floor not in floor_ids:
            issue("errors", "UNKNOWN_FLOOR", path, f"Unknown floor: {floor}", [room["requirement_id"]])
        if room.get("area") is None:
            issue("missing_information", "ROOM_AREA_MISSING", path,
                  "No client-supplied area target or bounds.", [room["requirement_id"]])

    area_values = [(f"building.rooms.{r['id']}.area", r["area"], r["requirement_id"])
                   for r in room_rows if r.get("area") is not None]
    area_values += [(p, f["value"], f["requirement_id"]) for p, f in facts.items()
                    if p in {"building.footprint", "building.gross_floor_area"} and f["value"] is not None]
    for path, value, key in area_values:
        low, high, target = value.get("min"), value.get("max"), value.get("target")
        if (low is not None and high is not None and low > high) or (
                target is not None and ((low is not None and target < low)
                                       or (high is not None and target > high))):
            issue("errors", "AREA_BOUNDS", path, "Area target/bounds contradict each other.", [key])
        if any(not math.isfinite(v) or v <= 0 for v in area_m2(value).values()):
            issue("errors", "NUMERIC_RANGE", path, "Converted area is outside finite positive range.", [key])

    relationships: dict[tuple[str, str], list[dict]] = {}
    relations = load_architecture("adjacency-rules.yaml")["relations"]
    pair_count = 0
    for row in building.get("relationships", []):
        path = f"building.relationships.{row['id']}"
        register(row["id"], path)
        key = row["requirement_id"]
        check_ref(key, path)
        if row["relation"] not in relations:
            issue("errors", "RELATION_TYPE", path, "Unsupported relationship.", [key])
        if any(room_id not in rooms for room_id in row["room_ids"]):
            issue("errors", "UNKNOWN_ROOM", path, "Relationship references an unknown room group.", [key])
            continue
        if row["strength"] == "hard" and key in requirements and (
                not confirmed(requirements, key) or requirements[key]["type"] != "mandatory"):
            issue("errors", "HARD_REQUIREMENT_UNCONFIRMED", path,
                  "Hard constraints require a confirmed mandatory requirement.", [key])
        pair_count += rooms[row["room_ids"][0]]["quantity"] * rooms[row["room_ids"][1]]["quantity"]
        if pair_count > 100000:
            issue("errors", "RESOURCE_LIMIT", path,
                  "At most 100000 expanded instance pairs supported (resource guard).", [key])
        pair = tuple(sorted(row["room_ids"]))
        for previous in relationships.get(pair, []):
            if previous["relation"] != row["relation"]:
                hard = previous["strength"] == row["strength"] == "hard"
                issue("errors" if hard else "warnings", "RELATION_CONFLICT", path,
                      "The same room groups request both adjacency and separation.",
                      [previous["requirement_id"], key])
        relationships.setdefault(pair, []).append(row)
        left, right = (rooms[r] for r in pair)
        if (row["relation"] == "adjacent" and left.get("floor_id") and right.get("floor_id")
                and left["floor_id"] != right["floor_id"]):
            issue("errors" if row["strength"] == "hard" else "warnings",
                  "ADJACENCY_FLOOR_CONFLICT", path, "Adjacency means the same storey.", [key])
    for row in building.get("excluded_room_types", []):
        key = row["requirement_id"]
        path = "building.excluded_room_types"
        check_ref(key, path)
        if row["room_type"] not in room_types:
            issue("errors", "ROOM_TYPE", path, "Unknown excluded room type.", [key])
        if row["strength"] == "hard" and key in requirements and (
                not confirmed(requirements, key) or requirements[key]["type"] != "mandatory"):
            issue("errors", "HARD_REQUIREMENT_UNCONFIRMED", path,
                  "Hard exclusions require a confirmed mandatory requirement.", [key])
        for room in room_rows:
            if room["type"] == row["room_type"]:
                hard_room = room["requirement_id"] in requirements and requirements[
                    room["requirement_id"]]["type"] == "mandatory"
                issue("errors" if row["strength"] == "hard" and hard_room else "warnings",
                      "ROOM_EXCLUSION_CONFLICT", path, "A requested room type is also excluded.",
                      [key, room["requirement_id"]])

    # Check arithmetic separately; totals are never evidence of spatial feasibility.
    try:
        dimensions = facts.get("site.dimensions", {}).get("value")
        if dimensions:
            scale = Decimal(1) if dimensions["unit"] == "m" else Decimal("0.001")
            lot = float(Decimal(str(dimensions["width"])) * Decimal(str(dimensions["length"]))
                        * scale * scale)
            if not math.isfinite(lot) or lot <= 0:
                raise ValueError
        for bound in ("target", "min", "max"):
            total = sum(Decimal(str(area_m2(r["area"])[bound])) * r["quantity"]
                        for r in room_rows if r.get("area") and bound in r["area"])
            if not math.isfinite(float(total)):
                raise ValueError
    except (ValueError, OverflowError):
        issue("errors", "NUMERIC_RANGE", "building", "Derived area exceeds finite numeric range.")
    issue("recommendations", "ARCHITECT_REVIEW", "project",
          "Architect approval is required before layout generation; no feasibility or compliance claim.")
    result["status"] = ("INVALID" if result["errors"] else
                        "INCOMPLETE" if result["missing_information"] else "VALID")
    result["ready_for_planning"] = result["status"] == "VALID"
    return result


@dataclass
class DesignBrief:
    """Snapshot model retaining all supplied provenance; no implicit defaults for facts."""

    data: dict

    @classmethod
    def from_dict(cls, value: dict) -> "DesignBrief":
        report = validate_design_brief(value)
        if report["errors"]:
            raise ValueError("Invalid design brief: " + "; ".join(
                f"{i['path']}: {i['message']}" for i in report["errors"]))
        return cls(deepcopy(value))

    def report(self) -> dict:
        return validate_design_brief(self.data)
