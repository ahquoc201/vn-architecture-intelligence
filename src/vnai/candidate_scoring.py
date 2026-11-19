"""Explicit bounded normalization with no missing-value imputation."""

from decimal import Decimal, ROUND_HALF_EVEN, localcontext


def score_candidate(metrics: list[dict], evidence: dict, config: dict) -> dict:
    by_id = {m["metric_id"]: m for m in metrics}
    criteria = []
    reasons = []
    with localcontext() as ctx:
        ctx.prec = 50
        quantum = Decimal(1).scaleb(-config["score_precision"])

        def rounded(value: Decimal) -> float:
            return float(value.quantize(quantum, rounding=ROUND_HALF_EVEN))

        active = []
        for c in config["criteria"]:
            m = by_id[c["metric_id"]]
            entry = {
                **c,
                "metric_status": m["status"],
                "value": m["value"],
                "normalized_score": None,
                "effective_weight": None,
                "contribution": None,
            }
            status = m["status"]
            if status == "NOT_APPLICABLE" and config["not_applicable_criteria"] == "exclude":
                entry.update(
                    status="EXCLUDED",
                    explanation="Explicit N/A exclusion; outside weight denominator.",
                )
            elif status != "VERIFIED" or m["value"] is None:
                excluded = (
                    not c["required"]
                    and config["optional_criteria"] == "exclude_unavailable"
                    and status != "NOT_APPLICABLE"
                )
                entry.update(
                    status="EXCLUDED" if excluded else "WITHHELD",
                    explanation="Unavailable evidence; no value imputed.",
                )
                if not excluded:
                    reasons.append(c["id"] + ": " + status)
            else:
                value, lo, hi = (Decimal(str(x)) for x in (m["value"], c["lower"], c["upper"]))
                if c["direction"] == "target":
                    target = Decimal(str(c["target"]))
                    normalized = (
                        (value - lo) / (target - lo)
                        if value <= target
                        else (hi - value) / (hi - target)
                    )
                else:
                    normalized = (value - lo) / (hi - lo)
                    if c["direction"] == "minimize":
                        normalized = 1 - normalized
                normalized = max(Decimal(0), min(Decimal(1), normalized))
                entry.update(
                    status="SCORED",
                    normalized_score=rounded(normalized),
                    explanation=f"{c['direction']} in [{c['lower']}, {c['upper']}], target={c.get('target')}; clipped linear normalization, HALF_EVEN display rounding.",
                )
                active.append((entry, normalized, Decimal(str(c["weight"]))))
            criteria.append(entry)
        denominator = sum((w for _, _, w in active), Decimal(0))
        aggregate = Decimal(0)
        for entry, normalized, weight in active:
            effective = weight / denominator
            entry["effective_weight"] = rounded(effective)
            entry["contribution"] = rounded(effective * normalized)
            aggregate += effective * normalized
        if not active:
            reasons.append("No applicable verified criteria.")
        if evidence["eligibility"] != "ELIGIBLE":
            reasons.append("Hard eligibility: " + evidence["eligibility"])
        return {
            "status": "WITHHELD" if reasons else "SCORED",
            "aggregate": None if reasons else rounded(aggregate),
            "active_weight_denominator": float(denominator),
            "active_criteria": [e["id"] for e, _, _ in active],
            "criteria": criteria,
            "reasons": reasons,
            "precision": config["score_precision"],
            "rounding": "ROUND_HALF_EVEN",
            "limitations": [
                "Policy-dependent preference score; not objective architectural quality."
            ],
        }
