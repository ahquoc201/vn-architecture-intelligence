"""Immutable 0.1.8 scenario goldens, CLI exits and exclusive report creation."""

import json
from pathlib import Path

import pytest

from evaluation_fixtures import golden_projection
from vnai.candidate_evaluation import evaluate_candidates
from vnai.candidate_comparison import compare_candidates
from vnai.candidate_ranking import rank_candidates
from vnai.cli import main
from vnai.contracts import new_report, schema_check

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples/batch006c"
NAMES = sorted(p.stem for p in EXAMPLES.glob("*.json"))


@pytest.mark.parametrize("name", NAMES)
def test_versioned_golden(name, monkeypatch):
    import vnai.contracts
    import vnai.design_brief

    monkeypatch.setattr(vnai.contracts, "__version__", "0.1.8")
    monkeypatch.setattr(vnai.design_brief, "__version__", "0.1.8")
    spec = json.loads((EXAMPLES / (name + ".json")).read_text())
    handler = rank_candidates if len(spec["candidates"]) > 1 else evaluate_candidates
    actual = handler(spec)
    golden = ROOT / "tests/golden/batch006c-v0.1.8" / (name + ".json")
    assert golden_projection(actual) == json.loads(golden.read_text())
    assert handler(spec) == actual


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "action,handler",
    [("evaluate", evaluate_candidates), ("compare", compare_candidates), ("rank", rank_candidates)],
)
def test_cli_all_examples_exact_output(name, action, handler, capsys):
    path = EXAMPLES / (name + ".json")
    before = path.read_bytes()
    report = handler(json.loads(before))
    validation = new_report("output-contract")
    schema = {"evaluate": "evaluation", "compare": "comparison", "rank": "ranking"}[action]
    assert schema_check(report, "candidate-" + schema + ".schema.json", validation), validation
    if report["errors"]:
        expected = 1
    elif action == "rank":
        expected = {
            "RANKED": 0,
            "TIED": 0,
            "RANKING_WITHHELD": 3,
            "PARTIALLY_COMPARABLE": 3,
            "NO_ELIGIBLE_CANDIDATES": 4,
        }[report["ranking_status"]]
    else:
        expected = {"VALID": 0, "INVALID": 1, "INCOMPLETE": 3}[report["status"]]
    assert main(["design", "candidates", action, str(path)]) == expected
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out) == report
    assert path.read_bytes() == before


def test_markdown_and_input_errors(tmp_path, capsys):
    source = EXAMPLES / "three-candidates.json"
    target = tmp_path / "comparison.md"
    args = ["design", "candidates", "rank", str(source), "--markdown", str(target)]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    before = target.read_bytes()
    assert target.read_text() == report["markdown"]
    assert (
        "Candidate digest:" in report["markdown"]
        and "Evidence counts (not confidence):" in report["markdown"]
    )
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"
    assert target.read_bytes() == before
    malformed = tmp_path / "bad.json"
    malformed.write_text('{"schema_version":1,"schema_version":1}')
    assert main(["design", "candidates", "evaluate", str(malformed)]) == 2
    assert "Duplicate" in json.loads(capsys.readouterr().out)["message"]
    assert main(["design", "candidates", "rank", str(tmp_path / "missing.json")]) == 2
    capsys.readouterr()
