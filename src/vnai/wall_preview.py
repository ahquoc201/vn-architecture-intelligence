"""Deterministic SVG/Markdown from actual metric engine output; no CAD drawing."""

from html import escape
import math
import json

from vnai.wall_topology import polygon, encode


def wall_markdown(report: dict) -> str:
    lines = [
        "# Proposed architectural wall geometry",
        "",
        "Engine: " + report["engine_version"],
        "Wall status: " + report["wall_status"],
        "Geometry: " + report["geometry_status"],
        "Specification: " + report["specification_status"],
        "Candidate digest: " + str(report["source_candidate_digest"]),
        "Wall revision: " + str(report["wall_revision_id"]),
        "",
        "CAD writes: false. Architect approval: NOT_GRANTED. No construction readiness is asserted.",
        "Source room polygons are allocations, not automatically finished faces. Wall intent/alignment is explicit.",
        "",
        "| Floor | Envelope m2 | Wall union m2 | Individual sum m2 | Outside envelope m2 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in report["floors"]:
        lines.append(
            f"| {f['floor_id']} | {f['envelope_area_m2']:.8g} | {f['wall_union_area_m2']:.8g} | {f['individual_wall_area_sum_m2']:.8g} | {f['wall_area_outside_envelope_m2']:.8g} |"
        )
    lines += [
        "",
        "| Room | Allocation m2 | Wall occupied m2 | Clear m2 | Change % | Components | Area basis |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["rooms"]:
        lines.append(
            f"| {escape(r['room_id'])} | {r['allocation_area_m2']:.8g} | {r['wall_occupied_area_m2']:.8g} | {r['clear_area_m2']:.8g} | {r['area_difference_percent']:.6g} | {r['component_count']} | {r['area_requirement_basis']} |"
        )
    kinds = {}
    for j in report["junctions"]:
        kinds[j["kind"]] = kinds.get(j["kind"], 0) + 1
    lines += [
        "",
        "Junctions: " + str(kinds),
        "Drafting readiness: " + str(report["drafting_readiness"]),
        "Opening/clearance evidence must be remapped and independently reviewed for this wall revision.",
        "",
    ]
    for bucket in ("errors", "missing_information", "warnings"):
        if report[bucket]:
            lines += ["## " + bucket.replace("_", " "), ""]
            lines.extend(
                "- " + escape(d["code"] + " / " + d["path"] + ": " + d["message"])
                for d in report[bucket]
            )
            lines.append("")
    return "\n".join(lines)


def wall_svg(report: dict) -> str:
    if not report["floors"]:
        raise ValueError("No generated wall/clear geometry is available to preview.")
    panels = []
    total = 0.0
    height = 0.0
    for floor in report["floors"]:
        points = [
            p
            for shape in [floor["permitted_envelope"], floor["wall_footprint"]]
            for part in shape["polygons"]
            for p in part["exterior"]
        ]
        x0, y0 = min(p[0] for p in points), min(p[1] for p in points)
        x1, y1 = max(p[0] for p in points), max(p[1] for p in points)
        width, tall = x1 - x0 + 1.2, y1 - y0 + 2.0
        panels.append((floor, total, x0, y0, x1, y1, width, tall))
        total += width
        height = max(height, tall)

    def n(x: float) -> str:
        return repr(0.0 if x == 0 else float(x))

    pixels_per_metre = min(100, 1600 / total, 1600 / height)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n(total)} {n(height)}" width="{n(total * pixels_per_metre)}" height="{n(height * pixels_per_metre)}" preserveAspectRatio="xMidYMid meet">',
        "<title>Proposed architectural wall geometry - not a construction drawing</title>",
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    metadata = {
        k: report[k]
        for k in (
            "engine_version",
            "source_candidate_digest",
            "wall_specification_digest",
            "derived_geometry_digest",
            "wall_revision_id",
            "cad_writes_permitted",
        )
    }
    out.append("<metadata>" + escape(json.dumps(metadata, sort_keys=True)) + "</metadata>")
    review = report["sources"]["input"]["source"]["replay"]["review"]
    source = review["candidate"]["geometry"]
    scale = 1 if source["units"] == "m" else 0.001
    for floor, origin, x0, y0, x1, y1, width, tall in panels:
        key = floor["floor_id"]

        def point(p):
            return (origin + 0.6 + p[0] - x0, 1.0 + y1 - p[1])

        def path(geometry):
            commands = []
            for part in geometry["polygons"]:
                for ring in [part["exterior"], *part["holes"]]:
                    coords = [point(p) for p in ring]
                    commands.append("M " + " L ".join(n(x) + " " + n(y) for x, y in coords) + " Z")
            return " ".join(commands)

        def draw(geometry, attrs, title):
            out.append(
                '<path d="'
                + path(geometry)
                + '" fill-rule="evenodd" '
                + attrs
                + "><title>"
                + escape(title)
                + "</title></path>"
            )

        out += [
            f'<text x="{n(origin + 0.3)}" y="0.25" font-family="sans-serif" font-size="0.22">{escape(key)} - {escape(report["wall_status"])}</text>',
            f'<text x="{n(origin + 0.3)}" y="0.5" font-family="sans-serif" font-size="0.13">Proposed geometry / no CAD authorization</text>',
        ]
        draw(
            floor["permitted_envelope"],
            'fill="#f8fafc" stroke="#111827" stroke-width="0.025"',
            "Exact permitted envelope",
        )
        for room in report["rooms"]:
            if room["floor_id"] == key:
                draw(
                    room["clear_geometry"],
                    'fill="#dcfce7" stroke="#86efac" stroke-width="0.012"',
                    room["room_id"] + " clear geometry",
                )
        reservations = [r for r in source["polygons"] if r["role"] == "reservation"] + review.get(
            "fixed_obstacles", []
        )
        for r in reservations:
            if r.get("floor_id") == key:
                draw(
                    encode(polygon(r, scale)),
                    'fill="#fbbf24" fill-opacity="0.45" stroke="#a16207" stroke-width="0.012"',
                    "Original reserved/fixed region: " + r["id"],
                )
        for wall in report["walls"]:
            if wall["floor_id"] != key:
                continue
            color = "#334155" if wall["classification"] == "exterior" else "#b45309"
            draw(
                wall["geometry"],
                f'fill="{color}" fill-opacity="0.9" stroke="{color}" stroke-width="0.008"',
                wall["id"] + " / thickness " + str(wall["measured_thickness_m"]) + " m",
            )
            center = [point(wall["centerline"][k]) for k in ("start", "end")]
            cx, cy = (sum(p[i] for p in center) / 2 for i in (0, 1))
            out.append(
                f'<text x="{n(cx)}" y="{n(cy)}" font-family="sans-serif" font-size="0.09" fill="#1f2937" stroke="white" stroke-width="0.018" paint-order="stroke">{escape(wall["id"][:9])}</text>'
            )
        for room in report["rooms"]:
            if room["floor_id"] != key:
                continue
            draw(
                room["allocation_geometry"],
                'fill="none" stroke="#64748b" stroke-width="0.012" stroke-dasharray="0.08 0.05"',
                room["room_id"] + " original allocation (unchanged)",
            )
            shape = (
                room["clear_geometry"]
                if room["clear_geometry"]["polygons"]
                else room["allocation_geometry"]
            )
            from shapely.ops import unary_union

            region = unary_union([polygon(p, 1) for p in shape["polygons"]])
            px, py = point(list(region.representative_point().coords)[0])
            # Fit labels to narrow rooms without changing their geometry or scale.
            minx, _, maxx, _ = region.bounds
            font = min(0.18, max(0.06, (maxx - minx) / (0.65 * len(room["room_id"]) + 1)))
            area_font = min(0.13, font * 0.8)
            out += [
                f'<text x="{n(px)}" y="{n(py)}" text-anchor="middle" font-family="sans-serif" font-size="{n(font)}">{escape(room["room_id"])}</text>',
                f'<text x="{n(px)}" y="{n(py + font * 1.3)}" text-anchor="middle" font-family="sans-serif" font-size="{n(area_font)}">clear {room["clear_area_m2"]:.4g} m2</text>',
            ]
        length = 10 ** math.floor(math.log10(max((x1 - x0) / 4, 1e-9)))
        by = 1.0 + y1 - y0 + 0.35
        bx = origin + 0.6
        out += [
            f'<path d="M {n(bx)} {n(by)} h {n(length)}" stroke="black" stroke-width="0.025"/>',
            f'<text x="{n(bx)}" y="{n(by + 0.2)}" font-family="sans-serif" font-size="0.13">{length:g} m / uniform scale</text>',
            f'<text x="{n(origin + 0.3)}" y="{n(tall - 0.12)}" font-family="sans-serif" font-size="0.115">Green: clear / gray dashed: allocation / amber: reserved</text>',
        ]
    out.append("</svg>")
    return "\n".join(out) + "\n"
