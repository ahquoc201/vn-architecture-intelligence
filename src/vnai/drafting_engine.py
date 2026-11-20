"""Deterministic CAD-neutral architectural drafting and annotation engine."""

from copy import deepcopy
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.drafting_annotations import build_floor_plan_view, build_stair_section_view
from vnai.drafting_dimensions import extract_dimensions, verify_dimension_chain_closure
from vnai.drafting_ir import compute_view_bounds, default_blocks, validate_ir_entities
from vnai.drafting_layout import resolve_view_layout
from vnai.drafting_styles import (
    build_drawing_style,
    build_layer_policy,
    build_unit_policy,
    dec,
    validate_layer_policy,
)
from vnai.integrated_design import integrated_design
from vnai.opening_drafting import draft_openings
from vnai.opening_hosts import shape_set
from vnai.review_common import candidate_digest
from vnai.stair_drafting import draft_stairs
from vnai.walls import generate_walls

EXIT_CODES = {
    "GENERATED": 0,
    "INVALID_INPUT": 1,
    "INCOMPLETE": 3,
    "CONFLICT": 4,
    "UNSUPPORTED": 5,
}


def _normalize_input(
    payload: Any,
    *,
    config_override: dict[str, Any] | None = None,
    scale_override: float | None = None,
    units_override: str | None = None,
) -> dict[str, Any]:
    """Wrap recognized B1/B3/B4 inputs or reports cleanly into architectural-drafting-input-v1."""
    if not isinstance(payload, dict):
        raise ValueError("Drafting input must be a JSON object.")
    doc = deepcopy(payload)
    if doc.get("contract") == "architectural-drafting-input-v1":
        wrapped = doc
    elif doc.get("contract") == "integrated-design-v1":
        wrapped = {
            "schema_version": 1,
            "contract": "architectural-drafting-input-v1",
            "source": {"source_kind": "integrated_report", "payload": doc},
        }
    elif doc.get("contract") == "architectural-walls-v1":
        wrapped = {
            "schema_version": 1,
            "contract": "architectural-drafting-input-v1",
            "source": {"source_kind": "wall_report", "payload": doc},
        }
    elif doc.get("contract") == "opening-drafting-v1":
        wrapped = {
            "schema_version": 1,
            "contract": "architectural-drafting-input-v1",
            "source": {"source_kind": "opening_report", "payload": doc},
        }
    elif doc.get("contract") == "stair-drafting-v1":
        wrapped = {
            "schema_version": 1,
            "contract": "architectural-drafting-input-v1",
            "source": {"source_kind": "stair_report", "payload": doc},
        }
    elif "wall_specification" in doc and "generation" in doc:
        wrapped = {
            "schema_version": 1,
            "contract": "architectural-drafting-input-v1",
            "source": {"source_kind": "integrated_spec", "payload": doc, "refine": True},
        }
    else:
        return doc  # Let schema_check diagnose invalid contract/structure.

    if config_override:
        for key, val in deepcopy(config_override).items():
            if key in {"schema_version", "contract", "source"}:
                continue
            if isinstance(val, dict) and isinstance(wrapped.get(key), dict):
                wrapped[key] = {**wrapped[key], **val}
            else:
                wrapped[key] = val

    if scale_override is not None:
        ps = dict(wrapped.get("paper_space") or {})
        ps["scale_denominator"] = scale_override
        ps["scale_authority"] = "project_drawing_preference"
        wrapped["paper_space"] = ps
    if units_override is not None:
        up = dict(wrapped.get("unit_policy") or {})
        up["drawing_units"] = units_override
        wrapped["unit_policy"] = up
    return wrapped


