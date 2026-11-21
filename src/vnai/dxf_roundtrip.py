"""DXF structural audit and independent handle-free semantic round-trip verification."""

from decimal import Decimal
import math
from pathlib import Path
import re
from typing import Any

from shapely.geometry import Polygon

from vnai import __version__
from vnai.contracts import canonical_digest, new_report, schema_check
from vnai.drafting_engine import validate_drafting
from vnai.drafting_ir import PRIMITIVE_TYPES
from vnai.drafting_styles import convert_length, dec, format_measurement, zero_float
from vnai.dxf_manifest import (
    DXF_INSUNITS,
    compute_file_sha256,
    decode_doc_meta,
    decode_ir_xdata,
)

ROUNDTRIP_EXIT_CODES = {
    "VERIFIED": 0,
    "CLEAN": 0,
    "RECOVERED_WITH_FIXES": 4,
    "CRITICAL_ERRORS": 1,
    "INVALID_INPUT": 1,
    "INCOMPLETE": 3,
    "MISMATCH": 4,
    "UNSUPPORTED": 5,
}


def _norm_float(value: float | int, unit: str) -> float:
    decimals = 7 if unit == "mm" else 10
    rounded = round(float(value), decimals)
    return 0.0 if rounded == 0.0 else rounded


def _norm_pt(pt: Any, unit: str) -> list[float]:
    return [_norm_float(pt[0], unit), _norm_float(pt[1], unit)]


def _pt_err(a: Any, b: Any) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _ang_diff(a: float, b: float) -> float:
    return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0)


def _strip_closing_dup(ring: list[list[float]]) -> list[list[float]]:
    if len(ring) >= 2 and _pt_err(ring[0], ring[-1]) <= 1e-9:
        return [list(p[:2]) for p in ring[:-1]]
    return [list(p[:2]) for p in ring]


def _poly_area_signed(pts: list[tuple[float, float]] | list[list[float]]) -> float:
    if len(pts) < 3:
        return 0.0
    terms = []
    n = len(pts)
    for i in range(n):
        x1, y1 = float(pts[i][0]), float(pts[i][1])
        x2, y2 = float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])
        terms.append(x1 * y2 - x2 * y1)
    return abs(math.fsum(terms)) / 2.0


def _all_coords_finite(vals: list[float]) -> bool:
    return all(math.isfinite(float(v)) for v in vals)


def audit_dxf_file(dxf_path: str | Path) -> dict[str, Any]:
    """Reopen and structurally audit a DXF file, kept separate from semantic round-trip."""
    import ezdxf
    from ezdxf.lldxf.const import DXFError

    path = Path(dxf_path)
    report: dict[str, Any] = {
        "report_schema_version": 1,
        "contract": "dxf-audit-report-v1",
        "exporter_version": __version__,
        "ezdxf_version": str(ezdxf.__version__),
        "dxf_path": str(path),
        "dxf_file_sha256": None,
        "audit_status": "CRITICAL_ERRORS",
        "lossless_eligible": False,
        "critical_error_count": 0,
        "fix_count": 0,
        "custom_issue_count": 0,
        "critical_errors": [],
        "fixes": [],
        "reference_and_geometry_issues": [],
        "cad_writes_permitted": False,
        "architect_approval": "NOT_GRANTED",
        "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
    }
    if not path.is_file():
        report["reference_and_geometry_issues"].append(
            {"code": "DXF_NOT_FOUND", "message": f"DXF file does not exist: {path}"}
        )
        report["custom_issue_count"] = 1
        return report

    report["dxf_file_sha256"] = compute_file_sha256(path)
    try:
        doc = ezdxf.readfile(path)
    except (DXFError, OSError, ValueError) as exc:
        report["critical_errors"].append(f"CORRUPT_DXF: {exc}")
        report["critical_error_count"] = 1
        return report

    auditor = doc.audit()
    crit = [str(e) for e in auditor.errors]
    fixes = [str(f) for f in auditor.fixes]
    custom_issues: list[dict[str, str]] = []

    layer_names = {lay.dxf.name for lay in doc.layers}
    style_names = {s.dxf.name for s in doc.styles}
    dimstyle_names = {ds.dxf.name for ds in doc.dimstyles}
    block_names = {blk.name for blk in doc.blocks}

    for layout in doc.layouts:
        for ent in layout:
            dxftype = ent.dxftype()
            lname = str(ent.dxf.get("layer", "0"))
            if lname not in layer_names:
                custom_issues.append(
                    {
                        "code": "MISSING_LAYER_REFERENCE",
                        "entity": dxftype,
                        "message": f"Entity references undeclared layer {lname!r}.",
                    }
                )
            if dxftype == "INSERT":
                bname = str(ent.dxf.get("name", ""))
                if bname not in block_names:
                    custom_issues.append(
                        {
                            "code": "BROKEN_BLOCK_REFERENCE",
                            "entity": dxftype,
                            "message": f"INSERT references missing block {bname!r}.",
                        }
                    )
            if dxftype in {"TEXT", "MTEXT"}:
                st = str(ent.dxf.get("style", "Standard"))
                if st not in style_names:
                    custom_issues.append(
                        {
                            "code": "MISSING_TEXT_STYLE",
                            "entity": dxftype,
                            "message": f"{dxftype} references missing style {st!r}.",
                        }
                    )
            if dxftype == "DIMENSION":
                ds = str(ent.dxf.get("dimstyle", "Standard"))
                geom = ent.dxf.get("geometry")
                if ds not in dimstyle_names or not geom or geom not in block_names:
                    custom_issues.append(
                        {
                            "code": "MISSING_DIMENSION_RENDER",
                            "entity": dxftype,
                            "message": f"DIMENSION missing dimstyle {ds!r} or geometry block {geom!r}.",
                        }
                    )
                pts = [
                    *list(ent.dxf.defpoint)[:2],
                    *list(ent.dxf.defpoint2)[:2],
                    *list(ent.dxf.defpoint3)[:2],
                    *list(ent.dxf.text_midpoint)[:2],
                ]
                if not _all_coords_finite(pts):
                    custom_issues.append(
                        {
                            "code": "CORRUPT_GEOMETRY",
                            "entity": dxftype,
                            "message": "DIMENSION contains non-finite coordinates.",
                        }
                    )
            elif dxftype == "LINE":
                s, e = ent.dxf.start, ent.dxf.end
                if not _all_coords_finite([s.x, s.y, e.x, e.y]):
                    custom_issues.append(
                        {"code": "CORRUPT_GEOMETRY", "entity": dxftype, "message": "Non-finite LINE."}
                    )
            elif dxftype in {"ARC", "CIRCLE"}:
                c = ent.dxf.center
                r = float(ent.dxf.radius)
                if not _all_coords_finite([c.x, c.y, r]) or r <= 0:
                    custom_issues.append(
                        {
                            "code": "CORRUPT_GEOMETRY",
                            "entity": dxftype,
                            "message": f"Invalid {dxftype} radius/center.",
                        }
                    )
            elif dxftype == "LWPOLYLINE":
                verts = list(ent.get_points("xy"))
                min_v = 3 if ent.closed else 2
                if len(verts) < min_v or any(not _all_coords_finite([vx, vy]) for vx, vy in verts):
                    custom_issues.append(
                        {
                            "code": "CORRUPT_GEOMETRY",
                            "entity": dxftype,
                            "message": "Degenerate or non-finite LWPOLYLINE.",
                        }
                    )
            elif dxftype == "HATCH":
                if len(ent.paths) == 0:
                    custom_issues.append(
                        {
                            "code": "CORRUPT_GEOMETRY",
                            "entity": dxftype,
                            "message": "HATCH has no boundary paths.",
                        }
                    )
                else:
                    rings = [[(float(v[0]), float(v[1])) for v in p.vertices] for p in ent.paths]
                    if len(rings[0]) < 3 or any(len(h) < 3 for h in rings[1:]):
                        custom_issues.append(
                            {
                                "code": "CORRUPT_GEOMETRY",
                                "entity": dxftype,
                                "message": "HATCH boundary ring has < 3 vertices.",
                            }
                        )
                    else:
                        poly = Polygon(rings[0], rings[1:])
                        if not poly.is_valid or poly.area <= 0:
                            custom_issues.append(
                                {
                                    "code": "CORRUPT_GEOMETRY",
                                    "entity": dxftype,
                                    "message": "HATCH polygon is invalid or zero area.",
                                }
                            )

    report["critical_errors"] = crit
    report["fixes"] = fixes
    report["reference_and_geometry_issues"] = custom_issues
    report["critical_error_count"] = len(crit)
    report["fix_count"] = len(fixes)
    report["custom_issue_count"] = len(custom_issues)

    if crit or custom_issues:
        report["audit_status"] = "CRITICAL_ERRORS"
        report["lossless_eligible"] = False
    elif fixes:
        report["audit_status"] = "RECOVERED_WITH_FIXES"
        report["lossless_eligible"] = False
    else:
        report["audit_status"] = "CLEAN"
        report["lossless_eligible"] = True
    return report


