"""Extend the B1 SVG with actual B2 cuts, leaf polygons, arcs and window symbols."""

from copy import deepcopy
from html import escape
import json
import re
from shapely.ops import unary_union
from vnai.wall_preview import wall_svg
from vnai.wall_topology import encode, polygon
from vnai.opening_hosts import shape_set


def opening_markdown(report: dict) -> str:
    def show(x):
        return "unknown" if x is None else str(x)

    lines = [
        "# Proposed wall-hosted opening schedule",
        "",
        "Engine: " + report["engine_version"],
        "Drafting: " + report["drafting_status"],
        "Revision: " + str(report["opening_revision_id"]),
        "CAD writes: false; architectural approval: NOT_GRANTED.",
        "",
        "| Mark | Type | Floor | Quantity | Rough W/H m | Frame inner m | Leaf m | Clear W/H m | Sill/head m | State |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["schedule"]:
        lines.append(
            "| "
            + " | ".join(
                escape(show(v)).replace("|", "&#124;")
                for v in (
                    r["mark"],
                    r["type"],
                    r["floor_id"],
                    r["quantity"],
                    show(r["rough_width_m"]) + " / " + show(r["rough_height_m"]),
                    r["frame_inner_width_m"],
                    r["leaf_width_m"],
                    show(r["clear_width_m"]) + " / " + show(r["clear_height_m"]),
                    show(r["sill_m"]) + " / " + show(r["head_m"]),
                    r["review_state"],
                )
            )
            + " |"
        )
    lines += [
        "",
        "Window plan cuts do not remove floor obstructions or create circulation edges. Room areas exclude thresholds.",
        "",
        "Graph: "
        + str(report.get("circulation", {}).get("graph", {}).get("graph_status", "UNKNOWN")),
        "Supplied-path clearance: "
        + str(report.get("circulation", {}).get("clearance", {}).get("physical_status", "UNKNOWN")),
        "",
    ]
    for bucket in ("source_conflicts", "errors", "missing_information", "warnings"):
        if report[bucket]:
            lines += ["## " + bucket.replace("_", " "), ""]
            lines += ["- " + escape(d["code"] + ": " + d["message"]) for d in report[bucket]]
            lines.append("")
    return "\n".join(lines) + "\n"


def opening_svg(report: dict) -> str:
    if not report["floors"]:
        raise ValueError("No measurable opening drafting geometry is available.")
    base = deepcopy(report["sources"]["wall_model"])
    floors = {f["floor_id"]: f for f in report["floors"]}
    wall_geometries = {
        w["wall_id"]: w["plan_geometry"] for f in report["floors"] for w in f["walls"]
    }
    for w in base["walls"]:
        w["geometry"] = wall_geometries[w["id"]]
    for f in base["floors"]:
        geometry = [shape_set(f["wall_footprint"])]
        for r in report["openings"]:
            if r["floor_id"] == f["floor_id"]:
                for k in ("movement_envelope", "frame_outline", "closed_leaf", "open_leaf"):
                    if k in r["primitives"]:
                        geometry.append(shape_set(r["primitives"][k]))
        # This internal field supplies view bounds only; wall polygons above remain actual plan geometry.
        f["wall_footprint"] = encode(unary_union(geometry))
    base["wall_status"] = report["drafting_status"]
    svg = wall_svg(base).rsplit("</svg>", 1)[0]
    svg = re.sub(r"<text\b[^>]*>W-[^<]*</text>\n?", "", svg)
    svg = svg.replace(
        "Proposed architectural wall geometry - not a construction drawing",
        "Proposed wall-hosted doors/windows - not a construction drawing",
    )
    spec = report["sources"]["input"]["specification"]
    meta = {
        k: report[k]
        for k in (
            "engine_version",
            "source_wall_revision_id",
            "opening_revision_id",
            "opening_geometry_digest",
            "specification_digest",
            "cad_writes_permitted",
        )
    }
    meta["plan_cut_height"] = spec.get("plan_cut_height")
    meta["plan_cut_units"] = spec["units"]
    meta["vertical_datum"] = spec["vertical_datum"]
    out = [
        svg,
        "<desc>"
        + escape(
            "; ".join(
                d["code"] + ": " + d["message"]
                for d in [*report["errors"], *report["missing_information"]]
            )
        )
        + "</desc>",
        '<metadata id="opening-drafting-revision">'
        + escape(json.dumps(meta, sort_keys=True))
        + "</metadata>",
    ]
    origin = 0.0

    def n(v):
        return repr(0.0 if v == 0 else float(v))

    for f in base["floors"]:
        fid = f["floor_id"]
        points = [
            p
            for g in (f["permitted_envelope"], f["wall_footprint"])
            for part in g["polygons"]
            for p in part["exterior"]
        ]
        x0 = min(p[0] for p in points)
        x1 = max(p[0] for p in points)
        y1 = max(p[1] for p in points)

        def point(p):
            return [origin + 0.6 + p[0] - x0, 1.0 + y1 - p[1]]

        def draw(geometry, style, title):
            parts = []
            for poly in geometry["polygons"]:
                for ring in [poly["exterior"], *poly["holes"]]:
                    parts.append(
                        "M " + " L ".join(n(x) + " " + n(y) for x, y in map(point, ring)) + " Z"
                    )
            out.append(
                '<path d="'
                + " ".join(parts)
                + '" fill-rule="evenodd" '
                + style
                + "><title>"
                + escape(title)
                + "</title></path>"
            )

        def line(record, style):
            a, b = point(record["start"]), point(record["end"])
            out.append(f'<path d="M {n(a[0])} {n(a[1])} L {n(b[0])} {n(b[1])}" {style}/>')

        out.append(
            f'<text x="{n(origin + 0.3)}" y="0.74" font-family="sans-serif" font-size="0.12">Plan cut: {escape(str(spec.get("plan_cut_height", "unknown")))} {spec["units"]} above finished floor</text>'
        )
        draw(
            floors[fid]["door_threshold_geometry"],
            'fill="#cffafe" stroke="none"',
            "Door thresholds: separately accounted, not added to room usable area",
        )
        source_units = report["sources"]["input"]["source"]["source"]["replay"]["review"][
            "candidate"
        ]["geometry"]["units"]
        for obstacle in spec.get("additional_obstacles", []):
            if obstacle.get("floor_id") == fid:
                draw(
                    encode(polygon(obstacle, 1 if source_units == "m" else 0.001)),
                    'fill="#fca5a5" fill-opacity="0.65" stroke="#b91c1c" stroke-width="0.02"',
                    "Known fixed obstacle: " + obstacle["id"],
                )
        for r in report["openings"]:
            if r["floor_id"] != fid:
                continue
            p = r["primitives"]
            window = r["type"].endswith("window")
            outside = r["plan_interpretation"] != "INTERSECTS_OPENING"
            color = (
                "#b91c1c"
                if r["physical_state"] == "BLOCKED"
                or r.get("movement_clearance_status") == "BLOCKED"
                else "#2563eb"
                if window
                else "#0891b2"
            )
            if r["rough_cut"] and not r["cut_accepted"]:
                draw(
                    r["rough_cut"],
                    'fill="none" stroke="#dc2626" stroke-width="0.035" stroke-dasharray="0.08 0.04"',
                    r["id"] + " unapplied cut / " + ", ".join(r["issues"]),
                )
            if "frame" in p:
                draw(
                    p["frame"],
                    f'fill="{color}" fill-opacity="0.6" stroke="{color}" stroke-width="0.012"'
                    + (' stroke-dasharray="0.06 0.04"' if outside else ""),
                    r["mark"] + " declared jamb frames / " + r["plan_interpretation"],
                )
            if "glazing" in p:
                line(
                    p["glazing"],
                    f'fill="none" stroke="{color}" stroke-width="0.025"'
                    + (' stroke-dasharray="0.07 0.05"' if outside else ""),
                )
            for name, state in (("closed_leaf", "closed"), ("open_leaf", "open")):
                if name in p:
                    current = r.get("operating_state") == state
                    draw(
                        p[name],
                        f'fill="{color if current else "none"}" stroke="{color}" stroke-width="0.014"'
                        + (' stroke-dasharray="0.06 0.04"' if not current or outside else ""),
                        r["mark"] + " " + state + " leaf",
                    )
            if "swing_arc" in p:
                arc = p["swing_arc"]
                a, b = point(arc["start"]), point(arc["end"])
                radius = n(arc["radius_m"])
                flag = 0 if arc["rotation"] == "ccw" else 1
                out.append(
                    f'<path d="M {n(a[0])} {n(a[1])} A {radius} {radius} 0 0 {flag} {n(b[0])} {n(b[1])}" fill="none" stroke="{color}" stroke-width="0.012"/>'
                )
            if "track" in p:
                line(
                    p["track"],
                    f'fill="none" stroke="{color}" stroke-width="0.012" stroke-dasharray="0.04 0.03"',
                )
            if r.get("reference"):
                a, b = r["reference"]["start"], r["reference"]["end"]
                px, py = point([(a[i] + b[i]) / 2 for i in (0, 1)])
                label = r["mark"] + (
                    " elevation unknown"
                    if window and r["plan_interpretation"] == "INCOMPLETE_VERTICAL"
                    else " projected"
                    if window and outside
                    else ""
                )
                out.append(
                    f'<text x="{n(px)}" y="{n(py - 0.12)}" text-anchor="middle" font-family="sans-serif" font-size="0.13" fill="{color}" stroke="white" stroke-width="0.02" paint-order="stroke">{escape(label)}<title>{escape(r["id"] + " / " + str(r["host_wall_id"]))}</title></text>'
                )
        origin += x1 - x0 + 1.2
    out.append("</svg>")
    return "\n".join(out) + "\n"
