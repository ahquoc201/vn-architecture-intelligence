"""Conditional ranking; unknown evidence and unsupported comparisons cannot win."""

from decimal import Decimal
from typing import Any

from vnai.candidate_comparison import compare_candidates, markdown_report


def rank_candidates(request: Any) -> dict:
    report = compare_candidates(request)
    report.update(
        contract="candidate-ranking-v1",
        ranking_status="RANKING_WITHHELD",
        ranking=[],
        conditional_order=[],
        winner_id=None,
        leaders=[],
        definitive=False,
        reasons=[],
    )
    if report["errors"]:
        report["reasons"].append("Invalid input or policy.")
    else:
        evaluations = report["evaluations"]
        eligible = [
            e
            for e in evaluations
            if e["evidence"]["eligibility"] == "ELIGIBLE" and e["scoring"]["status"] == "SCORED"
        ]
        pending = [
            e["id"]
            for e in evaluations
            if e["evidence"]["eligibility"] != "INELIGIBLE" and e not in eligible
        ]
        eligible_ids = {e["id"] for e in eligible}
        incompatible = [
            p
            for p in report["pairs"]
            if {p["left_id"], p["right_id"]} <= eligible_ids and not p["aggregate_comparable"]
        ]
        incompatible += [p for p in report["pairs"] if not p["baseline_compatible"]]
        if all(e["evidence"]["eligibility"] == "INELIGIBLE" for e in evaluations):
            report["ranking_status"] = "NO_ELIGIBLE_CANDIDATES"
            report["reasons"].append(
                "Every submitted candidate has a verified hard failure; no search infeasibility claim."
            )
        elif pending or incompatible or not eligible:
            report["reasons"] += [
                "Pending/unsupported or unscored alternatives: " + str(pending),
                "Incompatible eligible comparison pairs: " + str(len(incompatible)),
            ]
            if (
                request["config"]["allow_partial_ranking"]
                and len(eligible) >= 2
                and not incompatible
            ):
                report["ranking_status"] = "PARTIALLY_COMPARABLE"
                report["conditional_order"] = ordered(eligible, request["config"]["tie_tolerance"])
        else:
            report["ranking"] = ordered(eligible, request["config"]["tie_tolerance"])
            report["leaders"] = [r["id"] for r in report["ranking"] if r["rank"] == 1]
            report["ranking_status"] = "TIED" if len(report["leaders"]) > 1 else "RANKED"
            report["winner_id"] = report["leaders"][0] if len(report["leaders"]) == 1 else None
            report["definitive"] = True
    report["markdown"] = markdown_report(report)
    return report


def ordered(evaluations: list[dict], tolerance: float) -> list[dict]:
    result = []
    anchor = None
    rank = 0
    for i, e in enumerate(sorted(evaluations, key=lambda e: (-e["scoring"]["aggregate"], e["id"]))):
        score = Decimal(str(e["scoring"]["aggregate"]))
        if anchor is None or anchor - score > Decimal(str(tolerance)):
            anchor, rank = score, i + 1
        result.append({"id": e["id"], "rank": rank, "score": float(score)})
    return result
