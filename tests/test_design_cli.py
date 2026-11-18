"""JSON output and exit contracts; CLI never changes the brief."""

import json

import pytest

from design_fixtures import ROOT, incomplete_brief, valid_brief
from vnai.cli import main


@pytest.mark.parametrize("command", [["brief", "validate"], ["brief", "report"], ["program", "build"]])
@pytest.mark.parametrize("state,code", [("valid", 0), ("incomplete", 3), ("invalid", 1)])
def test_cli_status_and_stable_output(tmp_path, capsys, command, state, code):
    doc = valid_brief() if state == "valid" else incomplete_brief()
    if state == "invalid":
        doc["schema_version"] = 99
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    before = path.read_bytes()
    assert main(["design", *command, str(path)]) == code
    first = capsys.readouterr()
    assert json.loads(first.out)["status"] == state.upper()
    assert first.err == ""
    assert main(["design", *command, str(path)]) == code
    assert capsys.readouterr().out == first.out
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["brief.json"]


@pytest.mark.parametrize("content", ["{bad", '{"schema_version":1,"schema_version":2}',
                                     '{"schema_version":NaN}', '{"schema_version":1e999}'])
def test_input_error_is_json(tmp_path, capsys, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    assert main(["design", "brief", "validate", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_ERROR"


def test_missing_input_error_json(tmp_path, capsys):
    assert main(["design", "program", "build", str(tmp_path / "absent.json")]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID"


def test_existing_geometry_command_still_works(capsys):
    assert main(["review", str(ROOT / "examples/townhouse_sample.json")]) == 0
    assert json.loads(capsys.readouterr().out)["geometry"]["site_area_m2"] == 80


def test_unicode_brief_works_on_windows_legacy_stdout(tmp_path):
    import os
    import subprocess
    import sys

    doc = valid_brief()
    name = "Nh\u00e0 ph\u1ed1 - ph\u00f2ng th\u1edd"
    doc["project"]["name"] = name
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "vnai", "design", "brief", "report", str(path)],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"}, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["input_brief"]["project"]["name"] == name
