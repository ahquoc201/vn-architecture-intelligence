"""Provenance validation for the source registry, not truth verification."""

from pathlib import Path

import yaml

ALLOWED_EVIDENCE = {
    "candidate_unverified_edition",
    "metadata_verified",
    "toc_checked",
    "public_article_sampled",
    "public_article_reviewed",
    "official_scope_checked",
}
ALLOWED_SELECTION = {
    "core_candidate", "reference_candidate", "standards_reference", "pending_full_text"
}


def load_registry(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("Registry should be a mapping")
    return data


def validate_registry(data: dict) -> list[str]:
    """Return errors (empty list means structurally valid, not expertly approved)."""
    issues: list[str] = []
    sources = data.get("sources")
    if data.get("schema_version") != 1 or not isinstance(sources, list):
        return ["Invalid schema_version or sources array"]
    seen: set[str] = set()
    for idx, item in enumerate(sources):
        label = f"sources[{idx}]"
        if not isinstance(item, dict):
            issues.append(f"{label}: must be object")
            continue
        sid = item.get("id")
        if not isinstance(sid, str) or not sid.strip():
            issues.append(f"{label}: id required")
        elif sid in seen:
            issues.append(f"{label}: duplicate id {sid}")
        else:
            seen.add(sid)
        for key in ("title", "kind", "evidence_level", "selection", "rights", "notes"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                issues.append(f"{label}: {key} required")
        if item.get("evidence_level") not in ALLOWED_EVIDENCE:
            issues.append(f"{label}: evidence_level unknown")
        if item.get("selection") not in ALLOWED_SELECTION:
            issues.append(f"{label}: selection unknown")
        if item.get("rule_authority") != "none":
            issues.append(f"{label}: no approved rules exist in version 0.1.0")
        if not isinstance(item.get("creators"), list):
            issues.append(f"{label}: creators must be array")
        if not isinstance(item.get("domains"), list) or not item["domains"]:
            issues.append(f"{label}: domains must be nonempty array")
        url = item.get("url")
        if url is not None and (
            not isinstance(url, str) or not url.startswith("https://")
        ):
            issues.append(f"{label}: source url must be HTTPS or null")
        if url is None and item.get("evidence_level") != "candidate_unverified_edition":
            issues.append(f"{label}: verified source must have URL")
    return issues
