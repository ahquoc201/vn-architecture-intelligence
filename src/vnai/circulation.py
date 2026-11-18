"""Explicit connection graph; connectivity is never physical-access certification."""

from collections import deque
from typing import Any, TypeVar
from collections.abc import Hashable

from vnai.contracts import finish, issue
from vnai.review_common import ReviewContext, build_context, stage_report
from vnai.openings import _opening_report
from vnai.stairs import _stair_report


Node = TypeVar("Node", bound=Hashable)


def reachable(adjacency: dict[Node, set[Node]], roots: list[Node]) -> set[Node]:
    visited = set(roots)
    queue = deque(sorted(roots))
    while queue:
        node = queue.popleft()
        for neighbor in sorted(adjacency.get(node, set()) - visited):
            visited.add(neighbor)
            queue.append(neighbor)
    return visited


def _graph_report(ctx: ReviewContext, openings: dict, stairs: dict) -> dict:
    result = stage_report(
        ctx,
        "circulation-graph-v1",
        graph_status="NOT_VERIFIED",
        nodes=[s.record() for s in sorted(ctx.spaces.values(), key=lambda s: s.id)],
        edges=[],
        components=[],
        isolated_room_ids=[],
        room_access={},
        entrance_status="UNKNOWN",
        opening_validation=openings,
        stair_validation=stairs,
    )
    if ctx.report["errors"] or ctx.geometry_status != "VALID":
        return result
    adjacency = {key: set() for key in ctx.spaces}
    for kind, rows in (
        ("opening", openings["opening_results"]),
        ("stair", stairs["stair_results"]),
    ):
        for row in rows:
            if row["graph_eligible"]:
                a, b = row["space_ids"]
                adjacency[a].add(b)
                adjacency[b].add(a)
                result["edges"].append(
                    {
                        "id": row["id"],
                        "kind": kind,
                        "space_ids": list(row["space_ids"]),
                        "physical_state": row["physical_state"],
                    }
                )
    roots = sorted(
        key for key, space in ctx.spaces.items() if space.kind == "exterior" and adjacency[key]
    )
    reached = reachable(adjacency, roots)
    complete = openings["door_information_complete"] and stairs["stair_information_complete"]
    unvisited = set(adjacency)
    while unvisited:
        component = reachable(adjacency, [min(unvisited)])
        result["components"].append(sorted(component))
        unvisited -= component
    result["isolated_room_ids"] = sorted(
        key for key, space in ctx.spaces.items() if space.kind == "room" and not adjacency[key]
    )
    if roots:
        result["entrance_status"] = "CONNECTED"
    elif complete:
        result["entrance_status"] = "MISSING"
        issue(
            result,
            "errors",
            "NO_ENTRANCE_CONNECTION",
            "exteriors",
            "Complete inventory has no validated connection from exterior access.",
        )
    else:
        issue(
            result,
            "missing_information",
            "ENTRANCE_NOT_DEMONSTRATED",
            "exteriors",
            "Entrance connection is not demonstrated; missing data is not automatically a blocked door.",
        )
    for key, space in sorted(ctx.spaces.items()):
        if space.kind != "room":
            continue
        status = "GRAPH_CONNECTED" if key in reached else "BLOCKED" if complete else "NOT_VERIFIED"
        result["room_access"][key] = {"graph_reachable": key in reached, "status": status}
        if key not in reached:
            issue(
                result,
                "errors" if complete else "missing_information",
                "ROOM_DISCONNECTED" if complete else "ROOM_ACCESS_UNKNOWN",
                key,
                "No opening/stair chain from an exterior is demonstrated for this room.",
            )
    if (
        roots
        and len(result["components"]) == 1
        and all(r["graph_reachable"] for r in result["room_access"].values())
    ):
        result["graph_status"] = "GRAPH_CONNECTED"
    else:
        result["graph_status"] = "BLOCKED" if complete else "NOT_VERIFIED"
        if len(result["components"]) > 1:
            issue(
                result,
                "diagnostics",
                "DISCONNECTED_COMPONENTS",
                "graph",
                "Declared space graph contains disconnected components.",
            )
    # Topology remains separately visible, but malformed/blocked supplied connections are not hidden by exit 0.
    for source in (openings, stairs):
        for item in source["errors"]:
            if item not in result["errors"]:
                result["errors"].append(item)
    return finish(result)


def analyze_circulation(value: Any) -> dict:
    ctx = build_context(value)
    openings = _opening_report(ctx)
    return _graph_report(ctx, openings, _stair_report(ctx, openings))
