"""Exact immutable candidate/design binding and explicit human review semantics."""

from copy import deepcopy

import pytest

from circulation_fixtures import two_rooms, corridor, review_events, selection
from vnai.candidate_review import review_candidate, candidate_digest, design_digest
from vnai.contracts import new_report, schema_check


def codes(report):
    return {r["code"] for r in report["errors"] + report["missing_information"]}


def test_selection_is_not_approval_and_candidate_is_unchanged():
    spec = two_rooms()
    snapshot = deepcopy(spec)
    result = review_candidate(spec)
    assert result["status"] == "VALID" and result["review_state"] == "SELECTED"
    assert not result["approval_record_valid"] and not result["cad_writes_permitted"]
    assert result["candidate_digest"] == candidate_digest(spec["candidate"])
    assert result["design_digest"] == design_digest(spec)
    assert spec == snapshot
    assert schema_check(result, "candidate-review.schema.json#/$defs/result", new_report("test"))


def test_no_implicit_selection_when_only_candidate_is_supplied():
    spec = two_rooms()
    spec.pop("selection")
    spec["decisions"] = []
    result = review_candidate(spec)
    assert result["status"] == "INCOMPLETE" and result["review_state"] == "UNSELECTED"


@pytest.mark.parametrize(
    "states,expected",
    [
        (("SELECTED", "REVIEWED"), "REVIEWED"),
        (("SELECTED", "REVIEWED", "APPROVED"), "APPROVED"),
        (("SELECTED", "REJECTED"), "REJECTED"),
        (("SELECTED", "REVIEWED", "SUPERSEDED"), "SUPERSEDED"),
    ],
)
def test_review_transitions(states, expected):
    spec = review_events(corridor(True), states)
    report = review_candidate(spec)
    assert not report["errors"] and report["review_state"] == expected
    assert report["approval_record_valid"] is (expected == "APPROVED")
    assert not report["cad_writes_permitted"]


@pytest.mark.parametrize("field", ["candidate_id", "candidate_digest"])
def test_selection_mismatch(field):
    spec = two_rooms()
    spec["selection"][field] = "BAD" if field == "candidate_id" else "0" * 64
    report = review_candidate(spec)
    assert "CANDIDATE_SELECTION_MISMATCH" in codes(report)
    assert not report["approval_record_valid"]


def test_candidate_change_invalidates_selection_without_mutating_original():
    spec = two_rooms()
    before = deepcopy(spec)
    spec["candidate"]["geometry"]["tolerances"]["boundary_m"] = 0.001
    assert "CANDIDATE_SELECTION_MISMATCH" in codes(review_candidate(spec))
    assert before["candidate"]["geometry"]["tolerances"]["boundary_m"] == 0


@pytest.mark.parametrize(
    "change", ["opening", "path", "obstacle_declaration", "stairs_declaration"]
)
def test_all_design_content_changes_invalidate_approval(change):
    spec = review_events(corridor(True), ("SELECTED", "REVIEWED", "APPROVED"))
    if change == "opening":
        spec["openings"][1]["clear_width"] = 0.9
    elif change == "path":
        spec["passages"][0]["width"] = 0.3
    elif change == "obstacle_declaration":
        spec["fixed_obstacles_complete"] = False
    else:
        spec["stairs_complete"] = False
    report = review_candidate(spec)
    assert "STALE_DESIGN_REVIEW" in codes(report)
    assert not report["approval_record_valid"] and report["review_state"] != "APPROVED"


@pytest.mark.parametrize(
    "states",
    [
        ("SELECTED", "APPROVED"),
        ("SELECTED", "REJECTED", "REVIEWED"),
        ("SELECTED", "SUPERSEDED", "APPROVED"),
    ],
)
def test_invalid_promotions_do_not_create_approval(states):
    report = review_candidate(review_events(two_rooms(), states))
    assert "REVIEW_TRANSITION" in codes(report) and not report["approval_record_valid"]


def test_architect_role_and_timestamp_order():
    spec = review_events(two_rooms(), ("SELECTED", "REVIEWED", "APPROVED"))
    spec["decisions"][1]["record"]["role"] = "user"
    assert "ARCHITECT_REVIEW_ROLE" in codes(review_candidate(spec))
    spec = review_events(two_rooms(), ("SELECTED", "REVIEWED", "APPROVED"))
    spec["decisions"][1]["record"]["recorded_at"] = "2026-11-17T00:00:00Z"
    assert "REVIEW_TIMESTAMP_ORDER" in codes(review_candidate(spec))


@pytest.mark.parametrize(
    "timestamp",
    ["yesterday", "2026-11-18T00:00:00", "2026-02-30T00:00:00Z", "2026-11-18T24:00:00Z"],
)
def test_invalid_approval_timestamps(timestamp):
    spec = two_rooms()
    spec["decisions"][0]["record"]["recorded_at"] = timestamp
    assert review_candidate(spec)["status"] == "INVALID"


def test_recomputed_area_is_checked_instead_of_trusting_stored_pass():
    spec = two_rooms()
    spec["candidate"]["room_areas_m2"]["BED:1"] = 99
    selection(spec)
    report = review_candidate(spec)
    assert "CANDIDATE_MEASUREMENT_MISMATCH" in codes(report)
    assert not report["approval_record_valid"]


def test_review_provenance_and_timestamps_are_preserved_exactly():
    spec = review_events(corridor(True), ("SELECTED", "REVIEWED", "APPROVED"))
    report = review_candidate(spec)
    assert report["decision_history"] == spec["decisions"]
    assert report["selection_record"] == spec["selection"]
    assert (
        report["decision_history"][-1]["record"]["actor"]
        == spec["decisions"][-1]["record"]["actor"]
    )
