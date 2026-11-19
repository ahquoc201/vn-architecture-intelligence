# Architectural benchmark protocol - v0.1.9 / Batch 007-A

All scenarios are SYNTHETIC. Dimensions, room bounds, reservations, source authorization actors and automated expectations are test data, not real projects, recommended sizes, human reviews or expert architectural oracles.

| Scenario | Explicit synthetic scope | Observed automated result |
| --- | --- | --- |
| A: narrow townhouse | 4 x 20 m lot, 4 x 12 m footprint, two floors, stairwell/circulation reservations, living/kitchen/laundry, two bedrooms and prayer space, hard public adjacency and soft bedroom/prayer adjacency, daylight/ventilation/skylight requests | GENERATED, 3 candidates; replay VERIFIED. Drafting INCOMPLETE pending actual selection/review, openings, paths and stair links. |
| B: medium townhouse | 5 x 18 m lot, 5 x 12 m footprint, two floors, public/private/service zoning, multiple bedrooms, explicit circulation/stairwell reservations and hard/soft relationships | GENERATED, 3 candidates; replay VERIFIED. The same review/information gaps remain. |
| C: wider property | 8 x 15 m lot, 8 x 10 m footprint, one floor, multiple functional zones, alternative arrangement request, hard adjacency/privacy separation and soft adjacency | UNSUPPORTED, no candidate: mandatory qualitative separation has no executable metric in the current solver. The requirement is retained. |

Floor elevations and all reviewers in fixtures are synthetic. Bounded envelopes are not cadastral surveys or certified usable areas. Daylight/ventilation requests are retained, never claimed as simulated satisfaction. Stairwell reservations are not stairs. Solver diversity counts distinct layouts, not label permutations.

A search-exhausted fixture keeps A's physical requirements with an explicit one-operation budget. STEP_LIMIT/SEARCH_EXHAUSTED proves only that no candidate was found in that budget, not infeasibility. No unsupported/exhausted result is presented as an architectural failure oracle.

## Reproduce and measure

```powershell
vnai design benchmark run examples/batch007a/benchmark/benchmark-a.json
vnai design benchmark run examples/batch007a/benchmark/benchmark-b.json
vnai design benchmark run examples/batch007a/benchmark/benchmark-c.json
vnai design benchmark run examples/batch007a/benchmark/search-exhausted.json
python scripts/run_architectural_benchmarks.py --out outputs/benchmarks-v0.1.9-review-1
```

The runner uses actual generation specifications, explicit provenance, independent replay, architectural review/evaluation and readiness policy. It never invents selection, reviewer, approval, doors, paths or stair links. human_review_status=PENDING, expert_oracle_status=NOT_ESTABLISHED, feedback=NOT_COLLECTED.

Deterministic outcomes record generation status/count/search effort, replay applicability/coverage, known hard violations, missing dependencies, spatial status, room-level circulation evidence, readiness and feedback status. Missing evidence is not a zero quality score. Passing-test counts are not architectural quality.

The separate script measures perf_counter runtime and saves timing-observations.json outside deterministic reports/goldens. Runtime never controls search termination or acceptance. Use a new output directory each run; preserve input/result digests and Python/dependency versions for shared observations. No runtime target is invented.

## Distinguish four levels of evidence

1. Synthetic expected result: authored software expectation, such as a deliberate area failure.
2. Automated verification result: engine output against exact content.
3. Human-reviewed result: comments actually supplied by an identified human for exact candidate/design/source digests.
4. Expert-reviewed oracle: curated versioned expectation reviewed by a qualified architect for defined scope, including positive/negative/edge cases and unresolved dissent.

No level automatically becomes the next. AI commentary is not human review. Role/digest declarations do not authenticate identity or qualifications. This batch supplies protocol/template; expert review is pending.

## Actual human review workflow

1. Preserve exact specification, candidate/design/provenance digests, engine version and replay/architectural/evaluation/readiness reports. Select explicitly using the existing review contract; the benchmark runner never selects.
2. Supply actual available drawings/measurements. Ask the architect to review unmodeled privacy, proportions, daylight/ventilation and stairs; do not invent missing drawings/data.
3. Use ARCHITECTURAL_BENCHMARK_REVIEW_TEMPLATE.md. Leave identity/date/credentials/comments unfilled until supplied by a real human. Separate defects, missing evidence and optional preferences.
4. Record real feedback with exact digests, affected IDs, category, requested change/rationale and blocking state. Never convert an informal comment into approval or automatically resolved feedback.
5. Preserve the parent, supply an external child revision, explicitly confirm requirement baseline changes and independently replay current constraints/source lineage.
6. Obtain architect resolution bound to the child for blocking feedback, plus separate fresh review/approval where required. Recompute evidence/readiness; parent approval never transfers.
7. After actual expert review, propose a versioned oracle package with scope, exact digests, reviewed expectations and negative/edge fixtures, attribution/consent and unresolved issues. Keep customer drawings, personal information, commercial standard PDFs and copyrighted books outside the repo.
8. Keep mandatory legal/safety findings visible and advisory. Never alter geometry to conceal them. Standards/Feng Shui need their own source/expert/test gates; CAD operations require later explicit authorization.

## Outstanding expert work

Rectangles do not prove privacy, useful proportions, daylight/ventilation, stair usability, accessibility/egress, wall/door constructability, structure or MEP. All three expert reviews and architectural-quality oracles remain pending. C requires an architect-defined measurable separation requirement and supported method; no AI-generated privacy distance or code threshold is supplied.
