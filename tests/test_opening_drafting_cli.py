"""Versioned B2 golden, CLI compatibility, exclusive outputs and actual SVG."""

import json
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from jsonschema import Draft202012Validator
from vnai.cli import main
from vnai.opening_drafting import draft_openings, EXIT_CODES
from vnai.contracts import new_report, schema_check, canonical_digest
from opening_drafting_fixtures import projection

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / "examples/batch007b2").glob("*.json"))
GOLD = ROOT / "tests/golden/batch007b2-v0.1.11"


def frozen(path):
    return json.loads((GOLD / path.name).read_text())


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_versioned_opening_drafting_golden(path, monkeypatch):
    monkeypatch.setattr("vnai.contracts.__version__", "0.1.11")
    monkeypatch.setattr("vnai.design_brief.__version__", "0.1.11")
    raw = path.read_bytes()
    r = draft_openings(json.loads(raw))
    assert projection(r) == frozen(path)
    check = new_report("schema-test")
    assert schema_check(r, "opening-drafting-result.schema.json", check), check
    assert path.read_bytes() == raw
    assert (
        not r["cad_writes_permitted"]
        and r["standards_review"] == r["fengshui_review"] == "NOT_EVALUATED"
    )


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_draft_cli_all_fixtures(path, capsys):
    before = path.read_bytes()
    expected = frozen(path)
    code = main(["design", "openings", "draft", str(path)])
    r = json.loads(capsys.readouterr().out)
    assert code == EXIT_CODES[expected["drafting_status"]]
    assert canonical_digest(r) == expected["full_report_sha256"]
    assert path.read_bytes() == before and not r["approval_inherited"]


@pytest.mark.parametrize(
    "name",
    [
        "oracle-entrance",
        "fixed-window",
        "window-above-cut",
        "swing-fixed-collision",
        "missing-dimensions",
        "unsupported-angle",
        "stale-wall-digest",
        "townhouse-benchmark",
    ],
)
@pytest.mark.parametrize("action", ["drafting-validate", "schedule", "preview"])
def test_remaining_drafting_commands(name, action, tmp_path, capsys):
    path = ROOT / "examples/batch007b2" / (name + ".json")
    expected = frozen(path)
    args = ["design", "openings", action, str(path)]
    target = tmp_path / (name + (".svg" if action == "preview" else ".md"))
    if action == "preview":
        args += ["--out", str(target)]
    if action == "schedule":
        args += ["--markdown", str(target)]
    code = main(args)
    r = json.loads(capsys.readouterr().out)
    assert code == EXIT_CODES[expected["drafting_status"]]
    assert canonical_digest(r) == expected["full_report_sha256"]
    if action == "preview":
        assert target.exists() == bool(r["floors"])
        if r["floors"]:
            assert hashlib.sha256(target.read_bytes()).hexdigest() == expected["svg_sha256"]
            svg = ET.fromstring(target.read_text())
            assert svg.attrib["preserveAspectRatio"] == "xMidYMid meet"
            meta = svg.find("{http://www.w3.org/2000/svg}metadata[@id='opening-drafting-revision']")
            assert json.loads(meta.text)["opening_revision_id"] == r["opening_revision_id"]
    if action == "schedule":
        assert "PROPOSED" in target.read_text()


def test_stored_draft_tamper_and_exclusive_outputs(tmp_path, capsys):
    source = ROOT / "examples/batch007b2/oracle-entrance.json"
    report = draft_openings(json.loads(source.read_text()))
    stored = tmp_path / "stored.json"
    stored.write_text(json.dumps(report))
    assert main(["design", "openings", "drafting-validate", str(stored)]) == 0
    capsys.readouterr()
    report["schedule"][0]["quantity"] = 99
    stored.write_text(json.dumps(report))
    assert main(["design", "openings", "drafting-validate", str(stored)]) == 1
    capsys.readouterr()
    target = tmp_path / "existing.svg"
    target.write_text("keep original")
    assert main(["design", "openings", "preview", str(source), "--out", str(target)]) == 2
    capsys.readouterr()
    assert target.read_text() == "keep original"


@pytest.mark.parametrize(
    "body", ['{"schema_version":1,"schema_version":2}', '{"x":NaN}', "[]", "{"]
)
def test_bad_input_creates_no_preview(body, tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text(body)
    svg = tmp_path / "bad.svg"
    assert main(["design", "openings", "preview", str(source), "--out", str(svg)]) in (1, 2)
    capsys.readouterr()
    assert not svg.exists()


@pytest.mark.parametrize(
    "name", ["opening-drafting-input.schema.json", "opening-drafting-result.schema.json"]
)
def test_drafting_schemas_are_valid(name):
    Draft202012Validator.check_schema(
        json.loads((ROOT / "knowledge/architecture" / name).read_text())
    )


def test_legacy_opening_validate_command_is_unchanged(capsys):
    path = ROOT / "examples/batch006b/corridor-clearance.json"
    assert main(["design", "openings", "validate", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["contract"] == "opening-validation-v1" and not result["cad_writes_permitted"]
