"""Non-executable source provenance and anti-promotion safety guards."""

from copy import deepcopy
from pathlib import Path

import pytest

from vnai.cli import main
from vnai.fengshui_knowledge import (
    load_yaml_mapping,
    report_fengshui_corpus,
    validate_fengshui_corpus,
)
from vnai.source_registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
FENG = ROOT / "knowledge" / "fengshui"


@pytest.fixture
def docs():
    return (
        load_yaml_mapping(FENG / "edition-evidence.yaml"),
        load_yaml_mapping(FENG / "terminology.yaml"),
        load_yaml_mapping(FENG / "rule-candidates.yaml"),
        load_registry(ROOT / "sources" / "bibliography.yaml"),
    )


def validate(docs):
    return validate_fengshui_corpus(*docs)


def test_repo_corpus_valid(docs):
    assert validate(docs) == []


def test_report_non_executable(docs):
    report = report_fengshui_corpus(*docs)
    assert report["status"] == "NEEDS_SOURCE_REVIEW"
    assert report["evidence_records"] == 6
    assert report["working_terms"] == 8
    assert report["rule_questions"] == 4
    assert report["executable_rules"] == 0
    assert report["fengshui_predictions_permitted"] is False
    assert report["cad_writes_permitted"] is False
    assert report["technical_standards"] == "NOT_EVALUATED"
    assert {r["status"] for r in report["rules"]} == {"NEEDS_SOURCE_REVIEW"}


