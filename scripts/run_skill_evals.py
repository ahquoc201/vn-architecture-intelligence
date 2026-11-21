"""Collect live Claude Code transcripts for the vn-house-design behavioural eval set.

Run from the repository root after `vnai skills install`:
    python scripts/run_skill_evals.py --out outputs/skill-evals/<date> [--case E01-initial-4x20]

Requires the `claude` CLI. Each case runs `claude -p` in plan permission mode (read-only:
no file edits, no commands) and stores the raw transcript plus an ungraded rubric. Grading is
manual; this script never scores or fabricates results. Exit 3 when the CLI is unavailable.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--case", action="append", help="Run only these case IDs")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    cases = json.loads((ROOT / "evals/vn-house-design/cases.json").read_text("utf-8"))["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] in set(args.case)]
    claude = shutil.which("claude")
    if claude is None:
        print(json.dumps({"status": "NOT_RUN", "reason": "claude CLI not found on PATH"}))
        return 3
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    for case in cases:
        result = subprocess.run(
            [claude, "-p", case["prompt_vi"], "--permission-mode", "plan",
             "--output-format", "json"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=args.timeout,
        )
        (out / f"{case['id']}.transcript.json").write_text(result.stdout, encoding="utf-8")
        rubric = {**case, "exit_code": result.returncode, "stderr": result.stderr[-2000:],
                  "grade": "UNGRADED", "grader": None}
        (out / f"{case['id']}.rubric.json").write_text(
            json.dumps(rubric, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{case['id']}: exit {result.returncode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
