"""Candidate schemas stay valid and current reports are version stamped."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from vnai import __version__
from vnai.floorplan import generate_floorplans
from floorplan_fixtures import synthetic_spec


@pytest.mark.parametrize("name", ["floorplan-input", "floorplan-candidate"])
def test_schema_is_valid(name):
    path = Path(__file__).resolve().parents[1] / "knowledge/architecture" / (name + ".schema.json")
    Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_current_engine_stamp_is_not_historical_golden_metadata():
    report = generate_floorplans(synthetic_spec())
    assert report["engine_version"] == __version__ == "0.1.7"
    assert all(
        c["hard_validation"]["spatial_report"]["engine_version"] == __version__
        for c in report["candidates"]
    )
