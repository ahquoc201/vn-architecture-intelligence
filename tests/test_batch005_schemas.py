"""Published schema validity and canonical references."""

import json
from jsonschema import Draft202012Validator
import pytest
from batch005_fixtures import ROOT


@pytest.mark.parametrize("name", ["zoning", "geometry"])
def test_published_schema_valid(name):
    doc = json.loads((ROOT / "knowledge/architecture" / (name + ".schema.json")).read_text())
    Draft202012Validator.check_schema(doc)
