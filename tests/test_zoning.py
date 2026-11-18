"""Floor decisions, provenance, explicit review transitions and stale approvals."""

from copy import deepcopy

import pytest

from batch005_fixtures import fixture, resign_zoning
from vnai.zoning import create_zoning_proposal, validate_zoning
from design_fixtures import incomplete_brief


def codes(report, bucket="errors"):
    return {item["code"] for item in report[bucket]}


def test_unresolved_source_is_not_silently_zoned():
    brief = incomplete_brief()
    original = deepcopy(brief)
    doc = create_zoning_proposal(brief, "PROPOSAL")
    report = validate_zoning(doc)
    assert brief == original
    assert report["status"] == "INCOMPLETE"
    assert len(report["unassigned_room_ids"]) == 7
    assert all(a["floor_id"] is None and a["status"] == "proposed" for a in doc["assignments"])
    assert not report["architect_approved"] and not report["cad_writes_permitted"]


def test_valid_proposal_is_not_approval():
    report = validate_zoning(fixture("zoning-proposed"))
    assert not report["errors"]
    assert report["status"] == "INCOMPLETE"
    assert "ARCHITECT_APPROVAL_REQUIRED" in codes(report, "missing_information")


def test_explicit_approval_records_are_required_and_bound():
    doc = fixture("zoning-approved")
    assert validate_zoning(doc)["architect_approved"]
    doc["assignments"][0]["zone"] = "service"
    report = validate_zoning(doc)
    assert "STALE_APPROVAL" in codes(report)
    assert not report["architect_approved"]


def test_cannot_set_approved_flag_without_review_record():
    doc = fixture("zoning-proposed")
    doc["assignments"][0]["status"] = "approved"
    assert "MISSING_APPROVAL_RECORD" in codes(validate_zoning(doc))


@pytest.mark.parametrize("change", ["brief", "revision", "floors", "provenance"])
def test_approval_invalidated_by_context_changes(change):
    doc = fixture("zoning-approved")
    if change == "brief":
        doc["brief"]["project"]["architect_notes"] = "Changed after approval"
    elif change == "revision":
        doc["revision"] += 1
    elif change == "floors":
        doc["floors"][0]["elevation"] = {"value": 0, "unit": "m"}
    else:
        doc["assignments"][0]["provenance"] = "Changed"
    assert "STALE_APPROVAL" in codes(validate_zoning(doc))


def test_review_without_approval_stays_incomplete():
    doc = fixture("zoning-approved")
    doc["decisions"] = [e for e in doc["decisions"] if e["action"] == "reviewed"]
    for row in doc["assignments"]:
        row["status"] = "reviewed"
    assert validate_zoning(doc)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("state", ["rejected", "superseded"])
def test_terminal_decisions_do_not_assign_rooms(state):
    doc = fixture("zoning-approved")
    row = doc["assignments"][0]
    event = deepcopy(doc["decisions"][1])
    event["id"] = "TERMINAL"
    event["action"] = state
    event["record"]["recorded_at"] = "2026-11-18T00:02:00Z"
    doc["decisions"].append(event)
    row["status"] = state
    report = validate_zoning(doc)
    assert not report["errors"]
    assert row["room_id"] in report["unassigned_room_ids"]
    assert not report["architect_approved"]


def test_approval_transition_order_and_actor_role():
    doc = fixture("zoning-approved")
    doc["decisions"].pop(0)
    assert "APPROVAL_TRANSITION" in codes(validate_zoning(doc))
    doc = fixture("zoning-approved")
    doc["decisions"][0]["record"]["role"] = "agent"
    assert "SCHEMA" in codes(validate_zoning(doc))
    doc = fixture("zoning-approved")
    doc["decisions"][1]["record"]["recorded_at"] = "2026-11-17T00:00:00Z"
    assert "DECISION_ORDER" in codes(validate_zoning(doc))


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("floor_id", "UNKNOWN", "UNKNOWN_FLOOR"),
        ("requirement_id", "BAD", "ROOM_TRACEABILITY"),
        ("room_id", "BAD:1", "ROOM_TRACEABILITY"),
    ],
)
def test_bad_assignment_references(field, value, code):
    doc = fixture("zoning-proposed")
    doc["assignments"][0][field] = value
    assert code in codes(validate_zoning(doc))


def test_duplicate_active_assignments_and_identifiers():
    doc = fixture("zoning-proposed")
    copy = deepcopy(doc["assignments"][0])
    copy["id"] = "SECOND"
    doc["assignments"].append(copy)
    assert "ASSIGNMENT_CONFLICT" in codes(validate_zoning(doc))
    copy["id"] = doc["assignments"][0]["id"]
    assert "DUPLICATE_ID" in codes(validate_zoning(doc))


