"""Topology, dimensional bookkeeping, tolerances and explicit geometric relationships."""

from copy import deepcopy

import pytest

from batch005_fixtures import fixture, resign_geometry, resign_zoning
from vnai.spatial import geometry_digest, validate_geometry


def codes(report, bucket="errors"):
    return {i["code"] for i in report[bucket]}


def test_valid_geometry_accounts_for_areas_without_buildability_claim():
    doc = fixture("geometry-valid")
    before = deepcopy(doc)
    report = validate_geometry(doc)
    assert report["status"] == "VALID", report
    assert report["site_area_m2"] == 80
    assert report["footprint_area_m2"] == 72
    assert report["floor_areas"][0]["net_room_polygon_sum_m2"] == 16
    assert report["floor_areas"][0]["geometric_residual_m2"] == 56
    assert report["gross_floor_area_m2"] is None
    assert report["buildability"] == "NOT_EVALUATED"
    assert not report["cad_writes_permitted"]
    assert doc == before


def test_shared_boundary_not_area_overlap_and_different_floors_never_overlap():
    assert "ROOM_OVERLAP" not in codes(validate_geometry(fixture("geometry-valid")))
    doc = fixture("geometry-multistorey")
    assert doc["polygons"][2]["exterior"] == doc["polygons"][3]["exterior"]
    assert validate_geometry(doc)["status"] == "VALID"


@pytest.mark.parametrize(
    "name,code",
    [
        ("geometry-overlap", "ROOM_OVERLAP"),
        ("geometry-outside-footprint", "OUTSIDE_ENVELOPE"),
        ("geometry-invalid-polygon", "INVALID_POLYGON"),
    ],
)
def test_meaningful_geometry_conflicts(name, code):
    report = validate_geometry(fixture(name))
    assert report["status"] == "INVALID" and code in codes(report)


@pytest.mark.parametrize("offset,valid", [(0, True), (0.0005, True), (0.002, False)])
def test_explicit_boundary_tolerance(offset, valid):
    doc = fixture("geometry-valid")
    doc["polygons"][2]["exterior"] = [[-offset, 5], [2, 5], [2, 9], [-offset, 9]]
    report = validate_geometry(resign_geometry(doc))
    assert (report["status"] == "VALID") is valid
    if 0 < offset < 0.001:
        assert "BOUNDARY_WITHIN_TOLERANCE" in codes(report, "warnings")


def test_positive_overlap_tolerance_is_distinct_from_shared_boundary():
    doc = fixture("geometry-valid")
    doc["polygons"][3]["exterior"] = [[1.9999999, 0], [4, 0], [4, 4], [1.9999999, 4]]
    report = validate_geometry(resign_geometry(doc))
    assert not report["errors"]
    assert "OVERLAP_WITHIN_TOLERANCE" in codes(report, "warnings")
    doc["tolerances"]["overlap_m2"] = 0
    assert "ROOM_OVERLAP" in codes(validate_geometry(resign_geometry(doc)))


def test_millimetre_units_preserve_area():
    doc = fixture("geometry-valid")
    doc["units"] = "mm"
    for row in doc["polygons"]:
        row["units"] = "mm"
        row["exterior"] = [[x * 1000, y * 1000] for x, y in row["exterior"]]
    report = validate_geometry(resign_geometry(doc))
    assert report["status"] == "VALID" and report["site_area_m2"] == 80


@pytest.mark.parametrize("key,value", [("units", "mm"), ("frame_id", "OTHER")])
def test_no_silent_coordinate_conversion(key, value):
    doc = fixture("geometry-valid")
    doc["polygons"][2][key] = value
    assert "COORDINATE_MISMATCH" in codes(validate_geometry(resign_geometry(doc)))


def test_nonrectangular_site_and_polygon_hole_area():
    doc = fixture("geometry-valid")
    doc["polygons"] = doc["polygons"][:1]
    doc["polygons"][0]["exterior"] = [[0, 0], [4, 0], [4, 4], [2, 4], [2, 8], [0, 8]]
    doc["polygons"][0]["holes"] = [[[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5]]]
    report = validate_geometry(resign_geometry(doc))
    assert report["status"] == "VALID"
    assert report["site_area_m2"] == 23


