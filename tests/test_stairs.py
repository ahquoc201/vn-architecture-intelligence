"""Explicit envelopes and entry/exit openings, without claiming full stair design."""

from copy import deepcopy
import pytest

from circulation_fixtures import multi_floor, review_events, polygon
from vnai.stairs import validate_stairs
from vnai.architectural_review import architectural_review


def codes(report):
    return {r["code"] for r in report["errors"] + report["missing_information"]}


def test_two_floor_graph_connected_but_stair_walkability_not_verified():
    spec = multi_floor()
    before = deepcopy(spec)
    stair = validate_stairs(spec)
    assert stair["status"] == "VALID" and stair["stair_results"][0]["graph_eligible"]
    assert (
        stair["stair_results"][0]["rise_m"] == 3
        and stair["stair_results"][0]["alignment_status"] == "VALID"
    )
    assert stair["technical_stair_design"] == "NOT_EVALUATED"
    report = architectural_review(spec)
    assert (
        report["graph_status"] == "GRAPH_CONNECTED"
        and report["physical_circulation_status"] == "NOT_VERIFIED"
    )
    assert "STAIR_WALKING_GEOMETRY_NOT_EVALUATED" in codes(report)
    assert spec == before


@pytest.mark.parametrize("remove", ["point", "opening_id"])
def test_missing_endpoint_data_remains_incomplete(remove):
    spec = multi_floor()
    spec["stairs"][0]["destination"].pop(remove)
    review_events(spec)
    report = validate_stairs(spec)
    assert report["status"] == "INCOMPLETE" and "STAIR_ENTRY_EXIT_REQUIRED" in codes(report)
    assert not report["stair_results"][0]["graph_eligible"]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("floor_id", "BAD", "STAIR_ENVELOPE_REFERENCE"),
        ("stairwell_id", "BAD", "STAIR_ENVELOPE_REFERENCE"),
        ("space_id", "UNKNOWN", "STAIR_SPACE_REFERENCE"),
        ("opening_id", "ENTRANCE", "STAIR_OPENING_REFERENCE"),
        ("point", [2, 2], "STAIR_CONNECTION_POINT"),
    ],
)
def test_bad_stair_references(field, value, code):
    spec = multi_floor()
    spec["stairs"][0]["destination"][field] = value
    review_events(spec)
    report = validate_stairs(spec)
    assert code in codes(report) and not report["stair_results"][0]["graph_eligible"]


def test_direction_must_match_supplied_elevations():
    spec = multi_floor()
    spec["stairs"][0]["direction"] = "down"
    review_events(spec)
    assert "STAIR_DIRECTION" in codes(validate_stairs(spec))


def test_missing_elevations_are_unknown_not_invented():
    spec = multi_floor()
    for f in spec["candidate"]["geometry"]["floors"]:
        f.pop("elevation_m")
    from circulation_fixtures import selection

    selection(spec)
    review_events(spec)
    report = validate_stairs(spec)
    assert report["status"] == "INCOMPLETE" and report["stair_results"][0]["rise_m"] is None
    assert "STAIR_ELEVATIONS_REQUIRED" in codes(report)


def test_stair_box_collision_with_known_fixed_object():
    spec = multi_floor()
    spec["fixed_obstacles"] = [
        polygon(spec, "COLUMN", [[0.2, 1], [0.4, 1], [0.4, 1.2], [0.2, 1.2]], kind="other")
    ]
    review_events(spec)
    assert "STAIR_FIXED_COLLISION" in codes(validate_stairs(spec))


def test_duplicate_stair_ids_do_not_leave_a_verified_edge():
    spec = multi_floor()
    spec["stairs"].append(deepcopy(spec["stairs"][0]))
    review_events(spec)
    report = validate_stairs(spec)
    assert "DUPLICATE_STAIR_ID" in codes(report)
    assert not any(s["graph_eligible"] for s in report["stair_results"])


def test_proposed_stair_connection_is_not_promoted():
    spec = multi_floor()
    spec["stairs"][0]["confirmation"] = "proposed"
    review_events(spec)
    assert not validate_stairs(spec)["stair_results"][0]["graph_eligible"]


def test_actual_landing_nodes_are_connected_not_assumed():
    from circulation_fixtures import landing_stairs

    spec = landing_stairs()
    report = validate_stairs(spec)
    assert report["status"] == "VALID", report["errors"]
    assert report["stair_results"][0]["graph_eligible"]
    overall = architectural_review(spec)
    assert overall["graph_status"] == "GRAPH_CONNECTED"
    assert overall["physical_circulation_status"] == "NOT_VERIFIED"


def test_invalid_landing_reference_is_explicit():
    spec = multi_floor()
    spec["stairs"][0]["source"]["landing_id"] = "BED:1"
    review_events(spec)
    assert "STAIR_LANDING_REFERENCE" in codes(validate_stairs(spec))


def test_alignment_requirement_and_units_are_enforced():
    spec = multi_floor()
    candidate = spec["candidate"]
    row = next(p for p in candidate["geometry"]["polygons"] if p["id"] == "SW-F2")
    row["exterior"] = [[0, 0], [1, 0], [1, 3], [0, 3]]
    spec["openings"][-1]["host"]["end"] = [1, 3]
    from circulation_fixtures import selection

    selection(spec)
    review_events(spec)
    assert "STAIR_ALIGNMENT" in codes(validate_stairs(spec))
    spec = multi_floor()
    spec["stairs"][0]["units"] = "mm"
    review_events(spec)
    assert "COORDINATE_MISMATCH" in codes(validate_stairs(spec))
