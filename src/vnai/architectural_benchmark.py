"""Reproducible synthetic architectural benchmarks; expert review stays pending."""

from typing import Any

from vnai.cad_readiness import readiness_report
from vnai.candidate_evaluation import evaluate_candidates
from vnai.contracts import canonical_digest, new_report, schema_check
from vnai.design_provenance import bounded_geometry
from vnai.design_replay import validate_replay
from vnai.floorplan import generate_floorplans


def run_benchmark(value: Any) -> dict:
    result = new_report("architectural-benchmark-v1")
    result.update(
        benchmark_status="INVALID_INPUT",
        benchmark_id=None,
        specification_digest=None,
        generation=None,
        candidates=[],
        metrics={},
        architectural_requests=[],
        human_review_status="PENDING",
        expert_oracle_status="NOT_ESTABLISHED",
        timing_included=False,
    )
    if not schema_check(value, "architectural-benchmark.schema.json", result):
        return result
    spec = value["generation_specification"]
    if spec.get("geometry") and not bounded_geometry({"candidate": {"geometry": spec["geometry"]}}):
        result["errors"].append(
            {
                "code": "RESOURCE_LIMIT",
                "path": "generation_specification",
                "message": "Benchmark geometry exceeds bounded replay scope.",
                "requirement_ids": [],
            }
        )
        result["status"] = "INVALID"
        return result
    generated = generate_floorplans(spec, include_provenance=True)
    result.update(
        benchmark_status="COMPLETED",
        benchmark_id=value["benchmark_id"],
        specification_digest=canonical_digest(value),
        generation=generated,
        architectural_requests=value["architectural_requests"],
    )
    for candidate, provenance in zip(
        generated["candidates"], generated.get("generation_provenance", [])
    ):
        # No architect selection, door, stair link, route or review event is synthesized.
        review = {"schema_version": 1, "candidate": candidate}
        replay_input = {
            "schema_version": 1,
            "review": review,
            "mode": "original",
            "provenance": provenance,
        }
        replay = validate_replay(replay_input)
        evaluation = evaluate_candidates(
            {
                "schema_version": 1,
                "config": value["evaluation_config"],
                "candidates": [{"id": candidate["candidate_id"], "review": review}],
            }
        )
        readiness = readiness_report(
            {
                "schema_version": 1,
                "replay": replay_input,
                "policy": value["readiness_policy"],
                "drafting_information": {},
                "evaluation_config": value["evaluation_config"],
            }
        )
        result["candidates"].append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_digest": canonical_digest(candidate),
                "replay": replay,
                "evaluation": evaluation,
                "readiness": readiness,
                "feedback_resolution_status": "NOT_COLLECTED",
                "human_review_status": "PENDING",
            }
        )
    result["metrics"] = {
        "generation_status": generated["status"],
        "distinct_candidates": len(generated["candidates"]),
        "search_effort": generated["search"],
        "replay": [
            {
                "candidate_id": c["candidate_id"],
                "coverage": c["replay"]["coverage"],
                "verified_hard_violations": c["replay"]["coverage"].get("failed", 0),
                "missing_required_evidence": sorted(
                    set(c["replay"]["missing_dependencies"])
                    | {
                        gate["id"]
                        for gate in c["readiness"]["checks"]
                        if gate["status"] in {"UNKNOWN", "UNSUPPORTED"}
                    }
                ),
                "spatial_status": c["replay"]["sources"].get("spatial", {}).get("status"),
                "circulation_coverage": circulation_coverage(c["readiness"]),
                "feedback_resolution_status": c["feedback_resolution_status"],
                "readiness_status": c["readiness"]["readiness_status"],
            }
            for c in result["candidates"]
        ],
        "architectural_quality_assessed": False,
    }
    return result


def circulation_coverage(readiness: dict) -> dict:
    rooms = readiness["sources"]["architectural_review"]["clearance"]["room_physical_access"]
    verified = sum(state == "GEOMETRICALLY_TRAVERSABLE" for state in rooms.values())
    return {
        "scope": "SUPPLIED_PLANAR_ROUTE_VERIFICATION_ONLY",
        "verified_rooms": verified,
        "applicable_rooms": len(rooms),
        "unknown_rooms": len(rooms) - verified,
        "verified_fraction": verified / len(rooms) if rooms else None,
        "physical_state": readiness["sources"]["architectural_review"][
            "physical_circulation_status"
        ],
        "room_statuses": rooms,
        "quality_score": None,
    }