def test_rooms_in_holes_are_outside_envelope():
    doc = fixture("geometry-valid")
    doc["polygons"][1]["holes"] = [[[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5]]]
    assert "OUTSIDE_ENVELOPE" in codes(validate_geometry(resign_geometry(doc)))


def test_wrong_winding_warns_and_is_not_repaired():
    doc = fixture("geometry-valid")
    doc["polygons"][2]["exterior"].reverse()
    before = deepcopy(doc)
    report = validate_geometry(resign_geometry(doc))
    assert "RING_ORIENTATION" in codes(report, "warnings")
    assert doc["polygons"][2]["exterior"] == before["polygons"][2]["exterior"]


@pytest.mark.parametrize("points", [[[0, 0], [1, 0], [2, 0]], [[0, 0], [0.0001, 0], [0, 0.0001]]])
def test_zero_near_zero_area(points):
    doc = fixture("geometry-valid")
    doc["polygons"][2]["exterior"] = points
    assert "NEAR_ZERO_AREA" in codes(validate_geometry(resign_geometry(doc)))


def test_duplicate_ids_invalid_floor_and_ownership():
    doc = fixture("geometry-valid")
    doc["polygons"][2]["id"] = "SITE"
    assert "DUPLICATE_GEOMETRY_ID" in codes(validate_geometry(resign_geometry(doc)))
    doc = fixture("geometry-valid")
    doc["polygons"][2]["floor_id"] = "UNKNOWN"
    assert "UNKNOWN_FLOOR" in codes(validate_geometry(resign_geometry(doc)))
    doc = fixture("geometry-valid")
    doc["polygons"][2]["owner_id"] = "ROOM-A"
    assert "GEOMETRY_OWNER" in codes(validate_geometry(resign_geometry(doc)))


def test_stale_envelope_approval_never_survives_coordinate_edits():
    doc = fixture("geometry-valid")
    doc["polygons"][2]["exterior"][0][0] = 0.1
    assert "GEOMETRY_APPROVAL_RECORD" in codes(validate_geometry(doc))


def test_point_segment_contracts_and_future_refs():
    doc = fixture("geometry-valid")
    doc["points"] = [
        {"id": "P1", "owner_id": "F1", "xy": [0, 0]},
        {"id": "P2", "owner_id": "F1", "xy": [1, 0]},
    ]
    doc["segments"] = [{"id": "S1", "owner_id": "F1", "start": "P1", "end": "P2"}]
    doc["polygons"][2]["wall_refs"] = ["future-wall"]
    assert validate_geometry(resign_geometry(doc))["status"] == "VALID"
    doc["points"][1]["xy"] = [0, 0]
    assert "ZERO_LENGTH_SEGMENT" in codes(validate_geometry(resign_geometry(doc)))
    doc["segments"][0]["end"] = "BAD"
    assert "SEGMENT_REFERENCE" in codes(validate_geometry(resign_geometry(doc)))


def test_intentional_overlap_requires_explicit_current_approval():
    doc = fixture("geometry-overlap")
    rel = {
        "id": "INTENTIONAL",
        "geometry_ids": ["ROOM-A", "ROOM-B"],
        "kind": "intentional_overlap",
        "requirement_id": "REQ-A",
        "provenance": "Synthetic test",
        "rationale": "Shared functional space",
        "status": "proposed",
    }
    doc["relationships"].append(rel)
    assert "ROOM_OVERLAP" in codes(validate_geometry(resign_geometry(doc)))
    rel["status"] = "approved"
    rel["approval"] = {
        "actor": "SYNTHETIC_TEST_ARCHITECT",
        "role": "architect",
        "recorded_at": "2026-11-18T00:00:00Z",
        "digest": geometry_digest(doc, rel),
    }
    report = validate_geometry(resign_geometry(doc))
    assert not report["errors"]
    assert "INTENTIONAL_OVERLAP" in codes(report, "diagnostics")
    assert report["floor_areas"][0]["net_room_polygon_sum_m2"] == 16
    assert report["floor_areas"][0]["net_room_polygon_union_m2"] == 12


