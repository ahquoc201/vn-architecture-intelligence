"""Numerical, evidence, policy, ranking and contract regression oracles."""

from copy import deepcopy
from itertools import permutations
import json

import pytest

from evaluation_fixtures import area_alternatives, request, review_fixture, policy
from circulation_fixtures import selection
from vnai.candidate_evaluation import evaluate_candidates
from vnai.candidate_comparison import compare_candidates
from vnai.candidate_ranking import rank_candidates, ordered
from vnai.candidate_scoring import score_candidate
from vnai.contracts import canonical_digest, new_report, schema_check


@pytest.fixture(scope="module")
def alternatives():
    return area_alternatives()


def metric(evaluation, key):
    return next(m for m in evaluation["metrics"] if m["metric_id"] == key)


def check(evaluation, key):
    return next(c for c in evaluation["evidence"]["checks"] if c["check_id"] == key)


def test_measured_areas_and_targets_rank_without_quality_claim(alternatives):
    report = rank_candidates(request(*alternatives))
    assert report["ranking_status"] == "RANKED" and report["winner_id"] == "A"
    assert [r["score"] for r in report["ranking"]] == [0.916667, 0.25, 0.083333]
    for e, area, deviation in zip(report["evaluations"], (16, 24, 8), (0, 4, 4)):
        assert metric(e, "allocated_room_area_m2")["value"] == area
        assert metric(e, "area_target_deviation_m2")["value"] == deviation
        assert metric(e, "geometric_residual_area_m2")["value"] == 36 - area
        assert e["evidence"]["eligibility"] == "ELIGIBLE"
        assert check(e, "circulation_clearance")["status"] == "UNKNOWN"
        assert e["evidence"]["verified_coverage"] < 1
    assert "policy" in report["evaluations"][0]["scoring"]["limitations"][0].lower()
    assert report["architect_approval"] == "NOT_GRANTED_BY_EVALUATION"


def test_weights_change_ranking_and_digest(alternatives):
    spec = request(*alternatives)
    first = rank_candidates(spec)
    spec["config"]["criteria"][0]["weight"] = 20
    second = rank_candidates(spec)
    assert second["winner_id"] == "B" and first["winner_id"] == "A"
    assert second["policy_digest"] != first["policy_digest"]
    assert (
        second["evaluations"][0]["evaluation_digest"]
        != first["evaluations"][0]["evaluation_digest"]
    )
    assert (
        second["evaluations"][0]["candidate_digest"] == first["evaluations"][0]["candidate_digest"]
    )


