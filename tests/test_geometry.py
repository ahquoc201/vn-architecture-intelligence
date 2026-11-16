import json
from pathlib import Path

import pytest

from vnai.geometry import polygon_mm
from vnai.review import review_plan

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((ROOT / "examples" / "townhouse_sample.json").read_text(encoding="utf-8"))


def test_demo_area_and_separate_reviews():
    report = review_plan(sample())
    assert report["geometry"]["site_area_m2"] == 80
    assert [room["area_m2"] for room in report["geometry"]["level_room_areas"][0]["room_areas"]] == [22, 20, 20]
    assert report["site_orientation"]["frontage_facing_octant"] == "S"
    assert report["fengshui_advisory"]["status"] == "NOT_EVALUATED"
    assert report["standards_review"]["status"] == "NOT_EVALUATED"
    assert report["findings"] == []


def test_room_target_delta_is_warning_not_violation():
    plan = sample()
    plan["levels"][0]["rooms"][0]["target_area_m2"] = 15
    report = review_plan(plan)
    assert "ROOM_AREA_TARGET_DELTA" in [f["code"] for f in report["findings"]]


def test_overlap_and_outside_site_flags():
    plan = sample()
    plan["levels"][0]["rooms"][1]["polygon_mm"] = [[3000, 0], [5000, 0], [5000, 6000], [3000, 6000]]
    report = review_plan(plan)
    codes = {f["code"] for f in report["findings"]}
    assert "ROOM_OVERLAP" in codes
    assert "ROOM_OUTSIDE_SITE" in codes


def test_invalid_bowtie():
    with pytest.raises(ValueError, match="invalid polygon"):
        polygon_mm([[0, 0], [4, 4], [4, 0], [0, 4]], "bowtie")


def test_invalid_units():
    plan = sample()
    plan["units"] = "m"
    with pytest.raises(ValueError, match="millimetres"):
        review_plan(plan)


def test_missing_bearing_reports_needs_data():
    plan = sample()
    del plan["site"]["frontage_facing_degrees"]
    report = review_plan(plan)
    assert "FRONTAGE_BEARING_MISSING" in [f["code"] for f in report["findings"]]


def test_room_duplicate_id_rejected():
    plan = sample()
    plan["levels"][0]["rooms"][1]["id"] = plan["levels"][0]["rooms"][0]["id"]
    with pytest.raises(ValueError, match="Duplicate room"):
        review_plan(plan)
