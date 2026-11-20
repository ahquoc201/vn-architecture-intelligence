"""CLI, schema, tampering, exclusive-output and 9-SVG preview checks for Batch 007-C."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
import pytest

from vnai.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "batch007c"
PREVIEWS = EXAMPLES / "previews"


@pytest.mark.parametrize("name", ["drafting-input.schema.json", "drafting-ir.schema.json"])
def test_drafting_schemas_are_valid(name):
    schema = json.loads((ROOT / "knowledge" / "architecture" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_drafting_cli_generate_validate_report_layers_preview_and_tamper(tmp_path, capsys):
    src = EXAMPLES / "oracle-exterior-clear.json"
    raw = src.read_bytes()
    out_json = tmp_path / "drafting.json"
    out_md = tmp_path / "drafting.md"
    assert (
        main(
            [
                "design",
                "drafting",
                "generate",
                str(src),
                "--out",
                str(out_json),
                "--markdown",
                str(out_md),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["drafting_status"] == "GENERATED"
    assert report["cad_writes_permitted"] is False
    assert src.read_bytes() == raw
    assert "Phòng mẫu 4x5m" in out_md.read_text(encoding="utf-8")

    # Exclusive output prevents overwrite
    preserved = out_json.read_bytes()
    assert main(["design", "drafting", "generate", str(src), "--out", str(out_json)]) == 2
    capsys.readouterr()
    assert out_json.read_bytes() == preserved

    # Validate stored IR report
    assert main(["design", "drafting", "validate", str(out_json)]) == 0
    assert json.loads(capsys.readouterr().out)["drawing_ir_digest"] == report["drawing_ir_digest"]

    # Tampered dimension label is rejected (exit 1)
    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["dimensions"][0]["display_text"] = "9999"
    bad_json = tmp_path / "tampered.json"
    bad_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert main(["design", "drafting", "validate", str(bad_json)]) == 1
    bad_out = json.loads(capsys.readouterr().out)
    assert bad_out["drafting_status"] == "INVALID_INPUT"

    # Report & Layers commands on stored IR
    rep_md = tmp_path / "report.md"
    lay_md = tmp_path / "layers.md"
    assert main(["design", "drafting", "report", str(out_json), "--markdown", str(rep_md)]) == 0
    capsys.readouterr()
    assert "Architectural Drafting & Annotation Report" in rep_md.read_text(encoding="utf-8")
    assert main(["design", "drafting", "layers", str(out_json), "--markdown", str(lay_md)]) == 0
    lay_json = json.loads(capsys.readouterr().out)
    assert lay_json["cad_writes_permitted"] is False
    assert "A-WALL-EXT" in lay_md.read_text(encoding="utf-8")

    # Preview command with layer filtering and scale override
    svg_f1 = tmp_path / "f1.svg"
    assert (
        main(
            [
                "design",
                "drafting",
                "preview",
                str(out_json),
                "--floor",
                "F1",
                "--layers",
                "A-WALL-EXT,A-DIMS",
                "--out",
                str(svg_f1),
            ]
        )
        == 0
    )
    capsys.readouterr()
    svg_txt = svg_f1.read_text(encoding="utf-8")
    root_el = ET.fromstring(svg_txt)
    assert root_el.attrib["preserveAspectRatio"] == "xMidYMid meet"
    ns = "{http://www.w3.org/2000/svg}"
    meta = json.loads(root_el.find(f"{ns}metadata").text)
    assert meta["visible_layers"] == ["A-DIMS", "A-WALL-EXT"]
    assert meta["cad_writes_permitted"] is False

    # Applying --scale to a finalized architectural-drafting-v1 IR report is rejected (exit 2)
    bad_scale_svg = tmp_path / "bad_scale.svg"
    assert (
        main(
            [
                "design",
                "drafting",
                "preview",
                str(out_json),
                "--scale",
                "50",
                "--out",
                str(bad_scale_svg),
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert not bad_scale_svg.exists()


def test_drafting_cli_exit_codes_for_conflict_incomplete_and_malformed(tmp_path, capsys):
    # Conflict exit code 4
    col_svg = tmp_path / "col.svg"
    assert (
        main(
            [
                "design",
                "drafting",
                "preview",
                str(EXAMPLES / "collision-example.json"),
                "--floor",
                "F1",
                "--out",
                str(col_svg),
            ]
        )
        == 4
    )
    col_rep = json.loads(capsys.readouterr().out)
    assert col_rep["drafting_status"] == "CONFLICT"
    assert "A-REVIEW" in col_svg.read_text(encoding="utf-8")

    # Incomplete exit code 3 when require_north_arrow is True without confirmed north
    inc_spec = json.loads((EXAMPLES / "oracle-exterior-clear.json").read_text(encoding="utf-8"))
    inc_spec["orientation_override"] = {
        "north_degrees": 0,
        "confirmation": "missing",
        "provenance": "unconfirmed test north",
    }
    inc_spec["annotation_options"]["require_north_arrow"] = True
    inc_path = tmp_path / "inc.json"
    inc_path.write_text(json.dumps(inc_spec), encoding="utf-8")
    assert main(["design", "drafting", "generate", str(inc_path)]) == 3
    assert json.loads(capsys.readouterr().out)["drafting_status"] == "INCOMPLETE"

    # Malformed JSON -> exit 2, no file created
    bad = tmp_path / "bad.json"
    bad.write_text('{"x":NaN}')
    bad_svg = tmp_path / "bad.svg"
    assert main(["design", "drafting", "preview", str(bad), "--out", str(bad_svg)]) == 2
    capsys.readouterr()
    assert not bad_svg.exists()


def test_townhouse_config_overlay_and_scale_flag_cli(tmp_path, capsys):
    out_json = tmp_path / "th50.json"
    assert (
        main(
            [
                "design",
                "drafting",
                "generate",
                str(ROOT / "examples/batch007b4/residential-4x20-six-rooms.json"),
                "--config",
                str(EXAMPLES / "townhouse-6rooms-config.json"),
                "--scale",
                "50",
                "--out",
                str(out_json),
            ]
        )
        == 0
    )
    rep = json.loads(capsys.readouterr().out)
    assert rep["paper_space"]["scale_label"] == "1:50"
    assert any(r["display_name"] == "Phòng khách" for r in rep["annotations"]["rooms"])


def test_committed_nine_svg_previews_exist_and_are_valid():
    expected = (
        "01-townhouse-ground-floor-F1.svg",
        "02-townhouse-upper-floor-F2.svg",
        "03-dimension-chain-example.svg",
        "04-room-annotation-example.svg",
        "05-opening-annotation-example.svg",
        "06-annotated-stair-section.svg",
        "07-layer-visibility-example.svg",
        "08-annotation-collision-example.svg",
        "09-townhouse-complete-annotated-sheet.svg",
    )
    ns = "{http://www.w3.org/2000/svg}"
    for fname in expected:
        path = PREVIEWS / fname
        assert path.is_file(), f"Missing SVG preview: {path}"
        content = path.read_text(encoding="utf-8")
        root_el = ET.fromstring(content)
        assert root_el.attrib["preserveAspectRatio"] == "xMidYMid meet"
        meta = json.loads(root_el.find(f"{ns}metadata").text)
        assert meta["cad_writes_permitted"] is False
        assert meta["architect_approval"] == "NOT_GRANTED"

    # Spot-check domain content across previews
    assert "Phòng khách" in (PREVIEWS / "01-townhouse-ground-floor-F1.svg").read_text(encoding="utf-8")
    assert "Phòng ngủ 1" in (PREVIEWS / "02-townhouse-upper-floor-F2.svg").read_text(encoding="utf-8")
    assert "1600" in (PREVIEWS / "03-dimension-chain-example.svg").read_text(encoding="utf-8")
    assert "Hành lang chữ L" in (PREVIEWS / "04-room-annotation-example.svg").read_text(encoding="utf-8")
    assert "W01" in (PREVIEWS / "05-opening-annotation-example.svg").read_text(encoding="utf-8")
    assert "DEVELOPED_EXPLICIT_WALKING_LINE" in (PREVIEWS / "06-annotated-stair-section.svg").read_text(encoding="utf-8")
    f7_meta = json.loads(
        ET.fromstring((PREVIEWS / "07-layer-visibility-example.svg").read_text(encoding="utf-8"))
        .find(f"{ns}metadata")
        .text
    )
    assert "A-DIMS" in f7_meta["hidden_layers"]
    assert "A-REVIEW" in (PREVIEWS / "08-annotation-collision-example.svg").read_text(encoding="utf-8")
    assert "SECT-S1" in (PREVIEWS / "09-townhouse-complete-annotated-sheet.svg").read_text(encoding="utf-8")


def test_finalized_ir_rejects_overrides_consistently_across_layers_report_preview(
    tmp_path, capsys
):
    from vnai.drafting_engine import extract_layers_report

    src = EXAMPLES / "oracle-exterior-clear.json"
    out_json = tmp_path / "stored_ir.json"
    cfg_json = tmp_path / "override.json"
    cfg_json.write_text(json.dumps({"style": {"name": "arch-color-v1"}}), encoding="utf-8")

    assert main(["design", "drafting", "generate", str(src), "--out", str(out_json)]) == 0
    capsys.readouterr()

    override_cases = (
        ("cfg", ["--config", str(cfg_json)]),
        ("scale", ["--scale", "50"]),
        ("units", ["--units", "m"]),
    )
    for action in ("layers", "report", "preview"):
        for tag, extra_args in override_cases:
            out_flag = "--out" if action == "preview" else "--markdown"
            ext = "svg" if action == "preview" else "md"
            artifact = tmp_path / f"{action}_{tag}.{ext}"
            argv = [
                "design",
                "drafting",
                action,
                str(out_json),
                *extra_args,
                out_flag,
                str(artifact),
            ]
            assert main(argv) == 2
            err_payload = json.loads(capsys.readouterr().out)
            assert err_payload["status"] == "INVALID"
            assert err_payload["code"] == "INPUT_ERROR"
            assert err_payload["cad_writes_permitted"] is False
            assert "finalized architectural-drafting-v1 IR report" in err_payload["message"]
            assert not artifact.exists()

    stored_ir = json.loads(out_json.read_text(encoding="utf-8"))
    ok_layers = extract_layers_report(stored_ir)
    assert ok_layers["cad_writes_permitted"] is False
    for kwargs in (
        {"config_override": {}},
        {"scale_override": 50},
        {"units_override": "m"},
    ):
        with pytest.raises(ValueError, match="finalized architectural-drafting-v1 IR report"):
            extract_layers_report(stored_ir, **kwargs)

    # Non-finalized drafting input still accepts --scale override cleanly on layers.
    assert main(["design", "drafting", "layers", str(src), "--scale", "50"]) == 0
    layers_out = json.loads(capsys.readouterr().out)
    assert layers_out["cad_writes_permitted"] is False
    assert layers_out["drafting_status"] == "GENERATED"
