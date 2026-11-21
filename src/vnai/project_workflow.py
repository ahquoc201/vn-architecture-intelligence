"""Resumable project workspace that orchestrates existing deterministic VNAI commands.

The workspace adds no design logic. Each ``step`` runs one existing ``vnai`` CLI command
in-process with new versioned output paths, then appends a ledger event recording the
command, input/output SHA-256 digests, engine status and exit-code meaning. Human
decisions (requirement confirmation, selection, review, approval, export authorization)
are separate ledger events bound to an exact artifact digest. Nothing here grants CAD
modification rights; a new DXF export needs a matching ``export_authorization`` decision.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from vnai import __version__

CONTRACT = "vnai-workflow-project-v1"
LEDGER = "project.json"
FOLDERS = ("brief", "zoning", "candidates", "reviews", "drafting", "exports", "manifests")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
STATUS_KEYS = (
    "export_status",
    "equivalence_status",
    "roundtrip_status",
    "audit_status",
    "integrated_status",
    "generation_status",
    "evaluation_status",
    "readiness_status",
    "drafting_status",
    "status",
)
EXIT_MEANINGS = {
    0: ("OK", "Lệnh hoàn tất; kết quả vẫn là PROPOSED, chưa phải phê duyệt."),
    1: ("INVALID_OR_FAILED", "Dữ liệu sai cấu trúc hoặc kiểm tra thất bại; cần sửa đầu vào."),
    2: ("INPUT_OR_IO_ERROR", "Không đọc/ghi được tệp hoặc tham số sai; không phải lỗi thiết kế."),
    3: ("INCOMPLETE", "Thiếu thông tin bắt buộc; hỏi kiến trúc sư, không tự điền."),
    4: ("CONFLICT", "Xung đột/không khả thi/bằng chứng cũ; giữ nguyên ràng buộc, báo xung đột."),
    5: ("UNSUPPORTED", "Engine chưa hỗ trợ điều kiện này; giải thích giới hạn, không tự chế cách."),
    6: ("SEARCH_EXHAUSTED", "Hết không gian tìm kiếm; không chứng minh là bất khả thi."),
}
CRASH = ("ENGINE_CRASH", "Lỗi ngoài dự kiến của engine; giữ đầu vào và báo cáo để kiểm tra.")
DECISION_KINDS = {
    "requirement_confirmation": "Xác nhận yêu cầu/brief",
    "candidate_selection": "Chọn phương án (không phải phê duyệt)",
    "architect_feedback": "Góp ý của kiến trúc sư cho bản sửa",
    "architect_review": "Kiến trúc sư đã xem xét (không phải phê duyệt)",
    "architect_approval": "Kiến trúc sư phê duyệt (chỉ ghi lời người thật)",
    "export_authorization": "Cho phép tạo tệp DXF MỚI từ đúng Drawing IR này",
    "cad_copy_edit_authorization": (
        "Cho phép áp dụng đúng đề xuất thay đổi này lên MỘT bản sao DXF mới (một lần)"
    ),
}
REFUSED_KINDS = {
    "cad_modification": (
        "Sửa trực tiếp bản vẽ CAD/DWG gốc hoặc tài liệu AutoCAD đang mở không được hỗ trợ; "
        "hãy lập đề xuất (project cad-propose) và cho phép sửa trên bản sao."
    ),
}
PIPELINE = (
    "brief",
    "program",
    "zoning",
    "floorplan",
    "integrated",
    "evaluate",
    "drafting",
    "preview",
    "export",
    "audit",
    "verify",
)
STEPS = {
    # step: (output folder, output stem, output extension or None when stdout is the result)
    "brief": ("brief", "brief-validation", None),
    "brief-report": ("brief", "brief-report", None),
    "program": ("zoning", "space-program", None),
    "zoning": ("zoning", "zoning-validation", None),
    "geometry": ("zoning", "geometry-validation", None),
    "floorplan": ("candidates", "floorplan", ".json"),
    "integrated": ("candidates", "integrated", ".json"),
    "integrated-preview": ("candidates", "integrated-preview", ".svg"),
    "candidate-review": ("reviews", "candidate-review", None),
    "openings": ("reviews", "openings-validation", None),
    "opening-draft": ("candidates", "opening-draft", None),
    "circulation": ("reviews", "circulation", None),
    "stairs": ("reviews", "stairs-validation", None),
    "stair-draft": ("candidates", "stair-draft", None),
    "architectural-review": ("reviews", "architectural-review", None),
    "evaluate": ("reviews", "evaluation", None),
    "compare": ("reviews", "comparison", ".md"),
    "replay": ("reviews", "replay", None),
    "revision": ("reviews", "revision-compare", None),
    "readiness": ("reviews", "readiness", ".md"),
    "drafting": ("drafting", "drawing-ir", ".json"),
    "preview": ("drafting", "preview", ".svg"),
    "export": ("exports", "export", ".dxf"),
    "audit": ("reviews", "dxf-audit", ".md"),
    "verify": ("reviews", "dxf-verify", ".md"),
}

SIMPLE_COMMANDS = {
    "candidate-review": ["design", "candidate", "review"],
    "openings": ["design", "openings", "validate"],
    "opening-draft": ["design", "openings", "draft"],
    "circulation": ["design", "circulation", "analyze"],
    "stairs": ["design", "stairs", "validate"],
    "stair-draft": ["design", "stairs", "draft"],
    "architectural-review": ["design", "architectural-review"],
}


class WorkflowError(ValueError):
    """Refused workflow operation; the project ledger is left unchanged."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(project: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(project.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _abs(project: Path, stored: str) -> Path:
    candidate = Path(stored)
    return candidate if candidate.is_absolute() else project / candidate