def _resolve_source_context(source: dict[str, Any], flags: set[str], report: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve immutable architectural source models without mutating source geometry."""
    kind = source["source_kind"]
    payload = deepcopy(source["payload"])

    integrated_rep: dict[str, Any] | None = None
    walls_rep: dict[str, Any] | None = None
    openings_rep: dict[str, Any] | None = None
    stairs_rep: dict[str, Any] | None = None
    candidate: dict[str, Any] | None = None
    stair_spec: dict[str, Any] = {}
    wall_heights: list[dict[str, Any]] = []
    fixed_obstacles: list[dict[str, Any]] = []
    source_conflicts: list[dict[str, Any]] = []
    verification_coverage: dict[str, Any] | None = None
    revision_id: str | None = None

    if kind in {"integrated_report", "integrated_spec"}:
        if kind == "integrated_spec":
            integrated_rep = integrated_design(payload, refine=source.get("refine", True))
        else:
            integrated_rep = payload
        if integrated_rep.get("contract") != "integrated-design-v1":
            flags.add("invalid")
            issue(report, "errors", "INVALID_INTEGRATED_SOURCE", "source.payload", "Payload is not an integrated-design-v1 report.")
            return None
        pool = integrated_rep.get("candidates", []) + integrated_rep.get("originals", [])
        wanted_rev = source.get("candidate_revision_id")
        if wanted_rev:
            chosen = next((c for c in pool if c.get("revision_id") == wanted_rev), None)
            if chosen is None:
                flags.add("invalid")
                issue(report, "errors", "UNKNOWN_CANDIDATE_REVISION", "source.candidate_revision_id", f"Revision {wanted_rev} not found.")
                return None
        else:
            chosen = (integrated_rep.get("candidates") or integrated_rep.get("originals") or [None])[0]
        if chosen is None:
            flags.add("missing")
            issue(report, "missing_information", "NO_INTEGRATED_CANDIDATE", "source.payload", "Integrated report contains no candidate or original geometry.")
            return None
        candidate = chosen["candidate"]
        revision_id = chosen["revision_id"]
        walls_rep = chosen["engines"].get("walls") or {}
        openings_rep = chosen["engines"].get("openings") or {}
        stairs_rep = chosen["engines"].get("stairs") or {}
        src_in = integrated_rep.get("sources", {}).get("input", {})
        stair_spec = src_in.get("stair_specification", {})
        wall_heights = src_in.get("wall_heights", [])
        fixed_obstacles = src_in.get("review_template", {}).get("fixed_obstacles", [])
        source_conflicts = deepcopy(chosen.get("conflicts", []))
        verification_coverage = chosen.get("verification_coverage")
        for c in source_conflicts:
            if c.get("severity") == "FAILED":
                flags.add("conflict")
            elif c.get("severity") == "UNKNOWN":
                flags.add("missing")
            elif c.get("severity") == "UNSUPPORTED":
                flags.add("unsupported")

    elif kind in {"wall_report", "wall_spec"}:
        walls_rep = generate_walls(payload) if kind == "wall_spec" else payload
        if walls_rep.get("contract") != "architectural-walls-v1":
            flags.add("invalid")
            issue(report, "errors", "INVALID_WALL_SOURCE", "source.payload", "Payload is not an architectural-walls-v1 report.")
            return None
        if walls_rep.get("errors"):
            for err in walls_rep["errors"]:
                source_conflicts.append({"engine": "walls", "severity": "FAILED", **err})
            flags.add("conflict" if walls_rep.get("wall_status") == "CONFLICT" else "invalid")
        if walls_rep.get("missing_information"):
            for mi in walls_rep["missing_information"]:
                source_conflicts.append({"engine": "walls", "severity": "UNKNOWN", **mi})
            flags.add("missing")
        src_wall_in = walls_rep.get("sources", {}).get("input", {})
        candidate = src_wall_in.get("source", {}).get("replay", {}).get("review", {}).get("candidate")
        fixed_obstacles = src_wall_in.get("source", {}).get("replay", {}).get("review", {}).get("fixed_obstacles", [])
        revision_id = walls_rep.get("wall_revision_id")

    elif kind in {"opening_report", "opening_spec"}:
        openings_rep = draft_openings(payload) if kind == "opening_spec" else payload
        if openings_rep.get("contract") != "opening-drafting-v1":
            flags.add("invalid")
            issue(report, "errors", "INVALID_OPENING_SOURCE", "source.payload", "Payload is not an opening-drafting-v1 report.")
            return None
        walls_rep = openings_rep.get("sources", {}).get("wall_model") or {}
        if walls_rep:
            src_wall_in = walls_rep.get("sources", {}).get("input", {})
            candidate = src_wall_in.get("source", {}).get("replay", {}).get("review", {}).get("candidate")
            fixed_obstacles = src_wall_in.get("source", {}).get("replay", {}).get("review", {}).get("fixed_obstacles", [])
        revision_id = openings_rep.get("opening_revision_id")
        for err in openings_rep.get("errors", []):
            source_conflicts.append({"engine": "openings", "severity": "FAILED", **err})
            flags.add("conflict" if openings_rep.get("drafting_status") == "CONFLICT" else "invalid")
        for mi in openings_rep.get("missing_information", []):
            source_conflicts.append({"engine": "openings", "severity": "UNKNOWN", **mi})
            flags.add("missing")

    elif kind in {"stair_report", "stair_spec"}:
        stairs_rep = draft_stairs(payload) if kind == "stair_spec" else payload
        if stairs_rep.get("contract") != "stair-drafting-v1":
            flags.add("invalid")
            issue(report, "errors", "INVALID_STAIR_SOURCE", "source.payload", "Payload is not a stair-drafting-v1 report.")
            return None
        stair_spec = stairs_rep.get("sources", {}).get("input", {}).get("specification", {})
        openings_rep = stairs_rep.get("sources", {}).get("opening_model") or {}
        walls_rep = openings_rep.get("sources", {}).get("wall_model") or {}
        if walls_rep:
            src_wall_in = walls_rep.get("sources", {}).get("input", {})
            candidate = src_wall_in.get("source", {}).get("replay", {}).get("review", {}).get("candidate")
            fixed_obstacles = src_wall_in.get("source", {}).get("replay", {}).get("review", {}).get("fixed_obstacles", [])
        revision_id = stairs_rep.get("stair_revision_id")
        for err in stairs_rep.get("errors", []):
            source_conflicts.append({"engine": "stairs", "severity": "FAILED", **err})
            flags.add("conflict" if stairs_rep.get("drafting_status") == "CONFLICT" else "invalid")
        for mi in stairs_rep.get("missing_information", []):
            source_conflicts.append({"engine": "stairs", "severity": "UNKNOWN", **mi})
        if stairs_rep.get("geometry_status") == "NOT_GENERATED":
            flags.add("missing")

    # Floor IDs, envelopes, elevations, brief, and provenance
    floor_ids: list[str] = []
    floor_envelopes: dict[str, Polygon] = {}
    floor_elevations_m: dict[str, float] = {}
    brief: dict[str, Any] | None = None
    provenance = "source-grounded drafting IR; conceptual only"
    source_units = "m"

    if candidate:
        geom = candidate["geometry"]
        source_units = geom.get("units", "m")
        floor_ids = [f["id"] for f in geom.get("floors", [])]
        c_scale = 1.0 if source_units == "m" else 0.001
        footprint_poly = unary_union(
            [
                Polygon([(x * c_scale, y * c_scale) for x, y in p["exterior"]])
                for p in geom["polygons"]
                if p["role"] == "footprint"
            ]
        )
        for fid in floor_ids:
            outlines = [
                Polygon([(x * c_scale, y * c_scale) for x, y in p["exterior"]])
                for p in geom["polygons"]
                if p["role"] == "floor_outline" and p.get("floor_id") == fid
            ]
            floor_envelopes[fid] = unary_union(outlines) if outlines else footprint_poly
        for f in geom.get("floors", []):
            if f.get("elevation_m") is not None:
                floor_elevations_m[f["id"]] = float(f["elevation_m"])
        brief = geom.get("zoning", {}).get("brief")
        if geom.get("fixture_notice"):
            provenance = geom["fixture_notice"]
    elif walls_rep and walls_rep.get("floors"):
        source_units = walls_rep.get("source_units") or "m"
        floor_ids = [f["floor_id"] for f in walls_rep["floors"]]
        for f in walls_rep["floors"]:
            floor_envelopes[f["floor_id"]] = shape_set(f["permitted_envelope"])

    if stair_spec:
        u_scale = 1.0 if stair_spec.get("units", "m") == "m" else 0.001
        for lvl in stair_spec.get("levels", []):
            if lvl.get("confirmation") == "confirmed" and "finished_elevation" in lvl:
                floor_elevations_m[lvl["floor_id"]] = float(lvl["finished_elevation"]) * u_scale

    src_rev_digest = (
        revision_id
        or (walls_rep or {}).get("wall_revision_id")
        or (stairs_rep or {}).get("stair_revision_id")
        or canonical_digest(payload)
    )
    return {
        "source_kind": kind,
        "integrated_report": integrated_rep,
        "candidate": candidate,
        "walls_report": walls_rep or {},
        "openings_report": openings_rep or {},
        "stairs_report": stairs_rep or {},
        "stair_specification": stair_spec,
        "wall_heights": wall_heights,
        "fixed_obstacles": fixed_obstacles,
        "source_conflicts": source_conflicts,
        "conflicts": source_conflicts,
        "verification_coverage": verification_coverage,
        "floor_ids": floor_ids,
        "floor_envelopes": floor_envelopes,
        "floor_elevations_m": floor_elevations_m,
        "brief": brief,
        "source_units": source_units,
        "provenance": provenance,
        "source_revision_digest": src_rev_digest,
        "source_digests": {
            "source_input_digest": canonical_digest(payload),
            "source_candidate_digest": candidate_digest(candidate)
            if candidate
            else (walls_rep or {}).get("source_candidate_digest"),
            "source_revision_id": revision_id,
            "wall_revision_id": (walls_rep or {}).get("wall_revision_id"),
            "wall_geometry_digest": (walls_rep or {}).get("derived_geometry_digest"),
            "opening_revision_id": (openings_rep or {}).get("opening_revision_id"),
            "opening_geometry_digest": (openings_rep or {}).get("opening_geometry_digest"),
            "stair_revision_id": (stairs_rep or {}).get("stair_revision_id"),
            "verification_coverage": verification_coverage,
        },
    }


def _compute_digests(report: dict[str, Any]) -> dict[str, str]:
    """Compute invariant geometry/dimension digest separate from scale-dependent presentation."""
    geom_entities_by_view = []
    for view in report["model_space"]["views"]:
        geom_only = [
            {
                "entity_type": e["entity_type"],
                "layer": e["layer"],
                "coordinates": e["coordinates"],
                "source_geometry_id": e["source_geometry_id"],
            }
            for e in view["entities"]
            if e["entity_type"] in {"LINE", "POLYLINE", "ARC", "CIRCLE", "HATCH"}
            and e["layer"] in {"A-WALL-EXT", "A-WALL-INT", "A-DOOR", "A-DOOR-SWING", "A-WIND", "A-STAIR", "A-STAIR-ABOVE", "A-HATCH"}
        ]
        geom_entities_by_view.append(
            {
                "view_id": view["view_id"],
                "view_kind": view["view_kind"],
                "floor_id": view["floor_id"],
                "entities": geom_only,
            }
        )
    dims_core = [
        {
            "id": d["id"],
            "view_id": d["view_id"],
            "floor_id": d["floor_id"],
            "dimension_type": d["dimension_type"],
            "measurement_basis": d["measurement_basis"],
            "ref_point_1": d["ref_point_1"],
            "ref_point_2": d["ref_point_2"],
            "measured_value": d["measured_value"],
            "display_text": d["display_text"],
            "measurement_unit": d["measurement_unit"],
            "associated_entity_ids": d["associated_entity_ids"],
        }
        for d in report["dimensions"]
    ]
    geometry_and_dimensions_digest = canonical_digest(
        {
            "units": report["unit_policy"]["drawing_units"],
            "dimensions": dims_core,
            "dimension_chains": report["dimension_chains"],
            "views_geometry": geom_entities_by_view,
        }
    )
    model_space_digest = canonical_digest(report["model_space"])
    presentation_digest = canonical_digest(
        {
            "paper_space": report["paper_space"],
            "style": report["style"],
            "layer_policy": report["layer_policy"],
        }
    )
    drawing_ir_digest = canonical_digest(
        {
            "source_digests": report["source_digests"],
            "geometry_and_dimensions_digest": geometry_and_dimensions_digest,
            "model_space_digest": model_space_digest,
            "presentation_digest": presentation_digest,
            "annotations": report["annotations"],
            "reference_symbols": report["reference_symbols"],
            "collisions": report["collisions"],
            "unsupported_dimensions": report["unsupported_dimensions"],
            "unresolved_items": report["unresolved_items"],
        }
    )
    return {
        "geometry_and_dimensions_digest": geometry_and_dimensions_digest,
        "model_space_digest": model_space_digest,
        "presentation_digest": presentation_digest,
        "drawing_ir_digest": drawing_ir_digest,
    }


def generate_drafting(
    payload: Any,
    *,
    config_override: dict[str, Any] | None = None,
    scale_override: float | None = None,
    units_override: str | None = None,
) -> dict[str, Any]:
    """Run the complete deterministic architectural drafting pipeline."""
    result = new_report("architectural-drafting-v1")
    result.update(
        drafting_status="INVALID_INPUT",
        approval_inherited=False,
        architect_approval="NOT_GRANTED",
        construction_readiness="NOT_FOR_CONSTRUCTION_CONCEPTUAL_ONLY",
        source_kind=None,
        source_digests={},
        unit_policy={},
        paper_space={},
        layer_policy={},
        style={},
        model_space={"units": "mm", "blocks": {}, "views": []},
        dimensions=[],
        dimension_chains=[],
        unsupported_dimensions=[],
        annotations={
            "rooms": [],
            "openings": [],
            "stairs": [],
            "placement_adjustments": [],
        },
        reference_symbols={
            "north_arrow": None,
            "scale_bar": None,
            "reference_grid": None,
            "level_marks": [],
            "section_markers": [],
            "view_identifiers": [],
        },
        collisions=[],
        unresolved_items=[],
        source_conflicts=[],
        geometry_and_dimensions_digest=None,
        model_space_digest=None,
        presentation_digest=None,
        drawing_ir_digest=None,
        sources={},
    )
    try:
        wrapped = _normalize_input(
            payload,
            config_override=config_override,
            scale_override=scale_override,
            units_override=units_override,
        )
    except ValueError as exc:
        issue(result, "errors", "INVALID_DRAFTING_INPUT", "$", str(exc))
        return finish(result)

    if not schema_check(wrapped, "drafting-input.schema.json", result):
        return finish(result)

    flags: set[str] = set()
    result["source_kind"] = wrapped["source"]["source_kind"]
    result["sources"]["input"] = deepcopy(wrapped)

    context = _resolve_source_context(wrapped["source"], flags, result)
    if context is None:
        result["drafting_status"] = (
            "INVALID_INPUT"
            if "invalid" in flags
            else "INCOMPLETE"
            if "missing" in flags
            else "CONFLICT"
        )
        return finish(result)

    result["source_digests"] = context["source_digests"]
    result["source_conflicts"] = context["source_conflicts"]
    context["reference_grid"] = wrapped.get("reference_grid") or {}

    # Unit, paper-space, style and layer policies
    unit_policy = build_unit_policy(context["source_units"], wrapped.get("unit_policy"))
    ps_cfg = wrapped.get("paper_space") or {}
    scale_denom = float(ps_cfg.get("scale_denominator", 100))
    style = build_drawing_style(
        wrapped.get("style"),
        scale_denominator=scale_denom,
        drawing_units=unit_policy["drawing_units"],
        precision=unit_policy["display_precision"],
    )
    layer_policy = build_layer_policy(
        wrapped.get("layer_policy_overrides"), style_name=style["name"]
    )
    layer_issues = validate_layer_policy(layer_policy)
    if layer_issues:
        flags.add("invalid")
        for msg in layer_issues:
            issue(result, "errors", "INVALID_LAYER_POLICY", "layer_policy_overrides", msg)

    paper_space = {
        "scale_denominator": scale_denom,
        "scale_label": f"1:{int(scale_denom) if scale_denom.is_integer() else scale_denom}",
        "scale_authority": "project_drawing_preference",
        "border": ps_cfg.get(
            "border",
            {
                "enabled": True,
                "project_title": (context.get("candidate") or {}).get("geometry", {}).get(
                    "project_id", "VNAI Conceptual Drafting"
                ),
                "drawing_number": "A-101",
                "author_note": "PROPOSED / CONCEPTUAL — ARCHITECT REVIEW PENDING",
            },
        ),
        "paper_units": "mm",
    }

    result["unit_policy"] = unit_policy
    result["paper_space"] = paper_space
    result["layer_policy"] = layer_policy
    result["style"] = style
    result["model_space"]["units"] = unit_policy["drawing_units"]
    result["model_space"]["blocks"] = default_blocks(style["model_sizing"])

    # Determine requested views
    default_views = (
        ["stair_sections"]
        if wrapped["source"]["source_kind"] in {"stair_report", "stair_spec"}
        and not context["floor_ids"]
        else ["floor_plans", "stair_sections"]
    )
    requested_views = wrapped.get("views") or default_views
    annotation_options = wrapped.get("annotation_options") or {}
    placement_options = wrapped.get("placement_options") or {}

    # Opening mark consistency audit
    if context["openings_report"]:
        for err in context["openings_report"].get("errors", []):
            if err.get("code") == "CONFLICTING_OPENING_MARK":
                flags.add("conflict")
                issue(result, "errors", "CONFLICTING_OPENING_MARK", err.get("path", "openings"), err["message"])

    # Dimension extraction
    dimensions, chains, unsupported_dims, dim_missing = extract_dimensions(
        context, unit_policy, style, annotation_options
    )
    result["dimensions"] = dimensions
    result["dimension_chains"] = chains
    result["unsupported_dimensions"] = unsupported_dims
    for ch in chains:
        if not ch["geometric_closed"]:
            flags.add("conflict")
            issue(
                result,
                "errors",
                "DIMENSION_CHAIN_CLOSURE_MISMATCH",
                ch["chain_id"],
                f"Geometric closure error {ch['geometric_closure_error']} on {ch['chain_id']}.",
            )
        elif not ch["display_closed"]:
            issue(
                result,
                "warnings",
                "DIMENSION_CHAIN_DISPLAY_ROUNDING_DISCREPANCY",
                ch["chain_id"],
                f"Geometric chain {ch['chain_id']} closes exactly, while displayed rounded labels sum to {ch['displayed_segments_sum']} vs {ch['displayed_overall']}.",
            )
    for mi in dim_missing:
        result["unresolved_items"].append(mi)

    # Compose views -> extract primitives -> bounded placement & collision detection
    views_ir: list[dict[str, Any]] = []
    room_anns: list[dict[str, Any]] = []
    opening_anns: list[dict[str, Any]] = []
    stair_anns: list[dict[str, Any]] = []
    adjustments: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    view_identifiers: list[dict[str, Any]] = []
    all_level_marks: list[dict[str, Any]] = []
    all_section_markers: list[dict[str, Any]] = []
    north_summary: dict[str, Any] | None = None
    scale_summary: dict[str, Any] | None = None
    grid_summary: dict[str, Any] | None = None

    if "floor_plans" in requested_views:
        for fid in context["floor_ids"]:
            vid = f"PLAN-{fid}"
            fdims = [d for d in dimensions if d["view_id"] == vid]
            vdata = build_floor_plan_view(
                floor_id=fid,
                context=context,
                raw_input=wrapped,
                unit_policy=unit_policy,
                style=style,
                floor_dimensions=fdims,
                annotation_options=annotation_options,
            )
            view_obj = {
                "view_id": vdata["view_id"],
                "view_kind": vdata["view_kind"],
                "floor_id": vdata["floor_id"],
                "title": vdata["title"],
                "section_kind": None,
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
                "source_revision_digest": vdata["source_revision_digest"],
                "entities": vdata["entities"],
            }
            v_cols, v_adj = resolve_view_layout(
                view=view_obj,
                context=context,
                style=style,
                placement_options=placement_options,
                room_records=vdata["room_annotations"],
                opening_records=vdata["opening_annotations"],
            )
            view_obj["bounds"] = compute_view_bounds(view_obj["entities"])
            views_ir.append(view_obj)
            room_anns.extend(vdata["room_annotations"])
            opening_anns.extend(vdata["opening_annotations"])
            stair_anns.extend(vdata["stair_annotations"])
            adjustments.extend(v_adj)
            collisions.extend(v_cols)
            view_identifiers.append(
                {
                    "view_id": vid,
                    "view_kind": "floor_plan",
                    "floor_id": fid,
                    "title": vdata["title"],
                    "scale": paper_space["scale_label"],
                    "status": "PROPOSED_CONCEPTUAL",
                }
            )
            syms = vdata["symbols"]
            if syms["north_arrow"] is not None:
                north_summary = syms["north_arrow"]
            if syms["scale_bar"] is not None:
                scale_summary = syms["scale_bar"]
            if syms["reference_grid"] is not None:
                grid_summary = syms["reference_grid"]
            all_level_marks.extend(syms["level_marks"])
            all_section_markers.extend(syms["section_markers"])
            for unres in vdata["unresolved"]:
                if unres not in result["unresolved_items"]:
                    result["unresolved_items"].append(unres)
                if unres["code"].startswith("NORTH_") and annotation_options.get("require_north_arrow", False):
                    flags.add("missing")
                    issue(result, "missing_information", unres["code"], fid, unres["message"])

    if "stair_sections" in requested_views and context["stairs_report"].get("stairs"):
        for stair in context["stairs_report"]["stairs"]:
            sv_id = f"SECT-{stair['id']}"
            sdims = [d for d in dimensions if d["view_id"] == sv_id]
            sdata = build_stair_section_view(
                stair=stair,
                context=context,
                unit_policy=unit_policy,
                style=style,
                section_dimensions=sdims,
                annotation_options=annotation_options,
            )
            sview_obj = {
                "view_id": sdata["view_id"],
                "view_kind": sdata["view_kind"],
                "floor_id": None,
                "title": sdata["title"],
                "section_kind": sdata["section_kind"],
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
                "source_revision_digest": sdata["source_revision_digest"],
                "entities": sdata["entities"],
            }
            s_cols, s_adj = resolve_view_layout(
                view=sview_obj,
                context=context,
                style=style,
                placement_options=placement_options,
            )
            sview_obj["bounds"] = compute_view_bounds(sview_obj["entities"])
            views_ir.append(sview_obj)
            stair_anns.extend(sdata["stair_annotations"])
            adjustments.extend(s_adj)
            collisions.extend(s_cols)
            view_identifiers.append(
                {
                    "view_id": sv_id,
                    "view_kind": "stair_section",
                    "floor_id": None,
                    "title": sdata["title"],
                    "section_kind": sdata["section_kind"],
                    "scale": paper_space["scale_label"],
                    "status": "PROPOSED_CONCEPTUAL",
                }
            )
            all_level_marks.extend(sdata["level_marks"])

    if not views_ir:
        flags.add("missing")
        issue(
            result,
            "missing_information",
            "NO_DRAFTING_VIEWS_GENERATED",
            "views",
            "No floor plan or stair section geometry was available to compose drafting views.",
        )

    # Preserve non-blocking source unresolved records visibly without hiding them
    for sc in context["source_conflicts"]:
        if sc.get("severity") == "UNKNOWN":
            result["unresolved_items"].append(
                {
                    "code": sc.get("code", "SOURCE_UNKNOWN"),
                    "floor_id": None,
                    "message": sc.get("message", "Source unresolved item retained."),
                }
            )

    if collisions:
        flags.add("conflict")
        issue(
            result,
            "errors",
            "UNRESOLVED_ANNOTATION_COLLISION",
            "collisions",
            f"{len(collisions)} unresolved annotation collision(s) detected.",
        )

    result["model_space"]["views"] = views_ir
    result["annotations"] = {
        "rooms": room_anns,
        "openings": opening_anns,
        "stairs": stair_anns,
        "placement_adjustments": adjustments,
    }
    result["reference_symbols"] = {
        "north_arrow": north_summary,
        "scale_bar": scale_summary,
        "reference_grid": grid_summary,
        "level_marks": all_level_marks,
        "section_markers": all_section_markers,
        "view_identifiers": view_identifiers,
    }
    result["collisions"] = collisions

    ir_issues = validate_ir_entities(result["model_space"], layer_policy)
    if ir_issues:
        flags.add("invalid")
        for msg in ir_issues:
            issue(result, "errors", "INVALID_IR_ENTITY", "model_space", msg)

    result.update(_compute_digests(result))
    result["drafting_status"] = (
        "INVALID_INPUT"
        if "invalid" in flags
        else "CONFLICT"
        if "conflict" in flags
        else "UNSUPPORTED"
        if "unsupported" in flags
        else "INCOMPLETE"
        if "missing" in flags
        else "GENERATED"
    )
    return finish(result)


def validate_drafting(payload: Any) -> dict[str, Any]:
    """Validate either a drafting input or a stored architectural-drafting-v1 IR report."""
    if isinstance(payload, dict) and payload.get("contract") == "architectural-drafting-v1":
        check = new_report("stored-drafting-check")
        if not schema_check(payload, "drafting-ir.schema.json", check):
            out = generate_drafting({})
            out["errors"] = check["errors"]
            out["drafting_status"] = "INVALID_INPUT"
            return finish(out)
        # Re-verify layer policy, entity layers, chain closures, and recomputed digests.
        layer_issues = validate_layer_policy(payload.get("layer_policy", {}))
        ir_issues = validate_ir_entities(
            payload.get("model_space", {}), payload.get("layer_policy", {})
        )
        recomputed_digests = _compute_digests(payload)
        stored_input = payload.get("sources", {}).get("input")
        fresh = generate_drafting(stored_input) if stored_input else deepcopy(payload)
        mismatch_reasons: list[str] = []
        if layer_issues or ir_issues:
            mismatch_reasons.extend(layer_issues + ir_issues)
        for k, v in recomputed_digests.items():
            if payload.get(k) != v:
                mismatch_reasons.append(f"Stored digest mismatch for {k}.")
        if stored_input:
            for k in (
                "geometry_and_dimensions_digest",
                "model_space_digest",
                "presentation_digest",
                "drawing_ir_digest",
                "drafting_status",
            ):
                if payload.get(k) != fresh.get(k):
                    mismatch_reasons.append(f"Recomputed field mismatch for {k}.")
        for ch in payload.get("dimension_chains", []):
            segs = [dec(d["measured_value"]) for d in payload["dimensions"] if d["id"] in ch["segment_dimension_ids"]]
            over = next((dec(d["measured_value"]) for d in payload["dimensions"] if d["id"] == ch["overall_dimension_id"]), None)
            if over is None:
                mismatch_reasons.append(f"Missing overall dimension for chain {ch['chain_id']}.")
            else:
                ver = verify_dimension_chain_closure(
                    segs, over, payload["unit_policy"]["display_precision"], ch["measurement_unit"]
                )
                if ver["closure_status"] != ch["closure_status"]:
                    mismatch_reasons.append(f"Tampered closure_status on chain {ch['chain_id']}.")
        if mismatch_reasons:
            for msg in mismatch_reasons:
                issue(fresh, "errors", "STORED_DRAFTING_MISMATCH", "$", msg)
            fresh["drafting_status"] = "INVALID_INPUT"
        return finish(fresh)
    return generate_drafting(payload)


def ensure_no_finalized_ir_overrides(
    payload: Any,
    *,
    config_override: dict[str, Any] | None = None,
    scale_override: float | None = None,
    units_override: str | None = None,
) -> None:
    """Reject presentation/unit overrides on finalized IR reports so sizing stays synchronized."""
    if isinstance(payload, dict) and payload.get("contract") == "architectural-drafting-v1":
        if (
            config_override is not None
            or scale_override is not None
            or units_override is not None
        ):
            raise ValueError(
                "Cannot apply --config, --scale, or --units overrides to a finalized "
                "architectural-drafting-v1 IR report; pass the drafting input or source "
                "model so annotation sizing and collision checks stay synchronized."
            )


def extract_layers_report(
    payload: Any,
    *,
    config_override: dict[str, Any] | None = None,
    scale_override: float | None = None,
    units_override: str | None = None,
) -> dict[str, Any]:
    """Summarize CAD layer policy, per-layer entity inventory and ezdxf mapping."""
    ensure_no_finalized_ir_overrides(
        payload,
        config_override=config_override,
        scale_override=scale_override,
        units_override=units_override,
    )
    if isinstance(payload, dict) and payload.get("contract") == "architectural-drafting-v1":
        drafting = validate_drafting(payload)
    else:
        drafting = generate_drafting(
            payload,
            config_override=config_override,
            scale_override=scale_override,
            units_override=units_override,
        )
    policy = drafting.get("layer_policy", {})
    counts: dict[str, int] = {}
    views_by_layer: dict[str, set[str]] = {}
    for view in drafting.get("model_space", {}).get("views", []):
        for ent in view.get("entities", []):
            lname = ent["layer"]
            counts[lname] = counts.get(lname, 0) + 1
            views_by_layer.setdefault(lname, set()).add(view["view_id"])
    rows = []
    for layer in policy.get("layers", []):
        name = layer["name"]
        rows.append(
            {
                **layer,
                "entity_count": counts.get(name, 0),
                "views_present": sorted(views_by_layer.get(name, set())),
            }
        )
    return {
        "report_schema_version": 1,
        "engine_version": drafting["engine_version"],
        "contract": "architectural-drafting-layers-v1",
        "drafting_status": drafting["drafting_status"],
        "policy_version": policy.get("policy_version"),
        "authority": policy.get("authority"),
        "cad_writes_permitted": False,
        "architect_approval": "NOT_GRANTED",
        "total_entities": sum(counts.values()),
        "layers": rows,
        "errors": drafting["errors"],
        "missing_information": drafting["missing_information"],
        "warnings": drafting["warnings"],
    }
