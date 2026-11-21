"""Deterministic DXF export manifest, reversible IR XDATA mapping, and Markdown reports."""

import hashlib
import json
from pathlib import Path
from typing import Any

from vnai import __version__
from vnai.contracts import canonical_digest, load_json

VNAI_XDATA_APPID = "VNAI_IR"
VNAI_META_KEY = "VNAI_META"
SUPPORTED_DXF_VERSIONS = ("R2010", "R2013", "R2018")
DXF_INSUNITS = {"mm": 4, "m": 6}
INSUNITS_TO_UNIT = {4: "mm", 6: "m"}


def compute_file_sha256(path: str | Path) -> str:
    """Compute canonical SHA-256 checksum of an artifact file on disk."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def encode_ir_xdata(
    *,
    entity_id: str,
    source_geometry_id: str,
    entity_type: str,
    view_id: str,
    part: str = "primary",
    extra: dict[str, Any] | None = None,
) -> list[tuple[int, str]]:
    """Encode stable Drawing IR identity metadata as DXF XDATA string tags (<=255 chars each)."""
    items: list[tuple[str, Any]] = [
        ("id", entity_id),
        ("src", source_geometry_id),
        ("et", entity_type),
        ("vid", view_id),
        ("part", part),
    ]
    if extra:
        for key in sorted(extra):
            val = extra[key]
            if val is not None:
                items.append((key, val))
    return [(1000, f"{k}={v}"[:250]) for k, v in items]


def decode_ir_xdata(entity: Any) -> dict[str, str] | None:
    """Decode VNAI_IR XDATA string tags from a reopened DXF entity without using DXF handles."""
    try:
        if not entity.has_xdata(VNAI_XDATA_APPID):
            return None
        tags = entity.get_xdata(VNAI_XDATA_APPID)
    except Exception:
        return None
    out: dict[str, str] = {}
    for code, value in tags:
        if code == 1000 and isinstance(value, str) and "=" in value:
            key, val = value.split("=", 1)
            out[key] = val
    return out if "id" in out else None


def encode_doc_meta(meta: dict[str, Any]) -> list[tuple[int, str]]:
    """Serialize document-level IR provenance tags into XRecord (code=1) entries."""
    out: list[tuple[int, str]] = []
    for key in sorted(meta):
        val = meta[key]
        if val is not None:
            out.append((1, f"{key}={val}"[:250]))
    return out


def decode_doc_meta(doc: Any) -> dict[str, str]:
    """Read document-level VNAI_META XRecord from DXF rootdict if present."""
    out: dict[str, str] = {}
    try:
        if VNAI_META_KEY not in doc.rootdict:
            return out
        xr = doc.rootdict[VNAI_META_KEY]
        for tag in xr.tags:
            if tag.code == 1 and isinstance(tag.value, str) and "=" in tag.value:
                key, val = tag.value.split("=", 1)
                out[key] = val
    except Exception:
        return {}
    return out


def build_export_manifest(
    *,
    drafting_ir: dict[str, Any],
    view_spec: dict[str, Any] | None,
    dxf_version: str,
    ezdxf_version: str | None,
    source_units: str | None,
    target_units: str | None,
    unit_policy: dict[str, Any],
    scale_metadata: dict[str, Any],
    entity_count_by_type: dict[str, int],
    entity_count_by_layer: dict[str, int],
    supported_transformations: list[dict[str, Any]],
    unsupported_or_omitted_entities: list[dict[str, Any]],
    entity_id_map: dict[str, Any],
    paper_space_composition: dict[str, Any],
    unicode_text_verification: dict[str, Any],
    dxf_audit: dict[str, Any],
    roundtrip_verification: dict[str, Any],
    semantic_fingerprint: str | None,
    dxf_file_sha256: str | None,
    dxf_path: str | None,
    export_status: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    missing_information: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Construct canonical dxf-export-manifest-v1 manifest report."""
    src_ir_digest = drafting_ir.get("drawing_ir_digest")
    src_digests = drafting_ir.get("source_digests") or {}
    src_rev_digest = (
        (view_spec or {}).get("source_revision_digest")
        or src_digests.get("source_revision_id")
        or src_digests.get("source_candidate_digest")
    )
    view_id = (view_spec or {}).get("view_id")
    export_seed = [
        src_ir_digest,
        view_id,
        dxf_version,
        target_units,
        semantic_fingerprint,
        dxf_file_sha256,
        export_status,
    ]
    export_id = "DXF-" + canonical_digest(export_seed)[:16]
    status = "INVALID" if errors else "INCOMPLETE" if missing_information else "VALID"
    return {
        "report_schema_version": 1,
        "contract": "dxf-export-manifest-v1",
        "status": status,
        "export_status": export_status,
        "export_id": export_id,
        "export_schema_version": 1,
        "exporter_version": __version__,
        "ezdxf_version": ezdxf_version,
        "dxf_version": dxf_version,
        "source_drawing_ir_digest": src_ir_digest,
        "source_revision_digest": src_rev_digest,
        "source_digests": dict(src_digests),
        "source_units": source_units,
        "target_units": target_units,
        "unit_policy": unit_policy,
        "scale_metadata": scale_metadata,
        "view_id": view_id,
        "floor_id": (view_spec or {}).get("floor_id"),
        "view_kind": (view_spec or {}).get("view_kind"),
        "section_kind": (view_spec or {}).get("section_kind"),
        "entity_count_by_type": dict(sorted(entity_count_by_type.items())),
        "entity_count_by_layer": dict(sorted(entity_count_by_layer.items())),
        "supported_transformations": supported_transformations,
        "unsupported_or_omitted_entities": unsupported_or_omitted_entities,
        "entity_id_map": dict(sorted(entity_id_map.items())),
        "paper_space_composition": paper_space_composition,
        "unicode_text_verification": unicode_text_verification,
        "dxf_audit": dxf_audit,
        "roundtrip_verification": roundtrip_verification,
        "semantic_fingerprint": semantic_fingerprint,
        "dxf_file_sha256": dxf_file_sha256,
        "dxf_path": dxf_path,
        "cad_writes_permitted": False,
        "existing_cad_modification_permitted": False,
        "artifact_export_mode": "EXPLICIT_NEW_DXF_ARTIFACT",
        "approval_inherited": False,
        "architect_approval": "NOT_GRANTED",
        "standards_review": "NOT_EVALUATED",
        "fengshui_review": "NOT_EVALUATED",
        "construction_readiness": "NOT_FOR_CONSTRUCTION_CONCEPTUAL_ONLY",
        "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
        "errors": errors,
        "warnings": warnings,
        "missing_information": missing_information,
        "diagnostics": diagnostics,
    }


