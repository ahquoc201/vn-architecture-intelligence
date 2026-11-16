# R1 evidence contract: source → research insight → agent suggestion

This is a **research and design-advisory** contract, not a feng shui rules engine or legal compliance checker.

## What is permitted

- Cite a source at *article section*, *book edition/page* or *official public scope* granularity.
- Derive a qualitative **design conversation starter**, explicitly attributed to the source.
- Return multiple options, explaining household preferences and site-specific limitations.
- Mark missing facts as `NEEDS_DATA` or an unreviewed claim as `NEEDS_SOURCE_REVIEW`.

## What is prohibited

- Encode an unreviewed Bát Trạch/Dương Trạch calculation, Kua chart, compass boundary or auspicious-number rule.
- Assert that a cultural design preference predicts objectively better health, prosperity, or safety.
- Equate *traditional khí* with measurable airflow or climatic comfort without independent physical evidence.
- Infer TCVN/QCVN numerical limits from the public catalog scope, or label a design COMPLIANT.
- Write to production DWG using only an observation in `knowledge/insights.yaml`.

## Schema gates

`knowledge/insights.yaml` contains attributed, non-executable observations. Every entry requires:

1. `source_ids` mapping to `sources/bibliography.yaml`.
2. `source_locator` identifying the reviewed public section or legal scope; do not fabricate a book page.
3. One `conclusion_type`: observed cultural case, authors' recommendation, official scope.
4. `applicability` and `limitations` that prevent overgeneralization.
5. `expert_approved: false` and `executable: false` in R1.
6. `allowed_use: advisory_only` or `reference_only`.

The validator checks **data integrity and review gates**, not the truth of the external work. Promotion to an executable domain rule requires a later versioned rules schema, expert review, positive/negative/missing-data/edge tests, and traceable approval.

## Example for an AI agent

When a household asks for a worship room, the agent may suggest the *option* of a more private area, citing `VNAI-OBS-003`. It must not insist every Vietnamese household needs one, and must treat smoke/fire/ventilation as independent technical considerations (`VNAI-OBS-004`).
