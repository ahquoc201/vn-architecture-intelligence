"""Versioned exact JSON/SVG evidence, separately verified on Python 3.11/3.14."""

from pathlib import Path
import json
import pytest
from vnai.contracts import new_report, schema_check
from vnai.integrated_design import integrated_design
from integrated_fixtures import CASES, projection

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", CASES)
def test_versioned_integrated_golden(name, monkeypatch):
    monkeypatch.setattr("vnai.contracts.__version__", "0.1.13")
    monkeypatch.setattr("vnai.design_brief.__version__", "0.1.13")
    path = ROOT / "examples/batch007b4" / (name + ".json")
    raw = path.read_bytes()
    result = integrated_design(json.loads(raw))
    expected = json.loads(
        (ROOT / "tests/golden/batch007b4-v0.1.13" / (name + ".json")).read_text(encoding="utf-8")
    )
    # JSON lists preserve the expected canonical nested sequence representation.
    assert json.loads(json.dumps(projection(result))) == expected
    check = new_report("schema-check")
    assert schema_check(result, "integrated-design-result.schema.json", check), check
    assert raw == path.read_bytes() and not result["cad_writes_permitted"]
