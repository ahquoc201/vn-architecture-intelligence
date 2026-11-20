"""Independent B3 arithmetic, geometry, clearance and immutable revision oracles."""

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import json
import math
import pytest
from vnai.stair_drafting import draft_stairs, validate_drafting
from vnai.stair_geometry import exact, pitch
from vnai.stair_preview import stair_svg
from vnai.opening_hosts import shape_set
from vnai.contracts import new_report, schema_check

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / "examples/batch007b3" / (name + ".json")).read_text())


@lru_cache(maxsize=64)
def report(name):
    return draft_stairs(load(name))


def approx(value):
    return pytest.approx(value, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("name", ["straight", "l-shaped", "u-shaped"])
def test_supported_configuration_has_real_geometry(name):
    r = report(name)
    s = r["stairs"][0]
    assert s["geometry_status"] == "VALID"
    assert all(
        shape_set(f["geometry"]).is_valid and shape_set(f["geometry"]).area > 0
        for f in s["flights"]
    )
    assert all(shape_set(t["geometry"]).is_valid for t in s["surfaces"])
    assert r["geometry_status"] == "VALID" and r["drafting_status"] == "INCOMPLETE"
    assert (
        r["headroom"]["coverage_complete"] and r["headroom"]["status"] == "VERIFIED_MODELED_SCOPE"
    )
    assert not r["approval_inherited"] and not r["cad_writes_permitted"]
    assert r["architect_approval"] == "NOT_GRANTED"


def test_straight_independent_oracle_a():
    s = report("straight")["stairs"][0]
    f = s["flights"][0]
    assert f["risers"] == 20 and f["ordinary_treads"] == 19
    assert f["riser_height_m"] == 0.165 and f["run_m"] == 4.75
    assert f["pitch_degrees"] == pytest.approx(math.degrees(math.atan(0.165 / 0.25)), abs=1e-12)
    assert s["final_elevation_m"] == 3.3 and s["closure_residual_m"] == 0
    assert shape_set(f["geometry"]).bounds == approx([4, 1, 8.75, 2])
    assert [t["elevation_m"] for t in f["treads"]] == [
        float(Fraction(165 * i, 1000)) for i in range(1, 20)
    ]
    assert len(f["risers_geometry"]) == 20
    assert f["section_profile"][-1] == [4.75, 3.3]
    assert s["section_kind"] == "TRUE_LONGITUDINAL"


@pytest.mark.parametrize("name", ["l-shaped", "u-shaped"])
def test_two_flight_independent_oracle_b(name):
    s = report(name)["stairs"][0]
    assert [f["ordinary_treads"] for f in s["flights"]] == [9, 9]
    assert [f["run_m"] for f in s["flights"]] == [2.25, 2.25]
    assert [f["riser_height_m"] for f in s["flights"]] == [0.165, 0.165]
    assert s["flights"][0]["arrival_elevation_m"] == 1.65
    assert s["final_elevation_m"] == 3.3
    landing = next(t for t in s["surfaces"] if t["kind"] == "landing")
    assert landing["elevation_m"] == 1.65
    assert s["section_kind"] == "DEVELOPED_EXPLICIT_WALKING_LINE"
    assert "DEVELOPED_EXPLICIT_WALKING_LINE" in stair_svg(report(name), "section")
    assert (
        shape_set(s["flights"][0]["geometry"])
        .intersection(shape_set(s["flights"][1]["geometry"]))
        .area
        == 0
    )


def test_unequal_allocations_keep_exact_landing():
    s = report("unequal-risers")["stairs"][0]
    assert [f["risers"] for f in s["flights"]] == [12, 8]
    assert [f["ordinary_treads"] for f in s["flights"]] == [11, 7]
    assert [f["run_m"] for f in s["flights"]] == [2.75, 1.75]
    assert s["flights"][0]["arrival_elevation_m"] == 1.98 and s["final_elevation_m"] == 3.3


def test_local_clearance_independent_oracle_c():
    h = report("local-headroom")["headroom"]
    m = next(
        m
        for m in h["measurements"]
        if m["surface_id"] == "FL1-T8" and m["obstruction_id"] == "LOCAL-BEAM"
    )
    assert m["walking_elevation_m"] == 1.2 and m["underside_m"] == 3.4
    assert m["clearance_m"] == approx(2.2)
    assert shape_set(m["region"]).area == approx(0.2)
    assert h["minimum_verified_clearance_m"] == approx(2.2)
    assert h["coverage_complete"]


@pytest.mark.parametrize(
    "name,n,source,destination",
    [("non-integral-riser", 19, 0, 3.3), ("offset-final-elevation", 20, 17.35, 20.65)],
)
def test_exact_nonintegral_closure_oracle_d(name, n, source, destination):
    s = report(name)["stairs"][0]
    f = s["flights"][0]
    h = (Fraction(str(destination)) - Fraction(str(source))) / n
    assert f["riser_height_m"] == float(h)
    assert s["final_elevation_m"] == destination and s["closure_residual_m"] == 0
    assert f["risers_geometry"][-1]["top_m"] == destination


def test_nonuniform_last_riser_is_preserved_not_smoothed():
    r = report("nonuniform-final-riser")
    f = r["stairs"][0]["flights"][0]
    assert f["riser_height_m"] == 0.16 and f["last_riser_height_m"] == 0.26
    assert r["stairs"][0]["final_elevation_m"] == 3.3
    assert "NONUNIFORM_FINAL_RISER" in {i["code"] for i in r["warnings"]}
    assert f["treads"][-1]["elevation_m"] == 3.04


@pytest.mark.parametrize(
    "name,code",
    [
        ("invalid-floor-elevation", "SOURCE_FLOOR_ELEVATION_MISMATCH"),
        ("missing-floor-elevation", "FLOOR_ELEVATION_REQUIRED"),
        ("inconsistent-tread-count", "TREAD_RISER_CONVENTION"),
        ("outside-envelope", "STAIR_OUTSIDE_ENVELOPE"),
        ("invalid-landing", "RECTANGULAR_REGION_REQUIRED"),
        ("disconnected-landing", "LANDING_FLIGHT_CONNECTION"),
        ("known-wall-collision", "STAIR_WALL_COLLISION"),
        ("door-swing-collision", "DOOR_STAIR_MOVEMENT_COLLISION"),
        ("missing-slab-opening", "SLAB_OPENING_INFORMATION_REQUIRED"),
        ("headroom-failure", "HEADROOM_BELOW_DECLARED_REQUIREMENT"),
        ("missing-overhead", "HEADROOM_COVERAGE_INCOMPLETE"),
        ("partial-headroom", "HEADROOM_COVERAGE_INCOMPLETE"),
        ("stale-opening-digest", "STALE_SOURCE_OPENING_DRAFT"),
        ("approval-not-inherited", "STAIR_CHILD_REVIEW_REQUIRED"),
        ("missing-plan-cut", "STAIR_PLAN_CUT_REQUIRED"),
        ("known-fixed-collision", "STAIR_PRISM_COLLISION"),
    ],
)
def test_known_failure_and_missing_evidence_are_explicit(name, code):
    r = report(name)
    assert code in {e["code"] for k in ["errors", "warnings", "missing_information"] for e in r[k]}
    assert r["drafting_status"] != "GENERATED" and not r["cad_writes_permitted"]


@pytest.mark.parametrize("name", ["unsupported-spiral", "unsupported-winders"])
def test_unsupported_is_not_approximated(name):
    r = report(name)
    assert r["drafting_status"] == "UNSUPPORTED" and not r["stairs"]


def test_plan_cut_classifies_without_deleting_physical_geometry():
    r = report("straight")
    s = r["stairs"][0]
    assert len(s["flights"][0]["treads"]) == 19
    classes = s["plan_views"][0]["surface_classes"]
    assert {c["classification"] for c in classes} == {"ABOVE_CUT", "BELOW_CUT"}
    assert "stroke-dasharray" in stair_svg(r, "plan")
    assert len(report("missing-plan-cut")["stairs"][0]["flights"][0]["treads"]) == 19


def test_floor_opening_and_slab_are_known_not_invented():
    r = report("floor-opening-valid")
    assert r["floor_openings"][0]["opening_ids"] == ["VOID-F2"]
    slab = r["sources"]["slab_material"][0]
    assert slab["bottom_m"] == 3.1 and slab["top_m"] == 3.3
    assert shape_set(slab["geometry"]).area == approx(169 - 40)
    assert report("missing-slab-opening")["floor_openings"][0]["status"] == "INCOMPLETE"


def test_headroom_failure_and_partial_coverage_are_separate():
    assert report("headroom-failure")["headroom"]["status"] == "FAILED"
    h = report("partial-headroom")["headroom"]
    assert h["status"] == "INCOMPLETE" and h["measurements"] and h["uncovered_regions"]
    assert report("missing-overhead")["headroom"]["minimum_verified_clearance_m"] is None


def test_graph_edge_does_not_prove_headroom_or_physical_access():
    r = report("graph-without-clearance")
    links = r["circulation"]["stairs"]["stair_results"]
    assert links[0]["graph_eligible"] and links[0]["entry_exit_valid"] == [True, True]
    assert r["headroom"]["status"] == "INCOMPLETE"
    assert r["circulation"]["physical_status"] == "NOT_VERIFIED"


def test_townhouse_source_is_exact_and_conflicts_retained():
    v = load("townhouse-benchmark")
    original = json.loads((ROOT / "examples/batch007b2/townhouse-benchmark.json").read_text())
    assert v["source"] == original
    r = report("townhouse-benchmark")
    assert r["drafting_status"] == "CONFLICT"
    assert "STAIR_RESERVATION_FIT" in {e["code"] for e in r["errors"]}
    assert r["source_conflicts"] and r["headroom"]["status"] == "FAILED"
    assert not r["headroom"]["coverage_complete"] and r["headroom"]["uncovered_regions"]
    assert not r["cad_writes_permitted"]


def test_schedule_matches_actual_counts_and_dimensions():
    r = report("u-shaped")
    s = r["stairs"][0]
    schedule = r["schedule"][0]
    assert schedule["rise_m"] == 3.3 and len(schedule["flights"]) == 2
    assert sum(f["ordinary_treads"] for f in schedule["flights"]) == 18
    assert schedule["landings"][0]["elevation_m"] == 1.65
    assert schedule["review_status"] == "PROPOSED"
    assert s["review_status"] == "PROPOSED"


def test_repeat_immutability_and_stored_report_recomputation():
    v = load("straight")
    before = deepcopy(v)
    r = draft_stairs(v)
    assert v == before and draft_stairs(v) == r and validate_drafting(r) == r
    tampered = deepcopy(r)
    tampered["stairs"][0]["flights"][0]["risers"] = 999
    assert validate_drafting(tampered)["drafting_status"] == "INVALID_INPUT"
    check = new_report("check")
    assert schema_check(r, "stair-drafting-result.schema.json", check), check


def test_dimension_units_are_exact_and_pitch_is_independent():
    assert exact(3300, Fraction(1, 1000)) == Fraction(33, 10)
    for ratio in [Fraction(1, 100), Fraction(33, 50), Fraction(1), Fraction(10), Fraction(100000)]:
        assert pitch(ratio, Fraction(1)) == pytest.approx(
            math.degrees(math.atan(float(ratio))), abs=1e-12
        )


@pytest.mark.parametrize("key", ["frame_id", "source_opening_revision_id"])
def test_stale_frame_and_binding_fail_before_geometry(key):
    v = load("straight")
    if key == "frame_id":
        v["specification"][key] = "wrong"
    else:
        v[key] = "wrong"
    r = draft_stairs(v)
    assert r["drafting_status"] == "INVALID_INPUT" and not r["stairs"]


def test_oversized_integer_is_bounded_before_float_conversion():
    v = load("straight")
    v["specification"]["stairs"][0]["flights"][0]["origin"][0] = 10**400
    assert draft_stairs(v)["drafting_status"] == "INVALID_INPUT"


def test_headroom_decimal_threshold_does_not_false_fail():
    from stair_drafting_fixtures import geometry, NOTICE

    v = load("straight")
    spec = v["specification"]
    stair = spec["stairs"][0]
    stair["flights"][0].update(risers=30, tread_depth=0.15)
    stair["arrival"]["geometry"] = geometry(8.35, 1, 9, 2)
    spec["headroom_requirement"] = 2.2
    spec["obstacles"].append(
        {
            "id": "DECIMAL-BEAM",
            "kind": "beam",
            "geometry": geometry(5.35, 1, 5.5, 2),
            "bottom": 3.3,
            "top": 3.5,
            "provenance": NOTICE,
        }
    )
    r = draft_stairs(v)
    measurement = next(
        m
        for m in r["headroom"]["measurements"]
        if m["surface_id"] == "FL1-T10" and m["obstruction_id"] == "DECIMAL-BEAM"
    )
    assert measurement["walking_elevation_m"] == 1.1 and measurement["clearance_m"] == 2.2
    assert r["headroom"]["status"] == "VERIFIED_MODELED_SCOPE"


def test_millimetre_spec_has_identical_physical_output():
    v = load("straight")
    before = report("straight")
    spec = v["specification"]
    spec["units"] = "mm"
    for record in spec["levels"]:
        record["finished_elevation"] *= 1000
    for record in spec["plan_cut_elevations"]:
        record["elevation"] *= 1000
    for stair in spec["stairs"]:
        for f in stair["flights"]:
            f["origin"] = [x * 1000 for x in f["origin"]]
            for key in ["width", "tread_depth"]:
                f[key] *= 1000
        if "arrival" in stair:
            stair["arrival"]["exit_point"] = [x * 1000 for x in stair["arrival"]["exit_point"]]
    for record in spec["slabs"]:
        for key in ["underside", "top"]:
            record[key] *= 1000
    for record in spec["obstacles"]:
        for key in ["bottom", "top"]:
            record[key] *= 1000
    for key in ["headroom_requirement", "clear_width_requirement"]:
        spec[key] *= 1000
    r = draft_stairs(v)
    assert r["stairs"] == before["stairs"] and r["headroom"] == before["headroom"]


def test_full_stair_edge_must_fit_clear_portal_not_only_midpoint():
    from stair_drafting_fixtures import rebind

    v = load("u-shaped")
    o = v["source"]["specification"]["openings"][0]
    o.update(clear_width=0.5, clear_start_offset=0.35)
    rebind(v)
    r = draft_stairs(v)
    assert "STAIR_PORTAL_EDGE_WIDTH" in {e["code"] for e in r["errors"]}


def test_rectangular_slab_boundary_contact_is_not_penetration():
    r = report("u-shaped")
    assert not {"STAIR_RISER_PRISM_COLLISION", "STAIR_PRISM_COLLISION"} & {
        e["code"] for e in r["errors"]
    }
    assert r["stairs"][0]["flights"][-1]["exit_edge"][0][0] == 4


def test_missing_slab_does_not_become_complete_headroom_from_a_ceiling():
    r = report("missing-slab-opening")
    assert r["headroom"]["measurements"]
    assert r["headroom"]["status"] == "INCOMPLETE"
    assert not r["headroom"]["floor_opening_evidence_complete"]
    assert r["headroom"]["unresolved_floor_ids"] == ["F2"]


def test_local_physical_scope_requires_actual_portals_and_headroom():
    r = report("u-shaped")
    assert r["circulation"]["physical_status"] == "GEOMETRICALLY_TRAVERSABLE"
    assert (
        r["circulation"]["scope"]
        == "MODELED_STAIRS_AND_FRESH_006B_INTERFACES_NOT_WHOLE_BUILDING_ACCESS"
    )
    assert r["architect_approval"] == "NOT_GRANTED"
    assert report("headroom-failure")["geometry_status"] == "VALID"
    assert report("headroom-failure")["circulation"]["physical_status"] == "BLOCKED"


@pytest.mark.parametrize("modeled_upper", [False, True])
def test_stacked_flights_need_explicit_upper_undersides(modeled_upper):
    from vnai.stair_clearance import verify
    from vnai.stair_geometry import construct
    from vnai.review_common import build_context, Space

    v = load("straight")
    spec = deepcopy(v["specification"])
    lower = deepcopy(report("straight")["stairs"][0])
    source = report("straight")["sources"]["opening_model"]
    ctx = build_context(deepcopy(v["source"]["source"]["source"]["replay"]["review"]))
    ctx.floors.add("F3")
    ctx.geometry["floors"].append({"id": "F3", "elevation_m": 6.6})
    original = ctx.spaces["SW-F2"]
    ctx.spaces["SW-F3"] = Space("SW-F3", "stairwell", "F3", "SW-F3", original.shape)
    levels = {"F1": Fraction(0), "F2": Fraction(33, 10), "F3": Fraction(33, 5)}
    upper_row = deepcopy(spec["stairs"][0])
    upper_row.update(
        id="S2", source_floor="F2", destination_floor="F3", stairwell_ids=["SW-F2", "SW-F3"]
    )
    upper_row["flights"][0]["id"] = "UPPER-FL"
    errors = []
    upper = construct(
        upper_row,
        levels,
        Fraction(1),
        ctx.tolerance,
        ctx.area_tolerance,
        lambda *args: errors.append(args),
    )
    assert not errors
    spec["stairs"].append(upper_row)
    opening = deepcopy(spec["floor_openings"][0])
    opening.update(id="VOID-F3", floor_id="F3", stair_ids=["S2"])
    spec["floor_openings"].append(opening)
    slab = deepcopy(spec["slabs"][0])
    slab.update(id="SLAB-F3", floor_id="F3", underside=6.4, top=6.6, opening_ids=["VOID-F3"])
    spec["slabs"].append(slab)
    spec["obstacles"][0].update(bottom=10, top=10.2)
    if modeled_upper:
        for surface in upper["surfaces"]:
            spec["obstacles"].append(
                {
                    "id": "UNDERSIDE-" + surface["id"],
                    "kind": "upper_stair",
                    "geometry": surface["geometry"],
                    "bottom": surface["elevation_m"] - 0.15,
                    "top": surface["elevation_m"],
                    "provenance": "Explicit synthetic stepped underside .15m below upper walking tops.",
                }
            )
    result = verify(
        [lower, upper], spec, source, levels, ctx, Fraction(1), lambda *args: errors.append(args)
    )
    if modeled_upper:
        assert result["headroom"]["status"] == "VERIFIED_MODELED_SCOPE"
        assert result["headroom"]["minimum_verified_clearance_m"] == approx(3.15)
        assert not errors
    else:
        assert result["headroom"]["status"] == "INCOMPLETE"
        assert not result["headroom"]["upper_stair_evidence_complete"]
        assert "UPPER_STAIR_UNDERSIDE_REQUIRED" in {e[1] for e in errors}


def test_distinct_stairs_cannot_occupy_identical_walking_surfaces():
    v = load("straight")
    duplicate = deepcopy(v["specification"]["stairs"][0])
    duplicate["id"] = "S2"
    duplicate["flights"][0]["id"] = "DUP-FLIGHT"
    v["specification"]["stairs"].append(duplicate)
    v["specification"]["floor_openings"][0]["stair_ids"].append("S2")
    r = draft_stairs(v)
    assert r["drafting_status"] == "CONFLICT"
    assert "STAIR_STAIR_COLLISION" in {e["code"] for e in r["errors"]}
    assert r["circulation"]["physical_status"] == "BLOCKED"


def test_explicit_nosing_geometry_is_generated_without_default_detail():
    from vnai.stair_geometry import construct
    from stair_drafting_fixtures import geometry

    row = load("straight")["specification"]["stairs"][0]
    row["flights"][0]["nosing"] = 0.02
    row["envelope"] = geometry(3.9, 0, 9, 8)
    errors = []
    s = construct(
        row,
        {"F1": Fraction(0), "F2": Fraction(33, 10)},
        Fraction(1),
        0,
        0,
        lambda *args: errors.append(args),
    )
    assert not errors
    assert shape_set(s["flights"][0]["geometry"]).bounds == approx([3.98, 1, 8.75, 2])
    assert s["flights"][0]["treads"][0]["nosing_line"] == [[3.98, 1], [3.98, 2]]
    assert report("straight")["stairs"][0]["flights"][0]["treads"][0]["nosing_line"] is None


def test_developed_diagonal_landing_length_is_correctly_rounded():
    from vnai.stair_geometry import construct

    row = load("l-shaped")["specification"]["stairs"][0]
    row["landings"][0]["walking_line"] = [[6.25, 1.5], [6.75, 2]]
    errors = []
    s = construct(
        row,
        {"F1": Fraction(0), "F2": Fraction(33, 10)},
        Fraction(1),
        0,
        0,
        lambda *args: errors.append(args),
    )
    assert not errors
    landing = next(t for t in s["surfaces"] if t["kind"] == "landing")
    assert landing["developed_length_m"] == 0.7071067811865476
    assert s["section_kind"] == "DEVELOPED_EXPLICIT_WALKING_LINE"


def test_revision_reports_actual_affected_interfaces_without_inheriting_approval():
    r = report("u-shaped")
    impact = r["evidence_impact"]
    assert impact["affected_room_ids"] == ["BED:1", "LIVING:1"]
    assert len(impact["affected_wall_ids"]) == 2
    assert impact["affected_opening_ids"] == ["PORTAL-F1", "PORTAL-F2"]
    assert impact["affected_floor_ids"] == ["F1", "F2"]
    assert impact["source_candidate_unchanged"] and impact["source_wall_opening_geometry_unchanged"]
    assert "architect_approval" in impact["stale"] and not impact["approval_inherited"]


def test_explicit_balanced_flight_heights_are_not_forced_to_unstated_uniformity():
    from vnai.stair_geometry import construct

    row = load("l-shaped")["specification"]["stairs"][0]
    row["flights"][0]["riser_height"] = 0.15
    row["flights"][1]["riser_height"] = 0.18
    row["landings"][0]["elevation"] = 1.5
    diagnostics = []
    s = construct(
        row,
        {"F1": Fraction(0), "F2": Fraction(33, 10)},
        Fraction(1),
        0,
        0,
        lambda *args: diagnostics.append(args),
    )
    assert s["final_elevation_m"] == 3.3 and s["flights"][0]["arrival_elevation_m"] == 1.5
    assert [f["riser_height_m"] for f in s["flights"]] == [0.15, 0.18]
    assert all(d[0] == "warning" for d in diagnostics)
    assert "NONUNIFORM_FLIGHT_RISERS" in {d[1] for d in diagnostics}


def test_unresolved_original_constraints_remain_visible_after_stair_replay():
    r = report("u-shaped")
    assert "SOURCE_WALL_LIMITATIONS" in {e["code"] for e in r["missing_information"]}
    parent = r["sources"]["opening_model"]["sources"]["wall_model"]
    assert "ALLOCATION_REPLAY_STALE" in {e["code"] for e in parent["missing_information"]}
    assert r["circulation"]["physical_status"] == "GEOMETRICALLY_TRAVERSABLE"
    assert r["drafting_status"] == "INCOMPLETE"


@pytest.mark.parametrize("name", ["l-right-turn", "u-right-turn"])
def test_right_turn_is_valid_without_left_side_gap_assumptions(name):
    r = report(name)
    s = r["stairs"][0]
    assert s["geometry_status"] == "VALID"
    assert s["final_elevation_m"] == 3.3
    assert not {"STAIR_TURN_GEOMETRY", "STAIR_RETURN_GEOMETRY", "STAIR_FLIGHT_SEPARATION"} & {
        e["code"] for e in r["errors"]
    }
    if s["type"] == "U":
        assert shape_set(s["flights"][0]["geometry"]).distance(
            shape_set(s["flights"][1]["geometry"])
        ) == approx(0.2)
        assert [f["direction"] for f in s["flights"]] == [[1, 0], [-1, 0]]


def test_authored_synthetic_source_brief_matches_its_actual_site_and_footprint():
    from shapely.geometry import Polygon
    from vnai.zoning import decision_digest

    for path in sorted((ROOT / "examples/batch007b3").glob("*.json")):
        if path.stem == "townhouse-benchmark":
            continue
        value = json.loads(path.read_text())
        g = value["source"]["source"]["source"]["replay"]["review"]["candidate"]["geometry"]
        z = g["zoning"]
        site = Polygon(next(p["exterior"] for p in g["polygons"] if p["role"] == "site"))
        footprint = Polygon(next(p["exterior"] for p in g["polygons"] if p["role"] == "footprint"))
        dimensions = z["brief"]["site"]["dimensions"]["value"]
        assert (
            dimensions["width"] == site.bounds[2] - site.bounds[0]
            and dimensions["length"] == site.bounds[3] - site.bounds[1]
        )
        assert z["brief"]["building"]["footprint"]["value"]["target"] == footprint.area
        for event in z["decisions"]:
            assignment = next(a for a in z["assignments"] if a["id"] == event["decision_id"])
            assert event["record"]["digest"] == decision_digest(z, assignment)
            assert event["record"]["actor"] == "SYNTHETIC_TEST_ARCHITECT_NOT_REAL_APPROVAL"


@pytest.mark.parametrize("floor,sign", [("F1", 1), ("F2", -1)])
def test_plan_arrow_geometry_reverses_on_down_view(floor, sign):
    import xml.etree.ElementTree as ET

    svg = ET.fromstring(stair_svg(report("straight"), "plan"))
    namespace = {"s": "http://www.w3.org/2000/svg"}
    group = next(
        g
        for g in svg.findall("s:g", namespace)
        if g.attrib.get("data-floor") == floor and g.attrib.get("class") == "stair-direction"
    )
    paths = group.findall("s:polyline", namespace)

    def points(el):
        return [tuple(map(float, p.split(","))) for p in el.attrib["points"].split()]

    travel = points(paths[0])
    head = points(paths[1])
    assert (travel[-1][0] - travel[0][0]) * sign > 0
    assert head[1] == travel[-1]
    assert group.attrib["data-direction"] == ("UP" if sign == 1 else "DOWN")


@pytest.mark.parametrize("missing", ["headroom_requirement", "clear_width_requirement"])
def test_measurements_do_not_invent_unsupplied_physical_requirements(missing):
    value = load("u-shaped")
    value["specification"].pop(missing)
    result = draft_stairs(value)
    assert result["geometry_status"] == "VALID"
    assert result["headroom"]["status"] == "VERIFIED_MODELED_SCOPE"
    assert result["headroom"]["minimum_verified_clearance_m"] is not None
    assert result["circulation"]["physical_status"] == "NOT_VERIFIED"
    assert not result["cad_writes_permitted"]
