"""Actual integrated CLI boundaries, output preservation and recomputed previews."""

from copy import deepcopy
import json
import xml.etree.ElementTree as ET
from vnai.cli import main
from test_integrated_design import spec


def test_all_integrated_cli_actions_and_exclusive_outputs(tmp_path, capsys):
    source = tmp_path / "input.json"
    value = spec()
    source.write_text(json.dumps(value))
    original = source.read_bytes()
    report_path = tmp_path / "refined.json"
    assert main(["design", "integrated", "refine", str(source), "--out", str(report_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["integrated_status"] == "REFINED"
    assert source.read_bytes() == original
    assert main(["design", "integrated", "validate", str(report_path)]) == 0
    assert json.loads(capsys.readouterr().out) == report
    md = tmp_path / "report.md"
    assert main(["design", "integrated", "report", str(report_path), "--markdown", str(md)]) == 0
    capsys.readouterr()
    assert "CAD writes: false" in md.read_text()
    svg = tmp_path / "comparison.svg"
    assert main(["design", "integrated", "preview", str(report_path), "--out", str(svg)]) == 0
    capsys.readouterr()
    ET.fromstring(svg.read_text())
    assert report["candidates"][0]["revision_id"] in svg.read_text()
    preserved = svg.read_bytes()
    assert main(["design", "integrated", "preview", str(report_path), "--out", str(svg)]) == 2
    capsys.readouterr()
    assert svg.read_bytes() == preserved
    # Generation with the explicitly supplied feasible opening variant still enumerates room geometry.
    generated = deepcopy(value)
    op = generated["opening_specification"]
    alt = generated["refinements"][0]["passage_alternatives"][0]
    next(r for r in op["openings"] if r["id"] == "ENTRANCE")["offset"] = 0.8
    for key in ["passages", "clearance_regions"]:
        updates = {r["id"]: r for r in alt.get(key, [])}
        op[key] = [deepcopy(updates.get(r["id"], r)) for r in op[key]]
    generated["refinements"] = []
    source2 = tmp_path / "feasible.json"
    source2.write_text(json.dumps(generated))
    assert main(["design", "integrated", "generate", str(source2)]) == 0
    assert json.loads(capsys.readouterr().out)["integrated_status"] == "GENERATED"


def test_malformed_input_creates_no_requested_output(tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text('{"x":NaN}')
    target = tmp_path / "bad.svg"
    assert main(["design", "integrated", "preview", str(source), "--out", str(target)]) == 2
    capsys.readouterr()
    assert not target.exists()
