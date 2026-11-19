"""Shared local JSON contracts and deterministic diagnostics for Batch 005."""

from datetime import datetime
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from vnai import __version__
from vnai.resources import data_path

SCHEMA_NAMES = (
    "design-brief.schema.json",
    "zoning.schema.json",
    "geometry.schema.json",
    "floorplan-input.schema.json",
    "floorplan-candidate.schema.json",
    "candidate-review.schema.json",
    "opening.schema.json",
    "stair-connection.schema.json",
    "circulation-graph.schema.json",
    "opening-result.schema.json",
    "stair-result.schema.json",
    "architectural-review.schema.json",
    "evaluation-config.schema.json",
    "metric-result.schema.json",
    "evidence-coverage.schema.json",
    "candidate-evaluation-input.schema.json",
    "candidate-evaluation.schema.json",
    "candidate-comparison.schema.json",
    "candidate-ranking.schema.json",
    "generation-provenance.schema.json",
    "design-replay.schema.json",
    "design-revision.schema.json",
    "cad-readiness.schema.json",
    "architectural-benchmark.schema.json",
    "wall-input.schema.json",
    "wall-result.schema.json",

)
BASE = "https://vnai.invalid/contracts/"


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def load_json(path: str | Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise ValueError(f"Nonfinite JSON number: {value}")

    def number(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            reject(value)
        return parsed

    with Path(path).open(encoding="utf-8") as stream:
        return json.load(
            stream, object_pairs_hook=unique, parse_constant=reject, parse_float=number
        )


def new_report(kind: str) -> dict:
    return {
        "report_schema_version": 1,
        "engine_version": __version__,
        "contract": kind,
        "status": "VALID",
        "errors": [],
        "warnings": [],
        "missing_information": [],
        "diagnostics": [],
        "cad_writes_permitted": False,
        "standards_review": "NOT_EVALUATED",
        "fengshui_review": "NOT_EVALUATED",
    }


def issue(
    report: dict,
    bucket: str,
    code: str,
    path: str,
    message: str,
    requirements: list[str] | None = None,
) -> None:
    report[bucket].append(
        {"code": code, "path": path, "message": message, "requirement_ids": requirements or []}
    )


def finish(report: dict) -> dict:
    report["status"] = (
        "INVALID"
        if report["errors"]
        else "INCOMPLETE"
        if report["missing_information"]
        else "VALID"
    )
    return report


def schema_check(doc: Any, name: str, report: dict) -> bool:
    schemas = {}
    for schema_name in SCHEMA_NAMES:
        schema = load_json(data_path("knowledge/architecture/" + schema_name))
        schema["$id"] = BASE + schema_name
        schemas[schema_name] = schema
    registry = Registry().with_resources(
        (BASE + key, Resource.from_contents(value)) for key, value in schemas.items()
    )
    checker = FormatChecker()

    @checker.checks("date-time", raises=(ValueError, OverflowError))
    def timestamp(value: Any) -> bool:
        # jsonschema's date-time checker otherwise requires an optional dependency.
        if not isinstance(value, str):
            return True  # The schema's type check diagnoses non-strings.
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value,
            flags=re.IGNORECASE,
        ):
            return False
        return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).utcoffset() is not None

    selected = (
        schemas[name]
        if "#" not in name
        else {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": BASE + name}
    )
    validator = Draft202012Validator(selected, registry=registry, format_checker=checker)
    from vnai.design_brief import _nonfinite

    for path in _nonfinite(doc):
        issue(report, "errors", "NONFINITE_NUMBER", path, "Numbers must be finite.")
    for error in sorted(validator.iter_errors(doc), key=lambda e: (str(list(e.path)), e.message)):
        path = "$" + "".join(
            f"[{key}]" if isinstance(key, int) else f".{key}" for key in error.path
        )
        issue(report, "errors", "SCHEMA", path, error.message)
    finish(report)
    return not report["errors"]
