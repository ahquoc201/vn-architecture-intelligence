"""Content-bound external revisions and human-supplied feedback; no redesign."""

from typing import Any

from vnai.candidate_review import review_candidate
from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.design_replay import validate_replay
from vnai.review_common import candidate_digest, design_digest


def compare_revision(value: Any) -> dict:
    result = new_report("design-revision-v1")
    result.update(
        revision_status="INVALID_INPUT",
        revision_digest=None,
        diff={},
        changed_rooms=[],
        affected_constraints=[],
        stale_evidence=[],
        unresolved_feedback=[],
        feedback_results=[],
        approval_inherited=False,
        approval_invalidated=True,
        child_approval_record_valid=False,
        parent_review={},
        child_review={},
        replay=None,
        unchanged_evidence_dependencies=[],
        sources={},
    )
    if not schema_check(value, "design-revision.schema.json", result):
        return result
    parent, child = value["parent_review"], value["child_review"]
    result["sources"]["revision"] = value
    result["revision_digest"] = canonical_digest(value)
    for label, review in (("parent", parent), ("child", child)):
        for name, actual in (
            ("candidate_digest", candidate_digest(review["candidate"])),
            ("design_digest", design_digest(review)),
        ):
            if value[label + "_" + name] != actual:
                issue(
                    result,
                    "errors",
                    "REVISION_BINDING_MISMATCH",
                    label + "_" + name,
                    "Revision references exact immutable candidate/design content.",
                )
    if value["parent_revision_id"] == value["child_revision_id"]:
        issue(
            result,
            "errors",
            "REVISION_CYCLE",
            "child_revision_id",
            "Parent and child revision identifiers must differ.",
        )
    pc, cc = parent["candidate"], child["candidate"]
    pg, cg = pc["geometry"], cc["geometry"]

    def room_rows(geometry: dict) -> dict:
        return {r["room_id"]: r for r in geometry["polygons"] if r["role"] == "room"}

    pr, cr = room_rows(pg), room_rows(cg)
    changed = sorted(k for k in set(pr) | set(cr) if pr.get(k) != cr.get(k))
    changed_keys = sorted(
        k for k in set(parent) | set(child) if k != "decisions" and parent.get(k) != child.get(k)
    )
    brief_changed = any(
        pg.get("zoning", {}).get(k) != cg.get("zoning", {}).get(k)
        for k in ("brief", "floors", "assignments", "constraints", "assumptions")
    )
    result["changed_rooms"] = changed
    result["diff"] = {
        "added_rooms": sorted(set(cr) - set(pr)),
        "removed_rooms": sorted(set(pr) - set(cr)),
        "changed_review_sections": changed_keys,
        "requirement_baseline_changed": brief_changed,
        "parent_brief_digest": canonical_digest(pg.get("zoning", {}).get("brief")),
        "child_brief_digest": canonical_digest(cg.get("zoning", {}).get("brief")),
        "parent_candidate_digest": candidate_digest(pc),
        "child_candidate_digest": candidate_digest(cc),
        "parent_design_digest": design_digest(parent),
        "child_design_digest": design_digest(child),
    }
    design_changed = design_digest(parent) != design_digest(child)
    if pg != cg:
        result["affected_constraints"] += [
            "room_inventory",
            "traceability",
            "area_bounds",
            "dimension_bounds",
            "floor_assignments",
            "containment",
            "overlap",
            "reservations",
            "required_adjacency",
        ]
    if design_changed:
        result["affected_constraints"] += [
            "candidate_review",
            "openings",
            "circulation",
            "stairs",
            "clearance",
            "evaluation",
        ]
        result["stale_evidence"] = [
            "parent_candidate_review",
            "parent_architectural_review",
            "parent_evaluation",
        ]
    if brief_changed:
        result["affected_constraints"].append("requirement_baseline")
        confirmation = value.get("baseline_revision")
        if value["change_origin"] != "user_confirmed_requirement_change" or not confirmation:
            issue(
                result,
                "missing_information",
                "REVISED_BASELINE_REQUIRED",
                "baseline_revision",
                "Requirements changed: supply explicit user-confirmed revised specification; old baseline is not interchangeable.",
            )
    if value["change_origin"] == "unresolved_assumption":
        issue(
            result,
            "missing_information",
            "UNRESOLVED_ASSUMPTION",
            "change_origin",
            "A proposed assumption is not a confirmed design requirement.",
        )
    for name in (
        "geometry",
        "openings",
        "stairs",
        "fixed_obstacles",
        "clearance_regions",
        "passages",
    ):
        if parent.get(name) == child.get(name) and not design_changed:
            result["unchanged_evidence_dependencies"].append(name)
    # More precise unchanged factual dependencies, without reusing whole reports.
    if pg == cg:
        result["unchanged_evidence_dependencies"].append("candidate_geometry")
    if not brief_changed:
        result["unchanged_evidence_dependencies"].append("source_brief")
    parent_context = value.get("parent_replay_context")
    if parent_context is None:
        parent_context = {"schema_version": 1, "review": parent, "mode": "revision"}
        if "provenance" in value:
            parent_context["provenance"] = value["provenance"]
    parent_replay = validate_replay(parent_context)
    result["sources"]["parent_replay"] = parent_replay
    parent_binding_ok = parent_context["review"] == parent and all(
        any(c["id"] == key and c["status"] == "VERIFIED" for c in parent_replay["checks"])
        for key in ("provenance_integrity", "requirement_baseline")
    )
    if not parent_binding_ok:
        issue(
            result,
            "missing_information",
            "PARENT_BASELINE_UNVERIFIED",
            "parent_replay_context",
            "Parent content must bind to verifiable original or explicitly revised source provenance; physical defects may still be corrected in the child.",
        )
    result["parent_review"] = review_candidate(parent)
    result["child_review"] = review_candidate(child)
    parent_approval_ids = {
        e["id"] for e in parent.get("decisions", []) if e["state"] in {"REVIEWED", "APPROVED"}
    }
    copied = any(
        e["id"] in parent_approval_ids and e["state"] in {"REVIEWED", "APPROVED"}
        for e in child.get("decisions", [])
    )
    result["approval_invalidated"] = design_changed or copied
    result["child_approval_record_valid"] = (
        result["child_review"]["approval_record_valid"] and not copied
    )
    if copied:
        result["stale_evidence"].append("copied_parent_approval")
        issue(
            result,
            "missing_information",
            "FRESH_REVISION_REVIEW_REQUIRED",
            "child_review.decisions",
            "Parent approval events are not inherited by a new proposal; supply separate child review records.",
        )
    known_rooms = set(pr) | set(cr)
    known_geometry = {r["id"] for g in (pg, cg) for r in g["polygons"]}
    known_requirements = {
        r["id"]
        for g in (pg, cg)
        for r in g.get("zoning", {}).get("brief", {}).get("requirements", [])
    }
    feedback = value["feedback"]
    ids = [f["id"] for f in feedback]
    if len(ids) != len(set(ids)):
        issue(
            result,
            "errors",
            "DUPLICATE_FEEDBACK",
            "feedback",
            "Feedback identifiers must be unique.",
        )
    edges = {f["id"]: f["supersedes"] for f in feedback}
    superseded_by = {key: [] for key in ids}
    for f in feedback:
        for old in f["supersedes"]:
            if old not in edges or old == f["id"]:
                issue(
                    result,
                    "errors",
                    "FEEDBACK_SUPERSESSION_REFERENCE",
                    f["id"],
                    "Supersession references an existing distinct feedback item.",
                )
            else:
                superseded_by[old].append(f["id"])

    colors: dict[str, int] = {}

    def cyclic(node: str) -> bool:
        if colors.get(node) == 1:
            return True
        if colors.get(node) == 2:
            return False
        colors[node] = 1
        if any(cyclic(other) for other in edges.get(node, []) if other in edges):
            return True
        colors[node] = 2
        return False

    if any(cyclic(key) for key in edges):
        issue(
            result,
            "errors",
            "FEEDBACK_SUPERSESSION_CYCLE",
            "feedback",
            "Feedback supersession must be acyclic.",
        )
    for f in sorted(feedback, key=lambda f: f["id"]):
        target = f["target"]
        target_matches = any(
            target
            == {
                "candidate_id": r["candidate"]["candidate_id"],
                "candidate_digest": candidate_digest(r["candidate"]),
                "design_digest": design_digest(r),
            }
            for r in (parent, child)
        )
        references_valid = (
            set(f["affected_room_ids"]) <= known_rooms
            and set(f["affected_geometry_ids"]) <= known_geometry
            and set(f["requirement_ids"]) <= known_requirements
        )
        resolution = f.get("resolution_record")
        resolution_valid = bool(
            resolution
            and resolution["reviewer"]["role"] == "architect"
            and resolution["child_design_digest"] == design_digest(child)
        )
        resolved = f["resolution"] in {"VERIFIED", "WITHDRAWN"} and resolution_valid
        if f["resolution"] == "SUPERSEDED":
            resolved = bool(superseded_by[f["id"]]) and resolution_valid
        state = (
            "RESOLVED"
            if resolved and target_matches and references_valid
            else "STALE"
            if not target_matches
            else "OPEN"
        )
        if not references_valid:
            issue(
                result,
                "errors",
                "FEEDBACK_REFERENCE",
                f["id"],
                "Affected room, geometry and requirement IDs must exist in the parent/child baselines.",
            )
        if not target_matches:
            issue(
                result,
                "missing_information",
                "STALE_FEEDBACK_TARGET",
                f["id"],
                "Feedback must reference the exact parent or child candidate and design.",
            )
        if f["blocking"] and state != "RESOLVED":
            result["unresolved_feedback"].append(f["id"])
        result["feedback_results"].append(
            {
                "id": f["id"],
                "status": state,
                "blocking": f["blocking"],
                "declared_resolution": f["resolution"],
                "reviewer_identity_authenticated": False,
            }
        )
    if result["unresolved_feedback"]:
        issue(
            result,
            "missing_information",
            "BLOCKING_FEEDBACK_OPEN",
            "feedback",
            "Unresolved blocking feedback requires an explicit architect resolution bound to the child design.",
        )
    replay_input = {"schema_version": 1, "review": child, "mode": "revision"}
    for name in ("provenance", "baseline_revision"):
        if name in value:
            replay_input[name] = value[name]
    result["replay"] = validate_replay(replay_input)
    replay_status = result["replay"]["replay_status"]
    if replay_status != "VERIFIED":
        issue(
            result,
            "missing_information",
            "REVISION_REPLAY_REQUIRED",
            "replay",
            "Current child constraint replay: " + replay_status,
        )
    if result["child_review"]["errors"] or result["child_review"]["missing_information"]:
        issue(
            result,
            "missing_information",
            "CHILD_REVIEW_REQUIRED",
            "child_review",
            "Current child review/selection records require resolution; old approval is not a substitute.",
        )
    result["affected_constraints"] = sorted(set(result["affected_constraints"]))
    result["unchanged_evidence_dependencies"] = sorted(
        set(result["unchanged_evidence_dependencies"])
    )
    result["revision_status"] = (
        "INVALID_INPUT"
        if result["errors"]
        else "FAILED"
        if replay_status == "FAILED"
        else "STALE"
        if replay_status == "STALE"
        or any(f["status"] == "STALE" for f in result["feedback_results"])
        else "INCOMPLETE"
        if result["missing_information"]
        else "VERIFIED"
    )
    return finish(result)
