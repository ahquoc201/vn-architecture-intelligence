"""Versioned, explicit evaluation policy and content bindings."""

from copy import deepcopy
from typing import Any

from vnai.contracts import canonical_digest, issue, schema_check
from vnai.review_common import candidate_digest, design_digest

METRIC_VERSION = "bounded-floorplan-metrics-v1"
BASE_CHECKS = (
    "candidate_integrity",
    "spatial_geometry",
    "room_inventory",
    "floor_assignments",
    "room_area_bounds",
    "required_relationships",
)


def validate_policy(request: Any, report: dict) -> dict | None:
    if not schema_check(request, "candidate-evaluation-input.schema.json", report):
        return None
    for alternative in request["candidates"]:
        review = alternative["review"]
        geometry = review["candidate"]["geometry"]
        polygons = (
            geometry["polygons"]
            + review.get("fixed_obstacles", [])
            + review.get("clearance_regions", [])
        )
        vertices = [
            point
            for row in polygons
            for ring in [row["exterior"], *row.get("holes", [])]
            for point in ring
        ]
        if (
            len(polygons) > 500
            or len(vertices) > 10000
            or any(abs(v) > 1e9 for point in vertices for v in point)
        ):
            issue(
                report,
                "errors",
                "EVALUATION_RESOURCE_LIMIT",
                alternative["id"],
                "Evaluation supports <=500 combined polygons, <=10000 vertices and coordinate magnitude <=1e9 declared units; no infeasibility claim.",
            )
    current_ids = {c["review"]["candidate"]["candidate_id"] for c in request["candidates"]}
    if any(p["candidate_id"] not in current_ids for p in request.get("prior_evidence", [])):
        issue(
            report,
            "errors",
            "UNBOUND_PRIOR_EVIDENCE",
            "prior_evidence",
            "Prior evidence must name a submitted candidate; no evidence is imported by resemblance.",
        )
    config = deepcopy(request["config"])
    ids = [c["id"] for c in config["criteria"]]
    alternatives = [c["id"] for c in request["candidates"]]
    bindings = [
        (candidate_digest(c["review"]["candidate"]), design_digest(c["review"]))
        for c in request["candidates"]
    ]
    if len(set(ids)) != len(ids) or len(set(alternatives)) != len(alternatives):
        issue(
            report, "errors", "DUPLICATE_ID", "$", "Criterion and alternative IDs must be unique."
        )
    if len(set(bindings)) != len(bindings):
        issue(
            report,
            "errors",
            "DUPLICATE_CONTENT",
            "candidates",
            "Identical designs cannot be independent alternatives.",
        )
    for c in config["criteria"]:
        if any(abs(c[k]) > 1e100 for k in ("weight", "lower", "upper", "target") if k in c):
            issue(
                report,
                "errors",
                "POLICY_NUMERIC_RANGE",
                c["id"],
                "Policy magnitudes above 1e100 are unsupported computational inputs.",
            )
        if (
            c["lower"] >= c["upper"]
            or (
                c["direction"] == "target"
                and ("target" not in c or not c["lower"] < c["target"] < c["upper"])
            )
            or (c["direction"] != "target" and "target" in c)
        ):
            issue(
                report,
                "errors",
                "INVALID_NORMALIZATION",
                c["id"],
                "Use increasing bounds and an interior target only for target direction.",
            )
    scope = config["comparison_scope"]
    if scope["mode"] == "explicit_metric_basis" and not (
        scope.get("baseline_digests") and scope.get("metric_ids") and scope.get("rationale")
    ):
        issue(
            report,
            "errors",
            "COMPARISON_SCOPE_REQUIRED",
            "config.comparison_scope",
            "Explicit scope needs named baselines, metric IDs and a rationale.",
        )
    config["criteria"].sort(key=lambda c: c["id"])
    config["required_hard_checks"] = sorted(set(config["required_hard_checks"]))
    for key in ("baseline_digests", "metric_ids"):
        if key in scope:
            scope[key] = sorted(set(scope[key]))
    return None if report["errors"] else config


def binding(review: dict, policy: dict) -> dict:
    result = {
        "candidate_id": review["candidate"]["candidate_id"],
        "candidate_digest": candidate_digest(review["candidate"]),
        "design_digest": design_digest(review),
        "policy_digest": canonical_digest(policy),
    }
    return {**result, "evaluation_digest": canonical_digest({**result, "metrics": METRIC_VERSION})}


def baseline(review: dict) -> dict:
    geometry = review["candidate"]["geometry"]
    zoning = geometry.get("zoning", {})
    # Deliberately conservative: differing coordinate conventions or immutable context
    # require an explicit scope, even when a user believes them equivalent.
    context = {k: geometry[k] for k in ("project_id", "units", "frame", "floors", "tolerances")}
    context["polygons"] = sorted(
        [
            {k: v for k, v in p.items() if k not in {"approval", "status"}}
            for p in geometry["polygons"]
            if p["role"] != "room"
        ],
        key=lambda p: p["id"],
    )
    parts = {
        "brief": canonical_digest(zoning.get("brief")),
        "context": canonical_digest(context),
        "inventory": canonical_digest(
            {k: zoning.get(k) for k in ("assignments", "floors", "constraints", "assumptions")}
        ),
        "metric_definitions": METRIC_VERSION,
    }
    return {**parts, "digest": canonical_digest(parts)}
