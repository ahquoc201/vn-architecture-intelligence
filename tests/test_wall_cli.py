"""Versioned walls, command boundaries, stored-report validation and real SVG."""

from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from vnai.cli import main
from vnai.walls import generate_walls, EXIT_CODES
from vnai.wall_preview import wall_svg, wall_markdown
from wall_fixtures import projection

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / "examples/batch007b1").glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_versioned_wall_golden(path, monkeypatch):
    monkeypatch.setattr("vnai.contracts.__version__", "0.1.10")
    monkeypatch.setattr("vnai.design_brief.__version__", "0.1.10")
    original = path.read_bytes()
    report = generate_walls(json.loads(original))
    expected = json.loads((ROOT / "tests/golden/batch007b1-v0.1.10" / path.name).read_text())
    assert projection(report) == expected
    assert path.read_bytes() == original


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_wall_commands(path, tmp_path, capsys):
    original = path.read_bytes()
    generated = None
    for action in ("generate", "validate", "report", "preview"):
        args = ["design", "walls", action, str(path)]
        destination = tmp_path / (path.stem + (".svg" if action == "preview" else ".md"))
        if action == "preview":
            args += ["--out", str(destination)]
        elif action == "report":
            args += ["--markdown", str(destination)]
        code = main(args)
        report = json.loads(capsys.readouterr().out)
        assert code == EXIT_CODES[report["wall_status"]]
        if generated is None:
            generated = report
        else:
            assert report == generated
        if action == "report":
            assert destination.read_text() == wall_markdown(report)
        if action == "preview":
            assert destination.exists() == bool(report["floors"])
            if report["floors"]:
                assert destination.read_text() == wall_svg(report)
                svg = ET.fromstring(destination.read_text())
                assert svg.attrib["preserveAspectRatio"] == "xMidYMid meet"
                meta = json.loads(svg.find("{http://www.w3.org/2000/svg}metadata").text)
                assert not meta["cad_writes_permitted"]
        assert not report["cad_writes_permitted"] and not report["approval_inherited"]
    assert path.read_bytes() == original


def test_cli_stored_report_tampering_and_exclusive_output(tmp_path, capsys):
    path = ROOT / "examples/batch007b1/rectangle-inward.json"
    report = generate_walls(json.loads(path.read_text()))
    stored = tmp_path / "stored.json"
    stored.write_text(json.dumps(report))
    assert main(["design", "walls", "validate", str(stored)]) == 0
    assert json.loads(capsys.readouterr().out)["wall_status"] == "GENERATED"
    tampered = deepcopy(report)
    tampered["rooms"][0]["clear_area_m2"] = 999
    stored.write_text(json.dumps(tampered))
    assert main(["design", "walls", "validate", str(stored)]) == 1
    assert json.loads(capsys.readouterr().out)["wall_status"] == "INVALID_INPUT"
    target = tmp_path / "keep.svg"
    target.write_text("existing output")
    assert main(["design", "walls", "preview", str(path), "--out", str(target)]) == 2
    capsys.readouterr()
    assert target.read_text() == "existing output"


@pytest.mark.parametrize(
    "body", ['{"schema_version":1,"schema_version":2}', '{"x":NaN}', "[]", "{"]
)
def test_cli_malformed_input_does_not_create_preview(body, tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text(body)
    target = tmp_path / "bad.svg"
    assert main(["design", "walls", "preview", str(source), "--out", str(target)]) in (1, 2)
    capsys.readouterr()
    assert not target.exists()


@pytest.mark.parametrize("name", ["wall-input.schema.json", "wall-result.schema.json"])
def test_wall_schema_is_valid(name):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(
        json.loads((ROOT / "knowledge/architecture" / name).read_text())
    )


def test_townhouse_wall_source_preserves_existing_benchmark_requirements():
    benchmark = json.loads((ROOT / "examples/batch007a/benchmark/benchmark-a.json").read_text())
    value = json.loads((ROOT / "examples/batch007b1/townhouse-benchmark.json").read_text())
    assert (
        value["source"]["replay"]["provenance"]["generation_specification"]
        == benchmark["generation_specification"]
    )
    assert value["source"]["policy"] == benchmark["readiness_policy"]
