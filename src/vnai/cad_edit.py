"""Proposed CAD changes and authorized edits on a NEW isolated DXF copy (headless backend).

Flow: ``create_proposal`` (no CAD writes) → human ``cad_copy_edit_authorization`` decision
bound to the proposal digest → ``apply_proposal`` revalidates everything, writes one new copy
inside ``<project>/exports`` without touching the source, then audits and reads it back.

Live AutoCAD documents are never edited: the MCP bridge is read-only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from vnai import __version__
from vnai import project_workflow as pw
from vnai.cad_bridge import CadBridgeError, _open_dxf, compare_cad
from vnai.dxf_manifest import compute_file_sha256, decode_doc_meta, decode_ir_xdata

PROPOSAL_CONTRACT = "vnai-cad-change-proposal-v1"
EDIT_CONTRACT = "vnai-cad-copy-edit-v1"
AUTH_KIND = "cad_copy_edit_authorization"
MAX_OFFSET = 100_000.0  # drawing units; larger moves are almost certainly unit mistakes
OPERATIONS = {
    "translate_source_geometry": "Dịch chuyển mọi entity có cùng source_geometry_id (trừ DIMENSION)",
    "replace_text": "Thay nội dung một TEXT/MTEXT theo vnai_id",
}
EXIT_CODES = {"PROPOSED": 0, "APPLIED_VERIFIED": 0, "APPLIED_VERIFICATION_FAILED": 4,
              "FAILED_NO_OUTPUT": 1, "INTERRUPTED_UNCERTAIN": 4}


def _fingerprint(e: Any) -> str:
    attrs = {k: v for k, v in e.dxfattribs().items() if k not in {"handle", "owner"}}
    extra: Any = None
    t = e.dxftype()
    if t == "LWPOLYLINE":
        extra = [tuple(round(c, 9) for c in p) for p in e.get_points("xyb")]
    elif t == "MTEXT":
        extra = e.text
    elif t == "HATCH":
        extra = [len(getattr(p, "vertices", getattr(p, "edges", []))) for p in e.paths]
    elif t == "INSERT":
        extra = [(a.dxf.tag, a.dxf.text) for a in e.attribs]

    def norm(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 9)
        if isinstance(v, (tuple, list)) or hasattr(v, "__iter__") and not isinstance(v, str):
            try:
                return [norm(x) for x in v]
            except TypeError:
                return str(v)
        return v

    return json.dumps([t, sorted((k, norm(v)) for k, v in attrs.items()), norm(extra)],
                      default=str, sort_keys=True)


def _index(doc: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for e in doc.modelspace():
        x = decode_ir_xdata(e)
        if x:
            out.setdefault(x["id"], []).append(e)
    return out


def _targets(doc: Any, op: dict) -> list[tuple[str, Any]]:
    """Resolve the entities an operation touches, by VNAI ids (never by AutoCAD handle)."""
    found = []
    for e in doc.modelspace():
        x = decode_ir_xdata(e)
        if not x:
            continue
        if op["op"] == "translate_source_geometry" and x.get("src") == op["source_geometry_id"] \
                and e.dxftype() != "DIMENSION":
            found.append((x["id"], e))
        elif op["op"] == "replace_text" and x["id"] == op["entity_id"]:
            found.append((x["id"], e))
    return found


def validate_operations(doc: Any, operations: Any) -> list[str]:
    errors = []
    if not isinstance(operations, list) or not operations:
        return ["operations must be a non-empty list"]
    for i, op in enumerate(operations):
        if not isinstance(op, dict) or op.get("op") not in OPERATIONS:
            errors.append(f"op[{i}]: operation not in allowlist {sorted(OPERATIONS)}")
            continue
        if op["op"] == "translate_source_geometry":
            if set(op) != {"op", "source_geometry_id", "dx", "dy"}:
                errors.append(f"op[{i}]: needs exactly source_geometry_id, dx, dy")
                continue
            for k in ("dx", "dy"):
                v = op[k]
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) \
                        or abs(v) > MAX_OFFSET:
                    errors.append(f"op[{i}].{k}: finite number with |value| <= {MAX_OFFSET}")
        else:
            if set(op) != {"op", "entity_id", "text"} or not isinstance(op.get("text"), str):
                errors.append(f"op[{i}]: needs exactly entity_id and text")
                continue
            if len(op["text"]) > 250 or any(ord(c) < 32 for c in op["text"]):
                errors.append(f"op[{i}].text: <=250 chars, no control characters")
        if not errors or not errors[-1].startswith(f"op[{i}]"):
            hits = _targets(doc, op)
            if not hits:
                errors.append(f"op[{i}]: no VNAI-linked entity matches this operation")
            elif op["op"] == "replace_text" and hits[0][1].dxftype() not in {"TEXT", "MTEXT"}:
                errors.append(f"op[{i}]: replace_text only applies to TEXT/MTEXT")
    return errors


def _bbox(entities: list[Any]) -> list[float] | None:
    from ezdxf import bbox

    ext = bbox.extents(entities, fast=True)
    if not ext.has_data:
        return None
    return [round(ext.extmin.x, 6), round(ext.extmin.y, 6), round(ext.extmax.x, 6),
            round(ext.extmax.y, 6)]


def create_proposal(project: Path, source: Path, ir_path: Path, operations: list,
                    floor: str | None = None, view: str | None = None) -> dict:
    """Write a reviewable change proposal into ``reviews/``; never touches the drawing."""
    project = Path(project).resolve()
    pw.load_project(project)
    source = Path(source).resolve()
    before = compute_file_sha256(source) if source.is_file() else None
    doc = _open_dxf(source)
    errors = validate_operations(doc, operations)
    if errors:
        raise pw.WorkflowError("Invalid change proposal: " + "; ".join(errors))
    ir_path = Path(ir_path).resolve()
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    baseline = compare_cad(ir, source, floor_id=floor, view_id=view, expected_sha256=before)
    target = pw._next_path(project / "exports", f"{source.stem}-cadedit", ".dxf")
    affected, effects, dims = [], [], set()
    for op in operations:
        hits = _targets(doc, op)
        ids = sorted({h[0] for h in hits})
        affected.extend(ids)
        effect: dict[str, Any] = {"op": op, "entity_ids": ids, "bbox_before": _bbox([h[1] for h in hits])}
        if op["op"] == "translate_source_geometry":
            b = effect["bbox_before"]
            effect["bbox_after"] = None if b is None else [
                round(b[0] + op["dx"], 6), round(b[1] + op["dy"], 6),
                round(b[2] + op["dx"], 6), round(b[3] + op["dy"], 6)]
            for e in doc.modelspace():
                x = decode_ir_xdata(e)
                if x and e.dxftype() == "DIMENSION" and x.get("src") == op["source_geometry_id"]:
                    dims.add(x["id"])
        effects.append(effect)
    proposal = {
        "contract": PROPOSAL_CONTRACT,
        "engine_version": __version__,
        "proposal_status": "PROPOSED",
        "source_drawing": {"path": source.as_posix(), "sha256": before},
        "vnai_revision": {"drawing_ir": pw._rel(project, ir_path),
                          "drawing_ir_sha256": compute_file_sha256(ir_path),
                          "drawing_ir_digest": ir.get("drawing_ir_digest")},
        "baseline_comparison_status": baseline.get("comparison_status"),
        "target_copy": pw._rel(project, target),
        "operations": operations,
        "affected_entity_ids": sorted(set(affected)),
        "expected_effects": effects,
        "constraint_impacts": {
            "dimensions_not_moved_become_stale": sorted(dims),
            "vnai_constraints": "NOT_EVALUATED — the copy will deviate from the VNAI revision; "
                                "re-run VNAI (revision → integrated → drafting) to check clearances.",
        },
        "verification_plan": [
            "Re-check source SHA-256 and authorization digest immediately before writing",
            "Write to a temporary file, then link to a new unique path (no overwrite)",
            "Structural DXF audit of the copy",
            "Read-back: exactly the affected entity ids changed; all others identical",
            "Re-hash the source to prove it is unchanged",
            "Compare the copy with the VNAI revision (expected mismatches only on affected ids)",
        ],
        "rollback": "The source is opened read-only and never saved. To roll back, discard the "
                    "new copy; the ledger keeps the record. No AutoCAD undo is involved.",
        "unresolved_risks": [
            "Moved openings may collide with walls/furniture; not checked by this proposal.",
            "Associative dimensions and tags in the copy are not regenerated.",
            "AutoCAD visual check of the copy is still required (PENDING_HUMAN_AUTOCAD_VERIFICATION).",
        ],
        "edit_permission": "NOT_GRANTED",
        "cad_writes_permitted": False,
        "architect_approval": "NOT_GRANTED",
    }
    out = pw._next_path(project / "reviews", "cad-change-proposal", ".json")
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    data = pw.load_project(project)
    data["events"].append({
        "type": "cad_proposal", "id": f"CADP-{sum(e['type'] == 'cad_proposal' for e in data['events']) + 1:03d}",
        "at": pw._now(), "proposal": pw._rel(project, out), "proposal_sha256": pw.sha256(out),
        "source_sha256": before,
    })
    pw._save(project, data)
    if compute_file_sha256(source) != before:  # pragma: no cover - defensive
        raise CadBridgeError("STALE", "Source changed while building the proposal")
    return {**proposal, "proposal_path": pw._rel(project, out), "proposal_sha256": pw.sha256(out)}


def _authorization(data: dict, proposal_sha: str) -> dict | None:
    used = {e.get("authorization_id") for e in data["events"] if e["type"] in {"cad_edit", "cad_edit_started"}}
    for event in reversed(data["events"]):
        if event["type"] == "decision" and event["kind"] == AUTH_KIND \
                and event["target_sha256"] == proposal_sha:
            return None if event["id"] in used else event
    return None


def apply_proposal(project: Path, proposal_path: Path) -> dict:
    """Execute an authorized proposal on a new copy. Refuses on any doubt; never retries."""
    import ezdxf

    project = Path(project).resolve()
    data = pw.load_project(project)
    proposal_path = Path(proposal_path).resolve()
    if not proposal_path.is_file() or project not in proposal_path.parents:
        raise pw.WorkflowError("Proposal must be an existing file inside the project")
    proposal_sha = pw.sha256(proposal_path)
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    if proposal.get("contract") != PROPOSAL_CONTRACT:
        raise pw.WorkflowError("Not a CAD change proposal")
    for e in data["events"]:
        if e["type"] == "cad_edit_started" and e["proposal_sha256"] == proposal_sha and not any(
            r["type"] == "cad_edit" and r.get("started_id") == e["id"] for r in data["events"]
        ):
            raise pw.WorkflowError(
                f"INTERRUPTED_UNCERTAIN: attempt {e['id']} never finished; inspect "
                f"{e['target']} manually. Non-idempotent edits are not retried automatically."
            )
    auth = _authorization(data, proposal_sha)
    if auth is None:
        raise pw.WorkflowError(
            "CAD_EDIT_NOT_AUTHORIZED: no unused cad_copy_edit_authorization bound to this exact "
            "proposal digest (an authorization is single-use)."
        )
    source = Path(proposal["source_drawing"]["path"])
    if not source.is_file():
        raise pw.WorkflowError("STALE: source drawing missing")
    # exports must be a real directory of this project: a symlink/junction/alias that resolves
    # elsewhere is refused (compare the resolved path with the lexical one).
    exports_lex = project / "exports"
    exports = exports_lex.resolve()
    if exports_lex.is_symlink() or os.path.normcase(str(exports)) != os.path.normcase(str(exports_lex)) \
            or not exports.is_dir():
        raise pw.WorkflowError("PATH_REFUSED: <project>/exports is a link/alias or missing")
    rel = Path(str(proposal.get("target_copy", "")))
    if rel.is_absolute() or len(rel.parts) != 2 or rel.parts[0] != "exports" \
            or rel.suffix.lower() != ".dxf":
        raise pw.WorkflowError("PATH_REFUSED: target copy must be a .dxf directly in <project>/exports")
    target = exports / rel.name
    if os.path.lexists(target) or target.resolve() == source.resolve():
        raise pw.WorkflowError("PATH_COLLISION: target exists or equals the source; never overwrite")
    # Recheck digests immediately before modification and edit exactly the verified bytes.
    ir_abs = pw._abs(project, proposal["vnai_revision"]["drawing_ir"])
    ir_bytes = ir_abs.read_bytes() if ir_abs.is_file() else b""
    if hashlib.sha256(ir_bytes).hexdigest() != proposal["vnai_revision"]["drawing_ir_sha256"]:
        raise pw.WorkflowError("STALE: VNAI Drawing IR changed since the proposal")
    src_bytes = source.read_bytes()
    if hashlib.sha256(src_bytes).hexdigest() != proposal["source_drawing"]["sha256"]:
        raise pw.WorkflowError("STALE: source drawing changed since the proposal")
    fd, snap_name = tempfile.mkstemp(prefix=".", suffix=".source.dxf", dir=exports)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(src_bytes)
        doc = _open_dxf(Path(snap_name))
    finally:
        os.unlink(snap_name)
    errors = validate_operations(doc, proposal["operations"])
    if errors:
        raise pw.WorkflowError("SCOPE_REFUSED: " + "; ".join(errors))
    before_fp = {k: sorted(_fingerprint(e) for e in v) for k, v in _index(doc).items()}
    started = {
        "type": "cad_edit_started", "id": f"CADE-{sum(e['type'] == 'cad_edit_started' for e in data['events']) + 1:03d}",
        "at": pw._now(), "authorization_id": auth["id"], "proposal_sha256": proposal_sha,
        "target": pw._rel(project, target),
    }
    data["events"].append(started)
    pw._save(project, data)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".partial", dir=exports)
    os.close(fd)  # exclusive create: a pre-planted link at a predictable temp name cannot be used
    tmp = Path(tmp_name)
    result: dict[str, Any] = {
        "contract": EDIT_CONTRACT, "engine_version": __version__, "backend": "HEADLESS_DXF",
        "proposal": pw._rel(project, proposal_path), "proposal_sha256": proposal_sha,
        "authorization_id": auth["id"], "authorized_by": auth["by"],
        "authorization_synthetic": auth["synthetic"],
        "authentication": "NOT_PERFORMED — the ledger records a statement, not an identity proof",
        "source_drawing": proposal["source_drawing"], "target_copy": pw._rel(project, target),
        "cad_writes_permitted": False,
        "copy_edit_permission": {"scope": "SINGLE_NEW_COPY", "target": pw._rel(project, target),
                                 "operations": len(proposal["operations"]), "status": "USED"},
        "architect_approval": "NOT_GRANTED",
        "vnai_constraints_and_collisions": "NOT_EVALUATED",
        "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
    }
    try:
        for op in proposal["operations"]:
            for _, e in _targets(doc, op):
                if op["op"] == "translate_source_geometry":
                    e.translate(op["dx"], op["dy"], 0)
                elif e.dxftype() == "MTEXT":
                    e.text = op["text"]
                else:
                    e.dxf.text = op["text"]
        doc.saveas(str(tmp))
        os.link(tmp, target)  # fails if target appeared meanwhile: no overwrite
    except Exception as exc:  # noqa: BLE001 - report and stop, never retry
        result["edit_status"] = "INTERRUPTED_UNCERTAIN" if target.exists() else "FAILED_NO_OUTPUT"
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if tmp.exists():
            tmp.unlink()
    if "edit_status" not in result:
        from vnai.dxf_roundtrip import audit_dxf_file

        audit = audit_dxf_file(target)
        after_fp = {k: sorted(_fingerprint(e) for e in v)
                    for k, v in _index(ezdxf.readfile(str(target))).items()}
        changed = sorted(k for k in set(before_fp) | set(after_fp) if before_fp.get(k) != after_fp.get(k))
        expected = sorted(proposal["affected_entity_ids"])
        source_ok = compute_file_sha256(source) == proposal["source_drawing"]["sha256"]
        ir = json.loads(ir_bytes.decode("utf-8"))
        meta = decode_doc_meta(ezdxf.readfile(str(target)))
        try:
            cmp = compare_cad(ir, target, view_id=meta.get("view_id"),
                              floor_id=meta.get("floor_id"))
        except CadBridgeError as exc:
            cmp = {"comparison_status": exc.status}
        unexpected_vs_vnai = sorted(
            i["entity_id"]
            for g in cmp.get("by_source_geometry", {}).values() for i in g.get("issues", [])
            if i["entity_id"] not in expected
        )
        result.update({
            "target_sha256": compute_file_sha256(target),
            "audit_status": audit["audit_status"],
            "readback": {"expected_changed": expected, "actual_changed": changed,
                         "status": "VERIFIED_MATCH" if changed == expected else "VERIFIED_MISMATCH"},
            "source_unchanged": source_ok,
            "vnai_comparison": {"status": cmp.get("comparison_status"),
                                "unexpected_differences": unexpected_vs_vnai,
                                "note": "Differences on affected ids are expected: the copy now "
                                        "deviates from the VNAI revision until a new revision is made."},
        })
        ok = audit["audit_status"] == "CLEAN" and changed == expected and source_ok \
            and not unexpected_vs_vnai
        result["edit_status"] = "APPLIED_VERIFIED" if ok else "APPLIED_VERIFICATION_FAILED"
    report_path = pw._next_path(project / "manifests", "cad-edit", ".json")
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    data = pw.load_project(project)
    event = {"type": "cad_edit", "id": f"{started['id']}-R", "started_id": started["id"],
             "at": pw._now(), "authorization_id": auth["id"], "edit_status": result["edit_status"],
             "report": pw._rel(project, report_path), "report_sha256": pw.sha256(report_path)}
    if target.exists():
        event["target"], event["target_sha256"] = pw._rel(project, target), compute_file_sha256(target)
    data["events"].append(event)
    pw._save(project, data)
    return {**result, "report_path": pw._rel(project, report_path)}
