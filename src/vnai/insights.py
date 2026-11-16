"""Validate research insights as sourced observations, never as executable standards."""

from pathlib import Path

import yaml

from vnai.source_registry import load_registry

ALLOWED_DOMAINS = {"cultural_case_study", "architectural_advisory", "standard_scope_reference"}
ALLOWED_CONCLUSIONS = {"documented_observation", "author_recommendation", "official_scope"}
ALLOWED_USES = {"advisory_only", "reference_only"}
ALLOWED_STATUSES = {"candidate", "source_checked"}


def load_insights(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError("Insight corpus must be a mapping")
    return result


def validate_insights(data: dict, registry: dict) -> list[str]:
    """Check provenance and safety gates; does not prove that a source is factually true."""
    issues: list[str] = []
    if data.get("schema_version") != 1 or not isinstance(data.get("insights"), list):
        return ["Invalid insight corpus schema_version or insights array"]
    source_map = {src["id"]: src for src in registry.get("sources", []) if isinstance(src, dict)}
    seen: set[str] = set()
    for idx, item in enumerate(data["insights"]):
        label = f"insights[{idx}]"
        if not isinstance(item, dict):
            issues.append(f"{label}: must be a mapping")
            continue
        insight_id = item.get("id")
        if not isinstance(insight_id, str) or not insight_id.strip():
            issues.append(f"{label}: id required")
        elif insight_id in seen:
            issues.append(f"{label}: duplicate id {insight_id}")
        else:
            seen.add(insight_id)
        for key in ("title", "source_locator", "statement", "design_implication", "applicability", "limitations"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                issues.append(f"{label}: {key} required")
        if item.get("domain") not in ALLOWED_DOMAINS:
            issues.append(f"{label}: invalid domain")
        if item.get("conclusion_type") not in ALLOWED_CONCLUSIONS:
            issues.append(f"{label}: invalid conclusion_type")
        if item.get("allowed_use") not in ALLOWED_USES:
            issues.append(f"{label}: invalid allowed_use")
        if item.get("verification_status") not in ALLOWED_STATUSES:
            issues.append(f"{label}: invalid verification_status")
        if item.get("expert_approved") is not False or item.get("executable") is not False:
            issues.append(f"{label}: research observations cannot be marked approved/executable")
        if "rule_authority" in item or "predicate" in item:
            issues.append(f"{label}: no rule predicate/authority allowed in research observations")
        refs = item.get("source_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(s, str) for s in refs):
            issues.append(f"{label}: source_ids must be nonempty string list")
            continue
        if len(refs) != len(set(refs)):
            issues.append(f"{label}: duplicate source reference")
        for ref in refs:
            if ref not in source_map:
                issues.append(f"{label}: source {ref} not found in bibliography")
            elif item.get("verification_status") == "source_checked" and source_map[ref].get("evidence_level") not in {
                "public_article_reviewed", "official_scope_checked"
            }:
                issues.append(f"{label}: source {ref} has insufficient direct-content evidence")
        if item.get("domain") == "standard_scope_reference" and item.get("allowed_use") != "reference_only":
            issues.append(f"{label}: standards must be reference_only")
    return issues


def validate_repo_insights(insights_path: str | Path, sources_path: str | Path) -> list[str]:
    return validate_insights(load_insights(insights_path), load_registry(sources_path))