def test_cannot_override_confirmed_brief_floor():
    doc = fixture("zoning-proposed")
    doc["assignments"][0]["floor_id"] = "F2"
    assert "SOURCE_ASSIGNMENT_CONFLICT" in codes(validate_zoning(doc))


def test_hard_and_soft_floor_constraints():
    doc = fixture("zoning-proposed")
    doc["constraints"] = [
        {
            "id": "C1",
            "floor_id": "F2",
            "room_ids": ["BED:1"],
            "kind": "require",
            "requirement_id": "REQ-BED",
            "strength": "hard",
        }
    ]
    assert "FLOOR_CONSTRAINT_CONFLICT" in codes(validate_zoning(doc))
    doc["constraints"][0]["strength"] = "soft"
    report = validate_zoning(doc)
    assert "FLOOR_CONSTRAINT_CONFLICT" not in codes(report)
    assert "FLOOR_CONSTRAINT_CONFLICT" in codes(report, "warnings")


def test_constraints_conflict_even_without_assignment():
    doc = fixture("zoning-unresolved")
    doc["floors"] = [{"id": "F1"}, {"id": "F2"}, {"id": "F3"}]
    doc["constraints"] = [
        {
            "id": "C1",
            "floor_id": "F1",
            "room_ids": ["BED:1"],
            "kind": "require",
            "requirement_id": "REQ-BED",
            "strength": "hard",
        },
        {
            "id": "C2",
            "floor_id": "F2",
            "room_ids": ["BED:1"],
            "kind": "require",
            "requirement_id": "REQ-BED",
            "strength": "hard",
        },
    ]
    assert "CONTRADICTORY_FLOOR_CONSTRAINTS" in codes(validate_zoning(doc))


def test_unresolved_assumptions_and_extensions():
    doc = fixture("zoning-proposed")
    doc["assignments"][0]["zone"] = "client_defined_quiet_zone"
    doc["assumptions"] = [
        {
            "id": "A1",
            "requirement_id": "REQ-BED",
            "description": "Discuss zoning",
            "provenance": "synthetic",
            "resolved": False,
        }
    ]
    report = validate_zoning(doc)
    assert "ASSUMPTION_UNRESOLVED" in codes(report, "missing_information")
    assert not report["errors"]


@pytest.mark.parametrize("version", [0, 2, True, "1"])
def test_zoning_version(version):
    doc = fixture("zoning-proposed")
    doc["schema_version"] = version
    assert validate_zoning(doc)["status"] == "INVALID"


def test_invalid_brief_not_usable_for_zoning():
    doc = fixture("zoning-proposed")
    doc["brief"]["building"]["rooms"][0]["floor_id"] = "BAD"
    assert "INVALID_SOURCE_BRIEF" in codes(validate_zoning(doc))
    with pytest.raises(ValueError, match="invalid design brief"):
        create_zoning_proposal(doc["brief"], "P")


def test_confirmed_approval_still_requires_non_null_floor():
    doc = fixture("zoning-approved")
    doc["assignments"][0]["floor_id"] = None
    report = validate_zoning(resign_zoning(doc))
    assert "UNCONFIRMED_APPROVAL" in codes(report)


def test_terminal_decision_cannot_be_promoted_again():
    doc = fixture("zoning-approved")
    row = doc["assignments"][0]
    rejected = deepcopy(doc["decisions"][1])
    rejected["id"] = "REJECTED"
    rejected["action"] = "rejected"
    doc["decisions"].append(rejected)
    promoted = deepcopy(rejected)
    promoted["id"] = "PROMOTED"
    promoted["action"] = "reviewed"
    doc["decisions"].append(promoted)
    row["status"] = "reviewed"
    assert "APPROVAL_TRANSITION" in codes(validate_zoning(doc))


def test_no_unknown_decision_target_or_forged_requirement():
    doc = fixture("zoning-approved")
    doc["decisions"][0]["decision_id"] = "UNKNOWN"
    assert "UNKNOWN_DECISION" in codes(validate_zoning(doc))


@pytest.mark.parametrize(
    "stamp",
    [
        "yesterday",
        "2026-11-18T00:00:00",
        "2026-02-30T00:00:00Z",
        "2026-11-18T24:00:00Z",
        "2026-11-18T00:00:00+99:00",
    ],
)
def test_approval_timestamp_requires_real_timezone_qualified_datetime(stamp):
    doc = fixture("zoning-approved")
    doc["decisions"][0]["record"]["recorded_at"] = stamp
    assert "SCHEMA" in codes(validate_zoning(doc))