def extract_manifest_from_dxf(
    dxf_path: str | Path,
    sidecar_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract deterministic manifest inventory directly from a DXF file (+ optional sidecar)."""
    import ezdxf
    from ezdxf.lldxf.const import DXFError

    path = Path(dxf_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not path.is_file():
        errors.append(
            {
                "code": "DXF_NOT_FOUND",
                "path": str(path),
                "message": f"DXF file does not exist: {path}",
                "requirement_ids": [],
            }
        )
        return {
            "report_schema_version": 1,
            "contract": "dxf-extracted-manifest-v1",
            "status": "INVALID",
            "manifest_status": "INVALID_INPUT",
            "dxf_path": str(path),
            "cad_writes_permitted": False,
            "architect_approval": "NOT_GRANTED",
            "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
            "errors": errors,
            "warnings": warnings,
        }

    file_sha256 = compute_file_sha256(path)
    try:
        doc = ezdxf.readfile(path)
    except (DXFError, OSError, ValueError) as exc:
        errors.append(
            {
                "code": "CORRUPT_DXF",
                "path": str(path),
                "message": f"Failed to parse DXF file: {exc}",
                "requirement_ids": [],
            }
        )
        return {
            "report_schema_version": 1,
            "contract": "dxf-extracted-manifest-v1",
            "status": "INVALID",
            "manifest_status": "INVALID_INPUT",
            "dxf_path": str(path),
            "dxf_file_sha256": file_sha256,
            "cad_writes_permitted": False,
            "architect_approval": "NOT_GRANTED",
            "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
            "errors": errors,
            "warnings": warnings,
        }

    doc_meta = decode_doc_meta(doc)
    insunits = int(doc.header.get("$INSUNITS", 0))
    units_name = INSUNITS_TO_UNIT.get(insunits, f"UNRECOGNIZED_{insunits}")
    by_type: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    id_map: dict[str, dict[str, Any]] = {}
    untagged_count = 0

    for ent in doc.modelspace():
        dxftype = ent.dxftype()
        layer = str(ent.dxf.layer)
        by_type[dxftype] = by_type.get(dxftype, 0) + 1
        by_layer[layer] = by_layer.get(layer, 0) + 1
        xdata = decode_ir_xdata(ent)
        if xdata is None:
            untagged_count += 1
        else:
            ir_id = xdata["id"]
            rec = id_map.setdefault(
                ir_id,
                {
                    "ir_entity_type": xdata.get("et"),
                    "source_geometry_id": xdata.get("src"),
                    "layer": layer,
                    "dxf_types": [],
                    "parts": [],
                },
            )
            if dxftype not in rec["dxf_types"]:
                rec["dxf_types"].append(dxftype)
            part = xdata.get("part", "primary")
            if part not in rec["parts"]:
                rec["parts"].append(part)

    paper_layouts = [
        name
        for name in doc.layouts.names()
        if name != "Model" and len([e for e in doc.layouts.get(name) if e.dxftype() != "VIEWPORT" or e.dxf.id != 1]) > 0
    ]

    sidecar_data: dict[str, Any] | None = None
    sidecar_match: bool | None = None
    if sidecar_path is not None:
        sidecar_data = load_json(sidecar_path)
        sidecar_match = sidecar_data.get("dxf_file_sha256") == file_sha256
        if not sidecar_match:
            warnings.append(
                {
                    "code": "SIDECAR_CHECKSUM_MISMATCH",
                    "path": "$.dxf_file_sha256",
                    "message": "Sidecar manifest dxf_file_sha256 differs from reopened DXF file.",
                    "requirement_ids": [],
                }
            )

    registered_layers = [
        {
            "name": lay.dxf.name,
            "color": int(lay.color),
            "linetype": str(lay.dxf.linetype),
            "lineweight": int(lay.dxf.lineweight),
            "plot": bool(lay.dxf.plot),
            "on": bool(lay.is_on()),
        }
        for lay in doc.layers
    ]

    return {
        "report_schema_version": 1,
        "contract": "dxf-extracted-manifest-v1",
        "status": "VALID",
        "manifest_status": "EXTRACTED",
        "dxf_path": str(path),
        "dxf_file_sha256": file_sha256,
        "dxf_version": str(doc.dxfversion),
        "acad_version": str(doc.acad_release),
        "ezdxf_version": str(ezdxf.__version__),
        "insunits": insunits,
        "target_units": units_name,
        "doc_metadata": doc_meta,
        "model_space_entity_count": sum(by_type.values()),
        "entity_count_by_type": dict(sorted(by_type.items())),
        "entity_count_by_layer": dict(sorted(by_layer.items())),
        "untagged_entity_count": untagged_count,
        "ir_mapped_entity_count": len(id_map),
        "entity_id_map": dict(sorted(id_map.items())),
        "registered_layers": registered_layers,
        "paper_space_layouts_populated": paper_layouts,
        "sidecar_checksum_match": sidecar_match,
        "sidecar_export_id": (sidecar_data or {}).get("export_id"),
        "cad_writes_permitted": False,
        "architect_approval": "NOT_GRANTED",
        "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
        "handle_stability_note": "Mapping uses stable VNAI_IR XDATA IDs rather than volatile DXF handles.",
        "errors": errors,
        "warnings": warnings,
    }


def autocad_acceptance_checklist_markdown() -> str:
    """Return human architect manual AutoCAD verification checklist (stays PENDING until executed)."""
    return "\n".join(
        [
            "## Manual AutoCAD Acceptance Checklist (`PENDING_HUMAN_AUTOCAD_VERIFICATION`)",
            "",
            "> [!IMPORTANT]",
            "> `ezdxf` read-back and audit confirm file structure and geometric equivalence only; full AutoCAD / workstation rendering verification remains **PENDING** until a licensed architect inspects the DXF directly.",
            "",
            "- [ ] **File Opening**: Opens in desktop AutoCAD without recovery prompts or proxy-object errors.",
            "- [ ] **Drawing Units**: `UNITS` reports Insertion Scale = Millimeters (`$INSUNITS=4`) or Meters (`$INSUNITS=6`) matching the manifest.",
            "- [ ] **Overall Dimensions**: `DIST` across building envelope and perimeter matches real-world measurements (e.g., `4000 x 18000 mm` townhouse).",
            "- [ ] **Layer Table**: All `vnai-cad-layers-v1` layers (`A-WALL-EXT`, `A-WALL-INT`, `A-DOOR`, `A-DOOR-SWING`, `A-WIND`, `A-STAIR`, `A-DIMS`, etc.) retain colors, linetypes, lineweights, and `A-REVIEW` non-plot flag.",
            "- [ ] **Native Editable Dimensions**: Selecting a dimension highlights a native AutoCAD `DIMENSION` (`*D<n>` associative block, not exploded lines), and stretching a corner updates the dimension readout.",
            "- [ ] **Vietnamese Unicode Text**: All room labels (`Phòng khách`, `Bếp - Ăn`, `WC Tầng 1`, `Phòng ngủ 1`, etc.) render with clean diacritics using available workstation TTF/SHX fonts.",
            "- [ ] **Analytic Door Arcs**: Selecting a door swing shows a true `ARC` with exact hinge center, leaf radius, and 90° sweep.",
            "- [ ] **Wall Thicknesses**: Parallel wall lines and closed polylines match source B1 wall thicknesses without silent rounding.",
            "- [ ] **Staircase Geometry**: Treads, risers, landings, cut classification (`TRUE_LONGITUDINAL` vs `DEVELOPED_EXPLICIT_WALKING_LINE`), `UP`/`DOWN` arrows, and headroom dimensions match verified B3/B4 output.",
            "- [ ] **Model vs Paper Space**: Model Space contains 1:1 true-scale geometry; if Paper Space layouts were generated from an explicit sheet size, the `VIEWPORT` scale matches `paper_space.scale_label` without scaled model duplicates.",
            "- [ ] **Zero Corrupt Entities**: Running AutoCAD `AUDIT` reports zero errors and zero corrupted geometry.",
            "",
        ]
    )


def dxf_export_markdown(report: dict[str, Any]) -> str:
    """Render concise Markdown report for DXF export + round-trip manifest."""
    lines = [
        "# Production DXF Export & Verification Manifest",
        "",
        f"- **Export ID**: `{report['export_id']}`",
        f"- **Status**: `{report['export_status']}` (`{report['status']}`)",
        f"- **Exporter / ezdxf / DXF Version**: `{report['exporter_version']}` / `{report['ezdxf_version']}` / `{report['dxf_version']}`",
        f"- **View / Floor / Section Kind**: `{report['view_id']}` / `{report['floor_id'] or '-'}` / `{report['section_kind'] or '-'}`",
        f"- **Units**: `{report['source_units']}` → `{report['target_units']}` (guard: `{report['unit_policy'].get('double_conversion_guard')}`)",
        f"- **Scale Preference**: `{report['scale_metadata'].get('scale_label')}` ({report['scale_metadata'].get('scale_authority')})",
        f"- **Source Drawing IR Digest**: `{report['source_drawing_ir_digest']}`",
        f"- **DXF File SHA-256**: `{report['dxf_file_sha256']}`",
        f"- **Semantic Fingerprint**: `{report['semantic_fingerprint']}`",
        f"- **DXF Audit**: `{report['dxf_audit'].get('audit_status')}`",
        f"- **Round-trip Verification**: `{report['roundtrip_verification'].get('equivalence_status')}` (max error: `{report['roundtrip_verification'].get('max_numeric_error')}`)",
        f"- **Unicode Font Status**: `{report['unicode_text_verification'].get('font_rendering_status')}` (`{report['unicode_text_verification'].get('text_count', 0)}` strings verified at UTF-8 code-point level)",
        f"- **CAD Writes Permitted**: `{report['cad_writes_permitted']}` (artifact mode: `{report['artifact_export_mode']}`)",
        f"- **Architect Approval / Standards / Feng Shui**: `{report['architect_approval']}` / `{report['standards_review']}` / `{report['fengshui_review']}`",
        f"- **Manual AutoCAD Acceptance**: `{report['manual_autocad_acceptance_status']}`",
        "",
        "## Entity Inventory (Model Space)",
        "",
        "| Layer | Count |",
        "|---|---|",
    ]
    for lname, cnt in report.get("entity_count_by_layer", {}).items():
        lines.append(f"| `{lname}` | {cnt} |")
    if not report.get("entity_count_by_layer"):
        lines.append("| *(none)* | 0 |")
    lines += [
        "",
        autocad_acceptance_checklist_markdown(),
    ]
    if report.get("errors"):
        lines += ["## Errors", ""]
        for err in report["errors"]:
            lines.append(f"- `{err['code']}` ({err['path']}): {err['message']}")
    return "\n".join(lines).rstrip() + "\n"


def dxf_audit_markdown(report: dict[str, Any]) -> str:
    """Render concise Markdown report for DXF structural audit."""
    lines = [
        "# DXF File Structural Audit",
        "",
        f"- **DXF Path**: `{report.get('dxf_path')}`",
        f"- **Audit Status**: `{report.get('audit_status')}`",
        f"- **Lossless Eligible**: `{report.get('lossless_eligible')}`",
        f"- **Critical Errors**: `{report.get('critical_error_count')}`",
        f"- **Recovered Fixes**: `{report.get('fix_count')}`",
        f"- **Reference / Geometry Issues**: `{report.get('custom_issue_count')}`",
        f"- **CAD Writes Permitted**: `{report.get('cad_writes_permitted')}`",
        "",
    ]
    for bucket, title in (
        ("critical_errors", "Critical Audit Errors"),
        ("fixes", "Recovered Fixes"),
        ("reference_and_geometry_issues", "Reference & Geometry Issues"),
    ):
        items = report.get(bucket, [])
        if items:
            lines += [f"## {title}", ""]
            for it in items:
                lines.append(f"- {json.dumps(it, ensure_ascii=False)}")
            lines.append("")
    return "\n".join(lines)


def dxf_roundtrip_markdown(report: dict[str, Any]) -> str:
    """Render concise Markdown report for semantic round-trip comparison."""
    lines = [
        "# DXF Semantic Round-Trip Verification",
        "",
        f"- **Round-trip Status**: `{report.get('roundtrip_status')}`",
        f"- **Equivalence Class**: `{report.get('equivalence_status')}`",
        f"- **View ID**: `{report.get('view_id')}`",
        f"- **Max Numeric Error**: `{report.get('max_numeric_error')}` (tolerance: `{report.get('coord_tolerance')}`)",
        f"- **Semantic Fingerprint**: `{report.get('semantic_fingerprint')}`",
        f"- **DXF Audit Status**: `{report.get('dxf_audit', {}).get('audit_status')}`",
        f"- **Checked Entities**: `{report.get('checked_entity_count')}` | Missing: `{len(report.get('missing_entities', []))}` | Extra: `{len(report.get('extra_entities', []))}` | Mismatches: `{len(report.get('mismatches', []))}`",
        f"- **CAD Writes Permitted**: `{report.get('cad_writes_permitted')}`",
        "",
    ]
    if report.get("mismatches"):
        lines += ["## Mismatches", ""]
        for mm in report["mismatches"][:30]:
            lines.append(f"- `{mm.get('code')}` ({mm.get('entity_id')}): {mm.get('message')}")
        lines.append("")
    return "\n".join(lines)


def dxf_extracted_manifest_markdown(report: dict[str, Any]) -> str:
    """Render concise Markdown report for an extracted DXF inventory manifest."""
    meta = report.get("doc_metadata") or {}
    lines = [
        "# Extracted DXF Identity & Layer Manifest",
        "",
        f"- **DXF Path**: `{report.get('dxf_path')}`",
        f"- **Status**: `{report.get('manifest_status')}` (`{report.get('status')}`)",
        f"- **DXF Version / ezdxf**: `{report.get('dxf_version')}` / `{report.get('ezdxf_version')}`",
        f"- **Units ($INSUNITS)**: `{report.get('target_units')}` (`{report.get('insunits')}`)",
        f"- **View / Floor / Section**: `{meta.get('view_id')}` / `{meta.get('floor_id') or '-'}` / `{meta.get('section_kind') or '-'}`",
        f"- **Source Drawing IR Digest**: `{meta.get('drawing_ir_digest')}`",
        f"- **DXF File SHA-256**: `{report.get('dxf_file_sha256')}`",
        f"- **IR-Mapped Entities**: `{report.get('ir_mapped_entity_count', 0)}` | **Untagged Entities**: `{report.get('untagged_entity_count', 0)}`",
        f"- **Sidecar Export ID / Checksum Match**: `{report.get('sidecar_export_id')}` / `{report.get('sidecar_checksum_match')}`",
        f"- **CAD Writes Permitted**: `{report.get('cad_writes_permitted')}`",
        f"- **Manual AutoCAD Acceptance**: `{report.get('manual_autocad_acceptance_status')}`",
        "",
    ]
    return "\n".join(lines)
