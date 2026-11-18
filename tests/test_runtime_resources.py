"""Resource lookup cannot accidentally depend on the caller's cwd."""

from pathlib import Path

from batch005_fixtures import ROOT
from vnai import resources


def test_checkout_data_path_is_canonical():
    assert resources.data_path("knowledge/architecture/zoning.schema.json") == (
        ROOT / "knowledge/architecture/zoning.schema.json"
    )


def test_installed_data_falls_back_to_package_resource(monkeypatch, tmp_path):
    package = tmp_path / "site-packages" / "vnai"
    expected = package / "_data" / "knowledge/architecture/zoning.schema.json"
    expected.parent.mkdir(parents=True)
    expected.write_text("{}")
    monkeypatch.setattr(resources, "__file__", str(package / "resources.py"))
    monkeypatch.setattr(resources, "files", lambda name: package)
    monkeypatch.chdir(tmp_path)
    assert resources.data_path("knowledge/architecture/zoning.schema.json") == expected
    assert (
        Path(resources.data_path("knowledge/architecture/zoning.schema.json")).read_text() == "{}"
    )
