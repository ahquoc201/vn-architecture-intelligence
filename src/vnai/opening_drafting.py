"""Proposed B2 wall-hosted openings, separate from original candidates/walls."""

from copy import deepcopy
from typing import Any
from shapely.errors import GEOSException
from vnai.contracts import new_report, schema_check, canonical_digest, issue, finish
from vnai.walls import generate_walls
from vnai.review_common import build_context
from vnai.opening_hosts import resolve
from vnai.opening_primitives import build
from vnai.opening_accounting import account
from vnai.opening_replay import replay
from vnai.opening_schedule import schedule

EXIT_CODES = {"GENERATED": 0, "INVALID_INPUT": 1, "INCOMPLETE": 3, "CONFLICT": 4, "UNSUPPORTED": 5}


def normalize(value: dict) -> dict:
    value = deepcopy(value)
    spec = value["specification"]
    for k in (
        "openings",
        "wall_verticals",
        "additional_obstacles",
        "clearance_regions",
        "passages",
        "stairs",
        "exteriors",
    ):
        if k in spec:
            spec[k].sort(key=lambda r: r.get("id", r.get("wall_id", "")))
    for row in spec["openings"]:
        row["requirement_ids"] = sorted(set(row["requirement_ids"]))
        row["space_ids"] = sorted(row["space_ids"])
    return value


def reviewable(value):
    if isinstance(value, dict):
        return {k: reviewable(v) for k, v in value.items() if k != "approval"}
    if isinstance(value, list):
        return [reviewable(v) for v in value]
    return value


def draft_openings(value: Any, *, _cache=None) -> dict:
    if _cache is not None:
        return _cache.run("opening_drafting", value, lambda: _draft_openings(value, _cache))
    return _draft_openings(value, None)


