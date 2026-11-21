"""Comprehensive Batch 007-D tests covering all 25 required export, audit, negative & legacy cases."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

import ezdxf
import pytest

from vnai.drafting_engine import generate_drafting
from vnai.dxf_adapter import export_schematic_dxf
from vnai.dxf_export import export_drafting_dxf
from vnai.dxf_manifest import compute_file_sha256, extract_manifest_from_dxf
from vnai.dxf_roundtrip import audit_dxf_file, verify_dxf_roundtrip

ROOT = Path(__file__).resolve().parents[1]
EX7C = ROOT / "examples" / "batch007c"


@lru_cache(maxsize=8)
def _cached_ir(name: str) -> dict:
    return generate_drafting(json.loads((EX7C / name).read_text(encoding="utf-8")))


def _townhouse_ir() -> dict:
    return deepcopy(_cached_ir("townhouse-6rooms-drafting.json"))


def _oracle_a_ir() -> dict:
    return deepcopy(_cached_ir("oracle-exterior-clear.json"))


def test_primitives_lines_polylines_holes_circles_arcs_blocks_hatch(tmp_path):
    """Covers LINE, POLYLINE(+holes), CIRCLE, analytic ARC, BLOCK_REFERENCE(+ATTRIB), valid HATCH."""
    # collision-example contains wall_ext hatch with an interior hole ring
    col_ir = deepcopy(_cached_ir("collision-example.json"))
    m_hole = export_drafting_dxf(col_ir, tmp_path / "holes.dxf")
    assert m_hole["export_status"] == "EXPORTED"
    assert m_hole["roundtrip_verification"]["equivalence_status"] == "LOSSLESS_EQUIVALENT"
    assert m_hole["entity_count_by_type"]["HATCH"] == 2
    assert m_hole["entity_count_by_type"]["LWPOLYLINE"] >= 2

    # opening-annotation + oracle-dimension-chain cover LINE, analytic ARC, CIRCLE, DIMENSION, BLOCK_REFERENCE
    op_ir = deepcopy(_cached_ir("opening-annotation.json"))
    m_op = export_drafting_dxf(op_ir, tmp_path / "opening.dxf")
    assert m_op["export_status"] == "EXPORTED"
    assert m_op["entity_count_by_type"]["ARC"] == 1
    assert m_op["entity_count_by_type"]["INSERT"] >= 3  # TAG_DOOR, TAG_WINDOW, SYM_NORTH_ARROW, scale_bar

    ch_ir = deepcopy(_cached_ir("oracle-dimension-chain.json"))
    m_ch = export_drafting_dxf(ch_ir, tmp_path / "chain.dxf")
    assert m_ch["export_status"] == "EXPORTED"
    assert m_ch["entity_count_by_type"]["CIRCLE"] == 6
    assert m_ch["entity_count_by_type"]["LINE"] == 6
    assert m_ch["entity_count_by_type"]["TEXT"] == 6
    assert m_ch["entity_count_by_type"]["MTEXT"] == 1


def test_unit_conversion_mm_to_m_and_duplicate_conversion_prevention(tmp_path):
    """Verifies mm <-> m single conversion, $INSUNITS, dimdec=3, and conflicting units rejection."""
    ir = _oracle_a_ir()
    m_path = tmp_path / "meters.dxf"
    man = export_drafting_dxf(ir, m_path, target_units="m")
    assert man["export_status"] == "EXPORTED"
    assert man["unit_policy"]["unit_conversion_applied"] is True
    assert man["unit_policy"]["double_conversion_guard"] == "EXPLICIT_IR_TO_DXF_ONCE"
    assert man["unit_policy"]["insunits"] == 6
    assert man["roundtrip_verification"]["equivalence_status"] == "LOSSLESS_EQUIVALENT"

    doc = ezdxf.readfile(m_path)
    assert doc.header["$INSUNITS"] == 6
    horiz_4m = [d for d in doc.modelspace().query("DIMENSION") if abs(d.get_measurement() - 4.0) < 1e-6]
    assert len(horiz_4m) == 2

    # Unsupported target units rejected
    bad_u = export_drafting_dxf(ir, tmp_path / "inches.dxf", target_units="in")
    assert bad_u["export_status"] == "UNSUPPORTED"
    assert not (tmp_path / "inches.dxf").exists()

    # Conflicting IR unit declarations rejected without touching file
    bad_ir = deepcopy(ir)
    bad_ir["unit_policy"]["drawing_units"] = "m"  # while model_space.units is still "mm"
    conf = export_drafting_dxf(bad_ir, tmp_path / "conflict_u.dxf")
    assert conf["export_status"] == "INVALID_INPUT"
    assert not (tmp_path / "conflict_u.dxf").exists()


def test_paper_space_supplied_vs_missing_paper_size_and_no_model_duplication(tmp_path):
    """Explicit paper_size_mm generates Paper Space VIEWPORT; missing size when required returns INCOMPLETE."""
    ir = _oracle_a_ir()
    # require_paper_space=True with no paper_size_mm -> INCOMPLETE (never fabricate A3/A4)
    inc = export_drafting_dxf(
        ir,
        tmp_path / "no_ps.dxf",
        paper_space_layout={"enabled": True, "require_paper_space": True},
    )
    assert inc["export_status"] == "INCOMPLETE"
    assert inc["missing_information"][0]["code"] == "PAPER_SIZE_NOT_SUPPLIED"
    assert not (tmp_path / "no_ps.dxf").exists()

    # Explicit paper_size_mm -> Model Space stays 1:1, Paper Space gets exact 1:100 viewport
    ps_path = tmp_path / "with_ps.dxf"
    man = export_drafting_dxf(
        ir,
        ps_path,
        paper_space_layout={"enabled": True, "paper_size_mm": [420, 297], "title_block_supplied": True},
    )
    assert man["export_status"] == "EXPORTED"
    assert man["dxf_audit"]["audit_status"] == "CLEAN"
    assert man["paper_space_composition"]["status"] == "GENERATED_FROM_EXPLICIT_PAPER_SIZE"
    assert man["roundtrip_verification"]["equivalence_status"] == "LOSSLESS_EQUIVALENT"
    doc = ezdxf.readfile(ps_path)
    layout = doc.layouts.get("PLAN-F1")
    vps = [e for e in layout if e.dxftype() == "VIEWPORT" and e.dxf.id != 1]
    assert len(vps) == 1
    assert (vps[0].dxf.view_height / vps[0].dxf.height) == pytest.approx(100.0, abs=1e-4)
    # Model Space contains exact 1:1 building dimensions (not scaled copies)
    assert any(abs(d.get_measurement() - 4000.0) < 1e-6 for d in doc.modelspace().query("DIMENSION"))


def test_negative_invalid_hatch_unsupported_primitive_unmapped_layer_missing_digest(tmp_path):
    """Verify explicit rejection of invalid hatch, unsupported primitives, unmapped layers, and missing digests."""
    ir = _oracle_a_ir()

    # 1. Invalid self-intersecting bowtie hatch boundary -> CONFLICT, no file written, no silent repair
    bad_hatch = deepcopy(ir)
    hatch_ent = next(
        e for e in bad_hatch["model_space"]["views"][0]["entities"] if e["entity_type"] == "HATCH"
    )
    hatch_ent["coordinates"]["exterior"] = [[0.0, 0.0], [1000.0, 1000.0], [1000.0, 0.0], [0.0, 1000.0], [0.0, 0.0]]
    res_h = export_drafting_dxf(bad_hatch, tmp_path / "bad_hatch.dxf")
    assert res_h["export_status"] in {"CONFLICT", "INVALID_INPUT"}
    assert any(e["code"] in {"INVALID_HATCH_BOUNDARY", "STORED_DRAFTING_MISMATCH"} for e in res_h["errors"])
    assert not (tmp_path / "bad_hatch.dxf").exists()

    # Notice even if we inject a self-intersecting HATCH into a fresh un-tampered source? Check direct export bypass guard:
    # Our resolve_ir_and_view detects STORED_DRAFTING_MISMATCH OR INVALID_HATCH_BOUNDARY depending on source.input match;
    # let's test HATCH directly with source omitted (standalone IR whose HATCH itself is self-intersecting)!
    standalone_hatch = deepcopy(ir)
    standalone_hatch["sources"] = {}
    he = next(e for e in standalone_hatch["model_space"]["views"][0]["entities"] if e["entity_type"] == "HATCH")
    he["coordinates"]["exterior"] = [[0.0, 0.0], [1000.0, 1000.0], [1000.0, 0.0], [0.0, 1000.0], [0.0, 0.0]]
    # Recompute digests on standalone IR so resolve_ir_and_view passes into hatch geometry validation
    from vnai.drafting_engine import _compute_digests

    standalone_hatch.update(_compute_digests(standalone_hatch))
    res_h2 = export_drafting_dxf(standalone_hatch, tmp_path / "bad_hatch2.dxf")
    assert res_h2["export_status"] == "CONFLICT"
    assert res_h2["errors"][0]["code"] == "INVALID_HATCH_BOUNDARY"
    assert not (tmp_path / "bad_hatch2.dxf").exists()

    # 2. Unsupported primitive type -> UNSUPPORTED (exit 5)
    bad_prim = deepcopy(ir)
    bad_prim["model_space"]["views"][0]["entities"][0]["entity_type"] = "SPLINE"
    res_p = export_drafting_dxf(bad_prim, tmp_path / "bad_prim.dxf")
    assert res_p["export_status"] == "UNSUPPORTED"
    assert res_p["errors"][0]["code"] == "UNSUPPORTED_PRIMITIVE"

    # 3. Unmapped entity layer -> INVALID_INPUT (UNMAPPED_ENTITY_LAYER, never layer '0')
    bad_layer = deepcopy(ir)
    bad_layer["model_space"]["views"][0]["entities"][0]["layer"] = "E-UNKNOWN-ELEC"
    res_l = export_drafting_dxf(bad_layer, tmp_path / "bad_layer.dxf")
    assert res_l["export_status"] == "INVALID_INPUT"
    assert res_l["errors"][0]["code"] == "UNMAPPED_ENTITY_LAYER"

    # 4. Missing source digest -> INVALID_INPUT (MISSING_SOURCE_DIGEST)
    no_dig = deepcopy(ir)
    no_dig["drawing_ir_digest"] = None
    res_d = export_drafting_dxf(no_dig, tmp_path / "no_dig.dxf")
    assert res_d["export_status"] == "INVALID_INPUT"
    assert res_d["errors"][0]["code"] == "MISSING_SOURCE_DIGEST"


def test_roundtrip_detects_corruption_deletion_geometry_shift_dimension_and_unicode_tamper(tmp_path):
    """Audit and round-trip detect DXF corruption, deleted entity, moved point, changed dim & Unicode."""
    ir = _oracle_a_ir()
    dxf_p = tmp_path / "clean.dxf"
    man = export_drafting_dxf(ir, dxf_p)
    assert man["export_status"] == "EXPORTED"

    # 1. Corrupt DXF bytes -> AUDIT CRITICAL_ERRORS
    corrupt = tmp_path / "corrupt.dxf"
    corrupt.write_text("NOT A VALID DXF HEADER\n0\nEOF\n", encoding="utf-8")
    aud_bad = audit_dxf_file(corrupt)
    assert aud_bad["audit_status"] == "CRITICAL_ERRORS"
    assert aud_bad["lossless_eligible"] is False

    # 2. Deleted entity after export -> MISSING_EXPORTED_ENTITY
    del_p = tmp_path / "deleted.dxf"
    doc = ezdxf.readfile(dxf_p)
    msp = doc.modelspace()
    msp.delete_entity(list(msp.query("HATCH"))[0])
    doc.saveas(del_p)
    rt_del = verify_dxf_roundtrip(ir, del_p)
    assert rt_del["roundtrip_status"] == "MISMATCH"
    assert rt_del["missing_entities"]

    # 3. Modified geometry (wall vertex shifted 50 mm) -> POLYLINE_VERTEX_MISMATCH
    mod_p = tmp_path / "moved_geom.dxf"
    doc = ezdxf.readfile(dxf_p)
    lw = list(doc.modelspace().query('LWPOLYLINE[layer=="A-WALL-EXT"]'))[0]
    pts = list(lw.get_points("xy"))
    pts[0] = (pts[0][0] + 50.0, pts[0][1])
    lw.set_points(pts)
    doc.saveas(mod_p)
    rt_mod = verify_dxf_roundtrip(ir, mod_p)
    assert rt_mod["roundtrip_status"] == "MISMATCH"
    assert any(m["code"] == "POLYLINE_VERTEX_MISMATCH" for m in rt_mod["mismatches"])

    # 4. Modified dimension measurement -> DIMENSION_MEASUREMENT_MISMATCH
    dim_p = tmp_path / "tampered_dim.dxf"
    doc = ezdxf.readfile(dxf_p)
    d0 = list(doc.modelspace().query("DIMENSION"))[0]
    d0.dxf.actual_measurement = 9999.0
    doc.saveas(dim_p)
    rt_dim = verify_dxf_roundtrip(ir, dim_p)
    assert rt_dim["roundtrip_status"] == "MISMATCH"
    assert any(m["code"] == "DIMENSION_MEASUREMENT_MISMATCH" for m in rt_dim["mismatches"])

    # 5. Modified Unicode MTEXT (stripped Vietnamese diacritics) -> MTEXT_UNICODE_MISMATCH
    uni_p = tmp_path / "tampered_unicode.dxf"
    doc = ezdxf.readfile(dxf_p)
    mt = list(doc.modelspace().query("MTEXT"))[0]
    mt.text = "Phong mau 4x5m"
    doc.saveas(uni_p)
    rt_uni = verify_dxf_roundtrip(ir, uni_p)
    assert rt_uni["roundtrip_status"] == "MISMATCH"
    assert rt_uni["unicode_text_verification"]["all_codepoints_match"] is False
    assert any(m["code"] == "MTEXT_UNICODE_MISMATCH" for m in rt_uni["mismatches"])

    # 6. Recoverable audit fix (undefined entity linetype) -> RECOVERED_WITH_FIXES blocks lossless
    rec_p = tmp_path / "recovered_with_fixes.dxf"
    doc = ezdxf.readfile(dxf_p)
    lw = list(doc.modelspace().query('LWPOLYLINE[layer=="A-WALL-EXT"]'))[0]
    lw.dxf.linetype = "NO_SUCH_LTYPE"
    doc.saveas(rec_p)
    aud_rec = audit_dxf_file(rec_p)
    assert aud_rec["audit_status"] == "RECOVERED_WITH_FIXES"
    assert aud_rec["lossless_eligible"] is False
    assert aud_rec["fix_count"] >= 1
    rt_rec = verify_dxf_roundtrip(ir, rec_p)
    assert rt_rec["roundtrip_status"] == "MISMATCH"
    assert rt_rec["equivalence_status"] == "MISMATCH"

    # 7. Missing DXF path -> structured MISMATCH without raising FileNotFoundError
    rt_missing = verify_dxf_roundtrip(ir, tmp_path / "does_not_exist.dxf")
    assert rt_missing["roundtrip_status"] == "MISMATCH"
    assert rt_missing["equivalence_status"] == "MISMATCH"
    assert rt_missing["mismatches"][0]["code"] == "CORRUPT_OR_MISSING_DXF"


def test_output_path_protection_and_semantic_fingerprint_handle_independence(tmp_path):
    """Existing output protection, repo file protection, and handle/order-independent fingerprint."""
    ir = _oracle_a_ir()
    out_p = tmp_path / "protected.dxf"
    m1 = export_drafting_dxf(ir, out_p)

    # Implicit overwrite blocked
    with pytest.raises(FileExistsError):
        export_drafting_dxf(ir, out_p)

    # Explicit overwrite blocked against canonical repo fixture/source/schema paths
    with pytest.raises(ValueError, match="protected repository"):
        export_drafting_dxf(ir, ROOT / "examples" / "batch007c" / "illegal.dxf", overwrite=True)
    with pytest.raises(ValueError, match="input specification"):
        export_drafting_dxf(ir, out_p, overwrite=True, source_input_path=out_p)

    # Re-export or re-open produces identical handle-free semantic_fingerprint
    out_p2 = tmp_path / "reexport.dxf"
    m2 = export_drafting_dxf(ir, out_p2)
    assert m1["semantic_fingerprint"] == m2["semantic_fingerprint"]
    assert compute_file_sha256(out_p) == m1["dxf_file_sha256"]

    # Manifest extracted directly from DXF recovers IR mappings cleanly without relying on handles
    ext = extract_manifest_from_dxf(out_p)
    assert ext["ir_mapped_entity_count"] == len(ir["model_space"]["views"][0]["entities"])
    assert ext["untagged_entity_count"] == 0
    assert ext["cad_writes_permitted"] is False


def test_townhouse_f1_f2_stair_section_straight_and_legacy_schematic_compatibility(tmp_path):
    """Exports F1, F2, DEVELOPED U-stair, TRUE_LONGITUDINAL straight stair & preserves legacy dxf."""
    th_ir = _townhouse_ir()
    # Ambiguous multi-view without --view/--floor rejected safely
    amb = export_drafting_dxf(th_ir, tmp_path / "ambig.dxf")
    assert amb["export_status"] == "INVALID_INPUT"
    assert amb["errors"][0]["code"] == "AMBIGUOUS_MULTI_VIEW_EXPORT"

    for vid, exp_sec in (("PLAN-F1", None), ("PLAN-F2", None), ("SECT-S1", "DEVELOPED_EXPLICIT_WALKING_LINE")):
        man = export_drafting_dxf(th_ir, tmp_path / f"{vid}.dxf", view_id=vid)
        assert man["export_status"] == "EXPORTED"
        assert man["section_kind"] == exp_sec
        assert man["dxf_audit"]["audit_status"] == "CLEAN"
        assert man["roundtrip_verification"]["equivalence_status"] == "LOSSLESS_EQUIVALENT"
        assert man["cad_writes_permitted"] is False
        assert man["architect_approval"] == "NOT_GRANTED"

    # Straight stair true section
    st_ir = deepcopy(_cached_ir("oracle-stair-section.json"))
    m_st = export_drafting_dxf(st_ir, tmp_path / "straight_stair.dxf", view_id="SECT-S1")
    assert m_st["export_status"] == "EXPORTED"
    assert m_st["section_kind"] == "TRUE_LONGITUDINAL"

    # Legacy schematic DXF command stays intact
    plan = json.loads((ROOT / "examples" / "townhouse_sample.json").read_text(encoding="utf-8"))
    leg_out = export_schematic_dxf(plan, tmp_path / "legacy_schematic.dxf")
    assert leg_out.exists()
    assert len(ezdxf.readfile(leg_out).modelspace().query("LWPOLYLINE")) == 4
