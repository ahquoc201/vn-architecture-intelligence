"""Explicit CLI for research registry and geometry prototype."""

import argparse
import json
import math
import sys
from pathlib import Path

from vnai.design_brief import validate_design_brief
from vnai.dxf_adapter import export_schematic_dxf
from vnai.fengshui_knowledge import report_repo_fengshui, validate_repo_fengshui
from vnai.insights import validate_repo_insights
from vnai.review import review_markdown, review_plan
from vnai.site_orientation import review_site_orientation
from vnai.space_program import build_space_program
from vnai.source_registry import load_registry, validate_registry

DEFAULT_SOURCES = Path(__file__).resolve().parents[2] / "sources" / "bibliography.yaml"
DEFAULT_INSIGHTS = Path(__file__).resolve().parents[2] / "knowledge" / "insights.yaml"
DEFAULT_FENG_ROOT = Path(__file__).resolve().parents[2] / "knowledge" / "fengshui"


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
    for kind, actions in (("brief", ("validate", "report")), ("program", ("build",))):
        group = design_sub.add_parser(kind)
        action_sub = group.add_subparsers(dest="design_action", required=True)
        for action in actions:
            command = action_sub.add_parser(action)
            command.add_argument("input", help="Design brief JSON")

    review = sub.add_parser("review", help="Review concept polygon geometry")
    review.add_argument("plan")
    review.add_argument("--out", help="Path for JSON report")
    review.add_argument("--markdown", help="Path for Markdown report")

    dxf = sub.add_parser("dxf", help="Export schematic DXF, not construction drawings")
    dxf.add_argument("plan")
    dxf.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "design":
            try:
                # Reject duplicate object keys rather than silently replacing a requirement.
                def unique_object(pairs: list[tuple[str, object]]) -> dict:
                    value = {}
                    for key, child in pairs:
                        if key in value:
                            raise ValueError(f"Duplicate JSON object key: {key}")
                        value[key] = child
                    return value

                def reject_constant(value: str) -> None:
                    raise ValueError(f"Nonfinite JSON number: {value}")

                def finite_float(value: str) -> float:
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError(f"JSON number outside finite range: {value}")
                    return number

                with Path(args.input).open(encoding="utf-8") as stream:
                    brief = json.load(stream, object_pairs_hook=unique_object,
                                      parse_constant=reject_constant, parse_float=finite_float)
                if args.design_kind == "program":
                    report = build_space_program(brief)
                    validation = report["validation"]
                else:
                    validation = validate_design_brief(brief)
                    report = ({**validation, "input_brief": brief}
                              if args.design_action == "report" else validation)
                print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
                return {"VALID": 0, "INVALID": 1, "INCOMPLETE": 3}[validation["status"]]
            except (ValueError, OSError) as exc:
                print(json.dumps({"report_schema_version": 1, "status": "INVALID",
                                  "code": "INPUT_ERROR", "message": str(exc),
                                  "cad_writes_permitted": False}, ensure_ascii=True))
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
