"""B3 schemas, versioned JSON/SVG projections, CLI files and legacy compatibility."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from vnai.cli import main
from vnai.contracts import canonical_digest, new_report, schema_check
from vnai.stair_drafting import draft_stairs, EXIT_CODES
from stair_drafting_fixtures import projection

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / "examples/batch007b3").glob("*.json"))
GOLD = ROOT / "tests/golden/batch007b3-v0.1.12"


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_versioned_stair_golden(path, monkeypatch):
    monkeypatch.setattr("vnai.contracts.__version__", "0.1.12")
    monkeypatch.setattr("vnai.design_brief.__version__", "0.1.12")
    original = path.read_bytes()
    r = draft_stairs(json.loads(original))
    expected = json.loads((GOLD / path.name).read_text())
    assert projection(r) == expected
    check = new_report("schema-check")
    assert schema_check(r, "stair-drafting-result.schema.json", check), check
    assert path.read_bytes() == original and not r["cad_writes_permitted"]


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_stair_draft_cli(path, capsys, monkeypatch):
    monkeypatch.setattr("vnai.contracts.__version__", "0.1.12")
    monkeypatch.setattr("vnai.design_brief.__version__", "0.1.12")
    before = path.read_bytes()
    expected = json.loads((GOLD / path.name).read_text())
    code = main(["design", "stairs", "draft", str(path)])
    r = json.loads(capsys.readouterr().out)
    assert code == EXIT_CODES[expected["drafting_status"]]
    assert canonical_digest(r) == expected["full_report_sha256"]
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "name", ["straight", "u-shaped", "headroom-failure", "townhouse-benchmark"]
)
@pytest.mark.parametrize(
    "action", ["drafting-validate", "section", "schedule", "plan-preview", "section-preview"]
)
def test_other_stair_commands(name, action, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("vnai.contracts.__version__", "0.1.12")
    monkeypatch.setattr("vnai.design_brief.__version__", "0.1.12")
    path = ROOT / "examples/batch007b3" / (name + ".json")
    expected = json.loads((GOLD / path.name).read_text())
    target = tmp_path / (name + (".svg" if "preview" in action else ".md"))
    args = ["design", "stairs", "preview" if "preview" in action else action, str(path)]
    if "preview" in action:
        args += ["--view", "plan" if action == "plan-preview" else "section", "--out", str(target)]
    elif action in {"section", "schedule"}:
        args += ["--markdown", str(target)]
    code = main(args)
    r = json.loads(capsys.readouterr().out)
    assert code == EXIT_CODES[expected["drafting_status"]]
    assert canonical_digest(r) == expected["full_report_sha256"]
    if "preview" in action:
        ET.fromstring(target.read_text())
        assert r["stair_revision_id"] in target.read_text()
    elif action in {"section", "schedule"}:
        assert "CAD writes: false" in target.read_text()


def test_stored_stair_report_and_exclusive_files(tmp_path, capsys):
    path = ROOT / "examples/batch007b3/straight.json"
    stored = tmp_path / "stored.json"
    assert main(["design", "stairs", "draft", str(path)]) == 3
    r = json.loads(capsys.readouterr().out)
    stored.write_text(json.dumps(r))
    assert main(["design", "stairs", "drafting-validate", str(stored)]) == 3
    capsys.readouterr()
    r["schedule"][0]["flights"][0]["risers"] = 999
    stored.write_text(json.dumps(r))
    assert main(["design", "stairs", "drafting-validate", str(stored)]) == 1
    capsys.readouterr()
    target = tmp_path / "keep.svg"
    target.write_text("keep")
    assert main(["design", "stairs", "preview", str(path), "--out", str(target)]) == 2
    assert target.read_text() == "keep"
    capsys.readouterr()


@pytest.mark.parametrize(
    "content", ["{", "[]", '{"schema_version":1,"schema_version":1}', '{"bad": NaN}']
)
def test_malformed_stair_cli(content, tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text(content)
    assert main(["design", "stairs", "draft", str(p)]) in {1, 2}
    capsys.readouterr()


def test_old_stair_validation_cli_remains_compatible(capsys):
    assert (
        main(
            ["design", "stairs", "validate", str(ROOT / "examples/batch006b/stairs-connected.json")]
        )
        == 0
    )
    r = json.loads(capsys.readouterr().out)
    assert r["contract"] == "stair-validation-v1" and r["technical_stair_design"] == "NOT_EVALUATED"
    assert r["stair_results"][0]["physical_state"] == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "name", ["stair-drafting-input.schema.json", "stair-drafting-result.schema.json"]
)
def test_stair_schemas_are_valid(name):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(
        json.loads((ROOT / "knowledge/architecture" / name).read_text())
    )
