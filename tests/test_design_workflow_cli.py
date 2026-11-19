"""Versioned scenario oracles and command-line contracts for Batch 007A."""

import json
from pathlib import Path
from copy import deepcopy

import pytest

from replay_fixtures import projection
from vnai.architectural_benchmark import run_benchmark
from vnai.cad_readiness import readiness_report
from vnai.cli import main
from vnai.contracts import new_report, schema_check
from vnai.design_replay import validate_replay
from vnai.design_reports import workflow_exit, workflow_markdown
from vnai.design_revision import compare_revision

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "examples/batch007a"
FILES = sorted(INPUTS.glob("*/*.json"))
HANDLERS = {
    "replay": validate_replay,
    "revision": compare_revision,
    "readiness": readiness_report,
    "benchmark": run_benchmark,
}
ACTIONS = {"replay": "report", "revision": "compare", "readiness": "report", "benchmark": "run"}
SCHEMAS = {
    "replay": "design-replay",
    "revision": "design-revision",
    "readiness": "cad-readiness",
    "benchmark": "architectural-benchmark",
}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_versioned_full_report_oracle_and_determinism(path, monkeypatch):
    import vnai.contracts
    import vnai.design_brief

    monkeypatch.setattr(vnai.contracts, "__version__", "0.1.9")
    monkeypatch.setattr(vnai.design_brief, "__version__", "0.1.9")
    value = json.loads(path.read_text(encoding="utf-8"))
    before = deepcopy(value)
    handler = HANDLERS[path.parent.name]
    report = handler(value)
    expected = ROOT / "tests/golden/batch007a-v0.1.9" / path.parent.name / path.name
    assert projection(report) == json.loads(expected.read_text())
    assert handler(value) == report and value == before
    check = new_report("test")
    assert schema_check(report, SCHEMAS[path.parent.name] + ".schema.json#/$defs/result", check), (
        check
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_cli_exact_json_exit_codes_and_input_preservation(path, capsys):
    before = path.read_bytes()
    report = HANDLERS[path.parent.name](json.loads(before))
    args = ["design", path.parent.name, ACTIONS[path.parent.name], str(path)]
    assert main(args) == workflow_exit(report)
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out) == report
    assert path.read_bytes() == before


def test_replay_validate_and_exclusive_markdown(tmp_path, capsys):
    path = INPUTS / "replay/valid-provenance.json"
    target = tmp_path / "replay-v0.1.9.md"
    args = ["design", "replay", "validate", str(path), "--markdown", str(target)]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert target.read_text() == workflow_markdown(report)
    before = target.read_bytes()
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"
    assert target.read_bytes() == before


@pytest.mark.parametrize("kind", list(HANDLERS))
def test_invalid_contract_and_operational_errors(kind, tmp_path, capsys):
    path = tmp_path / "invalid.json"
    path.write_text('{"schema_version":999}')
    args = ["design", kind, ACTIONS[kind], str(path)]
    assert main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["errors"] and not report["cad_writes_permitted"]
    path.write_text('{"schema_version":1,"schema_version":1}')
    assert main(args) == 2
    assert "Duplicate" in json.loads(capsys.readouterr().out)["message"]


def test_optional_generation_provenance_cli(capsys):
    path = ROOT / "examples/batch006a/two-room.json"
    assert main(["design", "floorplan", "generate", str(path), "--provenance"]) == 0
    generated = json.loads(capsys.readouterr().out)
    assert len(generated["generation_provenance"]) == len(generated["candidates"])
    assert all(
        p["dependency_digests"]["generation_input"] == c["input_digest"]
        for p, c in zip(generated["generation_provenance"], generated["candidates"])
    )


def test_benchmark_summary_includes_missing_readiness_evidence():
    path = INPUTS / "benchmark/benchmark-a.json"
    report = run_benchmark(json.loads(path.read_text()))
    assert report["generation"]["status"] == "GENERATED" and len(report["candidates"]) == 3
    for item in report["metrics"]["replay"]:
        assert item["coverage"]["evaluation_fraction"] == 1
        assert item["verified_hard_violations"] == 0
        assert {"selection_review", "multi_floor_stair_information"} <= set(
            item["missing_required_evidence"]
        )
        circulation = item["circulation_coverage"]
        assert circulation["applicable_rooms"] == 6 and circulation["verified_rooms"] == 0
        assert circulation["unknown_rooms"] == 6 and circulation["quality_score"] is None
        assert circulation["physical_state"] == "NOT_VERIFIED"
        assert item["feedback_resolution_status"] == "NOT_COLLECTED"
    assert (
        report["human_review_status"] == "PENDING"
        and report["expert_oracle_status"] == "NOT_ESTABLISHED"
    )
