"""Schema/runtime contracts and explicit planning-data gates."""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from design_fixtures import ROOT, add_relationship, add_requirement, incomplete_brief, valid_brief
from vnai.design_brief import DesignBrief, validate_design_brief


def codes(report, bucket="errors"):
    return {item["code"] for item in report[bucket]}


def test_schema_valid_and_example_structurally_valid():
    schema = json.loads((ROOT / "knowledge/architecture/design-brief.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(incomplete_brief())) == []


def test_valid_means_data_ready_not_cad_approval():
    report = validate_design_brief(valid_brief())
    assert report["status"] == "VALID", report
    assert report["ready_for_planning"]
    assert report["architect_approval_required"]
    assert not report["cad_writes_permitted"]
    assert report["standards_review"] == report["fengshui_review"] == "NOT_EVALUATED"


def test_incomplete_example_has_no_errors_and_no_fabricated_values():
    doc = incomplete_brief()
    original = deepcopy(doc)
    report = validate_design_brief(doc)
    assert report["status"] == "INCOMPLETE"
    assert not report["errors"]
    assert {"FLOORS_MISSING", "ROOM_AREA_MISSING", "ROOM_FLOOR_MISSING",
            "REQUIREMENT_UNRESOLVED"} <= codes(report, "missing_information")
    assert doc == original


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_incompatible_schema(version):
    doc = valid_brief()
    doc["schema_version"] = version
    assert validate_design_brief(doc)["status"] == "INVALID"


@pytest.mark.parametrize("value", [0, -1, True, "4", None, float("nan"), float("inf")])
def test_invalid_dimensions(value):
    doc = valid_brief()
    doc["site"]["dimensions"]["value"]["width"] = value
    assert validate_design_brief(doc)["status"] == "INVALID"


@pytest.mark.parametrize("unit", ["cm", "meters", "sqm", "", None])
def test_unsupported_units(unit):
    doc = valid_brief()
    doc["site"]["dimensions"]["value"]["unit"] = unit
    assert "SCHEMA" in codes(validate_design_brief(doc))


@pytest.mark.parametrize("field", ["dimensions", "road_access", "frontage", "north_degrees", "constraints"])
def test_missing_critical_site_info(field):
    doc = valid_brief()
    del doc["site"][field]
    assert validate_design_brief(doc)["status"] == "INCOMPLETE"


def test_unknown_not_applicable_and_absent_are_distinct():
    doc = valid_brief()
    del doc["site"]["constraints"]
    assert validate_design_brief(doc)["status"] == "INCOMPLETE"
    doc["site"]["constraints"] = {"requirement_id": "Q-SITE-LIMITS", "value": None}
    req = next(r for r in doc["requirements"] if r["id"] == "Q-SITE-LIMITS")
    req["confirmation"] = "unknown"
    assert validate_design_brief(doc)["status"] == "INCOMPLETE"
    req["confirmation"] = "not_applicable"
    assert validate_design_brief(doc)["status"] == "VALID"
    doc["site"]["constraints"]["value"] = ["cannot coexist with not_applicable"]
    assert "VALUE_STATUS_CONFLICT" in codes(validate_design_brief(doc))


@pytest.mark.parametrize("field,value", [("floor_id", "F9"), ("quantity", 0), ("quantity", True)])
def test_invalid_rooms(field, value):
    doc = valid_brief()
    doc["building"]["rooms"][0][field] = value
    assert validate_design_brief(doc)["status"] == "INVALID"


@pytest.mark.parametrize("collection", ["rooms", "floors"])
def test_duplicate_identifiers(collection):
    doc = valid_brief()
    doc["building"][collection].append(deepcopy(doc["building"][collection][0]))
    assert "DUPLICATE_ID" in codes(validate_design_brief(doc))


def test_duplicate_requirement_and_unknown_reference():
    doc = valid_brief()
    doc["requirements"].append(deepcopy(doc["requirements"][0]))
    assert "DUPLICATE_ID" in codes(validate_design_brief(doc))
    doc = valid_brief()
    doc["building"]["rooms"][0]["requirement_id"] = "MISSING"
    assert "UNKNOWN_REQUIREMENT" in codes(validate_design_brief(doc))


def test_floor_count_conflict():
    doc = valid_brief()
    doc["building"]["floors"].pop()
    assert "STOREY_COUNT_CONFLICT" in codes(validate_design_brief(doc))


@pytest.mark.parametrize("area", [{"unit": "m2", "min": 11, "max": 10},
                                 {"unit": "m2", "min": 11, "target": 10},
                                 {"unit": "m2", "max": 9, "target": 10},
                                 {"unit": "m2"}, {"unit": "m2", "target": 0},
                                 {"unit": "ft2", "target": 10}])
def test_impossible_or_ambiguous_area(area):
    doc = valid_brief()
    doc["building"]["rooms"][0]["area"] = area
    assert validate_design_brief(doc)["status"] == "INVALID"


def test_assumptions_cannot_be_confirmed():
    doc = valid_brief()
    doc["requirements"][0]["type"] = "assumption"
    assert "ASSUMPTION_STATUS" in codes(validate_design_brief(doc))
    doc["requirements"][0]["confirmation"] = "unconfirmed"
    assert validate_design_brief(doc)["status"] == "INCOMPLETE"


def test_unsupported_fields_rejected():
    doc = valid_brief()
    doc["building"]["minimum_stair_width_from_llm"] = 900
    assert "SCHEMA" in codes(validate_design_brief(doc))


def test_contradictory_hard_adjacency_and_soft_preference():
    doc = valid_brief()
    add_relationship(doc)
    row = add_relationship(doc, "REL2", relation="separate")
    assert "RELATION_CONFLICT" in codes(validate_design_brief(doc))
    row["strength"] = "soft"
    report = validate_design_brief(doc)
    assert not report["errors"]
    assert "RELATION_CONFLICT" in codes(report, "warnings")


def test_adjacency_cross_floor_and_hard_governance():
    doc = valid_brief()
    row = add_relationship(doc)
    doc["building"]["rooms"][1]["floor_id"] = "F2"
    assert "ADJACENCY_FLOOR_CONFLICT" in codes(validate_design_brief(doc))
    doc["requirements"][-1]["type"] = "preference"
    assert "HARD_REQUIREMENT_UNCONFIRMED" in codes(validate_design_brief(doc))
    row["room_ids"] = ["BED", "BAD"]
    assert "UNKNOWN_ROOM" in codes(validate_design_brief(doc))


def test_excluded_room_conflict():
    doc = valid_brief()
    add_requirement(doc, "REQ-NO-BED")
    doc["building"]["excluded_room_types"] = [
        {"room_type": "bedroom", "requirement_id": "REQ-NO-BED", "strength": "hard"}]
    assert "ROOM_EXCLUSION_CONFLICT" in codes(validate_design_brief(doc))


def test_reference_is_not_loaded_or_trusted_as_geometry():
    doc = valid_brief()
    del doc["site"]["dimensions"]
    doc["site"]["geometry_ref"] = {"requirement_id": "REQ-LOT", "value": "customer.dwg"}
    report = validate_design_brief(doc)
    assert "GEOMETRY_REFERENCE_UNRESOLVED" in codes(report, "missing_information")


def test_numeric_overflow_and_resource_guard():
    doc = valid_brief()
    doc["site"]["dimensions"]["value"].update(width=1e308, length=1e308)
    assert "NUMERIC_RANGE" in codes(validate_design_brief(doc))
    doc = valid_brief()
    doc["building"]["rooms"][0]["quantity"] = 10001
    assert "RESOURCE_LIMIT" in codes(validate_design_brief(doc))


def test_multistorey_stairs_cannot_be_not_applicable():
    doc = valid_brief()
    doc["building"]["stairs"]["value"] = None
    next(r for r in doc["requirements"] if r["id"] == "Q-STAIR")["confirmation"] = "not_applicable"
    assert "MULTISTOREY_CIRCULATION" in codes(validate_design_brief(doc))


def test_model_copies_input_and_rejects_invalid_brief():
    doc = valid_brief()
    model = DesignBrief.from_dict(doc)
    doc["project"]["name"] = "changed later"
    assert model.data["project"]["name"] != doc["project"]["name"]
    assert model.report()["status"] == "VALID"
    with pytest.raises(ValueError, match="Invalid design brief"):
        DesignBrief.from_dict({})


@pytest.mark.parametrize("value", [[], None, 0, "brief"])
def test_non_object_inputs(value):
    assert validate_design_brief(value)["status"] == "INVALID"


def test_relationship_expansion_resource_limit():
    doc = valid_brief()
    doc["building"]["rooms"][0]["quantity"] = 400
    doc["building"]["rooms"][1]["quantity"] = 400
    add_relationship(doc, pair=["BED", "LIVING"])
    assert "RESOURCE_LIMIT" in codes(validate_design_brief(doc))


def test_unverified_measurements_block_planning():
    doc = valid_brief()
    add_requirement(doc, "REQ-VERIFY")
    doc["site"]["unverified_measurements"] = {
        "requirement_id": "REQ-VERIFY", "value": ["Boundary survey pending"]}
    assert "MEASUREMENTS_UNVERIFIED" in codes(validate_design_brief(doc), "missing_information")


def test_missing_sections_are_incomplete_not_invalid():
    doc = valid_brief()
    for section in ("site", "building", "client"):
        del doc[section]
    assert validate_design_brief(doc)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("bearing,valid", [(0, True), (359.999, True), (360, False), (-1, False)])
def test_bearing_boundaries(bearing, valid):
    doc = valid_brief()
    doc["site"]["north_degrees"]["value"] = bearing
    assert (validate_design_brief(doc)["status"] == "VALID") is valid


def test_equal_positive_area_bounds_allowed():
    doc = valid_brief()
    doc["building"]["rooms"][0]["area"] = {"unit": "m2", "min": 10, "max": 10, "target": 10}
    assert validate_design_brief(doc)["status"] == "VALID"