def test_linked_zoning_program_targets_and_floor_conflicts():
    doc = fixture("geometry-linked-approved")
    report = validate_geometry(doc)
    assert report["status"] == "VALID" and report["architectural_approval"] == "APPROVED"
    doc["polygons"][2]["exterior"][2][1] = 2
    report = validate_geometry(resign_geometry(doc))
    assert "ROOM_AREA_TARGET_MISMATCH" in codes(report, "warnings")
    doc["polygons"][2]["floor_id"] = "F2"
    doc["polygons"][2]["owner_id"] = "F2"
    assert "ZONING_FLOOR_CONFLICT" in codes(validate_geometry(resign_geometry(doc)))


def test_missing_program_room_polygon_and_wrong_source_reference():
    doc = fixture("geometry-linked-approved")
    doc["polygons"].pop()
    assert "ROOM_GEOMETRY_MISSING" in codes(
        validate_geometry(resign_geometry(doc)), "missing_information"
    )
    doc["polygons"][2]["requirement_id"] = "BAD"
    assert "ROOM_TRACEABILITY" in codes(validate_geometry(resign_geometry(doc)))


def test_elevation_and_project_mismatch():
    doc = fixture("geometry-linked-approved")
    doc["zoning"]["floors"][0]["elevation"] = {"value": 1000, "unit": "mm"}
    doc["floors"][0]["elevation_m"] = 0
    resign_zoning(doc["zoning"])
    assert "ELEVATION_CONFLICT" in codes(validate_geometry(resign_geometry(doc)))


@pytest.mark.parametrize("field,value", [("schema_version", 2), ("units", "ft"), ("polygons", [])])
def test_schema_contract_invalid(field, value):
    doc = fixture("geometry-valid")
    doc[field] = value
    assert validate_geometry(doc)["status"] == "INVALID"


def test_unsupported_multipart_and_nonfinite_rejected():
    doc = fixture("geometry-valid")
    doc["polygons"][2]["multipart"] = []
    assert "SCHEMA" in codes(validate_geometry(doc))
    doc = fixture("geometry-valid")
    doc["polygons"][2]["exterior"][0][0] = float("nan")
    assert "NONFINITE_NUMBER" in codes(validate_geometry(doc))


def test_world_frame_needs_projected_crs_and_complete_transform():
    doc = fixture("geometry-valid")
    doc["frame"]["kind"] = "world"
    assert "WORLD_CRS_REQUIRED" in codes(validate_geometry(resign_geometry(doc)))
    doc["frame"]["world_crs"] = "Synthetic projected metric grid"
    assert validate_geometry(resign_geometry(doc))["status"] == "VALID"
    doc["frame"]["kind"] = "local_site"
    doc["frame"]["origin_world"] = [100, 200]
    assert "FRAME_TRANSFORM_INCOMPLETE" in codes(validate_geometry(resign_geometry(doc)))


def test_floor_outlines_are_checked_and_gfa_requires_all_floors():
    doc = fixture("geometry-valid")
    outline = deepcopy(doc["polygons"][1])
    outline.update(
        id="OUTLINE", role="floor_outline", owner_id="F1", floor_id="F1", status="proposed"
    )
    outline.pop("approval")
    doc["polygons"].append(outline)
    report = validate_geometry(resign_geometry(doc))
    assert report["status"] == "VALID"
    assert report["gross_floor_area_m2"] == 72
    outline["exterior"] = [[0, 0], [4, 0], [4, 19], [0, 19]]
    assert "OUTSIDE_ENVELOPE" in codes(validate_geometry(resign_geometry(doc)))


def test_polygon_hole_outside_shell_is_invalid_without_repair():
    doc = fixture("geometry-valid")
    doc["polygons"][2]["holes"] = [[[8, 8], [9, 8], [9, 9], [8, 9]]]
    assert "INVALID_POLYGON" in codes(validate_geometry(resign_geometry(doc)))


def test_approval_does_not_ignore_point_or_tolerance_changes():
    doc = fixture("geometry-valid")
    doc["tolerances"]["boundary_m"] = 1
    assert "GEOMETRY_APPROVAL_RECORD" in codes(validate_geometry(doc))
    doc = fixture("geometry-valid")
    doc["points"].append({"id": "P1", "owner_id": "F1", "xy": [0, 0]})
    assert "GEOMETRY_APPROVAL_RECORD" in codes(validate_geometry(doc))
