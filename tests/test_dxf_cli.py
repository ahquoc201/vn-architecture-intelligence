"""CLI, schema, exit-code and committed townhouse deliverable DXF checks for Batch 007-D."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from vnai.cli import main
from vnai.drafting_engine import generate_drafting

ROOT = Path(__file__).resolve().parents[1]
EX7C = ROOT / "examples" / "batch007c"
EX7D = ROOT / "examples" / "batch007d"
EXPORTS = EX7D / "exports"


@pytest.mark.parametrize("name", ["dxf-export-spec.schema.json", "dxf-manifest.schema.json"])
def test_dxf_batch_schemas_are_valid(name):
    schema = json.loads((ROOT / "knowledge" / "architecture" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_cli_dxf_export_audit_verify_manifest_and_paper_space(tmp_path, capsys):
    ir = generate_drafting(json.loads((EX7C / "oracle-exterior-clear.json").read_text(encoding="utf-8")))
    ir_json = tmp_path / "ora_a_ir.json"
    ir_json.write_text(json.dumps(ir), encoding="utf-8")

    out_dxf = tmp_path / "ora_a.dxf"
    man_json = tmp_path / "ora_a.manifest.json"
    exp_md = tmp_path / "ora_a.export.md"

    assert (
        main(
            [
                "design",
                "dxf",
                "export",
                str(ir_json),
                "--out",
                str(out_dxf),
                "--paper-size",
                "420x297",
                "--manifest",
                str(man_json),
                "--markdown",
                str(exp_md),
            ]
        )
        == 0
    )
    rep_exp = json.loads(capsys.readouterr().out)
    assert rep_exp["export_status"] == "EXPORTED"
    assert rep_exp["cad_writes_permitted"] is False
    assert rep_exp["manual_autocad_acceptance_status"] == "PENDING_HUMAN_AUTOCAD_VERIFICATION"
    assert "Manual AutoCAD Acceptance Checklist" in exp_md.read_text(encoding="utf-8")

    # Audit CLI
    aud_md = tmp_path / "aud.md"
    assert main(["design", "dxf", "audit", str(out_dxf), "--markdown", str(aud_md)]) == 0
    rep_aud = json.loads(capsys.readouterr().out)
    assert rep_aud["audit_status"] == "CLEAN"
    assert rep_aud["cad_writes_permitted"] is False

    # Verify CLI
    ver_md = tmp_path / "ver.md"
    assert (
        main(
            [
                "design",
                "dxf",
                "verify",
                str(ir_json),
                "--dxf",
                str(out_dxf),
                "--markdown",
                str(ver_md),
            ]
        )
        == 0
    )
    rep_ver = json.loads(capsys.readouterr().out)
    assert rep_ver["roundtrip_status"] == "VERIFIED"
    assert rep_ver["equivalence_status"] == "LOSSLESS_EQUIVALENT"

    # Manifest CLI with --sidecar
    man_md = tmp_path / "man.md"
    assert (
        main(
            [
                "design",
                "dxf",
                "manifest",
                str(out_dxf),
                "--sidecar",
                str(man_json),
                "--markdown",
                str(man_md),
            ]
        )
        == 0
    )
    rep_man = json.loads(capsys.readouterr().out)
    assert rep_man["sidecar_checksum_match"] is True
    assert rep_man["untagged_entity_count"] == 0

    # Export spec v1 wrapper & --units m
    spec_json = tmp_path / "export_spec.json"
    spec_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "dxf-export-spec-v1",
                "drafting_ir": ir,
                "target_units": "m",
                "dxf_version": "R2013",
            }
        ),
        encoding="utf-8",
    )
    out_m = tmp_path / "ora_a_m.dxf"
    assert main(["design", "dxf", "export", str(spec_json), "--out", str(out_m)]) == 0
    rep_m = json.loads(capsys.readouterr().out)
    assert rep_m["target_units"] == "m"
    assert rep_m["dxf_version"] == "R2013"


def test_cli_dxf_exit_codes_overwrite_incomplete_unsupported_corrupt_and_conflict(tmp_path, capsys):
    ir = generate_drafting(json.loads((EX7C / "oracle-exterior-clear.json").read_text(encoding="utf-8")))
    ir_json = tmp_path / "ir.json"
    ir_json.write_text(json.dumps(ir), encoding="utf-8")

    # Exit 3: --require-paper-space without --paper-size
    inc_dxf = tmp_path / "inc.dxf"
    assert (
        main(
            [
                "design",
                "dxf",
                "export",
                str(ir_json),
                "--out",
                str(inc_dxf),
                "--require-paper-space",
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["export_status"] == "INCOMPLETE"
    assert not inc_dxf.exists()

    # Exit 5: unsupported DXF version
    uns_dxf = tmp_path / "uns.dxf"
    assert (
        main(
            [
                "design",
                "dxf",
                "export",
                str(ir_json),
                "--out",
                str(uns_dxf),
                "--dxf-version",
                "R12",
            ]
        )
        == 5
    )
    assert json.loads(capsys.readouterr().out)["export_status"] == "UNSUPPORTED"

    # Exit 2: existing output file protected unless --overwrite
    existing = tmp_path / "exist.dxf"
    assert main(["design", "dxf", "export", str(ir_json), "--out", str(existing)]) == 0
    capsys.readouterr()
    assert main(["design", "dxf", "export", str(ir_json), "--out", str(existing)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"

    # Exit 1: corrupt DXF audit
    bad_dxf = tmp_path / "bad.dxf"
    bad_dxf.write_text("CORRUPT", encoding="utf-8")
    assert main(["design", "dxf", "audit", str(bad_dxf)]) == 1
    assert json.loads(capsys.readouterr().out)["audit_status"] == "CRITICAL_ERRORS"

    # Exit 4: round-trip verify mismatch against wrong floor / different IR
    other_ir = generate_drafting(json.loads((EX7C / "room-annotation-vn.json").read_text(encoding="utf-8")))
    other_json = tmp_path / "other.json"
    other_json.write_text(json.dumps(other_ir), encoding="utf-8")
    assert main(["design", "dxf", "verify", str(other_json), "--dxf", str(existing)]) == 4
    assert json.loads(capsys.readouterr().out)["roundtrip_status"] == "MISMATCH"


def test_committed_townhouse_deliverable_dxfs_audit_and_verify():
    """All three deliverable townhouse DXFs exist, audit CLEAN, and keep governance flags."""
    files = (
        ("townhouse-F1.dxf", "townhouse-F1.manifest.json", "PLAN-F1", None),
        ("townhouse-F2.dxf", "townhouse-F2.manifest.json", "PLAN-F2", None),
        (
            "townhouse-stair-section.dxf",
            "townhouse-stair-section.manifest.json",
            "SECT-S1",
            "DEVELOPED_EXPLICIT_WALKING_LINE",
        ),
    )
    for dxf_name, man_name, exp_view, exp_section in files:
        dxf_p = EXPORTS / dxf_name
        man_p = EXPORTS / man_name
        assert dxf_p.is_file(), f"Missing deliverable DXF: {dxf_p}"
        assert man_p.is_file(), f"Missing deliverable manifest: {man_p}"
        man = json.loads(man_p.read_text(encoding="utf-8"))
        assert man["export_status"] == "EXPORTED"
        assert man["view_id"] == exp_view
        assert man["section_kind"] == exp_section
        assert man["dxf_audit"]["audit_status"] == "CLEAN"
        assert man["roundtrip_verification"]["equivalence_status"] == "LOSSLESS_EQUIVALENT"
        assert man["cad_writes_permitted"] is False
        assert man["architect_approval"] == "NOT_GRANTED"
        assert man["manual_autocad_acceptance_status"] == "PENDING_HUMAN_AUTOCAD_VERIFICATION"
        assert man["source_digests"]["verification_coverage"]["verified"] == 48
        assert main(["design", "dxf", "audit", str(dxf_p)]) == 0
        assert main(["design", "dxf", "manifest", str(dxf_p), "--sidecar", str(man_p)]) == 0
