"""Synthetic replay/revision fixtures using real generator and review contracts."""

from copy import deepcopy

from circulation_fixtures import base, selection, review_events
from design_fixtures import add_relationship
from floorplan_fixtures import synthetic_spec, approve_source, authorize
from vnai.contracts import canonical_digest
from vnai.design_provenance import create_generation_provenance
from vnai.floorplan import generate_floorplans
from vnai.review_common import candidate_digest, design_digest


def policy(stages=("room_geometry",), review="SELECTED"):
    return {
        "schema_version": 1,
        "policy_id": "synthetic-room-polygons-v1",
        "requested_stages": list(stages),
        "required_review_state": review,
        "require_openings": False,
        "require_graph": False,
        "require_clearance": False,
        "require_evaluation": False,
        "require_revision_review": False,
    }


def original():
    spec = synthetic_spec(width=6, depth=6)
    add_relationship(spec["geometry"]["zoning"]["brief"], pair=["BED", "LIVING"])
    approve_source(spec)
    generated = generate_floorplans(spec, include_provenance=True)
    assert generated["status"] == "GENERATED", generated
    review = base(generated["candidates"][0])
    review["openings_complete"] = False
    return {
        "schema_version": 1,
        "mode": "original",
        "review": review,
        "provenance": generated["generation_provenance"][0],
    }


def refresh(review):
    from shapely.geometry import Polygon

    geometry = review["candidate"]["geometry"]
    scale = 1 if geometry["units"] == "m" else 0.001
    review["candidate"]["room_areas_m2"] = {
        r["room_id"]: Polygon(r["exterior"], r.get("holes", [])).area * scale * scale
        for r in geometry["polygons"]
        if r["role"] == "room"
    }
    return selection(review)


def revised(original_input, change="translate"):
    result = deepcopy(original_input)
    result["mode"] = "revision"
    review = result["review"]
    candidate = review["candidate"]
    candidate["candidate_id"] = "SYNTHETIC-REVISION-" + change
    rows = [p for p in candidate["geometry"]["polygons"] if p["role"] == "room"]
    if change == "translate":
        all_x = [p[0] for r in rows for p in r["exterior"]]
        shift = -0.125 if max(all_x) == 6 else 0.125
        for r in rows:
            r["exterior"] = [[x + shift, y] for x, y in r["exterior"]]
    elif change == "dimensions":
        rows[0]["exterior"] = [[0, 4], [4, 4], [4, 6], [0, 6]]
    elif change == "area":
        rows[0]["exterior"] = [[0, 4], [1, 4], [1, 6], [0, 6]]
    elif change == "adjacency":
        rows[0]["exterior"] = [[0, 0], [2, 0], [2, 4], [0, 4]]
        rows[1]["exterior"] = [[4, 0], [6, 0], [6, 4], [4, 4]]
    refresh(review)
    return result


def revision_request(parent, child, feedback=None):
    pr, cr = parent["review"], child["review"]
    result = {
        "schema_version": 1,
        "parent_revision_id": "SYNTHETIC-REV-1",
        "child_revision_id": "SYNTHETIC-REV-2",
        "parent_review": deepcopy(pr),
        "child_review": deepcopy(cr),
        "parent_candidate_digest": candidate_digest(pr["candidate"]),
        "child_candidate_digest": candidate_digest(cr["candidate"]),
        "parent_design_digest": design_digest(pr),
        "child_design_digest": design_digest(cr),
        "change_origin": "architect_requested",
        "change_rationale": "Synthetic externally supplied revision; no AI redesign.",
        "feedback": feedback or [],
        "provenance": deepcopy(parent["provenance"]),
    }
    if child.get("baseline_revision"):
        result["baseline_revision"] = deepcopy(child["baseline_revision"])
    return result


