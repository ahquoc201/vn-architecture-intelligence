"""Pairwise metric comparability and factual trade-offs before global ranking."""

from itertools import combinations
from typing import Any

from vnai.candidate_evaluation import evaluate_candidates
from vnai.contracts import finish, issue


def pairwise(evaluations: list[dict], config: dict) -> list[dict]:
    pairs = []
    scope = config["comparison_scope"]
    for a, b in combinations(evaluations, 2):
        same = a["baseline"]["digest"] == b["baseline"]["digest"]
        explicit = scope["mode"] == "explicit_metric_basis" and all(
            e["baseline"]["digest"] in scope["baseline_digests"] for e in (a, b)
        )
        bm = {m["metric_id"]: m for m in b["metrics"]}
        comparable, noncomparable, strengths = [], [], []
        left_scores = {c["id"]: c for c in a["scoring"]["criteria"]}
        right_scores = {c["id"]: c for c in b["scoring"]["criteria"]}
        for m in a["metrics"]:
            key = m["metric_id"]
            other = bm[key]
            allowed = (
                same
                if scope["mode"] == "strict_baseline"
                else explicit and key in scope["metric_ids"]
            )
            reason = None
            if not allowed:
                reason = "INCOMPATIBLE_BASELINE_OR_SCOPE"
            elif (
                m["status"] != "VERIFIED"
                or other["status"] != "VERIFIED"
                or m["value"] is None
                or other["value"] is None
            ):
                reason = "EVIDENCE_NOT_VERIFIED_OR_NOT_APPLICABLE"
            elif m["unit"] != other["unit"] or m["metric_version"] != other["metric_version"]:
                reason = "METRIC_DEFINITION_MISMATCH"
            elif (m["unit"] == "fraction" or key == "area_target_deviation_m2") and m["coverage"][
                "denominator"
            ] != other["coverage"]["denominator"]:
                reason = "DIFFERENT_DENOMINATORS"
            if reason:
                noncomparable.append(
                    {
                        "metric_id": key,
                        "reason": reason,
                        "left_status": m["status"],
                        "right_status": other["status"],
                    }
                )
                continue
            comparable.append(
                {
                    "metric_id": key,
                    "left": m["value"],
                    "right": other["value"],
                    "delta_left_minus_right": m["value"] - other["value"],
                    "unit": m["unit"],
                    "evidence_refs": {a["id"]: m["evidence_refs"], b["id"]: other["evidence_refs"]},
                }
            )
            for c in sorted(config["criteria"], key=lambda c: c["id"]):
                if c["metric_id"] != key:
                    continue
                av = left_scores[c["id"]]["normalized_score"]
                bv = right_scores[c["id"]]["normalized_score"]
                if av is not None and bv is not None and av != bv:
                    strengths.append(
                        {
                            "criterion_id": c["id"],
                            "metric_id": key,
                            "preferred_by_declared_policy": a["id"] if av > bv else b["id"],
                            "less_preferred_by_declared_policy": b["id"] if av > bv else a["id"],
                            "normalized_scores": {a["id"]: av, b["id"]: bv},
                        }
                    )
        scoring = [e["scoring"] for e in (a, b)]
        aggregate_comparable = (
            all(s["status"] == "SCORED" for s in scoring)
            and scoring[0]["active_criteria"] == scoring[1]["active_criteria"]
        )
        active_ids = set(scoring[0]["active_criteria"])
        active_metrics = {c["metric_id"] for c in config["criteria"] if c["id"] in active_ids}
        aggregate_comparable = (
            aggregate_comparable
            and bool(active_metrics)
            and active_metrics <= {m["metric_id"] for m in comparable}
        )
        pairs.append(
            {
                "left_id": a["id"],
                "right_id": b["id"],
                "same_baseline": same,
                "baseline_compatible": same if scope["mode"] == "strict_baseline" else explicit,
                "comparable_metrics": comparable,
                "non_comparable_metrics": noncomparable,
                "verified_strengths_and_weaknesses": strengths,
                "missing_evidence": {e["id"]: e["evidence"]["pending_checks"] for e in (a, b)},
                "constraint_violations": {e["id"]: e["evidence"]["failed_checks"] for e in (a, b)},
                "evidence_coverage": {e["id"]: e["evidence"]["counts"] for e in (a, b)},
                "aggregate_comparable": aggregate_comparable,
                "limitations": [
                    "Direction-based trade-offs are policy preferences, not architectural approval."
                ],
            }
        )
    return pairs


