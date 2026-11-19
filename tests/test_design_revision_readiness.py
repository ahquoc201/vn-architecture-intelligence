"""Review lineage, explicit feedback resolution and scoped drafting readiness."""

from copy import deepcopy

import pytest

from circulation_fixtures import review_events
from replay_fixtures import (
    original,
    revised,
    revision_request,
    feedback,
    readiness,
    changed_baseline,
)
from vnai.cad_readiness import readiness_report
from vnai.design_revision import compare_revision


@pytest.fixture(scope="module")
def origin():
    return original()


def test_valid_revision_diff_and_readiness(origin):
    child = revised(origin)
    spec = revision_request(origin, child)
    before = deepcopy(spec)
    result = compare_revision(spec)
    assert result["revision_status"] == "VERIFIED"
    assert set(result["changed_rooms"]) == {"BED:1", "LIVING:1"}
    assert {"dimension_bounds", "required_adjacency"} <= set(result["affected_constraints"])
    assert "parent_evaluation" in result["stale_evidence"]
    assert "source_brief" in result["unchanged_evidence_dependencies"]
    assert not result["approval_inherited"] and result["approval_invalidated"]
    assert spec == before
    ready = readiness(child)
    ready["revision"] = spec
    assert readiness_report(ready)["readiness_status"] == "READY_FOR_DRAFTING"
    assert readiness_report(readiness(child))["readiness_status"] == "INCOMPLETE"


@pytest.mark.parametrize("state", ["OPEN", "ADDRESSED", "VERIFIED", "WITHDRAWN", "SUPERSEDED"])
def test_feedback_resolution_is_explicit(origin, state):
    child = revised(origin)
    f = feedback(origin, resolution=state, child=child)
    result = compare_revision(revision_request(origin, child, [f]))
    resolved = state in {"VERIFIED", "WITHDRAWN"}
    assert (result["revision_status"] == "VERIFIED") == resolved
    assert bool(result["unresolved_feedback"]) != resolved
    assert not result["feedback_results"][0]["reviewer_identity_authenticated"]
    if resolved:
        f["resolution_record"]["child_design_digest"] = "0" * 64
        assert compare_revision(revision_request(origin, child, [f]))["unresolved_feedback"] == [
            "FB-1"
        ]


def test_supersession_is_acyclic_and_does_not_hide_open_replacement(origin):
    child = revised(origin)
    old = feedback(origin, resolution="SUPERSEDED", child=child)
    new = feedback(origin, key="FB-2")
    new["supersedes"] = ["FB-1"]
    result = compare_revision(revision_request(origin, child, [old, new]))
    assert result["unresolved_feedback"] == ["FB-2"]
    old["supersedes"] = ["FB-2"]
    assert any(
        e["code"] == "FEEDBACK_SUPERSESSION_CYCLE"
        for e in compare_revision(revision_request(origin, child, [old, new]))["errors"]
    )


@pytest.mark.parametrize(
    "change", ["digest", "same_revision", "stale_feedback", "unknown_room", "ai_unresolved"]
)
def test_revision_binding_and_unknown_dependencies(origin, change):
    child = revised(origin)
    f = feedback(origin)
    spec = revision_request(origin, child, [f])
    if change == "digest":
        spec["parent_candidate_digest"] = "0" * 64
    elif change == "same_revision":
        spec["child_revision_id"] = spec["parent_revision_id"]
    elif change == "stale_feedback":
        spec["feedback"][0]["target"]["candidate_digest"] = "0" * 64
    elif change == "unknown_room":
        spec["feedback"][0]["affected_room_ids"] = ["NOT-A-ROOM"]
    else:
        spec["change_origin"] = "unresolved_assumption"
    result = compare_revision(spec)
    assert result["revision_status"] != "VERIFIED" and not result["approval_inherited"]


