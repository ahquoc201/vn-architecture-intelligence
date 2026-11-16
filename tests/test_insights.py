"""Protect provenance, attribution and non-executable research boundaries."""

from copy import deepcopy
from pathlib import Path

from vnai.insights import load_insights, validate_insights
from vnai.source_registry import load_registry

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    return (load_insights(ROOT / "knowledge/insights.yaml"),
            load_registry(ROOT / "sources/bibliography.yaml"))


def test_corpus_validates():
    insights, sources = fixtures()
    assert len(insights["insights"]) == 5
    assert validate_insights(insights, sources) == []


def test_unknown_source_is_rejected():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"][0]["source_ids"] = ["DOES-NOT-EXIST"]
    assert any("not found" in x for x in validate_insights(altered, sources))


def test_unreviewed_book_cannot_back_checked_insight():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"][0]["source_ids"] = ["FENG-NTD-2011"]
    assert any("insufficient" in x for x in validate_insights(altered, sources))


def test_rejects_executable_feng_shui_rule():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"][0]["executable"] = True
    assert any("cannot be marked approved/executable" in x for x in validate_insights(altered, sources))


def test_rejects_expert_approval_without_process():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"][0]["expert_approved"] = True
    assert any("cannot be marked approved/executable" in x for x in validate_insights(altered, sources))


def test_rejects_technical_rules_as_advice():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"][4]["allowed_use"] = "advisory_only"
    assert any("must be reference_only" in x for x in validate_insights(altered, sources))


def test_rejects_missing_locator():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"][0]["source_locator"] = ""
    assert any("source_locator required" in x for x in validate_insights(altered, sources))


def test_rejects_duplicate_identifiers():
    insights, sources = fixtures()
    altered = deepcopy(insights)
    altered["insights"].append(deepcopy(altered["insights"][0]))
    assert any("duplicate id" in x for x in validate_insights(altered, sources))


def test_no_insight_has_executable_authority():
    insights, _ = fixtures()
    assert all(i["executable"] is False and i["expert_approved"] is False for i in insights["insights"])