@pytest.mark.parametrize(
    "name,status,graph,clearance",
    [
        ("corridor-clearance", "ELIGIBLE", "VERIFIED", "VERIFIED"),
        ("corridor-graph-only", "PENDING_VERIFICATION", "VERIFIED", "UNKNOWN"),
        ("missing-openings", "PENDING_VERIFICATION", "UNKNOWN", "UNKNOWN"),
        ("stairs-missing-endpoint", "PENDING_VERIFICATION", "UNKNOWN", "UNKNOWN"),
        ("swing-obstacle", "INELIGIBLE", "VERIFIED", "FAILED"),
        ("disconnected-room", "INELIGIBLE", "FAILED", "FAILED"),
        ("door-outside-host", "INELIGIBLE", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_actual_review_evidence(name, status, graph, clearance):
    spec = request(
        review_fixture(name),
        config=policy(("entrance_reachability", "circulation_clearance", "stair_connectivity")),
    )
    e = evaluate_candidates(spec)["evaluations"][0]
    assert e["evidence"]["eligibility"] == status
    assert check(e, "entrance_reachability")["status"] == graph
    assert check(e, "circulation_clearance")["status"] == clearance
    if clearance == "UNKNOWN":
        m = metric(e, "circulation_clearance_coverage")
        assert m["value"] is None and m["status"] == "UNKNOWN"
    if status != "ELIGIBLE":
        assert e["scoring"]["aggregate"] is None


def test_hard_failure_beats_all_soft_scores(alternatives):
    failed = deepcopy(alternatives[0])
    rooms = [r for r in failed["candidate"]["geometry"]["polygons"] if r["role"] == "room"]
    rooms[1]["exterior"] = deepcopy(rooms[0]["exterior"])
    selection(failed)
    report = rank_candidates(request(alternatives[0], failed))
    assert report["evaluations"][1]["evidence"]["eligibility"] == "INELIGIBLE"
    assert "spatial_geometry" in report["evaluations"][1]["evidence"]["failed_checks"]
    assert report["evaluations"][1]["scoring"]["aggregate"] is None
    assert report["winner_id"] == "A"


def test_all_ineligible_is_not_search_infeasibility():
    report = rank_candidates(
        request(review_fixture("swing-obstacle"), review_fixture("disconnected-room"))
    )
    assert report["ranking_status"] == "NO_ELIGIBLE_CANDIDATES"
    assert not report["definitive"] and report["winner_id"] is None
    assert not report["ranking"] and len(report["evaluations"]) == 2


def test_critical_unknown_withholds_even_if_another_can_score():
    spec = request(
        review_fixture("corridor-clearance"),
        review_fixture("corridor-graph-only"),
        config=policy(("entrance_reachability", "circulation_clearance")),
    )
    report = rank_candidates(spec)
    assert report["ranking_status"] == "RANKING_WITHHELD"
    assert report["winner_id"] is None and not report["definitive"]
    assert report["pairs"][0]["comparable_metrics"]
    assert report["evaluations"][1]["scoring"]["aggregate"] is None


def test_stale_prior_does_not_reuse_a_score():
    spec = request(review_fixture("corridor-clearance"))
    old = evaluate_candidates(spec)["evaluations"][0]
    spec["prior_evidence"] = [old["evidence"]]
    assert evaluate_candidates(spec)["evaluations"][0]["evidence"]["eligibility"] == "ELIGIBLE"
    spec["candidates"][0]["review"]["openings"][0]["provenance"] += " revised"
    fresh = evaluate_candidates(spec)["evaluations"][0]
    assert check(fresh, "candidate_integrity")["status"] == "UNKNOWN"
    assert fresh["evidence"]["eligibility"] == "PENDING_VERIFICATION"
    assert fresh["scoring"]["aggregate"] is None
    assert fresh["design_digest"] != old["design_digest"]
    assert metric(fresh, "allocated_room_area_m2")["value"] == 16


@pytest.mark.parametrize("change", ["geometry", "requirements", "stairs"])
def test_digest_covers_all_design_dependencies(change):
    spec = request(review_fixture("corridor-clearance"))
    old = evaluate_candidates(spec)["evaluations"][0]
    spec["prior_evidence"] = [old["evidence"]]
    review = spec["candidates"][0]["review"]
    if change == "geometry":
        review["candidate"]["geometry"]["polygons"][0]["provenance"] = "Changed geometry source"
    elif change == "requirements":
        review["candidate"]["geometry"]["zoning"]["brief"]["project"]["name"] += " revised"
    else:
        review["stairs_complete"] = False
    fresh = evaluate_candidates(spec)["evaluations"][0]
    assert fresh["evaluation_digest"] != old["evaluation_digest"]
    assert fresh["scoring"]["aggregate"] is None
    assert check(fresh, "candidate_integrity")["status"] == "UNKNOWN"


def test_baseline_incompatibility_and_explicit_basis(alternatives):
    spec = request(alternatives[0], review_fixture("corridor-clearance"))
    report = rank_candidates(spec)
    assert report["ranking_status"] == "RANKING_WITHHELD"
    assert not report["pairs"][0]["comparable_metrics"]
    spec["config"]["comparison_scope"] = {
        "id": "explicit-area-only",
        "mode": "explicit_metric_basis",
        "baseline_digests": [e["baseline"]["digest"] for e in report["evaluations"]],
        "metric_ids": ["allocated_room_area_m2", "area_target_deviation_m2"],
        "rationale": "Synthetic comparison of two explicit area measures only, no whole-design equivalence.",
    }
    explicit = rank_candidates(spec)
    assert explicit["ranking_status"] == "TIED"
    assert len(explicit["pairs"][0]["comparable_metrics"]) == 2
    assert explicit["winner_id"] is None


def test_ties_precision_and_no_transitive_tie_chain(alternatives):
    spec = request(*alternatives)
    spec["config"]["tie_tolerance"] = 0.7
    report = rank_candidates(spec)
    assert report["ranking_status"] == "TIED"
    assert report["leaders"] == ["A", "B"]
    assert [r["rank"] for r in report["ranking"]] == [1, 1, 3]
    assert report["winner_id"] is None
    rows = [{"id": k, "scoring": {"aggregate": v}} for k, v in zip("ABC", (0.9, 0.8, 0.7))]
    assert [r["rank"] for r in ordered(rows, 0.1)] == [1, 1, 3]


def test_order_repeat_and_immutability(alternatives):
    spec = request(*alternatives)
    before = deepcopy(spec)
    expected = rank_candidates(spec)
    for permutation in permutations(spec["candidates"]):
        current = {**spec, "candidates": list(permutation)}
        assert rank_candidates(current) == expected
    assert rank_candidates(spec) == expected and spec == before
    reordered = deepcopy(spec)
    reordered["config"]["criteria"].reverse()
    assert rank_candidates(reordered) == expected


def test_na_excluded_and_completeness_is_not_coverage():
    full = evaluate_candidates(request(review_fixture("corridor-clearance")))["evaluations"][0]
    assert check(full, "stair_connectivity")["status"] == "NOT_APPLICABLE"
    counts = full["evidence"]["counts"]
    assert counts["applicable"] == counts["total"] - counts["not_applicable"]
    graph = evaluate_candidates(request(review_fixture("corridor-graph-only")))["evaluations"][0]
    assert graph["evidence"]["input_completeness"]["complete_sections"] == 4
    assert graph["evidence"]["verified_coverage"] < 1
    assert not graph["evidence"]["confidence_estimated"]


def test_selected_does_not_approve():
    e = evaluate_candidates(request(review_fixture("selected-only")))["evaluations"][0]
    assert e["selection_state"] == "SELECTED"
    assert not e["approval_record_valid"]
    assert e["sources"]["review"]["candidate"]["approval_status"] == "PROPOSED"


@pytest.mark.parametrize(
    "key",
    [
        "unsupported_metric",
        "unsupported_hard",
        "invalid_bounds",
        "missing_target",
        "duplicate_id",
        "zero_weight",
        "bad_scope",
        "duplicate_content",
        "nonfinite",
    ],
)
def test_unsupported_and_invalid_policies(alternatives, key):
    spec = request(*alternatives)
    c = spec["config"]["criteria"][0]
    if key == "unsupported_metric":
        c["metric_id"] = "aesthetic_quality"
    elif key == "unsupported_hard":
        spec["config"]["required_hard_checks"] = ["structural_safety"]
    elif key == "invalid_bounds":
        c["lower"] = c["upper"]
    elif key == "missing_target":
        c["direction"] = "target"
    elif key == "duplicate_id":
        spec["config"]["criteria"][1]["id"] = c["id"]
    elif key == "zero_weight":
        c["weight"] = 0
    elif key == "bad_scope":
        spec["config"]["comparison_scope"]["mode"] = "explicit_metric_basis"
    elif key == "duplicate_content":
        spec["candidates"][1]["review"] = deepcopy(spec["candidates"][0]["review"])
    else:
        c["weight"] = float("inf")
    report = rank_candidates(spec)
    assert report["ranking_status"] == "RANKING_WITHHELD"
    assert report["winner_id"] is None
    if key.startswith("unsupported"):
        assert not report["errors"]
        assert all(e["scoring"]["aggregate"] is None for e in report["evaluations"])
        if key == "unsupported_hard":
            assert report["evaluations"][0]["evidence"]["eligibility"] == "UNSUPPORTED"
        else:
            assert metric(report["evaluations"][0], "aesthetic_quality")["status"] == "UNSUPPORTED"
    else:
        assert report["status"] == "INVALID" and report["errors"]


def test_optional_exclusion_is_explicit_and_required_missing_is_not_zero():
    spec = request(review_fixture("corridor-graph-only"))
    spec["config"]["criteria"].append(
        {
            "id": "clearance",
            "metric_id": "circulation_clearance_coverage",
            "direction": "maximize",
            "weight": 2,
            "required": True,
            "lower": 0,
            "upper": 1,
        }
    )
    assert evaluate_candidates(spec)["evaluations"][0]["scoring"]["aggregate"] is None
    spec["config"]["optional_criteria"] = "exclude_unavailable"
    assert evaluate_candidates(spec)["evaluations"][0]["scoring"]["aggregate"] is None
    spec["config"]["criteria"][-1]["required"] = False
    e = evaluate_candidates(spec)["evaluations"][0]
    assert e["scoring"]["aggregate"] is not None
    assert e["scoring"]["active_weight_denominator"] == 4
    assert (
        next(c for c in e["scoring"]["criteria"] if c["id"] == "clearance")["status"] == "EXCLUDED"
    )


@pytest.mark.parametrize(
    "direction,value,expected",
    [
        ("maximize", -2, 0),
        ("maximize", 20, 1),
        ("minimize", 2, 0.8),
        ("target", 2, 0.4),
        ("target", 8, 0.4),
        ("target", 5, 1),
    ],
)
def test_normalization_oracles(direction, value, expected):
    config = policy()
    criterion = {
        "id": "test",
        "metric_id": "test",
        "direction": direction,
        "weight": 1,
        "required": True,
        "lower": 0,
        "upper": 10,
    }
    if direction == "target":
        criterion["target"] = 5
    config["criteria"] = [criterion]
    score = score_candidate(
        [{"metric_id": "test", "status": "VERIFIED", "value": value}],
        {"eligibility": "ELIGIBLE"},
        config,
    )
    assert score["aggregate"] == expected


def test_output_contracts_and_reference_hashes(alternatives):
    spec = request(*alternatives)
    for handler, name in (
        (evaluate_candidates, "evaluation"),
        (compare_candidates, "comparison"),
        (rank_candidates, "ranking"),
    ):
        report = handler(spec)
        validation = new_report("test")
        assert schema_check(report, "candidate-" + name + ".schema.json", validation), validation
        for e in report["evaluations"]:
            assert schema_check(e["evidence"], "evidence-coverage.schema.json", validation), (
                validation
            )
            for m in e["metrics"]:
                assert schema_check(m, "metric-result.schema.json", validation), validation
                assert m["candidate_digest"] == canonical_digest(
                    e["sources"]["review"]["candidate"]
                )
                for ref in m["evidence_refs"]:
                    assert ref["digest"] == canonical_digest(e["sources"][ref["kind"]])
            assert not report["cad_writes_permitted"]
            assert report["standards_review"] == report["fengshui_review"] == "NOT_EVALUATED"
    json.dumps(report, allow_nan=False)


def test_partial_ranking_has_no_global_winner(alternatives):
    spec = request(*alternatives)
    spec["config"]["allow_partial_ranking"] = True
    spec["candidates"][2]["review"]["selection"]["candidate_digest"] = "0" * 64
    report = rank_candidates(spec)
    assert report["ranking_status"] == "PARTIALLY_COMPARABLE"
    assert [r["id"] for r in report["conditional_order"]] == ["A", "B"]
    assert report["ranking"] == [] and report["winner_id"] is None and not report["definitive"]


def test_different_optional_weight_bases_cannot_rank():
    spec = request(review_fixture("corridor-clearance"), review_fixture("corridor-graph-only"))
    spec["config"]["optional_criteria"] = "exclude_unavailable"
    spec["config"]["criteria"].append(
        {
            "id": "clearance",
            "metric_id": "circulation_clearance_coverage",
            "direction": "maximize",
            "weight": 1,
            "required": False,
            "lower": 0,
            "upper": 1,
        }
    )
    report = rank_candidates(spec)
    assert all(e["scoring"]["aggregate"] is not None for e in report["evaluations"])
    assert report["ranking_status"] == "RANKING_WITHHELD"
    assert not report["pairs"][0]["aggregate_comparable"]


def test_na_policy_and_no_active_criteria():
    spec = request(review_fixture("corridor-clearance"))
    spec["config"]["criteria"] = [
        {
            "id": "stair",
            "metric_id": "stair_connectivity",
            "direction": "maximize",
            "weight": 1,
            "required": True,
            "lower": 0,
            "upper": 1,
        }
    ]
    e = evaluate_candidates(spec)["evaluations"][0]
    assert e["scoring"]["aggregate"] is None and e["scoring"]["active_weight_denominator"] == 0
    spec["config"]["not_applicable_criteria"] = "withhold"
    e = evaluate_candidates(spec)["evaluations"][0]
    assert e["scoring"]["criteria"][0]["status"] == "WITHHELD"


@pytest.mark.parametrize(
    "change,expected",
    [("area", "room_area_bounds"), ("floor", "floor_assignments"), ("inventory", "room_inventory")],
)
def test_source_hard_constraints_recomputed(alternatives, change, expected):
    review = deepcopy(alternatives[0])
    candidate = review["candidate"]
    rows = candidate["geometry"]["polygons"]
    room = next(r for r in rows if r["role"] == "room")
    if change == "area":
        room["exterior"] = [[0, 0], [1, 0], [1, 1], [0, 1]]
        candidate["room_areas_m2"][room["room_id"]] = 1
    elif change == "floor":
        room["floor_id"] = "NONEXISTENT"
    else:
        rows.remove(room)
        candidate["room_areas_m2"].pop(room["room_id"])
    selection(review)
    e = evaluate_candidates(request(review))["evaluations"][0]
    assert check(e, expected)["status"] == "FAILED"
    assert e["evidence"]["eligibility"] == "INELIGIBLE" and e["scoring"]["aggregate"] is None


def test_invalid_geometry_keeps_unknown_values_and_observed_hard_failure(alternatives):
    review = deepcopy(alternatives[0])
    room = next(r for r in review["candidate"]["geometry"]["polygons"] if r["role"] == "room")
    room["exterior"] = [[0, 0], [4, 2], [4, 0], [0, 2]]
    selection(review)
    e = evaluate_candidates(request(review))["evaluations"][0]
    assert check(e, "spatial_geometry")["status"] == "FAILED"
    assert metric(e, "allocated_room_area_m2")["value"] is None
    assert metric(e, "allocated_room_area_m2")["status"] == "UNKNOWN"


def test_resource_and_unbound_evidence_are_explicit(alternatives):
    spec = request(alternatives[0])
    polygons = spec["candidates"][0]["review"]["candidate"]["geometry"]["polygons"]
    polygons.extend([deepcopy(polygons[0]) for _ in range(501)])
    report = evaluate_candidates(spec)
    assert report["status"] == "INVALID"
    assert any(e["code"] == "EVALUATION_RESOURCE_LIMIT" for e in report["errors"])
    assert not report["evaluations"]
    old = evaluate_candidates(request(review_fixture("corridor-clearance")))["evaluations"][0][
        "evidence"
    ]
    spec = request(alternatives[0])
    spec["prior_evidence"] = [old]
    assert evaluate_candidates(spec)["errors"][0]["code"] == "UNBOUND_PRIOR_EVIDENCE"


def test_supported_stair_graph_is_not_physical_stair_proof():
    e = evaluate_candidates(
        request(
            review_fixture("stairs-connected"),
            config=policy(("stair_connectivity", "circulation_clearance")),
        )
    )["evaluations"][0]
    assert check(e, "stair_connectivity")["status"] == "VERIFIED"
    assert check(e, "circulation_clearance")["status"] == "UNKNOWN"
    assert e["evidence"]["eligibility"] == "PENDING_VERIFICATION"


def test_asymmetric_target_tradeoffs_follow_actual_policy(alternatives):
    spec = request(alternatives[0], alternatives[2])
    spec["config"]["criteria"] = [
        {
            "id": "target-area",
            "metric_id": "allocated_room_area_m2",
            "direction": "target",
            "weight": 1,
            "required": True,
            "lower": 0,
            "upper": 40,
            "target": 10,
        }
    ]
    report = rank_candidates(spec)
    assert [e["scoring"]["aggregate"] for e in report["evaluations"]] == [0.8, 0.8]
    assert report["ranking_status"] == "TIED"
    assert report["pairs"][0]["verified_strengths_and_weaknesses"] == []


def test_required_adjacency_and_no_invented_separation():
    from design_fixtures import add_relationship
    from floorplan_fixtures import synthetic_spec, approve_source
    from circulation_fixtures import base
    from vnai.floorplan import generate_floorplans

    spec = synthetic_spec(width=6, depth=4)
    add_relationship(spec["geometry"]["zoning"]["brief"], pair=["BED", "LIVING"])
    approve_source(spec)
    candidate = generate_floorplans(spec)["candidates"][0]
    review = base(candidate)
    review["openings_complete"] = False
    first = evaluate_candidates(request(review))["evaluations"][0]
    assert check(first, "required_relationships")["status"] == "VERIFIED"
    assert metric(first, "required_adjacency_satisfaction")["value"] == 1
    room = next(r for r in candidate["geometry"]["polygons"] if r.get("room_id") == "LIVING:1")
    # Keep area and source assignment, move one room to the opposite side of the envelope.
    room["exterior"] = [[4, 0], [6, 0], [6, 4], [4, 4]]
    bed = next(r for r in candidate["geometry"]["polygons"] if r.get("room_id") == "BED:1")
    bed["exterior"] = [[0, 0], [2, 0], [2, 4], [0, 4]]
    review = base(candidate)
    review["openings_complete"] = False
    second = evaluate_candidates(request(review))["evaluations"][0]
    assert check(second, "required_relationships")["status"] == "FAILED"
    assert second["evidence"]["eligibility"] == "INELIGIBLE"
    # A changed source with undefined architectural separation remains explicitly unsupported.
    candidate["geometry"]["zoning"]["brief"]["building"]["relationships"][0]["relation"] = (
        "separate"
    )
    spec["geometry"] = candidate["geometry"]
    approve_source(spec)
    third = evaluate_candidates(request(base(candidate)))["evaluations"][0]
    assert check(third, "required_relationships")["status"] == "UNSUPPORTED"
    assert third["scoring"]["aggregate"] is None


def test_known_stair_direction_failure_is_ineligible_without_requested_stair_gate():
    review = review_fixture("stairs-connected")
    review["stairs"][0]["direction"] = "down"
    e = evaluate_candidates(request(review))["evaluations"][0]
    assert check(e, "stair_connectivity")["status"] == "FAILED"
    assert e["evidence"]["eligibility"] == "INELIGIBLE" and e["scoring"]["aggregate"] is None


def test_missing_assignment_is_unknown_not_failed(alternatives):
    review = deepcopy(alternatives[0])
    review["candidate"]["geometry"]["zoning"]["assignments"] = []
    selection(review)
    e = evaluate_candidates(request(review))["evaluations"][0]
    assert check(e, "floor_assignments")["status"] == "UNKNOWN"
    assert e["scoring"]["aggregate"] is None