def feedback(parent, key="FB-1", resolution="OPEN", child=None):
    review = parent["review"]
    room = next(p for p in review["candidate"]["geometry"]["polygons"] if p["role"] == "room")
    item = {
        "id": key,
        "target": {
            "candidate_id": review["candidate"]["candidate_id"],
            "candidate_digest": candidate_digest(review["candidate"]),
            "design_digest": design_digest(review),
        },
        "reviewer": {"identity": "SYNTHETIC_TEST_ARCHITECT_NOT_REAL_REVIEW", "role": "architect"},
        "category": "functional_layout",
        "affected_room_ids": [room["room_id"]],
        "affected_geometry_ids": [room["id"]],
        "requirement_ids": [room["requirement_id"]],
        "requested_modification": "Review the supplied room placement.",
        "rationale": "Synthetic feedback used only as an automated contract oracle.",
        "blocking": True,
        "resolution": resolution,
        "supersedes": [],
    }
    if resolution in {"VERIFIED", "WITHDRAWN", "SUPERSEDED"} and child:
        item["resolution_record"] = {
            "reviewer": {
                "identity": "SYNTHETIC_TEST_ARCHITECT_NOT_REAL_REVIEW",
                "role": "architect",
            },
            "child_design_digest": design_digest(child["review"]),
            "rationale": "Synthetic explicit resolution record, not expert validation.",
        }
    return item


def readiness(replay, stages=("room_geometry",), review="SELECTED"):
    return {
        "schema_version": 1,
        "replay": deepcopy(replay),
        "policy": policy(stages, review),
        "drafting_information": {},
    }


def changed_baseline(parent):
    child = revised(parent)
    spec = deepcopy(parent["provenance"]["generation_specification"])
    spec["geometry"]["zoning"]["brief"]["project"]["name"] += " - confirmed revised baseline"
    spec["geometry"]["zoning"]["brief"]["building"]["rooms"][0]["area"].update(max=9, target=8.5)
    approve_source(spec)
    child["review"]["candidate"]["geometry"]["zoning"] = deepcopy(spec["geometry"]["zoning"])
    refresh(child["review"])
    child["baseline_revision"] = {
        "specification": spec,
        "confirmation": {
            "reviewer": {"identity": "SYNTHETIC_CLIENT_NOT_REAL_CONFIRMATION", "role": "user"},
            "specification_digest": canonical_digest(spec),
            "confirmed": True,
            "rationale": "Synthetic explicit revised requirement baseline.",
        },
    }
    return child


def reserved_case():
    spec = synthetic_spec(width=6, depth=6)
    spec["geometry"]["polygons"].append(
        {
            "id": "SYNTHETIC-SHAFT",
            "role": "reservation",
            "reservation_kind": "service_shaft",
            "owner_id": "F1",
            "floor_id": "F1",
            "frame_id": "LOCAL",
            "units": "m",
            "exterior": [[0, 0], [1, 0], [1, 6], [0, 6]],
            "holes": [],
            "status": "proposed",
            "requirement_id": "REQ-internal_circulation",
            "provenance": "Synthetic fixed shaft region.",
        }
    )
    authorize(spec)
    candidate = generate_floorplans(spec)["candidates"][0]
    result = {
        "schema_version": 1,
        "review": base(candidate),
        "mode": "revision",
        "provenance": create_generation_provenance(spec, candidate),
    }
    result["review"]["openings_complete"] = False
    row = next(
        p for p in result["review"]["candidate"]["geometry"]["polygons"] if p["role"] == "room"
    )
    row["exterior"] = [[0, 0], [2, 0], [2, 4], [0, 4]]
    refresh(result["review"])
    return result


