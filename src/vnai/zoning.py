"""Explicit floor assignments and architect decision records; never a zoning optimizer."""

from copy import deepcopy
from datetime import datetime
from typing import Any

from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.space_program import build_space_program


def decision_digest(doc: dict, assignment: dict) -> str:
    """Bind review to the full source brief, revision and exact assignment content."""
    return canonical_digest(
        {
            "proposal_id": doc["proposal_id"],
            "revision": doc["revision"],
            "brief": doc["brief"],
            "floors": doc["floors"],
            "constraints": doc["constraints"],
            "assumptions": doc["assumptions"],
            "assignments": [
                {k: v for k, v in row.items() if k != "status"} for row in doc["assignments"]
            ],
            "decision_id": assignment["id"],
        }
    )


def create_zoning_proposal(brief: dict, proposal_id: str) -> dict:
    """Record only supplied floor assignments; never auto-approve or infer a zone."""
    program = build_space_program(brief)
    if program["status"] == "INVALID":
        raise ValueError("Cannot propose zoning from an invalid design brief")
    doc = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "revision": 1,
        "brief": deepcopy(brief),
        "floors": [{"id": f["id"]} for f in brief.get("building", {}).get("floors", [])],
        "assignments": [],
        "decisions": [],
        "constraints": [],
        "assumptions": [],
    }
    for i, room in enumerate(program["rooms"], 1):
        doc["assignments"].append(
            {
                "id": f"ASSIGN-{i}",
                "room_id": room["id"],
                "requirement_id": room["requirement_id"],
                "floor_id": room["floor_id"],
                "zone": "unresolved",
                "provenance": "source_design_brief",
                "confirmation": "confirmed"
                if room["floor_id"] and room["confirmed"]
                else "proposed",
                "status": "proposed",
            }
        )
    return doc


