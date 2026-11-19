"""Independent B2 cut, movement, floor-level and immutability oracles."""

from copy import deepcopy
import math
import json
from pathlib import Path
import pytest
from shapely.geometry import Point
from opening_drafting_fixtures import oracle
from vnai.opening_drafting import draft_openings, validate_drafting
from vnai.opening_hosts import shape_set
from vnai.contracts import new_report, schema_check


def metric(expected):
    return pytest.approx(expected, rel=1e-12, abs=1e-12)


@pytest.fixture(scope="module")
def one():
    v = oracle()
    return v, draft_openings(v)


def test_analytical_wall_door_cut_oracle(one):
    _, r = one
    assert r["drafting_status"] == "GENERATED" and r["geometry_status"] == "VALID"
    f = r["floors"][0]
    assert f["source_wall_area_m2"] == metric(0.8)
    assert f["plan_cut_area_m2"] == metric(0.18)
    assert f["remaining_wall_plan_area_m2"] == metric(0.62)
    assert f["floor_wall_obstruction_area_m2"] == metric(0.62)
    assert f["walls"][0]["plan_component_count"] == 2
    assert r["rooms"][0]["clear_floor_area_m2"] == metric(19.2)
    assert r["rooms"][0]["door_threshold_contribution_m2"] == metric(0.18)
    assert r["schedule"][0]["rough_width_m"] == 0.9
    assert r["schedule"][0]["leaf_width_m"] == 0.78
    assert r["schedule"][0]["clear_width_m"] == 0.74
    assert r["schedule"][0]["frame_inner_width_m"] == metric(0.82)


def test_hinged_geometry_independent_axis_oracle(one):
    p = one[1]["openings"][0]["primitives"]
    assert p["hinge_point"] == metric([1.56, 0.2])
    assert p["swing_arc"]["end"] == metric([1.56, 0.98])
    assert p["swing_arc"]["radius_m"] == 0.78
    envelope = shape_set(p["movement_envelope"])
    for i in range(91):
        angle = math.radians(i)
        assert envelope.covers(Point(1.56 + 0.78 * math.cos(angle), 0.2 + 0.78 * math.sin(angle)))
    assert shape_set(p["open_leaf"]).bounds == metric((1.5425, 0.2, 1.5775, 0.98))


def test_fresh_graph_and_supplied_route_replay(one):
    r = one[1]
    assert r["circulation"]["graph"]["graph_status"] == "GRAPH_CONNECTED"
    assert r["circulation"]["clearance"]["physical_status"] == "GEOMETRICALLY_TRAVERSABLE"
    assert r["openings"][0]["physical_state"] == "GEOMETRICALLY_TRAVERSABLE"
    assert not r["cad_writes_permitted"] and not r["approval_inherited"]
    assert r["architect_approval"] == "NOT_GRANTED"


def test_input_immutable_repeatable_and_stored_validation(one):
    v, r = one
    before = deepcopy(v)
    assert draft_openings(v) == r and v == before
    assert validate_drafting(r) == r
    altered = deepcopy(r)
    altered["floors"][0]["plan_cut_area_m2"] = 999
    assert validate_drafting(altered)["drafting_status"] == "INVALID_INPUT"
    check = new_report("test")
    assert schema_check(r, "opening-drafting-result.schema.json", check), check


def test_overlapping_cuts_rejected_without_area_double_count(one):
    v = deepcopy(one[0])
    second = deepcopy(v["specification"]["openings"][0])
    second.update(id="DOOR-2", mark="D02", offset=1.8)
    v["specification"]["openings"].append(second)
    r = draft_openings(v)
    assert r["drafting_status"] == "CONFLICT"
    assert all(not o["cut_accepted"] for o in r["openings"])
    assert r["floors"][0]["plan_cut_area_m2"] == 0
    assert r["floors"][0]["remaining_wall_plan_area_m2"] == metric(0.8)
    assert r["floors"][0]["proposed_cut_union_area_m2"] == metric(0.24)


@pytest.mark.parametrize(
    "change", ["wall_digest", "source_revision", "floor", "endpoint", "unknown_space"]
)
def test_invalid_hosts_do_not_apply_cuts(one, change):
    v = deepcopy(one[0])
    row = v["specification"]["openings"][0]
    if change == "wall_digest":
        row["source_wall_digest"] = "stale"
    if change == "source_revision":
        v["source_wall_revision_id"] = "stale"
    if change == "floor":
        row["floor_id"] = "unknown-floor"
    if change == "endpoint":
        row["start"] = [100, 100]
    if change == "unknown_space":
        row["space_ids"][0] = "unknown-space"
    r = draft_openings(v)
    assert r["drafting_status"] == "INVALID_INPUT"
    assert all(not o["cut_accepted"] for o in r["openings"])


