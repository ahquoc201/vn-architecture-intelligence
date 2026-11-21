"""Production CAD-neutral Drawing IR v1 to editable DXF exporter (no AutoCAD MCP writes)."""

from copy import deepcopy
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from shapely.geometry import Polygon

from vnai import __version__
from vnai.contracts import issue, new_report, schema_check
from vnai.drafting_ir import PRIMITIVE_TYPES
from vnai.drafting_styles import convert_length, dec, format_measurement, validate_layer_policy, zero_float
from vnai.dxf_manifest import (
    DXF_INSUNITS,
    SUPPORTED_DXF_VERSIONS,
    VNAI_META_KEY,
    VNAI_XDATA_APPID,
    build_export_manifest,
    compute_file_sha256,
    encode_doc_meta,
    encode_ir_xdata,
)
from vnai.dxf_roundtrip import resolve_ir_and_view, verify_dxf_roundtrip

EXIT_CODES = {
    "EXPORTED": 0,
    "VERIFIED": 0,
    "CLEAN": 0,
    "INVALID_INPUT": 1,
    "AUDIT_ERROR": 1,
    "INCOMPLETE": 3,
    "CONFLICT": 4,
    "MISMATCH": 4,
    "RECOVERED_WITH_FIXES": 4,
    "UNSUPPORTED": 5,
}

TEXT_STYLE_NAME = "VNAI_VN_UNICODE"
SUPPORTED_SYMBOL_KINDS = frozenset(
    {"scale_bar", "section_marker", "stair_direction_arrow", "slide_direction"}
)


def _is_protected_repo_path(path: Path) -> bool:
    """Block overwriting canonical repository inputs, schemas, tests, or source modules."""
    parts = [p.lower() for p in path.parts]
    for idx, part in enumerate(parts):
        if part in {"src", "knowledge", "tests", "sources", "skills"}:
            return True
        if part == "examples" and idx + 1 < len(parts):
            nxt = parts[idx + 1]
            if nxt.endswith(".json") or nxt.startswith("batch005") or nxt.startswith("batch006") or nxt.startswith("batch007"):
                # Allow exporting generated .dxf/.json artifacts only under examples/batch007d/exports
                if not (nxt == "batch007d" and idx + 2 < len(parts) and parts[idx + 2] == "exports"):
                    return True
    return False


def _validate_output_paths(
    out_path: str | Path,
    *,
    manifest_out: str | Path | None,
    overwrite: bool,
    source_input_path: str | Path | None,
) -> tuple[Path, Path | None]:
    if out_path is None or str(out_path).strip() == "":
        raise ValueError("Explicit --out DXF file path is required.")
    out_p = Path(out_path)
    if out_p.suffix.lower() != ".dxf":
        raise ValueError(f"Output path must end with .dxf: {out_path}")
    if out_p.exists() and out_p.is_dir():
        raise ValueError(f"Output path points to a directory: {out_path}")

    out_res = out_p.resolve()
    man_p = Path(manifest_out) if manifest_out is not None else None
    man_res = man_p.resolve() if man_p is not None else None

    if man_res is not None and out_res == man_res:
        raise ValueError("DXF output path and manifest output path cannot alias.")
    if source_input_path is not None:
        src_res = Path(source_input_path).resolve()
        if out_res == src_res or (man_res is not None and man_res == src_res):
            raise ValueError("Refusing to overwrite input specification file.")
    if _is_protected_repo_path(out_res) or (man_res is not None and _is_protected_repo_path(man_res)):
        raise ValueError("Refusing to overwrite protected repository source, schema, or fixture files.")
    if not overwrite:
        if out_p.exists():
            raise FileExistsError(f"DXF output already exists (pass overwrite=True to replace): {out_p}")
        if man_p is not None and man_p.exists():
            raise FileExistsError(f"Manifest output already exists: {man_p}")
    return out_p, man_p


def _strip_closing_vertex(pts: list[list[float]]) -> list[list[float]]:
    if len(pts) >= 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 1e-9:
        return [list(p[:2]) for p in pts[:-1]]
    return [list(p[:2]) for p in pts]


def _extract_dim_override_template(display_text: str, exp_num_str: str) -> str:
    txt = str(display_text).strip()
    if txt.startswith(exp_num_str) and len(txt) > len(exp_num_str):
        suffix = txt[len(exp_num_str) :]
        return f"<>{suffix}"
    # Preserve symbolic measurement when converted across units (e.g. '3165 min CLR' -> '<> min CLR')
    parts = txt.split(None, 1)
    if len(parts) == 2 and parts[0].replace(".", "", 1).replace("-", "", 1).isdigit():
        return f"<> {parts[1]}"
    return "<>"


