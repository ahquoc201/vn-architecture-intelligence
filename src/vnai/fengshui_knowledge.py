"""Validate a non-executable traditional-knowledge research queue.

This module enforces *research* integrity and fail-closed safety flags. It does not
verify historical texts, interpret a school, predict outcomes, or approve CAD edits.
"""

from collections import defaultdict
from pathlib import Path

import yaml

from vnai.source_registry import load_registry

EDITION_KEYS = {
    "id", "source_id", "school", "comparison_group", "edition_label", "catalog_kind",
    "catalog_url", "year_claimed", "publisher_claimed", "translator_claimed",
    "pages_claimed", "identifier_claimed", "metadata_claim_status", "full_text_reviewed",
    "page_level_rules_verified", "expert_reviewed", "rights_clearance", "notes",
}
TERM_KEYS = {
    "id", "label_vi", "label_zh", "school", "source_ids", "working_definition",
    "ambiguity", "verified_from_primary_text", "allowed_use",
}
RULE_KEYS = {
    "id", "school", "topic", "source_ids", "evidence_record_ids", "source_locator",
    "review_status", "interpretation", "unresolved_inputs", "oracle_cases",
    "full_text_reviewed", "expert_approved", "executable", "cad_writes_permitted",
}
VALID_SCHOOLS = {"bat_trach", "duong_trach_tam_yeu"}
VALID_CATALOG_KINDS = {"national_library_mirror", "publisher_catalog", "retailer_listing"}


