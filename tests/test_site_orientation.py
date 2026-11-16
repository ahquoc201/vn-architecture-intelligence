"""R1 Batch 002: geomagnetic reference guardrails and compass-sector tests."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from vnai.cli import main
from vnai.site_orientation import (
    bearing_from_vectors,
    direction_with_uncertainty,
    review_site_orientation,
)
from vnai.source_registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "examples/townhouse_orientation.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("outward", "expected"),
    [([0, 1], 0), ([1, 0], 90), ([0, -1], 180), ([-1, 0], 270)],
)
def test_cardinals_from_true_north(outward, expected):
    assert bearing_from_vectors([0, 1], outward) == expected


def test_arbitrary_drawing_rotation_and_vector_scale():
    assert bearing_from_vectors([3, 0], [0, -7]) == 90  # north is +X, east is -Y
    assert bearing_from_vectors([2, 2], [2, 2]) == 0
    assert bearing_from_vectors([1, 1], [-1, -1]) == 180


@pytest.mark.parametrize("bearing", [22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5])
def test_exact_octant_boundary_is_ambiguous(bearing):
    result = direction_with_uncertainty(bearing, 0)
    assert result["status"] == "AMBIGUOUS_BOUNDARY"
    assert len(result["possible_directions"]) == 2
    assert result["direction"] is None


def test_uncertainty_overlapping_boundary_and_unambiguous():
    assert direction_with_uncertainty(22.4, 0.2)["possible_directions"] == ["N", "NE"]
    assert direction_with_uncertainty(22.6, 0.2)["possible_directions"] == ["N", "NE"]
    assert direction_with_uncertainty(22.4, 0)["direction"] == "N"
    assert direction_with_uncertainty(22.6, 0)["direction"] == "NE"
    assert direction_with_uncertainty(-90, 1)["direction"] == "W"
    assert direction_with_uncertainty(450, 1)["direction"] == "E"
    assert direction_with_uncertainty(337.5, 0)["possible_directions"] == ["NW", "N"]


@pytest.mark.parametrize("bad", [True, "90", None, -1, 22.5, float("nan"), float("inf")])
def test_uncertainty_validation(bad):
    with pytest.raises(ValueError):
        direction_with_uncertainty(90, bad)


@pytest.mark.parametrize("bad", [True, "90", float("nan"), float("inf")])
def test_bearing_validation(bad):
    with pytest.raises(ValueError):
        direction_with_uncertainty(bad, 0)


@pytest.mark.parametrize("bad", [[0, 0], [float("nan"), 1], [True, 1], [1], "east"])
def test_vector_validation(bad):
    with pytest.raises(ValueError):
        bearing_from_vectors([0, 1], bad)


def test_large_finite_vectors_are_valid():
    assert bearing_from_vectors([0, 1], [1e308, 1e308]) == 45


def test_example_is_geometry_only_and_not_a_cad_write():
    result = review_site_orientation(EXAMPLE)
    assert result["status"] == "COMPUTED"
    assert result["bearing_degrees_clockwise_from_true_north"] == 180
    assert result["sector"]["direction"] == "S"
    assert result["fengshui"]["status"] == "NEEDS_SOURCE_REVIEW"
    assert result["fengshui"]["rules_applied"] == []
    assert result["technical_standards"]["status"] == "NOT_EVALUATED"
    assert result["cad_writes_permitted"] is False


@pytest.mark.parametrize("remove", ["north_vector_drawing_xy", "frontage_outward_vector_drawing_xy", "measurement_uncertainty_degrees"])
def test_missing_inputs_report_needs_data(remove):
    payload = deepcopy(EXAMPLE)
    del payload[remove]
    result = review_site_orientation(payload)
    assert result["status"] == "NEEDS_DATA"
    assert remove in result["missing_or_unconfirmed"]
    assert result["cad_writes_permitted"] is False


def test_magnetic_north_is_not_assumed_true_north():
    payload = deepcopy(EXAMPLE)
    payload["north_reference"] = "magnetic_north"
    result = review_site_orientation(payload)
    assert result["status"] == "NEEDS_DATA"
    assert "verified_true_north_conversion" in result["missing_or_unconfirmed"]


def test_outward_facing_must_be_explicit():
    payload = deepcopy(EXAMPLE)
    payload["facing_definition"] = "along_street"
    result = review_site_orientation(payload)
    assert "confirmed_frontage_outward_direction" in result["missing_or_unconfirmed"]


def test_unknown_fields_are_rejected():
    with pytest.raises(ValueError, match="Unknown orientation fields"):
        review_site_orientation({**EXAMPLE, "kua_number": 9})


def test_cli_orientation_json_output(tmp_path, capsys):
    target = tmp_path / "result.json"
    assert main(["fengshui", "orientation", str(ROOT / "examples/townhouse_orientation.json"), "--out", str(target)]) == 0
    assert "no feng shui approval" in capsys.readouterr().out
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["bearing_degrees_clockwise_from_true_north"] == 180
    assert report["cad_writes_permitted"] is False


def test_edition_matrix_uses_known_sources_but_approves_no_rules():
    data = yaml.safe_load((ROOT / "research/editions/r1-batch002.yaml").read_text(encoding="utf-8"))
    catalog = load_registry(ROOT / "sources/bibliography.yaml")
    known = {entry["id"] for entry in catalog["sources"]}
    assert data["schema_version"] == 1
    assert len(data["entries"]) == 2
    for item in data["entries"]:
        assert item["source_id"] in known
        assert item["edition_confirmed"] is False
        assert item["primary_text_reviewed"] is False
        assert item["reviewer_approved"] is False
        assert item["executable_rules"] is False


def test_json_schema_is_valid_json_with_expected_fields():
    schema = json.loads((ROOT / "knowledge/fengshui/orientation-input.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["north_reference"]["const"] == "true_north"
    assert schema["properties"]["facing_definition"]["const"] == "building_to_street"
    assert schema["additionalProperties"] is False
