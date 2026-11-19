"""Measure synthetic benchmarks; nondeterministic timing never enters core reports."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from vnai import __version__
from vnai.architectural_benchmark import run_benchmark
from vnai.contracts import canonical_digest, load_json
from vnai.design_reports import workflow_markdown


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", type=Path, required=True, help="New output directory; never overwrite"
    )
    args = parser.parse_args()
    paths = sorted(
        (Path(__file__).resolve().parents[1] / "examples/batch007a/benchmark").glob(
            "benchmark-*.json"
        )
    )
    args.out.mkdir(parents=True, exist_ok=False)
    timings = []
    for index, path in enumerate(paths, 1):
        value = load_json(path)
        start = perf_counter()
        report = run_benchmark(value)
        elapsed = perf_counter() - start
        stem = f"benchmark-{index}"
        (args.out / (stem + ".json")).write_text(
            json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (args.out / (stem + ".md")).write_text(workflow_markdown(report), encoding="utf-8")
        timing = {
            "benchmark_id": value["benchmark_id"],
            "engine_version": __version__,
            "observed_runtime_seconds": elapsed,
            "specification_digest": canonical_digest(value),
            "deterministic_report_digest": canonical_digest(report),
            "generation_status": report["generation"]["status"],
            "candidate_count": len(report["candidates"]),
            "expert_review": "PENDING",
            "runtime_is_acceptance_threshold": False,
        }
        timings.append(timing)
        print(json.dumps(timing))
    (args.out / "timing-observations.json").write_text(
        json.dumps(timings, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