def _error_manifest(
    *,
    drafting_ir: dict[str, Any],
    view_spec: dict[str, Any] | None,
    dxf_version: str,
    ezdxf_version: str | None,
    source_units: str | None,
    target_units: str | None,
    export_status: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    missing_information: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    dxf_audit: dict[str, Any] | None = None,
    roundtrip: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ps = drafting_ir.get("paper_space") or {}
    return build_export_manifest(
        drafting_ir=drafting_ir,
        view_spec=view_spec,
        dxf_version=dxf_version,
        ezdxf_version=ezdxf_version,
        source_units=source_units,
        target_units=target_units,
        unit_policy={
            "source_units": source_units,
            "target_units": target_units,
            "double_conversion_guard": "EXPLICIT_IR_TO_DXF_ONCE",
        },
        scale_metadata={
            "scale_denominator": ps.get("scale_denominator"),
            "scale_label": ps.get("scale_label"),
            "scale_authority": ps.get("scale_authority"),
        },
        entity_count_by_type={},
        entity_count_by_layer={},
        supported_transformations=[],
        unsupported_or_omitted_entities=[],
        entity_id_map={},
        paper_space_composition={"status": "NOT_GENERATED"},
        unicode_text_verification={"text_count": 0, "all_codepoints_match": False, "font_rendering_status": "UNVERIFIED_EXTERNAL_WORKSTATION_FONT", "samples": []},
        dxf_audit=dxf_audit or {"audit_status": "NOT_RUN"},
        roundtrip_verification=roundtrip or {"roundtrip_status": "NOT_RUN", "equivalence_status": "MISMATCH"},
        semantic_fingerprint=None,
        dxf_file_sha256=None,
        dxf_path=None,
        export_status=export_status,
        errors=errors,
        warnings=warnings,
        missing_information=missing_information,
        diagnostics=diagnostics,
    )


def _register_blocks(
    doc: Any,
    model_sizing: dict[str, Any],
    scale_pt: Any,
    text_style: str,
) -> None:
    """Create CAD blocks corresponding to Drafting IR reusable BLOCK_REFERENCE types."""
    th = scale_pt(model_sizing["text_height"])
    dh = scale_pt(model_sizing["dim_text_height"])

    # TAG_DOOR: capsule outline centered at (0,0)
    b_door = doc.blocks.new("TAG_DOOR")
    dw, dhalf_h = th * 2.1, th * 1.05
    b_door.add_lwpolyline([(-dw, -dhalf_h), (dw, -dhalf_h), (dw, dhalf_h), (-dw, dhalf_h)], close=True)
    b_door.add_attdef("MARK", insert=(0.0, th * 0.15), dxfattribs={"height": dh * 0.9, "style": text_style})
    b_door.add_attdef("DIM_LABEL", insert=(0.0, -th * 1.4), dxfattribs={"height": dh * 0.75, "style": text_style})

    # TAG_WINDOW: hexagonal outline centered at (0,0)
    b_win = doc.blocks.new("TAG_WINDOW")
    ww, wh = th * 1.9, th * 1.05
    b_win.add_lwpolyline([(-ww, 0.0), (-ww * 0.6, -wh), (ww * 0.6, -wh), (ww, 0.0), (ww * 0.6, wh), (-ww * 0.6, wh)], close=True)
    b_win.add_attdef("MARK", insert=(0.0, th * 0.15), dxfattribs={"height": dh * 0.9, "style": text_style})
    b_win.add_attdef("DIM_LABEL", insert=(0.0, -th * 1.4), dxfattribs={"height": dh * 0.75, "style": text_style})

    # SYM_LEVEL_MARK: datum triangle + horizontal leader bar
    b_lvl = doc.blocks.new("SYM_LEVEL_MARK")
    sz = th * 1.2
    b_lvl.add_lwpolyline([(0.0, 0.0), (-sz * 0.5, sz * 0.85), (sz * 0.5, sz * 0.85)], close=True)
    b_lvl.add_line((-sz * 0.7, 0.0), (sz * 5.2, 0.0))
    b_lvl.add_attdef("LABEL", insert=(sz * 0.8, sz * 0.3), dxfattribs={"height": dh * 0.85, "style": text_style})

    # SYM_NORTH_ARROW: true north compass symbol
    b_north = doc.blocks.new("SYM_NORTH_ARROW")
    nr = th * 2.8
    b_north.add_circle((0.0, 0.0), radius=nr)
    b_north.add_lwpolyline([(0.0, nr * 0.9), (-nr * 0.32, -nr * 0.35), (0.0, -nr * 0.1), (nr * 0.32, -nr * 0.35)], close=True)
    b_north.add_text("N", dxfattribs={"height": th * 1.0, "insert": (-th * 0.35, nr * 1.1), "style": text_style})


def export_drafting_dxf(
    payload: Any,
    out_path: str | Path,
    *,
    view_id: str | None = None,
    floor_id: str | None = None,
    target_units: str | None = None,
    dxf_version: str = "R2010",
    text_font_name: str = "Arial.ttf",
    paper_space_layout: dict[str, Any] | None = None,
    manifest_out: str | Path | None = None,
    overwrite: bool = False,
    source_input_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export validated Drawing IR v1 view into editable DXF + verified semantic manifest."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    out_p, man_p = _validate_output_paths(
        out_path, manifest_out=manifest_out, overwrite=overwrite, source_input_path=source_input_path
    )
    src_copy = deepcopy(payload)
    validated, spec_opts, view_spec, ir_errors = resolve_ir_and_view(
        src_copy, view_id=view_id, floor_id=floor_id
    )

    if spec_opts:
        target_units = target_units if target_units is not None else spec_opts.get("target_units")
        dxf_version = spec_opts.get("dxf_version", dxf_version) if dxf_version == "R2010" else dxf_version
        text_font_name = spec_opts.get("text_font_name", text_font_name)
        paper_space_layout = paper_space_layout or spec_opts.get("paper_space_layout")

    warnings: list[dict[str, Any]] = []
    missing_information: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    if ir_errors or view_spec is None:
        err_status = (
            "UNSUPPORTED"
            if any(e.get("code") == "UNSUPPORTED_PRIMITIVE" for e in ir_errors)
            else "INVALID_INPUT"
        )
        return _error_manifest(
            drafting_ir=validated if isinstance(validated, dict) else {},
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=(validated.get("model_space") or {}).get("units") if isinstance(validated, dict) else None,
            target_units=target_units,
            export_status=err_status,
            errors=ir_errors,
            warnings=warnings,
            missing_information=missing_information,
            diagnostics=diagnostics,
        )

    if dxf_version not in SUPPORTED_DXF_VERSIONS:
        errs = [
            {
                "code": "UNSUPPORTED_DXF_VERSION",
                "path": "$.dxf_version",
                "message": f"Unsupported DXF version {dxf_version!r}; supported: {SUPPORTED_DXF_VERSIONS}.",
                "requirement_ids": [],
            }
        ]
        return _error_manifest(
            drafting_ir=validated,
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=validated["model_space"]["units"],
            target_units=target_units,
            export_status="UNSUPPORTED",
            errors=errs,
            warnings=warnings,
            missing_information=missing_information,
            diagnostics=diagnostics,
        )

    # Unit resolution & duplicate-conversion guard
    src_units = validated["model_space"]["units"]
    policy_units = validated["unit_policy"]["drawing_units"]
    if src_units != policy_units or src_units not in DXF_INSUNITS:
        errs = [
            {
                "code": "CONFLICTING_UNIT_DECLARATION",
                "path": "$.unit_policy",
                "message": f"Conflicting IR units: model_space={src_units!r}, unit_policy={policy_units!r}.",
                "requirement_ids": [],
            }
        ]
        return _error_manifest(
            drafting_ir=validated,
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=src_units,
            target_units=target_units,
            export_status="INVALID_INPUT",
            errors=errs,
            warnings=warnings,
            missing_information=missing_information,
            diagnostics=diagnostics,
        )

    dst_units = target_units or src_units
    if dst_units not in DXF_INSUNITS:
        errs = [
            {
                "code": "UNKNOWN_TARGET_UNITS",
                "path": "$.target_units",
                "message": f"Unsupported target DXF units {dst_units!r}; supported: ('mm', 'm').",
                "requirement_ids": [],
            }
        ]
        return _error_manifest(
            drafting_ir=validated,
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=src_units,
            target_units=dst_units,
            export_status="UNSUPPORTED",
            errors=errs,
            warnings=warnings,
            missing_information=missing_information,
            diagnostics=diagnostics,
        )

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

    # Paper Space requirement gate (do not fabricate paper sizes!)
    ps_opts = paper_space_layout or {}
    if ps_opts.get("require_paper_space") and not ps_opts.get("paper_size_mm"):
        miss = [
            {
                "code": "PAPER_SIZE_NOT_SUPPLIED",
                "path": "$.paper_space_layout.paper_size_mm",
                "message": "Paper Space requested with require_paper_space=True, but no paper_size_mm was supplied.",
                "requirement_ids": [],
            }
        ]
        return _error_manifest(
            drafting_ir=validated,
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=src_units,
            target_units=dst_units,
            export_status="INCOMPLETE",
            errors=[],
            warnings=warnings,
            missing_information=miss,
            diagnostics=diagnostics,
        )

    # Create DXF document
    doc = ezdxf.new(dxf_version, setup=True)
    doc.header["$INSUNITS"] = DXF_INSUNITS[dst_units]
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.appids.add(VNAI_XDATA_APPID)

    scale_denom = float(validated["paper_space"]["scale_denominator"])
    xr = doc.rootdict.add_xrecord(VNAI_META_KEY)
    xr.reset(
        encode_doc_meta(
            {
                "contract": "architectural-drafting-v1",
                "drawing_ir_digest": validated["drawing_ir_digest"],
                "geom_dims_digest": validated["geometry_and_dimensions_digest"],
                "source_rev": view_spec.get("source_revision_digest"),
                "view_id": view_spec["view_id"],
                "floor_id": view_spec.get("floor_id") or "",
                "view_kind": view_spec["view_kind"],
                "section_kind": view_spec.get("section_kind") or "",
                "source_units": src_units,
                "target_units": dst_units,
                "scale_denom": str(scale_denom),
                "exporter": __version__,
            }
        )
    )

    # Register linetypes & layers strictly from vnai-cad-layers-v1 policy
    if "DOTTED" not in doc.linetypes:
        doc.linetypes.add("DOTTED", pattern=[0.5, 0.0, -0.25])
    layer_policy = validated["layer_policy"]
    layer_issues = validate_layer_policy(layer_policy)
    if layer_issues:
        errs = [
            {"code": "INVALID_LAYER_POLICY", "path": "$.layer_policy", "message": m, "requirement_ids": []}
            for m in layer_issues
        ]
        return _error_manifest(
            drafting_ir=validated,
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=src_units,
            target_units=dst_units,
            export_status="INVALID_INPUT",
            errors=errs,
            warnings=warnings,
            missing_information=missing_information,
            diagnostics=diagnostics,
        )

    registered_layers: set[str] = set()
    for row in layer_policy["layers"]:
        em = row["ezdxf_mapping"]
        lname = em["name"]
        lt = em["linetype"]
        if lt not in doc.linetypes:
            errs = [
                {
                    "code": "UNSUPPORTED_LINETYPE",
                    "path": f"$.layer_policy.{lname}",
                    "message": f"Layer {lname} requests unregistered linetype {lt!r}.",
                    "requirement_ids": [],
                }
            ]
            return _error_manifest(
                drafting_ir=validated,
                view_spec=view_spec,
                dxf_version=dxf_version,
                ezdxf_version=str(ezdxf.__version__),
                source_units=src_units,
                target_units=dst_units,
                export_status="UNSUPPORTED",
                errors=errs,
                warnings=warnings,
                missing_information=missing_information,
                diagnostics=diagnostics,
            )
        lay = doc.layers.add(lname, color=int(em["color"]), linetype=lt)
        lay.dxf.lineweight = int(em["lineweight"])
        lay.dxf.plot = 1 if em["plot"] else 0
        if not em["on"]:
            lay.off()
        registered_layers.add(lname)

    # Text style (Unicode; no proprietary font files embedded/copied)
    doc.styles.add(TEXT_STYLE_NAME, font=text_font_name)

    # Dimension style matching Batch 007-C model_sizing in target units
    sizing = validated["style"]["model_sizing"]
    dimstyle_name = f"VNAI_DIM_{int(round(scale_denom))}"
    ds = doc.dimstyles.new(dimstyle_name)
    ds.dxf.dimtxt = sv(sizing["dim_text_height"])
    ds.dxf.dimasz = sv(sizing["arrow_size"])
    ds.dxf.dimexo = sv(sizing["extension_offset"])
    ds.dxf.dimexe = sv(sizing["extension_overshoot"])
    ds.dxf.dimdec = dst_precision
    ds.dxf.dimzin = 0
    ds.dxf.dimdsep = ord(".")
    ds.dxf.dimtxsty = TEXT_STYLE_NAME
    ds.dxf.dimtad = 1
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimtmove = 1
    ds.dxf.dimscale = 1.0
    ds.dxf.dimlfac = 1.0
    if validated["style"].get("tick_style") == "slash":
        ds.set_arrows(ezdxf.ARROWS.architectural_tick)

    _register_blocks(doc, sizing, sv, TEXT_STYLE_NAME)

    msp = doc.modelspace()
    align_map = {
        "middle": TextEntityAlignment.MIDDLE_CENTER,
        "start": TextEntityAlignment.MIDDLE_LEFT,
        "end": TextEntityAlignment.MIDDLE_RIGHT,
    }
    attach_map = {"middle": 5, "start": 4, "end": 6}
    dims_by_id = {d["id"]: d for d in validated.get("dimensions", [])}

    entity_id_map: dict[str, dict[str, Any]] = {}
    count_by_type: dict[str, int] = {}
    count_by_layer: dict[str, int] = {}
    transformations: list[dict[str, Any]] = []
    unsupported_or_omitted: list[dict[str, Any]] = []
    block_counter = 0

    def register_emitted(ir_ent: dict[str, Any], dxf_ent: Any, part: str, extra: dict[str, Any] | None = None) -> None:
        eid = ir_ent["id"]
        dxftype = dxf_ent.dxftype()
        layer = ir_ent["layer"]
        dxf_ent.set_xdata(
            VNAI_XDATA_APPID,
            encode_ir_xdata(
                entity_id=eid,
                source_geometry_id=ir_ent["source_geometry_id"],
                entity_type=ir_ent["entity_type"],
                view_id=view_spec["view_id"],
                part=part,
                extra=extra,
            ),
        )
        count_by_type[dxftype] = count_by_type.get(dxftype, 0) + 1
        count_by_layer[layer] = count_by_layer.get(layer, 0) + 1
        rec = entity_id_map.setdefault(
            eid,
            {
                "ir_entity_type": ir_ent["entity_type"],
                "layer": layer,
                "source_geometry_id": ir_ent["source_geometry_id"],
                "dxf_types": [],
                "parts": [],
            },
        )
        if dxftype not in rec["dxf_types"]:
            rec["dxf_types"].append(dxftype)
        if part not in rec["parts"]:
            rec["parts"].append(part)

    export_errors: list[dict[str, Any]] = []

    def fail_abort(status_label: str, code: str, path: str, msg: str) -> dict[str, Any]:
        issue({"errors": export_errors}, "errors", code, path, msg)
        return _error_manifest(
            drafting_ir=validated,
            view_spec=view_spec,
            dxf_version=dxf_version,
            ezdxf_version=str(ezdxf.__version__),
            source_units=src_units,
            target_units=dst_units,
            export_status=status_label,
            errors=export_errors,
            warnings=warnings,
            missing_information=missing_information,
            diagnostics=diagnostics,
        )

    for ir_ent in view_spec["entities"]:
        eid = ir_ent["id"]
        et = ir_ent["entity_type"]
        layer = ir_ent["layer"]
        c = ir_ent["coordinates"]
        m = ir_ent.get("metadata", {})

        if layer not in registered_layers:
            return fail_abort(
                "INVALID_INPUT",
                "UNMAPPED_ENTITY_LAYER",
                f"$.entities[{eid}].layer",
                f"Entity {eid} specifies unmapped layer {layer!r}; refusing silent fallback to layer '0'.",
            )
        if et not in PRIMITIVE_TYPES:
            return fail_abort(
                "UNSUPPORTED",
                "UNSUPPORTED_PRIMITIVE",
                f"$.entities[{eid}].entity_type",
                f"Unsupported IR primitive type {et!r}.",
            )

        if et == "LINE":
            de = msp.add_line(spt(c["start"]), spt(c["end"]), dxfattribs={"layer": layer})
            register_emitted(ir_ent, de, "line")

        elif et == "POLYLINE":
            closed = bool(c.get("closed", True))
            ext = [spt(p) for p in (_strip_closing_vertex(c["exterior"]) if closed else c["exterior"])]
            min_pts = 3 if closed else 2
            if len(ext) < min_pts:
                return fail_abort("CONFLICT", "CORRUPT_POLYLINE", eid, f"POLYLINE {eid} has fewer than {min_pts} vertices.")
            lw = msp.add_lwpolyline(ext, close=closed, dxfattribs={"layer": layer})
            register_emitted(ir_ent, lw, "exterior")
            for idx, hole in enumerate(c.get("holes", [])):
                hpts = [spt(p) for p in (_strip_closing_vertex(hole) if closed else hole)]
                if len(hpts) < min_pts:
                    return fail_abort("CONFLICT", "CORRUPT_POLYLINE_HOLE", eid, f"Hole {idx} on {eid} is degenerate.")
                hlw = msp.add_lwpolyline(hpts, close=closed, dxfattribs={"layer": layer})
                register_emitted(ir_ent, hlw, f"hole:{idx}")

        elif et == "ARC":
            radius = sv(c["radius"])
            if radius <= 0:
                return fail_abort("CONFLICT", "CORRUPT_ARC", eid, f"ARC {eid} has non-positive radius {radius}.")
            rot = c.get("rotation", "ccw")
            sa = (float(c["end_angle_deg"]) if rot == "cw" else float(c["start_angle_deg"])) % 360.0
            ea = (float(c["start_angle_deg"]) if rot == "cw" else float(c["end_angle_deg"])) % 360.0
            arc_e = msp.add_arc(
                center=spt(c["center"]),
                radius=radius,
                start_angle=sa,
                end_angle=ea,
                dxfattribs={"layer": layer},
            )
            register_emitted(ir_ent, arc_e, "arc", extra={"rot": rot})

        elif et == "CIRCLE":
            radius = sv(c["radius"])
            if radius <= 0:
                return fail_abort("CONFLICT", "CORRUPT_CIRCLE", eid, f"CIRCLE {eid} has non-positive radius {radius}.")
            circ_e = msp.add_circle(spt(c["center"]), radius=radius, dxfattribs={"layer": layer})
            register_emitted(ir_ent, circ_e, "circle")

        elif et == "TEXT":
            align = align_map.get(m.get("anchor", "middle"), TextEntityAlignment.MIDDLE_CENTER)
            txt_e = msp.add_text(
                str(m.get("text", "")),
                height=sv(m.get("height", sizing["text_height"])),
                rotation=float(m.get("rotation_deg", 0.0)),
                dxfattribs={"layer": layer, "style": TEXT_STYLE_NAME},
            )
            txt_e.set_placement(spt(c["insert"]), align=align)
            register_emitted(ir_ent, txt_e, "text")

        elif et == "MTEXT":
            att = attach_map.get(m.get("anchor", "middle"), 5)
            body = "\\P".join(str(line) for line in m.get("lines", []))
            ls_fac = min(max(float(m.get("line_spacing", 1.25)), 0.25), 4.0)
            mt_e = msp.add_mtext(
                body,
                dxfattribs={
                    "layer": layer,
                    "style": TEXT_STYLE_NAME,
                    "char_height": sv(m.get("height", sizing["text_height"])),
                    "line_spacing_factor": ls_fac,
                },
            )
            mt_e.set_location(spt(c["insert"]), attachment_point=att)
            register_emitted(ir_ent, mt_e, "mtext")

        elif et == "DIMENSION":
            orient = m.get("orientation", "horizontal")
            if orient not in {"horizontal", "vertical"}:
                return fail_abort(
                    "UNSUPPORTED",
                    "UNSUPPORTED_DIMENSION_CONFIG",
                    eid,
                    f"Unsupported linear dimension orientation {orient!r}.",
                )
            p1 = spt(c["ref_point_1"])
            p2 = spt(c["ref_point_2"])
            ls = spt(c["line_start"])
            le = spt(c["line_end"])
            tp = spt(c["text_point"])
            span = abs(p2[0] - p1[0]) if orient == "horizontal" else abs(p2[1] - p1[1])
            if span <= 1e-9:
                return fail_abort(
                    "UNSUPPORTED",
                    "UNSUPPORTED_DIMENSION_CONFIG",
                    eid,
                    f"Dimension {eid} has degenerate zero projected span.",
                )
            did = m.get("dimension_id")
            if did and did in dims_by_id:
                expected_meas = sv(dims_by_id[did]["measured_value"])
                if abs(span - expected_meas) > (1e-4 if dst_units == "mm" else 1e-7):
                    return fail_abort(
                        "CONFLICT",
                        "DIMENSION_SOURCE_INCONSISTENCY",
                        eid,
                        f"Dimension {eid} ref span {span} disagrees with recorded measurement {expected_meas}.",
                    )

            angle = 0.0 if orient == "horizontal" else 90.0
            base = [(ls[0] + le[0]) / 2.0, (ls[1] + le[1]) / 2.0]
            exp_num = format_measurement(dec(span), dst_precision)[0]
            tmpl = _extract_dim_override_template(str(m.get("display_text", "")), exp_num)
            dim_ovr = msp.add_linear_dim(
                base=base,
                p1=p1,
                p2=p2,
                angle=angle,
                text=tmpl,
                dimstyle=dimstyle_name,
                dxfattribs={"layer": layer},
                override={
                    "dimtxt": sv(m.get("height", sizing["dim_text_height"])),
                    "dimasz": sv(m.get("arrow_size", sizing["arrow_size"])),
                    "dimdec": dst_precision,
                    "dimzin": 0,
                    "dimdsep": ord("."),
                    "dimtxsty": TEXT_STYLE_NAME,
                    "dimtmove": 1,
                },
            )
            if math.hypot(tp[0] - base[0], tp[1] - base[1]) > sv(m.get("height", sizing["dim_text_height"])) * 0.4:
                dim_ovr.set_location(tp, leader=False)
            dim_ovr.render()
            dim_ent = dim_ovr.dimension
            dim_ent.dxf.actual_measurement = float(span)
            if abs(float(dim_ent.get_measurement()) - span) > (1e-4 if dst_units == "mm" else 1e-7):
                return fail_abort(
                    "AUDIT_ERROR",
                    "DIMENSION_RENDER_MISMATCH",
                    eid,
                    f"Native DXF DIMENSION measurement {dim_ent.get_measurement()} != {span}.",
                )
            register_emitted(ir_ent, dim_ent, "dimension", extra={"dim_id": did or eid, "orient": orient})

        elif et == "HATCH":
            ext_ring = [spt(p) for p in _strip_closing_vertex(c["exterior"])]
            hole_rings = [[spt(p) for p in _strip_closing_vertex(h)] for h in c.get("holes", [])]
            if len(ext_ring) < 3 or any(len(hr) < 3 for hr in hole_rings):
                return fail_abort("CONFLICT", "INVALID_HATCH_BOUNDARY", eid, f"HATCH {eid} boundary has < 3 vertices.")
            poly = Polygon(ext_ring, hole_rings)
            if not poly.is_valid or poly.is_empty or poly.area <= 0:
                return fail_abort(
                    "CONFLICT",
                    "INVALID_HATCH_BOUNDARY",
                    eid,
                    f"HATCH {eid} boundary polygon is invalid, self-intersecting, or zero-area.",
                )
            hatch = msp.add_hatch(dxfattribs={"layer": layer})
            pat = str(m.get("pattern", "ANSI31")).upper()
            pat_scale = 25.0 if dst_units == "mm" else 0.025
            hatch.set_pattern_fill(pat, scale=pat_scale)
            hatch.paths.add_polyline_path(ext_ring, is_closed=True, flags=1)
            for hr in hole_rings:
                hatch.paths.add_polyline_path(hr, is_closed=True, flags=16)
            register_emitted(ir_ent, hatch, "hatch")

        elif et == "BLOCK_REFERENCE":
            bname = m.get("block_name")
            if not bname or bname not in doc.blocks:
                return fail_abort("INVALID_INPUT", "MISSING_BLOCK_DEFINITION", eid, f"Missing CAD block {bname!r}.")
            sc = float(c.get("scale", 1.0))
            rot = float(c.get("rotation_deg", 0.0))
            ins = msp.add_blockref(
                bname,
                spt(c["insert"]),
                dxfattribs={"layer": layer, "xscale": sc, "yscale": sc, "rotation": rot},
            )
            if bname in {"TAG_DOOR", "TAG_WINDOW"}:
                ins.add_auto_attribs({"MARK": str(m.get("mark", "")), "DIM_LABEL": str(m.get("dimension_label", ""))})
            elif bname == "SYM_LEVEL_MARK":
                ins.add_auto_attribs({"LABEL": str(m.get("label", ""))})
            register_emitted(ir_ent, ins, "block_ref", extra={"bname": bname})

        elif et == "SYMBOL":
            sk = m.get("symbol_kind")
            if sk not in SUPPORTED_SYMBOL_KINDS:
                return fail_abort(
                    "UNSUPPORTED",
                    "UNSUPPORTED_SYMBOL_KIND",
                    eid,
                    f"Unsupported IR SYMBOL kind {sk!r}.",
                )
            if sk == "scale_bar":
                block_counter += 1
                sb_name = f"VNAI_SB_{block_counter}"
                blk = doc.blocks.new(sb_name)
                length_u = sv(c["length"])
                half_u = length_u / 2.0
                bar_h = sv(sizing["dim_text_height"]) * 0.45
                lbl_h = sv(sizing["dim_text_height"]) * 0.75
                blk.add_lwpolyline([(0.0, 0.0), (half_u, 0.0), (half_u, bar_h), (0.0, bar_h)], close=True)
                blk.add_lwpolyline([(half_u, 0.0), (length_u, 0.0), (length_u, bar_h), (half_u, bar_h)], close=True)
                mid_str = format_measurement(dec(half_u), dst_precision)[0]
                end_str = format_measurement(dec(length_u), dst_precision)[0]
                blk.add_text("0", height=lbl_h, dxfattribs={"style": TEXT_STYLE_NAME, "insert": (0.0, -lbl_h * 1.4)})
                blk.add_text(mid_str, height=lbl_h, dxfattribs={"style": TEXT_STYLE_NAME, "insert": (half_u, -lbl_h * 1.4)})
                blk.add_text(
                    f"{end_str} {dst_units} (1:{int(round(scale_denom))})",
                    height=lbl_h,
                    dxfattribs={"style": TEXT_STYLE_NAME, "insert": (length_u, -lbl_h * 1.4)},
                )
                ins = msp.add_blockref(sb_name, spt(c["insert"]), dxfattribs={"layer": layer})
                register_emitted(ir_ent, ins, "scale_bar", extra={"skind": sk})
            elif sk == "section_marker":
                sx, sy = spt(c["start"])
                ex, ey = spt(c["end"])
                lx, ly = m.get("look_direction", [0, 1])
                arrow_len = sv(sizing["text_height"]) * 1.2
                bub_r = sv(sizing["grid_bubble_radius"]) * 0.7
                cl = msp.add_line((sx, sy), (ex, ey), dxfattribs={"layer": layer})
                register_emitted(ir_ent, cl, "cut_line", extra={"skind": sk})
                al = msp.add_line((sx, sy), (sx + lx * arrow_len, sy + ly * arrow_len), dxfattribs={"layer": layer})
                register_emitted(ir_ent, al, "look_arrow", extra={"skind": sk})
                bc = msp.add_circle((sx, sy), radius=bub_r, dxfattribs={"layer": layer})
                register_emitted(ir_ent, bc, "bubble", extra={"skind": sk})
                bt = msp.add_text(
                    str(m.get("label", "S")),
                    height=sv(sizing["dim_text_height"]) * 0.9,
                    dxfattribs={"layer": layer, "style": TEXT_STYLE_NAME},
                )
                bt.set_placement((sx, sy), align=TextEntityAlignment.MIDDLE_CENTER)
                register_emitted(ir_ent, bt, "label", extra={"skind": sk})
            else:  # stair_direction_arrow or slide_direction
                ap = spt(c.get("from_point", c.get("direction_start")))
                bp = spt(c.get("to_point", c.get("direction_end")))
                sh = msp.add_line(ap, bp, dxfattribs={"layer": layer})
                register_emitted(ir_ent, sh, "shaft", extra={"skind": sk})
                dx, dy = bp[0] - ap[0], bp[1] - ap[1]
                lng = math.hypot(dx, dy) or 1.0
                ux, uy = dx / lng, dy / lng
                nx, ny = -uy, ux
                hlen = sv(sizing["arrow_size"])
                chw = hlen * 0.55
                chev = msp.add_lwpolyline(
                    [
                        (bp[0] - hlen * ux + chw * nx, bp[1] - hlen * uy + chw * ny),
                        (bp[0], bp[1]),
                        (bp[0] - hlen * ux - chw * nx, bp[1] - hlen * uy - chw * ny),
                    ],
                    close=False,
                    dxfattribs={"layer": layer},
                )
                register_emitted(ir_ent, chev, "chevron", extra={"skind": sk})

    # Paper Space composition ONLY when explicit paper_size_mm is supplied
    ps_composition: dict[str, Any] = {
        "status": "NOT_GENERATED_NO_PAPER_SIZE_SUPPLIED",
        "model_space_scale": "1:1",
        "paper_space_scale_label": validated["paper_space"]["scale_label"],
    }
    if ps_opts.get("enabled", True) and ps_opts.get("paper_size_mm"):
        pw, ph = [float(v) for v in ps_opts["paper_size_mm"]]
        margins = [float(v) for v in ps_opts.get("margins_mm", [10.0, 10.0, 10.0, 10.0])]
        layout_name = str(view_spec["view_id"])
        layout = doc.layouts.get("Layout1")
        if layout_name != "Layout1":
            doc.layouts.rename("Layout1", layout_name)
        layout = doc.layouts.get(layout_name)
        if "VIEWPORTS" not in doc.layers:
            vp_lay = doc.layers.add("VIEWPORTS", color=8, linetype="CONTINUOUS")
            vp_lay.dxf.plot = 0
        layout.page_setup(size=(pw, ph), margins=tuple(margins), units="mm")
        ml, mb, mr, mt = margins
        border_pts = [(ml, mb), (pw - mr, mb), (pw - mr, ph - mt), (ml, ph - mt)]
        layout.add_lwpolyline(border_pts, close=True, dxfattribs={"layer": "A-GRID"})
        vb = view_spec["bounds"]
        cx_m = sv((vb["min_x"] + vb["max_x"]) / 2.0)
        cy_m = sv((vb["min_y"] + vb["max_y"]) / 2.0)
        vp_w = max(pw - ml - mr - 10.0, 20.0)
        vp_h = max(ph - mb - mt - 24.0, 20.0)
        mm_per_unit = 1.0 if dst_units == "mm" else 1000.0
        view_h = (vp_h * scale_denom) / mm_per_unit
        layout.add_viewport(
            center=(pw / 2.0, mb + 14.0 + vp_h / 2.0),
            size=(vp_w, vp_h),
            view_center_point=(cx_m, cy_m),
            view_height=view_h,
            dxfattribs={"layer": "A-GRID"},
        )
        sub_sec = f" ({view_spec['section_kind']})" if view_spec.get("section_kind") else ""
        title_str = str(ps_opts.get("sheet_title") or validated["paper_space"].get("border", {}).get("project_title") or view_spec["title"])
        dnum = str(ps_opts.get("drawing_number") or validated["paper_space"].get("border", {}).get("drawing_number") or "A-101")
        layout.add_text(
            f"{dnum} | {view_spec['view_id']}{sub_sec} | {title_str} | Scale {validated['paper_space']['scale_label']}",
            dxfattribs={"layer": "A-ROOM-TEXT", "style": TEXT_STYLE_NAME, "height": 3.5, "insert": (ml + 4.0, mb + 4.5)},
        )
        ps_composition = {
            "status": "GENERATED_FROM_EXPLICIT_PAPER_SIZE",
            "layout_name": layout_name,
            "paper_size_mm": [pw, ph],
            "viewport_scale_label": validated["paper_space"]["scale_label"],
            "title_block_supplied": bool(ps_opts.get("title_block_supplied", False)),
        }

    # Transformation provenance summary
    transformations = [
        {"ir_primitive": "LINE", "dxf_entity": "LINE", "analytic": True},
        {"ir_primitive": "POLYLINE", "dxf_entity": "LWPOLYLINE", "analytic": True},
        {"ir_primitive": "ARC", "dxf_entity": "ARC", "analytic": True},
        {"ir_primitive": "CIRCLE", "dxf_entity": "CIRCLE", "analytic": True},
        {"ir_primitive": "TEXT", "dxf_entity": "TEXT", "analytic": True},
        {"ir_primitive": "MTEXT", "dxf_entity": "MTEXT", "analytic": True},
        {"ir_primitive": "DIMENSION", "dxf_entity": "DIMENSION (*D rendered)", "analytic": True},
        {"ir_primitive": "HATCH", "dxf_entity": "HATCH", "analytic": True},
        {"ir_primitive": "BLOCK_REFERENCE", "dxf_entity": "INSERT + ATTRIB", "analytic": True},
        {"ir_primitive": "SYMBOL", "dxf_entity": "INSERT / LINE+CIRCLE+TEXT+LWPOLYLINE", "analytic": True},
    ]

    # Atomic save to sibling temp file, then audit + independent round-trip verify BEFORE publishing
    out_p.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=".vnai-tmp-", suffix=".dxf", dir=str(out_p.parent))
    os.close(tmp_fd)
    tmp_p = Path(tmp_name)
    try:
        doc.saveas(tmp_p)
        roundtrip_rep = verify_dxf_roundtrip(
            validated,
            tmp_p,
            view_id=view_spec["view_id"],
            target_units=dst_units,
            paper_space_layout=ps_opts if ps_opts.get("paper_size_mm") else None,
        )
        audit_rep = roundtrip_rep["dxf_audit"]
        if audit_rep["audit_status"] != "CLEAN" or roundtrip_rep["roundtrip_status"] != "VERIFIED":
            status_code = (
                "AUDIT_ERROR"
                if audit_rep["audit_status"] == "CRITICAL_ERRORS"
                else "CONFLICT"
            )
            errs = [
                {
                    "code": m.get("code", "ROUNDTRIP_OR_AUDIT_FAILURE"),
                    "path": str(m.get("entity_id", "$")),
                    "message": m.get("message", "DXF failed audit or round-trip check."),
                    "requirement_ids": [],
                }
                for m in (roundtrip_rep["mismatches"] or [{"code": "AUDIT_FAILURE", "entity_id": "$", "message": f"Audit status: {audit_rep['audit_status']}"}])
            ]
            return _error_manifest(
                drafting_ir=validated,
                view_spec=view_spec,
                dxf_version=dxf_version,
                ezdxf_version=str(ezdxf.__version__),
                source_units=src_units,
                target_units=dst_units,
                export_status=status_code,
                errors=errs,
                warnings=warnings,
                missing_information=missing_information,
                diagnostics=diagnostics,
                dxf_audit=audit_rep,
                roundtrip=roundtrip_rep,
            )

        os.replace(tmp_p, out_p)
    finally:
        if tmp_p.exists():
            try:
                tmp_p.unlink()
            except OSError:
                pass

    file_sha256 = compute_file_sha256(out_p)
    roundtrip_rep["dxf_path"] = str(out_p)
    roundtrip_rep["dxf_audit"]["dxf_path"] = str(out_p)

    manifest = build_export_manifest(
        drafting_ir=validated,
        view_spec=view_spec,
        dxf_version=dxf_version,
        ezdxf_version=str(ezdxf.__version__),
        source_units=src_units,
        target_units=dst_units,
        unit_policy={
            "source_units": src_units,
            "target_units": dst_units,
            "conversion_factor": zero_float(factor),
            "unit_conversion_applied": src_units != dst_units,
            "insunits": DXF_INSUNITS[dst_units],
            "double_conversion_guard": "EXPLICIT_IR_TO_DXF_ONCE",
        },
        scale_metadata={
            "scale_denominator": scale_denom,
            "scale_label": validated["paper_space"]["scale_label"],
            "scale_authority": validated["paper_space"]["scale_authority"],
            "model_geometry_scaled_by_paper_scale": False,
        },
        entity_count_by_type=count_by_type,
        entity_count_by_layer=count_by_layer,
        supported_transformations=transformations,
        unsupported_or_omitted_entities=unsupported_or_omitted,
        entity_id_map=entity_id_map,
        paper_space_composition=ps_composition,
        unicode_text_verification=roundtrip_rep["unicode_text_verification"],
        dxf_audit=audit_rep,
        roundtrip_verification=roundtrip_rep,
        semantic_fingerprint=roundtrip_rep["semantic_fingerprint"],
        dxf_file_sha256=file_sha256,
        dxf_path=str(out_p),
        export_status="EXPORTED",
        errors=[],
        warnings=warnings,
        missing_information=missing_information,
        diagnostics=diagnostics,
    )

    m_chk = new_report("dxf-manifest-check")
    if not schema_check(manifest, "dxf-manifest.schema.json", m_chk):
        manifest["errors"].extend(m_chk["errors"])
        manifest["export_status"] = "INVALID_INPUT"
        manifest["status"] = "INVALID"
        return manifest

    if man_p is not None:
        man_p.parent.mkdir(parents=True, exist_ok=True)
        # Re-check overwrite protection on manifest target
        with man_p.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(manifest, ensure_ascii=True, indent=2, allow_nan=False) + "\n")

    return manifest
