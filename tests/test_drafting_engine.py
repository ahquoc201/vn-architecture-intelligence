"""Focused tests for CAD-neutral IR, Vietnamese annotations, layers, symbols, collisions and B4 benchmark."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from vnai.drafting_engine import extract_layers_report, generate_drafting, validate_drafting
from vnai.drafting_preview import drafting_markdown, drafting_svg
from vnai.drafting_styles import build_layer_policy, convert_length, validate_layer_policy
from vnai.integrated_design import integrated_design
from vnai.review_common import candidate_digest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "batch007c"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _townhouse_drafting() -> dict:
    return generate_drafting(_load("townhouse-6rooms-drafting.json"))


def test_unit_conversion_and_double_conversion_guard():
    assert str(convert_length(4, "m", "mm")) == "4000"
    assert str(convert_length(4000, "mm", "m")) == "4"
    spec = _load("oracle-exterior-clear.json")
    rep_mm = generate_drafting(spec, units_override="mm")
    rep_m = generate_drafting(spec, units_override="m")
    assert rep_mm["unit_policy"]["unit_conversion_applied"] is True
    assert rep_m["unit_policy"]["unit_conversion_applied"] is False
    assert rep_mm["unit_policy"]["double_conversion_guard"] == "EXPLICIT_SOURCE_TO_DRAWING_ONCE"
    d_mm = next(d for d in rep_mm["dimensions"] if d["measurement_basis"] == "clear_room_interior")
    d_m = next(d for d in rep_m["dimensions"] if d["measurement_basis"] == "clear_room_interior")
    assert d_mm["measured_value"] == pytest.approx(d_m["measured_value"] * 1000.0)


def test_irregular_room_refusal_nonconvex_interior_point_and_vietnamese_diacritics():
    spec = _load("room-annotation-vn.json")
    rep = generate_drafting(spec)
    assert rep["drafting_status"] == "GENERATED"
    assert any(
        u["code"] == "AMBIGUOUS_IRREGULAR_ROOM_SPAN" and u["entity_id"] == "BED:1"
        for u in rep["unsupported_dimensions"]
    )
    room_ann = rep["annotations"]["rooms"][0]
    assert room_ann["display_name"] == "Hành lang chữ L"
    assert room_ann["centroid_inside_clear"] is False
    assert room_ann["interior_point_verified_inside"] is True
    md = drafting_markdown(rep)
    svg = drafting_svg(rep, floor="F1")
    assert "Hành lang chữ L" in md
    assert "Hành lang chữ L" in svg


def test_opening_annotations_analytic_arc_and_conflicting_mark_detection():
    spec = _load("opening-annotation.json")
    rep = generate_drafting(spec)
    assert rep["drafting_status"] == "GENERATED"
    arcs = [
        e
        for v in rep["model_space"]["views"]
        for e in v["entities"]
        if e["entity_type"] == "ARC"
    ]
    assert arcs, "Expected analytic ARC primitive for hinged door swing."
    assert all(a["metadata"]["analytic"] is True and a["coordinates"]["radius"] > 0 for a in arcs)
    door_ann = next(o for o in rep["annotations"]["openings"] if o["opening_id"] == "DOOR-1")
    assert door_ann["rough_width"] != door_ann["leaf_width"]
    assert door_ann["leaf_width"] != door_ann["clear_width"]
    assert door_ann["schedule_specification_digest"] is not None

    # Conflicting repeated opening marks must fail validation
    bad = deepcopy(spec)
    openings = bad["source"]["payload"]["specification"]["openings"]
    dup = deepcopy(openings[0])
    dup["id"] = "DOOR-DUP"
    dup["offset"] = 2.6
    dup["rough_width"] = 0.85
    dup["leaf"]["width"] = 0.75
    dup["clear_width"] = 0.69
    openings.append(dup)
    bad_rep = generate_drafting(bad)
    assert bad_rep["drafting_status"] == "CONFLICT"
    assert any(e["code"] == "CONFLICTING_OPENING_MARK" for e in bad_rep["errors"])


def test_reference_symbols_north_grid_sections_and_no_fabricated_elevations():
    # Unconfirmed / missing north orientation -> unresolved, no fabricated arrow
    spec_no_north = _load("oracle-exterior-clear.json")
    spec_no_north["orientation_override"] = {
        "north_degrees": 0,
        "confirmation": "missing",
        "provenance": "synthetic unconfirmed north test",
    }
    rep_no_north = generate_drafting(spec_no_north)
    assert rep_no_north["reference_symbols"]["north_arrow"]["status"] == "UNRESOLVED"
    assert not any(
        e["entity_type"] == "BLOCK_REFERENCE"
        and e.get("metadata", {}).get("block_name") == "SYM_NORTH_ARROW"
        for v in rep_no_north["model_space"]["views"]
        for e in v["entities"]
    )
    assert any(u["code"] == "FLOOR_ELEVATION_UNRESOLVED" for u in rep_no_north["unresolved_items"])

    # Also test completely missing north_degrees in a stored wall report brief
    from vnai.walls import generate_walls

    wrep = generate_walls(deepcopy(spec_no_north["source"]["payload"]))
    wrep["sources"]["input"]["source"]["replay"]["review"]["candidate"]["geometry"]["zoning"]["brief"]["site"].pop("north_degrees", None)
    rep_missing_north = generate_drafting(wrep)
    assert rep_missing_north["reference_symbols"]["north_arrow"]["status"] == "UNRESOLVED"
    assert any(u["code"] == "NORTH_ORIENTATION_UNRESOLVED" for u in rep_missing_north["unresolved_items"])

    req_north = deepcopy(spec_no_north)
    req_north["annotation_options"]["require_north_arrow"] = True
    rep_inc = generate_drafting(req_north)
    assert rep_inc["drafting_status"] == "INCOMPLETE"

    # Unprovenanced structural grid downgrades safely; unmapped section marker stays PROPOSED
    grid_spec = deepcopy(spec_no_north)
    grid_spec["reference_grid"] = {
        "grid_role": "supplied_structural_column_grid",
        "x_axes": [{"label": "1", "coord_source_units": 0}],
        "y_axes": [{"label": "A", "coord_source_units": 0}],
    }
    grid_spec["section_markers"] = [
        {
            "id": "SM-PROP",
            "label": "X",
            "floor_id": "F1",
            "start": [0.5, 2.5],
            "end": [3.5, 2.5],
            "look_direction": [0, 1],
            "referenced_view_id": "NON_EXISTENT_SECT",
        }
    ]
    rep_grid = generate_drafting(grid_spec)
    assert rep_grid["reference_symbols"]["reference_grid"]["grid_role"] == "architectural_reference_grid"
    assert rep_grid["reference_symbols"]["section_markers"][0]["status"] == "PROPOSED_SECTION_MARKER"


def test_layer_policy_validation_custom_overrides_and_ezdxf_mapping():
    policy = build_layer_policy()
    assert len(policy["layers"]) == 15
    assert validate_layer_policy(policy) == []
    assert all("ezdxf_mapping" in row and row["ezdxf_mapping"]["name"] == row["name"] for row in policy["layers"])

    # Invalid layer override rejected
    spec = _load("oracle-exterior-clear.json")
    spec["layer_policy_overrides"] = [{"name": "BAD/LAYER*NAME", "aci_color": 7}]
    bad = generate_drafting(spec)
    assert bad["drafting_status"] == "INVALID_INPUT"
    assert any(e["code"] == "INVALID_LAYER_POLICY" for e in bad["errors"])

    layers_rep = extract_layers_report(_load("oracle-exterior-clear.json"))
    assert layers_rep["cad_writes_permitted"] is False
    assert layers_rep["total_entities"] > 0
    assert any(r["name"] == "A-WALL-EXT" and r["entity_count"] > 0 for r in layers_rep["layers"])


def test_collision_detection_reports_exact_and_approximate_without_moving_walls():
    col_spec = _load("collision-example.json")
    col_rep = generate_drafting(col_spec)
    assert col_rep["drafting_status"] == "CONFLICT"
    assert len(col_rep["collisions"]) > 0
    kinds = {c["collision_kind"] for c in col_rep["collisions"]}
    assert "EXACT_GEOMETRIC" in kinds
    assert all(c["status"] == "UNRESOLVED" for c in col_rep["collisions"])
    review_markers = [
        e
        for v in col_rep["model_space"]["views"]
        for e in v["entities"]
        if e["layer"] == "A-REVIEW" and e.get("metadata", {}).get("role") == "unresolved_collision_marker"
    ]
    assert len(review_markers) == len(col_rep["collisions"])

    # Bounded placement enabled resolves solvable overlaps without altering wall geometry
    fixed_spec = deepcopy(col_spec)
    fixed_spec["placement_options"] = {"allow_reposition": True, "allow_leader_callout": True, "max_attempts": 12}
    fixed_spec["paper_space"]["scale_denominator"] = 100
    fixed_spec["annotation_options"]["show_wall_thickness_dims"] = False
    fixed_rep = generate_drafting(fixed_spec)
    assert fixed_rep["collisions"] == []
    walls_before = [
        e["coordinates"]
        for v in col_rep["model_space"]["views"]
        for e in v["entities"]
        if e["layer"] in {"A-WALL-EXT", "A-WALL-INT"}
    ]
    walls_after = [
        e["coordinates"]
        for v in fixed_rep["model_space"]["views"]
        for e in v["entities"]
        if e["layer"] in {"A-WALL-EXT", "A-WALL-INT"}
    ]
    assert walls_before == walls_after


def test_input_immutability_and_deterministic_digests():
    raw_bytes = (EXAMPLES / "oracle-exterior-clear.json").read_bytes()
    payload = json.loads(raw_bytes)
    snap = deepcopy(payload)
    r1 = generate_drafting(payload)
    r2 = generate_drafting(payload)
    assert payload == snap
    assert raw_bytes == (EXAMPLES / "oracle-exterior-clear.json").read_bytes()
    assert r1["drawing_ir_digest"] == r2["drawing_ir_digest"]
    assert r1["model_space_digest"] == r2["model_space_digest"]
    assert validate_drafting(r1)["drawing_ir_digest"] == r1["drawing_ir_digest"]


def test_integrated_townhouse_benchmark_preserves_48_checks_and_geometry():
    th_input = _load("townhouse-6rooms-drafting.json")
    b4_raw = json.loads((ROOT / "examples/batch007b4/residential-4x20-six-rooms.json").read_text(encoding="utf-8"))
    assert th_input["source"]["payload"] == b4_raw

    b4_report = integrated_design(deepcopy(b4_raw), refine=True)
    b4_cand = b4_report["candidates"][0]
    assert b4_cand["verification_coverage"]["verified"] == 48
    assert b4_cand["verification_coverage"]["all_required_verified"] is True

    draft = _townhouse_drafting()
    assert draft["drafting_status"] == "GENERATED"
    assert draft["collisions"] == []
    assert draft["cad_writes_permitted"] is False
    assert draft["approval_inherited"] is False
    assert draft["architect_approval"] == "NOT_GRANTED"
    assert draft["standards_review"] == "NOT_EVALUATED"
    assert draft["fengshui_review"] == "NOT_EVALUATED"
    assert draft["construction_readiness"] == "NOT_FOR_CONSTRUCTION_CONCEPTUAL_ONLY"

    assert draft["source_digests"]["source_revision_id"] == b4_cand["revision_id"]
    assert draft["source_digests"]["source_candidate_digest"] == candidate_digest(b4_cand["candidate"])
    assert draft["source_digests"]["wall_revision_id"] == b4_cand["engines"]["walls"]["wall_revision_id"]
    assert draft["source_digests"]["opening_revision_id"] == b4_cand["engines"]["openings"]["opening_revision_id"]
    assert draft["source_digests"]["stair_revision_id"] == b4_cand["engines"]["stairs"]["stair_revision_id"]
    assert draft["source_digests"]["verification_coverage"]["verified"] == 48

    # Confirm all 6 Vietnamese room labels, exact clear areas, north arrow, section marker, and SVG
    room_map = {r["room_id"]: r for r in draft["annotations"]["rooms"]}
    assert set(room_map) == {"LIVING:1", "KITCHEN:1", "BATH-G:1", "BED:1", "BED:2", "BATH-U:1"}
    assert room_map["LIVING:1"]["display_name"] == "Phòng khách"
    assert room_map["KITCHEN:1"]["display_name"] == "Bếp - Ăn"
    assert room_map["BATH-G:1"]["clear_area_m2"] == pytest.approx(3.23, abs=1e-10)
    assert room_map["LIVING:1"]["clear_area_m2"] == pytest.approx(20.52, abs=1e-10)
    assert draft["reference_symbols"]["north_arrow"]["status"] == "CONFIRMED"
    assert draft["reference_symbols"]["section_markers"][0]["status"] == "DEFINED_SECTION_VIEW"

    # Re-run B4 after drafting to confirm unchanged source specification yields identical 48/48 results
    b4_after = integrated_design(b4_raw, refine=True)
    assert b4_after["candidates"][0]["revision_id"] == b4_cand["revision_id"]
    assert b4_after["candidates"][0]["verification_coverage"]["verified"] == 48

    svg_sheet = drafting_svg(draft, view="sheet")
    root_el = ET.fromstring(svg_sheet)
    assert root_el.attrib["preserveAspectRatio"] == "xMidYMid meet"
    assert "Phòng khách" in svg_sheet
    assert "Bếp - Ăn" in svg_sheet
