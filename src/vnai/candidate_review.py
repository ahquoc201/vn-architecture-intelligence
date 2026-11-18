"""Explicit content-bound candidate selection/review records, without authentication."""

from datetime import datetime
from copy import deepcopy
from typing import Any

from vnai.contracts import finish, issue
from vnai.review_common import (
    build_context,
    candidate_digest,
    design_digest,
    stage_report,
    ReviewContext,
)

__all__ = ["review_candidate", "candidate_digest", "design_digest"]


def review_records(ctx: ReviewContext) -> dict:
    result = stage_report(
        ctx,
        "candidate-review-v1",
        review_state="UNSELECTED",
        decision_history=[],
        selection_record=None,
        approval_record_valid=False,
        geometry_status=ctx.geometry_status,
        source_candidate_preserved=True,
        unsupported_evaluations=[
            "ARCHITECT_IDENTITY_NOT_AUTHENTICATED",
            "ORIGINAL_SOLVER_DIMENSION_INPUT_NOT_REPLAYED",
        ],
    )
    if ctx.report["errors"] or ctx.geometry_status != "VALID":
        return result
    result["decision_history"] = deepcopy(ctx.spec.get("decisions", []))
    result["selection_record"] = deepcopy(ctx.spec.get("selection"))
    selection = ctx.spec.get("selection")
    if not selection:
        issue(
            result,
            "missing_information",
            "CANDIDATE_SELECTION_REQUIRED",
            "selection",
            "Select a candidate by exact ID and content digest.",
        )
        return finish(result)
    if (
        selection["candidate_id"] != result["candidate_id"]
        or selection["candidate_digest"] != result["candidate_digest"]
    ):
        issue(
            result,
            "errors",
            "CANDIDATE_SELECTION_MISMATCH",
            "selection",
            "Selection does not match the supplied immutable candidate.",
        )
        return finish(result)
    state, previous = "SELECTED", None
    ids = set()
    allowed = {
        "SELECTED": {"REVIEWED", "REJECTED", "SUPERSEDED"},
        "REVIEWED": {"APPROVED", "REJECTED", "SUPERSEDED"},
        "APPROVED": {"REJECTED", "SUPERSEDED"},
        "REJECTED": set(),
        "SUPERSEDED": set(),
    }
    for index, event in enumerate(ctx.spec.get("decisions", [])):
        path = "decisions." + event["id"]
        valid = True
        if event["id"] in ids:
            issue(
                result, "errors", "DUPLICATE_REVIEW_DECISION", path, "Decision IDs must be unique."
            )
            valid = False
        ids.add(event["id"])
        next_state = event["state"]
        if not (index == 0 and next_state == "SELECTED") and next_state not in allowed[state]:
            issue(
                result,
                "errors",
                "REVIEW_TRANSITION",
                path,
                f"Invalid transition: {state} to {next_state}.",
            )
            valid = False
        record = event["record"]
        if record["digest"] != result["design_digest"]:
            issue(
                result,
                "errors",
                "STALE_DESIGN_REVIEW",
                path,
                "Review record does not match exact candidate/openings/stairs/clearance content.",
            )
            valid = False
        if next_state in {"REVIEWED", "APPROVED"} and record["role"] != "architect":
            issue(
                result,
                "errors",
                "ARCHITECT_REVIEW_ROLE",
                path,
                "Review/approval requires an explicit architect role; no identity is inferred.",
            )
            valid = False
        stamp = datetime.fromisoformat(record["recorded_at"].upper().replace("Z", "+00:00"))
        if previous is not None and stamp < previous:
            issue(
                result,
                "errors",
                "REVIEW_TIMESTAMP_ORDER",
                path,
                "Review event timestamps must be nondecreasing.",
            )
            valid = False
        previous = stamp
        if valid:
            state = next_state
    result["review_state"] = state
    result["approval_record_valid"] = state == "APPROVED" and not result["errors"]
    return finish(result)


def review_candidate(value: Any) -> dict:
    return review_records(build_context(value))
