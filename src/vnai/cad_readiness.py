"""Explicit drafting-information gates; never CAD write authorization."""

from typing import Any

from vnai.architectural_review import architectural_review
from vnai.candidate_evaluation import evaluate_candidates
from vnai.candidate_metrics import PHYSICAL_FAILURES
from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.design_provenance import bounded_geometry
from vnai.design_replay import validate_replay
from vnai.design_revision import compare_revision
from vnai.review_common import candidate_digest, design_digest
from vnai.space_program import build_space_program
from vnai.spatial import validate_geometry
from vnai.zoning import validate_zoning


def readiness_report(value: Any) -> dict:
    result = new_report("cad-readiness-v1")
    result.update(
        readiness_status="INVALID_INPUT",
        scope=[],
        policy_digest=None,
        checks=[],
        stages={},
        sources={},
        construction_readiness="NOT_EVALUATED",
        approval_granted=False,
    )
    if not schema_check(value, "cad-readiness.schema.json", result):
        return result
    replay_input = value["replay"]
    review = replay_input["review"]
    if not bounded_geometry(review):
        issue(
            result, "errors", "RESOURCE_LIMIT", "replay.review", "Geometry resource scope exceeded."
        )
        return result
    policy = value["policy"]
    result.update(
        scope=sorted(policy["requested_stages"]),
        policy_digest=canonical_digest(
            {**policy, "requested_stages": sorted(policy["requested_stages"])}
        ),
    )
    geometry = review["candidate"]["geometry"]
    zoning = geometry.get("zoning")
    architecture = architectural_review(review)
    replay = validate_replay(replay_input)
    spatial = validate_geometry(geometry)
    program = build_space_program(zoning["brief"]) if zoning else None
    governed = validate_zoning(zoning) if zoning else None
    result["sources"].update(
        request=value,
        replay=replay,
        architectural_review=architecture,
        spatial=spatial,
        program=program,
        zoning=governed,
    )

    def check(key: str, status: str, reason: str) -> None:
        result["checks"].append({"id": key, "status": status, "reason": reason})

    check(
        "brief_program",
        "VERIFIED" if program and program["status"] == "VALID" else "UNKNOWN",
        "Actual brief/program completeness, not inferred from generated status.",
    )
    check(
        "zoning",
        "VERIFIED"
        if governed and governed["status"] == "VALID" and governed["architect_approved"]
        else "UNKNOWN",
        "Current source zoning must be complete, consistent and content-bound.",
    )
    replay_state = {
        "VERIFIED": "VERIFIED",
        "FAILED": "FAILED",
        "STALE": "UNKNOWN",
        "INCOMPLETE": "UNKNOWN",
        "UNSUPPORTED": "UNSUPPORTED",
        "INVALID_INPUT": "UNKNOWN",
    }[replay["replay_status"]]
    check("original_hard_replay", replay_state, "Independent replay: " + replay["replay_status"])
    check(
        "geometry",
        "VERIFIED"
        if spatial["status"] == "VALID"
        else "FAILED"
        if replay["replay_status"] == "FAILED"
        else "UNKNOWN",
        "Current spatial validation; source/reference errors do not prove physical failure.",
    )
    current_review = architecture["candidate_review"]
    levels = {
        "UNSELECTED": 0,
        "SELECTED": 1,
        "REVIEWED": 2,
        "APPROVED": 3,
        "REJECTED": -1,
        "SUPERSEDED": -1,
    }
    state = current_review["review_state"]
    required = policy["required_review_state"]
    review_ok = (
        levels[state] >= levels[required]
        and not current_review["errors"]
        and bool(review.get("selection"))
    )
    check(
        "selection_review",
        "VERIFIED" if review_ok else "FAILED" if state in {"REJECTED", "SUPERSEDED"} else "UNKNOWN",
        "Required "
        + required
        + "; current "
        + state
        + ". Declared identities are not authenticated.",
    )
    for field, source, verified, failure in (
        (
            "require_openings",
            architecture["opening_validation"],
            architecture["opening_validation"]["status"] == "VALID",
            False,
        ),
        (
            "require_graph",
            architecture["circulation_graph"],
            architecture["graph_status"] == "GRAPH_CONNECTED",
            architecture["graph_status"] == "BLOCKED",
        ),
        (
            "require_clearance",
            architecture["clearance"],
            architecture["physical_circulation_status"] == "GEOMETRICALLY_TRAVERSABLE",
            architecture["physical_circulation_status"] == "BLOCKED",
        ),
    ):
        if policy[field]:
            check(
                field,
                "VERIFIED" if verified else "FAILED" if failure else "UNKNOWN",
                "Required current scoped review: " + source["contract"],
            )
    # Never hide a known physical failure merely because a preliminary policy omits that check.
    known = architecture["physical_circulation_status"] == "BLOCKED" or any(
        e["code"] in PHYSICAL_FAILURES for e in architecture["opening_validation"]["errors"]
    )
    check(
        "known_circulation_conflicts",
        "FAILED" if known else "VERIFIED",
        "No positive claim about missing routes: only observed BLOCKED conflicts disqualify.",
    )
    if any(
        e["code"]
        in {
            "STAIR_DIRECTION",
            "STAIR_ALIGNMENT",
            "STAIR_FIXED_COLLISION",
            "STAIR_OUTSIDE_ENVELOPE",
            "STAIR_CONNECTION_POINT",
            "STAIR_SAME_FLOOR",
        }
        for e in architecture["stair_validation"]["errors"]
    ):
        check(
            "known_stair_conflicts",
            "FAILED",
            "Known supplied stair geometry/direction conflicts remain blocking even when an inter-floor stair is not otherwise applicable.",
        )
    if len(geometry["floors"]) > 1:
        stairs = architecture["stair_validation"]
        stair_known_failure = any(
            e["code"]
            in {
                "STAIR_DIRECTION",
                "STAIR_ALIGNMENT",
                "STAIR_FIXED_COLLISION",
                "STAIR_OUTSIDE_ENVELOPE",
                "STAIR_CONNECTION_POINT",
                "STAIR_SAME_FLOOR",
            }
            for e in stairs["errors"]
        )
        check(
            "multi_floor_stair_information",
            "FAILED"
            if stair_known_failure
            else "VERIFIED"
            if stairs["status"] == "VALID"
            and review.get("stairs_complete") is True
            and bool(stairs["stair_results"])
            else "UNKNOWN",
            "Multiple floors require explicit confirmed vertical links; detailed stair drafting remains separate.",
        )
    else:
        check(
            "multi_floor_stair_information",
            "NOT_APPLICABLE",
            "Single-floor design needs no inter-floor stair connection.",
        )
    config = value.get("evaluation_config")
    prior = value.get("prior_evidence", [])
    if policy["require_evaluation"] or prior:
        if not config:
            check(
                "candidate_evaluation",
                "UNKNOWN",
                "Explicit evaluation policy is required; no default scoring preferences.",
            )
        else:
            evaluation = evaluate_candidates(
                {
                    "schema_version": 1,
                    "config": config,
                    "candidates": [{"id": "CURRENT", "review": review}],
                    "prior_evidence": prior,
                }
            )
            result["sources"]["evaluation"] = evaluation
            e = evaluation["evaluations"][0] if evaluation["evaluations"] else None
            ok = (
                e
                and e["evidence"]["eligibility"] == "ELIGIBLE"
                and e["scoring"]["status"] == "SCORED"
            )
            failure = bool(e and e["evidence"]["eligibility"] == "INELIGIBLE")
            unsupported = bool(
                e
                and (
                    e["evidence"]["eligibility"] == "UNSUPPORTED"
                    or any(
                        c["metric_status"] == "UNSUPPORTED" and c["status"] == "WITHHELD"
                        for c in e["scoring"]["criteria"]
                    )
                )
            )
            if any(
                error["code"]
                in {
                    "INVALID_NORMALIZATION",
                    "POLICY_NUMERIC_RANGE",
                    "COMPARISON_SCOPE_REQUIRED",
                    "DUPLICATE_ID",
                }
                for error in evaluation["errors"]
            ):
                issue(
                    result,
                    "errors",
                    "INVALID_EVALUATION_POLICY",
                    "evaluation_config",
                    "Correct the explicit evaluation policy before assessing drafting readiness.",
                )
            check(
                "candidate_evaluation",
                "VERIFIED"
                if ok
                else "FAILED"
                if failure
                else "UNSUPPORTED"
                if unsupported
                else "UNKNOWN",
                "Recomputed current evidence/required criteria; score magnitude never grants readiness.",
            )
    revision_value = value.get("revision")
    if revision_value:
        revision = compare_revision(revision_value)
        result["sources"]["revision"] = revision
        matches = revision_value["child_candidate_digest"] == candidate_digest(
            review["candidate"]
        ) and revision_value["child_design_digest"] == design_digest(review)
        same_provenance = revision_value.get("provenance") == replay_input.get(
            "provenance"
        ) and revision_value.get("baseline_revision") == replay_input.get("baseline_revision")
        check(
            "revision_review",
            "VERIFIED"
            if matches and same_provenance and revision["revision_status"] == "VERIFIED"
            else "FAILED"
            if revision["revision_status"] == "FAILED"
            else "UNKNOWN",
            "Exact child/provenance binding, independently replayed constraints and resolved blocking feedback.",
        )
        if (
            revision["approval_invalidated"]
            and not revision["child_approval_record_valid"]
            and required == "APPROVED"
        ):
            check(
                "fresh_child_approval",
                "UNKNOWN",
                "Parent approval cannot satisfy required child approval.",
            )
    elif policy["require_revision_review"] or replay_input["mode"] == "revision":
        check(
            "revision_review",
            "UNKNOWN",
            "Revision mode requires an explicit parent-child feedback/review record.",
        )
    base_status = _status([c["status"] for c in result["checks"]])
    info = value["drafting_information"]
    rooms = [r["room_id"] for r in geometry["polygons"] if r["role"] == "room"]
    result["stages"]["room_geometry"] = {
        "status": base_status,
        "scope": "SUPPLIED_ROOM_POLYGONS_ONLY",
        "prerequisites": []
        if base_status == "READY_FOR_DRAFTING"
        else [
            c["id"] for c in result["checks"] if c["status"] not in {"VERIFIED", "NOT_APPLICABLE"}
        ],
    }
    for stage, field in (
        ("architectural_walls_openings", "wall_opening_information"),
        ("stairs", "stair_drafting_information"),
    ):
        if stage == "stairs" and len(geometry["floors"]) == 1:
            result["stages"][stage] = {
                "status": "NOT_APPLICABLE",
                "scope": "NO_INTER_FLOOR_STAIR",
                "prerequisites": [],
            }
        else:
            available = info.get(field, {}).get("available") is True
            result["stages"][stage] = {
                "status": "UNSUPPORTED" if available else "INCOMPLETE",
                "scope": "EXTERNAL_INFORMATION_NOT_VALIDATED_FOR_DRAFTING",
                "prerequisites": [
                    "Future validated wall thicknesses/assemblies and hosted opening schedules"
                    if stage != "stairs"
                    else "Future validated tread/riser/landing/headroom and detailed stair drawing contract"
                ],
            }
    annotations = info.get("annotations")
    annotation_ok = bool(
        annotations
        and annotations["units"] == geometry["units"]
        and annotations["frame_id"] == geometry["frame"]["id"]
        and set(annotations["floor_ids"]) == {f["id"] for f in geometry["floors"]}
        and len(annotations["floor_ids"]) == len(geometry["floors"])
        and sorted(r["room_id"] for r in annotations["room_labels"]) == sorted(rooms)
    )
    result["stages"]["annotations"] = {
        "status": base_status if annotation_ok else "INCOMPLETE",
        "scope": "DECLARED_LABEL_AND_SHEET_INFORMATION_ONLY",
        "prerequisites": []
        if annotation_ok
        else ["Explicit sheet title/scale and exact frame, units, floor IDs and room labels"],
    }
    requested = [result["stages"][s]["status"] for s in result["scope"]]
    result["readiness_status"] = _status([base_status, *requested])
    for c in result["checks"]:
        if c["status"] not in {"VERIFIED", "NOT_APPLICABLE"}:
            issue(
                result,
                "errors" if c["status"] == "FAILED" else "missing_information",
                "READINESS_BLOCKER",
                c["id"],
                c["reason"],
            )
    for stage in result["scope"]:
        if result["stages"][stage]["status"] not in {"READY_FOR_DRAFTING", "NOT_APPLICABLE"}:
            issue(
                result,
                "missing_information",
                "DRAFTING_INFORMATION_REQUIRED",
                stage,
                "; ".join(result["stages"][stage]["prerequisites"]),
            )
    if any(e["code"] == "INVALID_EVALUATION_POLICY" for e in result["errors"]):
        result["readiness_status"] = "INVALID_INPUT"
    return finish(result)


def _status(statuses: list[str]) -> str:
    if any(s in {"FAILED", "NOT_READY"} for s in statuses):
        return "NOT_READY"
    if "UNSUPPORTED" in statuses:
        return "UNSUPPORTED"
    if any(s in {"UNKNOWN", "INCOMPLETE"} for s in statuses):
        return "INCOMPLETE"
    return "READY_FOR_DRAFTING"
