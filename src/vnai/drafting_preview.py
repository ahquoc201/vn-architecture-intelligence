"""Scale-consistent SVG drawing composition and Markdown drafting reports."""

from html import escape
import json
import math
from typing import Any


def _linetype_dasharray(linetype: str) -> str:
    return {
        "CONTINUOUS": "",
        "DASHED": "6 4",
        "DASHDOT": "10 3 2 3",
        "CENTER": "12 3 3 3",
        "DOTTED": "2 3",
    }.get(linetype, "")


def _n(val: float) -> str:
    return format(0.0 if abs(val) < 1e-12 else val, ".6g")


def _active_layers(
    layer_policy: dict[str, Any],
    include_layers: set[str] | None,
    hide_layers: set[str] | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in layer_policy.get("layers", []):
        name = row["name"]
        vis = bool(row.get("visible", True))
        if include_layers is not None:
            vis = name in include_layers
        if hide_layers is not None and name in hide_layers:
            vis = False
        result[name] = {**row, "effective_visible": vis}
    return result


def drafting_svg(
    report: dict[str, Any],
    *,
    view: str = "sheet",
    floor: str | None = None,
    include_layers: set[str] | None = None,
    hide_layers: set[str] | None = None,
) -> str:
    """Render actual CAD-neutral IR primitives into a scale-consistent architectural SVG."""
    views = report.get("model_space", {}).get("views", [])
    if not views:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="140">'
            '<rect width="100%" height="100%" fill="white"/>'
            f'<text x="24" y="50" font-family="Arial, sans-serif" font-size="14">No drafting views available ({escape(report.get("drafting_status", "UNKNOWN"))}). CAD writes: false.</text>'
            "</svg>\n"
        )

    if floor is not None:
        selected = [v for v in views if v.get("floor_id") == floor or v.get("view_id") == floor]
    elif view == "plan":
        selected = [v for v in views if v["view_kind"] == "floor_plan"]
    elif view == "section":
        selected = [v for v in views if v["view_kind"] == "stair_section"]
    else:
        selected = list(views)

    if not selected:
        raise ValueError(f"Requested preview view={view!r} / floor={floor!r} matched no generated views.")

    drawing_units = report["unit_policy"]["drawing_units"]
    unit_to_mm = 1.0 if drawing_units == "mm" else 1000.0
    scale_denom = float(report["paper_space"]["scale_denominator"])
    # 4.0 px per paper mm provides crisp screen readability while strictly tracking paper scale.
    px_per_paper_mm = 4.0
    px_per_model = (unit_to_mm / scale_denom) * px_per_paper_mm

    layers_map = _active_layers(report["layer_policy"], include_layers, hide_layers)
    style = report["style"]
    font_family = style["font_family"]
    border_cfg = report["paper_space"].get("border", {})
    border_enabled = bool(border_cfg.get("enabled", True))

    # Compute uniform panel frames from view bounds
    margin_pad = 48.0
    gap_x = 40.0
    header_h = 54.0
    footer_h = 96.0 if border_enabled else 52.0
    panel_specs = []
    cursor_x = margin_pad
    max_panel_h = 0.0
    for v in selected:
        b = v["bounds"]
        mw = max(b["max_x"] - b["min_x"], 1.0)
        mh = max(b["max_y"] - b["min_y"], 1.0)
        pw = max(mw * px_per_model + 90.0, 320.0)
        ph = max(mh * px_per_model + 90.0, 260.0)
        panel_specs.append((v, cursor_x, pw, ph, b))
        cursor_x += pw + gap_x
        max_panel_h = max(max_panel_h, ph)

    sheet_w = max(cursor_x - gap_x + margin_pad, 620.0)
    sheet_h = header_h + max_panel_h + footer_h + margin_pad

    layer_order = [
        "A-HATCH",
        "A-GRID",
        "A-STAIR-ABOVE",
        "A-STAIR",
        "A-WALL-INT",
        "A-WALL-EXT",
        "A-WIND",
        "A-DOOR-SWING",
        "A-DOOR",
        "A-DIMS",
        "A-LEVEL",
        "A-SECT",
        "A-ROOM-TEXT",
        "A-OPENING-TAG",
        "A-REVIEW",
    ]
    for lname in layers_map:
        if lname not in layer_order:
            layer_order.append(lname)

    visible_names = sorted(k for k, v in layers_map.items() if v["effective_visible"])
    hidden_names = sorted(k for k, v in layers_map.items() if not v["effective_visible"])

    meta = {
        "engine_version": report["engine_version"],
        "drawing_ir_digest": report["drawing_ir_digest"],
        "geometry_and_dimensions_digest": report["geometry_and_dimensions_digest"],
        "model_space_digest": report["model_space_digest"],
        "presentation_digest": report["presentation_digest"],
        "source_revision_id": report["source_digests"].get("source_revision_id"),
        "view_ids": [v["view_id"] for v in selected],
        "scale_label": report["paper_space"]["scale_label"],
        "scale_denominator": scale_denom,
        "drawing_units": drawing_units,
        "px_per_paper_mm": px_per_paper_mm,
        "px_per_model_unit": px_per_model,
        "visible_layers": visible_names,
        "hidden_layers": hidden_names,
        "cad_writes_permitted": False,
        "architect_approval": "NOT_GRANTED",
    }

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(sheet_w)}" height="{_n(sheet_h)}" '
        f'viewBox="0 0 {_n(sheet_w)} {_n(sheet_h)}" preserveAspectRatio="xMidYMid meet" '
        f'font-family="{escape(font_family)}">',
        "<title>Proposed Conceptual Architectural Drawing — Not For Construction</title>",
        "<metadata>" + escape(json.dumps(meta, sort_keys=True)) + "</metadata>",
        "<defs>"
        '<pattern id="hatch-ansi31" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<rect width="8" height="8" fill="#e5e7eb"/>'
        '<line x1="0" y1="0" x2="0" y2="8" stroke="#9ca3af" stroke-width="1"/>'
        "</pattern>"
        "</defs>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    if border_enabled:
        parts.append(
            f'<rect x="14" y="14" width="{_n(sheet_w - 28)}" height="{_n(sheet_h - 28)}" '
            'fill="none" stroke="#111827" stroke-width="1.6"/>'
        )
        parts.append(
            f'<rect x="20" y="20" width="{_n(sheet_w - 40)}" height="{_n(sheet_h - 40)}" '
            'fill="none" stroke="#374151" stroke-width="0.6"/>'
        )

    status_color = "#166534" if report["drafting_status"] == "GENERATED" else "#b91c1c"
    parts.append(
        f'<text x="32" y="42" font-size="14" font-weight="bold" fill="#111827">'
        f'{escape(str(border_cfg.get("project_title", "VNAI Architectural Drafting")))} '
        f'| Scale {escape(report["paper_space"]["scale_label"])} (project preference) | Units: {escape(drawing_units)}</text>'
    )
    parts.append(
        f'<text x="{_n(sheet_w - 32)}" y="42" font-size="11" font-weight="bold" text-anchor="end" fill="{status_color}">'
        f'Status: {escape(report["drafting_status"])} | Collisions: {len(report["collisions"])}</text>'
    )

    for v, left_x, pw, ph, bounds in panel_specs:
        # Center model bounds inside panel horizontally and vertically
        mw = bounds["max_x"] - bounds["min_x"]
        mh = bounds["max_y"] - bounds["min_y"]
        ox = left_x + (pw - mw * px_per_model) / 2.0
        oy = header_h + (max_panel_h - mh * px_per_model) / 2.0 + mh * px_per_model

        def xy(pt: list[float]) -> tuple[float, float]:
            return (
                ox + (pt[0] - bounds["min_x"]) * px_per_model,
                oy - (pt[1] - bounds["min_y"]) * px_per_model,
            )

        # Subtle panel frame & title
        parts.append(
            f'<rect x="{_n(left_x)}" y="{_n(header_h)}" width="{_n(pw)}" height="{_n(max_panel_h)}" '
            'fill="#ffffff" stroke="#e5e7eb" stroke-width="0.8"/>'
        )
        sub_kind = f" ({v['section_kind']})" if v.get("section_kind") else ""
        parts.append(
            f'<text x="{_n(left_x + 12)}" y="{_n(header_h + 20)}" font-size="12" font-weight="bold" fill="#111827">'
            f'{escape(v["view_id"])}: {escape(v["title"] + sub_kind)}</text>'
        )

        # Group entities by layer order
        by_layer: dict[str, list[dict[str, Any]]] = {}
        for ent in v["entities"]:
            by_layer.setdefault(ent["layer"], []).append(ent)

        for lname in layer_order:
            linfo = layers_map.get(lname)
            if not linfo or not linfo["effective_visible"]:
                continue
            ents = by_layer.get(lname, [])
            if not ents:
                continue
            color = linfo["svg_color"]
            sw = max(float(linfo["lineweight_mm"]) * 3.2, 0.55)
            dash = _linetype_dasharray(linfo["linetype"])
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(f'<g class="cad-layer" data-layer="{escape(lname)}" data-view="{escape(v["view_id"])}">')

            for ent in ents:
                et = ent["entity_type"]
                c = ent["coordinates"]
                m = ent.get("metadata", {})

                if et == "HATCH":
                    rings = [c["exterior"], *c.get("holes", [])]
                    d_cmds = []
                    for ring in rings:
                        pts = [xy(p) for p in ring]
                        d_cmds.append("M " + " L ".join(_n(x) + " " + _n(y) for x, y in pts) + " Z")
                    parts.append(
                        f'<path d="{" ".join(d_cmds)}" fill="url(#hatch-ansi31)" fill-rule="evenodd" stroke="none" opacity="0.85"/>'
                    )

                elif et == "LINE":
                    x1, y1 = xy(c["start"])
                    x2, y2 = xy(c["end"])
                    parts.append(
                        f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
                        f'stroke="{color}" stroke-width="{_n(sw)}"{dash_attr}/>'
                    )

                elif et == "POLYLINE":
                    if c.get("closed"):
                        rings = [c["exterior"], *c.get("holes", [])]
                        d_cmds = []
                        for ring in rings:
                            pts = [xy(p) for p in ring]
                            d_cmds.append("M " + " L ".join(_n(x) + " " + _n(y) for x, y in pts) + " Z")
                        fill = "#f3f4f6" if m.get("opening_part") == "frame" else "#fef2f2" if m.get("role") == "fixed_obstacle" else "none"
                        parts.append(
                            f'<path d="{" ".join(d_cmds)}" fill="{fill}" fill-rule="evenodd" '
                            f'stroke="{color}" stroke-width="{_n(sw)}"{dash_attr}/>'
                        )
                    else:
                        pts_str = " ".join(_n(x) + "," + _n(y) for x, y in map(xy, c["exterior"]))
                        parts.append(
                            f'<polyline points="{pts_str}" fill="none" stroke="{color}" '
                            f'stroke-width="{_n(sw)}"{dash_attr}/>'
                        )

                elif et == "ARC":
                    sx, sy = xy(c["start_point"])
                    ex, ey = xy(c["end_point"])
                    r_px = float(c["radius"]) * px_per_model
                    sweep = 0 if c.get("rotation") == "ccw" else 1
                    parts.append(
                        f'<path d="M {_n(sx)} {_n(sy)} A {_n(r_px)} {_n(r_px)} 0 0 {sweep} {_n(ex)} {_n(ey)}" '
                        f'fill="none" stroke="{color}" stroke-width="{_n(sw)}"{dash_attr}/>'
                    )

                elif et == "CIRCLE":
                    cx, cy = xy(c["center"])
                    r_px = float(c["radius"]) * px_per_model
                    parts.append(
                        f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r_px)}" fill="white" '
                        f'stroke="{color}" stroke-width="{_n(sw)}"{dash_attr}/>'
                    )

                elif et == "TEXT":
                    ix, iy = xy(c["insert"])
                    fs = max(float(m.get("height", 200.0)) * px_per_model, 7.0)
                    anchor = m.get("anchor", "middle")
                    rot = float(m.get("rotation_deg", 0.0))
                    tf = f' transform="rotate({_n(-rot)} {_n(ix)} {_n(iy)})"' if rot else ""
                    parts.append(
                        f'<text x="{_n(ix)}" y="{_n(iy)}" dy="0.35em" font-size="{_n(fs)}" '
                        f'text-anchor="{anchor}" fill="{color}"{tf}>{escape(str(m.get("text", "")))}</text>'
                    )

                elif et == "MTEXT":
                    ix, iy = xy(c["insert"])
                    fs = max(float(m.get("height", 200.0)) * px_per_model, 8.0)
                    lines = [str(line) for line in m.get("lines", [])]
                    anchor = m.get("anchor", "middle")
                    line_px = fs * float(m.get("line_spacing", 1.25))
                    start_y = iy - ((len(lines) - 1) * line_px) / 2.0
                    tspans = []
                    for i, line_txt in enumerate(lines):
                        weight = "bold" if i == 0 else "normal"
                        fill_line = "#b91c1c" if "CONFLICT" in line_txt else color
                        tspans.append(
                            f'<tspan x="{_n(ix)}" y="{_n(start_y + i * line_px)}" font-weight="{weight}" fill="{fill_line}">'
                            f'{escape(line_txt)}</tspan>'
                        )
                    parts.append(
                        f'<text font-size="{_n(fs)}" text-anchor="{anchor}">{"".join(tspans)}</text>'
                    )

                elif et == "DIMENSION":
                    lsx, lsy = xy(c["line_start"])
                    lex, ley = xy(c["line_end"])
                    tpx, tpy = xy(c["text_point"])
                    # Extension lines
                    for ext in c.get("extension_lines", []):
                        esx, esy = xy(ext["start"])
                        eex, eey = xy(ext["end"])
                        parts.append(
                            f'<line x1="{_n(esx)}" y1="{_n(esy)}" x2="{_n(eex)}" y2="{_n(eey)}" '
                            f'stroke="{color}" stroke-width="0.5"/>'
                        )
                    # Dimension line
                    parts.append(
                        f'<line x1="{_n(lsx)}" y1="{_n(lsy)}" x2="{_n(lex)}" y2="{_n(ley)}" '
                        f'stroke="{color}" stroke-width="0.7"/>'
                    )
                    # Architectural 45° diagonal tick marks at ends
                    tick = max(float(m.get("arrow_size", 150.0)) * px_per_model * 0.65, 3.0)
                    for tx_end, ty_end in ((lsx, lsy), (lex, ley)):
                        parts.append(
                            f'<line x1="{_n(tx_end - tick)}" y1="{_n(ty_end + tick)}" '
                            f'x2="{_n(tx_end + tick)}" y2="{_n(ty_end - tick)}" '
                            f'stroke="{color}" stroke-width="1.1"/>'
                        )
                    fs = max(float(m.get("height", 200.0)) * px_per_model, 7.5)
                    rot_attr = (
                        f' transform="rotate(-90 {_n(tpx)} {_n(tpy)})"'
                        if m.get("orientation") == "vertical"
                        else ""
                    )
                    parts.append(
                        f'<text x="{_n(tpx)}" y="{_n(tpy)}" dy="0.3em" font-size="{_n(fs)}" '
                        f'text-anchor="middle" fill="{color}"{rot_attr}>'
                        f'{escape(str(m.get("display_text", "")))}</text>'
                    )

                elif et == "SYMBOL":
                    sk = m.get("symbol_kind")
                    if sk == "scale_bar":
                        bx, by = xy(c["insert"])
                        total_len = float(c["length"]) * px_per_model
                        half = total_len / 2.0
                        bh = 5.0
                        parts.append(f'<rect x="{_n(bx)}" y="{_n(by)}" width="{_n(half)}" height="{bh}" fill="#111827" stroke="#111827" stroke-width="0.6"/>')
                        parts.append(f'<rect x="{_n(bx + half)}" y="{_n(by)}" width="{_n(half)}" height="{bh}" fill="#ffffff" stroke="#111827" stroke-width="0.6"/>')
                        mid_val = _n(float(c["length"]) / 2.0)
                        end_val = _n(float(c["length"]))
                        parts.append(f'<text x="{_n(bx)}" y="{_n(by + 15)}" font-size="8" fill="#111827">0</text>')
                        parts.append(f'<text x="{_n(bx + half)}" y="{_n(by + 15)}" font-size="8" text-anchor="middle" fill="#111827">{mid_val}</text>')
                        parts.append(f'<text x="{_n(bx + total_len)}" y="{_n(by + 15)}" font-size="8" text-anchor="end" fill="#111827">{end_val} {escape(m.get("units", "mm"))} ({escape(report["paper_space"]["scale_label"])})</text>')
                    elif sk == "section_marker":
                        sx, sy = xy(c["start"])
                        ex, ey = xy(c["end"])
                        parts.append(f'<line x1="{_n(sx)}" y1="{_n(sy)}" x2="{_n(ex)}" y2="{_n(ey)}" stroke="{color}" stroke-width="1.4" stroke-dasharray="10 3 2 3"/>')
                        lx, ly = m.get("look_direction", [0, 1])
                        ux, uy = sx + lx * 10.0, sy - ly * 10.0
                        parts.append(f'<line x1="{_n(sx)}" y1="{_n(sy)}" x2="{_n(ux)}" y2="{_n(uy)}" stroke="{color}" stroke-width="1.6"/>')
                        parts.append(f'<circle cx="{_n(sx)}" cy="{_n(sy)}" r="7" fill="white" stroke="{color}" stroke-width="1.1"/>')
                        parts.append(f'<text x="{_n(sx)}" y="{_n(sy)}" dy="0.35em" font-size="8" font-weight="bold" text-anchor="middle" fill="{color}">{escape(str(m.get("label", "S")))}</text>')
                    elif sk in {"stair_direction_arrow", "slide_direction"}:
                        a = xy(c.get("from_point", c.get("direction_start")))
                        b = xy(c.get("to_point", c.get("direction_end")))
                        dx, dy = b[0] - a[0], b[1] - a[1]
                        length = math.hypot(dx, dy) or 1.0
                        ux, uy = dx / length, dy / length
                        nx, ny = -uy, ux
                        parts.append(
                            f'<path d="M {_n(b[0] - 8 * ux + 4 * nx)} {_n(b[1] - 8 * uy + 4 * ny)} '
                            f'L {_n(b[0])} {_n(b[1])} L {_n(b[0] - 8 * ux - 4 * nx)} {_n(b[1] - 8 * uy - 4 * ny)}" '
                            f'fill="none" stroke="{color}" stroke-width="1.4"/>'
                        )

                elif et == "BLOCK_REFERENCE":
                    ix, iy = xy(c["insert"])
                    bname = m.get("block_name")
                    if bname in {"TAG_DOOR", "TAG_WINDOW"}:
                        mark = str(m.get("mark", ""))
                        sub = str(m.get("dimension_label", ""))
                        bw = max(len(mark) * 5.2 + 8.0, 28.0)
                        bh = 13.0
                        rx = 6.0 if bname == "TAG_DOOR" else 1.5
                        parts.append(
                            f'<rect x="{_n(ix - bw / 2.0)}" y="{_n(iy - bh / 2.0)}" width="{_n(bw)}" height="{bh}" '
                            f'rx="{rx}" fill="white" stroke="{color}" stroke-width="0.9"/>'
                        )
                        parts.append(
                            f'<text x="{_n(ix)}" y="{_n(iy)}" dy="0.32em" font-size="7.5" font-weight="bold" '
                            f'text-anchor="middle" fill="{color}">{escape(mark)}</text>'
                        )
                        if sub:
                            parts.append(
                                f'<text x="{_n(ix)}" y="{_n(iy + 12.0)}" font-size="6.8" text-anchor="middle" fill="{color}">{escape(sub)}</text>'
                            )
                    elif bname == "SYM_LEVEL_MARK":
                        parts.append(
                            f'<polygon points="{_n(ix)},{_n(iy)} {_n(ix - 5)},{_n(iy - 8)} {_n(ix + 5)},{_n(iy - 8)}" '
                            f'fill="none" stroke="{color}" stroke-width="1.0"/>'
                        )
                        parts.append(
                            f'<line x1="{_n(ix - 6)}" y1="{_n(iy)}" x2="{_n(ix + 70)}" y2="{_n(iy)}" stroke="{color}" stroke-width="0.8"/>'
                        )
                        parts.append(
                            f'<text x="{_n(ix + 7)}" y="{_n(iy - 3)}" font-size="8" fill="{color}">{escape(str(m.get("label", "")))}</text>'
                        )
                    elif bname == "SYM_NORTH_ARROW":
                        deg = float(c.get("rotation_deg", 0.0))
                        parts.append(f'<g transform="translate({_n(ix)},{_n(iy)}) rotate({_n(deg)})">')
                        parts.append(f'<circle cx="0" cy="0" r="12" fill="white" stroke="{color}" stroke-width="1.0"/>')
                        parts.append(f'<polygon points="0,-11 -4,4 0,1 4,4" fill="{color}"/>')
                        parts.append(f'<text x="0" y="-15" font-size="9" font-weight="bold" text-anchor="middle" fill="{color}">N</text>')
                        parts.append("</g>")

            parts.append("</g>")

    # Bottom title block / governance notice
    foot_y = header_h + max_panel_h + 18.0
    parts.append(
        f'<text x="32" y="{_n(foot_y + 14)}" font-size="11" font-weight="bold" fill="#111827">'
        f'CONCEPTUAL / PROPOSED DRAWING ({escape(str(border_cfg.get("drawing_number", "A-101")))}) — NOT FOR CONSTRUCTION</text>'
    )
    parts.append(
        f'<text x="32" y="{_n(foot_y + 31)}" font-size="10" fill="#374151">'
        f'Architect Approval: {escape(report["architect_approval"])} | CAD Writes: false | '
        f'Standards/Feng Shui: NOT_EVALUATED | Engine v{escape(report["engine_version"])}</text>'
    )
    if report["collisions"]:
        parts.append(
            f'<text x="32" y="{_n(foot_y + 47)}" font-size="10" font-weight="bold" fill="#b91c1c">'
            f'Unresolved Annotation Collisions: {len(report["collisions"])} (highlighted on layer A-REVIEW)</text>'
        )
    elif report["unresolved_items"]:
        parts.append(
            f'<text x="32" y="{_n(foot_y + 47)}" font-size="10" fill="#92400e">'
            f'Unresolved Info: {escape("; ".join(u["code"] for u in report["unresolved_items"][:4]))}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def drafting_markdown(report: dict[str, Any]) -> str:
    """Produce a human-readable UTF-8 Markdown summary of the drafting IR."""
    lines = [
        "# Architectural Drafting & Annotation Report",
        "",
        f"- **Engine version**: `{report['engine_version']}`",
        f"- **Contract**: `{report['contract']}`",
        f"- **Drafting status**: `{report['drafting_status']}`",
        f"- **Construction readiness**: `{report['construction_readiness']}`",
        f"- **Architect approval**: `{report['architect_approval']}` (inherited: `{report['approval_inherited']}`)",
        f"- **CAD writes permitted**: `{report['cad_writes_permitted']}`",
        f"- **Standards / Feng Shui review**: `{report['standards_review']}` / `{report['fengshui_review']}`",
        f"- **Units / Paper scale**: `{report['unit_policy'].get('drawing_units')}` @ `{report['paper_space'].get('scale_label')}` ({report['paper_space'].get('scale_authority')})",
        f"- **Geometry & dimensions digest**: `{report['geometry_and_dimensions_digest']}`",
        f"- **Drawing IR digest**: `{report['drawing_ir_digest']}`",
        "",
        "## Views",
        "",
        "| View ID | Kind | Floor | Section Kind | Entities |",
        "|---|---|---|---|---|",
    ]
    for v in report.get("model_space", {}).get("views", []):
        lines.append(
            f"| {v['view_id']} | {v['view_kind']} | {v.get('floor_id') or '-'} | {v.get('section_kind') or '-'} | {len(v['entities'])} |"
        )

    lines += [
        "",
        "## Room Annotations (Clear vs Allocated)",
        "",
        "| Floor | Room ID | Display Name | Clear m² | Allocation m² | Basis | Leader Used |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report.get("annotations", {}).get("rooms", []):
        lines.append(
            f"| {r['floor_id']} | {r['room_id']} | {r['display_name']} | {r['clear_area_m2']:.4g} | {r['allocation_area_m2']:.4g} | {r['area_basis']} | {r['used_leader']} |"
        )

    lines += [
        "",
        "## Dimension Chains",
        "",
        "| Chain ID | Axis | Side | Segments Sum | Overall | Closure Status |",
        "|---|---|---|---|---|---|",
    ]
    for ch in report.get("dimension_chains", []):
        lines.append(
            f"| {ch['chain_id']} | {ch['axis']} | {ch['side']} | {ch['exact_segments_sum']} {ch['measurement_unit']} | {ch['exact_overall']} {ch['measurement_unit']} | {ch['closure_status']} |"
        )

    if report.get("unsupported_dimensions"):
        lines += ["", "## Unsupported Dimensions", ""]
        for u in report["unsupported_dimensions"]:
            lines.append(f"- `{u['code']}` ({u['entity_id']} / {u.get('floor_id')}): {u['reason']}")

    if report.get("collisions"):
        lines += [
            "",
            "## Unresolved Annotation Collisions",
            "",
            "| ID | View | Kind | Category | Entities |",
            "|---|---|---|---|---|",
        ]
        for c in report["collisions"]:
            lines.append(
                f"| {c['id']} | {c['view_id']} | {c['collision_kind']} | {c['category']} | {c['entity_a']} vs {c['entity_b']} |"
            )

    if report.get("unresolved_items"):
        lines += ["", "## Unresolved Information", ""]
        for item in report["unresolved_items"]:
            lines.append(f"- `{item.get('code')}`: {item.get('message')}")

    lines.append("")
    return "\n".join(lines)


def layers_markdown(layer_report: dict[str, Any]) -> str:
    """Produce a Markdown table of CAD layer policy and ezdxf mapping."""
    lines = [
        "# CAD Layer Policy Inventory",
        "",
        f"- **Policy version**: `{layer_report['policy_version']}`",
        f"- **Authority**: `{layer_report['authority']}`",
        f"- **Total entities**: `{layer_report['total_entities']}`",
        f"- **CAD writes permitted**: `{layer_report['cad_writes_permitted']}`",
        "",
        "| Layer | Category | ACI | Linetype | Lineweight mm | Visible | Plottable | Entities |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in layer_report.get("layers", []):
        lines.append(
            f"| {row['name']} | {row['entity_category']} | {row['aci_color']} | {row['linetype']} | {row['lineweight_mm']} | {row['visible']} | {row['plottable']} | {row['entity_count']} |"
        )
    lines.append("")
    return "\n".join(lines)
