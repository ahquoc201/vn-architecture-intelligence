"""Scale-consistent plan and true/developed section SVG from staircase reports."""

from html import escape
import json
from shapely.geometry import LineString
from shapely.ops import unary_union
from vnai.opening_hosts import shape_set
from vnai.stair_clearance import wall_prisms
from vnai.stair_geometry import exact
from fractions import Fraction


def stair_markdown(report):
    lines = [
        "# Proposed stair schedule",
        "",
        "Engine: " + report["engine_version"],
        "Revision: " + str(report["stair_revision_id"]),
        "Status: " + report["drafting_status"],
        "CAD writes: false; approval: NOT_GRANTED.",
        "",
        "| Stair / type | Floors | Rise m | Risers | Ordinary treads | Going m | Run m | Width m | Landings | Headroom |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in report["schedule"]:
        values = [
            s["id"] + " / " + s["type"],
            s["source_floor"] + " -> " + s["destination_floor"],
            s["rise_m"],
            [f["risers"] for f in s["flights"]],
            [f["ordinary_treads"] for f in s["flights"]],
            [f["tread_depth_m"] for f in s["flights"]],
            [f["run_m"] for f in s["flights"]],
            [f["width_m"] for f in s["flights"]],
            [
                (record_item["dimensions_m"], record_item["elevation_m"])
                for record_item in s["landings"]
            ],
            str(s["headroom_status"]) + " / " + str(s["minimum_verified_headroom_m"]),
        ]
        lines.append(
            "| " + " | ".join(escape(str(x)).replace("|", "&#124;") for x in values) + " |"
        )
    lines += [
        "",
        "Section kinds: " + "; ".join(s["id"] + ": " + s["section_kind"] for s in report["stairs"]),
    ]
    lines += [
        "",
        "Riser heights derived from exact total-rise allocation unless explicitly supplied. Arrival surfaces are separate from ordinary treads.",
        "Headroom scope: continuous flat modeled walking regions and horizontal-bottom prisms; no structural or regulatory certification.",
    ]
    for bucket in ["errors", "missing_information", "warnings"]:
        lines += ["", "## " + bucket] + [
            "- " + escape(r["code"] + ": " + r["path"] + " — " + r["message"])
            for r in report[bucket]
        ]
    return "\n".join(lines) + "\n"


def stair_svg(report, view="plan"):
    """Draw measured geometry; DOWN arrows reverse the canonical ascending paths."""
    from shapely.geometry import Point, box
    from vnai.wall_topology import encode
    from textwrap import wrap

    source = report["sources"].get("opening_model", {})
    spec = report["sources"].get("input", {}).get("specification", {})
    if not report["stairs"]:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="160"><text x="20" y="40">No generated staircase geometry: '
            + escape(report["drafting_status"])
            + "</text></svg>\n"
        )
    scalar = Fraction(1) if spec["units"] == "m" else Fraction(1, 1000)
    levels = {
        r["floor_id"]: exact(r["finished_elevation"], scalar)
        for r in spec["levels"]
        if "finished_elevation" in r and r["confirmation"] == "confirmed"
    }
    walls, _ = wall_prisms(source, levels)
    obstructions = (
        report["sources"].get("slab_material", [])
        + walls
        + [
            {
                "id": o["id"],
                "geometry": o["geometry"],
                "bottom_m": float(exact(o["bottom"], scalar)),
                "top_m": float(exact(o["top"], scalar)),
            }
            for o in spec["obstacles"]
            if o["bottom"] < o["top"]
        ]
    )
    panels = []
    for stair in report["stairs"]:
        if view == "plan":
            for floor in [stair["source_floor"], stair["destination_floor"]]:
                shapes = [shape_set(stair["envelope"])]
                rooms = [r for r in source["rooms"] if r["floor_id"] == floor]
                shapes.extend(shape_set(r["clear_floor_geometry"]) for r in rooms)
                shapes.extend(
                    shape_set(f["source_wall_footprint"])
                    for f in source["floors"]
                    if f["floor_id"] == floor
                )
                panels.append((stair, floor, unary_union(shapes).bounds, rooms))
        else:
            points = [p for section in stair["sections"] for p in section["profile"]]
            applicable = [
                o
                for o in obstructions
                if shape_set(o["geometry"]).intersection(shape_set(stair["footprint"])).area > 0
            ]
            low = min([stair["source_elevation_m"]] + [o["bottom_m"] for o in applicable])
            high = max([stair["destination_elevation_m"] + 1] + [o["top_m"] for o in applicable])
            panels.append(
                (stair, None, (min(p[0] for p in points), low, max(p[0] for p in points), high), [])
            )
    scale = 760 / max(max(b[2] - b[0], b[3] - b[1], 1) for s, f, b, r in panels)
    width = 960 * len(panels)
    height = 1080
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" font-family="Arial, sans-serif">',
        "<metadata>"
        + escape(
            json.dumps(
                {
                    "engine_version": report["engine_version"],
                    "revision": report["stair_revision_id"],
                    "source_opening_revision": report["source_opening_revision_id"],
                    "view": view,
                    "scale_px_per_m": scale,
                    "cad_writes_permitted": False,
                },
                sort_keys=True,
            )
        )
        + "</metadata>",
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for index, (stair, floor, bounds, rooms) in enumerate(panels):
        offset = index * 960

        def xy(p):
            return [offset + 65 + (p[0] - bounds[0]) * scale, 900 - (p[1] - bounds[1]) * scale]

        def line(points, color="#26364a", dash=False, width=1.5):
            value = " ".join(",".join(format(v, ".12g") for v in xy(p)) for p in points)
            parts.append(
                f'<polyline points="{value}" fill="none" stroke="{color}" stroke-width="{width}"'
                + (' stroke-dasharray="5 4"' if dash else "")
                + "/>"
            )

        def text(point, value, color="#111", size=12, dx=0, dy=0, anchor="start"):
            x, y = xy(point)
            x += dx
            y += dy
            parts.append(
                f'<text x="{x:.12g}" y="{y:.12g}" fill="{color}" font-size="{size}" text-anchor="{anchor}">'
                + escape(str(value))
                + "</text>"
            )

        def polygon(value, fill, stroke="#566", dash=False):
            geometry = shape_set(value)
            for p in geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]:
                if p.is_empty:
                    continue
                d = " ".join(
                    "M "
                    + " L ".join(",".join(format(v, ".12g") for v in xy(c)) for c in ring.coords)
                    + " Z"
                    for ring in [p.exterior, *p.interiors]
                )
                parts.append(
                    f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{stroke}" stroke-width="1"'
                    + (' stroke-dasharray="5 4"' if dash else "")
                    + "/>"
                )

        title = (
            stair["id"] + " " + (floor or stair["section_kind"]) + " — " + report["drafting_status"]
        )
        parts.append(f'<text x="{offset + 25}" y="30" font-size="19">' + escape(title) + "</text>")
        parts.append(
            f'<text x="{offset + 25}" y="54" font-size="12">Proposed geometry / no CAD authorization / units m</text>'
        )
        if view == "plan":
            pv = next(v for v in stair["plan_views"] if v["floor_id"] == floor)
            cut = pv["cut_elevation_m"]
            ascending = floor == stair["source_floor"]
            parts.append(
                f'<text x="{offset + 25}" y="75" font-size="12">Absolute plan cut: '
                + escape(str(cut))
                + "; above-cut geometry dashed</text>"
            )
            parts.append(
                f'<text x="{offset + 25}" y="97" font-size="12">Green entry '
                + escape(stair["source_floor"] + " z=" + str(stair["source_elevation_m"]))
                + " m; purple exit "
                + escape(stair["destination_floor"] + " z=" + str(stair["final_elevation_m"]))
                + " m</text>"
            )
            for r in rooms:
                polygon(r["clear_floor_geometry"], "#e2f6e8")
            for wall in walls:
                if (
                    wall["floor_id"] == floor
                    and cut is not None
                    and wall["bottom_m"] <= cut < wall["top_m"]
                ):
                    polygon(wall["geometry"], "#424e60")
            for opening in source["openings"]:
                if opening["floor_id"] != floor:
                    continue
                for key in ["frame_outline", "open_leaf"]:
                    if key in opening["primitives"]:
                        polygon(opening["primitives"][key], "#60cfdf", "#008bac")
                arc = opening["primitives"].get("swing_arc")
                if arc:
                    a = xy(arc["start"])
                    b = xy(arc["end"])
                    radius = arc["radius_m"] * scale
                    sweep = 0 if arc["rotation"] == "ccw" else 1
                    parts.append(
                        f'<path d="M {a[0]} {a[1]} A {radius} {radius} 0 0 {sweep} {b[0]} {b[1]}" fill="none" stroke="#008bac"/>'
                    )
            polygon(stair["envelope"], "none", "#bd9820", True)
            for surface in stair["surfaces"]:
                above = cut is None or surface["elevation_m"] > cut
                polygon(surface["geometry"], "#eef1ff" if above else "#c5d0f6", "#526cba", above)
                if spec.get("number_steps") and surface["kind"] == "tread":
                    p = shape_set(surface["geometry"]).representative_point()
                    f = next(f for f in stair["flights"] if f["id"] == surface["flight_id"])
                    u = f["direction"]
                    normal = (-u[1], u[0])
                    point = [
                        p.x + normal[0] * f["width_m"] * 0.28,
                        p.y + normal[1] * f["width_m"] * 0.28,
                    ]
                    text(point, surface["id"].rsplit("-T", 1)[-1], size=8, dy=3, anchor="middle")
                elif surface["kind"] == "landing":
                    path = (
                        surface["walking_line"]
                        if ascending
                        else list(reversed(surface["walking_line"]))
                    )
                    line(path, "#0b689c", False, 1.5)
            for f in stair["flights"]:
                path = f["walking_line"] if ascending else list(reversed(f["walking_line"]))
                u = [v if ascending else -v for v in f["direction"]]
                end = path[-1]
                normal = (-u[1], u[0])
                direction = "UP" if ascending else "DOWN"
                parts.append(
                    '<g class="stair-direction" data-floor="'
                    + escape(floor)
                    + '" data-flight="'
                    + escape(f["id"])
                    + '" data-direction="'
                    + direction
                    + '">'
                )
                line(path, "#0b689c", False, 2)
                line(
                    [
                        [end[i] - u[i] * 0.18 + normal[i] * 0.08 for i in (0, 1)],
                        end,
                        [end[i] - u[i] * 0.18 - normal[i] * 0.08 for i in (0, 1)],
                    ],
                    "#0b689c",
                    False,
                    2,
                )
                parts.append("</g>")
                point = [path[0][i] - u[i] * 0.25 for i in (0, 1)]
                text(
                    point,
                    direction + " " + f["id"],
                    "#064f7b",
                    10,
                    dy=-5,
                    anchor="end" if u[0] > 0 else "start",
                )
            for opening in spec["floor_openings"]:
                if opening["floor_id"] == floor:
                    polygon(opening["geometry"], "none", "#b833a9", True)
            for collision in report["sources"].get("collision_regions", []):
                if collision["stair_id"] == stair["id"]:
                    polygon(collision["geometry"], "#ffb7b7", "#ca1515")
            for point, color in [
                (stair["entry_point"], "#087b47"),
                (stair["exit_point"], "#b833a9"),
            ]:
                x, y = xy(point)
                parts.append(f'<circle cx="{x:.12g}" cy="{y:.12g}" r="3" fill="{color}"/>')
        else:
            paths = []
            for f in stair["flights"]:
                paths.append((f["id"], LineString(f["walking_line"]), f["section_profile"][0][0]))
            for surface in stair["surfaces"]:
                if surface["kind"] == "landing":
                    section = next(s for s in stair["sections"] if s["id"] == surface["id"])
                    paths.append(
                        (
                            surface["id"],
                            LineString(surface["walking_line"]),
                            section["profile"][0][0],
                        )
                    )
                elif surface["kind"] == "arrival":
                    section = next((s for s in stair["sections"] if s["id"] == surface["id"]), None)
                    if section:
                        paths.append(
                            (
                                surface["id"],
                                LineString(
                                    [stair["flights"][-1]["walking_line"][-1], stair["exit_point"]]
                                ),
                                section["profile"][0][0],
                            )
                        )
            for _, path, start in paths:
                for obstruction in obstructions:
                    hit = path.intersection(shape_set(obstruction["geometry"]))
                    pieces = list(hit.geoms) if hasattr(hit, "geoms") else [hit]
                    for g in pieces:
                        if g.is_empty or g.geom_type != "LineString":
                            continue
                        ends = sorted(path.project(Point(p)) for p in (g.coords[0], g.coords[-1]))
                        lo, hi = start + ends[0], start + ends[-1]
                        if hi > lo:
                            polygon(
                                encode(box(lo, obstruction["bottom_m"], hi, obstruction["top_m"])),
                                "#dadada",
                                "#777",
                            )
            for z, label in [
                (stair["source_elevation_m"], "source FFL"),
                (stair["destination_elevation_m"], "destination FFL"),
            ]:
                line([[bounds[0], z], [bounds[2], z]], "#777", True)
                text([bounds[0], z], label + " " + str(z) + " m", dy=-10)
            opening_labels = {}
            for _, path, start in paths:
                for opening in spec["floor_openings"]:
                    if stair["id"] not in opening["stair_ids"] or opening["floor_id"] not in levels:
                        continue
                    hit = path.intersection(shape_set(opening["geometry"]))
                    pieces = list(hit.geoms) if hasattr(hit, "geoms") else [hit]
                    for g in pieces:
                        if g.is_empty or g.geom_type != "LineString":
                            continue
                        ends = sorted(path.project(Point(p)) for p in (g.coords[0], g.coords[-1]))
                        lo, hi = start + ends[0], start + ends[-1]
                        z = float(levels[opening["floor_id"]])
                        line([[lo, z], [hi, z]], "#b833a9", True, 2)
                        old = opening_labels.get(opening["id"], (lo, hi, z))
                        opening_labels[opening["id"]] = (min(old[0], lo), max(old[1], hi), z)
            for name, (lo, hi, z) in opening_labels.items():
                text([(lo + hi) / 2, z], name, "#b833a9", 10, dy=16, anchor="middle")
            for section in stair["sections"]:
                line(section["profile"], "#214882", False, 2)
            if spec.get("number_steps"):
                for f in stair["flights"]:
                    for j, tread in enumerate(f["treads"]):
                        text(
                            [
                                f["section_profile"][0][0] + (j + 0.5) * f["tread_depth_m"],
                                tread["elevation_m"],
                            ],
                            j + 1,
                            "#214882",
                            8,
                            dy=-4,
                            anchor="middle",
                        )
            measures = [
                m
                for m in report["headroom"].get("measurements", [])
                if m["stair_id"] == stair["id"]
            ]
            minimum = (
                min(
                    measures, key=lambda m: (m["clearance_m"], m["surface_id"], m["obstruction_id"])
                )
                if measures
                else None
            )
            if minimum:
                surface = next(s for s in stair["surfaces"] if s["id"] == minimum["surface_id"])
                wanted = surface["flight_id"] if surface["kind"] == "tread" else surface["id"]
                record = next((p for p in paths if p[0] == wanted), None)
                if record:
                    location = Point(minimum["location_m"])
                    x = record[2] + record[1].project(location)
                    lateral = record[1].distance(location)
                    line(
                        [[x, minimum["walking_elevation_m"]], [x, minimum["underside_m"]]],
                        "#b12323",
                        lateral > 0,
                        2,
                    )
                    screen = xy([x, minimum["underside_m"]])
                    anchor = "end" if screen[0] > offset + 700 else "start"
                    text(
                        [x, minimum["underside_m"]],
                        str(minimum["clearance_m"]) + " m known min",
                        "#b12323",
                        10,
                        dx=-8 if anchor == "end" else 8,
                        dy=-8,
                        anchor=anchor,
                    )
                    label = (
                        "Witness XY "
                        + str(minimum["location_m"])
                        + (
                            "; projected from lateral offset " + format(lateral, ".3g") + " m"
                            if lateral > 0
                            else "; on supplied section path"
                        )
                    )
                    parts.append(
                        f'<text x="{offset + 25}" y="1055" font-size="11">'
                        + escape(label)
                        + "</text>"
                    )
            parts.append(
                f'<text x="{offset + 25}" y="97" font-size="12">Headroom: '
                + escape(report["headroom"].get("status", "UNKNOWN"))
                + "; continuous modeled area scope</text>"
            )
        parts.append(
            f'<line x1="{offset + 65}" y1="950" x2="{offset + 65 + scale:.12g}" y2="950" stroke="black" stroke-width="2"/>'
        )
        parts.append(f'<text x="{offset + 65}" y="970" font-size="12">1 m / uniform scale</text>')
        messages = wrap(" / ".join(sorted({e["code"] for e in report["errors"]})), width=110)
        for row, message in enumerate(messages[:3]):
            parts.append(
                f'<text x="{offset + 25}" y="{1000 + row * 14}" font-size="11">'
                + escape(message)
                + "</text>"
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