def benchmark_spec(width, depth, key):
    from design_fixtures import valid_brief
    from vnai.zoning import create_zoning_proposal
    from evaluation_fixtures import policy as evaluation_policy

    brief = valid_brief()
    brief["project"]["id"] = "SYNTHETIC-BENCHMARK-" + key
    brief["project"]["name"] = (
        "Synthetic residential benchmark " + key + "; no real project/expert approval"
    )
    brief["site"]["dimensions"]["value"] = {
        "shape": "rectangle",
        "width": width,
        "length": depth,
        "unit": "m",
    }
    floor_count = 1 if key == "C" else 2
    footprint_depth = 10 if key == "C" else 12
    brief["building"]["storeys"]["value"] = floor_count
    brief["building"]["floors"] = [
        {"id": "F" + str(i), "label": "Synthetic floor " + str(i)}
        for i in range(1, floor_count + 1)
    ]
    brief["building"]["footprint"]["value"] = {"target": width * footprint_depth, "unit": "m2"}
    dim = {
        "LIVING": (3 if key == "A" else 4, 4),
        "KITCHEN": (3 if key in {"A", "C"} else 4, 3 if key != "C" else 4),
        "BED": (3 if key in {"A", "C"} else 4, 3),
        "PRAYER": (1 if key == "A" else 2, 2),
        "LAUNDRY": (1 if key == "A" else 2, 2),
    }
    for room in brief["building"]["rooms"]:
        room["quantity"] = 2 if room["id"] == "BED" else 1
        room["floor_id"] = "F2" if floor_count == 2 and room["id"] in {"BED", "PRAYER"} else "F1"
        w, d = dim[room["id"]]
        room["area"] = {"min": w * d, "max": w * d, "target": w * d, "unit": "m2"}
    add_relationship(brief, key="PUBLIC-ADJACENCY", pair=["LIVING", "KITCHEN"])
    add_relationship(brief, key="BED-PRAYER-PREFERENCE", pair=["BED", "PRAYER"], strength="soft")
    if key == "C":
        add_relationship(
            brief, key="PRIVACY-SEPARATION", pair=["BED", "LIVING"], relation="separate"
        )
    zoning = create_zoning_proposal(brief, "SYNTHETIC-ZONING-" + key)
    for row in zoning["assignments"]:
        row["zone"] = (
            "private"
            if row["room_id"].startswith("BED")
            else "service"
            if row["room_id"].startswith("LAUNDRY")
            else "public"
        )
    geometry = deepcopy(synthetic_spec()["geometry"])
    geometry.update(
        project_id=brief["project"]["id"],
        zoning=zoning,
        floors=[
            {"id": f["id"], "elevation_m": 0 if f["id"] == "F1" else 3}
            for f in brief["building"]["floors"]
        ],
    )
    site, footprint = geometry["polygons"][:2]
    for row in (site, footprint):
        row["owner_id"] = geometry["project_id"]
    site["exterior"] = [[0, 0], [width, 0], [width, depth], [0, depth]]
    footprint["exterior"] = [[0, 0], [width, 0], [width, footprint_depth], [0, footprint_depth]]
    geometry["polygons"] = [site, footprint]
    for floor in geometry["floors"]:
        f = floor["id"]
        if floor_count == 2:
            intervals = [
                ("STAIRWELL", "stairwell", 0, 4, "Q-STAIR"),
                ("CIRCULATION", "circulation", 4, footprint_depth, "REQ-internal_circulation"),
            ]
        else:
            intervals = [
                ("CIRCULATION", "circulation", 0, footprint_depth, "REQ-internal_circulation")
            ]
        for label, kind, y0, y1, req in intervals:
            geometry["polygons"].append(
                {
                    "id": label + "-" + f,
                    "role": "reservation",
                    "reservation_kind": kind,
                    "owner_id": f,
                    "floor_id": f,
                    "frame_id": "LOCAL",
                    "units": "m",
                    "exterior": [[0, y0], [1, y0], [1, y1], [0, y1]],
                    "holes": [],
                    "status": "proposed",
                    "requirement_id": req,
                    "provenance": "Explicit synthetic benchmark reservation, not a detailed stair/path design.",
                }
            )
    dimensions = []
    for row in zoning["assignments"]:
        group = row["room_id"].split(":")[0]
        w, d = dim[group]
        dimensions.append(
            {
                "room_id": row["room_id"],
                "requirement_id": row["requirement_id"],
                "width": {"min": w, "max": w},
                "depth": {"min": d, "max": d},
            }
        )
    spec = {
        "schema_version": 1,
        "geometry": geometry,
        "fixed_elements_status": "complete",
        "room_dimensions": dimensions,
        "parameters": {
            "grid_step": 1,
            "candidate_count": 3,
            "max_steps": 20000,
            "solution_limit": 8,
        },
    }
    approve_source(spec)
    return {
        "schema_version": 1,
        "benchmark_id": "SYNTHETIC-" + key,
        "fixture_notice": "SYNTHETIC benchmark; not a real project or expert-approved oracle.",
        "generation_specification": spec,
        "evaluation_config": evaluation_policy(),
        "readiness_policy": policy(review="REVIEWED"),
        "architectural_requests": [
            "Synthetic functional/public/private zoning and explicit room dimensions.",
            "Natural lighting, ventilation and skylight requested; not simulated or verified.",
            "Expert architectural review pending; source approval actors are synthetic fixtures.",
        ],
    }