def load_yaml_mapping(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        doc = yaml.safe_load(stream)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return doc


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _fields(item: dict, expected: set[str], prefix: str, issues: list[str]) -> None:
    for key in sorted(expected - item.keys()):
        issues.append(f"{prefix}: missing {key}")
    for key in sorted(item.keys() - expected):
        issues.append(f"{prefix}: unexpected {key} (unreviewed executable data prohibited)")


def _id_list(value: object, prefix: str, issues: list[str]) -> list[str]:
    if not isinstance(value, list) or not value or not all(_nonblank(x) for x in value):
        issues.append(f"{prefix}: must be nonempty list of string IDs")
        return []
    if len(value) != len(set(value)):
        issues.append(f"{prefix}: duplicate IDs")
    return value


def _header(doc: dict, field: str, purpose: str, issues: list[str]) -> list:
    if doc.get("schema_version") != 1 or doc.get("purpose") != purpose:
        issues.append(f"{field}: invalid schema_version or purpose")
    if not isinstance(doc.get(field), list) or not doc[field]:
        issues.append(f"{field}: nonempty list required")
        return []
    return doc[field]


def validate_fengshui_corpus(
    editions: dict, terms: dict, rules: dict, registry: dict
) -> list[str]:
    """Integrity checks only. A PASS never means a traditional rule is approved."""
    issues: list[str] = []
    source_ids = {
        src.get("id") for src in registry.get("sources", [])
        if isinstance(src, dict) and _nonblank(src.get("id"))
    }
    edition_rows = _header(
        editions, "records", "bibliographic_claim_comparison_not_text_verification", issues
    )
    term_rows = _header(terms, "terms", "research_working_glossary_not_doctrinal_definitions", issues)
    rule_rows = _header(rules, "rules", "unanswered_research_questions_only", issues)
    if not _nonblank(editions.get("reviewed_at")):
        issues.append("editions: reviewed_at must be a date string")
    if not _nonblank(editions.get("notes")):
        issues.append("editions: notes required")
    edition_ids: set[str] = set()
    edition_sources: dict[str, str] = {}
    edition_schools: dict[str, str] = {}
    for n, row in enumerate(edition_rows):
        prefix = f"records[{n}]"
        if not isinstance(row, dict):
            issues.append(f"{prefix}: mapping required")
            continue
        _fields(row, EDITION_KEYS, prefix, issues)
        key = row.get("id")
        if not _nonblank(key) or key in edition_ids:
            issues.append(f"{prefix}: missing/duplicate id")
        else:
            edition_ids.add(key)
            edition_sources[key] = row.get("source_id")
            edition_schools[key] = row.get("school")
        if not _nonblank(row.get("source_id")) or row["source_id"] not in source_ids:
            issues.append(f"{prefix}: missing source_id in registry")
        expected_source = {
            "bat_trach": "FENG-BAT-TRACH-MINH-KINH",
            "duong_trach_tam_yeu": "FENG-DUONG-TRACH-TAM-YEU",
        }.get(row.get("school") if _nonblank(row.get("school")) else "")
        if expected_source and row.get("source_id") != expected_source:
            issues.append(f"{prefix}: source_id does not match school")
        if not _nonblank(row.get("school")) or row["school"] not in VALID_SCHOOLS:
            issues.append(f"{prefix}: unsupported school")
        for field in ("comparison_group", "edition_label", "catalog_url", "publisher_claimed", "notes"):
            if not _nonblank(row.get(field)):
                issues.append(f"{prefix}: {field} required")
        if _nonblank(row.get("catalog_url")) and not row["catalog_url"].startswith("https://"):
            issues.append(f"{prefix}: catalog_url must be HTTPS")
        if not _nonblank(row.get("catalog_kind")) or row["catalog_kind"] not in VALID_CATALOG_KINDS:
            issues.append(f"{prefix}: invalid catalog_kind")
        if row.get("metadata_claim_status") != "catalog_page_checked":
            issues.append(f"{prefix}: metadata claim status must describe checked catalog page")
        for field in ("year_claimed", "pages_claimed"):
            value = row.get(field)
            if type(value) is not int or value <= 0:
                issues.append(f"{prefix}: {field} must be positive integer")
        for field in ("translator_claimed", "identifier_claimed"):
            value = row.get(field)
            if value is not None and not _nonblank(value):
                issues.append(f"{prefix}: {field} must be null or nonblank string")
        for field in ("full_text_reviewed", "page_level_rules_verified", "expert_reviewed"):
            if row.get(field) is not False:
                issues.append(f"{prefix}: {field} must be false in this research batch")
        if row.get("rights_clearance") != "not_evaluated":
            issues.append(f"{prefix}: rights_clearance must be not_evaluated")

    glossary_ids: set[str] = set()
    for n, row in enumerate(term_rows):
        prefix = f"terms[{n}]"
        if not isinstance(row, dict):
            issues.append(f"{prefix}: mapping required")
            continue
        _fields(row, TERM_KEYS, prefix, issues)
        key = row.get("id")
        if not _nonblank(key) or key in glossary_ids:
            issues.append(f"{prefix}: missing/duplicate id")
        else:
            glossary_ids.add(key)
        if not _nonblank(row.get("school")) or row["school"] not in VALID_SCHOOLS | {"shared", "geometry_only"}:
            issues.append(f"{prefix}: invalid school")
        for field in ("label_vi", "working_definition", "ambiguity"):
            if not _nonblank(row.get(field)):
                issues.append(f"{prefix}: {field} required")
        label_zh = row.get("label_zh")
        if label_zh is not None and not _nonblank(label_zh):
            issues.append(f"{prefix}: label_zh must be null or nonblank")
        for ref in _id_list(row.get("source_ids"), f"{prefix}.source_ids", issues):
            if ref not in source_ids:
                issues.append(f"{prefix}: unknown source {ref}")
        if row.get("verified_from_primary_text") is not False:
            issues.append(f"{prefix}: primary-text verified prohibited without review")
        if row.get("allowed_use") != "input_clarification_only":
            issues.append(f"{prefix}: allowed_use must be input_clarification_only")

    rule_ids: set[str] = set()
    for n, row in enumerate(rule_rows):
        prefix = f"rules[{n}]"
        if not isinstance(row, dict):
            issues.append(f"{prefix}: mapping required")
            continue
        _fields(row, RULE_KEYS, prefix, issues)
        key = row.get("id")
        if not _nonblank(key) or key in rule_ids:
            issues.append(f"{prefix}: missing/duplicate id")
        else:
            rule_ids.add(key)
        if (not _nonblank(row.get("school")) or row["school"] not in VALID_SCHOOLS
                or not _nonblank(row.get("topic"))):
            issues.append(f"{prefix}: unsupported school or missing topic")
        refs = _id_list(row.get("source_ids"), f"{prefix}.source_ids", issues)
        for ref in refs:
            if ref not in source_ids:
                issues.append(f"{prefix}: unknown source {ref}")
        record_ids = _id_list(row.get("evidence_record_ids"), f"{prefix}.evidence_record_ids", issues)
        for record_id in record_ids:
            if record_id not in edition_ids:
                issues.append(f"{prefix}: unknown evidence record {record_id}")
            elif edition_sources.get(record_id) not in refs:
                issues.append(f"{prefix}: evidence {record_id} not linked to a rule source")
            elif edition_schools.get(record_id) != row.get("school"):
                issues.append(f"{prefix}: evidence {record_id} does not match rule school")
        if row.get("review_status") != "candidate":
            issues.append(f"{prefix}: review_status must be candidate")
        if row.get("source_locator") is not None or row.get("interpretation") is not None:
            issues.append(f"{prefix}: unverified rule cannot contain locator/interpretation")
        missing = row.get("unresolved_inputs")
        if not isinstance(missing, list) or not missing or not all(_nonblank(x) for x in missing):
            issues.append(f"{prefix}: unresolved_inputs must be nonempty string list")
        if row.get("oracle_cases") != []:
            issues.append(f"{prefix}: no oracle cases authorized until primary review")
        for field in ("full_text_reviewed", "expert_approved", "executable", "cad_writes_permitted"):
            if row.get(field) is not False:
                issues.append(f"{prefix}: {field} must be false")
    return issues


def report_fengshui_corpus(editions: dict, terms: dict, rules: dict, registry: dict) -> dict:
    """Produce a non-interpretive, provenance-only queue report; fail on invalid input."""
    issues = validate_fengshui_corpus(editions, terms, rules, registry)
    if issues:
        raise ValueError("Invalid research corpus: " + "; ".join(issues))
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in editions["records"]:
        groups[record["comparison_group"]].append(record)
    conflicts = [
        {
            "comparison_group": group,
            "catalog_records": [row["id"] for row in rows],
            "page_claims": sorted({row["pages_claimed"] for row in rows}),
            "status": "CATALOG_CLAIMS_DIFFER_NOT_RESOLVED",
        }
        for group, rows in sorted(groups.items())
        if len({row["pages_claimed"] for row in rows}) > 1
    ]
    return {
        "status": "NEEDS_SOURCE_REVIEW",
        "evidence_records": len(editions["records"]),
        "working_terms": len(terms["terms"]),
        "rule_questions": len(rules["rules"]),
        "executable_rules": 0,
        "edition_page_claim_conflicts": conflicts,
        "rules": [
            {"id": row["id"], "school": row["school"], "status": "NEEDS_SOURCE_REVIEW"}
            for row in rules["rules"]
        ],
        "fengshui_predictions_permitted": False,
        "technical_standards": "NOT_EVALUATED",
        "cad_writes_permitted": False,
        "note": "Catalog metadata and questions only; no primary-text or expert-vetted formulas.",
    }


def validate_repo_fengshui(
    editions_path: str | Path,
    terms_path: str | Path,
    rules_path: str | Path,
    sources_path: str | Path,
) -> list[str]:
    return validate_fengshui_corpus(
        load_yaml_mapping(editions_path),
        load_yaml_mapping(terms_path),
        load_yaml_mapping(rules_path),
        load_registry(sources_path),
    )


def report_repo_fengshui(
    editions_path: str | Path,
    terms_path: str | Path,
    rules_path: str | Path,
    sources_path: str | Path,
) -> dict:
    return report_fengshui_corpus(
        load_yaml_mapping(editions_path),
        load_yaml_mapping(terms_path),
        load_yaml_mapping(rules_path),
        load_registry(sources_path),
    )
