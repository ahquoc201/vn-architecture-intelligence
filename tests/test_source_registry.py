from pathlib import Path

from vnai.source_registry import load_registry, validate_registry


ROOT = Path(__file__).resolve().parents[1]


def test_registry_structure():
    data = load_registry(ROOT / "sources" / "bibliography.yaml")
    assert len(data["sources"]) >= 10
    assert validate_registry(data) == []


def test_no_executable_rules_are_misrepresented():
    data = load_registry(ROOT / "sources" / "bibliography.yaml")
    assert all(s["rule_authority"] == "none" for s in data["sources"])


def test_duplicate_source_rejected():
    data = load_registry(ROOT / "sources" / "bibliography.yaml")
    data["sources"].append(dict(data["sources"][0]))
    assert any("duplicate id" in error for error in validate_registry(data))


def test_source_approval_guard():
    data = load_registry(ROOT / "sources" / "bibliography.yaml")
    data["sources"][0]["rule_authority"] = "approved"
    assert any("no approved rules" in error for error in validate_registry(data))
