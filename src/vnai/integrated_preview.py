"""Review drawings from actual composed engines; no new geometry inference."""

from html import escape
import json
from shapely.geometry import Polygon
from vnai.opening_hosts import shape_set
from vnai.stair_preview import stair_svg


def integrated_markdown(report: dict) -> str:
    lines = [
        "# Proposed integrated floorplan review",
        "",
        f"Engine {report['engine_version']}; status {report['integrated_status']}",
        "CAD writes: false. Architect approval: NOT_GRANTED. Technical/Feng Shui review: NOT_EVALUATED.",
        "",
        f"Search: {json.dumps(report['search'], sort_keys=True)}",
        "",
        "| Revision | State | Hard violations | Required unknown |",
        "|---|---|---|---|",
    ]
    for r in report["originals"] + report["candidates"]:
        lines.append(
            f"| {r['revision_id']} | {r['verification_status']} | {r['hard_violations']} | {r['required_unknown']} |"
        )
    lines += ["", "| Operation | Accepted | Resolved | Introduced |", "|---|---|---|---|"]
    for a in report["attempts"]:
        lines.append(
            f"| {a['permission_id']}: {a['original']} → {a['proposed']} | {a['accepted']} | {len(a['conflicts_resolved'])} | {len(a['conflicts_introduced'])} |"
        )
    for r in report["candidates"] or report["originals"][:1]:
        lines += [
            "",
            "## " + r["revision_id"],
            "",
            "| Floor / room | Allocation m² | Clear m² |",
            "|---|---|---|",
        ]
        for room in r["engines"]["walls"]["rooms"]:
            lines.append(
                f"| {room['floor_id']} / {room['room_id']} | {room['allocation_area_m2']:.6g} | {room['clear_area_m2']:.6g} |"
            )
        lines += ["", "Unresolved conflicts:"] + [
            f"- {c['severity']}: {c['engine']} / {c['code']} / {','.join(c['entity_ids'])}"
            for c in r["conflicts"]
        ]
    lines += [
        "",
        "Geometric verification is restricted to supplied data and supported flat/orthogonal models. No construction readiness or architect approval is inferred.",
        "",
    ]
    return "\n".join(lines)


