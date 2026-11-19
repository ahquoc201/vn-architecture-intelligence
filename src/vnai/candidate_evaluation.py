"""Bounded orchestration of metric, evidence and policy layers."""

from typing import Any

from vnai.candidate_evidence import evidence_coverage
from vnai.candidate_metrics import measure
from vnai.candidate_scoring import score_candidate
from vnai.contracts import canonical_digest, finish, issue, new_report
from vnai.evaluation_policy import baseline, binding, validate_policy


def evaluate_candidates(request: Any) -> dict:
    report = new_report("candidate-evaluation-v1")
    report.update(
        policy_digest=None,
        scope=None,
        evaluations=[],
        architect_selection="NOT_PERFORMED",
        architect_approval="NOT_GRANTED_BY_EVALUATION",
    )
    config = validate_policy(request, report)
    if config is None:
        return finish(report)
    report.update(policy_digest=canonical_digest(config), scope=config["comparison_scope"])
    for alternative in sorted(request["candidates"], key=lambda c: c["id"]):
        review = alternative["review"]
        bound = binding(review, config)
        measured = measure(review, bound, [c["metric_id"] for c in config["criteria"]])
        evidence = evidence_coverage(
            review, measured, bound, config, request.get("prior_evidence", [])
        )
        scoring = score_candidate(measured["metrics"], evidence, config)
        report["evaluations"].append(
            {
                "id": alternative["id"],
                **bound,
                "baseline": baseline(review),
                "metrics": measured["metrics"],
                "sources": measured["sources"],
                "evidence": evidence,
                "scoring": scoring,
                "selection_state": measured["sources"]["architectural"]["candidate_review"][
                    "review_state"
                ],
                "approval_record_valid": measured["sources"]["architectural"]["candidate_review"][
                    "approval_record_valid"
                ],
            }
        )
        if scoring["status"] == "WITHHELD":
            issue(
                report,
                "missing_information",
                "SCORING_WITHHELD",
                alternative["id"],
                "; ".join(scoring["reasons"]),
            )
    return finish(report)
