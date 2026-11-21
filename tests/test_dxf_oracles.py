"""Independent mathematical oracles A-F for Batch 007-D DXF export and read-back."""

from decimal import Decimal
import json
import math
from pathlib import Path

import ezdxf
import pytest

from vnai.drafting_engine import generate_drafting
from vnai.drafting_styles import DEFAULT_LAYERS
from vnai.dxf_export import export_drafting_dxf
from vnai.dxf_manifest import INSUNITS_TO_UNIT

ROOT = Path(__file__).resolve().parents[1]
EX7C = ROOT / "examples" / "batch007c"
EX7D = ROOT / "examples" / "batch007d"


def _shoelace_area_m2(pts: list[tuple[float, float]] | list[list[float]], unit: str = "mm") -> float:
    terms = []
    n = len(pts)
    for i in range(n):
        x1, y1 = float(pts[i][0]), float(pts[i][1])
        x2, y2 = float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])
        terms.append(x1 * y2 - x2 * y1)
    area_u2 = abs(math.fsum(terms)) / 2.0
    return area_u2 / 1_000_000.0 if unit == "mm" else area_u2


def _export_fixture(fixture_path: Path, out_dxf: Path, *, scale: int | None = None, **kwargs):
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    ir = generate_drafting(raw, scale_override=scale)
    manifest = export_drafting_dxf(ir, out_dxf, **kwargs)
    return ir, manifest, ezdxf.readfile(out_dxf)


def test_oracle_a_rectangle_dimensions_and_areas_survive_dxf(tmp_path):
    """Oracle A: 4000x5000 mm building (20.0 m2 outer, 16.56 m2 clear, 3.44 m2 inward walls)."""
    dxf_path = tmp_path / "oracle_a.dxf"
    _, manifest, doc = _export_fixture(EX7C / "oracle-exterior-clear.json", dxf_path)
    assert manifest["export_status"] == "EXPORTED"
    assert INSUNITS_TO_UNIT[doc.header["$INSUNITS"]] == "mm"

    msp = doc.modelspace()
    # Building footprint LWPOLYLINE on A-GRID
    grid_polys = [list(e.get_points("xy")) for e in msp.query('LWPOLYLINE[layer=="A-GRID"]')]
    areas = sorted(_shoelace_area_m2(pts, "mm") for pts in grid_polys)
    assert pytest.approx(20.0, abs=1e-9) in areas

    # Exterior wall boundary (outer 20.0 m2 minus inner 16.56 m2 hole = 3.44 m2)
    wall_polys = [list(e.get_points("xy")) for e in msp.query('LWPOLYLINE[layer=="A-WALL-EXT"]')]
    assert len(wall_polys) == 2
    wall_areas = sorted(_shoelace_area_m2(pts, "mm") for pts in wall_polys)
    assert wall_areas[0] == pytest.approx(16.56, abs=1e-9)
    assert wall_areas[1] == pytest.approx(20.0, abs=1e-9)
    assert (wall_areas[1] - wall_areas[0]) == pytest.approx(3.44, abs=1e-9)


def test_oracle_b_native_dimensions_and_scale_invariance(tmp_path):
    """Oracle B: native DXF DIMENSION 0..4000 mm stays 4000 mm across 1:50 and 1:100."""
    _, m100, doc100 = _export_fixture(
        EX7C / "oracle-exterior-clear.json", tmp_path / "ora_b_100.dxf", scale=100
    )
    _, m50, doc50 = _export_fixture(
        EX7C / "oracle-exterior-clear.json", tmp_path / "ora_b_50.dxf", scale=50
    )

    for doc, dimstyle_name, exp_dimtxt in (
        (doc100, "VNAI_DIM_100", 200.0),
        (doc50, "VNAI_DIM_50", 100.0),
    ):
        assert dimstyle_name in doc.dimstyles
        assert doc.dimstyles.get(dimstyle_name).dxf.dimtxt == pytest.approx(exp_dimtxt, abs=1e-9)
        dims = list(doc.modelspace().query("DIMENSION"))
        assert len(dims) == 17
        assert all(d.dxf.geometry in doc.blocks for d in dims)
        horiz_4000 = [
            d
            for d in dims
            if abs(float(d.dxf.angle) - 0.0) < 1e-6 and abs(d.get_measurement() - 4000.0) < 1e-6
        ]
        assert len(horiz_4000) == 2
        for d in horiz_4000:
            xs = sorted([d.dxf.defpoint2.x, d.dxf.defpoint3.x])
            assert xs == [pytest.approx(0.0, abs=1e-9), pytest.approx(4000.0, abs=1e-9)]
            assert d.dxf.actual_measurement == pytest.approx(4000.0, abs=1e-9)

    assert m100["scale_metadata"]["scale_denominator"] == 100.0
    assert m50["scale_metadata"]["scale_denominator"] == 50.0


