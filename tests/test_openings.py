"""Boundary-hosted doors, supplied motion and bounded local clearance."""

from copy import deepcopy
from math import pi

import pytest
from shapely.geometry import Polygon

from circulation_fixtures import two_rooms, corridor, polygon, review_events
from vnai.openings import validate_openings, swing_sector
from vnai.circulation import analyze_circulation
from vnai.architectural_review import architectural_review


def codes(report):
    return {r["code"] for r in report["errors"] + report["missing_information"]}


def test_explicit_door_creates_graph_edge_not_full_walking_clearance():
    spec = two_rooms()
    report = validate_openings(spec)
    assert report["status"] == "INCOMPLETE" and not report["errors"]
    assert all(r["graph_eligible"] for r in report["opening_results"])
    assert all(r["physical_state"] == "NOT_VERIFIED" for r in report["opening_results"])
    graph = analyze_circulation(spec)
    assert graph["graph_status"] == "GRAPH_CONNECTED"
    assert architectural_review(spec)["physical_circulation_status"] == "NOT_VERIFIED"


def test_shared_boundary_without_door_does_not_generate_edge():
    spec = two_rooms()
    spec["openings"] = spec["openings"][:1]
    review_events(spec)
    graph = analyze_circulation(spec)
    assert len(graph["edges"]) == 1 and graph["edges"][0]["id"] == "ENTRANCE"
    assert graph["room_access"]["BED:1"]["status"] == "BLOCKED"
    assert graph["room_access"]["LIVING:1"]["graph_reachable"]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("start", [-1, 2], "OPENING_OUTSIDE_HOST"),
        ("clear_width", 2, "OPENING_WIDTH"),
        ("floor_id", "BAD", "OPENING_FLOOR"),
        ("frame_id", "BAD", "COORDINATE_MISMATCH"),
        ("units", "mm", "COORDINATE_MISMATCH"),
        ("space_ids", ["BED:1", "UNKNOWN"], "OPENING_SPACE"),
    ],
)
def test_invalid_openings(field, value, code):
    spec = two_rooms()
    spec["openings"][1][field] = value
    review_events(spec)
    result = validate_openings(spec)
    assert code in codes(result)
    assert not result["opening_results"][1]["graph_eligible"]


def test_host_itself_must_match_both_boundaries():
    spec = two_rooms()
    spec["openings"][1]["host"] = {"start": [0, 1], "end": [4, 1]}
    review_events(spec)
    assert "HOST_BOUNDARY_MISMATCH" in codes(validate_openings(spec))


@pytest.mark.parametrize("width", [0, -1, True, float("nan")])
def test_nonpositive_or_invalid_width(width):
    spec = two_rooms()
    spec["openings"][1]["clear_width"] = width
    assert validate_openings(spec)["status"] == "INVALID"


def test_duplicate_and_overlapping_openings_are_not_silently_merged():
    spec = two_rooms()
    spec["openings"].append(deepcopy(spec["openings"][1]))
    review_events(spec)
    report = validate_openings(spec)
    assert "DUPLICATE_OPENING_ID" in codes(report)
    assert not any(r["graph_eligible"] for r in report["opening_results"] if r["id"] == "DOOR")
    spec["openings"][-1]["id"] = "ANOTHER"
    review_events(spec)
    assert "OVERLAPPING_OPENINGS" in codes(validate_openings(spec))


def test_wrong_swing_direction_and_fixed_collision_are_reported():
    spec = two_rooms()
    spec["openings"][1]["swing"]["opens_into"] = "BED:1"
    review_events(spec)
    assert "SWING_OUTSIDE_SPACE" in codes(validate_openings(spec))
    spec = two_rooms()
    spec["fixed_obstacles"] = [
        polygon(spec, "COLUMN", [[1.2, 2.2], [1.4, 2.2], [1.4, 2.4], [1.2, 2.4]], kind="other")
    ]
    review_events(spec)
    result = validate_openings(spec)
    assert "SWING_FIXED_COLLISION" in codes(result)
    assert result["opening_results"][1]["physical_state"] == "BLOCKED"
    overall = architectural_review(spec)
    assert (
        overall["graph_status"] == "GRAPH_CONNECTED"
        and overall["physical_circulation_status"] == "BLOCKED"
    )


def test_conservative_sector_encloses_ideal_quarter_disc_without_repair():
    sector = swing_sector((0, 0), (1, 0), "start", "ccw")
    assert sector.is_valid and sector.area >= pi / 4
    assert sector.bounds[0] >= 0 and sector.bounds[1] >= 0
    assert sector.covers(Polygon([[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]]))
    mirrored = swing_sector((0, 0), (0, 1), "start", "ccw")
    assert mirrored.bounds[2] == 0  # Exact terminal point, not cos(pi/2) noise.


def test_proposed_opening_does_not_establish_verified_edge():
    spec = two_rooms()
    spec["openings"][1]["confirmation"] = "proposed"
    review_events(spec)
    result = validate_openings(spec)
    assert (
        "OPENING_UNCONFIRMED" in codes(result)
        and not result["opening_results"][1]["graph_eligible"]
    )


def test_sliding_model_requires_explicit_motion_envelope():
    spec = two_rooms()
    door = spec["openings"][1]
    door["door_type"] = "sliding"
    door.pop("swing")
    review_events(spec)
    assert "SLIDING_ENVELOPE_REQUIRED" in codes(validate_openings(spec))
    spec["clearance_regions"].append(
        polygon(spec, "SLIDE", [[0.5, 1.9], [2.5, 1.9], [2.5, 2.1], [0.5, 2.1]])
    )
    door["sliding_envelope_id"] = "SLIDE"
    review_events(spec)
    result = validate_openings(spec)
    assert not result["errors"] and result["opening_results"][1]["graph_eligible"]


def test_missing_obstacle_inventory_never_becomes_clearance_pass():
    spec = corridor(True)
    spec.pop("fixed_obstacles_complete")
    review_events(spec)
    result = validate_openings(spec)
    assert result["status"] == "INCOMPLETE"
    assert all(
        r["physical_state"] != "GEOMETRICALLY_TRAVERSABLE" for r in result["opening_results"]
    )


def test_no_assumed_positive_normative_minimum_width():
    spec = two_rooms()
    spec["openings"][1]["clear_width"] = 0.01
    review_events(spec)
    report = validate_openings(spec)
    assert report["opening_results"][1]["graph_eligible"]
    assert "OPENING_WIDTH" not in codes(report)  # A clinical/code minimum is never invented.


def test_distinct_door_spans_can_have_conflicting_swing_envelopes():
    spec = two_rooms()
    spec["openings"][0]["end"] = [2.5, 4]
    spec["openings"][0]["clear_width"] = 1.5
    review_events(spec)
    report = validate_openings(spec)
    assert "SWING_ENVELOPE_CONFLICT" in codes(report)
    assert all(
        r["graph_eligible"] and r["physical_state"] == "BLOCKED" for r in report["opening_results"]
    )