def resolve_ir_and_view(
    payload: Any,
    *,
    view_id: str | None = None,
    floor_id: str | None = None,
    doc_meta: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Validate Drafting IR v1 (or DXF Export Spec v1 wrapper) and select target view."""
    errors: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        errors.append(
            {
                "code": "INVALID_PAYLOAD",
                "path": "$",
                "message": "Input must be a JSON object.",
                "requirement_ids": [],
            }
        )
        return {}, None, None, errors

    spec_opts: dict[str, Any] | None = None
    ir_candidate = payload
    if payload.get("contract") == "dxf-export-spec-v1":
        spec_check = new_report("dxf-export-spec-check")
        if not schema_check(payload, "dxf-export-spec.schema.json", spec_check):
            return {}, None, None, spec_check["errors"]
        spec_opts = payload
        ir_candidate = payload["drafting_ir"]
        view_id = view_id if view_id is not None else payload.get("view_id")
        floor_id = floor_id if floor_id is not None else payload.get("floor_id")

    if not isinstance(ir_candidate, dict) or ir_candidate.get("contract") != "architectural-drafting-v1":
        errors.append(
            {
                "code": "UNSUPPORTED_CONTRACT",
                "path": "$.contract",
                "message": "Expected architectural-drafting-v1 Drawing IR or dxf-export-spec-v1 wrapper.",
                "requirement_ids": [],
            }
        )
        return {}, spec_opts, None, errors

    if not ir_candidate.get("drawing_ir_digest") or not ir_candidate.get("geometry_and_dimensions_digest") or not ir_candidate.get("source_digests"):
        errors.append(
            {
                "code": "MISSING_SOURCE_DIGEST",
                "path": "$.source_digests",
                "message": "Drawing IR must carry source_digests, geometry_and_dimensions_digest, and drawing_ir_digest.",
                "requirement_ids": [],
            }
        )
        return ir_candidate, spec_opts, None, errors

    declared_layers = {
        row.get("name")
        for row in (ir_candidate.get("layer_policy") or {}).get("layers", [])
        if isinstance(row, dict)
    }
    pre_views = (ir_candidate.get("model_space") or {}).get("views", [])
    if isinstance(pre_views, list):
        for v in pre_views:
            if not isinstance(v, dict):
                continue
            for ent in v.get("entities", []):
                if not isinstance(ent, dict):
                    continue
                et = ent.get("entity_type")
                if et not in PRIMITIVE_TYPES:
                    errors.append(
                        {
                            "code": "UNSUPPORTED_PRIMITIVE",
                            "path": f"$.model_space.views.{v.get('view_id')}.entities.{ent.get('id')}",
                            "message": f"Unsupported IR primitive type {et!r}; cannot export safely.",
                            "requirement_ids": [],
                        }
                    )
                    return ir_candidate, spec_opts, None, errors
                lname = ent.get("layer")
                if declared_layers and lname not in declared_layers:
                    errors.append(
                        {
                            "code": "UNMAPPED_ENTITY_LAYER",
                            "path": f"$.model_space.views.{v.get('view_id')}.entities.{ent.get('id')}.layer",
                            "message": f"Entity {ent.get('id')} uses undeclared layer {lname!r}; refusing silent fallback to layer '0'.",
                            "requirement_ids": [],
                        }
                    )
                    return ir_candidate, spec_opts, None, errors

    validated = validate_drafting(ir_candidate)
    if validated["drafting_status"] == "INVALID_INPUT" or validated["errors"] and any(
        e["code"] in {"STORED_DRAFTING_MISMATCH", "SCHEMA", "INVALID_IR_ENTITY", "INVALID_LAYER_POLICY"}
        for e in validated["errors"]
    ):
        return validated, spec_opts, None, validated["errors"]

    views = validated.get("model_space", {}).get("views", [])
    if not views:
        errors.append(
            {
                "code": "NO_VIEWS_AVAILABLE",
                "path": "$.model_space.views",
                "message": "Drawing IR contains no exportable views.",
                "requirement_ids": [],
            }
        )
        return validated, spec_opts, None, errors

    selected: dict[str, Any] | None = None
    if view_id is not None:
        selected = next((v for v in views if v["view_id"] == view_id), None)
        if selected is None:
            errors.append(
                {
                    "code": "VIEW_NOT_FOUND",
                    "path": "$.model_space.views",
                    "message": f"Requested view_id {view_id!r} not found in Drawing IR.",
                    "requirement_ids": [],
                }
            )
    elif floor_id is not None:
        selected = next(
            (v for v in views if v.get("floor_id") == floor_id or v.get("view_id") == floor_id),
            None,
        )
        if selected is None:
            errors.append(
                {
                    "code": "FLOOR_NOT_FOUND",
                    "path": "$.model_space.views",
                    "message": f"Requested floor_id {floor_id!r} not found in Drawing IR.",
                    "requirement_ids": [],
                }
            )
    elif len(views) == 1:
        selected = views[0]
    elif doc_meta and doc_meta.get("view_id"):
        selected = next((v for v in views if v["view_id"] == doc_meta["view_id"]), None)
        if selected is None:
            errors.append(
                {
                    "code": "VIEW_NOT_FOUND",
                    "path": "$.model_space.views",
                    "message": f"DXF VNAI_META view_id {doc_meta['view_id']!r} not found in Drawing IR.",
                    "requirement_ids": [],
                }
            )
    else:
        errors.append(
            {
                "code": "AMBIGUOUS_MULTI_VIEW_EXPORT",
                "path": "$.model_space.views",
                "message": "Drawing IR has multiple views; pass explicit view_id or floor_id so floors are never stacked.",
                "requirement_ids": [v["view_id"] for v in views],
            }
        )
    return validated, spec_opts, selected, errors


def _extract_expected_dim_suffix(display_text: str) -> str:
    """Split trailing annotation suffix (e.g. ' min CLR' in '3165 min CLR')."""
    match = re.match(r"^[+-]?\d+(?:\.\d+)?(.*)$", display_text.strip())
    if match:
        return match.group(1)
    return ""


def _record_mismatch(
    mismatches: list[dict[str, Any]],
    code: str,
    entity_id: str,
    message: str,
) -> None:
    mismatches.append({"code": code, "entity_id": entity_id, "message": message})


def verify_dxf_roundtrip(
    drafting_ir: Any,
    dxf_path: str | Path,
    *,
    view_id: str | None = None,
    floor_id: str | None = None,
    target_units: str | None = None,
    paper_space_layout: dict[str, Any] | None = None,
    expected_font_status: str = "UNVERIFIED_EXTERNAL_WORKSTATION_FONT",
) -> dict[str, Any]:
    """Independently reopen DXF, audit it, and perform handle-free semantic round-trip check."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    audit_rep = audit_dxf_file(dxf_path)
    if audit_rep["audit_status"] == "CRITICAL_ERRORS" and (
        any(c.startswith("CORRUPT_DXF") for c in audit_rep["critical_errors"])
        or any(
            i.get("code") == "DXF_NOT_FOUND"
            for i in audit_rep["reference_and_geometry_issues"]
        )
    ):
        return {
            "report_schema_version": 1,
            "contract": "dxf-roundtrip-verification-v1",
            "exporter_version": __version__,
            "roundtrip_status": "MISMATCH",
            "equivalence_status": "MISMATCH",
            "view_id": view_id,
            "dxf_path": str(dxf_path),
            "dxf_audit": audit_rep,
            "max_numeric_error": None,
            "coord_tolerance": None,
            "checked_entity_count": 0,
            "missing_entities": [],
            "extra_entities": [],
            "mismatches": [
                {
                    "code": "CORRUPT_OR_MISSING_DXF",
                    "entity_id": "$",
                    "message": "DXF could not be opened cleanly.",
                }
            ],
            "unicode_text_verification": {"text_count": 0, "all_codepoints_match": False, "font_rendering_status": expected_font_status, "samples": []},
            "semantic_fingerprint": None,
            "cad_writes_permitted": False,
            "architect_approval": "NOT_GRANTED",
            "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
        }

    doc = ezdxf.readfile(dxf_path)
    doc_meta = decode_doc_meta(doc)
    validated, spec_opts, view_spec, ir_errors = resolve_ir_and_view(
        drafting_ir, view_id=view_id, floor_id=floor_id, doc_meta=doc_meta
    )
    if ir_errors or view_spec is None:
        return {
            "report_schema_version": 1,
            "contract": "dxf-roundtrip-verification-v1",
            "exporter_version": __version__,
            "roundtrip_status": "INVALID_INPUT",
            "equivalence_status": "MISMATCH",
            "view_id": view_id,
            "dxf_path": str(dxf_path),
            "dxf_audit": audit_rep,
            "max_numeric_error": None,
            "coord_tolerance": None,
            "checked_entity_count": 0,
            "missing_entities": [],
            "extra_entities": [],
            "mismatches": [
                {"code": e["code"], "entity_id": e["path"], "message": e["message"]} for e in ir_errors
            ],
            "unicode_text_verification": {"text_count": 0, "all_codepoints_match": False, "font_rendering_status": expected_font_status, "samples": []},
            "semantic_fingerprint": None,
            "cad_writes_permitted": False,
            "architect_approval": "NOT_GRANTED",
            "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
        }

    src_units = validated["model_space"]["units"]
    unit_policy_units = validated["unit_policy"]["drawing_units"]
    if src_units != unit_policy_units or src_units not in DXF_INSUNITS:
        return {
            "report_schema_version": 1,
            "contract": "dxf-roundtrip-verification-v1",
            "exporter_version": __version__,
            "roundtrip_status": "INVALID_INPUT",
            "equivalence_status": "MISMATCH",
            "view_id": view_spec["view_id"],
            "dxf_path": str(dxf_path),
            "dxf_audit": audit_rep,
            "max_numeric_error": None,
            "coord_tolerance": None,
            "checked_entity_count": 0,
            "missing_entities": [],
            "extra_entities": [],
            "mismatches": [
                {
                    "code": "CONFLICTING_UNIT_DECLARATION",
                    "entity_id": "$.unit_policy",
                    "message": f"Conflicting IR units: model_space={src_units!r}, unit_policy={unit_policy_units!r}",
                }
            ],
            "unicode_text_verification": {"text_count": 0, "all_codepoints_match": False, "font_rendering_status": expected_font_status, "samples": []},
            "semantic_fingerprint": None,
            "cad_writes_permitted": False,
            "architect_approval": "NOT_GRANTED",
            "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
        }

    # Resolve expected target units (explicit arg > spec > DXF $INSUNITS fallback if in {4,6} > src_units)
    insunits = int(doc.header.get("$INSUNITS", 0))
    if target_units is not None:
        dst_units = target_units
    elif spec_opts and spec_opts.get("target_units"):
        dst_units = spec_opts["target_units"]
    elif insunits == 4:
        dst_units = "mm"
    elif insunits == 6:
        dst_units = "m"
    else:
        dst_units = src_units

    coord_tol = 1e-5 if dst_units == "mm" else 1e-8
    lossless_tol = 1e-9 if dst_units == "mm" else 1e-12
    area_tol = 1e-3 if dst_units == "mm" else 1e-9
    factor = convert_length(Decimal("1"), src_units, dst_units)
    dst_precision = (
        int(validated["unit_policy"]["display_precision_mm"])
        if dst_units == "mm"
        else int(validated["unit_policy"]["display_precision_m"])
    )

    def sv(val: float | int) -> float:
        if src_units == dst_units:
            return 0.0 if float(val) == 0.0 else float(val)
        return zero_float(dec(val) * factor)

    def spt(pt: list[float]) -> list[float]:
        return [sv(pt[0]), sv(pt[1])]

    mismatches: list[dict[str, Any]] = []
    missing_entities: list[str] = []
    extra_entities: list[str] = []
    max_err = 0.0

    def bump(err: float) -> None:
        nonlocal max_err
        if err > max_err:
            max_err = err

    # 1. Verify DXF $INSUNITS
    expected_ins = DXF_INSUNITS.get(dst_units)
    if insunits != expected_ins:
        _record_mismatch(
            mismatches,
            "INSUNITS_MISMATCH",
            "$HEADER",
            f"Expected $INSUNITS={expected_ins} for {dst_units}, got {insunits}.",
        )

    # 2. Verify layer policy definitions preserved
    for layer_row in validated["layer_policy"]["layers"]:
        em = layer_row["ezdxf_mapping"]
        lname = em["name"]
        if lname not in doc.layers:
            _record_mismatch(mismatches, "MISSING_LAYER", lname, f"DXF missing layer {lname!r}.")
            continue
        lay = doc.layers.get(lname)
        if int(lay.color) != int(em["color"]):
            _record_mismatch(
                mismatches, "LAYER_COLOR_MISMATCH", lname, f"Expected color {em['color']}, got {lay.color}."
            )
        if str(lay.dxf.linetype).upper() != str(em["linetype"]).upper():
            _record_mismatch(
                mismatches,
                "LAYER_LINETYPE_MISMATCH",
                lname,
                f"Expected linetype {em['linetype']}, got {lay.dxf.linetype}.",
            )
        if int(lay.dxf.lineweight) != int(em["lineweight"]):
            _record_mismatch(
                mismatches,
                "LAYER_LINEWEIGHT_MISMATCH",
                lname,
                f"Expected lineweight {em['lineweight']}, got {lay.dxf.lineweight}.",
            )
        if bool(lay.dxf.plot) != bool(em["plot"]) or bool(lay.is_on()) != bool(em["on"]):
            _record_mismatch(
                mismatches,
                "LAYER_FLAGS_MISMATCH",
                lname,
                f"Layer {lname} plot/visibility flags drifted.",
            )

    # 3. Group reopened ModelSpace entities by VNAI_IR XDATA ID
    dxf_by_ir: dict[str, list[tuple[Any, dict[str, str]]]] = {}
    for ent in doc.modelspace():
        xd = decode_ir_xdata(ent)
        if xd is None:
            extra_entities.append(f"UNTAGGED:{ent.dxftype()}:{ent.dxf.layer}")
            continue
        dxf_by_ir.setdefault(xd["id"], []).append((ent, xd))

    dims_by_id = {d["id"]: d for d in validated.get("dimensions", [])}
    normalized_entities: list[dict[str, Any]] = []
    unicode_samples: list[dict[str, Any]] = []
    unicode_all_ok = True

    align_map = {
        "middle": TextEntityAlignment.MIDDLE_CENTER,
        "start": TextEntityAlignment.MIDDLE_LEFT,
        "end": TextEntityAlignment.MIDDLE_RIGHT,
    }
    attach_map = {"middle": 5, "start": 4, "end": 6}

    for ir_ent in view_spec["entities"]:
        eid = ir_ent["id"]
        et = ir_ent["entity_type"]
        layer = ir_ent["layer"]
        c = ir_ent["coordinates"]
        m = ir_ent.get("metadata", {})
        found = dxf_by_ir.pop(eid, None)
        if not found:
            missing_entities.append(eid)
            _record_mismatch(mismatches, "MISSING_EXPORTED_ENTITY", eid, f"{et} missing from DXF.")
            continue

        # Check layer equality on every grouped primitive
        for dxf_e, _ in found:
            if str(dxf_e.dxf.layer) != layer:
                _record_mismatch(
                    mismatches,
                    "ENTITY_LAYER_MISMATCH",
                    eid,
                    f"Expected layer {layer}, found {dxf_e.dxf.layer}.",
                )

        norm_rec: dict[str, Any] = {"id": eid, "entity_type": et, "layer": layer}

        if et == "LINE":
            lines = [d for d, _ in found if d.dxftype() == "LINE"]
            if len(lines) != 1:
                _record_mismatch(mismatches, "ENTITY_TYPE_MISMATCH", eid, "Expected 1 DXF LINE.")
            else:
                exp_s, exp_e = spt(c["start"]), spt(c["end"])
                got_s = [lines[0].dxf.start.x, lines[0].dxf.start.y]
                got_e = [lines[0].dxf.end.x, lines[0].dxf.end.y]
                err = max(_pt_err(exp_s, got_s), _pt_err(exp_e, got_e))
                bump(err)
                if err > coord_tol:
                    _record_mismatch(mismatches, "LINE_COORD_MISMATCH", eid, f"LINE drift {err:.6g}")
                norm_rec.update({"start": _norm_pt(got_s, dst_units), "end": _norm_pt(got_e, dst_units)})

        elif et == "POLYLINE":
            lws = [(d, xd) for d, xd in found if d.dxftype() == "LWPOLYLINE"]
            closed = bool(c.get("closed", True))
            exp_rings = [("exterior", c["exterior"])] + [
                (f"hole:{idx}", h) for idx, h in enumerate(c.get("holes", []))
            ]
            by_part = {xd.get("part", "exterior"): d for d, xd in lws}
            if len(lws) != len(exp_rings):
                _record_mismatch(
                    mismatches,
                    "POLYLINE_PART_COUNT_MISMATCH",
                    eid,
                    f"Expected {len(exp_rings)} LWPOLYLINEs, found {len(lws)}.",
                )
            norm_rings = []
            for pname, ring in exp_rings:
                lw = by_part.get(pname)
                if lw is None:
                    _record_mismatch(mismatches, "POLYLINE_PART_MISSING", eid, f"Missing {pname}.")
                    continue
                if bool(lw.closed) != closed:
                    _record_mismatch(mismatches, "POLYLINE_CLOSURE_MISMATCH", eid, f"{pname} closed={lw.closed} != {closed}.")
                exp_pts = [spt(p) for p in _strip_closing_dup(ring)]
                got_pts = [[float(vx), float(vy)] for vx, vy in lw.get_points("xy")]
                if len(exp_pts) != len(got_pts):
                    _record_mismatch(
                        mismatches,
                        "POLYLINE_VERTEX_COUNT_MISMATCH",
                        eid,
                        f"{pname}: expected {len(exp_pts)} vertices, got {len(got_pts)}.",
                    )
                else:
                    verr = max((_pt_err(p1, p2) for p1, p2 in zip(exp_pts, got_pts)), default=0.0)
                    bump(verr)
                    if verr > coord_tol:
                        _record_mismatch(mismatches, "POLYLINE_VERTEX_MISMATCH", eid, f"{pname} max vertex err {verr:.6g}")
                    if closed:
                        area_diff = abs(_poly_area_signed(exp_pts) - _poly_area_signed(got_pts))
                        if area_diff > area_tol:
                            _record_mismatch(mismatches, "POLYLINE_AREA_MISMATCH", eid, f"{pname} area diff {area_diff:.6g}")
                norm_rings.append({"part": pname, "closed": bool(lw.closed), "pts": [_norm_pt(p, dst_units) for p in got_pts]})
            norm_rec["rings"] = norm_rings

        elif et == "ARC":
            arcs = [d for d, _ in found if d.dxftype() == "ARC"]
            if len(arcs) != 1:
                _record_mismatch(mismatches, "ARC_PRIMITIVE_MISMATCH", eid, "Expected analytic DXF ARC.")
            else:
                a = arcs[0]
                exp_c = spt(c["center"])
                exp_r = sv(c["radius"])
                rot = c.get("rotation", "ccw")
                exp_sa = (c["end_angle_deg"] if rot == "cw" else c["start_angle_deg"]) % 360.0
                exp_ea = (c["start_angle_deg"] if rot == "cw" else c["end_angle_deg"]) % 360.0
                got_c = [a.dxf.center.x, a.dxf.center.y]
                got_r = float(a.dxf.radius)
                cerr = max(_pt_err(exp_c, got_c), abs(exp_r - got_r))
                aerr = max(_ang_diff(exp_sa, a.dxf.start_angle), _ang_diff(exp_ea, a.dxf.end_angle))
                bump(cerr)
                if cerr > coord_tol or aerr > 1e-4:
                    _record_mismatch(
                        mismatches,
                        "ARC_GEOMETRY_MISMATCH",
                        eid,
                        f"ARC mismatch center/r err={cerr:.6g}, angle err={aerr:.6g}",
                    )
                # Verify unordered start/end points preserve exact wall/leaf endpoints
                exp_ep = [spt(c["start_point"]), spt(c["end_point"])]
                got_ep = [[a.start_point.x, a.start_point.y], [a.end_point.x, a.end_point.y]]
                ep_err = min(
                    max(_pt_err(exp_ep[0], got_ep[0]), _pt_err(exp_ep[1], got_ep[1])),
                    max(_pt_err(exp_ep[0], got_ep[1]), _pt_err(exp_ep[1], got_ep[0])),
                )
                bump(ep_err)
                if ep_err > coord_tol:
                    _record_mismatch(mismatches, "ARC_ENDPOINTS_MISMATCH", eid, f"ARC endpoint err={ep_err:.6g}")
                norm_rec.update(
                    {
                        "center": _norm_pt(got_c, dst_units),
                        "radius": _norm_float(got_r, dst_units),
                        "start_angle": round(float(a.dxf.start_angle) % 360.0, 6),
                        "end_angle": round(float(a.dxf.end_angle) % 360.0, 6),
                        "rotation": rot,
                    }
                )

        elif et == "CIRCLE":
            circs = [d for d, _ in found if d.dxftype() == "CIRCLE"]
            if len(circs) != 1:
                _record_mismatch(mismatches, "CIRCLE_PRIMITIVE_MISMATCH", eid, "Expected DXF CIRCLE.")
            else:
                ci = circs[0]
                exp_c, exp_r = spt(c["center"]), sv(c["radius"])
                got_c, got_r = [ci.dxf.center.x, ci.dxf.center.y], float(ci.dxf.radius)
                err = max(_pt_err(exp_c, got_c), abs(exp_r - got_r))
                bump(err)
                if err > coord_tol:
                    _record_mismatch(mismatches, "CIRCLE_GEOMETRY_MISMATCH", eid, f"CIRCLE err={err:.6g}")
                norm_rec.update({"center": _norm_pt(got_c, dst_units), "radius": _norm_float(got_r, dst_units)})

        elif et == "TEXT":
            txts = [d for d, _ in found if d.dxftype() == "TEXT"]
            if len(txts) != 1:
                _record_mismatch(mismatches, "TEXT_PRIMITIVE_MISMATCH", eid, "Expected DXF TEXT.")
            else:
                t = txts[0]
                exp_str = str(m.get("text", ""))
                got_str = str(t.dxf.text)
                cp_match = [ord(ch) for ch in exp_str] == [ord(ch) for ch in got_str]
                if not cp_match:
                    unicode_all_ok = False
                    _record_mismatch(mismatches, "TEXT_UNICODE_MISMATCH", eid, f"TEXT {got_str!r} != {exp_str!r}")
                unicode_samples.append({"entity_id": eid, "kind": "TEXT", "text": got_str, "codepoint_match": cp_match})
                align, pos1, pos2 = t.get_placement()
                exp_align = align_map.get(m.get("anchor", "middle"), TextEntityAlignment.MIDDLE_CENTER)
                got_pos = [pos1.x, pos1.y] if pos2 is None else [pos2.x, pos2.y]
                err = max(_pt_err(spt(c["insert"]), got_pos), abs(sv(m.get("height", 200.0)) - float(t.dxf.height)))
                bump(err)
                if align != exp_align or err > coord_tol or _ang_diff(m.get("rotation_deg", 0.0), t.dxf.rotation) > 1e-4:
                    _record_mismatch(mismatches, "TEXT_PLACEMENT_MISMATCH", eid, f"TEXT placement err={err:.6g}")
                norm_rec.update({"text": got_str, "insert": _norm_pt(got_pos, dst_units), "height": _norm_float(t.dxf.height, dst_units)})

        elif et == "MTEXT":
            mtxts = [d for d, _ in found if d.dxftype() == "MTEXT"]
            if len(mtxts) != 1:
                _record_mismatch(mismatches, "MTEXT_PRIMITIVE_MISMATCH", eid, "Expected DXF MTEXT.")
            else:
                mt = mtxts[0]
                exp_lines = [str(line) for line in m.get("lines", [])]
                got_lines = mt.plain_text().split("\n")
                cp_match = [[ord(ch) for ch in ln] for ln in exp_lines] == [[ord(ch) for ch in ln] for ln in got_lines]
                if not cp_match:
                    unicode_all_ok = False
                    _record_mismatch(mismatches, "MTEXT_UNICODE_MISMATCH", eid, f"MTEXT {got_lines!r} != {exp_lines!r}")
                unicode_samples.append({"entity_id": eid, "kind": "MTEXT", "lines": got_lines, "codepoint_match": cp_match})
                got_pos = [mt.dxf.insert.x, mt.dxf.insert.y]
                err = max(_pt_err(spt(c["insert"]), got_pos), abs(sv(m.get("height", 200.0)) - float(mt.dxf.char_height)))
                bump(err)
                exp_att = attach_map.get(m.get("anchor", "middle"), 5)
                if int(mt.dxf.attachment_point) != exp_att or err > coord_tol:
                    _record_mismatch(mismatches, "MTEXT_PLACEMENT_MISMATCH", eid, f"MTEXT placement err={err:.6g}")
                norm_rec.update({"lines": got_lines, "insert": _norm_pt(got_pos, dst_units), "height": _norm_float(mt.dxf.char_height, dst_units)})

        elif et == "DIMENSION":
            dims = [d for d, _ in found if d.dxftype() == "DIMENSION"]
            if len(dims) != 1:
                _record_mismatch(mismatches, "DIMENSION_PRIMITIVE_MISMATCH", eid, "Expected native DXF DIMENSION.")
            else:
                de = dims[0]
                exp_p1, exp_p2 = spt(c["ref_point_1"]), spt(c["ref_point_2"])
                got_p1 = [de.dxf.defpoint2.x, de.dxf.defpoint2.y]
                got_p2 = [de.dxf.defpoint3.x, de.dxf.defpoint3.y]
                p_err = max(_pt_err(exp_p1, got_p1), _pt_err(exp_p2, got_p2))
                bump(p_err)
                if p_err > coord_tol:
                    _record_mismatch(mismatches, "DIMENSION_DEFPOINT_MISMATCH", eid, f"Dimension defpoints moved ({p_err:.6g}).")
                orient = m.get("orientation", "horizontal")
                got_span = abs(got_p2[0] - got_p1[0]) if orient == "horizontal" else abs(got_p2[1] - got_p1[1])
                exp_meas = sv(dims_by_id[m["dimension_id"]]["measured_value"]) if m.get("dimension_id") in dims_by_id else (
                    abs(exp_p2[0] - exp_p1[0]) if orient == "horizontal" else abs(exp_p2[1] - exp_p1[1])
                )
                stored_meas = de.dxf.get("actual_measurement")
                get_meas = float(de.get_measurement())
                m_err = max(abs(got_span - exp_meas), abs(get_meas - exp_meas))
                if stored_meas is not None:
                    m_err = max(m_err, abs(float(stored_meas) - exp_meas))
                bump(m_err)
                if m_err > coord_tol:
                    _record_mismatch(
                        mismatches,
                        "DIMENSION_MEASUREMENT_MISMATCH",
                        eid,
                        f"Dimension measurement drift: expected {exp_meas}, span={got_span}, get_meas={get_meas}, stored={stored_meas}.",
                    )
                gblk_name = de.dxf.get("geometry")
                if not gblk_name or gblk_name not in doc.blocks or len(doc.blocks[gblk_name]) == 0:
                    _record_mismatch(mismatches, "DIMENSION_UNRENDERED", eid, f"Dimension missing rendered geometry block {gblk_name!r}.")
                else:
                    # Verify rendered geometry block contains an MTEXT/TEXT representation matching formatted measurement
                    blk_texts = [
                        (be.plain_text() if be.dxftype() == "MTEXT" else be.dxf.text)
                        for be in doc.blocks[gblk_name]
                        if be.dxftype() in {"MTEXT", "TEXT"}
                    ]
                    fmt_num = format_measurement(dec(exp_meas), dst_precision)[0]
                    if not blk_texts or not any(
                        fmt_num in txt or fmt_num.replace(".", ",") in txt
                        for txt in blk_texts
                    ):
                        _record_mismatch(
                            mismatches,
                            "DIMENSION_RENDER_TEXT_MISMATCH",
                            eid,
                            f"Rendered block text {blk_texts!r} missing expected formatted measurement {fmt_num!r}.",
                        )
                exp_suf = _extract_expected_dim_suffix(str(m.get("display_text", "")))
                exp_tmpl = f"<>{exp_suf}" if exp_suf else "<>"
                if str(de.dxf.get("text", "")) != exp_tmpl:
                    _record_mismatch(mismatches, "DIMENSION_TEXT_TEMPLATE_MISMATCH", eid, f"Expected {exp_tmpl!r}, got {de.dxf.text!r}.")
                norm_rec.update(
                    {
                        "orientation": orient,
                        "defpoint2": _norm_pt(got_p1, dst_units),
                        "defpoint3": _norm_pt(got_p2, dst_units),
                        "measurement": _norm_float(got_span, dst_units),
                        "text_template": str(de.dxf.text),
                    }
                )

        elif et == "HATCH":
            hs = [d for d, _ in found if d.dxftype() == "HATCH"]
            if len(hs) != 1:
                _record_mismatch(mismatches, "HATCH_PRIMITIVE_MISMATCH", eid, "Expected DXF HATCH.")
            else:
                h = hs[0]
                if str(h.dxf.pattern_name).upper() != str(m.get("pattern", "ANSI31")).upper():
                    _record_mismatch(mismatches, "HATCH_PATTERN_MISMATCH", eid, f"Pattern {h.dxf.pattern_name} != {m.get('pattern')}")
                exp_rings = [c["exterior"], *c.get("holes", [])]
                if len(h.paths) != len(exp_rings):
                    _record_mismatch(mismatches, "HATCH_PATH_COUNT_MISMATCH", eid, f"Expected {len(exp_rings)} paths, got {len(h.paths)}.")
                else:
                    norm_h_rings = []
                    for ridx, (ering, path_obj) in enumerate(zip(exp_rings, h.paths)):
                        exp_pts = [spt(p) for p in _strip_closing_dup(ering)]
                        got_pts = [[float(v[0]), float(v[1])] for v in path_obj.vertices]
                        if len(exp_pts) != len(got_pts):
                            _record_mismatch(mismatches, "HATCH_VERTEX_COUNT_MISMATCH", eid, f"Ring {ridx}: {len(got_pts)} != {len(exp_pts)}")
                        else:
                            herr = max((_pt_err(p1, p2) for p1, p2 in zip(exp_pts, got_pts)), default=0.0)
                            bump(herr)
                            if herr > coord_tol:
                                _record_mismatch(mismatches, "HATCH_BOUNDARY_MISMATCH", eid, f"Ring {ridx} err={herr:.6g}")
                        norm_h_rings.append([_norm_pt(p, dst_units) for p in got_pts])
                    norm_rec["pattern"] = str(h.dxf.pattern_name).upper()
                    norm_rec["rings"] = norm_h_rings

        elif et == "BLOCK_REFERENCE":
            inss = [d for d, _ in found if d.dxftype() == "INSERT"]
            if len(inss) != 1:
                _record_mismatch(mismatches, "BLOCK_REF_MISMATCH", eid, "Expected 1 DXF INSERT.")
            else:
                ins = inss[0]
                bname = m.get("block_name")
                exp_ins = spt(c["insert"])
                got_ins = [ins.dxf.insert.x, ins.dxf.insert.y]
                err = _pt_err(exp_ins, got_ins)
                bump(err)
                got_attrs = {str(a.dxf.tag): str(a.dxf.text) for a in ins.attribs}
                exp_attrs = {}
                if bname in {"TAG_DOOR", "TAG_WINDOW"}:
                    exp_attrs = {"MARK": str(m.get("mark", "")), "DIM_LABEL": str(m.get("dimension_label", ""))}
                elif bname == "SYM_LEVEL_MARK":
                    exp_attrs = {"LABEL": str(m.get("label", ""))}
                if ins.dxf.name != bname or err > coord_tol or got_attrs != exp_attrs or _ang_diff(c.get("rotation_deg", 0.0), ins.dxf.rotation) > 1e-4:
                    _record_mismatch(
                        mismatches,
                        "INSERT_DATA_MISMATCH",
                        eid,
                        f"INSERT mismatch name={ins.dxf.name}!= {bname} or attribs {got_attrs}!={exp_attrs}.",
                    )
                norm_rec.update({"block": ins.dxf.name, "insert": _norm_pt(got_ins, dst_units), "attribs": dict(sorted(got_attrs.items()))})

        elif et == "SYMBOL":
            sk = m.get("symbol_kind")
            if sk == "scale_bar":
                inss = [d for d, _ in found if d.dxftype() == "INSERT"]
                if len(inss) != 1:
                    _record_mismatch(mismatches, "SYMBOL_MISMATCH", eid, "Expected scale_bar INSERT.")
                else:
                    got_ins = [inss[0].dxf.insert.x, inss[0].dxf.insert.y]
                    err = _pt_err(spt(c["insert"]), got_ins)
                    bump(err)
                    if err > coord_tol or inss[0].dxf.name not in doc.blocks:
                        _record_mismatch(mismatches, "SYMBOL_MISMATCH", eid, "scale_bar geometry drifted.")
                    norm_rec.update({"symbol_kind": sk, "insert": _norm_pt(got_ins, dst_units), "length": _norm_float(sv(c["length"]), dst_units)})
            elif sk == "section_marker":
                by_p = {xd.get("part"): d for d, xd in found}
                if not {"cut_line", "look_arrow", "bubble", "label"}.issubset(by_p):
                    _record_mismatch(mismatches, "SYMBOL_MISMATCH", eid, "Missing section_marker primitives.")
                else:
                    cl = by_p["cut_line"]
                    err = max(_pt_err(spt(c["start"]), [cl.dxf.start.x, cl.dxf.start.y]), _pt_err(spt(c["end"]), [cl.dxf.end.x, cl.dxf.end.y]))
                    bump(err)
                    lbl_txt = str(by_p["label"].dxf.text)
                    if err > coord_tol or lbl_txt != str(m.get("label", "S")):
                        _record_mismatch(mismatches, "SYMBOL_MISMATCH", eid, "section_marker cut_line/label mismatch.")
                    norm_rec.update({"symbol_kind": sk, "start": _norm_pt([cl.dxf.start.x, cl.dxf.start.y], dst_units), "end": _norm_pt([cl.dxf.end.x, cl.dxf.end.y], dst_units), "label": lbl_txt})
            elif sk in {"stair_direction_arrow", "slide_direction"}:
                by_p = {xd.get("part"): d for d, xd in found}
                if not {"shaft", "chevron"}.issubset(by_p):
                    _record_mismatch(mismatches, "SYMBOL_MISMATCH", eid, f"Missing {sk} shaft/chevron.")
                else:
                    sh = by_p["shaft"]
                    exp_a = spt(c.get("from_point", c.get("direction_start")))
                    exp_b = spt(c.get("to_point", c.get("direction_end")))
                    err = max(_pt_err(exp_a, [sh.dxf.start.x, sh.dxf.start.y]), _pt_err(exp_b, [sh.dxf.end.x, sh.dxf.end.y]))
                    bump(err)
                    if err > coord_tol:
                        _record_mismatch(mismatches, "SYMBOL_MISMATCH", eid, f"{sk} endpoint mismatch.")
                    norm_rec.update({"symbol_kind": sk, "start": _norm_pt([sh.dxf.start.x, sh.dxf.start.y], dst_units), "end": _norm_pt([sh.dxf.end.x, sh.dxf.end.y], dst_units)})
            else:
                _record_mismatch(mismatches, "UNSUPPORTED_SYMBOL", eid, f"Unknown symbol_kind {sk!r}.")

        normalized_entities.append(norm_rec)

    for leftover_id in sorted(dxf_by_ir):
        extra_entities.append(leftover_id)
        _record_mismatch(mismatches, "EXTRA_IR_ENTITY_IN_DXF", leftover_id, "DXF contains IR ID absent from source view.")
    for untagged in sorted(extra_entities):
        if untagged.startswith("UNTAGGED:"):
            _record_mismatch(mismatches, "UNTAGGED_ENTITY_IN_DXF", untagged, "ModelSpace contains untagged DXF entity.")

    # Verify optional PaperSpace layout if paper_space_layout with paper_size_mm supplied
    ps_spec = paper_space_layout or (spec_opts or {}).get("paper_space_layout") or {}
    ps_norm: dict[str, Any] = {"checked": False}
    if ps_spec.get("enabled", True) and ps_spec.get("paper_size_mm"):
        exp_pw, exp_ph = [float(x) for x in ps_spec["paper_size_mm"]]
        scale_denom = float(validated["paper_space"]["scale_denominator"])
        target_layout = next(
            (doc.layouts.get(n) for n in doc.layouts.names() if n != "Model" and len([e for e in doc.layouts.get(n) if e.dxftype() != "VIEWPORT" or e.dxf.id != 1]) > 0),
            None,
        )
        if target_layout is None:
            _record_mismatch(mismatches, "MISSING_PAPER_SPACE_LAYOUT", "$PAPER_SPACE", "Expected populated Paper Space layout.")
        else:
            vps = [e for e in target_layout if e.dxftype() == "VIEWPORT" and e.dxf.id != 1]
            if len(vps) != 1:
                _record_mismatch(mismatches, "PAPER_VIEWPORT_COUNT_MISMATCH", target_layout.name, f"Expected 1 model VIEWPORT, got {len(vps)}.")
            else:
                vp = vps[0]
                mm_per_unit = 1.0 if dst_units == "mm" else 1000.0
                got_scale = (float(vp.dxf.view_height) * mm_per_unit) / max(float(vp.dxf.height), 1e-9)
                if abs(got_scale - scale_denom) > 1e-4 or abs(float(target_layout.dxf.paper_width) - exp_pw) > 1e-3 or abs(float(target_layout.dxf.paper_height) - exp_ph) > 1e-3:
                    _record_mismatch(mismatches, "PAPER_VIEWPORT_SCALE_MISMATCH", target_layout.name, f"Viewport scale {got_scale} != {scale_denom}.")
                ps_norm = {"checked": True, "paper_size_mm": [exp_pw, exp_ph], "viewport_scale_denominator": round(got_scale, 6)}

    normalized_model = {
        "view_id": view_spec["view_id"],
        "target_units": dst_units,
        "insunits": expected_ins,
        "layers": sorted([r["name"] for r in validated["layer_policy"]["layers"]]),
        "entities": sorted(normalized_entities, key=lambda x: x["id"]),
        "paper_space": ps_norm,
    }
    sem_fp = canonical_digest(normalized_model)

    has_blocking = bool(mismatches or missing_entities or extra_entities or audit_rep["audit_status"] != "CLEAN")
    if has_blocking:
        eq_status = "MISMATCH"
        rt_status = "MISMATCH"
    elif max_err <= lossless_tol:
        eq_status = "LOSSLESS_EQUIVALENT"
        rt_status = "VERIFIED"
    else:
        eq_status = "NUMERICALLY_EQUIVALENT"
        rt_status = "VERIFIED"

    return {
        "report_schema_version": 1,
        "contract": "dxf-roundtrip-verification-v1",
        "exporter_version": __version__,
        "roundtrip_status": rt_status,
        "equivalence_status": eq_status,
        "view_id": view_spec["view_id"],
        "target_units": dst_units,
        "dxf_path": str(dxf_path),
        "dxf_file_sha256": audit_rep["dxf_file_sha256"],
        "dxf_audit": audit_rep,
        "max_numeric_error": zero_float(max_err),
        "coord_tolerance": coord_tol,
        "lossless_tolerance": lossless_tol,
        "checked_entity_count": len(normalized_entities),
        "missing_entities": sorted(missing_entities),
        "extra_entities": sorted(extra_entities),
        "mismatches": mismatches,
        "unicode_text_verification": {
            "text_count": len(unicode_samples),
            "all_codepoints_match": unicode_all_ok,
            "font_rendering_status": expected_font_status,
            "note": "UTF-8 DXF string code-point match is verified; workstation TTF/SHX font rendering depends on architect AutoCAD environment.",
            "samples": unicode_samples,
        },
        "semantic_fingerprint": sem_fp,
        "cad_writes_permitted": False,
        "architect_approval": "NOT_GRANTED",
        "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
    }