def test_oracle_c_analytic_arcs_preserve_center_radius_and_angles(tmp_path):
    """Oracle C: analytic ARC entities preserve center, radius, angles, and endpoints."""
    ir, manifest, doc = _export_fixture(EX7C / "opening-annotation.json", tmp_path / "oracle_c.dxf")
    assert manifest["export_status"] == "EXPORTED"
    ir_arcs = [e for e in ir["model_space"]["views"][0]["entities"] if e["entity_type"] == "ARC"]
    dxf_arcs = list(doc.modelspace().query("ARC"))
    assert len(ir_arcs) == len(dxf_arcs) == 1

    src = ir_arcs[0]["coordinates"]
    arc = dxf_arcs[0]
    assert arc.dxf.layer == "A-DOOR-SWING"
    assert [arc.dxf.center.x, arc.dxf.center.y] == pytest.approx(src["center"], abs=1e-9)
    assert arc.dxf.radius == pytest.approx(src["radius"], abs=1e-9)
    assert arc.dxf.radius == pytest.approx(780.0, abs=1e-9)
    assert arc.dxf.start_angle % 360.0 == pytest.approx(0.0, abs=1e-6)
    assert arc.dxf.end_angle % 360.0 == pytest.approx(90.0, abs=1e-6)
    assert [arc.start_point.x, arc.start_point.y] == pytest.approx([2340.0, 200.0], abs=1e-6)
    assert [arc.end_point.x, arc.end_point.y] == pytest.approx([1560.0, 980.0], abs=1e-6)


def test_oracle_d_wall_opening_remaining_area_is_exact_0_62_m2(tmp_path):
    """Oracle D: 4000x200 mm wall with 900 mm rough door -> 0.62 m2 remaining wall area."""
    _, manifest, doc = _export_fixture(EX7D / "oracle-d-wall-opening.json", tmp_path / "oracle_d.dxf")
    assert manifest["export_status"] == "EXPORTED"
    msp = doc.modelspace()
    wall_polys = list(msp.query('LWPOLYLINE[layer=="A-WALL-EXT"]'))
    assert len(wall_polys) == 2
    remaining_m2 = math.fsum(_shoelace_area_m2(list(w.get_points("xy")), "mm") for w in wall_polys)
    assert Decimal(str(round(remaining_m2, 12))) == Decimal("0.62")


def test_oracle_e_vietnamese_unicode_codepoints_preserved(tmp_path):
    """Oracle E: All six Vietnamese labels survive export/read-back cleanly with font status unverified."""
    expected_labels = [
        "Phòng khách",
        "Phòng ngủ",
        "Bếp + Ăn",
        "Vệ sinh",
        "Cầu thang",
        "Phòng thờ",
    ]
    _, manifest, doc = _export_fixture(
        EX7D / "oracle-e-vietnamese-unicode.json", tmp_path / "oracle_e.dxf"
    )
    assert manifest["export_status"] == "EXPORTED"
    uv = manifest["unicode_text_verification"]
    assert uv["all_codepoints_match"] is True
    assert uv["font_rendering_status"] == "UNVERIFIED_EXTERNAL_WORKSTATION_FONT"

    msp = doc.modelspace()
    all_texts = [t.dxf.text for t in msp.query("TEXT")] + [
        mt.plain_text() for mt in msp.query("MTEXT")
    ]
    joined = "\n".join(all_texts)
    for label in expected_labels:
        assert label in joined
        # Explicit Unicode code-point comparison against recovered lines
        assert any(
            [ord(ch) for ch in line] == [ord(ch) for ch in label]
            for block in all_texts
            for line in block.split("\n")
        )


def test_oracle_f_layer_and_style_identity_preserved(tmp_path):
    """Oracle F: All 15 CAD layers preserve color, linetype, lineweight, plot, visibility, and style."""
    _, manifest, doc = _export_fixture(EX7C / "oracle-exterior-clear.json", tmp_path / "oracle_f.dxf")
    assert manifest["export_status"] == "EXPORTED"
    for row in DEFAULT_LAYERS:
        lname = row["name"]
        assert lname in doc.layers
        lay = doc.layers.get(lname)
        assert lay.color == row["aci_color"]
        assert lay.dxf.linetype.upper() == row["linetype"].upper()
        assert lay.dxf.lineweight == int(round(row["lineweight_mm"] * 100))
        assert bool(lay.dxf.plot) is bool(row["plottable"])
        assert lay.is_on() is bool(row["visible"])
    assert "VNAI_VN_UNICODE" in doc.styles
    assert all(
        e.dxf.layer in {r["name"] for r in DEFAULT_LAYERS} for e in doc.modelspace()
    )