def test_new_candidate_does_not_inherit_parent_approval(origin):
    parent = deepcopy(origin)
    review_events(parent["review"], ("SELECTED", "REVIEWED", "APPROVED"))
    child = revised(parent)
    result = compare_revision(revision_request(parent, child))
    assert result["parent_review"]["approval_record_valid"]
    assert result["approval_invalidated"] and not result["child_approval_record_valid"]
    assert "copied_parent_approval" in result["stale_evidence"]
    ready = readiness(child, review="APPROVED")
    ready["revision"] = revision_request(parent, child)
    assert readiness_report(ready)["readiness_status"] == "INCOMPLETE"
    review_events(child["review"], ("SELECTED", "REVIEWED", "APPROVED"))
    for e in child["review"]["decisions"]:
        e["id"] = "CHILD-" + e["id"]
    result = compare_revision(revision_request(parent, child))
    assert result["child_approval_record_valid"] and result["revision_status"] == "VERIFIED"
    assert not result["approval_inherited"]


def test_changed_requirements_are_a_new_explicit_baseline(origin):
    child = changed_baseline(origin)
    spec = revision_request(origin, child)
    assert compare_revision(spec)["revision_status"] == "INCOMPLETE"
    spec["change_origin"] = "user_confirmed_requirement_change"
    result = compare_revision(spec)
    assert result["revision_status"] == "VERIFIED"
    assert result["diff"]["requirement_baseline_changed"]
    original_max = origin["provenance"]["generation_specification"]["geometry"]["zoning"]["brief"][
        "building"
    ]["rooms"][0]["area"]["max"]
    revised_max = child["baseline_revision"]["specification"]["geometry"]["zoning"]["brief"][
        "building"
    ]["rooms"][0]["area"]["max"]
    assert original_max == 8 and revised_max == 9
    assert (
        next(c for c in result["replay"]["checks"] if c["id"] == "room:BED:1:area")["expected"][
            "max"
        ]
        == 9
    )
    assert result["diff"]["parent_brief_digest"] != result["diff"]["child_brief_digest"]


def test_scoped_room_readiness_is_not_complete_architectural_readiness(origin):
    result = readiness_report(readiness(origin))
    assert result["readiness_status"] == "READY_FOR_DRAFTING" and result["scope"] == [
        "room_geometry"
    ]
    assert result["stages"]["architectural_walls_openings"]["status"] == "INCOMPLETE"
    assert result["stages"]["stairs"]["status"] == "NOT_APPLICABLE"
    assert not result["cad_writes_permitted"] and not result["approval_granted"]
    assert result["construction_readiness"] == "NOT_EVALUATED"
    assert (
        result["sources"]["architectural_review"]["candidate_review"]["review_state"] == "SELECTED"
    )
    assert (
        readiness_report(readiness(origin, review="APPROVED"))["readiness_status"] == "INCOMPLETE"
    )
    spec = readiness(origin, ("architectural_walls_openings",))
    assert readiness_report(spec)["readiness_status"] == "INCOMPLETE"
    spec["drafting_information"]["wall_opening_information"] = {
        "available": True,
        "reference": "synthetic-external-wall-data",
    }
    assert readiness_report(spec)["readiness_status"] == "UNSUPPORTED"


def test_annotation_information_is_supplied_not_generated(origin):
    spec = readiness(origin, ("room_geometry", "annotations"))
    assert readiness_report(spec)["readiness_status"] == "INCOMPLETE"
    spec["drafting_information"]["annotations"] = {
        "title": "Synthetic concept sheet",
        "drawing_scale": 100,
        "units": "m",
        "frame_id": "LOCAL",
        "floor_ids": ["F1"],
        "room_labels": [
            {"room_id": k, "label": k} for k in origin["review"]["candidate"]["room_areas_m2"]
        ],
    }
    assert readiness_report(spec)["readiness_status"] == "READY_FOR_DRAFTING"
    spec["drafting_information"]["annotations"]["room_labels"].pop()
    assert readiness_report(spec)["readiness_status"] == "INCOMPLETE"