ROOT = Path(__file__).resolve().parents[1]


def case(name):
    return json.loads((ROOT / "examples/batch007b2" / (name + ".json")).read_text())


@pytest.mark.parametrize("name,plan_cut", [("fixed-window", 0.34), ("window-above-cut", 0.18)])
def test_window_plan_cut_is_not_a_floor_passage(name, plan_cut):
    r = draft_openings(case(name))
    f = r["floors"][0]
    assert r["drafting_status"] == "GENERATED"
    assert f["plan_cut_area_m2"] == metric(plan_cut)
    assert f["floor_wall_obstruction_area_m2"] == metric(0.62)
    assert r["rooms"][0]["clear_floor_area_m2"] == metric(19.2)
    window = next(o for o in r["openings"] if o["type"].endswith("window"))
    assert not window["graph_eligible"] and not window["floor_cut_applied"]
    assert len(r["circulation"]["graph"]["edges"]) == 1
    assert r["circulation"]["graph"]["edges"][0]["id"] == "DOOR-1"
    assert not r["rooms"][0]["window_cut_added_to_room_area"]


def test_sliding_travel_and_leaf_geometry_are_measurable():
    r = draft_openings(case("sliding-valid"))
    p = r["openings"][0]["primitives"]
    assert r["drafting_status"] == "GENERATED"
    assert p["travel_m"] == 0.9 and p["sliding_mode"] == "surface"
    assert shape_set(p["open_leaf"]).bounds == metric((2.46, 0.24, 3.24, 0.275))
    assert p["movement_envelope_area_m2"] == metric((0.78 + 0.9) * 0.035)
    bad = draft_openings(case("sliding-insufficient-travel"))
    assert bad["drafting_status"] == "CONFLICT"
    assert any(e["code"] == "INSUFFICIENT_SLIDING_TRAVEL" for e in bad["errors"])


def test_host_junction_is_protected_without_applying_partial_cut():
    r = draft_openings(case("junction-interference"))
    assert r["drafting_status"] == "UNSUPPORTED"
    assert all(not o["cut_accepted"] for o in r["openings"])
    assert any(e["code"] == "OPENING_JUNCTION_INTERFERENCE" for e in r["missing_information"])
    assert r["floors"][0]["plan_cut_area_m2"] == 0


def test_historical_mapping_preserves_source_and_requires_new_evidence():
    v = case("historical-opening")
    source = deepcopy(v["source"])
    r = draft_openings(v)
    assert r["drafting_status"] == "INCOMPLETE" and r["geometry_status"] == "VALID"
    assert r["openings"][0]["host_resolution"] == "MIGRATED_UNAMBIGUOUS_REQUIRES_REVIEW"
    assert v["source"] == source
    assert not r["approval_inherited"]
    ambiguous = draft_openings(case("ambiguous-provisional-host"))
    assert any(d["code"] == "AMBIGUOUS_PROVISIONAL_HOST" for d in ambiguous["missing_information"])
    assert not ambiguous["openings"][0]["cut_accepted"]


def test_multiple_floors_do_not_share_cuts_or_invent_stairs():
    r = draft_openings(case("multiple-floors"))
    assert r["drafting_status"] == "INCOMPLETE" and len(r["floors"]) == 2
    assert [f["plan_cut_area_m2"] for f in r["floors"]] == metric([0.18, 0.18])
    assert len({o["host_wall_id"] for o in r["openings"]}) == 2
    assert r["circulation"]["clearance"]["physical_status"] != "GEOMETRICALLY_TRAVERSABLE"


def test_townhouse_keeps_exact_wall_source_and_original_requirements():
    v = case("townhouse-benchmark")
    assert v["source"] == json.loads(
        (ROOT / "examples/batch007b1/townhouse-benchmark.json").read_text()
    )
    r = draft_openings(v)
    assert r["drafting_status"] == "CONFLICT" and r["source_conflicts"]
    assert len(r["openings"]) == 4 and all(o["rough_cut"] for o in r["openings"])
    assert not r["drafting_readiness"]["approval_granted"]


def test_precision_sensitive_areas_use_exact_fraction_oracle(one):
    from fractions import Fraction

    f = one[1]["floors"][0]
    # Three independent integer/rational dimensions, no call to cut implementation.
    assert f["source_wall_area_m2"] == float(Fraction(4) * Fraction(1, 5))
    assert f["plan_cut_area_m2"] == float(Fraction(9, 10) * Fraction(1, 5))
    assert f["remaining_wall_plan_area_m2"] == metric(float(Fraction(31, 50)))


