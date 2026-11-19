"""Human-readable workflow reports, with immutable machine-readable evidence."""

import json

EXIT_CODES = {
    "VERIFIED": 0,
    "FAILED": 1,
    "INVALID_INPUT": 1,
    "INCOMPLETE": 3,
    "STALE": 4,
    "UNSUPPORTED": 5,
    "READY_FOR_DRAFTING": 0,
    "NOT_READY": 1,
}


def workflow_exit(report: dict) -> int:
    for field in ("replay_status", "revision_status", "readiness_status"):
        if field in report:
            return EXIT_CODES[report[field]]
    if report.get("benchmark_status") == "INVALID_INPUT":
        return 1
    return {
        "GENERATED": 0,
        "INVALID_INPUT": 1,
        "INCOMPLETE": 3,
        "INFEASIBLE": 4,
        "UNSUPPORTED": 5,
        "SEARCH_EXHAUSTED": 6,
    }[report["generation"]["status"]]


def workflow_markdown(report: dict) -> str:
    state = next(
        (
            report[k]
            for k in ("replay_status", "revision_status", "readiness_status", "benchmark_status")
            if k in report
        ),
        report["status"],
    )
    lines = [
        "# " + report["contract"],
        "",
        "Engine: " + report["engine_version"],
        "State: " + state,
        "",
        "CAD writes: false. Construction readiness: NOT_EVALUATED. No approval is granted.",
        "Digests bind content; reviewer identity/professional credentials are not authenticated.",
        "",
    ]
    for key in (
        "candidate_digest",
        "design_digest",
        "specification_digest",
        "provenance_digest",
        "revision_digest",
        "scope",
        "policy_digest",
        "coverage",
        "blocking_issues",
        "missing_dependencies",
        "unsupported_checks",
        "baseline_status",
        "diff",
        "changed_rooms",
        "affected_constraints",
        "stale_evidence",
        "unresolved_feedback",
        "approval_invalidated",
        "child_approval_record_valid",
        "unchanged_evidence_dependencies",
        "feedback_results",
        "stages",
        "metrics",
        "architectural_requests",
        "human_review_status",
        "expert_oracle_status",
    ):
        if key in report:
            lines += [
                "## " + key.replace("_", " "),
                "",
                "```json",
                json.dumps(report[key], ensure_ascii=True, indent=2, allow_nan=False),
                "```",
                "",
            ]
    if "checks" in report:
        lines += [
            "## Constraint/gate results",
            "",
            "| Check | Status | Observed | Required | Method / next dependency |",
            "| --- | --- | --- | --- | --- | --- |",
        ]

        def cell(value: object) -> str:
            text = (
                json.dumps(value, ensure_ascii=True, sort_keys=True)
                if isinstance(value, (dict, list))
                else str(value)
            )
            return text.replace("|", "\\|").replace("\n", " ")

        for check in report["checks"]:
            values = [
                check["id"],
                check["status"],
                check.get("observed"),
                check.get("expected"),
                check.get("method", check.get("reason")),
            ]
            lines.append("| " + " | ".join(cell(v) for v in values) + " |")
        lines += [
            "",
            "Exact content digests and per-check source references are retained in the accompanying JSON report.",
            "",
        ]
    for bucket in ("errors", "missing_information", "warnings"):
        if report[bucket]:
            lines += ["## " + bucket.replace("_", " "), ""]
            lines.extend(
                "- " + d["code"] + " (" + d["path"] + "): " + d["message"] for d in report[bucket]
            )
            lines.append("")
    lines += [
        "Next: provide missing dependencies, resolve blocking feedback and obtain explicit review of the exact revision. A drafting gate does not authorize CAD operations.",
        "",
    ]
    return "\n".join(lines)