def _draft_openings(value: Any, _cache) -> dict:
    result = new_report("opening-drafting-v1")
    result.update(
        drafting_status="INVALID_INPUT",
        geometry_status="NOT_GENERATED",
        source_candidate_digest=None,
        source_wall_revision_id=None,
        source_wall_geometry_digest=None,
        specification_digest=None,
        opening_geometry_digest=None,
        opening_revision_id=None,
        frame_id=None,
        units="m",
        openings=[],
        floors=[],
        rooms=[],
        schedule=[],
        circulation={},
        evidence_impact={},
        drafting_readiness={},
        sources={},
        source_conflicts=[],
        unresolved_opening_ids=[],
        approval_inherited=False,
        architect_approval="NOT_GRANTED",
    )
    if not schema_check(value, "opening-drafting-input.schema.json", result):
        return finish(result)
    value = normalize(value)
    spec = value["specification"]
    flags = set()

    def problem(kind, code, path, message):
        flags.add(kind)
        result["drafting_status"] = (
            "INVALID_INPUT"
            if "invalid" in flags
            else "CONFLICT"
            if "conflict" in flags
            else "UNSUPPORTED"
            if "unsupported" in flags
            else "INCOMPLETE"
            if "missing" in flags
            else "GENERATED"
        )
        bucket = (
            "errors"
            if kind in {"invalid", "conflict"}
            else "warnings"
            if kind == "warning"
            else "missing_information"
        )
        issue(result, bucket, code, path, message)

    result["sources"]["input"] = value

    def bounded_numbers(item, scale):
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            # Compare before multiplying so oversized JSON integers cannot overflow float conversion.
            return abs(item) <= 1e9 / scale
        if isinstance(item, dict):
            return all(bounded_numbers(v, scale) for v in item.values())
        if isinstance(item, list):
            return all(bounded_numbers(v, scale) for v in item)
        return True

    if not bounded_numbers(spec, 1 if spec["units"] == "m" else 0.001):
        problem(
            "unsupported",
            "OPENING_NUMERIC_SCOPE",
            "specification",
            "Drafting physical magnitudes are limited to 1e9 m; no overflow or approximation is attempted.",
        )
        return finish(result)
    model = generate_walls(value["source"], _cache=_cache)
    result["sources"]["wall_model"] = model
    result.update(
        source_candidate_digest=model["source_candidate_digest"],
        source_wall_revision_id=model["wall_revision_id"],
        source_wall_geometry_digest=model["derived_geometry_digest"],
        frame_id=model["frame_id"],
        specification_digest=canonical_digest(reviewable(spec)),
    )
    if (
        value["source_candidate_digest"] != model["source_candidate_digest"]
        or value["source_wall_revision_id"] != model["wall_revision_id"]
    ):
        problem(
            "invalid",
            "STALE_OPENING_SOURCE",
            "source",
            "Opening request must bind the exact current candidate and wall revision.",
        )
    if spec["frame_id"] != model["frame_id"]:
        problem(
            "invalid",
            "OPENING_COORDINATE_FRAME",
            "specification.frame_id",
            "Drafting frame must match the source wall frame; no transform is inferred.",
        )
    if not model["floors"]:
        problem(
            "invalid" if model["wall_status"] == "INVALID_INPUT" else "missing",
            "WALL_GEOMETRY_REQUIRED",
            "source",
            "No usable source wall geometry is available.",
        )
    if "invalid" in flags or not model["floors"]:
        return finish(result)
    if model["wall_status"] == "CONFLICT":
        result["source_conflicts"] = deepcopy(model["errors"])
        problem(
            "conflict",
            "SOURCE_WALL_CONFLICTS_RETAINED",
            "source",
            "Opening drafting does not resolve or relax source clear-area/reservation/design conflicts.",
        )
    elif model["wall_status"] in {"INCOMPLETE", "UNSUPPORTED"}:
        problem(
            "missing",
            "SOURCE_WALL_LIMITATIONS",
            "source",
            "Source wall information/constraint replay is incomplete or unsupported; proposed openings cannot promote it.",
        )
    if model["drafting_readiness"].get("source_status") != "READY_FOR_DRAFTING":
        problem(
            "warning",
            "SOURCE_DRAFTING_LIMITATIONS",
            "source",
            "Source drafting readiness remains limited; this proposed opening revision grants no approval.",
        )
    rows = spec["openings"]
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        problem(
            "invalid", "DUPLICATE_DRAFTING_OPENING_ID", "openings", "Opening IDs must be unique."
        )
        return finish(result)
    if "plan_cut_height" not in spec:
        problem(
            "missing",
            "PLAN_CUT_HEIGHT_REQUIRED",
            "specification",
            "Declare the project plan-cut elevation; no default height is inferred.",
        )
    known_walls = {w["id"] for w in model["walls"]}
    vertical_ids = [v["wall_id"] for v in spec.get("wall_verticals", [])]
    if len(vertical_ids) != len(set(vertical_ids)):
        problem(
            "invalid",
            "DUPLICATE_WALL_VERTICAL",
            "wall_verticals",
            "Each host needs one unambiguous vertical interval.",
        )
        return finish(result)
    if any(v["wall_id"] not in known_walls for v in spec.get("wall_verticals", [])):
        problem(
            "invalid",
            "UNKNOWN_VERTICAL_WALL",
            "wall_verticals",
            "Vertical records refer to an unknown wall.",
        )
        return finish(result)
    confirmed_verticals = {
        v["wall_id"] for v in spec.get("wall_verticals", []) if v["confirmation"] == "confirmed"
    }
    if known_walls - confirmed_verticals:
        problem(
            "missing",
            "WALL_SECTION_VERTICALS_INCOMPLETE",
            "wall_verticals",
            "The wall plan section needs confirmed base/height data for every source wall; unknown walls are retained conservatively.",
        )
    if any(v["base"] != 0 for v in spec.get("wall_verticals", [])):
        problem(
            "unsupported",
            "RAISED_WALL_BASE_UNSUPPORTED",
            "wall_verticals",
            "Raised wall bases require a separate floor-obstruction model; current floor footprint is retained as a conservative bound.",
        )
    # Supplementary 006-B sidecars are fresh declarations, never inherited clearance passes.
    sidecar = deepcopy(value["source"]["source"]["replay"]["review"])
    sidecar["exteriors"] = spec.get("exteriors", sidecar.get("exteriors", []))
    sidecar["openings"] = []
    sidecar["decisions"] = []
    sidecar["clearance_regions"] = spec.get("clearance_regions", [])
    sidecar["fixed_obstacles"] = sidecar.get("fixed_obstacles", []) + spec.get(
        "additional_obstacles", []
    )
    sidecar["fixed_obstacles_complete"] = spec.get("fixed_obstacles_complete", False)
    sidecar["openings_complete"] = spec["openings_complete"]
    for k in ("passages", "stairs"):
        sidecar[k] = spec.get(k, [])
    sidecar["stairs_complete"] = spec.get("stairs_complete", False)
    sidecar_pairs = sum(
        len(r["exterior"]) + sum(len(h) for h in r.get("holes", []))
        for k in ("fixed_obstacles", "clearance_regions")
        for r in sidecar[k]
    )
    if sidecar_pairs > 10000:
        problem(
            "invalid",
            "OPENING_RESOURCE_LIMIT",
            "specification",
            "Fresh sidecars exceed 10000 coordinate pairs.",
        )
        return finish(result)
    source_scale = 1.0 if sidecar["candidate"]["geometry"]["units"] == "m" else 0.001
    if not bounded_numbers(
        [sidecar[k] for k in ("fixed_obstacles", "clearance_regions", "passages")], source_scale
    ):
        problem(
            "unsupported",
            "OPENING_SIDECAR_NUMERIC_SCOPE",
            "specification",
            "Fresh sidecar physical coordinates exceed the bounded geometry scope.",
        )
        return finish(result)
    ctx = build_context(sidecar)
    if ctx.report["errors"]:
        for d in ctx.report["errors"]:
            problem("invalid", d["code"], d["path"], d["message"])
        return finish(result)
    records = []
    try:
        for row in rows:
            r = resolve(row, model, ctx, spec, problem)
            if row["confirmation"] != "confirmed":
                r["issues"].append("OPENING_SPEC_UNCONFIRMED")
                problem(
                    "missing",
                    "OPENING_SPEC_UNCONFIRMED",
                    row["id"],
                    "Proposed dimensions remain unconfirmed; no verified cut or circulation claim follows.",
                )
            if row["review_state"] != "proposed":
                approval = row.get("approval")
                if (
                    not approval
                    or approval["digest"] != result["specification_digest"]
                    or approval["role"] != "architect"
                ):
                    r["issues"].append("OPENING_REVIEW_RECORD_REQUIRED")
                    problem(
                        "missing",
                        "OPENING_REVIEW_RECORD_REQUIRED",
                        row["id"],
                        "Claimed specification review needs an exact bound architect record; derived geometry remains PROPOSED.",
                    )
            build(r, spec, problem)
            records.append(r)
        for i, r in enumerate(records):
            if "_cut" not in r:
                continue
            for previous in records[:i]:
                if (
                    "_cut" in previous
                    and r["floor_id"] == previous["floor_id"]
                    and r["_cut"].intersection(previous["_cut"]).area > 0
                ):
                    intervals = [
                        r.get("bottom_m"),
                        r.get("head_m"),
                        previous.get("bottom_m"),
                        previous.get("head_m"),
                    ]
                    if any(v is None for v in intervals):
                        overlap_kind, overlap_code = (
                            "missing",
                            "PROJECTED_CUT_OVERLAP_VERTICAL_UNKNOWN",
                        )
                    elif max(r["bottom_m"], previous["bottom_m"]) >= min(
                        r["head_m"], previous["head_m"]
                    ):
                        overlap_kind, overlap_code = "unsupported", "STACKED_OPENINGS_UNSUPPORTED"
                    else:
                        overlap_kind, overlap_code = "conflict", "OVERLAPPING_DRAFTING_CUTS"
                    r["issues"].append(overlap_code)
                    previous["issues"].append(overlap_code)
                    problem(
                        overlap_kind,
                        overlap_code,
                        r["id"],
                        "Rough opening cut overlaps "
                        + previous["id"]
                        + "; both are retained as proposals but neither cut is applied.",
                    )
        for r in records:
            r["cut_accepted"] = "_cut" in r and not r["issues"]
            r["plan_cut_applied"] = (
                r["cut_accepted"] and r["plan_interpretation"] == "INTERSECTS_OPENING"
            )
            r["floor_cut_applied"] = (
                r["cut_accepted"] and not r["type"].endswith("window") and r.get("bottom_m") == 0
            )
        floor_obstructions = account(model, records, result, spec, problem)
        result["circulation"] = replay(ctx, model, records, floor_obstructions, spec, problem)
        result["schedule"] = schedule(rows, records, spec["units"], problem)
        for r in records:
            r["issues"] = sorted(set(r["issues"]))
            r["opening_digest"] = canonical_digest(
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "host_wall_id",
                        "host_wall_digest",
                        "reference",
                        "rough_cut",
                        "primitives",
                        "plan_interpretation",
                        "clear_reference",
                        "operating_state",
                    )
                }
            )
        result["openings"] = [
            {k: v for k, v in r.items() if not k.startswith("_")} for r in records
        ]
        result["unresolved_opening_ids"] = [
            r["id"]
            for r in records
            if r["issues"]
            or r["physical_state"] == "BLOCKED"
            or r["clearance_status"] == "UNKNOWN"
            and not r["type"].endswith("window")
        ]
        result["geometry_status"] = (
            "VALID" if all(r["cut_accepted"] for r in records) else "PARTIAL"
        )
        result["opening_geometry_digest"] = canonical_digest(
            {
                "openings": [[r["id"], r["opening_digest"]] for r in result["openings"]],
                "floors": result["floors"],
            }
        )
        result["opening_revision_id"] = "OR-" + canonical_digest(
            [
                model["wall_revision_id"],
                result["specification_digest"],
                result["opening_geometry_digest"],
            ]
        )
    except (GEOSException, ValueError, OverflowError) as exc:
        problem("unsupported", "OPENING_GEOMETRY_OPERATION", "geometry", str(exc))
    result["drafting_status"] = (
        "INVALID_INPUT"
        if "invalid" in flags
        else "CONFLICT"
        if "conflict" in flags
        else "UNSUPPORTED"
        if "unsupported" in flags
        else "INCOMPLETE"
        if "missing" in flags
        else "GENERATED"
    )
    result["drafting_readiness"] = {
        "source_wall_status": model["wall_status"],
        "derived_status": "NOT_READY" if "conflict" in flags else "INCOMPLETE",
        "architect_review_required": True,
        "approval_granted": False,
        "cad_writes_permitted": False,
    }
    result["evidence_impact"] = {
        "source_candidate_unchanged": True,
        "source_wall_geometry_unchanged": True,
        "preserved_dependencies": [
            "source_allocation_geometry",
            "source_brief",
            "original_allocation_replay",
            "original_wall_geometry",
            "unchanged_known_fixed_geometry",
        ],
        "stale_for_opening_revision": [
            "source_boundary_openings",
            "source_circulation",
            "source_clearance",
            "candidate_evaluation",
            "architect_approval",
        ],
        "fresh_replay": "006-B graph/path/stair stages with actual B2 door cuts and retained window obstructions",
        "approval_inherited": False,
        "technical_review": "NOT_EVALUATED",
    }
    return finish(result)


def validate_drafting(value: Any) -> dict:
    if not isinstance(value, dict) or value.get("contract") != "opening-drafting-v1":
        return draft_openings(value)
    check = new_report("stored-opening-drafting")
    if not schema_check(value, "opening-drafting-result.schema.json", check):
        result = draft_openings({})
        result["errors"] = check["errors"]
        return finish(result)
    fresh = draft_openings(value.get("sources", {}).get("input"))
    keys = (
        "source_candidate_digest",
        "source_wall_revision_id",
        "source_wall_geometry_digest",
        "specification_digest",
        "opening_geometry_digest",
        "opening_revision_id",
        "openings",
        "floors",
        "rooms",
        "schedule",
        "circulation",
        "evidence_impact",
        "drafting_readiness",
        "drafting_status",
        "geometry_status",
    )
    if any(value.get(k) != fresh.get(k) for k in keys):
        issue(
            fresh,
            "errors",
            "STORED_OPENING_DRAFT_MISMATCH",
            "$",
            "Stored geometry/schedule/evidence does not match independent recomputation.",
        )
        fresh["drafting_status"] = "INVALID_INPUT"
    return finish(fresh)
