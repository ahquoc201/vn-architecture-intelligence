"""Explicit immutable generation sidecars; digests are not human authentication."""

from copy import deepcopy
from typing import Any

from vnai.contracts import canonical_digest, new_report, schema_check
from vnai.floorplan import ALGORITHM, DEFAULT_PARAMETERS
from vnai.space_program import build_space_program


def geometry_context(geometry: dict) -> dict:
    result = {
        k: geometry[k]
        for k in (
            "project_id",
            "units",
            "frame",
            "floors",
            "points",
            "segments",
            "relationships",
            "tolerances",
        )
    }
    result["polygons"] = sorted(
        [
            {k: v for k, v in p.items() if k not in {"status", "approval"}}
            for p in geometry["polygons"]
            if p["role"] != "room"
        ],
        key=lambda p: p["id"],
    )
    return result


def dependencies(spec: dict, candidate: dict) -> dict:
    geometry = spec["geometry"]
    zoning = geometry["zoning"]
    program = build_space_program(zoning["brief"])
    parameters = {**DEFAULT_PARAMETERS, **spec["parameters"]}
    return {
        "brief": canonical_digest(zoning["brief"]),
        "program": canonical_digest(
            {
                k: program[k]
                for k in ("project_id", "rooms", "relationships", "areas", "input_brief")
            }
        ),
        "zoning": canonical_digest(zoning),
        "site_floor_geometry": canonical_digest(geometry_context(geometry)),
        "specification": canonical_digest(spec),
        "generation_input": canonical_digest(
            {"specification": spec, "effective_parameters": parameters, "algorithm": ALGORITHM}
        ),
        "origin_candidate": canonical_digest(candidate),
    }


def provenance_digest(value: dict) -> str:
    return canonical_digest({k: v for k, v in value.items() if k != "provenance_digest"})


def bounded_geometry(review: dict) -> bool:
    geometry = review["candidate"]["geometry"]
    rows = (
        geometry["polygons"]
        + review.get("fixed_obstacles", [])
        + review.get("clearance_regions", [])
    )
    physical = {
        "geometry": {
            k: geometry[k]
            for k in ("frame", "floors", "points", "segments", "polygons", "tolerances")
        },
        "review": {k: v for k, v in review.items() if k != "candidate"},
    }
    coordinate_pairs = 0

    def supported(value: Any) -> bool:
        nonlocal coordinate_pairs
        if isinstance(value, dict):
            return all(supported(v) for v in value.values())
        if isinstance(value, list):
            if len(value) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
            ):
                coordinate_pairs += 1
            return coordinate_pairs <= 10000 and all(supported(v) for v in value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return abs(value) <= 1e9
        return True

    return len(rows) <= 500 and supported(physical) and coordinate_pairs <= 10000


def create_generation_provenance(specification: Any, candidate: Any) -> dict:
    report = new_report("provenance-input")
    if not schema_check(specification, "floorplan-input.schema.json", report) or not schema_check(
        candidate, "floorplan-candidate.schema.json", report
    ):
        raise ValueError("Invalid generation specification/candidate contract.")
    spec = deepcopy(specification)
    if not spec.get("geometry", {}).get("zoning") or not spec.get("parameters", {}).get(
        "grid_step"
    ):
        raise ValueError(
            "Original geometry, zoning and grid specification are required; history is not reconstructed."
        )
    if not bounded_geometry({"candidate": candidate}):
        raise ValueError("Provenance candidate exceeds supported geometry limits.")
    deps = dependencies(spec, candidate)
    parameters = {**DEFAULT_PARAMETERS, **spec["parameters"]}
    if (
        candidate["input_digest"] != deps["generation_input"]
        or candidate["parameters"] != parameters
    ):
        raise ValueError(
            "Specification/parameters do not match the declared original generation input."
        )
    program = build_space_program(spec["geometry"]["zoning"]["brief"])
    result = {
        "schema_version": 1,
        "method": "generation-provenance-v1",
        "generation_engine_version": candidate["hard_validation"]["spatial_report"].get(
            "engine_version", "UNKNOWN"
        ),
        "generation_specification": spec,
        "origin_candidate": deepcopy(candidate),
        "dependency_digests": deps,
        "solver": {
            "algorithm": candidate["algorithm"],
            "parameters": parameters,
            "tolerances": spec["geometry"]["tolerances"],
        },
        "constraint_register": {
            "rooms": program["rooms"],
            "dimensions": spec.get("room_dimensions", []),
            "relationships": program["relationships"],
            "reservations": [p for p in spec["geometry"]["polygons"] if p["role"] == "reservation"],
        },
    }
    result["provenance_digest"] = provenance_digest(result)
    if not schema_check(result, "generation-provenance.schema.json", report):
        raise ValueError("Provenance exceeds the supported contract scope.")
    return result
