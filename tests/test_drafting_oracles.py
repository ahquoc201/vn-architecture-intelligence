"""Independent mathematical oracles for Batch 007-C drafting and dimension engine."""

from decimal import Decimal
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from vnai.drafting_dimensions import build_dimension_chain, verify_dimension_chain_closure
from vnai.drafting_engine import generate_drafting
from vnai.drafting_preview import drafting_svg

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "batch007c"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_oracle_a_exterior_vs_clear_dimensions():
    """4000x5000 mm exterior with 200 mm inward walls -> 3600x4600 mm clear, 16.56 m2."""
    report = generate_drafting(_load("oracle-exterior-clear.json"))
    assert report["drafting_status"] == "GENERATED"
    assert report["collisions"] == []

    by_basis = {}
    for d in report["dimensions"]:
        by_basis.setdefault(d["measurement_basis"], []).append(d)

    overall_x = [
        d for d in by_basis["dimension_chain_overall"] if d["dimension_type"] == "linear_horizontal"
    ]
    overall_y = [
        d for d in by_basis["dimension_chain_overall"] if d["dimension_type"] == "linear_vertical"
    ]
    assert overall_x and all(d["measured_value"] == pytest.approx(4000.0, abs=1e-9) for d in overall_x)
    assert overall_y and all(d["measured_value"] == pytest.approx(5000.0, abs=1e-9) for d in overall_y)

    clear_dims = by_basis["clear_room_interior"]
    clear_w = next(d for d in clear_dims if d["dimension_type"] == "linear_horizontal")
    clear_l = next(d for d in clear_dims if d["dimension_type"] == "linear_vertical")
    assert clear_w["measured_value"] == pytest.approx(3600.0, abs=1e-9)
    assert clear_w["display_text"] == "3600"
    assert clear_l["measured_value"] == pytest.approx(4600.0, abs=1e-9)
    assert clear_l["display_text"] == "4600"

    wall_t = by_basis["wall_thickness_actual"]
    assert len(wall_t) == 1 and wall_t[0]["measured_value"] == pytest.approx(200.0, abs=1e-9)

    room_ann = report["annotations"]["rooms"][0]
    assert room_ann["clear_area_m2"] == pytest.approx(16.56, abs=1e-10)
    assert room_ann["allocation_area_m2"] == pytest.approx(20.0, abs=1e-10)
    assert room_ann["area_basis"] == "clear_room_interior"


def test_oracle_b_dimension_chain_exact_and_rounding_discrepancy():
    """0, 1200, 2800, 4000 mm -> segments 1200, 1600, 1200 mm, overall 4000 mm."""
    report = generate_drafting(_load("oracle-dimension-chain.json"))
    assert report["drafting_status"] == "GENERATED"
    chain = next(c for c in report["dimension_chains"] if c["chain_id"] == "CHAIN-F1-X-SOUTH")
    assert chain["reference_coordinates"] == [0.0, 1200.0, 2800.0, 4000.0]
    dim_map = {d["id"]: d for d in report["dimensions"]}
    seg_vals = [dim_map[sid]["measured_value"] for sid in chain["segment_dimension_ids"]]
    assert seg_vals == [1200.0, 1600.0, 1200.0]
    assert dim_map[chain["overall_dimension_id"]]["measured_value"] == 4000.0
    assert chain["exact_segments_sum"] == 4000.0
    assert chain["geometric_closure_error"] == 0.0
    assert chain["geometric_closed"] is True
    assert chain["display_closed"] is True
    assert chain["closure_status"] == "GEOMETRIC_CLOSED_EXACT"

    # Independent rounding discrepancy oracle: 3 * (1000/3) = 1000 exact, 333+333+333 = 999 displayed
    dims_round, ch_round = build_dimension_chain(
        axis="x",
        stations=[
            (Decimal("0"), 0.0, ["A"], "grid"),
            (Decimal("1") / Decimal("3"), 0.0, ["B"], "grid"),
            (Decimal("2") / Decimal("3"), 0.0, ["C"], "grid"),
            (Decimal("1"), 0.0, ["D"], "grid"),
        ],
        line_coord=-500.0,
        overall_line_coord=-1000.0,
        side="bottom",
        ext_offset=100.0,
        ext_overshoot=100.0,
        source_units="m",
        drawing_units="mm",
        precision=0,
        source_geometry_digest="a" * 64,
        view_id="PLAN-F1",
        floor_id="F1",
        chain_id="ROUND-ORACLE",
        dim_text_height=200.0,
    )
    assert ch_round["geometric_closed"] is True
    assert ch_round["geometric_closure_error"] == 0.0
    assert ch_round["displayed_segments_sum"] == 999.0
    assert ch_round["displayed_overall"] == 1000.0
    assert ch_round["display_rounding_discrepancy"] == -1.0
    assert ch_round["display_closed"] is False
    assert ch_round["closure_status"] == "GEOMETRIC_CLOSED_DISPLAY_ROUNDING_DISCREPANCY"
    # Never silently alter a segment label to force displayed closure.
    assert [d["display_text"] for d in dims_round[:-1]] == ["333", "333", "333"]

    # Independent geometric closure mismatch oracle
    mismatch = verify_dimension_chain_closure(
        [Decimal("1200"), Decimal("1600"), Decimal("1150")], Decimal("4000"), 0, "mm"
    )
    assert mismatch["geometric_closed"] is False
    assert mismatch["geometric_closure_error"] == -50.0
    assert mismatch["closure_status"] == "GEOMETRIC_CLOSURE_MISMATCH"


