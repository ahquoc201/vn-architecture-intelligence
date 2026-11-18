"""Golden reports and stable CLI output, exit codes and read-only behavior."""

import json

import pytest

from batch005_fixtures import ROOT, fixture
from vnai.cli import main
from vnai.spatial import validate_geometry
from vnai.zoning import validate_zoning

NAMES = sorted(p.stem for p in (ROOT / "examples/batch005").glob("*.json"))


@pytest.mark.parametrize("name", NAMES)
def test_full_golden_report(name, monkeypatch):
    # Preserve 0.1.5 snapshots while exercising current implementations with historical stamps.
    import vnai.contracts
    import vnai.design_brief
    monkeypatch.setattr(vnai.contracts, "__version__", "0.1.5")
    monkeypatch.setattr(vnai.design_brief, "__version__", "0.1.5")
    doc = fixture(name)
    report = validate_zoning(doc) if name.startswith("zoning") else validate_geometry(doc)
    expected = json.loads((ROOT / "tests/golden/batch005" / (name + ".json")).read_text())
    assert report == expected


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("action", ["validate", "report"])
def test_cli_json_exit_codes_and_stability(name, action, tmp_path, capsys):
    doc = fixture(name)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    before = path.read_bytes()
    args = (["design", "zoning"] if name.startswith("zoning") else ["geometry"]) + [
        action,
        str(path),
    ]
    expected = validate_zoning(doc) if name.startswith("zoning") else validate_geometry(doc)
    code = {"VALID": 0, "INVALID": 1, "INCOMPLETE": 3}[expected["status"]]
    assert main(args) == code
    first = capsys.readouterr()
    assert json.loads(first.out) == expected and not first.err
    assert main(args) == code
    assert capsys.readouterr().out == first.out
    assert before == path.read_bytes()
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("command", [["design", "zoning"], ["geometry"]])
@pytest.mark.parametrize(
    "bad",
    [
        "{invalid",
        '{"schema_version":1,"schema_version":2}',
        '{"schema_version":NaN}',
        '{"schema_version":1e999}',
    ],
)
def test_new_cli_parse_errors(command, bad, tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(bad)
    assert main([*command, "validate", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"


@pytest.mark.parametrize("command", [["design", "zoning"], ["geometry"]])
def test_new_cli_missing_file(command, tmp_path, capsys):
    assert main([*command, "report", str(tmp_path / "missing.json")]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"
