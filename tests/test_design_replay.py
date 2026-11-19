"""Independent geometric replay, stale provenance and backwards compatibility."""

from copy import deepcopy

import pytest

from replay_fixtures import original, revised, changed_baseline, reserved_case
from vnai.contracts import canonical_digest, new_report, schema_check
from vnai.design_provenance import create_generation_provenance
from vnai.design_replay import validate_replay
from vnai.floorplan import generate_floorplans


@pytest.fixture(scope="module")
def origin():
    return original()


def test_original_provenance_traceability_and_no_mutation(origin):
    before = deepcopy(origin)
    result = validate_replay(origin)
    assert result["replay_status"] == "VERIFIED"
    assert result["candidate_digest"] == canonical_digest(origin["review"]["candidate"])
    assert result["specification_digest"] == canonical_digest(
        origin["provenance"]["generation_specification"]
    )
    assert result["coverage"]["failed"] == 0 and result["coverage"]["evaluation_fraction"] == 1
    assert not result["original_generation_evidence"]["trusted_as_replay"]
    assert not result["grid_search_reexecuted"] and origin == before
    assert validate_replay(origin) == result
    for check in result["checks"]:
        for ref in check["evidence_refs"]:
            name = ref["pointer"].split("/")[-1]
            assert ref["digest"] == canonical_digest(result["sources"][name])


def test_replay_never_calls_search_or_generator(origin, monkeypatch):
    import vnai.floorplan
    import vnai.floorplan_search

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay attempted search/generation")

    monkeypatch.setattr(vnai.floorplan, "generate_floorplans", forbidden)
    monkeypatch.setattr(vnai.floorplan, "_prepare", forbidden)
    monkeypatch.setattr(vnai.floorplan_search, "search", forbidden)
    assert validate_replay(origin)["replay_status"] == "VERIFIED"


@pytest.mark.parametrize(
    "change,failed", [("dimensions", ":width"), ("area", ":area"), ("adjacency", "relation:")]
)
def test_observed_failures_override_stored_pass(origin, change, failed):
    value = revised(origin, change)
    assert value["review"]["candidate"]["hard_validation"]["passed"]
    result = validate_replay(value)
    assert result["replay_status"] == "FAILED"
    assert any(c["status"] == "FAILED" and failed in c["id"] for c in result["checks"])
    assert result["coverage"]["failed"] > 0


def test_qualifying_manual_revision_not_regenerated_or_grid_snapped(origin):
    value = revised(origin)
    result = validate_replay(value)
    assert result["replay_status"] == "VERIFIED"
    assert value["review"]["candidate"]["geometry"] != origin["review"]["candidate"]["geometry"]
    assert not result["grid_search_reexecuted"]


def test_reservation_exclusion_and_same_floor_conflicts():
    result = validate_replay(reserved_case())
    assert result["replay_status"] == "FAILED"
    assert any(
        "reservation:SYNTHETIC-SHAFT" in c["id"] and c["status"] == "FAILED"
        for c in result["checks"]
    )


@pytest.mark.parametrize(
    "field",
    ["generation_engine_version", "dependency_digests", "constraint_register", "provenance_digest"],
)
def test_stale_provenance_is_not_validated_by_hash_alone(origin, field):
    value = deepcopy(origin)
    if field == "dependency_digests":
        value["provenance"][field]["brief"] = "0" * 64
    elif field == "constraint_register":
        value["provenance"][field]["dimensions"][0]["width"]["max"] += 1
    elif field == "provenance_digest":
        value["provenance"][field] = "0" * 64
    else:
        value["provenance"][field] = "not-the-declared-generation-engine"
    assert validate_replay(value)["replay_status"] == "STALE"


