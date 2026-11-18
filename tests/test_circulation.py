"""Graph reachability remains distinct from supplied-route geometric traversal."""

from copy import deepcopy

from circulation_fixtures import two_rooms, corridor, polygon, review_events
from vnai.circulation import analyze_circulation
from vnai.architectural_review import architectural_review


def codes(report):
    return {r["code"] for r in report["errors"] + report["missing_information"]}


def test_corridor_graph_connects_actual_nodes_with_actual_openings_only():
    result = analyze_circulation(corridor())
    assert result["graph_status"] == "GRAPH_CONNECTED"
    assert len(result["edges"]) == 3 and len(result["components"]) == 1
    assert {n["kind"] for n in result["nodes"]} == {"room", "circulation", "exterior"}
    assert all(r["graph_reachable"] for r in result["room_access"].values())
    assert architectural_review(corridor())["physical_circulation_status"] == "NOT_VERIFIED"


def test_full_supplied_planar_routes_can_be_verified_without_architectural_approval():
    spec = corridor(True)
    before = deepcopy(spec)
    result = architectural_review(spec)
    assert result["status"] == "VALID" and result["graph_status"] == "GRAPH_CONNECTED"
    assert result["physical_circulation_status"] == "GEOMETRICALLY_TRAVERSABLE"
    assert all(
        v == "GEOMETRICALLY_TRAVERSABLE"
        for v in result["clearance"]["room_physical_access"].values()
    )
    assert result["architectural_approval"] == "SELECTED" and not result["fully_verified"]
    assert (
        result["technical_compliance"]
        == result["standards_review"]
        == result["fengshui_review"]
        == "NOT_EVALUATED"
    )
    assert not result["cad_writes_permitted"] and spec == before


def test_known_path_obstacle_blocks_clearance_but_not_topological_connectivity():
    spec = corridor(True)
    spec["fixed_obstacles"] = [
        polygon(spec, "COLUMN", [[0.4, 2], [0.6, 2], [0.6, 2.2], [0.4, 2.2]], kind="other")
    ]
    review_events(spec)
    result = architectural_review(spec)
    assert (
        result["graph_status"] == "GRAPH_CONNECTED"
        and result["physical_circulation_status"] == "BLOCKED"
    )
    assert "PASSAGE_FIXED_COLLISION" in codes(result)


def test_missing_door_inventory_is_unknown_not_automatically_blocked():
    spec = two_rooms()
    spec.pop("openings")
    spec["openings_complete"] = False
    review_events(spec)
    report = architectural_review(spec)
    assert report["status"] == "INCOMPLETE"
    assert report["graph_status"] == report["physical_circulation_status"] == "NOT_VERIFIED"
    assert all(
        a["status"] == "NOT_VERIFIED" for a in report["circulation_graph"]["room_access"].values()
    )
    assert not report["blocking_issues"]


def test_complete_empty_entrance_inventory_is_reported_separately():
    spec = two_rooms()
    spec["openings"] = [spec["openings"][1]]
    review_events(spec)
    report = analyze_circulation(spec)
    assert report["entrance_status"] == "MISSING" and report["graph_status"] == "BLOCKED"
    assert "NO_ENTRANCE_CONNECTION" in codes(report)


def test_missing_bridge_path_cannot_be_replaced_by_space_graph_connectivity():
    spec = corridor(True)
    spec["passages"] = [p for p in spec["passages"] if p["id"] != "P-C2"]
    review_events(spec)
    result = architectural_review(spec)
    assert result["graph_status"] == "GRAPH_CONNECTED"
    assert result["physical_circulation_status"] == "NOT_VERIFIED"
    assert result["clearance"]["room_physical_access"]["BED:1"] == "NOT_VERIFIED"


def test_declared_width_and_endpoint_checks():
    spec = corridor(True)
    spec["passages"][1]["width"] = 0.9
    review_events(spec)
    result = architectural_review(spec)
    assert (
        "PASSAGE_OPENING_WIDTH" in codes(result)
        and result["physical_circulation_status"] == "BLOCKED"
    )
    spec = corridor(True)
    spec["passages"][-1]["path"][0] = [1, 2.8]
    review_events(spec)
    assert "PASSAGE_ENDPOINT" in codes(architectural_review(spec))


def test_unconfirmed_routes_and_unknown_fixed_geometry_are_not_passes():
    spec = corridor(True)
    spec["passages"][0]["confirmation"] = "proposed"
    review_events(spec)
    assert architectural_review(spec)["physical_circulation_status"] == "NOT_VERIFIED"
    spec = corridor(True)
    spec["fixed_obstacles_complete"] = False
    review_events(spec)
    report = architectural_review(spec)
    assert report["physical_circulation_status"] == "NOT_VERIFIED"
    assert "FIXED_OBSTACLE_INFORMATION_REQUIRED" in codes(report)


def test_clearance_envelope_cannot_extend_into_an_unrelated_room():
    spec = corridor(True)
    spec["clearance_regions"][2]["exterior"] = [[0.5, 0.5], [1.5, 0.5], [1.5, 2.5], [0.5, 2.5]]
    review_events(spec)
    assert "CLEARANCE_OUTSIDE_SPACES" in codes(architectural_review(spec))


def test_invalid_route_reference_is_not_proof_of_a_physical_obstruction():
    spec = corridor(True)
    spec["passages"][0]["opening_ids"] = ["UNKNOWN"]
    review_events(spec)
    report = architectural_review(spec)
    assert report["status"] == "INVALID"
    assert "PASSAGE_OPENING_REFERENCE" in codes(report)
    assert report["physical_circulation_status"] == "NOT_VERIFIED"


def test_unknown_clearance_reference_does_not_become_a_known_collision():
    spec = corridor(True)
    spec["openings"][1]["clearance_id"] = "UNKNOWN"
    review_events(spec)
    report = architectural_review(spec)
    assert report["status"] == "INVALID"
    assert report["graph_status"] == "GRAPH_CONNECTED"
    assert report["physical_circulation_status"] == "NOT_VERIFIED"
    assert report["opening_validation"]["opening_results"][1]["physical_state"] == "NOT_VERIFIED"
