"""Read-only defaults, explicit exclusive output and generator exit codes."""

import json

import pytest
from floorplan_fixtures import synthetic_spec, authorize, alternatives_spec, approve_source
from vnai.cli import main


@pytest.mark.parametrize(
    "state,code",
    [
        ("GENERATED", 0),
        ("INCOMPLETE", 3),
        ("INFEASIBLE", 4),
        ("INVALID_INPUT", 1),
        ("UNSUPPORTED", 5),
        ("SEARCH_EXHAUSTED", 6),
    ],
)
def test_generator_cli_status_codes(state, code, tmp_path, capsys):
    spec = synthetic_spec()
    if state == "INCOMPLETE":
        spec.pop("fixed_elements_status")
        authorize(spec)
    if state == "INFEASIBLE":
        for r in spec["geometry"]["zoning"]["brief"]["building"]["rooms"]:
            r["area"] = {"unit": "m2", "min": 9, "max": 9}
        approve_source(spec)
    if state == "INVALID_INPUT":
        spec["schema_version"] = 9
    if state == "UNSUPPORTED":
        spec["parameters"]["grid_step"] = 0.01
        authorize(spec)
    if state == "SEARCH_EXHAUSTED":
        spec["parameters"]["max_steps"] = 1
    source = tmp_path / "input.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    before = source.read_bytes()
    args = ["design", "floorplan", "generate", str(source)]
    assert main(args) == code
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out)["status"] == state
    assert main(args) == code and capsys.readouterr().out == output.out
    assert source.read_bytes() == before and list(tmp_path.iterdir()) == [source]


def test_cli_count_override_and_exclusive_file_output(tmp_path, capsys):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(alternatives_spec()))
    target = tmp_path / "new/report.json"
    args = [
        "design",
        "floorplan",
        "generate",
        str(source),
        "--candidates",
        "1",
        "--out",
        str(target),
    ]
    assert main(args) == 0
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == json.loads(target.read_text())
    assert len(json.loads(stdout)["candidates"]) == 1
    before = target.read_bytes()
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"
    assert before == target.read_bytes()
    original = source.read_bytes()
    assert main(["design", "floorplan", "generate", str(source), "--out", str(source)]) == 2
    capsys.readouterr()
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "text", ["{bad", '{"schema_version":1,"schema_version":2}', '{"schema_version":NaN}']
)
def test_cli_parse_errors(text, tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text(text)
    assert main(["design", "floorplan", "generate", str(source)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"
