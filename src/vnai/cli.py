"""Explicit CLI for research registry and geometry prototype."""

import argparse
import json
import sys
from pathlib import Path

from vnai.candidate_review import review_candidate
from vnai.openings import validate_openings
from vnai.circulation import analyze_circulation
from vnai.stairs import validate_stairs
from vnai.architectural_review import architectural_review
from vnai.contracts import load_json
from vnai.design_brief import validate_design_brief
from vnai.dxf_adapter import export_schematic_dxf
from vnai.fengshui_knowledge import report_repo_fengshui, validate_repo_fengshui
from vnai.floorplan import generate_floorplans, EXIT_CODES as FLOORPLAN_EXIT_CODES
from vnai.insights import validate_repo_insights
from vnai.resources import data_path
from vnai.review import review_markdown, review_plan
from vnai.site_orientation import review_site_orientation
from vnai.space_program import build_space_program
from vnai.source_registry import load_registry, validate_registry
from vnai.spatial import validate_geometry
from vnai.zoning import validate_zoning

DEFAULT_SOURCES = data_path("sources/bibliography.yaml")
DEFAULT_INSIGHTS = data_path("knowledge/insights.yaml")
DEFAULT_FENG_ROOT = data_path("knowledge/fengshui")


def load_plan(file: str | Path) -> dict:
    with Path(file).open(encoding="utf-8") as stream:
        plan = json.load(stream)
    if not isinstance(plan, dict):
        raise ValueError("Plan JSON must be object")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vnai")
    sub = parser.add_subparsers(dest="command", required=True)

    registry = sub.add_parser("sources", help="Source bibliography operations")
    source_sub = registry.add_subparsers(dest="action", required=True)
    validate = source_sub.add_parser("validate")
    validate.add_argument("--file", default=str(DEFAULT_SOURCES))

    knowledge = sub.add_parser("knowledge", help="Review-corpus integrity operations")
    knowledge_sub = knowledge.add_subparsers(dest="action", required=True)
    validate_k = knowledge_sub.add_parser("validate")
    validate_k.add_argument("--file", default=str(DEFAULT_INSIGHTS))
    validate_k.add_argument("--sources", default=str(DEFAULT_SOURCES))

    fengshui = sub.add_parser("fengshui", help="Geometric orientation, not divination")
    feng_sub = fengshui.add_subparsers(dest="action", required=True)
    orientation = feng_sub.add_parser("orientation", help="Compass azimuth from site vectors")
    orientation.add_argument("input", help="Orientation JSON with true north and outward frontage")
    orientation.add_argument("--out", help="Save JSON result to this file")

    fknowledge = feng_sub.add_parser("knowledge", help="Research queue; no rules executable")
    fk_sub = fknowledge.add_subparsers(dest="faction", required=True)
    for action in ("validate", "report"):
        command = fk_sub.add_parser(action)
        command.add_argument("--editions", default=str(DEFAULT_FENG_ROOT / "edition-evidence.yaml"))
        command.add_argument("--terms", default=str(DEFAULT_FENG_ROOT / "terminology.yaml"))
        command.add_argument("--rules", default=str(DEFAULT_FENG_ROOT / "rule-candidates.yaml"))
        command.add_argument("--sources", default=str(DEFAULT_SOURCES))
        if action == "report":
            command.add_argument("--out", help="Save research queue JSON")

    design = sub.add_parser("design", help="Design brief and room program; no CAD writes")
    design_sub = design.add_subparsers(dest="design_kind", required=True)
    for kind, actions in (
        ("brief", ("validate", "report")),
        ("program", ("build",)),
        ("zoning", ("validate", "report")),
        ("floorplan", ("generate",)),
        ("candidate", ("review",)),
        ("openings", ("validate", "draft", "drafting-validate", "schedule", "preview")),
        ("circulation", ("analyze",)),
        ("stairs", ("validate", "draft", "drafting-validate", "section", "schedule", "preview")),
    ):
        group = design_sub.add_parser(kind)
        action_sub = group.add_subparsers(dest="design_action", required=True)
        for action in actions:
            command = action_sub.add_parser(action)
            command.add_argument("input", help="Design contract JSON")
            if kind == "openings" and action == "preview":
                command.add_argument(
                    "--out", required=True, help="Create a new actual opening SVG exclusively"
                )
            if kind == "openings" and action == "schedule":
                command.add_argument("--markdown", help="Create a new opening schedule exclusively")
            if kind == "stairs" and action == "preview":
                command.add_argument("--view", choices=("plan", "section"), default="plan")
                command.add_argument("--out", required=True)
            if kind == "stairs" and action in {"section", "schedule"}:
                command.add_argument("--markdown")
            if kind == "floorplan":
                command.add_argument(
                    "--provenance",
                    action="store_true",
                    help="Include explicit source/candidate provenance sidecars",
                )
                command.add_argument("--candidates", type=int, choices=(1, 2, 3))
                command.add_argument("--max-steps", type=int)
                command.add_argument(
                    "--out", help="Write JSON report to a new file; never overwrite"
                )

    integrated = design_sub.add_parser(
        "integrated", help="Bounded proposed wall-aware design workflow"
    )
    integrated_actions = integrated.add_subparsers(dest="design_action", required=True)
    for action in ("generate", "refine", "validate", "report", "preview"):
        command = integrated_actions.add_parser(action)
        command.add_argument("input")
        command.add_argument("--out", required=action == "preview")
        command.add_argument("--markdown")
        if action == "preview":
            command.add_argument(
                "--view", choices=("before", "after", "comparison", "section"), default="comparison"
            )
            command.add_argument("--floor")

    candidates = design_sub.add_parser(
        "candidates", help="Evidence-based evaluation; no auto approval"
    )
    candidates_sub = candidates.add_subparsers(dest="design_action", required=True)
    for action in ("evaluate", "compare", "rank"):
        command = candidates_sub.add_parser(action)
        command.add_argument("input", help="Versioned evaluation request JSON")
        if action != "evaluate":
            command.add_argument(
                "--markdown", help="Create a new human-readable report; never overwrite"
            )

    for kind, actions in (
        ("replay", ("validate", "report")),
        ("revision", ("compare",)),
        ("readiness", ("report",)),
        ("benchmark", ("run",)),
    ):
        group = design_sub.add_parser(kind)
        action_sub = group.add_subparsers(dest="design_action", required=True)
        for action in actions:
            command = action_sub.add_parser(action)
            command.add_argument("input", help="Versioned design workflow JSON")
            command.add_argument("--markdown", help="Create a new Markdown report; never overwrite")

    wall_group = design_sub.add_parser(
        "walls", help="Construct proposed wall polygons; no CAD writes"
    )
    wall_actions = wall_group.add_subparsers(dest="design_action", required=True)
    for action in ("generate", "validate", "report", "preview"):
        command = wall_actions.add_parser(action)
        command.add_argument("input", help="Wall specification/source or stored wall report JSON")
        if action == "preview":
            command.add_argument(
                "--out", required=True, help="Create a new SVG preview exclusively"
            )
        if action == "report":
            command.add_argument(
                "--markdown", help="Create a new human-readable report exclusively"
            )

    drafting_group = design_sub.add_parser(
        "drafting", help="Architectural dimensions, annotations, CAD layers & SVG previews; no CAD writes"
    )
    drafting_actions = drafting_group.add_subparsers(dest="design_action", required=True)
    for action in ("generate", "validate", "report", "preview", "layers"):
        command = drafting_actions.add_parser(action)
        command.add_argument("input", help="Drafting input, integrated/wall/stair report or stored drafting IR JSON")
        if action != "validate":
            command.add_argument("--config", help="Optional drafting configuration overlay JSON")
            command.add_argument("--scale", type=float, help="Optional project paper scale denominator (e.g. 50, 100)")
            command.add_argument("--units", choices=("mm", "m"), help="Optional drawing model units")
        if action == "generate":
            command.add_argument("--out", help="Write drafting IR JSON to a new file exclusively")
            command.add_argument("--markdown", help="Create a new Markdown drafting report exclusively")
        if action in {"report", "layers"}:
            command.add_argument("--markdown", help="Create a new Markdown report exclusively")
        if action == "preview":
            command.add_argument("--out", required=True, help="Create a new SVG preview exclusively")
            command.add_argument("--floor", help="Filter preview to a specific floor or view ID")
            command.add_argument("--view", choices=("sheet", "plan", "section"), default="sheet")
            command.add_argument("--layers", help="Comma-separated list of visible layers")
            command.add_argument("--hide-layers", help="Comma-separated list of hidden layers")

    dxf_design = design_sub.add_parser(
        "dxf", help="Production DXF export, audit, manifest and semantic round-trip verification"
    )
    dxf_actions = dxf_design.add_subparsers(dest="design_action", required=True)
    for action in ("export", "audit", "verify", "manifest"):
        command = dxf_actions.add_parser(action)
        command.add_argument(
            "input",
            help="Drawing IR / Export Spec JSON (export, verify) or DXF file (audit, manifest)",
        )
        if action == "export":
            command.add_argument("--out", required=True, help="Explicit new .dxf output path")
            command.add_argument("--view", help="Exact view_id to export")
            command.add_argument("--floor", help="Exact floor_id to export")
            command.add_argument("--units", choices=("mm", "m"), help="Target DXF model units")
            command.add_argument(
                "--dxf-version",
                default="R2010",
                help="Target DXF release version (R2010, R2013, R2018)",
            )
            command.add_argument(
                "--font",
                default="Arial.ttf",
                help="Text style font filename reference (no proprietary font files bundled)",
            )
            command.add_argument(
                "--paper-size",
                help="Explicit supplied paper size WxH in mm (e.g. 420x297) for Paper Space layout",
            )
            command.add_argument(
                "--require-paper-space",
                action="store_true",
                help="Return INCOMPLETE if no explicit paper size is supplied",
            )
            command.add_argument("--manifest", help="Optional sidecar manifest JSON output path")
            command.add_argument(
                "--overwrite",
                action="store_true",
                help="Allow replacing an existing non-protected output artifact",
            )
        if action == "verify":
            command.add_argument("--dxf", required=True, help="DXF file to reopen and verify")
            command.add_argument("--view", help="Exact view_id to verify")
            command.add_argument("--floor", help="Exact floor_id to verify")
            command.add_argument("--units", choices=("mm", "m"), help="Expected DXF model units")
        if action == "manifest":
            command.add_argument("--sidecar", help="Optional sidecar manifest JSON to cross-check")
        command.add_argument("--markdown", help="Optional Markdown summary report output path")

    architecture = design_sub.add_parser(
        "architectural-review", help="Separate geometry, graph, clearance and approval results"
    )
    architecture.add_argument("input", help="Candidate review context JSON")

    geometry = sub.add_parser("geometry", help="2D spatial contract; no CAD writes")
    geometry_sub = geometry.add_subparsers(dest="geometry_action", required=True)
    for action in ("validate", "report"):
        command = geometry_sub.add_parser(action)
        command.add_argument("input", help="Geometry contract JSON")

    review = sub.add_parser("review", help="Review concept polygon geometry")
    review.add_argument("plan")
    review.add_argument("--out", help="Path for JSON report")
    review.add_argument("--markdown", help="Path for Markdown report")

    dxf = sub.add_parser("dxf", help="Export schematic DXF, not construction drawings")
    dxf.add_argument("plan")
    dxf.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command in {"design", "geometry"}:
            try:
                if args.command == "design" and args.design_kind == "dxf":
                    from vnai.dxf_export import EXIT_CODES as DXF_EXIT_CODES, export_drafting_dxf
                    from vnai.dxf_manifest import (
                        dxf_audit_markdown,
                        dxf_export_markdown,
                        dxf_extracted_manifest_markdown,
                        dxf_roundtrip_markdown,
                        extract_manifest_from_dxf,
                    )
                    from vnai.dxf_roundtrip import (
                        ROUNDTRIP_EXIT_CODES,
                        audit_dxf_file,
                        verify_dxf_roundtrip,
                    )

                    md_path = getattr(args, "markdown", None)
                    overwrite = bool(getattr(args, "overwrite", False))
                    if md_path and not overwrite and Path(md_path).exists():
                        raise FileExistsError(f"Markdown report already exists: {md_path}")

                    if args.design_action == "export":
                        man_path = getattr(args, "manifest", None)
                        if md_path and Path(md_path).resolve() in {
                            Path(args.out).resolve(),
                            *(({Path(man_path).resolve()}) if man_path else set()),
                        }:
                            raise ValueError("Markdown output path aliases DXF or manifest path.")
                        ir_doc = load_json(args.input)
                        ps_layout: dict[str, object] | None = None
                        if getattr(args, "paper_size", None) or getattr(
                            args, "require_paper_space", False
                        ):
                            ps_layout = {
                                "enabled": True,
                                "require_paper_space": bool(
                                    getattr(args, "require_paper_space", False)
                                ),
                            }
                            if getattr(args, "paper_size", None):
                                raw_sz = str(args.paper_size).lower().split("x")
                                if len(raw_sz) != 2:
                                    raise ValueError(
                                        f"Invalid --paper-size {args.paper_size!r}; use WxH in mm (e.g. 420x297)."
                                    )
                                pw, ph = float(raw_sz[0]), float(raw_sz[1])
                                if pw <= 0 or ph <= 0:
                                    raise ValueError("Paper size dimensions must be positive.")
                                ps_layout["paper_size_mm"] = [pw, ph]
                        report = export_drafting_dxf(
                            ir_doc,
                            args.out,
                            view_id=getattr(args, "view", None),
                            floor_id=getattr(args, "floor", None),
                            target_units=getattr(args, "units", None),
                            dxf_version=args.dxf_version,
                            text_font_name=args.font,
                            paper_space_layout=ps_layout,
                            manifest_out=man_path,
                            overwrite=overwrite,
                            source_input_path=args.input,
                        )
                        md_text = dxf_export_markdown(report)
                        exit_code = DXF_EXIT_CODES[report["export_status"]]
                    elif args.design_action == "audit":
                        report = audit_dxf_file(args.input)
                        md_text = dxf_audit_markdown(report)
                        exit_code = ROUNDTRIP_EXIT_CODES[report["audit_status"]]
                    elif args.design_action == "verify":
                        ir_doc = load_json(args.input)
                        report = verify_dxf_roundtrip(
                            ir_doc,
                            args.dxf,
                            view_id=getattr(args, "view", None),
                            floor_id=getattr(args, "floor", None),
                            target_units=getattr(args, "units", None),
                        )
                        md_text = dxf_roundtrip_markdown(report)
                        exit_code = ROUNDTRIP_EXIT_CODES[report["roundtrip_status"]]
                    else:  # manifest
                        report = extract_manifest_from_dxf(
                            args.input, sidecar_path=getattr(args, "sidecar", None)
                        )
                        md_text = dxf_extracted_manifest_markdown(report)
                        exit_code = 0 if report["status"] == "VALID" else 1

                    if md_path:
                        target_md = Path(md_path)
                        target_md.parent.mkdir(parents=True, exist_ok=True)
                        with target_md.open(
                            "w" if overwrite else "x", encoding="utf-8", newline="\n"
                        ) as stream:
                            stream.write(md_text)
                    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                    return exit_code

                brief = load_json(args.input)
                if args.command == "design" and args.design_kind == "integrated":
                    targets = [Path(p).resolve() for p in [args.out, args.markdown] if p]
                    if len(targets) != len(set(targets)) or any(p.exists() for p in targets):
                        raise FileExistsError(
                            "Requested integrated output exists or output paths alias; use new versioned paths."
                        )
                    from vnai.integrated_design import (
                        integrated_design,
                        validate_integrated,
                        EXIT_CODES as INTEGRATED_CODES,
                    )
                    from vnai.integrated_preview import integrated_svg, integrated_markdown

                    report = (
                        validate_integrated(brief)
                        if args.design_action in {"validate", "report", "preview"}
                        else integrated_design(brief, refine=args.design_action == "refine")
                    )
                    payload = (
                        json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
                    )
                    target, content = None, None
                    if args.design_action == "preview":
                        target, content = (
                            Path(args.out),
                            integrated_svg(report, view=args.view, floor=args.floor),
                        )
                    elif args.out:
                        target, content = Path(args.out), payload
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(content)
                    if args.markdown:
                        target = Path(args.markdown)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(integrated_markdown(report))
                    print(payload, end="")
                    return INTEGRATED_CODES[report["integrated_status"]]
                if args.command == "design" and args.design_kind == "drafting":
                    out_path = getattr(args, "out", None)
                    md_path = getattr(args, "markdown", None)
                    targets = [Path(p).resolve() for p in [out_path, md_path] if p]
                    if len(targets) != len(set(targets)) or any(p.exists() for p in targets):
                        raise FileExistsError(
                            "Requested drafting output exists or output paths alias; use new versioned paths."
                        )
                    from vnai.drafting_engine import (
                        EXIT_CODES as DRAFTING_CODES,
                        ensure_no_finalized_ir_overrides,
                        extract_layers_report,
                        generate_drafting,
                        validate_drafting,
                    )
                    from vnai.drafting_preview import (
                        drafting_markdown,
                        drafting_svg,
                        layers_markdown,
                    )

                    cfg_override = load_json(args.config) if getattr(args, "config", None) else None
                    if cfg_override is not None and not isinstance(cfg_override, dict):
                        raise ValueError("Drafting config JSON must be an object.")
                    scale_override = getattr(args, "scale", None)
                    units_override = getattr(args, "units", None)

                    if args.design_action in {"layers", "report", "preview"}:
                        ensure_no_finalized_ir_overrides(
                            brief,
                            config_override=cfg_override,
                            scale_override=scale_override,
                            units_override=units_override,
                        )

                    if args.design_action == "validate":
                        report = validate_drafting(brief)
                    elif args.design_action == "layers":
                        report = extract_layers_report(
                            brief,
                            config_override=cfg_override,
                            scale_override=scale_override,
                            units_override=units_override,
                        )
                    elif (
                        args.design_action in {"report", "preview"}
                        and brief.get("contract") == "architectural-drafting-v1"
                    ):
                        report = validate_drafting(brief)
                    else:
                        report = generate_drafting(
                            brief,
                            config_override=cfg_override,
                            scale_override=scale_override,
                            units_override=units_override,
                        )

                    payload = (
                        json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
                    )
                    target, content = None, None
                    if args.design_action == "preview":
                        inc = (
                            {s.strip() for s in args.layers.split(",") if s.strip()}
                            if args.layers
                            else None
                        )
                        hid = (
                            {s.strip() for s in args.hide_layers.split(",") if s.strip()}
                            if args.hide_layers
                            else None
                        )
                        target, content = (
                            Path(args.out),
                            drafting_svg(
                                report,
                                view=args.view,
                                floor=args.floor,
                                include_layers=inc,
                                hide_layers=hid,
                            ),
                        )
                    elif out_path:
                        target, content = Path(out_path), payload
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(content)
                    if md_path:
                        md_content = (
                            layers_markdown(report)
                            if args.design_action == "layers"
                            else drafting_markdown(report)
                        )
                        target_md = Path(md_path)
                        target_md.parent.mkdir(parents=True, exist_ok=True)
                        with target_md.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(md_content)
                    print(payload, end="")
                    return DRAFTING_CODES[report["drafting_status"]]
                if (
                    args.command == "design"
                    and args.design_kind == "stairs"
                    and args.design_action != "validate"
                ):
                    from vnai.stair_drafting import (
                        draft_stairs,
                        validate_drafting as validate_stair_draft,
                        EXIT_CODES as STAIR_DRAFT_CODES,
                    )
                    from vnai.stair_preview import stair_svg, stair_markdown

                    report = (
                        validate_stair_draft(brief)
                        if args.design_action == "drafting-validate"
                        else draft_stairs(brief)
                    )
                    target = None
                    if args.design_action == "preview":
                        target, content = Path(args.out), stair_svg(report, args.view)
                    elif args.design_action in {"section", "schedule"} and args.markdown:
                        target, content = Path(args.markdown), stair_markdown(report)
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(content)
                    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                    return STAIR_DRAFT_CODES[report["drafting_status"]]
                if (
                    args.command == "design"
                    and args.design_kind == "openings"
                    and args.design_action != "validate"
                ):
                    from vnai.opening_drafting import (
                        draft_openings,
                        validate_drafting,
                        EXIT_CODES as OPENING_DRAFT_EXIT_CODES,
                    )
                    from vnai.opening_preview import opening_svg, opening_markdown

                    report = (
                        validate_drafting(brief)
                        if args.design_action == "drafting-validate"
                        else draft_openings(brief)
                    )
                    target = None
                    if args.design_action == "preview" and report["floors"]:
                        target, content = Path(args.out), opening_svg(report)
                    elif args.design_action == "schedule" and args.markdown:
                        target, content = Path(args.markdown), opening_markdown(report)
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(content)
                    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                    return OPENING_DRAFT_EXIT_CODES[report["drafting_status"]]
                if args.command == "design" and args.design_kind == "walls":
                    from vnai.walls import (
                        generate_walls,
                        validate_walls,
                        EXIT_CODES as WALL_EXIT_CODES,
                    )
                    from vnai.wall_preview import wall_svg, wall_markdown

                    report = (
                        validate_walls(brief)
                        if args.design_action == "validate"
                        else generate_walls(brief)
                    )
                    target = None
                    content = None
                    if args.design_action == "preview" and report["floors"]:
                        target, content = Path(args.out), wall_svg(report)
                    elif args.design_action == "report" and args.markdown:
                        target, content = Path(args.markdown), wall_markdown(report)
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(content)
                    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                    return WALL_EXIT_CODES[report["wall_status"]]
                if args.command == "design" and args.design_kind in {
                    "replay",
                    "revision",
                    "readiness",
                    "benchmark",
                }:
                    from vnai.design_replay import validate_replay
                    from vnai.design_revision import compare_revision
                    from vnai.cad_readiness import readiness_report
                    from vnai.architectural_benchmark import run_benchmark
                    from vnai.design_reports import workflow_exit, workflow_markdown

                    report = {
                        "replay": validate_replay,
                        "revision": compare_revision,
                        "readiness": readiness_report,
                        "benchmark": run_benchmark,
                    }[args.design_kind](brief)
                    if args.markdown:
                        target = Path(args.markdown)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(workflow_markdown(report))
                    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                    return workflow_exit(report)
                if args.command == "design" and args.design_kind == "candidates":
                    from vnai.candidate_evaluation import evaluate_candidates
                    from vnai.candidate_comparison import compare_candidates
                    from vnai.candidate_ranking import rank_candidates

                    report = {
                        "evaluate": evaluate_candidates,
                        "compare": compare_candidates,
                        "rank": rank_candidates,
                    }[args.design_action](brief)
                    if getattr(args, "markdown", None):
                        target = Path(args.markdown)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(report["markdown"])
                    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                    if report["errors"]:
                        return 1
                    if args.design_action == "rank":
                        return {
                            "RANKED": 0,
                            "TIED": 0,
                            "NO_ELIGIBLE_CANDIDATES": 4,
                            "PARTIALLY_COMPARABLE": 3,
                            "RANKING_WITHHELD": 3,
                        }[report["ranking_status"]]
                    return {"VALID": 0, "INVALID": 1, "INCOMPLETE": 3}[report["status"]]
                if args.command == "geometry":
                    report = validate_geometry(brief)
                    validation = report
                elif args.design_kind in {
                    "candidate",
                    "openings",
                    "circulation",
                    "stairs",
                    "architectural-review",
                }:
                    handlers = {
                        "candidate": review_candidate,
                        "openings": validate_openings,
                        "circulation": analyze_circulation,
                        "stairs": validate_stairs,
                        "architectural-review": architectural_review,
                    }
                    report = handlers[args.design_kind](brief)
                    validation = report
                elif args.design_kind == "floorplan":
                    report = generate_floorplans(
                        brief,
                        candidate_count=args.candidates,
                        max_steps=args.max_steps,
                        include_provenance=args.provenance,
                    )
                    payload = (
                        json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
                    )
                    if args.out:
                        target = Path(args.out)
                        # Exclusive creation preserves reports and prevents overwriting any input.
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(payload)
                    print(payload, end="")
                    return FLOORPLAN_EXIT_CODES[report["status"]]
                elif args.design_kind == "zoning":
                    report = validate_zoning(brief)
                    validation = report
                elif args.design_kind == "program":
                    report = build_space_program(brief)
                    validation = report["validation"]
                else:
                    validation = validate_design_brief(brief)
                    report = (
                        {**validation, "input_brief": brief}
                        if args.design_action == "report"
                        else validation
                    )
                print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                return {"VALID": 0, "INVALID": 1, "INCOMPLETE": 3}[validation["status"]]
            except (ValueError, OSError) as exc:
                print(
                    json.dumps(
                        {
                            "report_schema_version": 1,
                            "status": "INVALID",
                            "code": "INPUT_ERROR",
                            "message": str(exc),
                            "cad_writes_permitted": False,
                        },
                        ensure_ascii=True,
                    )
                )
                return 2
        if args.command == "sources":
            issues = validate_registry(load_registry(args.file))
            if issues:
                for issue in issues:
                    print(f"ERROR: {issue}", file=sys.stderr)
                return 1
            print("Source registry structurally valid (NOT content/rule approval).")
            return 0
        if args.command == "knowledge":
            issues = validate_repo_insights(args.file, args.sources)
            if issues:
                for issue in issues:
                    print(f"ERROR: {issue}", file=sys.stderr)
                return 1
            print("Research insights structurally valid (NOT executable or expert-approved).")
            return 0
        if args.command == "fengshui" and args.action == "knowledge":
            paths = (args.editions, args.terms, args.rules, args.sources)
            if args.faction == "validate":
                issues = validate_repo_fengshui(*paths)
                if issues:
                    for issue in issues:
                        print(f"ERROR: {issue}", file=sys.stderr)
                    return 1
                print("Feng shui research queue structurally valid (NO rules approved).")
                return 0
            payload = json.dumps(report_repo_fengshui(*paths), ensure_ascii=False, indent=2) + "\n"
            if args.out:
                target = Path(args.out)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(payload, encoding="utf-8")
                print(f"Research-only report: {target}")
            else:
                print(payload, end="")
            return 0
        if args.command == "fengshui" and args.action == "orientation":
            report = review_site_orientation(load_plan(args.input))
            result = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.out:
                target = Path(args.out)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(result, encoding="utf-8")
                print(f"Orientation JSON (no feng shui approval): {target}")
            else:
                print(result, end="")
            return 0
        if args.command == "review":
            report = review_plan(load_plan(args.plan))
            result = json.dumps(report, ensure_ascii=False, indent=2)
            if args.out:
                target = Path(args.out)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(result + "\n", encoding="utf-8")
                print(f"JSON report: {target}")
            else:
                print(result)
            if args.markdown:
                target = Path(args.markdown)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(review_markdown(report), encoding="utf-8")
                print(f"Markdown report: {target}")
            return 0
        if args.command == "dxf":
            target = export_schematic_dxf(load_plan(args.plan), args.out)
            print(f"SCHEMATIC DXF ONLY: {target}")
            return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
