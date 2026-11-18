"""Independent invariant, negative and determinism tests for preliminary layouts."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

from floorplan_fixtures import (
    synthetic_spec,
    alternatives_spec,
    reservation_spec,
    multizone_spec,
    authorize,
    approve_source,
)
from vnai.floorplan import generate_floorplans, _score
from vnai.floorplan_search import Placement
from vnai.spatial import validate_geometry
from vnai.zoning import create_zoning_proposal
from vnai.contracts import new_report, schema_check
from design_fixtures import incomplete_brief

ROOT = Path(__file__).resolve().parents[1]


def codes(report):
    return {
        i["code"]
        for bucket in ("errors", "warnings", "missing_information")
        for i in report[bucket]
    }


def test_two_room_partition_measured_geometry_and_traceability():
    spec = synthetic_spec()
    before = deepcopy(spec)
    report = generate_floorplans(spec)
    assert report["status"] == "GENERATED"
    assert len(report["candidates"]) == 2
    assert "FEWER_CANDIDATES" in codes(report)
    for c in report["candidates"]:
        assert c["approval_status"] == "PROPOSED" and not c["cad_writes_permitted"]
        assert c["hard_validation"]["passed"]
        assert c["room_areas_m2"] == {"BED:1": 8, "LIVING:1": 8}
        rooms = [p for p in c["geometry"]["polygons"] if p["role"] == "room"]
        shapes = [Polygon(p["exterior"]) for p in rooms]
        assert all(s.is_valid and s.area == 8 and box(0, 0, 4, 4).covers(s) for s in shapes)
        assert shapes[0].intersection(shapes[1]).area == 0
        assert shapes[0].boundary.intersection(shapes[1].boundary).length == 4
        assert {p["room_id"]: p["requirement_id"] for p in rooms} == {
            "BED:1": "REQ-BED",
            "LIVING:1": "REQ-LIVING",
        }
        assert all(p["floor_id"] == "F1" and p["units"] == "m" for p in rooms)
        assert validate_geometry(c["geometry"])["status"] == "VALID"
        assert all(
            p["status"] == "proposed" and "approval" not in p for p in c["geometry"]["polygons"]
        )
        assert "CIRCULATION_CONNECTIVITY_NOT_VERIFIED" in c["unresolved_checks"]
        check = new_report("candidate")
        assert schema_check(c, "floorplan-candidate.schema.json", check), check
    assert spec == before


def test_three_genuinely_distinct_candidates_and_reproducible_digests():
    spec = alternatives_spec()
    report = generate_floorplans(spec)
    assert report == generate_floorplans(deepcopy(spec))
    assert len(report["candidates"]) == 3
    bounds = []
    for candidate in report["candidates"]:
        bounds.append(
            tuple(
                sorted(
                    (p["room_id"], Polygon(p["exterior"]).bounds)
                    for p in candidate["geometry"]["polygons"]
                    if p["role"] == "room"
                )
            )
        )
    assert len(set(bounds)) == 3
    assert len({c["candidate_id"] for c in report["candidates"]}) == 3
    # Object key order never changes a semantic digest or layout.
    reordered = json.loads(json.dumps(spec, sort_keys=True))
    assert generate_floorplans(reordered) == report


def test_equivalent_interchangeable_instances_are_deduplicated():
    spec = synthetic_spec()
    brief = spec["geometry"]["zoning"]["brief"]
    brief["building"]["rooms"] = brief["building"]["rooms"][:1]
    brief["building"]["rooms"][0]["quantity"] = 2
    zoning = create_zoning_proposal(brief, "SYNTHETIC-GENERATION")
    for a in zoning["assignments"]:
        a["zone"] = "private"
    spec["geometry"]["zoning"] = zoning
    spec["room_dimensions"] = [
        {
            "room_id": a["room_id"],
            "requirement_id": "REQ-BED",
            "width": {"min": 2, "max": 2},
            "depth": {"min": 4, "max": 4},
        }
        for a in zoning["assignments"]
    ]
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "GENERATED"
    assert len(report["candidates"]) == 1
    assert report["search"]["distinct_solutions_evaluated"] == 1
    assert "FEWER_CANDIDATES" in codes(report)


@pytest.mark.parametrize(
    "field", ["geometry", "room_dimensions", "authorization", "fixed_elements_status"]
)
def test_missing_information_is_explicit(field):
    spec = synthetic_spec()
    del spec[field]
    if field != "authorization":
        authorize(spec)
    report = generate_floorplans(spec)
    assert report["status"] == "INCOMPLETE"
    assert not report["candidates"]


def test_footprint_never_inferred_from_4x20_lot():
    spec = synthetic_spec()
    spec["geometry"]["polygons"] = [
        p for p in spec["geometry"]["polygons"] if p["role"] != "footprint"
    ]
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INCOMPLETE" and "FOOTPRINT_REQUIRED" in codes(report)
    assert not report["candidates"]


def test_original_townhouse_unresolved_remains_incomplete():
    spec = synthetic_spec()
    spec["geometry"]["zoning"] = create_zoning_proposal(incomplete_brief(), "UNRESOLVED")
    spec["geometry"]["project_id"] = spec["geometry"]["zoning"]["brief"]["project"]["id"]
    for row in spec["geometry"]["polygons"]:
        row["owner_id"] = spec["geometry"]["project_id"]
    # Supply synthetic floor identifiers in both geometry and zoning; source brief questions remain unresolved.
    floors = [{"id": "F1"}, {"id": "F2"}, {"id": "F3"}]
    spec["geometry"]["floors"] = deepcopy(floors)
    spec["geometry"]["zoning"]["floors"] = deepcopy(floors)
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INCOMPLETE"
    assert not report["candidates"]


def test_unassigned_rooms_and_pending_source_approval():
    spec = synthetic_spec()
    zoning = spec["geometry"]["zoning"]
    zoning["brief"]["building"]["rooms"][0]["floor_id"] = None
    zoning["assignments"][0]["floor_id"] = None
    zoning["assignments"][0]["status"] = "proposed"
    zoning["decisions"] = []
    for row in zoning["assignments"]:
        row["status"] = "proposed"
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INCOMPLETE"
    assert "ROOM_UNASSIGNED" in codes(report)


def test_target_is_not_silently_promoted_to_hard_area_range():
    spec = synthetic_spec()
    spec["geometry"]["zoning"]["brief"]["building"]["rooms"][0]["area"] = {
        "unit": "m2",
        "target": 8,
    }
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "INCOMPLETE" and "ROOM_AREA_RANGE_REQUIRED" in codes(report)


def test_proven_area_infeasibility_does_not_return_candidate():
    spec = alternatives_spec()
    for r in spec["geometry"]["zoning"]["brief"]["building"]["rooms"]:
        r["area"] = {"unit": "m2", "min": 9, "max": 9, "target": 9}
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "INFEASIBLE"
    assert "MINIMUM_AREA_EXCEEDS_AVAILABLE" in codes(report)
    assert report["search"]["termination"] == "NOT_STARTED" and not report["candidates"]


def test_dimension_impossibility_is_separate_from_reversed_bounds():
    spec = synthetic_spec()
    spec["room_dimensions"][0]["width"] = {"min": 5, "max": 6}
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INFEASIBLE" and "ROOM_DIMENSIONS_IMPOSSIBLE" in codes(report)
    spec["room_dimensions"][0]["width"] = {"min": 6, "max": 5}
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INVALID_INPUT" and "DIMENSION_BOUNDS" in codes(report)


def test_invalid_polygon_rejected_without_repair():
    spec = synthetic_spec()
    before = deepcopy(spec)
    spec["geometry"]["polygons"][1]["exterior"] = [[0, 0], [4, 4], [4, 0], [0, 4]]
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INVALID_INPUT"
    assert not report["candidates"]
    assert (
        spec["geometry"]["polygons"][1]["exterior"] != before["geometry"]["polygons"][1]["exterior"]
    )


@pytest.mark.parametrize("kind", ["stairwell", "circulation", "service_shaft", "other"])
def test_fixed_reserved_regions_remain_unallocated(kind):
    spec = reservation_spec()
    spec["geometry"]["polygons"][-1]["reservation_kind"] = kind
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "GENERATED"
    reserved = Polygon(spec["geometry"]["polygons"][-1]["exterior"])
    for candidate in report["candidates"]:
        rooms = [p for p in candidate["geometry"]["polygons"] if p["role"] == "room"]
        assert sum(Polygon(p["exterior"]).area for p in rooms) == 16
        assert all(Polygon(p["exterior"]).intersection(reserved).area == 0 for p in rooms)
        assert validate_geometry(candidate["geometry"])["status"] == "VALID"


def test_reserved_area_participates_in_proof_of_insufficient_area():
    spec = reservation_spec()
    spec["geometry"]["polygons"][-1]["exterior"] = [[0, 0], [2, 0], [2, 4], [0, 4]]
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INFEASIBLE" and not report["candidates"]


def test_search_budget_exhaustion_is_not_infeasibility():
    spec = alternatives_spec()
    report = generate_floorplans(spec, max_steps=1)
    assert report["status"] == "SEARCH_EXHAUSTED"
    assert report["search"]["termination"] == "STEP_LIMIT" and report["search"]["steps"] == 1
    assert not report["candidates"]


def test_grid_space_failure_is_not_continuous_infeasibility():
    spec = synthetic_spec()
    spec["parameters"]["grid_step"] = 3
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "SEARCH_EXHAUSTED"
    assert report["search"]["termination"] == "GRID_SPACE_EXHAUSTED"


def test_solution_limit_is_reported_and_does_not_claim_optimality():
    spec = alternatives_spec()
    spec["parameters"]["solution_limit"] = 1
    report = generate_floorplans(spec)
    assert report["status"] == "GENERATED" and len(report["candidates"]) == 1
    assert report["search"]["termination"] == "SOLUTION_LIMIT"
    assert not report["search"]["optimality_proven"]
    assert {"PARTIAL_SEARCH", "FEWER_CANDIDATES"} <= codes(report)


def test_soft_scores_are_computed_and_sorted():
    report = generate_floorplans(multizone_spec())
    scores = [c["soft_scores"]["total"] for c in report["candidates"]]
    assert scores == sorted(scores, reverse=True)
    for candidate in report["candidates"]:
        shapes = {
            p["room_id"]: Polygon(p["exterior"])
            for p in candidate["geometry"]["polygons"]
            if p["role"] == "room"
        }
        expected = (
            1.0
            if shapes["BED:1"].boundary.intersection(shapes["KITCHEN:1"].boundary).length > 0
            else 0.0
        )
        assert candidate["soft_scores"]["preferred_adjacency"] == expected
        assert candidate["soft_scores"]["total"] == (expected + 1) / 2
    prepared = {
        "rooms": [
            {"id": "A", "floor_id": "F1", "area": {"target": 4}},
            {"id": "B", "floor_id": "F1", "area": {"target": 4}},
        ],
        "soft_pairs": [("A", "B")],
    }
    a = Placement(box(0, 0, 2, 2), 1, 4, 2, 2)
    b = Placement(box(2, 0, 4, 2), 2, 4, 2, 2)
    far = Placement(box(4, 0, 6, 2), 4, 4, 2, 2)
    assert _score({"A": a, "B": b}, prepared)["total"] == 1
    assert _score({"A": a, "B": far}, prepared)["total"] == 0.5


def test_mandatory_adjacency_cannot_be_hidden_by_soft_score():
    spec = multizone_spec()
    brief = spec["geometry"]["zoning"]["brief"]
    rel = brief["building"]["relationships"][0]
    rel["strength"] = "hard"
    next(r for r in brief["requirements"] if r["id"] == rel["requirement_id"])["type"] = "mandatory"
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "GENERATED"
    for candidate in report["candidates"]:
        shapes = {
            p["room_id"]: Polygon(p["exterior"])
            for p in candidate["geometry"]["polygons"]
            if p["role"] == "room"
        }
        assert shapes["BED:1"].boundary.intersection(shapes["KITCHEN:1"].boundary).length == 2


def test_unsupported_mandatory_separation_is_not_ignored():
    spec = multizone_spec()
    brief = spec["geometry"]["zoning"]["brief"]
    rel = brief["building"]["relationships"][0]
    rel.update(relation="separate", strength="hard")
    next(r for r in brief["requirements"] if r["id"] == rel["requirement_id"])["type"] = "mandatory"
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "UNSUPPORTED" and not report["candidates"]


def test_unsupported_envelopes_and_existing_rooms_are_explicit():
    spec = synthetic_spec()
    spec["geometry"]["polygons"][1]["exterior"] = [[0, 0], [4, 0], [4, 3], [2, 4], [0, 4]]
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "UNSUPPORTED" and "RECTANGLE_REQUIRED" in codes(report)
    source = generate_floorplans(synthetic_spec())["candidates"][0]["geometry"]
    spec = synthetic_spec()
    spec["geometry"] = source
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "UNSUPPORTED" and "EXISTING_ROOM_GEOMETRY" in codes(report)


def test_stale_authorization_and_unconfirmed_dimension_provenance():
    spec = synthetic_spec()
    spec["room_dimensions"][0]["width"]["min"] = 1
    assert generate_floorplans(spec)["status"] == "INVALID_INPUT"
    spec = synthetic_spec()
    spec["room_dimensions"][0]["requirement_id"] = "BAD"
    report = generate_floorplans(authorize(spec))
    assert "DIMENSION_PROVENANCE" in codes(report)


@pytest.mark.parametrize("bad", [{}, [], None, {"schema_version": 2}, {"schema_version": True}])
def test_invalid_schema(bad):
    assert generate_floorplans(bad)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_bad_grid_values(value):
    spec = synthetic_spec()
    spec["parameters"]["grid_step"] = value
    assert generate_floorplans(spec)["status"] == "INVALID_INPUT"


def test_grid_resource_guard_handles_pathologically_thin_grid():
    spec = synthetic_spec()
    spec["parameters"]["grid_step"] = 0.00001
    assert generate_floorplans(authorize(spec))["status"] == "UNSUPPORTED"


def test_positive_area_below_declared_geometry_threshold_is_rejected():
    spec = synthetic_spec()
    spec["geometry"]["tolerances"]["min_area_m2"] = 8
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "SEARCH_EXHAUSTED" and not report["candidates"]


def test_multifloor_processing_preserves_ids_and_does_not_compare_across_planes():
    spec = synthetic_spec()
    z = spec["geometry"]["zoning"]
    z["brief"]["building"]["storeys"]["value"] = 2
    z["brief"]["building"]["floors"].append({"id": "F2", "label": "Synthetic second floor"})
    z["floors"].append({"id": "F2"})
    z["brief"]["building"]["rooms"][1]["floor_id"] = "F2"
    z["assignments"][1]["floor_id"] = "F2"
    spec["geometry"]["floors"].append({"id": "F2"})
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "GENERATED"
    for candidate in report["candidates"]:
        assert candidate["floor_ids"] == ["F1", "F2"] and candidate["floor_id"] is None
        assert {
            p["room_id"]: p["floor_id"]
            for p in candidate["geometry"]["polygons"]
            if p["role"] == "room"
        } == {"BED:1": "F1", "LIVING:1": "F2"}
        assert candidate["hard_validation"]["spatial_report"]["status"] == "VALID"


@pytest.mark.parametrize(
    "name",
    [
        "two-room",
        "alternatives",
        "fixed-stair",
        "multizone",
        "missing-footprint",
        "insufficient-area",
        "search-budget",
    ],
)
def test_full_golden_reproducibility(name):
    spec = json.loads((ROOT / "examples/batch006a" / (name + ".json")).read_text())
    golden = json.loads((ROOT / "tests/golden/batch006a-v0.1.6" / (name + ".json")).read_text())
    assert generate_floorplans(spec) == golden


def test_decimal_dimensions_do_not_create_false_infeasibility():
    spec = synthetic_spec(width=0.4, depth=0.1)
    brief = spec["geometry"]["zoning"]["brief"]
    for room in brief["building"]["rooms"]:
        room["area"] = {"unit": "m2", "min": 0.02, "max": 0.02, "target": 0.02}
    for dim in spec["room_dimensions"]:
        dim["width"] = {"min": 0.2, "max": 0.2}
        dim["depth"] = {"min": 0.1, "max": 0.1}
    spec["parameters"]["grid_step"] = 0.1
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "GENERATED"
    assert all(
        all(abs(value - 0.02) < 1e-12 for value in c["room_areas_m2"].values())
        for c in report["candidates"]
    )


def test_millimetre_input_preserves_declared_units_and_metric_areas():
    spec = synthetic_spec()
    geometry = spec["geometry"]
    geometry["units"] = "mm"
    for row in geometry["polygons"]:
        row["units"] = "mm"
        row["exterior"] = [[x * 1000, y * 1000] for x, y in row["exterior"]]
    for dim in spec["room_dimensions"]:
        for axis in ("width", "depth"):
            dim[axis] = {key: value * 1000 for key, value in dim[axis].items()}
    spec["parameters"]["grid_step"] = 1000
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "GENERATED"
    for c in report["candidates"]:
        assert c["geometry"]["units"] == "mm"
        assert c["room_areas_m2"] == {"BED:1": 8, "LIVING:1": 8}
        assert c["hard_validation"]["spatial_report"]["status"] == "VALID"


def test_corner_contact_is_not_required_edge_adjacency():
    from vnai.floorplan_search import adjacent

    a = Placement(box(0, 0, 2, 2), 1, 4, 2, 2)
    corner = Placement(box(2, 2, 4, 4), 2, 4, 2, 2)
    edge = Placement(box(2, 0, 4, 2), 2, 4, 2, 2)
    assert not adjacent(a, corner) and adjacent(a, edge)


def test_preferred_area_score_normalization():
    prepared = {"rooms": [{"id": "A", "floor_id": "F1", "area": {"target": 4}}], "soft_pairs": []}
    assert _score({"A": Placement(box(0, 0, 2, 2), 1, 4, 2, 2)}, prepared)["preferred_area"] == 1
    assert _score({"A": Placement(box(0, 0, 4, 2), 1, 8, 4, 2)}, prepared)["preferred_area"] == 0


def test_reservation_metadata_is_required_and_not_counted_as_a_program_room():
    spec = reservation_spec()
    row = spec["geometry"]["polygons"][-1]
    del row["reservation_kind"]
    assert generate_floorplans(authorize(spec))["status"] == "INVALID_INPUT"


def test_room_dimension_inventory_must_match_program():
    spec = synthetic_spec()
    spec["room_dimensions"].append(deepcopy(spec["room_dimensions"][0]))
    report = generate_floorplans(authorize(spec))
    assert "DUPLICATE_ROOM_DIMENSIONS" in codes(report)
    spec = synthetic_spec()
    spec["room_dimensions"][0]["room_id"] = "UNKNOWN:1"
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INVALID_INPUT" and "UNKNOWN_ROOM_DIMENSIONS" in codes(report)


def test_explicit_source_footprint_bounds_cannot_be_overridden_by_geometry():
    spec = synthetic_spec()
    spec["geometry"]["zoning"]["brief"]["building"]["footprint"]["value"] = {
        "unit": "m2",
        "min": 20,
        "max": 20,
    }
    report = generate_floorplans(approve_source(spec))
    assert report["status"] == "INVALID_INPUT" and "FOOTPRINT_SOURCE_BOUNDS_CONFLICT" in codes(
        report
    )


def test_missing_grid_in_partial_parameter_block_is_incomplete():
    spec = synthetic_spec()
    spec["parameters"] = {}
    report = generate_floorplans(authorize(spec))
    assert report["status"] == "INCOMPLETE" and "GRID_REQUIRED" in codes(report)


def test_bad_generation_authority_role_is_not_an_approval():
    spec = synthetic_spec()
    spec["authorization"]["record"]["role"] = "agent"
    report = generate_floorplans(spec)
    assert report["status"] == "INVALID_INPUT" and not report["candidates"]
