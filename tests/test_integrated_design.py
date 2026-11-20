"""Independent arithmetic, source preservation and bounded integrated replay."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import json
import math
import xml.etree.ElementTree as ET
import pytest
from vnai.contracts import canonical_digest, new_report, schema_check
from vnai.engine_cache import EngineCache
from vnai.integrated_design import integrated_design, validate_integrated
from vnai.integrated_preview import integrated_svg
from vnai.opening_hosts import shape_set
from integrated_fixtures import area_oracle, partition_oracle
from floorplan_fixtures import approve_source

ROOT = Path(__file__).resolve().parents[1]


def spec():
    return json.loads(
        (ROOT / "examples/batch007b4/townhouse-4x20-v4.json").read_text(encoding="utf-8")
    )


@lru_cache(maxsize=1)
def report():
    return integrated_design(spec())


def test_mandatory_generated_multistorey_reference_is_actually_verified():
    r = report()
    assert r["integrated_status"] == "REFINED", [
        (o["verification_status"], o["conflicts"]) for o in r["originals"]
    ]
    assert r["search"]["evaluations"] == 2 and r["search"]["refinement_attempts"] == 1
    c = r["candidates"][0]
    assert c["hard_violations"] == 0 and c["required_unknown"] == 0
    assert c["verification_coverage"]["all_required_verified"]
    assert all(x["status"] == "VERIFIED" for x in c["checks"])
    assert set(c["candidate"]["floor_ids"]) == {"F1", "F2"}
    assert all(
        v == "GEOMETRICALLY_TRAVERSABLE"
        for v in c["integrated_circulation"]["room_access"].values()
    )
    assert all(
        o["physical_state"] == "NOT_APPLICABLE_WINDOW"
        for o in c["engines"]["openings"]["openings"]
        if o["type"].endswith("window")
    )
    assert r["ranking_status"] == "WITHHELD_NO_EVALUATION_POLICY"


def test_independent_room_area_dimensions_and_union_accounting():
    c = report()["candidates"][0]
    for room in c["engines"]["walls"]["rooms"]:
        p = shape_set(room["clear_geometry"])
        x0, y0, x1, y1 = p.bounds
        assert room["allocation_area_m2"] == 24
        assert x1 - x0 == pytest.approx(3.6, abs=1e-12)
        assert y1 - y0 == pytest.approx(5.7, abs=1e-12)
        assert room["clear_area_m2"] == pytest.approx(20.52, abs=1e-12)
    for f in c["accounting"]["floors"]:
        assert math.fsum(f["exclusive_partition"].values()) == pytest.approx(64, abs=1e-12)
        assert f["gross_floor_area_m2"] is None
    assert c["accounting"]["site_area_m2"] == 80
    assert c["accounting"]["building_clear_room_union_m2"] == pytest.approx(82.08, abs=1e-12)


def test_independent_stair_and_void_oracles():
    c = report()["candidates"][0]
    stairs = c["engines"]["stairs"]
    s = stairs["stairs"][0]
    assert [f["risers"] for f in s["flights"]] == [10, 10]
    assert [f["ordinary_treads"] for f in s["flights"]] == [9, 9]
    assert all(f["riser_height_m"] == 0.165 for f in s["flights"])
    assert all(f["run_m"] == 2.16 for f in s["flights"])
    assert s["final_elevation_m"] == 3.3 and s["closure_residual_m"] == 0
    assert shape_set(s["footprint"]).area == pytest.approx(4.518, abs=1e-12)
    assert stairs["headroom"]["minimum_verified_clearance_m"] == pytest.approx(3.165, abs=1e-12)
    assert (
        stairs["headroom"]["coverage_complete"]
        and stairs["headroom"]["floor_opening_evidence_complete"]
    )
    assert shape_set(spec()["stair_specification"]["floor_openings"][0]["geometry"]).area == 8.25


def test_refinement_preserves_every_requirement_fixed_geometry_and_opening_dimensions():
    r = report()
    before = r["originals"][0]
    after = r["candidates"][0]
    assert before["hard_violations"] > 0 and after["conflicts"] == []
    assert canonical_digest(before["candidate"]) == canonical_digest(after["candidate"])
    assert before["revision_id"] != after["revision_id"]
    assert (
        before["engines"]["walls"]["wall_revision_id"]
        == after["engines"]["walls"]["wall_revision_id"]
    )
    old = {o["id"]: o for o in before["opening_specification"]["openings"]}
    new = {o["id"]: o for o in after["opening_specification"]["openings"]}
    for key in old:
        if key == "ENTRANCE":
            assert {k: v for k, v in old[key].items() if k != "offset"} == {
                k: v for k, v in new[key].items() if k != "offset"
            }
        else:
            assert old[key] == new[key]
    assert old["ENTRANCE"]["offset"] == 2 and new["ENTRANCE"]["offset"] == 0.8
    assert r["attempts"][0]["accepted"] and not r["attempts"][0]["conflicts_introduced"]
    assert r["attempts"][0]["conflicts_resolved"]
    assert (
        after["candidate"]["geometry"]["zoning"]["brief"]
        == spec()["generation"]["geometry"]["zoning"]["brief"]
    )


def test_fresh_stair_evidence_does_not_overwrite_legacy_unknowns_or_grant_approval():
    c = report()["candidates"][0]
    assert c["engines"]["openings"]["circulation"]["clearance"]["physical_status"] == "NOT_VERIFIED"
    assert c["integrated_circulation"]["status"] == "GEOMETRICALLY_TRAVERSABLE"
    assert any(
        s["finding"]["code"] == "STAIR_WALKING_GEOMETRY_NOT_EVALUATED"
        for s in c["superseded_missing_checks"]
    )
    assert any(
        s["code"] == "STAIR_WALKING_GEOMETRY_NOT_EVALUATED"
        for s in c["upstream_findings_retained"]["openings"]["missing_information"]
    )
    assert (
        c["architect_approval"] == "NOT_GRANTED"
        and not c["approval_inherited"]
        and not c["cad_writes_permitted"]
    )


def test_real_svg_per_floor_and_comparison_bind_actual_revisions():
    r = report()
    for view in ["before", "after", "comparison", "section"]:
        svg = integrated_svg(r, view=view)
        ET.fromstring(svg)
        assert "false" in svg and ("CAD" in svg or "cad_writes_permitted" in svg)
    for floor in ["F1", "F2"]:
        svg = integrated_svg(r, view="after", floor=floor)
        ET.fromstring(svg)
        assert floor in svg and "20.52" in svg and ("UP" if floor == "F1" else "DOWN") in svg
        assert r["candidates"][0]["revision_id"] in svg
    with pytest.raises(ValueError):
        integrated_svg(r, floor="MISSING")


def test_stored_report_is_recomputed_and_tampering_rejected():
    r = report()
    current = validate_integrated(r)
    assert canonical_digest(current) == canonical_digest(r)
    edited = deepcopy(r)
    edited["candidates"][0]["candidate"]["room_areas_m2"]["BED:1"] = 999
    assert validate_integrated(edited)["integrated_status"] == "INVALID_INPUT"


def test_input_immutability_and_output_schema():
    data = spec()
    frozen = deepcopy(data)
    r = report()
    assert data == frozen
    check = new_report("check")
    assert schema_check(r, "integrated-design-result.schema.json", check), check
    assert canonical_digest(data) == canonical_digest(r["sources"]["input"])


def test_ephemeral_cache_reuses_only_exact_inputs_and_returns_isolated_results():
    cache = EngineCache()
    calls = []

    def build():
        calls.append(1)
        return {"nested": [7]}

    a = cache.run("engine", {"x": 1}, build)
    a["nested"][0] = 99
    assert cache.run("engine", {"x": 1}, build) == {"nested": [7]}
    cache.run("engine", {"x": 2}, build)
    assert len(calls) == 2 and cache.hits == 1 and cache.misses == 2
    EngineCache().run("engine", {"x": 1}, build)
    assert len(calls) == 3
    assert report()["search"]["cache"]["hits"] > 0


@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing_stair", "INCOMPLETE"),
        ("stale", "INVALID_INPUT"),
        ("budget", "SEARCH_EXHAUSTED"),
        ("operation", "UNSUPPORTED"),
        ("permission", "INVALID_INPUT"),
        ("duplicate", "INVALID_INPUT"),
        ("unknown_fixed", "INVALID_INPUT"),
        ("open_inventory", "INCOMPLETE"),
        ("fixed_inventory", "INCOMPLETE"),
        ("plan_cut", "INCOMPLETE"),
    ],
)
def test_readiness_and_search_status_semantics(change, expected):
    s = spec()
    if change == "missing_stair":
        s.pop("stair_specification")
    if change == "open_inventory":
        s["opening_specification"]["openings_complete"] = False
    if change == "fixed_inventory":
        s["opening_specification"]["fixed_obstacles_complete"] = False
    if change == "plan_cut":
        s["opening_specification"].pop("plan_cut_height")
    if change == "unknown_fixed":
        s["fixed_room_ids"] = ["MISSING-ROOM"]
    if change == "stale":
        s["requirements_digest"] = "0" * 64
    if change == "budget":
        s["search"]["max_steps"] = 1
    if change == "operation":
        s["refinements"] = [{"id": "X", "fixed": False, "type": "unrestricted_optimization"}]
    if change == "permission":
        s["refinements"][0]["offsets"] = [100]
    if change == "duplicate":
        s["clear_requirements"].append(deepcopy(s["clear_requirements"][0]))
    r = integrated_design(s)
    assert r["integrated_status"] == expected, r
    assert not r["cad_writes_permitted"]
    if change in {"open_inventory", "fixed_inventory", "plan_cut"}:
        assert r["search"]["evaluations"] == 0 and r["missing_information"]


def test_proven_infeasibility_has_original_numerical_contradiction():
    s = spec()
    b = s["generation"]["geometry"]["zoning"]["brief"]
    for room in b["building"]["rooms"]:
        room["area"] = {"min": 40, "max": 40, "unit": "m2"}
    approve_source(s["generation"])
    s["requirements_digest"] = canonical_digest(b)
    r = integrated_design(s)
    assert r["integrated_status"] == "INFEASIBLE"
    assert r["sources"]["generation_validation"]["errors"]
    assert r["search"]["evaluations"] == 0


def test_oracle_a_allocation_pass_does_not_hide_clear_area_failure():
    source = area_oracle()
    original = deepcopy(source)
    r = integrated_design(source)
    assert source == original
    s = r["originals"][0]
    room = s["engines"]["walls"]["rooms"][0]
    assert room["allocation_area_m2"] == 20
    assert room["clear_area_m2"] == pytest.approx(16.56, abs=1e-12)
    assert room["wall_occupied_area_m2"] == pytest.approx(3.44, abs=1e-12)
    assert any(
        c["code"] == "CLEAR_AREA_M2_VIOLATION" and c["required"]["min"] == 18
        for c in s["conflicts"]
    )
    assert not r["candidates"] and r["integrated_status"] == "SEARCH_EXHAUSTED"


def test_oracle_b_partition_resolves_area_without_moving_fixed_exterior():
    r = integrated_design(partition_oracle())
    original = r["originals"][0]
    assert next(x for x in original["engines"]["walls"]["rooms"] if x["room_id"] == "BED:1")[
        "clear_area_m2"
    ] == pytest.approx(17.1, abs=1e-12)
    attempt = next(a for a in r["attempts"] if a["proposed"] == 5.5)
    assert attempt["accepted"] and not attempt["conflicts_introduced"]
    revised = next(
        x for x in r["evaluated_revisions"] if x["revision_id"] == attempt["proposed_revision_id"]
    )
    rooms = {x["room_id"]: x for x in revised["room_measurements"]}
    assert rooms["BED:1"]["clear_area_m2"] == pytest.approx(18.9, abs=1e-12)
    assert rooms["LIVING:1"]["clear_area_m2"] == pytest.approx(15.3, abs=1e-12)
    assert not any(c["code"] == "CLEAR_AREA_M2_VIOLATION" for c in revised["conflicts"])
    assert revised["revision_id"] != original["revision_id"]


def test_immutable_room_permission_cannot_be_overridden():
    s = partition_oracle()
    s["fixed_room_ids"] = ["BED:1"]
    r = integrated_design(s)
    assert r["integrated_status"] == "INVALID_INPUT" and not r["candidates"]


def test_no_permission_does_not_move_conflicting_opening():
    s = spec()
    s["refinements"][0]["fixed"] = True
    s["search"]["max_evaluations"] = 1
    r = integrated_design(s)
    assert not r["candidates"] and not r["attempts"]
    assert r["originals"][0]["opening_specification"]["openings"][0]["offset"] == 2


def test_contacts_cannot_exempt_stair_or_shaft_reservations():
    s = spec()
    s["search"]["max_evaluations"] = 1
    contact = s["wall_specification"]["reservation_wall_contacts"][0]
    contact["reservation_id"] = "SW-F1"
    contact["geometry"] = deepcopy(s["stair_specification"]["stairs"][0]["envelope"])
    r = integrated_design(s)
    assert not r["candidates"]
    assert any(
        e["code"] == "INVALID_INTENTIONAL_WALL_CONTACT"
        for e in r["originals"][0]["engines"]["walls"]["errors"]
    )


def test_new_hard_failure_rejects_an_otherwise_useful_partition_move():
    source = partition_oracle()
    next(r for r in source["clear_requirements"] if r["room_id"] == "LIVING:1")["area_m2"][
        "min"
    ] = 16
    result = integrated_design(source)
    move = next(a for a in result["attempts"] if a["proposed"] == 5.5)
    assert not move["accepted"] and move["conflicts_introduced"]
    assert any(
        c["code"] == "CLEAR_AREA_M2_VIOLATION" and c["entity_ids"] == ["LIVING:1"]
        for c in move["conflicts_after"]
    )
    assert not result["candidates"]


def test_equivalent_states_are_deduplicated_and_count_is_not_manufactured():
    source = spec()
    source["search"].update(candidate_count=2, max_evaluations=3)
    permission = source["refinements"][0]
    permission["passage_alternatives"].append(
        {
            "offset": 2,
            "passages": [
                p
                for p in source["opening_specification"]["passages"]
                if p["id"].startswith("ENTRANCE-")
            ],
            "clearance_regions": [
                p
                for p in source["opening_specification"]["clearance_regions"]
                if p["id"] == "CLEAR-ENTRANCE"
            ],
        }
    )
    result = integrated_design(source)
    assert result["search"]["duplicate_states_skipped"] > 0
    assert len(result["candidates"]) == 1 and result["search"]["requested_candidate_count"] == 2
    assert any(w["code"] == "FEWER_VERIFIED_CANDIDATES" for w in result["warnings"])


def test_generated_room_and_wall_geometry_respects_protected_stair_reservation():
    state = report()["candidates"][0]
    for row in state["candidate"]["geometry"]["polygons"]:
        if row["role"] != "room":
            continue
        reservation = next(
            p
            for p in state["candidate"]["geometry"]["polygons"]
            if p["id"] == "SW-" + row["floor_id"]
        )
        from shapely.geometry import Polygon

        assert Polygon(row["exterior"]).intersection(Polygon(reservation["exterior"])).area == 0
    stair = shape_set(spec()["stair_specification"]["stairs"][0]["envelope"])
    for floor in state["engines"]["walls"]["floors"]:
        assert shape_set(floor["wall_footprint"]).intersection(stair).area == 0


@pytest.mark.parametrize(
    "name,status",
    [("historical-4x20-loaded", "CONFLICT"), ("historical-8x15-separation", "UNSUPPORTED")],
)
def test_historical_integrated_replay_preserves_original_obstacles_and_unsupported_constraint(
    name, status
):
    source = json.loads(
        (ROOT / "examples/batch007b4" / (name + ".json")).read_text(encoding="utf-8")
    )
    original = deepcopy(source)
    result = integrated_design(source)
    assert source == original and result["integrated_status"] == status
    assert not result["candidates"] and not result["cad_writes_permitted"]
    if status == "CONFLICT":
        historical = json.loads(
            (ROOT / "examples/batch007b3/townhouse-benchmark.json").read_text(encoding="utf-8")
        )
        assert source["seed"] == historical["source"]["source"]["source"]
    else:
        assert any(
            e["code"] == "MANDATORY_SEPARATION_UNMODELED"
            for e in result["sources"]["generation_validation"]["errors"]
        )


def test_primary_six_room_residential_benchmark_matches_independent_reference():
    source = json.loads(
        (ROOT / "examples/batch007b4/residential-4x20-six-rooms.json").read_text(encoding="utf-8")
    )
    result = integrated_design(source)
    assert result["integrated_status"] == "REFINED", result["originals"][0]["conflicts"]
    candidate = result["candidates"][0]
    assert candidate["verification_coverage"]["all_required_verified"]
    assert candidate["verification_coverage"]["required_checks"] == 48
    assert candidate["hard_violations"] == candidate["required_unknown"] == 0
    assert len(candidate["engines"]["walls"]["rooms"]) == 6
    for room in candidate["engines"]["walls"]["rooms"]:
        assert room["clear_area_m2"] == pytest.approx(
            3.23 if room["room_id"].startswith("BATH") else 20.52, abs=1e-12
        )
    assert candidate["accounting"]["building_clear_room_union_m2"] == pytest.approx(
        88.54, abs=1e-12
    )
    assert all(
        v == "GEOMETRICALLY_TRAVERSABLE"
        for v in candidate["integrated_circulation"]["room_access"].values()
    )
    assert result["attempts"][0]["accepted"] and not result["attempts"][0]["conflicts_introduced"]


def test_invalid_loaded_geometry_cannot_crash_accounting_or_create_an_illustration():
    source = json.loads(
        (ROOT / "examples/batch007b4/historical-4x20-loaded.json").read_text(encoding="utf-8")
    )
    candidate = source["seed"]["replay"]["review"]["candidate"]
    room = next(p for p in candidate["geometry"]["polygons"] if p["role"] == "room")
    room["exterior"] = [[0, 0], [1, 1], [0, 1], [1, 0]]
    result = integrated_design(source)
    assert not result["candidates"]
    assert result["originals"][0]["accounting"]["accounting_status"] == "NO_VERIFIED_WALL_GEOMETRY"
    with pytest.raises(ValueError):
        integrated_svg(result)