def test_required_circulation_is_not_zero_imputed(origin):
    spec = readiness(origin)
    spec["policy"].update(require_graph=True, require_clearance=True, require_openings=True)
    result = readiness_report(spec)
    assert result["readiness_status"] == "INCOMPLETE"
    assert {
        c["status"] for c in result["checks"] if c["id"] in {"require_graph", "require_clearance"}
    } == {"UNKNOWN"}


def test_failed_child_cannot_become_ready_through_selection(origin):
    child = revised(origin, "dimensions")
    spec = readiness(child)
    spec["revision"] = revision_request(origin, child)
    assert readiness_report(spec)["readiness_status"] == "NOT_READY"


def test_readiness_rejects_revision_bound_to_another_child(origin):
    child = revised(origin)
    spec = readiness(child)
    spec["revision"] = revision_request(origin, revised(origin, "dimensions"))
    assert readiness_report(spec)["readiness_status"] != "READY_FOR_DRAFTING"


def test_stale_evaluation_blocks_readiness(origin):
    from evaluation_fixtures import policy as evaluation_policy
    from vnai.candidate_evaluation import evaluate_candidates

    before = evaluate_candidates(
        {
            "schema_version": 1,
            "config": evaluation_policy(),
            "candidates": [{"id": "ORIGIN", "review": origin["review"]}],
        }
    )
    spec = readiness(origin)
    spec["policy"]["require_evaluation"] = True
    spec["evaluation_config"] = evaluation_policy()
    spec["prior_evidence"] = [before["evaluations"][0]["evidence"]]
    assert readiness_report(spec)["readiness_status"] == "READY_FOR_DRAFTING"
    spec["prior_evidence"][0]["design_digest"] = "0" * 64
    report = readiness_report(spec)
    assert report["readiness_status"] == "INCOMPLETE"
    assert (
        next(c for c in report["checks"] if c["id"] == "candidate_evaluation")["status"]
        == "UNKNOWN"
    )


def test_parent_must_bind_to_its_source_provenance(origin):
    child = revised(origin)
    spec = revision_request(origin, child)
    spec["parent_review"]["candidate"]["geometry"]["zoning"]["brief"]["project"]["name"] += (
        " unrelated baseline"
    )
    from vnai.review_common import candidate_digest, design_digest

    spec["parent_candidate_digest"] = candidate_digest(spec["parent_review"]["candidate"])
    spec["parent_design_digest"] = design_digest(spec["parent_review"])
    report = compare_revision(spec)
    assert report["revision_status"] != "VERIFIED"
    assert any(e["code"] == "PARENT_BASELINE_UNVERIFIED" for e in report["missing_information"])


def test_parent_physical_defect_can_be_repaired_without_inheriting_approval(origin):
    bad = revised(origin, "area")
    good = revised(origin)
    report = compare_revision(revision_request(bad, good))
    assert report["sources"]["parent_replay"]["replay_status"] == "FAILED"
    assert report["replay"]["replay_status"] == "VERIFIED"
    assert report["revision_status"] == "VERIFIED" and not report["approval_inherited"]


def test_unsupported_evaluation_requirement_stays_unsupported(origin):
    from evaluation_fixtures import policy as evaluation_policy

    spec = readiness(origin)
    spec["policy"]["require_evaluation"] = True
    spec["evaluation_config"] = evaluation_policy()
    spec["evaluation_config"]["criteria"][0]["metric_id"] = "unsupported-quality-score"
    assert readiness_report(spec)["readiness_status"] == "UNSUPPORTED"
    spec["evaluation_config"]["criteria"][0]["lower"] = spec["evaluation_config"]["criteria"][0][
        "upper"
    ]
    assert readiness_report(spec)["readiness_status"] == "INVALID_INPUT"


def test_extreme_physical_sidecar_data_is_rejected_before_geometry_operations(origin):
    from circulation_fixtures import two_rooms

    sidecar = two_rooms()
    sidecar["openings"][0]["start"][0] = 1e300
    spec = readiness(origin)
    spec["replay"]["review"] = sidecar
    assert readiness_report(spec)["readiness_status"] == "INVALID_INPUT"
