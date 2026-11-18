"""Deterministic room program, without layout generation or CAD side effects."""

from copy import deepcopy
from decimal import Decimal
from itertools import product

from vnai.design_brief import area_m2, confirmed, validate_design_brief


def build_space_program(brief: dict) -> dict:
    validation = validate_design_brief(brief)
    output = {"report_schema_version": 1, "engine_version": validation["engine_version"],
              "brief_schema_version": validation["brief_schema_version"],
              "project_id": validation["project_id"], "status": validation["status"],
              "validation": validation, "rooms": [], "relationships": [], "areas": None,
              "input_brief": deepcopy(brief), "cad_writes_permitted": False,
              "layout_generated": False, "geometric_feasibility": "NOT_EVALUATED"}
    if validation["errors"]:
        return output  # Never manufacture a partial program from invalid data.
    requirements = {r["id"]: r for r in brief["requirements"]}
    building = brief.get("building", {})
    groups: dict[str, list[str]] = {}
    for room in building.get("rooms", []):
        ids = groups.setdefault(room["id"], [])
        for index in range(room["quantity"]):
            instance_id = f"{room['id']}:{index + 1}"
            ids.append(instance_id)
            key = room["requirement_id"]
            output["rooms"].append({
                "id": instance_id, "room_group_id": room["id"], "type": room["type"],
                "requirement_id": key, "governance": deepcopy(requirements[key]),
                "floor_id": room.get("floor_id"),
                "requested_area_m2": area_m2(room["area"]) if room.get("area") else None,
                "confirmed": confirmed(requirements, key),
            })
    for relationship in building.get("relationships", []):
        left, right = relationship["room_ids"]
        output["relationships"].append({**deepcopy(relationship),
                                        "instance_pairs": [list(pair) for pair in
                                                           product(groups[left], groups[right])]})
    lot_area = None
    dimensions = brief.get("site", {}).get("dimensions")
    if dimensions and dimensions["value"] is not None and confirmed(
            requirements, dimensions["requirement_id"]):
        value = dimensions["value"]
        scale = Decimal(1) if value["unit"] == "m" else Decimal("0.001")
        lot_area = float(Decimal(str(value["width"])) * Decimal(str(value["length"]))
                         * scale * scale)

    def supplied_area(name: str) -> dict | None:
        fact = building.get(name)
        if fact and fact["value"] is not None and confirmed(requirements, fact["requirement_id"]):
            return {"requirement_id": fact["requirement_id"], **area_m2(fact["value"])}
        return None

    totals = {}
    for bound in ("target", "min", "max"):
        values = []
        for room in output["rooms"]:
            area = room["requested_area_m2"]
            if not area or not room["confirmed"]:
                continue
            # A supplied target alone is not a guaranteed minimum or maximum.
            if bound in area:
                values.append(Decimal(str(area[bound])))
        complete = bool(output["rooms"]) and len(values) == len(output["rooms"])
        known_sum = float(sum(values, Decimal(0))) if values else None
        totals[bound] = {"known_sum_m2": known_sum, "covered_room_count": len(values),
                         "complete": complete, "total_m2": known_sum if complete else None}
    output["areas"] = {
        "lot_area_m2": lot_area,
        "lot_area_method": "declared rectangular dimensions; not a cadastral verification",
        "building_footprint_m2": supplied_area("footprint"),
        "gross_floor_area_m2": supplied_area("gross_floor_area"),
        "requested_net_room_area_m2": totals,
        "unallocated_area_m2": None,
        "note": "GFA minus net room targets is not unallocated usable area. No wall, stair, "
                "void, circulation or setback geometry has been calculated; sums prove no feasibility.",
    }
    return output