def test_page_discrepancy_not_silently_resolved(docs):
    conflicts = report_fengshui_corpus(*docs)["edition_page_claim_conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["page_claims"] == [670, 696]
    assert conflicts[0]["comparison_group"] == "DTT-2016-HONG-DUC-8935088548224"


@pytest.mark.parametrize("field", ["full_text_reviewed", "page_level_rules_verified", "expert_reviewed"])
def test_edition_cannot_be_approved_without_review(docs, field):
    changed = deepcopy(docs)
    changed[0]["records"][0][field] = True
    assert field in " ".join(validate(changed))


@pytest.mark.parametrize("field", ["full_text_reviewed", "expert_approved", "executable", "cad_writes_permitted"])
def test_rule_cannot_be_approved_without_review(docs, field):
    changed = deepcopy(docs)
    changed[2]["rules"][0][field] = True
    assert field in " ".join(validate(changed))


@pytest.mark.parametrize("field", ["source_locator", "interpretation"])
def test_rule_cannot_sneak_in_unsupported_content(docs, field):
    changed = deepcopy(docs)
    changed[2]["rules"][0][field] = "not a verified quotation"
    assert "unverified rule" in " ".join(validate(changed))


@pytest.mark.parametrize("field", ["formula", "predicate", "recommendation", "auspicious_direction"])
def test_reject_hidden_rule_fields(docs, field):
    changed = deepcopy(docs)
    changed[2]["rules"][0][field] = "unsafe"
    assert f"unexpected {field}" in " ".join(validate(changed))


@pytest.mark.parametrize("doc_index,field", [(0, "records"), (1, "terms"), (2, "rules")])
def test_reject_empty_corpi(docs, doc_index, field):
    changed = deepcopy(docs)
    changed[doc_index][field] = []
    assert "nonempty list" in " ".join(validate(changed))


@pytest.mark.parametrize("doc_index,field", [(0, "records"), (1, "terms"), (2, "rules")])
def test_reject_duplicate_ids(docs, doc_index, field):
    changed = deepcopy(docs)
    changed[doc_index][field].append(deepcopy(changed[doc_index][field][0]))
    assert "duplicate id" in " ".join(validate(changed))


def test_reject_unknown_edition_source(docs):
    changed = deepcopy(docs)
    changed[0]["records"][0]["source_id"] = "NOT-IN-REGISTRY"
    assert "missing source_id" in " ".join(validate(changed))


def test_reject_unknown_term_source(docs):
    changed = deepcopy(docs)
    changed[1]["terms"][0]["source_ids"] = ["BAD-REF"]
    assert "unknown source" in " ".join(validate(changed))


def test_reject_unknown_rule_source(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["source_ids"] = ["BAD-REF"]
    assert "unknown source" in " ".join(validate(changed))


def test_reject_unknown_evidence_record(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["evidence_record_ids"] = ["BAD-EDITION"]
    assert "unknown evidence" in " ".join(validate(changed))


def test_reject_crossed_book_evidence(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["evidence_record_ids"] = ["DTT-HONGBANG-2013"]
    assert "not linked to a rule source" in " ".join(validate(changed))


def test_reject_duplicate_source_references(docs):
    changed = deepcopy(docs)
    changed[1]["terms"][0]["source_ids"] = ["FENG-BAT-TRACH-MINH-KINH"] * 2
    assert "duplicate IDs" in " ".join(validate(changed))


def test_reject_non_https_catalog(docs):
    changed = deepcopy(docs)
    changed[0]["records"][0]["catalog_url"] = "http://example.org"
    assert "must be HTTPS" in " ".join(validate(changed))


def test_reject_invalid_page_count(docs):
    changed = deepcopy(docs)
    changed[0]["records"][0]["pages_claimed"] = True
    assert "positive integer" in " ".join(validate(changed))


def test_reject_glossary_approval(docs):
    changed = deepcopy(docs)
    changed[1]["terms"][0]["verified_from_primary_text"] = True
    assert "primary-text verified prohibited" in " ".join(validate(changed))


def test_reject_approved_rule_status(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["review_status"] = "expert_approved"
    assert "must be candidate" in " ".join(validate(changed))


def test_reject_oracles_without_source(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["oracle_cases"] = [{"input": "?", "output": "good"}]
    assert "no oracle cases authorized" in " ".join(validate(changed))


def test_report_rejects_tampering(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["cad_writes_permitted"] = True
    with pytest.raises(ValueError, match="Invalid research corpus"):
        report_fengshui_corpus(*changed)


def test_cli_validate_success(capsys):
    assert main(["fengshui", "knowledge", "validate"]) == 0
    assert "NO rules approved" in capsys.readouterr().out


def test_cli_report_json(capsys):
    import json

    assert main(["fengshui", "knowledge", "report"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["cad_writes_permitted"] is False


def test_cli_report_file(tmp_path):
    import json

    dest = tmp_path / "research" / "report.json"
    assert main(["fengshui", "knowledge", "report", "--out", str(dest)]) == 0
    assert json.loads(dest.read_text(encoding="utf-8"))["status"] == "NEEDS_SOURCE_REVIEW"


def test_cli_fails_unsafe_data(tmp_path, capsys):
    import yaml

    doc = load_yaml_mapping(FENG / "rule-candidates.yaml")
    doc["rules"][0]["executable"] = True
    target = tmp_path / "tampered.yaml"
    target.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    rc = main(["fengshui", "knowledge", "validate", "--rules", str(target)])
    assert rc == 1
    assert "must be false" in capsys.readouterr().err


def test_cli_fails_missing_file(tmp_path, capsys):
    rc = main(["fengshui", "knowledge", "validate", "--rules", str(tmp_path / "absent.yaml")])
    assert rc == 2
    assert "ERROR" in capsys.readouterr().err


def test_ensure_missing_fields_not_silently_accepted(docs):
    changed = deepcopy(docs)
    del changed[2]["rules"][0]["cad_writes_permitted"]
    assert "missing cad_writes_permitted" in " ".join(validate(changed))


def test_enforce_no_source_drift(docs):
    changed = deepcopy(docs)
    changed[0]["records"][0]["id"] = "DTT-HONGBANG-2013"
    assert "duplicate id" in " ".join(validate(changed))


@pytest.mark.parametrize("new_value", [False, 0, [], {}, None])
def test_no_type_confusion_with_edition_source(docs, new_value):
    changed = deepcopy(docs)
    changed[0]["records"][0]["source_id"] = new_value
    assert validate(changed)


def test_reject_school_source_mismatch(docs):
    changed = deepcopy(docs)
    changed[0]["records"][0]["school"] = "duong_trach_tam_yeu"
    assert "source_id does not match school" in " ".join(validate(changed))


def test_reject_rule_evidence_school_mismatch(docs):
    changed = deepcopy(docs)
    changed[2]["rules"][0]["source_ids"].append("FENG-DUONG-TRACH-TAM-YEU")
    changed[2]["rules"][0]["evidence_record_ids"] = ["DTT-HONGBANG-2013"]
    assert "does not match rule school" in " ".join(validate(changed))