def integrated_svg(report: dict, *, view: str = "comparison", floor: str | None = None) -> str:
    before = report["originals"][:1]
    after = report["candidates"][:1]
    if view == "section":
        chosen = after or before
        if not chosen or not chosen[0]["engines"]["stairs"].get("stairs"):
            raise ValueError("No supported staircase section exists.")
        svg = stair_svg(chosen[0]["engines"]["stairs"], "section")
        at = svg.index(">") + 1
        metadata = (
            '<metadata id="integrated-source-revision">'
            + escape(
                json.dumps(
                    {
                        "integrated_revision": chosen[0]["revision_id"],
                        "cad_writes_permitted": False,
                    },
                    sort_keys=True,
                )
            )
            + "</metadata>"
        )
        caption = (
            '<text x="25" y="70" font-family="Arial, sans-serif" font-size="11">B4: '
            + escape(chosen[0]["verification_status"].replace("_", " "))
            + "; human architect approval pending.</text>"
        )
        return svg[:at] + metadata + svg[at:].replace("</svg>", caption + "</svg>")
    states = before if view == "before" else after if view == "after" else before + after
    if not states or any(not state["engines"]["walls"].get("floors") for state in states):
        raise ValueError("No actual candidate/wall geometry for requested preview.")
    panels = [
        (r, f)
        for r in states
        for f in sorted(r["candidate"]["floor_ids"])
        if floor is None or f == floor
    ]
    if not panels:
        raise ValueError("Unknown floor or missing candidate.")
    allpoints = [
        p
        for r, f in panels
        for poly in r["candidate"]["geometry"]["polygons"]
        for p in poly["exterior"]
    ]
    minx, miny = min(p[0] for p in allpoints), min(p[1] for p in allpoints)
    maxx, maxy = max(p[0] for p in allpoints), max(p[1] for p in allpoints)
    unit = 1 if states[0]["candidate"]["geometry"]["units"] == "m" else 0.001
    scale = min(280 / max((maxx - minx) * unit, 1), 900 / max((maxy - miny) * unit, 1))
    width = 480 * len(panels)
    height = 1260
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="Arial, sans-serif" preserveAspectRatio="xMidYMid meet">',
        '<rect width="100%" height="100%" fill="white"/>',
        "<metadata>"
        + escape(
            json.dumps(
                {
                    "engine_version": report["engine_version"],
                    "revisions": [r["revision_id"] for r in states],
                    "view": view,
                    "scale_px_per_m": scale,
                    "cad_writes_permitted": False,
                },
                sort_keys=True,
            )
        )
        + "</metadata>",
    ]

    def n(v):
        return format(v, ".12g")

    for index, (state, fid) in enumerate(panels):
        left = index * 480

        def xy(p):
            return left + 100 + (p[0] - minx * unit) * scale, 1060 - (p[1] - miny * unit) * scale

        def text(x, y, t, size=13, color="#1f2937"):
            parts.append(
                f'<text x="{n(x)}" y="{n(y)}" font-size="{size}" fill="{color}">{escape(str(t))}</text>'
            )

        def line(points, color="#374151", weight=1, dash=""):
            p = " ".join(n(x) + "," + n(y) for x, y in map(xy, points))
            parts.append(
                f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{weight}" stroke-dasharray="{dash}"/>'
            )

        def draw(geom, fill, stroke="#9ca3af", weight=0.7, dash=""):
            if geom.is_empty:
                return
            polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
            for p in polys:
                if p.geom_type != "Polygon":
                    continue
                d = ""
                for ring in [p.exterior, *p.interiors]:
                    coords = list(map(xy, ring.coords))
                    d += "M" + " L".join(n(x) + " " + n(y) for x, y in coords) + " Z "
                parts.append(
                    f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{stroke}" stroke-width="{weight}" stroke-dasharray="{dash}"/>'
                )

        text(
            left + 25, 30, ("ORIGINAL" if state in before else "PROPOSED REFINED") + " / " + fid, 18
        )
        text(
            left + 25,
            54,
            state["verification_status"].replace("_", " "),
            12,
            "#b91c1c" if state["hard_violations"] else "#166534",
        )
        text(
            left + 25,
            77,
            f"Design-wide: failed findings {state['hard_violations']} | unknown {state['required_unknown']}",
            12,
        )
        geo = state["candidate"]["geometry"]
        for p in geo["polygons"]:
            if p.get("floor_id") not in [None, fid]:
                continue
            shape = Polygon([(x * unit, y * unit) for x, y in p["exterior"]])
            if p["role"] == "site":
                draw(shape, "#fafafa", "#94a3b8", 1, "4 3")
            if p["role"] == "footprint":
                draw(shape, "white", "#111827", 1)
            if p.get("reservation_kind") == "circulation":
                draw(shape, "#e0f2fe", "#7dd3fc")
            if p.get("reservation_kind") == "service_shaft":
                draw(shape, "#e5e7eb", "#4b5563")
        for f in state["engines"]["openings"].get("floors", []):
            if f["floor_id"] == fid:
                draw(shape_set(f["wall_plan_at_cut"]), "#374151", "#111827")
        for obstacle in report["sources"]["input"]["review_template"].get("fixed_obstacles", []):
            if obstacle["floor_id"] == fid:
                draw(
                    Polygon([(x * unit, y * unit) for x, y in obstacle["exterior"]]),
                    "#fda4af",
                    "#be123c",
                )
        for opening in state["engines"]["openings"].get("openings", []):
            if opening["floor_id"] != fid:
                continue
            p = opening.get("primitives", {})
            for key, color in [
                ("frame", "#60a5fa"),
                ("open_leaf", "#92400e"),
                ("glazing", "#38bdf8"),
            ]:
                if key in p and isinstance(p[key], dict) and p[key].get("type") == "PolygonSet":
                    draw(shape_set(p[key]), color, color)
            if "glazing" in p and "start" in p["glazing"]:
                line([p["glazing"]["start"], p["glazing"]["end"]], "#0284c7", 1.5)
            if "track" in p:
                line([p["track"]["start"], p["track"]["end"]], "#7c3aed", 1)
            if "swing_arc" in p:
                arc = p["swing_arc"]
                a, b = xy(arc["start"]), xy(arc["end"])
                flag = 0 if arc["rotation"] == "ccw" else 1
                parts.append(
                    f'<path d="M{n(a[0])} {n(a[1])} A{n(arc["radius_m"] * scale)} {n(arc["radius_m"] * scale)} 0 0 {flag} {n(b[0])} {n(b[1])}" fill="none" stroke="#b45309" stroke-width=".8"/>'
                )
        stairs = state["engines"]["stairs"]
        for stair in stairs.get("stairs", []):
            if fid not in (stair["source_floor"], stair["destination_floor"]):
                continue
            for surface in stair["surfaces"]:
                draw(shape_set(surface["geometry"]), "#fff7ed", "#c2410c", 0.55)
            for flight in stair["flights"]:
                points = flight["walking_line"]
                if fid == stair["destination_floor"]:
                    points = list(reversed(points))
                line(points, "#c2410c", 1.4)
                a, b = map(xy, [points[-2], points[-1]])
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = (dx * dx + dy * dy) ** 0.5
                if length:
                    ux, uy = dx / length, dy / length
                    parts.append(
                        f'<path d="M{n(b[0] - 7 * ux + 3 * uy)} {n(b[1] - 7 * uy - 3 * ux)} L{n(b[0])} {n(b[1])} L{n(b[0] - 7 * ux - 3 * uy)} {n(b[1] - 7 * uy + 3 * ux)}" fill="none" stroke="#c2410c"/>'
                    )
            c = shape_set(stair["footprint"]).centroid
            x, y = xy([c.x, c.y])
            text(x - 12, y, "UP" if fid == stair["source_floor"] else "DOWN", 9, "#9a3412")
        for opening in (
            report["sources"]["input"].get("stair_specification", {}).get("floor_openings", [])
        ):
            if opening["floor_id"] == fid:
                draw(shape_set(opening["geometry"]), "none", "#0891b2", 1, "5 3")
        for room in state["engines"]["walls"]["rooms"]:
            if room["floor_id"] == fid:
                clear = shape_set(room["clear_geometry"])
                anchor = clear if not clear.is_empty else shape_set(room["allocation_geometry"])
                p = anchor.representative_point()
                x, y = xy([p.x, p.y])
                if (anchor.bounds[2] - anchor.bounds[0]) * scale < 100:
                    parts.append(
                        f'<path d="M{n(x)} {n(y)} L{left + 300} {n(y)}" stroke="#64748b" fill="none" stroke-width=".6"/>'
                    )
                    text(left + 310, y, room["room_id"], 11)
                    text(left + 310, y + 17, n(room["clear_area_m2"]) + " m2 clear", 10)
                else:
                    text(x - 34, y, room["room_id"], 12)
                    text(x - 34, y + 17, n(room["clear_area_m2"]) + " m2 clear", 11)
        line(
            [[minx * unit, miny * unit - 0.35], [minx * unit + 1, miny * unit - 0.35]], "#111827", 3
        )
        text(left + 100, 1097, "1 m | uniform geometric scale", 11)
        text(left + 25, 1120, "PROPOSED - architect review pending", 12)
        text(left + 25, 1141, "CAD writes: false | construction: NOT_EVALUATED", 11)
        codes = sorted({c["code"] for c in state["conflicts"]})
        if codes:
            text(
                left + 25,
                1159,
                f"Design-wide codes: first {min(4, len(codes))}/{len(codes)}; see full report",
                10,
            )
        for i, code in enumerate(codes[:4]):
            text(left + 25, 1179 + 18 * i, code[:58], 10, "#b91c1c")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