def comparison_status(pairs: list[dict]) -> str:
    if pairs and all(p["aggregate_comparable"] for p in pairs):
        return "COMPARABLE"
    return "PARTIALLY_COMPARABLE" if any(p["comparable_metrics"] for p in pairs) else "INCOMPARABLE"


def markdown_report(report: dict) -> str:
    lines = [
        "# Floorplan evaluation - advisory decision support",
        "",
        "Scope: " + str(report["scope"]),
        "",
        "Ranking: "
        + report.get("ranking_status", report.get("comparison_status", report["status"])),
        "",
        "No architect decision is performed. CAD writes: false. Technical standards and Feng Shui: NOT_EVALUATED.",
        "",
    ]
    for e in report["evaluations"]:
        evidence, scoring = e["evidence"], e["scoring"]
        lines += [
            "## " + e["id"],
            "",
            "Candidate: " + e["candidate_id"],
            "Candidate digest: " + e["candidate_digest"],
            "Design digest: " + e["design_digest"],
            "Eligibility: " + evidence["eligibility"],
            "Observed source selection/review state: " + e["selection_state"],
            "Preference aggregate: " + str(scoring["aggregate"]),
            "Evidence counts (not confidence): " + str(evidence["counts"]),
            "Input declarations (not verification): " + str(evidence["input_completeness"]),
            "",
            "| Criterion | Value | Evidence | Weight | Normalized | Effective weight | Explanation |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for c in scoring["criteria"]:
            lines.append(
                "| "
                + " | ".join(
                    str(c[k])
                    for k in (
                        "id",
                        "value",
                        "metric_status",
                        "weight",
                        "normalized_score",
                        "effective_weight",
                        "explanation",
                    )
                )
                + " |"
            )
        lines += [
            "",
            "Unresolved required checks: " + str(evidence["pending_checks"]),
            "Unsupported required checks: " + str(evidence["unsupported_checks"]),
            "Known failures: " + str(evidence["failed_checks"]),
            "Scoring limitations: " + str(scoring["reasons"]),
            "Next: resolve listed checks, confirm inventories and routes, then request a separate architect decision.",
            "",
        ]
        lines += [
            "| Observed metric | Value | Unit | Status | Observed / applicable |",
            "| --- | --- | --- | --- | --- |",
        ]
        for m in e["metrics"]:
            lines.append(
                f"| {m['metric_id']} | {m['value']} | {m['unit']} | {m['status']} | {m['coverage']['numerator']} / {m['coverage']['denominator']} |"
            )
        lines += [
            "",
            "Declared generator unresolved checks: "
            + str(e["sources"]["review"]["candidate"]["unresolved_checks"]),
            "Additional validation: " + str(e["sources"]["architectural"]["next_actions"]),
            "",
        ]
    for p in report.get("pairs", []):
        lines += [
            "## " + p["left_id"] + " / " + p["right_id"],
            "",
            "Aggregate comparable: " + str(p["aggregate_comparable"]),
            "Verified trade-offs: " + str(p["verified_strengths_and_weaknesses"]),
            "Non-comparable metrics: " + str(p["non_comparable_metrics"]),
            "",
        ]
    lines += [
        "Ranking: " + str(report.get("ranking", [])),
        "Conditional subset order: " + str(report.get("conditional_order", [])),
        "Withholding reasons: " + str(report.get("reasons", [])),
        "",
        "Limitations: supplied planar proofs only; no original dimension replay, structural, MEP, technical compliance or aesthetics assessment.",
        "",
    ]
    return "\n".join(lines)


def compare_candidates(request: Any) -> dict:
    report = evaluate_candidates(request)
    report.update(
        contract="candidate-comparison-v1", pairs=[], comparison_status="INVALID_INPUT", markdown=""
    )
    if report["errors"]:
        report["markdown"] = markdown_report(report)
        return report
    if len(report["evaluations"]) < 2:
        issue(
            report,
            "errors",
            "COMPARISON_REQUIRES_TWO",
            "candidates",
            "Comparison requires two or more alternatives.",
        )
        report["markdown"] = markdown_report(report)
        return finish(report)
    report["pairs"] = pairwise(report["evaluations"], request["config"])
    report["comparison_status"] = comparison_status(report["pairs"])
    if report["comparison_status"] != "COMPARABLE":
        issue(
            report,
            "missing_information",
            "GLOBAL_COMPARISON_WITHHELD",
            "pairs",
            "Individual verified metrics may be comparable; a global score comparison is not justified.",
        )
    finish(report)
    report["markdown"] = markdown_report(report)
    return report