def validate_zoning(doc: Any) -> dict:
    report = new_report("zoning-v1")
    report.update(
        {
            "assignments": [],
            "unassigned_room_ids": [],
            "relationships": [],
            "architect_approved": False,
            "source_brief_status": None,
        }
    )
    if not schema_check(doc, "zoning.schema.json", report):
        return report
    program = build_space_program(doc["brief"])
    report["source_brief_status"] = program["status"]
    if program["status"] == "INVALID":
        issue(report, "errors", "INVALID_SOURCE_BRIEF", "brief", "Correct the source brief first.")
        report["source_brief_errors"] = program["validation"]["errors"]
        return finish(report)
    # Retain source issues. Decisions do not rewrite or implicitly confirm the brief.
    report["source_brief_missing_information"] = program["validation"]["missing_information"]
    if program["status"] == "INCOMPLETE":
        issue(
            report,
            "missing_information",
            "SOURCE_BRIEF_INCOMPLETE",
            "brief",
            "Zoning does not resolve the source brief; preserve its missing-data register.",
        )
    report["relationships"] = deepcopy(program["relationships"])
    rooms = {row["id"]: row for row in program["rooms"]}
    floors = {row["id"] for row in doc["floors"]}
    ids: set[str] = set()

    def register(key: str, path: str) -> None:
        if key in ids:
            issue(report, "errors", "DUPLICATE_ID", path, f"Duplicate identifier: {key}")
        ids.add(key)

    for floor in doc["floors"]:
        register(floor["id"], "floors")
    source_floors = {f["id"] for f in doc["brief"].get("building", {}).get("floors", [])}
    if source_floors and floors != source_floors:
        issue(report, "errors", "FLOOR_SET_CONFLICT", "floors", "Floor IDs differ from the brief.")
    storeys = doc["brief"].get("building", {}).get("storeys")
    if storeys and storeys["value"] is not None and len(floors) != storeys["value"]:
        issue(
            report,
            "missing_information" if not floors else "errors",
            "STOREY_COUNT_CONFLICT",
            "floors",
            "Supply floor IDs matching the source storey count.",
            [storeys["requirement_id"]],
        )
    requirements = {r["id"]: r for r in doc["brief"]["requirements"]}
    events: dict[str, list[dict]] = {}
    for event in doc["decisions"]:
        register(event["id"], "decisions")
        events.setdefault(event["decision_id"], []).append(event)
    assignments: dict[str, dict] = {}
    active: dict[str, dict] = {}
    approved_count = 0
    for row in doc["assignments"]:
        path = f"assignments.{row['id']}"
        register(row["id"], path)
        assignments[row["id"]] = row
        key = row["requirement_id"]
        room = rooms.get(row["room_id"])
        if not room or room["requirement_id"] != key:
            issue(
                report,
                "errors",
                "ROOM_TRACEABILITY",
                path,
                "Use a source program instance and its original requirement ID.",
                [key],
            )
        if row["floor_id"] is not None and row["floor_id"] not in floors:
            issue(
                report,
                "errors",
                "UNKNOWN_FLOOR",
                path,
                "Assignment references an unknown floor.",
                [key],
            )
        state = "proposed"
        previous_time = None
        for event in events.get(row["id"], []):
            action = event["action"]
            allowed = {
                "proposed": {"reviewed", "rejected", "superseded"},
                "reviewed": {"approved", "rejected", "superseded"},
                "approved": {"rejected", "superseded"},
                "rejected": set(),
                "superseded": set(),
            }
            if action not in allowed[state]:
                issue(
                    report,
                    "errors",
                    "APPROVAL_TRANSITION",
                    path,
                    f"Invalid decision transition: {state} to {action}.",
                    [key],
                )
            stamp = datetime.fromisoformat(
                event["record"]["recorded_at"].upper().replace("Z", "+00:00")
            )
            if previous_time is not None and stamp < previous_time:
                issue(
                    report,
                    "errors",
                    "DECISION_ORDER",
                    path,
                    "Decision timestamps are not ordered.",
                    [key],
                )
            previous_time = stamp
            if event["record"]["digest"] != decision_digest(doc, row):
                issue(
                    report,
                    "errors",
                    "STALE_APPROVAL",
                    path,
                    "Review/approval record does not match current decision content.",
                    [key],
                )
            state = action
        if state != row["status"]:
            issue(
                report,
                "errors",
                "MISSING_APPROVAL_RECORD",
                path,
                "Declared status must match explicit architect decision history.",
                [key],
            )
        if row["status"] == "approved":
            if row["confirmation"] != "confirmed" or row["floor_id"] is None:
                issue(
                    report,
                    "errors",
                    "UNCONFIRMED_APPROVAL",
                    path,
                    "Approved assignments need confirmed floor decisions.",
                    [key],
                )
            if row["zone"] == "unresolved":
                issue(
                    report,
                    "errors",
                    "UNRESOLVED_ZONE_APPROVAL",
                    path,
                    "Resolve the functional zone before approval.",
                    [key],
                )
            approved_count += 1
        if row["status"] not in {"rejected", "superseded"}:
            if row["room_id"] in active:
                issue(
                    report,
                    "errors",
                    "ASSIGNMENT_CONFLICT",
                    path,
                    "A room has multiple active assignment decisions.",
                    [key],
                )
            active[row["room_id"]] = row
            if (
                room
                and room["confirmed"]
                and room["floor_id"] is not None
                and row["floor_id"] != room["floor_id"]
            ):
                issue(
                    report,
                    "errors",
                    "SOURCE_ASSIGNMENT_CONFLICT",
                    path,
                    "Confirmed source floor differs; revise the brief explicitly first.",
                    [key],
                )
            if row["status"] != "approved":
                issue(
                    report,
                    "missing_information",
                    "ARCHITECT_APPROVAL_REQUIRED",
                    path,
                    "Proposed/reviewed assignments are not architect-approved.",
                    [key],
                )
            if row["zone"] == "unresolved":
                issue(
                    report,
                    "missing_information",
                    "ZONE_UNRESOLVED",
                    path,
                    "Choose an explicit functional zone; no room-type mapping is inferred.",
                    [key],
                )
        report["assignments"].append(deepcopy(row))
    for event_id in events:
        if event_id not in assignments:
            issue(
                report,
                "errors",
                "UNKNOWN_DECISION",
                "decisions",
                "Record references an unknown assignment.",
            )
    for room_id, room in rooms.items():
        if room_id not in active or active[room_id]["floor_id"] is None:
            report["unassigned_room_ids"].append(room_id)
            issue(
                report,
                "missing_information",
                "ROOM_UNASSIGNED",
                room_id,
                "Room remains unassigned; no floor is inferred.",
                [room["requirement_id"]],
            )
    for assumption in doc["assumptions"]:
        register(assumption["id"], "assumptions")
        if assumption["requirement_id"] not in requirements:
            issue(
                report,
                "errors",
                "UNKNOWN_REQUIREMENT",
                "assumptions",
                "Unknown assumption requirement.",
            )
        if not assumption["resolved"]:
            issue(
                report,
                "missing_information",
                "ASSUMPTION_UNRESOLVED",
                "assumptions",
                assumption["description"],
                [assumption["requirement_id"]],
            )
    seen_constraints: dict[str, list[dict]] = {}
    for constraint in doc["constraints"]:
        register(constraint["id"], "constraints")
        key = constraint["requirement_id"]
        req = requirements.get(key)
        if (
            not req
            or constraint["floor_id"] not in floors
            or any(r not in rooms for r in constraint["room_ids"])
        ):
            issue(
                report,
                "errors",
                "CONSTRAINT_REFERENCE",
                "constraints",
                "Unknown floor, room or requirement.",
                [key],
            )
            continue
        if constraint["strength"] == "hard" and (
            req["type"] != "mandatory" or req["confirmation"] != "confirmed"
        ):
            issue(
                report,
                "errors",
                "HARD_CONSTRAINT_UNCONFIRMED",
                "constraints",
                "Hard floor constraints require confirmed mandatory provenance.",
                [key],
            )
        for room_id in constraint["room_ids"]:
            for previous in seen_constraints.get(room_id, []):
                opposite = (
                    previous["floor_id"] == constraint["floor_id"]
                    and previous["kind"] != constraint["kind"]
                )
                competing = (
                    previous["kind"] == constraint["kind"] == "require"
                    and previous["floor_id"] != constraint["floor_id"]
                )
                if opposite or competing:
                    hard = previous["strength"] == constraint["strength"] == "hard"
                    issue(
                        report,
                        "errors" if hard else "warnings",
                        "CONTRADICTORY_FLOOR_CONSTRAINTS",
                        "constraints",
                        "Room has contradictory floor constraints.",
                        [previous["requirement_id"], key],
                    )
            seen_constraints.setdefault(room_id, []).append(constraint)
            floor_id = active.get(room_id, {}).get("floor_id")
            if floor_id is None:
                continue
            conflict = (
                floor_id != constraint["floor_id"]
                if constraint["kind"] == "require"
                else floor_id == constraint["floor_id"]
            )
            if conflict:
                issue(
                    report,
                    "errors" if constraint["strength"] == "hard" else "warnings",
                    "FLOOR_CONSTRAINT_CONFLICT",
                    "constraints",
                    "Assignment conflicts with floor constraint.",
                    [key],
                )
    for relation in program["relationships"]:
        if relation["relation"] == "adjacent":
            for left, right in relation["instance_pairs"]:
                a, b = active.get(left, {}).get("floor_id"), active.get(right, {}).get("floor_id")
                if a is not None and b is not None and a != b:
                    issue(
                        report,
                        "errors" if relation["strength"] == "hard" else "warnings",
                        "ADJACENCY_FLOOR_CONFLICT",
                        "relationships",
                        "Adjacent rooms require the same storey.",
                        [relation["requirement_id"]],
                    )
    finish(report)
    report["architect_approved"] = (
        report["status"] == "VALID" and bool(rooms) and approved_count == len(rooms)
    )
    return report