def test_missing_historical_provenance_stays_missing(origin):
    value = deepcopy(origin)
    value.pop("provenance")
    result = validate_replay(value)
    assert result["replay_status"] == "INCOMPLETE" and not result["checks"]
    assert result["missing_dependencies"] == ["original_generation_provenance"]
    with pytest.raises(ValueError, match="required|specification"):
        create_generation_provenance({"schema_version": 1}, value["review"]["candidate"])


def test_new_generation_opt_in_has_no_default_output_or_candidate_change(origin):
    spec = origin["provenance"]["generation_specification"]
    before = deepcopy(spec)
    old = generate_floorplans(spec)
    new = generate_floorplans(spec, include_provenance=True)
    assert new["generation_provenance"]
    new.pop("generation_provenance")
    assert old == new and spec == before
    invalid = deepcopy(spec)
    invalid["parameters"]["candidate_count"] = 1
    with pytest.raises(ValueError, match="match"):
        create_generation_provenance(invalid, old["candidates"][0])


def test_changed_baseline_needs_explicit_matching_confirmation(origin):
    value = changed_baseline(origin)
    assert validate_replay(value)["replay_status"] == "VERIFIED"
    before = deepcopy(value)
    value.pop("baseline_revision")
    assert validate_replay(value)["replay_status"] == "STALE"
    before["baseline_revision"]["confirmation"]["specification_digest"] = "0" * 64
    assert validate_replay(before)["replay_status"] == "STALE"


@pytest.mark.parametrize(
    "change", ["unit", "trace", "overlap", "remove_reservation", "stale_area", "invalid_polygon"]
)
def test_replay_negative_contracts(origin, change):
    value = revised(origin)
    geometry = value["review"]["candidate"]["geometry"]
    rows = [r for r in geometry["polygons"] if r["role"] == "room"]
    if change == "unit":
        rows[0]["units"] = "mm"
    elif change == "trace":
        rows[0]["requirement_id"] = "REQ-MISSING"
    elif change == "overlap":
        rows[0]["exterior"] = deepcopy(rows[1]["exterior"])
    elif change == "stale_area":
        value["review"]["candidate"]["room_areas_m2"][rows[0]["room_id"]] = 7
    elif change == "invalid_polygon":
        rows[0]["exterior"] = [[0, 0], [2, 4], [2, 0], [0, 4]]
    else:
        geometry["polygons"][0]["exterior"][0][0] = -0.5
    result = validate_replay(value)
    assert result["replay_status"] != "VERIFIED"
    assert result["blocking_issues"]
    if change == "stale_area":
        assert result["replay_status"] == "STALE"


def test_result_contract_and_nonfinite_guard(origin):
    result = validate_replay(origin)
    check = new_report("test")
    assert schema_check(result, "design-replay.schema.json#/$defs/result", check), check
    invalid = deepcopy(origin)
    invalid["review"]["candidate"]["geometry"]["polygons"][0]["exterior"][0][0] = float("inf")
    assert validate_replay(invalid)["replay_status"] == "INVALID_INPUT"


def test_changed_coordinate_convention_is_unsupported_not_a_proven_geometric_failure(origin):
    value = revised(origin)
    value["review"]["candidate"]["geometry"]["frame"]["id"] = "UNKNOWN-TRANSFORM"
    result = validate_replay(value)
    assert result["replay_status"] == "UNSUPPORTED"
    assert not any(c["status"] == "FAILED" for c in result["checks"])


def test_stored_floor_metadata_is_not_trusted(origin):
    value = revised(origin)
    value["review"]["candidate"]["floor_ids"] = ["WRONG-FLOOR"]
    result = validate_replay(value)
    assert result["replay_status"] == "STALE"
    assert "candidate_floor_metadata" in result["blocking_issues"]


def test_combined_geometry_resource_guard(origin):
    value = deepcopy(origin)
    geometry = value["review"]["candidate"]["geometry"]
    geometry["polygons"].extend([deepcopy(geometry["polygons"][0]) for _ in range(501)])
    assert validate_replay(value)["replay_status"] == "INVALID_INPUT"
