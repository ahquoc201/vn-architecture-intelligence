"""Independent geometry, graph, clearance and architect-record results per candidate."""

from typing import Any

from vnai.contracts import finish
from vnai.review_common import build_context, stage_report
from vnai.candidate_review import review_records
from vnai.openings import _opening_report
from vnai.stairs import _stair_report
from vnai.circulation import _graph_report
from vnai.clearance import _clearance_report


def architectural_review(value: Any) -> dict:
    ctx = build_context(value)
    review = review_records(ctx)
    openings = _opening_report(ctx)
    stairs = _stair_report(ctx, openings)
    graph = _graph_report(ctx, openings, stairs)
    clearance = _clearance_report(ctx, openings, stairs, graph)
    result = stage_report(
        ctx,
        "architectural-review-v1",
        candidate_review=review,
        opening_validation=openings,
        circulation_graph=graph,
        stair_validation=stairs,
        clearance=clearance,
        geometry_status=ctx.geometry_status,
        graph_status=graph["graph_status"],
        physical_circulation_status=clearance["physical_status"],
        technical_compliance="NOT_EVALUATED",
        architectural_approval=review["review_state"],
        fully_verified=False,
        blocking_issues=[],
        unsupported_evaluations=[
            "AUTHENTICATION_AND_SIGNATURES",
            "COMPLETE_WALL_MODEL",
            "DOOR_HARDWARE_AND_LEAF_THICKNESS",
            "STAIR_TREAD_RISER_HEADROOM",
            "FULL_ACCESSIBILITY_EGRESS_CERTIFICATION",
            "STRUCTURE_MEP",
            "QCVN_TCVN_AND_FENGSHUI_RULES",
        ],
        next_actions=[],
    )
    for bucket in ("errors", "warnings", "missing_information", "diagnostics"):
        unique = {}
        for report in (result, review, openings, stairs, graph, clearance):
            for item in report[bucket]:
                unique[
                    (item["code"], item["path"], item["message"], tuple(item["requirement_ids"]))
                ] = item
        result[bucket] = list(unique.values())
    result["blocking_issues"] = list(result["errors"])
    if result["errors"]:
        result["next_actions"].append(
            "Resolve known geometric/reference conflicts before adopting this proposal."
        )
    if result["missing_information"]:
        result["next_actions"].append(
            "Provide and confirm the listed opening, route, obstacle and stair information."
        )
    if not review["approval_record_valid"]:
        result["next_actions"].append(
            "Obtain explicit architect review/approval of the exact immutable design content."
        )
    result["next_actions"].append(
        "Keep technical/code/Feng Shui review separate; no CAD writes are permitted."
    )
    return finish(result)
