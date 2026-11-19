"""Full golden outputs, independent stage contracts and read-only CLI behavior."""

import json
from pathlib import Path

import pytest

from vnai.architectural_review import architectural_review
from vnai.candidate_review import review_candidate
from vnai.openings import validate_openings
from vnai.circulation import analyze_circulation
from vnai.stairs import validate_stairs
from vnai.cli import main
from vnai.contracts import new_report, schema_check

ROOT = Path(__file__).resolve().parents[1]
NAMES = sorted(p.stem for p in (ROOT / "examples/batch006b").glob("*.json"))
STAGES = [
    (["candidate", "review"], review_candidate, "candidate-review.schema.json#/$defs/result"),
    (["openings", "validate"], validate_openings, "opening-result.schema.json"),
    (["circulation", "analyze"], analyze_circulation, "circulation-graph.schema.json"),
    (["stairs", "validate"], validate_stairs, "stair-result.schema.json"),
    (["architectural-review"], architectural_review, "architectural-review.schema.json"),
]


def fixture(name):
    return json.loads((ROOT / "examples/batch006b" / (name + ".json")).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_full_golden_output(name, monkeypatch):
    # Preserve the complete 0.1.7 oracle, including historical metadata, under current validators.
    import vnai.contracts
    import vnai.design_brief
    monkeypatch.setattr(vnai.contracts, "__version__", "0.1.7")
    monkeypatch.setattr(vnai.design_brief, "__version__", "0.1.7")
    expected = json.loads((ROOT / "tests/golden/batch006b-v0.1.7" / (name + ".json")).read_text())
    assert architectural_review(fixture(name)) == expected


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("command,handler,schema", STAGES)
def test_all_new_cli_fixtures_have_stable_contracts_and_no_input_mutation(
    name, command, handler, schema, tmp_path, capsys
):
    spec = fixture(name)
    source = tmp_path / "input.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    before = source.read_bytes()
    report = handler(spec)
    check = new_report("output-contract")
    assert schema_check(report, schema, check), check
    code = {"VALID": 0, "INVALID": 1, "INCOMPLETE": 3}[report["status"]]
    args = ["design", *command, str(source)]
    assert main(args) == code
    first = capsys.readouterr()
    assert json.loads(first.out) == report and not first.err
    assert main(args) == code
    assert capsys.readouterr().out == first.out
    assert source.read_bytes() == before and list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("command,handler,schema", STAGES)
@pytest.mark.parametrize(
    "bad", ["{bad", '{"schema_version":1,"schema_version":2}', '{"schema_version":NaN}']
)
def test_new_cli_parse_errors(command, handler, schema, bad, tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text(bad)
    assert main(["design", *command, str(source)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"


@pytest.mark.parametrize("command,handler,schema", STAGES)
def test_missing_input_file_is_structured(command, handler, schema, tmp_path, capsys):
    assert main(["design", *command, str(tmp_path / "missing.json")]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"


@pytest.mark.parametrize("command,handler,schema", STAGES)
@pytest.mark.parametrize("bad", [{}, [], None, {"schema_version": 9}])
def test_invalid_contexts_are_rejected_without_graph_or_approval_claims(
    command, handler, schema, bad
):
    report = handler(bad)
    assert report["status"] == "INVALID" and not report["cad_writes_permitted"]
    check = new_report("invalid-output")
    assert schema_check(report, schema, check), check
