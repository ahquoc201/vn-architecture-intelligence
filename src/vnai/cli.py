"""Explicit CLI for research registry and geometry prototype."""

import argparse
import json
import sys
from pathlib import Path

from vnai.dxf_adapter import export_schematic_dxf
from vnai.insights import validate_repo_insights
from vnai.review import review_markdown, review_plan
from vnai.source_registry import load_registry, validate_registry

DEFAULT_SOURCES = Path(__file__).resolve().parents[2] / "sources" / "bibliography.yaml"
DEFAULT_INSIGHTS = Path(__file__).resolve().parents[2] / "knowledge" / "insights.yaml"


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

    review = sub.add_parser("review", help="Review concept polygon geometry")
    review.add_argument("plan")
    review.add_argument("--out", help="Path for JSON report")
    review.add_argument("--markdown", help="Path for Markdown report")

    dxf = sub.add_parser("dxf", help="Export schematic DXF, not construction drawings")
    dxf.add_argument("plan")
    dxf.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
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