def test_oracle_c_scale_independence_1_to_50_vs_1_to_100():
    """Changing paper scale from 1:50 to 1:100 must not alter real-world 4000 mm dimensions."""
    spec = _load("oracle-exterior-clear.json")
    r50 = generate_drafting(spec, scale_override=50)
    r100 = generate_drafting(spec, scale_override=100)

    assert r50["paper_space"]["scale_label"] == "1:50"
    assert r100["paper_space"]["scale_label"] == "1:100"
    assert r50["geometry_and_dimensions_digest"] == r100["geometry_and_dimensions_digest"]
    assert r50["presentation_digest"] != r100["presentation_digest"]

    d50 = next(
        d
        for d in r50["dimensions"]
        if d["measurement_basis"] == "dimension_chain_overall"
        and d["dimension_type"] == "linear_horizontal"
    )
    d100 = next(
        d
        for d in r100["dimensions"]
        if d["measurement_basis"] == "dimension_chain_overall"
        and d["dimension_type"] == "linear_horizontal"
    )
    assert d50["measured_value"] == d100["measured_value"] == 4000.0
    assert d50["display_text"] == d100["display_text"] == "4000"
    assert r50["style"]["model_sizing"]["text_height"] == pytest.approx(120.0)
    assert r100["style"]["model_sizing"]["text_height"] == pytest.approx(240.0)

    svg50 = drafting_svg(r50, floor="F1")
    svg100 = drafting_svg(r100, floor="F1")
    ns = "{http://www.w3.org/2000/svg}"
    meta50 = json.loads(ET.fromstring(svg50).find(f"{ns}metadata").text)
    meta100 = json.loads(ET.fromstring(svg100).find(f"{ns}metadata").text)
    assert meta50["px_per_paper_mm"] == meta100["px_per_paper_mm"]
    assert meta50["px_per_model_unit"] == pytest.approx(2.0 * meta100["px_per_model_unit"])


def test_oracle_d_stair_annotations_straight_and_townhouse():
    """Stair annotations must match verified B3 straight and B4 U-stair geometry exactly."""
    straight_rep = generate_drafting(_load("oracle-stair-section.json"))
    assert straight_rep["drafting_status"] == "GENERATED"
    ann_s = straight_rep["annotations"]["stairs"][0]
    assert ann_s["section_kind"] == "TRUE_LONGITUDINAL"
    assert ann_s["risers"] == 20
    assert ann_s["riser_height"] == pytest.approx(165.0)
    assert ann_s["tread_depth"] == pytest.approx(250.0)
    assert ann_s["source_elevation_m"] == 0.0
    assert ann_s["destination_elevation_m"] == 3.3

    by_basis = {
        d["measurement_basis"]: d["measured_value"]
        for d in straight_rep["dimensions"]
        if d["view_id"] == "SECT-S1"
    }
    assert by_basis["floor_to_floor_height"] == pytest.approx(3300.0)
    assert by_basis["stair_riser_height"] == pytest.approx(165.0)
    assert by_basis["stair_tread_depth"] == pytest.approx(250.0)

    # Townhouse U-stair oracle
    th_rep = generate_drafting(_load("townhouse-6rooms-drafting.json"))
    assert th_rep["drafting_status"] == "GENERATED"
    sect_ann = next(s for s in th_rep["annotations"]["stairs"] if "section_kind" in s)
    assert sect_ann["section_kind"] == "DEVELOPED_EXPLICIT_WALKING_LINE"
    assert sect_ann["risers"] == 20
    assert sect_ann["riser_height"] == pytest.approx(165.0)
    assert sect_ann["tread_depth"] == pytest.approx(240.0)

    th_sect_dims = {}
    for d in th_rep["dimensions"]:
        if d["view_id"] == "SECT-S1":
            th_sect_dims[d["measurement_basis"]] = d["measured_value"]
    assert th_sect_dims["floor_to_floor_height"] == pytest.approx(3300.0)
    assert th_sect_dims["stair_landing_elevation"] == pytest.approx(1650.0)
    assert th_sect_dims["stair_verified_local_headroom"] == pytest.approx(3165.0)

    f1_dims = {}
    f2_dims = {}
    for d in th_rep["dimensions"]:
        if d["view_id"] == "PLAN-F1":
            f1_dims.setdefault(d["measurement_basis"], []).append(d["measured_value"])
        elif d["view_id"] == "PLAN-F2":
            f2_dims.setdefault(d["measurement_basis"], []).append(d["measured_value"])
    assert all(v == pytest.approx(800.0) for v in f1_dims["stair_flight_width"])
    assert all(v == pytest.approx(2160.0) for v in f1_dims["stair_flight_run"])
    assert f1_dims["stair_landing_width"][0] == pytest.approx(590.0)
    assert f1_dims["stair_landing_depth"][0] == pytest.approx(1800.0)
    assert f2_dims["floor_opening_width"][0] == pytest.approx(2750.0)
    assert f2_dims["floor_opening_length"][0] == pytest.approx(3300.0)
