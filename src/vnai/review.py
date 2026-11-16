"""Geometry checks and explicit non-evaluation of unapproved specialist rules."""

from datetime import date

from vnai import __version__
from vnai.geometry import area_m2, polygon_mm, validate_plan_structure
from vnai.orientation import azimuth_octant

AREA_TARGET_TOLERANCE = 0.05  # project QA threshold, NOT a building regulation
AREA_OVERLAP_TOLERANCE_M2 = 0.0001


def review_plan(plan: dict) -> dict:
    validate_plan_structure(plan)
    site = plan["site"]
    site_polygon = polygon_mm(site["outline_mm"], "site")
    checks: list[dict] = []
    levels: list[dict] = []
    measured_site_m2 = round(area_m2(site_polygon), 3)

    for level in plan["levels"]:
        rooms: list[dict] = []
        polygons: list[tuple[str, object]] = []
        for room in level["rooms"]:
            shape = polygon_mm(room["polygon_mm"], room["id"])
            area = area_m2(shape)
            entry = {
                "id": room["id"],
                "name": room.get("name", room["id"]),
                "area_m2": round(area, 3),
                "target_area_m2": room.get("target_area_m2"),
                "measurement": "net area of supplied polygon, NOT verified finished clear area",
            }
            rooms.append(entry)
            if not site_polygon.buffer(0.01).covers(shape):
                checks.append(
                    {
                        "status": "WARNING",
                        "code": "ROOM_OUTSIDE_SITE",
                        "level": level["id"],
                        "room_id": room["id"],
                        "message": "Room polygon extends beyond site outline; not a legal setback check.",
                    }
                )
            target = room.get("target_area_m2")
            if target is not None and abs(area - target) / target > AREA_TARGET_TOLERANCE:
                checks.append(
                    {
                        "status": "WARNING",
                        "code": "ROOM_AREA_TARGET_DELTA",
                        "level": level["id"],
                        "room_id": room["id"],
                        "message": f"Measured {area:.3f} m² differs by >5% from brief {target:.3f} m².",
                    }
                )
            for previous_id, previous_shape in polygons:
                intersection_m2 = area_m2(shape.intersection(previous_shape))
                if intersection_m2 > AREA_OVERLAP_TOLERANCE_M2:
                    checks.append(
                        {
                            "status": "WARNING",
                            "code": "ROOM_OVERLAP",
                            "level": level["id"],
                            "room_id": room["id"],
                            "other_room_id": previous_id,
                            "intersection_m2": round(intersection_m2, 3),
                            "message": "Room polygons overlap in same level (positive shared area).",
                        }
                    )
            polygons.append((room["id"], shape))
        levels.append({"id": level["id"], "room_areas": rooms})

    if not any(level["room_areas"] for level in levels):
        checks.append(
            {"status": "NEEDS_DATA", "code": "NO_ROOMS", "message": "No room polygons provided."}
        )

    frontage = site.get("frontage_facing_degrees")
    bearing_label: str | None = None
    if frontage is not None:
        bearing_label = azimuth_octant(frontage)
    else:
        checks.append(
            {
                "status": "NEEDS_DATA",
                "code": "FRONTAGE_BEARING_MISSING",
                "message": "Cannot assess cardinal frontage without measured bearing.",
            }
        )

    if site.get("true_north_degrees") is None:
        checks.append(
            {
                "status": "NEEDS_DATA",
                "code": "DRAWING_NORTH_MISSING",
                "message": "Orientation of true North in drawing coordinates must be confirmed.",
            }
        )
    else:
        # This is not used to infer frontage from polygon coordinates.
        azimuth_octant(site["true_north_degrees"])

    return {
        "project_id": plan.get("project_id", "unnamed"),
        "created_on": date.today().isoformat(),
        "engine_version": __version__,
        "design_stage": plan.get("design_stage", "unspecified"),
        "geometry": {
            "status": "MEASURED",
            "site_area_m2": measured_site_m2,
            "level_room_areas": levels,
            "method": "Shapely polygon areas using coordinates in mm; no wall/clearance inference",
        },
        "site_orientation": {
            "status": "MEASURED" if bearing_label is not None else "NEEDS_DATA",
            "frontage_facing_octant": bearing_label,
            "true_north_degrees_in_drawing": site.get("true_north_degrees"),
            "note": "Geographic bearings only; not Bát Trạch or feng shui calculation",
        },
        "fengshui_advisory": {
            "status": "NOT_EVALUATED",
            "reason": "No feng shui formulas approved from checked editions in v0.1.0",
            "sources": ["FENG-NTD-2011", "FENG-BAT-TRACH-MINH-KINH"],
        },
        "standards_review": {
            "status": "NOT_EVALUATED",
            "reason": "No source-clause-specific technical rules approved in v0.1.0",
            "sources": ["STD-TCVN13967-2024", "STD-QCVN02-2022"],
            "cad_modification_allowed": False,
        },
        "findings": checks,
        "limitations": [
            "Concept geometry only; no approved architectural construction documents.",
            "Room polygons are not necessarily net clear finished room area.",
            "No door, circulation, stair, structure, MEP, or climate simulations.",
            "Traditional Feng Shui interpretations are not empirically verified predictions.",
        ],
    }


def review_markdown(report: dict) -> str:
    lines = [
        f"# Geometry & research review — {report['project_id']}",
        "",
        f"Engine version: `{report['engine_version']}` · {report['created_on']}",
        "",
        "## Measured geometry (mm source coordinates)",
        f"Site polygon: **{report['geometry']['site_area_m2']:.3f} m²**",
        "",
        "| Level | Room | Polygon area (m²) | Brief target (m²) |",
        "|---|---|---:|---:|",
    ]
    for level in report["geometry"]["level_room_areas"]:
        for room in level["room_areas"]:
            target = room["target_area_m2"]
            lines.append(
                f"| {level['id']} | {room['name'].replace('|', '/')} | "
                f"{room['area_m2']:.3f} | {target if target is not None else '—'} |"
            )
    lines += [
        "",
        "## Findings and missing data",
    ]
    if not report["findings"]:
        lines.append("No geometry warnings from the supported subset; NOT a construction approval.")
    for finding in report["findings"]:
        lines.append(
            f"- **{finding['status']} [{finding['code']}]**: {finding['message']}"
        )
    lines += [
        "",
        "## Distinct specialist reviews",
        "- Feng Shui: **NOT_EVALUATED** — source-specific formulas have not been approved.",
        "- Standards: **NOT_EVALUATED** — no clause-level technical checker approved.",
        "",
        "## Limitations",
    ]
    lines.extend(f"- {text}" for text in report["limitations"])
    return "\n".join(lines) + "\n"
