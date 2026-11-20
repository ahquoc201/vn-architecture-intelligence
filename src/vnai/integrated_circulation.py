"""Join freshly verified local portal routes and B3 stair edges, without new geometry."""

from vnai.circulation import reachable


def compose_circulation(candidate, opening_spec, openings, stair_spec, stairs):
    network = {}
    origins = set()
    interiors = set()
    edges = []

    def node(space, opening):
        key = (space, opening)
        network.setdefault(key, set())
        return key

    def join(a, b, source):
        network[a].add(b)
        network[b].add(a)
        edges.append({"nodes": [list(a), list(b)], "evidence": source})

    for row in openings.get("openings", []):
        if (
            row.get("graph_eligible")
            and row.get("physical_state") == "GEOMETRICALLY_TRAVERSABLE"
            and len(row["space_ids"]) == 2
        ):
            a, b = (node(s, row["id"]) for s in row["space_ids"])
            join(a, b, "B2:" + row["id"])
    measured = {
        p["id"]: p
        for p in openings.get("circulation", {}).get("clearance", {}).get("passage_results", [])
    }
    rooms = {p["room_id"] for p in candidate["geometry"]["polygons"] if p["role"] == "room"}
    exterior_ids = {e["id"] for e in opening_spec.get("exteriors", [])}
    for path in opening_spec.get("passages", []):
        if measured.get(path["id"], {}).get("status") != "GEOMETRICALLY_TRAVERSABLE":
            continue
        ports = [node(path["space_id"], o) for o in path["opening_ids"]]
        if len(ports) == 2:
            join(ports[0], ports[1], "B2-PATH:" + path["id"])
        if path["space_id"] in rooms:
            interiors.update(ports)
        if len(ports) == 1 and path["space_id"] in exterior_ids:
            origins.add(ports[0])
    stair_rows = {
        s["id"]: s for s in stairs.get("circulation", {}).get("stairs", {}).get("stair_results", [])
    }
    if (
        stairs.get("geometry_status") == "VALID"
        and stairs.get("circulation", {}).get("physical_status") == "GEOMETRICALLY_TRAVERSABLE"
    ):
        for connection in stair_spec.get("connections", []):
            evidence = stair_rows.get(connection["id"], {})
            if not evidence.get("graph_eligible") or not all(evidence.get("entry_exit_valid", [])):
                continue
            a, b = (
                node(connection[k]["stairwell_id"], connection[k]["opening_id"])
                for k in ["source", "destination"]
            )
            join(a, b, "B3:" + connection["id"])
    arrived = (
        reachable(network, sorted(origins))
        if opening_spec.get("fixed_obstacles_complete") is True
        else set()
    )
    access = {
        room: (
            "GEOMETRICALLY_TRAVERSABLE"
            if any(p in arrived for p in interiors if p[0] == room)
            else "NOT_VERIFIED"
        )
        for room in sorted(rooms)
    }
    return {
        "status": "GEOMETRICALLY_TRAVERSABLE"
        if access and all(v == "GEOMETRICALLY_TRAVERSABLE" for v in access.values())
        else "NOT_VERIFIED",
        "room_access": access,
        "verified_edges": edges,
        "exterior_origins": [list(n) for n in sorted(origins)],
        "scope": "SUPPLIED_WIDTH_CHECKED_PORTAL_PATH_CHAINS_PLUS_VERIFIED_B3_STAIRS_NOT_BODY_FIRE_ACCESSIBILITY_CERTIFICATION",
        "architect_approval": "NOT_GRANTED",
        "cad_writes_permitted": False,
    }