def scenario_inputs():
    from evaluation_fixtures import policy as evaluation_policy
    from vnai.candidate_evaluation import evaluate_candidates

    origin = original()
    child = revised(origin)
    original_ready = readiness(origin)
    legacy = deepcopy(origin)
    legacy.pop("provenance")
    approved = deepcopy(origin)
    review_events(approved["review"], ("SELECTED", "REVIEWED", "APPROVED"))
    stale_approval_child = revised(approved)
    revised_baseline = changed_baseline(origin)
    baseline_revision_request = revision_request(origin, revised_baseline)
    baseline_revision_request["change_origin"] = "user_confirmed_requirement_change"
    blocker = feedback(origin)
    stale = readiness(child)
    stale["revision"] = revision_request(origin, child)
    stale["policy"]["require_evaluation"] = True
    stale["evaluation_config"] = evaluation_policy()
    old = evaluate_candidates(
        {
            "schema_version": 1,
            "config": evaluation_policy(),
            "candidates": [{"id": "ORIGIN", "review": origin["review"]}],
        }
    )
    stale["prior_evidence"] = [old["evaluations"][0]["evidence"]]
    blocking = readiness(child)
    blocking["revision"] = revision_request(origin, child, [blocker])
    unsupported = deepcopy(origin)
    unsupported["review"]["candidate"]["geometry"]["polygons"] = [
        p for p in unsupported["review"]["candidate"]["geometry"]["polygons"]
    ]
    return {
        "valid-provenance": ("replay", origin),
        "missing-original-constraints": ("replay", legacy),
        "modified-room-dimensions": ("replay", revised(origin, "dimensions")),
        "revised-hard-area-failure": ("replay", revised(origin, "area")),
        "mandatory-adjacency-failure": ("replay", revised(origin, "adjacency")),
        "reserved-region-failure": ("replay", reserved_case()),
        "stale-evaluation-evidence": ("readiness", stale),
        "insufficient-drafting-information": (
            "readiness",
            readiness(origin, ("architectural_walls_openings",)),
        ),
        "blocking-architect-feedback": ("readiness", blocking),
        "selected-without-approval": ("readiness", readiness(origin, review="APPROVED")),
        "approval-invalidated": ("revision", revision_request(approved, stale_approval_child)),
        "changed-requirement-baseline": ("revision", baseline_revision_request),
        "room-geometry-ready": ("readiness", original_ready),
        "architectural-drafting-withheld": (
            "readiness",
            readiness(origin, ("room_geometry", "architectural_walls_openings")),
        ),
        "single-storey-stairs-not-applicable": (
            "readiness",
            readiness(origin, ("room_geometry", "stairs")),
        ),
        "valid-manual-revision": ("revision", revision_request(origin, child)),
        "legacy-batch006": ("replay", legacy),
        "resolved-feedback": (
            "revision",
            revision_request(origin, child, [feedback(origin, resolution="VERIFIED", child=child)]),
        ),
    }


def projection(report):
    from vnai.contracts import canonical_digest

    projected = {
        "full_report_sha256": canonical_digest(report),
        "status": report["status"],
        "states": {
            k: report[k]
            for k in ("replay_status", "revision_status", "readiness_status", "benchmark_status")
            if k in report
        },
        "candidate_digest": report.get("candidate_digest"),
        "specification_digest": report.get("specification_digest"),
        "checks": report.get("checks"),
        "stages": report.get("stages"),
        "coverage": report.get("coverage"),
        "unresolved_feedback": report.get("unresolved_feedback"),
        "approval_invalidated": report.get("approval_invalidated"),
        "child_approval_record_valid": report.get("child_approval_record_valid"),
    }
    if "generation" in report:
        projected["generation_status"] = (
            report["generation"]["status"] if report["generation"] else None
        )
        projected["metrics"] = report["metrics"]
        projected["expert_oracle_status"] = report["expert_oracle_status"]
    if report.get("replay"):
        projected["child_replay_checks"] = report["replay"]["checks"]
    return projected
