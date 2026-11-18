"""Units, explicit tolerances and independent report/schema invariants."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from circulation_fixtures import corridor, two_rooms, review_events, selection
from vnai.architectural_review import architectural_review
from vnai.openings import validate_openings


@pytest.mark.parametrize(
    "name",
    [
        "candidate-review",
        "opening",
        "stair-connection",
        "circulation-graph",
        "opening-result",
        "stair-result",
        "architectural-review",
    ],
)
def test_published_schemas_are_valid(name):
    path = Path(__file__).resolve().parents[1] / "knowledge/architecture" / (name + ".schema.json")
    Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_review_matches_candidate_coordinate_units_in_millimetres():
    spec = corridor(True)
    before = architectural_review(spec)
    candidate = spec["candidate"]
    candidate["parameters"]["grid_step"] *= 1000
    geometry = candidate["geometry"]
    geometry["units"] = "mm"
    for row in geometry["polygons"]:
        row["units"] = "mm"
        row["exterior"] = [[x * 1000, y * 1000] for x, y in row["exterior"]]
        row["holes"] = [[[x * 1000, y * 1000] for x, y in ring] for ring in row.get("holes", [])]
    for row in spec["clearance_regions"] + spec["fixed_obstacles"]:
        row["units"] = "mm"
        row["exterior"] = [[x * 1000, y * 1000] for x, y in row["exterior"]]
    for row in spec["openings"]:
        row["units"] = "mm"
        row["clear_width"] *= 1000
        for key in ("start", "end"):
            row[key] = [v * 1000 for v in row[key]]
        for key in ("start", "end"):
            row["host"][key] = [v * 1000 for v in row["host"][key]]
    for row in spec["passages"]:
        row["units"] = "mm"
        row["width"] *= 1000
        row["path"] = [[x * 1000, y * 1000] for x, y in row["path"]]
    selection(spec)
    review_events(spec)
    result = architectural_review(spec)
    assert result["status"] == "VALID", result["errors"]
    assert (
        result["physical_circulation_status"]
        == before["physical_circulation_status"]
        == "GEOMETRICALLY_TRAVERSABLE"
    )
    assert (
        result["clearance"]["room_physical_access"] == before["clearance"]["room_physical_access"]
    )


def test_boundary_offset_uses_declared_tolerance_without_snapping_input():
    spec = two_rooms()
    spec["candidate"]["geometry"]["tolerances"]["boundary_m"] = 0.001
    selection(spec)
    for key in ("start", "end"):
        spec["openings"][1]["host"][key][1] += 0.0005
    review_events(spec)
    original = deepcopy(spec)
    result = validate_openings(spec)
    assert result["opening_results"][1]["graph_eligible"]
    assert any(r["code"] == "HOST_WITHIN_BOUNDARY_TOLERANCE" for r in result["warnings"])
    assert spec == original
    spec["candidate"]["geometry"]["tolerances"]["boundary_m"] = 0
    selection(spec)
    review_events(spec)
    assert not validate_openings(spec)["opening_results"][1]["graph_eligible"]


def test_approved_record_does_not_turn_technical_compliance_into_pass():
    spec = review_events(corridor(True), ("SELECTED", "REVIEWED", "APPROVED"))
    report = architectural_review(spec)
    assert report["candidate_review"]["approval_record_valid"]
    assert report["architectural_approval"] == "APPROVED"
    assert report["technical_compliance"] == "NOT_EVALUATED" and not report["fully_verified"]
    assert not report["cad_writes_permitted"]
