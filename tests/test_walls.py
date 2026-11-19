"""Independent geometric wall oracles and negative/safety cases."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from vnai.contracts import new_report, schema_check
from vnai.walls import generate_walls, validate_walls
from vnai.wall_preview import wall_svg

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / "examples/batch007b1" / (name + ".json")).read_text())


@pytest.fixture(scope="module")
def reports():
    return {
        name: generate_walls(load(name))
        for name in [
            "rectangle-inward",
            "shared-wall",
            "t-junction",
            "x-junction",
            "l-junction",
            "mixed-x-thickness",
            "different-junction-thickness",
            "open-plan",
            "explicit-offset",
            "outside-envelope",
            "disconnected-clear-room",
            "reservation-encroachment",
            "multiple-floors",
            "clear-area-violation",
            "stale-opening-evidence",
            "historical-candidate",
        ]
    }


def shape(data):
    return unary_union([Polygon(p["exterior"], p["holes"]) for p in data["polygons"]])


def test_analytical_rectangle_oracle(reports):
    r = reports["rectangle-inward"]
    assert r["wall_status"] == "GENERATED" and r["geometry_status"] == "VALID"
    f, room = r["floors"][0], r["rooms"][0]
    # Independent elementary rectangle arithmetic: (4-2*.2)*(5-2*.2)=16.56.
    assert f["envelope_area_m2"] == 20
    assert room["clear_area_m2"] == pytest.approx(16.56, abs=1e-12)
    assert f["wall_union_area_m2"] == pytest.approx(3.44, abs=1e-12)
    assert room["area_difference_percent"] == pytest.approx(-17.2)
    assert shape(room["clear_geometry"]).bounds == pytest.approx((0.2, 0.2, 3.8, 4.8))
    assert len(r["walls"]) == 4 and all(
        w["measured_thickness_m"] == pytest.approx(0.2) for w in r["walls"]
    )
    assert all({f["role"] for f in w["faces"]} == {"interior", "exterior"} for w in r["walls"])


def test_shared_wall_is_single_and_areas_are_union(reports):
    r = reports["shared-wall"]
    interior = [w for w in r["walls"] if w["classification"] == "shared_boundary"]
    assert len(interior) == 1 and len(interior[0]["related_room_ids"]) == 2
    # Exterior ring 5.04 + inner partition strip .1*(5-.4)=.46.
    assert r["floors"][0]["wall_union_area_m2"] == pytest.approx(5.5)
    assert [room["clear_area_m2"] for room in r["rooms"]] == pytest.approx([17.25, 17.25])
    assert r["floors"][0]["individual_wall_area_sum_m2"] > 5.5
    assert r["floors"][0]["wall_overlap_not_double_counted_m2"] > 0
    assert all(face["role"] == "interior" for face in interior[0]["faces"])


@pytest.mark.parametrize(
    "name,union,clear",
    [
        ("t-junction", 6.375, [21, 10.3125, 10.3125]),
        ("x-junction", 6.75, [10.3125] * 4),
        ("mixed-x-thickness", 11.28, [9, 9, 9.36, 9.36]),
        ("l-junction", 6.84, [41.16]),
        ("different-junction-thickness", 7.44, [40.56]),
    ],
)
def test_analytical_junction_oracles(reports, name, union, clear):
    r = reports[name]
    assert r["wall_status"] == "GENERATED"
    assert r["floors"][0]["wall_union_area_m2"] == pytest.approx(union, abs=1e-11)
    assert sorted(x["clear_area_m2"] for x in r["rooms"]) == pytest.approx(sorted(clear), abs=1e-11)
    assert all(j["status"] == "VERIFIED" for j in r["junctions"])
    assert all(shape(w["geometry"]).is_valid for w in r["walls"])


def test_l_and_x_cores_have_independent_analytical_area(reports):
    ell = next(j for j in reports["l-junction"]["junctions"] if j["point"] == [2, 2])
    cross = next(j for j in reports["x-junction"]["junctions"] if j["kind"] == "X")
    assert ell["kind"] == "L" and ell["area_m2"] == pytest.approx(0.04)
    assert cross["area_m2"] == pytest.approx(0.01)
    assert len(cross["pair_ownership"]) == 4
    assert sum(c["area_m2"] for c in cross["pair_ownership"]) == pytest.approx(0.04)
    assert len(cross["wall_ids"]) == 4


def test_mixed_thickness_not_overwritten_by_junction(reports):
    r = reports["mixed-x-thickness"]
    for w in r["walls"]:
        p = shape(w["geometry"])
        measured = p.bounds[3] - p.bounds[1] if w["normal"] == [0, 1] else p.bounds[2] - p.bounds[0]
        assert measured == pytest.approx(w["thickness_m"], abs=1e-12)
    j = next(j for j in r["junctions"] if j["kind"] == "X")
    assert j["area_m2"] == pytest.approx(0.08)


def test_open_plan_is_explicit_no_partition(reports):
    r = reports["open-plan"]
    assert not [w for w in r["walls"] if w["classification"] == "shared_boundary"]
    assert r["floors"][0]["wall_union_area_m2"] == pytest.approx(5.04)
    assert [x["clear_area_m2"] for x in r["rooms"]] == pytest.approx([17.48, 17.48])
    assert any(
        b["kind"] == "shared" and b["treatment"] == "no_wall" for b in r["boundary_topology"]
    )


def test_explicit_offset_uses_canonical_normal(reports):
    r = reports["explicit-offset"]
    w = next(w for w in r["walls"] if w["classification"] == "special")
    assert w["centerline"]["start"][1] == pytest.approx(2.3)
    assert w["offset_m"] == pytest.approx(0.3)
    assert shape(w["geometry"]).bounds == pytest.approx((2, 2.2, 6, 2.4))


def test_outside_wall_is_not_silently_clipped(reports):
    r = reports["outside-envelope"]
    f = r["floors"][0]
    assert r["wall_status"] == "CONFLICT" and r["geometry_status"] == "INVALID"
    assert f["wall_union_area_m2"] == pytest.approx(3.6)
    assert f["wall_area_outside_envelope_m2"] == pytest.approx(1.84)
    assert shape(f["wall_footprint"]).bounds == pytest.approx((-0.1, -0.1, 4.1, 5.1))


def test_empty_and_disconnected_clear_geometry_are_retained(reports):
    r = reports["disconnected-clear-room"]
    room = r["rooms"][0]
    assert r["wall_status"] == "CONFLICT" and room["component_count"] == 2
    assert len(room["clear_geometry"]["polygons"]) == 2
    assert [c["area_m2"] for c in room["remaining_components"]] == pytest.approx([7.92, 7.92])
    empty = generate_walls(load("empty-clear-room"))
    assert empty["wall_status"] == "CONFLICT" and empty["rooms"][0]["clear_area_m2"] == 0
    assert empty["rooms"][0]["component_count"] == 0


def test_reserved_areas_and_clear_requirements_are_rechecked(reports):
    r = reports["reservation-encroachment"]
    assert r["wall_status"] == "CONFLICT"
    assert any(f["reservation_impacts"] for f in r["floors"])
    assert any(e["code"] == "WALL_RESERVED_REGION_ENCROACHMENT" for e in r["errors"])
    r = reports["clear-area-violation"]
    assert r["constraint_impact"]["allocation_replay_status"] == "VERIFIED"
    assert any(e["code"] == "CLEAR_AREA_BELOW_MINIMUM" for e in r["errors"])
    assert r["rooms"][0]["clear_area_m2"] == pytest.approx(16.56)
    assert r["rooms"][0]["source_area_requirements_m2"]["min"] == 20


def test_multiple_floors_have_no_cross_floor_union(reports):
    r = reports["multiple-floors"]
    assert r["wall_status"] == "GENERATED" and len(r["walls"]) == 8
    assert [f["wall_union_area_m2"] for f in r["floors"]] == pytest.approx([3.44, 3.44])
    assert len({j["id"] for j in r["junctions"]}) == 8
    assert r["drafting_readiness"]["source_status"] == "INCOMPLETE"
    assert r["drafting_readiness"]["derived_status"] == "INCOMPLETE"


def test_openings_are_only_mapped_never_cut_and_old_evidence_is_stale(reports):
    r = reports["stale-opening-evidence"]
    assert r["opening_mappings"]
    assert all(m["status"] == "MAPPED_REQUIRES_REVIEW" for m in r["opening_mappings"])
    assert all(
        not m["wall_cut_performed"] and not m["opening_geometry_created"]
        for m in r["opening_mappings"]
    )
    assert "walking_clearance" in r["evidence_impact"]["stale_for_wall_revision"]
    assert "architect_approval" in r["evidence_impact"]["stale_for_wall_revision"]
    assert r["architect_approval"] == "NOT_GRANTED" and not r["approval_inherited"]
    assert reports["historical-candidate"]["wall_status"] == "INCOMPLETE"
    assert reports["historical-candidate"]["geometry_status"] == "VALID"


@pytest.mark.parametrize(
    "name", ["missing-thickness", "missing-semantics", "unconfirmed-wall-spec"]
)
def test_unknown_information_is_not_a_verified_clear_constraint(name):
    r = generate_walls(load(name))
    assert r["wall_status"] == "INCOMPLETE"
    assert all(x["clear_area_constraint_status"].startswith("UNKNOWN") for x in r["rooms"])
    assert not r["cad_writes_permitted"]


def test_input_immutable_order_invariant_repeatable_and_digest_bound():
    value = load("shared-wall")
    before = deepcopy(value)
    first = generate_walls(value)
    value["wall_specification"]["treatments"].reverse()
    assert generate_walls(value) == first
    assert before["source"] == value["source"]
    assert generate_walls(before) == first
    assert (
        value["source"]["replay"]["review"]["candidate"]
        == before["source"]["replay"]["review"]["candidate"]
    )
    assert validate_walls(first) == first
    first["floors"][0]["wall_union_area_m2"] = 0
    assert validate_walls(first)["wall_status"] == "INVALID_INPUT"


def test_millimeter_thickness_is_explicit_conversion_and_ids_remain_stable():
    value = load("rectangle-inward")
    base = generate_walls(value)
    value["wall_specification"]["treatments"][0]["wall"]["thickness"] = {"value": 200, "unit": "mm"}
    converted = generate_walls(value)
    assert converted["wall_status"] == "GENERATED"
    assert converted["derived_geometry_digest"] == base["derived_geometry_digest"]
    assert converted["wall_specification_digest"] != base["wall_specification_digest"]
    assert [w["id"] for w in converted["walls"]] == [w["id"] for w in base["walls"]]


def test_finished_face_and_centerline_interpretations_are_explicit():
    value = load("shared-wall")
    value["wall_specification"]["treatments"][0]["wall"]["reference_semantics"] = (
        "exterior_finished_face_reference"
    )
    p = value["wall_specification"]["treatments"][1]["wall"]
    p.update(
        reference_semantics="interior_finished_face_reference",
        reference_room_id="BED:1",
        alignment="right",
    )
    r = generate_walls(value)
    assert r["wall_status"] == "GENERATED"
    assert [x["clear_area_m2"] for x in r["rooms"]] == pytest.approx([17.48, 17.02])
    p["alignment"] = "centered"
    assert generate_walls(value)["wall_status"] == "UNSUPPORTED"
    p["reference_semantics"] = "wall_centerline_reference"
    assert generate_walls(value)["wall_status"] == "GENERATED"


def test_clear_dimensions_are_not_inferred_from_bounding_box_of_nonrectangular_room():
    value = load("l-junction")
    value["wall_specification"]["constraint_basis"]["dimensions"] = "clear"
    r = generate_walls(value)
    assert r["wall_status"] == "UNSUPPORTED"
    assert r["rooms"][0]["clear_dimension_constraint_status"] == "UNSUPPORTED"


@pytest.mark.parametrize(
    "change",
    [
        "binding",
        "unknown_requirement",
        "unknown_floor",
        "duplicate_id",
        "conflicting_intent",
        "zero_thickness",
        "nonfinite",
    ],
)
def test_invalid_specifications_cannot_generate_a_valid_proposal(change):
    value = load("rectangle-inward")
    spec = value["wall_specification"]
    p = spec["treatments"][0]["wall"]
    if change == "binding":
        spec["source_candidate_digest"] = "0" * 64
    elif change == "unknown_requirement":
        p["requirement_ids"] = ["UNKNOWN"]
    elif change == "unknown_floor":
        spec["treatments"][0]["selector"]["floor_ids"] = ["NOFLOOR"]
    elif change == "duplicate_id":
        spec["treatments"].append(deepcopy(spec["treatments"][0]))
    elif change == "conflicting_intent":
        other = deepcopy(spec["treatments"][0])
        other["id"] = "CONFLICT"
        other["wall"]["thickness"]["value"] = 0.3
        spec["treatments"].append(other)
    elif change == "zero_thickness":
        p["thickness"]["value"] = 0
    else:
        p["thickness"]["value"] = float("inf")
    assert generate_walls(value)["wall_status"] == "INVALID_INPUT"


def test_different_wall_offset_cannot_create_remote_junction_bridge():
    value = load("l-junction")
    value["wall_specification"]["special_walls"][0]["wall"]["offset"] = {"value": 10, "unit": "m"}
    r = generate_walls(value)
    assert r["wall_status"] in {"UNSUPPORTED", "CONFLICT"}
    assert any(e["code"] == "OFFSET_JUNCTION_DISCONNECTED" for e in r["missing_information"])


def test_semantically_changed_walls_invalidate_derived_binding_but_not_source():
    value = load("rectangle-inward")
    before = deepcopy(value["source"])
    first = generate_walls(value)
    value["wall_specification"]["treatments"][0]["wall"]["thickness"]["value"] = 0.3
    second = generate_walls(value)
    assert first["source_candidate_digest"] == second["source_candidate_digest"]
    assert first["wall_revision_id"] != second["wall_revision_id"]
    assert first["derived_geometry_digest"] != second["derived_geometry_digest"]
    assert value["source"] == before
    assert not second["cad_writes_permitted"] and not second["approval_inherited"]


def test_source_approval_is_not_wall_approval():
    value = load("rectangle-inward")
    p = value["wall_specification"]["treatments"][0]["wall"]
    p["approval_status"] = "approved"
    r = generate_walls(value)
    assert r["wall_status"] == "INCOMPLETE"
    assert all(w["approval_status"] == "PROPOSED" for w in r["walls"])
    assert r["architect_approval"] == "NOT_GRANTED"


def test_all_output_polygons_and_schema_are_valid(reports):
    for r in reports.values():
        check = new_report("test")
        assert schema_check(r, "wall-result.schema.json", check), check
        for floor in r["floors"]:
            assert shape(floor["wall_footprint"]).is_valid
        for room in r["rooms"]:
            assert room["allocation_area_m2"] == pytest.approx(
                room["wall_occupied_area_m2"] + room["clear_area_m2"]
            )
        assert not r["cad_writes_permitted"]
        assert r["standards_review"] == r["fengshui_review"] == "NOT_EVALUATED"
    svg = wall_svg(reports["rectangle-inward"])
    assert 'preserveAspectRatio="xMidYMid meet"' in svg and "<metadata>" in svg
    assert "16.56" in svg and reports["rectangle-inward"]["wall_revision_id"] in svg


def test_orthogonal_concave_allocation_generates_real_walls_and_retains_replay_limit():
    r = generate_walls(load("orthogonal-room"))
    assert r["geometry_status"] == "VALID" and r["walls"]
    assert r["wall_status"] == "INCOMPLETE"
    assert r["constraint_impact"]["allocation_replay_status"] == "UNSUPPORTED"
    # Clear L: 3.7*5.6 + 3.9*1.7 = 27.35, original L allocation = 32.
    room = r["rooms"][0]
    assert room["allocation_area_m2"] == 32
    assert room["clear_area_m2"] == pytest.approx(27.35)
    assert (
        room["component_count"] == 1 and len(room["clear_geometry"]["polygons"][0]["exterior"]) == 7
    )


def test_explicit_mm_source_coordinates_are_converted_once():
    r = generate_walls(load("millimeter-coordinates"))
    assert (
        r["wall_status"] == "GENERATED" and r["source_units"] == "mm" and r["output_units"] == "m"
    )
    assert r["rooms"][0]["clear_area_m2"] == pytest.approx(16.56)
    assert r["floors"][0]["wall_union_area_m2"] == pytest.approx(3.44)
    assert (
        r["derived_geometry_digest"]
        == generate_walls(load("rectangle-inward"))["derived_geometry_digest"]
    )
