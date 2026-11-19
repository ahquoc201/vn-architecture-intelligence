"""Evidence applicability and hard eligibility, independently of preference scores."""

from collections import Counter

from vnai.evaluation_policy import BASE_CHECKS

STATUSES = ("VERIFIED", "FAILED", "UNKNOWN", "NOT_EVALUATED", "NOT_APPLICABLE", "UNSUPPORTED")


def evidence_coverage(
    review: dict, measured: dict, bound: dict, config: dict, prior: list[dict]
) -> dict:
    checks = dict(measured["checks"])
    required = sorted(set(BASE_CHECKS) | set(config["required_hard_checks"]))
    for key in required:
        if key not in checks:
            checks[key] = {
                **bound,
                "check_id": key,
                "check_version": 1,
                "status": "UNSUPPORTED",
                "reason": "No implementation for this explicitly requested hard check.",
                "coverage": {"numerator": 0, "denominator": 1},
                "evidence_refs": measured["metrics"][0]["evidence_refs"],
            }
    relevant = [p for p in prior if p["candidate_id"] == bound["candidate_id"]]
    if relevant and any(any(p[k] != bound[k] for k in bound) for p in relevant):
        checks["candidate_integrity"] = {
            **checks["candidate_integrity"],
            "status": "UNKNOWN",
            "reason": "Stale supplied evidence binding; recomputed facts remain separate. Replace old evidence.",
        }
    counts = Counter(c["status"] for c in checks.values())
    failed = sorted(k for k, c in checks.items() if c["status"] == "FAILED")
    unsupported = sorted(k for k in required if checks[k]["status"] == "UNSUPPORTED")
    pending = sorted(k for k in required if checks[k]["status"] in {"UNKNOWN", "NOT_EVALUATED"})
    eligibility = (
        "INELIGIBLE"
        if failed
        else "UNSUPPORTED"
        if unsupported
        else "PENDING_VERIFICATION"
        if pending
        else "ELIGIBLE"
    )
    applicable = len(checks) - counts["NOT_APPLICABLE"]
    declared = {
        "openings": review.get("openings_complete") is True,
        "stairs": review.get("stairs_complete") is True,
        "fixed_obstacles": review.get("fixed_obstacles_complete") is True,
        "source_brief": bool(review["candidate"]["geometry"].get("zoning")),
    }
    return {
        "schema_version": 1,
        **bound,
        "checks": [checks[k] for k in sorted(checks)],
        "counts": {
            "total": len(checks),
            "applicable": applicable,
            "not_applicable": counts["NOT_APPLICABLE"],
            "evaluated": counts["VERIFIED"] + counts["FAILED"],
            **{s.lower(): counts[s] for s in STATUSES if s != "NOT_APPLICABLE"},
        },
        "evaluation_coverage": (counts["VERIFIED"] + counts["FAILED"]) / applicable
        if applicable
        else None,
        "verified_coverage": counts["VERIFIED"] / applicable if applicable else None,
        "input_completeness": {
            "complete_sections": sum(declared.values()),
            "applicable_sections": len(declared),
            "declared": declared,
        },
        "eligibility": eligibility,
        "failed_checks": failed,
        "pending_checks": pending,
        "unsupported_checks": unsupported,
        "required_checks": required,
        "confidence_estimated": False,
    }