def load_project(project: Path) -> dict:
    ledger = Path(project) / LEDGER
    if not ledger.is_file():
        raise WorkflowError(f"Not a VNAI project (missing {LEDGER}): {project}")
    data = json.loads(ledger.read_text(encoding="utf-8"))
    if data.get("contract") != CONTRACT:
        raise WorkflowError(f"Unsupported project contract: {data.get('contract')}")
    return data


def _save(project: Path, data: dict) -> None:
    ledger = Path(project) / LEDGER
    fd, tmp = tempfile.mkstemp(dir=project, prefix=".project-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(tmp, ledger)


def init_project(project: Path, name: str) -> dict:
    project = Path(project)
    if (project / LEDGER).exists():
        raise WorkflowError(f"Project already exists; resume it instead: {project}")
    if not SAFE_ID.match(name):
        raise WorkflowError("Project name must match [A-Za-z0-9_.:-]{1,64}")
    for folder in FOLDERS:
        (project / folder).mkdir(parents=True, exist_ok=True)
    (project / "manifests" / "runs").mkdir(exist_ok=True)
    data = {
        "contract": CONTRACT,
        "schema_version": 1,
        "project_name": name,
        "created_at": _now(),
        "created_with_engine": __version__,
        "cad_writes_permitted": False,
        "cad_modification_permitted": False,
        "note": "Workflow ledger. Engine outputs stay PROPOSED; decisions are human statements.",
        "events": [],
    }
    _save(project, data)
    return data


def _next_path(folder: Path, stem: str, ext: str) -> Path:
    pattern = re.compile(rf"^{re.escape(stem)}-v(\d{{3}})\.")
    used = [int(m.group(1)) for p in folder.glob(f"{stem}-v*") if (m := pattern.match(p.name))]
    return folder / f"{stem}-v{(max(used) + 1) if used else 1:03d}{ext}"


def import_file(project: Path, source: Path, folder: str, label: str | None = None) -> dict:
    """Copy an external input into the workspace under a new versioned name."""
    data = load_project(project)
    if folder not in FOLDERS:
        raise WorkflowError(f"Folder must be one of {FOLDERS}")
    source = Path(source)
    if not source.is_file():
        raise WorkflowError(f"Input not found: {source}")
    stem = label or source.stem
    if not SAFE_ID.match(stem):
        raise WorkflowError("Label must match [A-Za-z0-9_.:-]{1,64}")
    target = _next_path(Path(project) / folder, stem, source.suffix.lower() or ".json")
    shutil.copyfile(source, target)
    event = {
        "type": "import",
        "id": f"IMP-{sum(e['type'] == 'import' for e in data['events']) + 1:03d}",
        "at": _now(),
        "source_name": source.name,
        "source_sha256": sha256(source),
        "artifact": _rel(project, target),
        "sha256": sha256(target),
    }
    data["events"].append(event)
    _save(project, data)
    return event


def _authorization_for(data: dict, project: Path, ir_path: Path) -> dict | None:
    digest = sha256(ir_path)
    for event in reversed(data["events"]):
        if (
            event["type"] == "decision"
            and event["kind"] == "export_authorization"
            and event["target_sha256"] == digest
        ):
            return event
    return None


def _build(step: str, project: Path, src: Path, opts: dict) -> tuple[list[str], dict, str]:
    folder_name, stem, ext = STEPS[step]
    folder = project / folder_name
    floor, view = opts.get("floor"), opts.get("view")
    for value in (floor, view):
        if value is not None and not SAFE_ID.match(value):
            raise WorkflowError("floor/view identifiers must match [A-Za-z0-9_.:-]{1,64}")
    suffix = "-".join(x for x in (floor, view) if x)
    if suffix:
        stem = f"{stem}-{suffix}"
    out = _next_path(folder, stem, ext) if ext else None
    s = str(src)
    outputs: dict[str, Path] = {}
    if step == "brief":
        argv = ["design", "brief", "validate", s]
    elif step == "brief-report":
        argv = ["design", "brief", "report", s]
    elif step == "program":
        argv = ["design", "program", "build", s]
    elif step == "zoning":
        argv = ["design", "zoning", "validate", s]
    elif step == "geometry":
        argv = ["geometry", "validate", s]
    elif step == "floorplan":
        argv = ["design", "floorplan", "generate", s, "--provenance", "--out", str(out)]
        argv += ["--candidates", str(opts.get("candidates") or 3)]
        outputs["report"] = out
    elif step == "integrated":
        mode = opts.get("mode") or "refine"
        if mode not in {"generate", "refine"}:
            raise WorkflowError("integrated mode must be generate or refine")
        md = out.with_suffix(".md")
        argv = ["design", "integrated", mode, s, "--out", str(out), "--markdown", str(md)]
        outputs.update(report=out, markdown=md)
    elif step == "integrated-preview":
        argv = ["design", "integrated", "preview", s, "--view", view or "comparison"]
        argv += (["--floor", floor] if floor else []) + ["--out", str(out)]
        outputs["svg"] = out
    elif step in SIMPLE_COMMANDS:
        argv = [*SIMPLE_COMMANDS[step], s]
    elif step == "evaluate":
        argv = ["design", "candidates", "evaluate", s]
    elif step == "compare":
        argv = ["design", "candidates", "compare", s, "--markdown", str(out)]
        outputs["markdown"] = out
    elif step == "replay":
        argv = ["design", "replay", "validate", s]
    elif step == "revision":
        argv = ["design", "revision", "compare", s]
    elif step == "readiness":
        argv = ["design", "readiness", "report", s, "--markdown", str(out)]
        outputs["markdown"] = out
    elif step == "drafting":
        md = out.with_suffix(".md")
        argv = ["design", "drafting", "generate", s, "--out", str(out), "--markdown", str(md)]
        outputs.update(ir=out, markdown=md)
    elif step == "preview":
        argv = ["design", "drafting", "preview", s, "--view", view or "sheet"]
        argv += (["--floor", floor] if floor else []) + ["--out", str(out)]
        outputs["svg"] = out
    elif step == "export":
        if not (floor or view):
            raise WorkflowError("export needs an explicit --floor or --view")
        manifest = _next_path(project / "manifests", stem, ".manifest.json")
        md = out.with_suffix(".md")
        argv = ["design", "dxf", "export", s, "--out", str(out), "--manifest", str(manifest)]
        argv += ["--floor", floor] if floor else ["--view", view]
        if opts.get("units"):
            argv += ["--units", opts["units"]]
        argv += ["--markdown", str(md)]
        outputs.update(dxf=out, manifest=manifest, markdown=md)
    elif step == "audit":
        argv = ["design", "dxf", "audit", s, "--markdown", str(out)]
        outputs["markdown"] = out
    elif step == "verify":
        dxf = opts.get("dxf")
        if not dxf or not Path(dxf).is_file():
            raise WorkflowError("verify needs --dxf pointing to an exported DXF file")
        argv = ["design", "dxf", "verify", s, "--dxf", str(Path(dxf).resolve())]
        argv += (["--floor", floor] if floor else []) + (["--view", view] if view else [])
        if opts.get("units"):
            argv += ["--units", opts["units"]]
        argv += ["--markdown", str(out)]
        outputs["markdown"] = out
    else:  # pragma: no cover - guarded by argparse choices
        raise WorkflowError(f"Unknown step {step}")
    return argv, outputs, folder_name


def run_step(project: Path, step: str, source: Path, **opts) -> dict:
    """Run one existing VNAI command and append a digest-bound ledger event."""
    from vnai.cli import main as vnai_main

    project = Path(project).resolve()
    data = load_project(project)
    if step not in STEPS:
        raise WorkflowError(f"Unknown step {step}; choose from {sorted(STEPS)}")
    src = Path(source).resolve()
    if not src.is_file():
        raise WorkflowError(f"Input not found: {source}")
    authorization = None
    if step == "export":
        if project not in src.parents:
            raise WorkflowError("Export input must be a Drawing IR stored inside the project")
        authorization = _authorization_for(data, project, src)
        if authorization is None:
            raise WorkflowError(
                "EXPORT_NOT_AUTHORIZED: record an explicit export_authorization decision "
                "bound to this exact Drawing IR before exporting a new DXF."
            )
    if opts.get("dxf"):
        opts["dxf"] = str(Path(opts["dxf"]).resolve())
    argv, outputs, _ = _build(step, project, src, opts)
    input_sha = sha256(src)
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = vnai_main(argv)
        category, meaning = EXIT_MEANINGS.get(exit_code, CRASH)
    except SystemExit as exc:  # argparse usage errors
        exit_code = exc.code if isinstance(exc.code, int) else 2
        category, meaning = EXIT_MEANINGS.get(exit_code, CRASH)
    except Exception as exc:  # noqa: BLE001 - recorded, never hidden
        exit_code = 70
        category, meaning = CRASH
        stderr.write(f"{type(exc).__name__}: {exc}\n")
    run_no = sum(e["type"] == "run" for e in data["events"]) + 1
    run_id = f"RUN-{run_no:03d}"
    stdout_path = project / "manifests" / "runs" / f"{run_id}-{step}.stdout.json"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(stdout.getvalue(), encoding="utf-8")
    statuses: dict[str, object] = {}
    try:
        payload = json.loads(stdout.getvalue())
        if isinstance(payload, dict):
            statuses = {k: payload[k] for k in STATUS_KEYS if isinstance(payload.get(k), str)}
    except json.JSONDecodeError:
        payload = None
    primary = next((statuses[k] for k in STATUS_KEYS if k in statuses), None)
    produced = {
        role: {"path": _rel(project, path), "sha256": sha256(path)}
        for role, path in outputs.items()
        if path.is_file()
    }
    produced["stdout"] = {"path": _rel(project, stdout_path), "sha256": sha256(stdout_path)}
    event = {
        "type": "run",
        "id": run_id,
        "step": step,
        "at": _now(),
        "engine_version": __version__,
        "command": ["vnai", *[_rel(project, Path(a)) if os.sep in a or "/" in a else a
                              for a in argv]],
        "input": {"path": _rel(project, src), "sha256": input_sha},
        "outputs": produced,
        "exit_code": exit_code,
        "category": category,
        "meaning_vi": meaning,
        "primary_status": primary,
        "statuses": statuses,
        "stderr": stderr.getvalue().strip()[-2000:],
        "cad_writes_permitted": False,
    }
    if authorization is not None:
        event["authorization_id"] = authorization["id"]
    data["events"].append(event)
    _save(project, data)
    return event


def record_decision(
    project: Path,
    kind: str,
    target: Path,
    statement: str,
    by: str,
    synthetic: bool = False,
) -> dict:
    """Record a human decision bound to the exact digest of one workspace artifact."""
    project = Path(project).resolve()
    data = load_project(project)
    if kind in REFUSED_KINDS:
        raise WorkflowError(REFUSED_KINDS[kind])
    if kind not in DECISION_KINDS:
        raise WorkflowError(f"Decision kind must be one of {sorted(DECISION_KINDS)}")
    if not statement.strip() or not by.strip():
        raise WorkflowError("A decision needs the person's own statement and name/role")
    target = Path(target).resolve()
    if not target.is_file() or project not in target.parents:
        raise WorkflowError("Decision target must be an existing artifact inside the project")
    if kind == "export_authorization" and target.suffix.lower() != ".json":
        raise WorkflowError("export_authorization must target a Drawing IR JSON artifact")
    if kind == "cad_copy_edit_authorization":
        try:
            contract = json.loads(target.read_text(encoding="utf-8")).get("contract")
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            contract = None
        if contract != "vnai-cad-change-proposal-v1":
            raise WorkflowError("cad_copy_edit_authorization must target a CAD change proposal")
    number = sum(e["type"] == "decision" for e in data["events"]) + 1
    event = {
        "type": "decision",
        "id": f"DEC-{number:03d}",
        "kind": kind,
        "label_vi": DECISION_KINDS[kind],
        "at": _now(),
        "by": by.strip(),
        "statement": statement.strip(),
        "target": _rel(project, target),
        "target_sha256": sha256(target),
        "synthetic": bool(synthetic),
        "grants_cad_modification": False,
        "note": (
            "Ledger record of a human statement. It does not change engine artifacts, "
            "which keep architect_approval NOT_GRANTED and cad_writes_permitted false."
        ),
    }
    if kind == "export_authorization":
        event["scope"] = "NEW_DXF_FILES_ONLY_NO_OVERWRITE"
    if kind == "cad_copy_edit_authorization":
        event["scope"] = "SINGLE_USE_NEW_COPY_EXACT_PROPOSAL_OPERATIONS"
    data["events"].append(event)
    _save(project, data)
    return event


def project_status(project: Path) -> dict:
    """Re-hash every recorded artifact and summarise where the workflow can resume."""
    project = Path(project).resolve()
    data = load_project(project)
    integrity = []
    latest: dict[str, dict] = {}
    produced_by: dict[str, dict] = {}
    for event in data["events"]:
        if event["type"] == "import":
            items = [("artifact", event["artifact"], event["sha256"])]
        elif event["type"] == "run":
            latest[event["step"]] = event
            items = [("input", event["input"]["path"], event["input"]["sha256"])]
            for role, out in event["outputs"].items():
                items.append((role, out["path"], out["sha256"]))
                produced_by[out["path"]] = event
        else:
            continue
        for role, stored, digest in items:
            path = _abs(project, stored)
            state = "MISSING" if not path.is_file() else (
                "INTACT" if sha256(path) == digest else "MODIFIED"
            )
            if state != "INTACT":
                integrity.append({"event": event["id"], "role": role, "path": stored,
                                  "state": state})
    decisions = []
    for event in data["events"]:
        if event["type"] != "decision":
            continue
        path = _abs(project, event["target"])
        if not path.is_file():
            validity = "STALE_TARGET_MISSING"
        elif sha256(path) != event["target_sha256"]:
            validity = "STALE_TARGET_CHANGED"
        else:
            validity = "CURRENT"
            source_run = produced_by.get(event["target"])
            if source_run and latest[source_run["step"]]["id"] != source_run["id"]:
                validity = "SUPERSEDED_BY_NEWER_RUN"
        decisions.append({"id": event["id"], "kind": event["kind"], "target": event["target"],
                          "by": event["by"], "synthetic": event["synthetic"],
                          "validity": validity})
    steps = {
        step: {"run": e["id"], "category": e["category"], "primary_status": e["primary_status"],
               "exit_code": e["exit_code"], "outputs": {k: v["path"]
                                                         for k, v in e["outputs"].items()}}
        for step, e in latest.items()
    }
    next_actions = []
    blocked = [s for s, e in latest.items() if e["category"] != "OK"]
    for step in blocked:
        next_actions.append(f"Bước '{step}': {latest[step]['meaning_vi']}")
    done = [s for s in PIPELINE if s in latest and latest[s]["category"] == "OK"]
    if done and not blocked:
        idx = PIPELINE.index(done[-1])
        if idx + 1 < len(PIPELINE):
            nxt = PIPELINE[idx + 1]
            if nxt == "export":
                next_actions.append(
                    "Có thể xuất DXF MỚI khi người dùng yêu cầu rõ ràng và ghi "
                    "export_authorization gắn với đúng Drawing IR."
                )
            else:
                next_actions.append(f"Bước tiếp theo có thể chạy: '{nxt}'.")
    if not latest:
        next_actions.append("Chưa có bước nào: thu thập brief rồi chạy bước 'brief'.")
    if integrity:
        next_actions.insert(0, "Có tệp bị sửa/mất sau khi ghi nhận: chạy lại bước liên quan.")
    finished = {e.get("started_id") for e in data["events"] if e["type"] == "cad_edit"}
    cad_edits = [
        {"id": e["id"], "edit_status": e["edit_status"], "target": e.get("target"),
         "report": e["report"]}
        for e in data["events"] if e["type"] == "cad_edit"
    ] + [
        {"id": e["id"], "edit_status": "INTERRUPTED_UNCERTAIN", "target": e["target"],
         "report": None}
        for e in data["events"] if e["type"] == "cad_edit_started" and e["id"] not in finished
    ]
    if any(c["edit_status"] == "INTERRUPTED_UNCERTAIN" for c in cad_edits):
        next_actions.insert(0, "Có lần sửa bản sao CAD bị gián đoạn: kiểm tra tay, không tự chạy lại.")
    approvals = [d for d in decisions if d["kind"] == "architect_approval"
                 and d["validity"] == "CURRENT" and not d["synthetic"]]
    return {
        "contract": CONTRACT,
        "status": "STALE" if integrity else "INTACT",
        "project_name": data["project_name"],
        "engine_version": __version__,
        "events": len(data["events"]),
        "steps": steps,
        "integrity_issues": integrity,
        "decisions": decisions,
        "human_approval_recorded": bool(approvals),
        "cad_copy_edits": cad_edits,
        "cad_writes_permitted": False,
        "cad_modification_permitted": False,
        "next_actions_vi": next_actions,
    }


def status_markdown(report: dict) -> str:
    lines = [
        f"# Dự án {report['project_name']} — trạng thái workflow",
        "",
        f"Toàn vẹn tệp: **{report['status']}**. CAD writes: false. "
        "Kết quả engine luôn là PROPOSED.",
        "",
        "| Bước | Lần chạy | Kết quả | Trạng thái engine |",
        "|---|---|---|---|",
    ]
    for step, info in report["steps"].items():
        lines.append(f"| {step} | {info['run']} | {info['category']} | {info['primary_status']} |")
    if report["decisions"]:
        lines += ["", "| Quyết định | Loại | Người | Hiệu lực |", "|---|---|---|---|"]
        for d in report["decisions"]:
            who = d["by"] + (" (synthetic)" if d["synthetic"] else "")
            lines.append(f"| {d['id']} | {d['kind']} | {who} | {d['validity']} |")
    for issue in report["integrity_issues"]:
        lines.append(f"- ⚠ {issue['path']}: {issue['state']} ({issue['event']})")
    lines += ["", "## Tiếp theo", *[f"- {a}" for a in report["next_actions_vi"]], ""]
    return "\n".join(lines)
