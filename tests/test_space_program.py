"""Determinism, traceability and independent area quantities."""

from copy import deepcopy

from design_fixtures import add_relationship, incomplete_brief, valid_brief
from vnai.space_program import build_space_program


def test_example_has_seven_rooms_without_invented_assignments():
    doc = incomplete_brief()
    snapshot = deepcopy(doc)
    program = build_space_program(doc)
    assert len(program["rooms"]) == 7
    assert [r["id"] for r in program["rooms"][:3]] == ["BED:1", "BED:2", "BED:3"]
    assert all(r["floor_id"] is None and r["requested_area_m2"] is None for r in program["rooms"])
    assert program["areas"]["lot_area_m2"] == 80
    assert program["areas"]["gross_floor_area_m2"] is None
    assert program["areas"]["building_footprint_m2"] is None
    assert program["areas"]["unallocated_area_m2"] is None
    assert program["areas"]["requested_net_room_area_m2"]["target"]["total_m2"] is None
    assert program["status"] == "INCOMPLETE"
    assert doc == snapshot
    assert program == build_space_program(doc)
    assert not program["cad_writes_permitted"] and not program["layout_generated"]


def test_areas_units_coverage_and_traceability():
    doc = valid_brief()
    doc["site"]["dimensions"]["value"].update(width=4000, length=20000, unit="mm")
    doc["building"]["rooms"][0]["area"] = {"target": 10000000, "unit": "mm2"}
    program = build_space_program(doc)
    assert program["areas"]["lot_area_m2"] == 80
    assert program["areas"]["building_footprint_m2"]["target"] == 60
    totals = program["areas"]["requested_net_room_area_m2"]
    assert totals["target"] == {"known_sum_m2": 70, "covered_room_count": 7,
                                "complete": True, "total_m2": 70}
    assert totals["min"]["total_m2"] is None  # target does not invent a lower bound
    assert program["rooms"][0]["requirement_id"] == "REQ-BED"
    assert program["rooms"][0]["governance"]["origin"] == "synthetic_client_brief"


def test_partial_area_totals_and_ranges():
    doc = valid_brief()
    doc["building"]["rooms"][0]["area"] = {"min": 8, "max": 12, "unit": "m2"}
    program = build_space_program(doc)
    totals = program["areas"]["requested_net_room_area_m2"]
    assert totals["target"]["total_m2"] is None
    assert totals["target"]["known_sum_m2"] == 40
    assert totals["min"]["known_sum_m2"] == 24
    assert totals["max"]["known_sum_m2"] == 36
    assert program["geometric_feasibility"] == "NOT_EVALUATED"


def test_relationships_expand_instances_and_preserve_strength():
    doc = valid_brief()
    add_relationship(doc, pair=["BED", "LIVING"], strength="soft")
    program = build_space_program(doc)
    rel = program["relationships"][0]
    assert rel["instance_pairs"] == [["BED:1", "LIVING:1"], ["BED:2", "LIVING:1"],
                                     ["BED:3", "LIVING:1"]]
    assert rel["strength"] == "soft" and rel["requirement_id"] == "REQ-REL1"


def test_invalid_input_has_no_partial_program():
    doc = valid_brief()
    doc["building"]["rooms"][0]["floor_id"] = "BAD"
    program = build_space_program(doc)
    assert program["status"] == "INVALID"
    assert program["rooms"] == [] and program["areas"] is None


def test_unconfirmed_area_not_counted_as_confirmed_total():
    doc = valid_brief()
    doc["requirements"][0]["confirmation"] = "unconfirmed"
    program = build_space_program(doc)
    assert program["areas"]["requested_net_room_area_m2"]["target"]["total_m2"] is None
    assert not program["rooms"][0]["confirmed"]


def test_gfa_is_supplied_independently_not_footprint_times_storeys():
    from design_fixtures import add_requirement

    doc = valid_brief()
    add_requirement(doc, "REQ-GFA")
    doc["building"]["gross_floor_area"] = {
        "requirement_id": "REQ-GFA", "value": {"min": 130, "max": 160, "unit": "m2"}}
    program = build_space_program(doc)
    assert program["areas"]["gross_floor_area_m2"] == {
        "requirement_id": "REQ-GFA", "min": 130, "max": 160}
    assert program["areas"]["unallocated_area_m2"] is None
