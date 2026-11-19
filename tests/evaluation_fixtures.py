"""Synthetic policy alternatives using actual Batch 006A/B contracts."""

from copy import deepcopy
import json
from pathlib import Path

from circulation_fixtures import base
from floorplan_fixtures import synthetic_spec, approve_source, authorize
from vnai.floorplan import generate_floorplans

ROOT = Path(__file__).resolve().parents[1]


def review_fixture(name):
    return json.loads((ROOT / "examples/batch006b" / (name + ".json")).read_text(encoding="utf-8"))


def policy(required=()):
    return {
        "schema_version": 1,
        "policy_id": "synthetic-area-v1",
        "required_hard_checks": list(required),
        "criteria": [
            {
                "id": "area",
                "metric_id": "allocated_room_area_m2",
                "direction": "maximize",
                "weight": 1,
                "required": True,
                "lower": 0,
                "upper": 24,
            },
            {
                "id": "deviation",
                "metric_id": "area_target_deviation_m2",
                "direction": "minimize",
                "weight": 3,
                "required": True,
                "lower": 0,
                "upper": 4,
            },
        ],
        "optional_criteria": "withhold",
        "not_applicable_criteria": "exclude",
        "score_precision": 6,
        "tie_tolerance": 0.000001,
        "allow_partial_ranking": False,
        "comparison_scope": {"id": "synthetic-same-requirements", "mode": "strict_baseline"},
    }


def request(*reviews, config=None):
    return {
        "schema_version": 1,
        "config": config or policy(),
        "candidates": [{"id": chr(65 + i), "review": deepcopy(r)} for i, r in enumerate(reviews)],
    }


def area_alternatives():
    spec = synthetic_spec(width=6, depth=6)
    for room in spec["geometry"]["zoning"]["brief"]["building"]["rooms"]:
        room["area"] = {"min": 4, "max": 12, "target": 8, "unit": "m2"}
    approve_source(spec)
    alternatives = []
    for width, depth in ((4, 2), (4, 3), (2, 2)):
        current = deepcopy(spec)
        for dimension in current["room_dimensions"]:
            dimension["width"] = {"min": width, "max": width}
            dimension["depth"] = {"min": depth, "max": depth}
        authorize(current)
        result = generate_floorplans(current)
        assert result["status"] == "GENERATED", result
        sidecar = base(result["candidates"][0])
        # Geometry-only policy explicitly leaves access proofs unresolved, never failed.
        sidecar["openings_complete"] = False
        sidecar["stairs_complete"] = False
        alternatives.append(sidecar)
    return alternatives


def scenarios():
    from vnai.candidate_evaluation import evaluate_candidates

    alternatives = area_alternatives()
    three = request(*alternatives)
    strict = policy(("entrance_reachability", "circulation_clearance", "stair_connectivity"))
    cases = {
        "three-candidates": three,
        "target-deviations": request(*alternatives[:2]),
        "hard-failure": request(review_fixture("swing-obstacle")),
        "missing-circulation": request(review_fixture("missing-openings"), config=strict),
        "verified-circulation": request(review_fixture("corridor-clearance"), config=strict),
        "graph-unknown-clearance": request(review_fixture("corridor-graph-only"), config=strict),
        "incomplete-stairs": request(review_fixture("stairs-missing-endpoint"), config=strict),
        "tie": deepcopy(three),
        "incompatible-baselines": request(alternatives[0], review_fixture("corridor-clearance")),
        "stale-evidence": request(review_fixture("corridor-clearance")),
        "ranking-withheld": request(
            review_fixture("corridor-clearance"),
            review_fixture("corridor-graph-only"),
            config=strict,
        ),
        "all-ineligible": request(
            review_fixture("swing-obstacle"), review_fixture("disconnected-room")
        ),
        "permutation": deepcopy(three),
        "repeated": deepcopy(three),
        "changed-weights": deepcopy(three),
        "not-applicable": request(review_fixture("corridor-clearance")),
        "unsupported-metric": deepcopy(three),
        "selected-not-approved": request(review_fixture("selected-only")),
    }
    cases["tie"]["config"]["tie_tolerance"] = 0.7
    cases["permutation"]["candidates"].reverse()
    cases["changed-weights"]["config"]["criteria"][0]["weight"] = 20
    stale = cases["stale-evidence"]
    stale["prior_evidence"] = [evaluate_candidates(stale)["evaluations"][0]["evidence"]]
    stale["candidates"][0]["review"]["openings"][0]["provenance"] += " revised after evidence"
    cases["unsupported-metric"]["config"]["criteria"][0]["metric_id"] = "aesthetic_quality"
    return cases


def golden_projection(report):
    from vnai.contracts import canonical_digest

    return {
        "full_report_sha256": canonical_digest(report),
        "status": report["status"],
        "ranking_status": report.get("ranking_status"),
        "winner_id": report.get("winner_id"),
        "ranking": report.get("ranking"),
        "evaluations": [
            {
                "id": e["id"],
                "candidate_digest": e["candidate_digest"],
                "design_digest": e["design_digest"],
                "evaluation_digest": e["evaluation_digest"],
                "eligibility": e["evidence"]["eligibility"],
                "counts": e["evidence"]["counts"],
                "checks": {c["check_id"]: c["status"] for c in e["evidence"]["checks"]},
                "aggregate": e["scoring"]["aggregate"],
                "metrics": {
                    m["metric_id"]: {
                        k: m[k] for k in ("value", "status", "coverage", "evidence_refs")
                    }
                    for m in e["metrics"]
                },
            }
            for e in report["evaluations"]
        ],
        "pairs": [
            {
                "left_id": p["left_id"],
                "right_id": p["right_id"],
                "aggregate_comparable": p["aggregate_comparable"],
                "comparable_metric_ids": [m["metric_id"] for m in p["comparable_metrics"]],
            }
            for p in report.get("pairs", [])
        ],
    }