def test_declared_clear_span_cannot_intersect_actual_open_leaf(one):
    v = deepcopy(one[0])
    v["specification"]["openings"][0]["clear_start_offset"] = 0.04
    r = draft_openings(v)
    assert r["drafting_status"] == "CONFLICT"
    assert any(e["code"] == "DECLARED_CLEAR_PASSAGE_OBSTRUCTED" for e in r["errors"])


def test_wall_material_above_and_below_window_is_preserved():
    r = draft_openings(case("fixed-window"))
    bands = r["floors"][0]["walls"][0]["vertical_bands"]
    assert [(b["bottom_m"], b["head_m"]) for b in bands] == [
        (0, 0.8),
        (0.8, 1.8),
        (1.8, 2.1),
        (2.1, 3),
    ]
    assert [b["remaining_wall_area_m2"] for b in bands] == metric([0.62, 0.46, 0.62, 0.8])
    assert bands[0]["rough_void_opening_ids"] == ["DOOR-1"]
    assert not bands[-1]["rough_void_opening_ids"]


def to_mm(value):
    value = deepcopy(value)
    spec = value["specification"]
    spec["units"] = "mm"
    spec["plan_cut_height"] *= 1000
    for v in spec["wall_verticals"]:
        v["base"] *= 1000
        v["height"] *= 1000
    for row in spec["openings"]:
        for key in (
            "offset",
            "rough_width",
            "rough_height",
            "bottom",
            "sill",
            "head",
            "clear_width",
            "clear_height",
            "clear_start_offset",
            "frame_inner_width",
            "mount_offset",
        ):
            if key in row:
                row[key] *= 1000
        for key in ("frame", "leaf"):
            if key in row:
                for k, v in row[key].items():
                    if isinstance(v, (int, float)):
                        row[key][k] = v * 1000
        if "slide" in row:
            row["slide"]["travel"] *= 1000
        for k in ("start", "end"):
            if k in row:
                row[k] = [x * 1000 for x in row[k]]
    return value


def test_mm_specs_convert_once_and_have_identical_physical_digest():
    v = case("fixed-window")
    metric = draft_openings(v)
    mm = draft_openings(to_mm(v))
    assert mm["drafting_status"] == metric["drafting_status"] == "GENERATED"
    assert mm["opening_geometry_digest"] == metric["opening_geometry_digest"]
    assert mm["specification_digest"] != metric["specification_digest"]
    assert mm["floors"] == metric["floors"]
    unknown = to_mm(case("window-missing-elevation"))
    r = draft_openings(unknown)
    w = next(o for o in r["openings"] if o["type"].endswith("window"))
    assert w["rough_height_m"] == 1 and w["sill_m"] is None and w["head_m"] == 1.8


def test_plan_above_wall_top_has_no_wall_section_but_keeps_floor_obstruction(one):
    v = deepcopy(one[0])
    v["specification"]["plan_cut_height"] = 4
    r = draft_openings(v)
    f = r["floors"][0]
    assert r["drafting_status"] == "GENERATED"
    assert f["wall_area_at_cut_before_openings_m2"] == 0
    assert f["remaining_wall_plan_area_m2"] == 0 and f["plan_cut_area_m2"] == 0
    assert f["wall_area_outside_cut_elevation_m2"] == metric(0.8)
    assert f["floor_wall_obstruction_area_m2"] == metric(0.62)
    assert r["rooms"][0]["clear_floor_area_m2"] == metric(19.2)


def test_two_nonoverlapping_doors_union_and_schedule_quantity():
    r = draft_openings(case("repeated-mark-quantity"))
    f = r["floors"][0]
    assert r["drafting_status"] == "GENERATED"
    assert f["plan_cut_area_m2"] == metric(0.36)
    assert f["remaining_wall_plan_area_m2"] == metric(0.44)
    assert len(r["schedule"]) == 1 and r["schedule"][0]["quantity"] == 2
    assert r["schedule"][0]["declared_units"] == "m"


def test_centered_interior_and_inward_exterior_cut_independent_areas():
    r = draft_openings(case("interior-hinged"))
    assert r["floors"][0]["plan_cut_area_m2"] == metric(0.18 + 0.09)
    assert r["floors"][0]["remaining_wall_plan_area_m2"] == metric(5.23)


def test_closed_door_keeps_design_width_but_defers_current_walking(one):
    v = deepcopy(one[0])
    v["specification"]["openings"][0]["operating_state"] = "closed"
    r = draft_openings(v)
    assert r["drafting_status"] == "INCOMPLETE" and r["geometry_status"] == "VALID"
    assert r["openings"][0]["physical_state"] != "GEOMETRICALLY_TRAVERSABLE"
    assert r["openings"][0]["graph_eligible"]
    assert not any(e["code"] == "DECLARED_CLEAR_PASSAGE_OBSTRUCTED" for e in r["errors"])


@pytest.mark.parametrize(
    "change,expected",
    [
        ("head", "CONFLICT"),
        ("cut_edge", "UNSUPPORTED"),
        ("cut_missing", "INCOMPLETE"),
        ("wall_height_unknown", "INCOMPLETE"),
        ("frame_mismatch", "INVALID_INPUT"),
        ("numeric_scope", "UNSUPPORTED"),
        ("duplicate_vertical", "INVALID_INPUT"),
    ],
)
def test_vertical_frame_and_resource_limits(one, change, expected):
    v = deepcopy(one[0])
    row = v["specification"]["openings"][0]
    if change == "head":
        row["head"] = 2.5
    if change == "cut_edge":
        v["specification"]["plan_cut_height"] = 2.1
    if change == "cut_missing":
        v["specification"].pop("plan_cut_height")
    if change == "wall_height_unknown":
        v["specification"]["wall_verticals"] = []
    if change == "frame_mismatch":
        v["specification"]["frame_id"] = "different-frame"
    if change == "numeric_scope":
        row["rough_height"] = 1e300
    if change == "duplicate_vertical":
        v["specification"]["wall_verticals"] *= 2
    r = draft_openings(v)
    assert r["drafting_status"] == expected and not r["cad_writes_permitted"]


def test_stacked_openings_are_explicitly_unsupported_not_false_3d_overlap(one):
    from opening_drafting_fixtures import add_window

    v = add_window(one[0], offset=1.5, rough_width=0.9, sill=2.2, head=2.8, rough_height=0.6)
    r = draft_openings(v)
    assert r["drafting_status"] == "UNSUPPORTED"
    assert any(d["code"] == "STACKED_OPENINGS_UNSUPPORTED" for d in r["missing_information"])


def test_new_inputs_permutation_invariant_and_review_not_inherited():
    v = case("fixed-window")
    first = draft_openings(v)
    v["specification"]["openings"].reverse()
    v["specification"]["clearance_regions"].reverse()
    for row in v["specification"]["openings"]:
        row["space_ids"].reverse()
    assert draft_openings(v) == first
    pending = draft_openings(case("stale-approval-evidence"))
    assert pending["drafting_status"] == "INCOMPLETE"
    assert all(o["approval_status"] == "PROPOSED" for o in pending["openings"])
    assert pending["architect_approval"] == "NOT_GRANTED" and not pending["approval_inherited"]


def test_oversized_json_integer_reports_scope_without_overflow(one):
    v = deepcopy(one[0])
    v["specification"]["openings"][0]["rough_height"] = 10**400
    r = draft_openings(v)
    assert r["drafting_status"] == "UNSUPPORTED" and not r["cad_writes_permitted"]


def test_clear_width_is_checked_against_geometry_not_equated_to_leaf_width(one):
    v = deepcopy(one[0])
    v["specification"]["openings"][0]["leaf"]["width"] = 0.70
    r = draft_openings(v)
    assert r["drafting_status"] == "GENERATED"
    assert r["openings"][0]["clear_width_m"] == 0.74
    assert r["openings"][0]["primitives"]["leaf_width_m"] == 0.70
    assert r["openings"][0]["physical_state"] == "GEOMETRICALLY_TRAVERSABLE"
    # This is only the declared planar aperture; it proves no closed-leaf seal/assembly detail.


@pytest.mark.parametrize("name", ["unsupported-angle", "unsupported-pocket"])
def test_unsupported_motion_does_not_fabricate_open_pose(name):
    r = draft_openings(case(name))
    p = r["openings"][0]["primitives"]
    assert r["drafting_status"] == "UNSUPPORTED"
    assert "open_leaf" not in p and "movement_envelope" not in p
    assert not r["openings"][0]["cut_accepted"]


def test_missing_mount_or_window_operation_does_not_choose_a_default():
    v = case("sliding-valid")
    v["specification"]["openings"][0].pop("mount_offset")
    r = draft_openings(v)
    assert r["drafting_status"] == "INCOMPLETE"
    assert "open_leaf" not in r["openings"][0]["primitives"]
    v = case("operable-window")
    v["specification"]["openings"][1].pop("operation")
    r = draft_openings(v)
    window = next(o for o in r["openings"] if o["type"].endswith("window"))
    assert r["drafting_status"] == "INCOMPLETE" and "open_leaf" not in window["primitives"]
