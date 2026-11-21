# Claude Code workflow integration (engineering reference)

Architect-facing guide: [ARCHITECT_QUICKSTART.md](ARCHITECT_QUICKSTART.md).

## Roles

- **Claude Code** — one user-facing agent: interprets Vietnamese requests, fills existing contracts,
  chooses `vnai` steps, explains results, asks for human decisions. No other autonomous agents.
- **VNAI Python** — deterministic geometry, validation, evaluation, drafting and DXF tools.
- **Architect** — decision maker; the only source of approval statements.

## Skill installation (`vnai-skill-install-v1`)

Canonical skills live only in `skills/<name>/` (also bundled into the wheel as `vnai/_data/skills`).
`vnai skills install [--dest DIR]` copies them into `DIR/.claude/skills/<name>/` and writes
`.vnai-installed.json` (per-file SHA-256 + skill digest). `vnai skills check` reports each skill as:

| State | Meaning | `install` action |
|---|---|---|
| CURRENT | copy matches canonical digest | none |
| MISSING | not installed | install |
| STALE | canonical changed since install | replace managed copy |
| MODIFIED | installed copy hand-edited | refuse unless `--force` |
| UNMANAGED | same-name folder without marker | refuse unless `--force` |

Exit: 0 CURRENT/INSTALLED, 3 NEEDS_ACTION, 1 INVALID (frontmatter `name` ≠ folder, missing
`description`, description > 1024 chars, broken relative link). Plain copies work on Windows
(PowerShell/Git Bash) and WSL2 without symlink privileges; `.claude/skills/` is git-ignored.
Claude Code live-reloads skill folders (`/reload-skills` if needed).

`vn-house-design` uses progressive disclosure: `SKILL.md` (always loaded on activation) plus
`reference/intake.md`, `reference/stages.md`, `reference/status-codes.md` (read per stage).

## Project workspace (`vnai-workflow-project-v1`)

```bash
vnai project init projects/<name> --name <name>
vnai project import <dir> <file> --folder brief|zoning|candidates|reviews|drafting|exports|manifests
vnai project step <dir> <step> <input> [--floor F1] [--view plan] [--mode refine] [--candidates 3] [--dxf X] [--units mm]
vnai project decide <dir> --kind <kind> --target <artifact> --statement "<words>" --by "<name/role>" [--synthetic]
vnai project status <dir> [--markdown]
```

- `project.json` is an append-only event ledger (atomic rewrite): `import`, `run`, `decision`.
- Each `run` calls the existing CLI in-process with **new** `-vNNN` output paths, records the argv,
  input/output SHA-256, stdout (`manifests/runs/RUN-NNN-<step>.stdout.json`), exit code, category,
  `primary_status` and Vietnamese meaning. Engines are not reimplemented.
- Steps: `brief`, `brief-report`, `program`, `zoning`, `geometry`, `floorplan`, `candidate-review`,
  `openings`, `opening-draft`, `circulation`, `stairs`, `stair-draft`, `architectural-review`,
  `integrated`, `integrated-preview`, `evaluate`, `compare`, `replay`, `revision`, `readiness`,
  `drafting`, `preview`, `export`, `audit`, `verify`.
- Exit categories: 0 OK, 1 INVALID_OR_FAILED, 2 INPUT_OR_IO_ERROR, 3 INCOMPLETE, 4 CONFLICT,
  5 UNSUPPORTED, 6 SEARCH_EXHAUSTED, 70 ENGINE_CRASH. Workflow refusals print `REFUSED`, exit 3,
  and leave the ledger unchanged.
- `status` re-hashes every recorded file (`INTACT` / `STALE` exit 4), marks decisions
  `CURRENT`, `STALE_TARGET_CHANGED`, `STALE_TARGET_MISSING` or `SUPERSEDED_BY_NEWER_RUN`, and lists
  next actions. This is the resume mechanism; chat memory is not.

## Decisions and permissions

Kinds: `requirement_confirmation`, `candidate_selection`, `architect_feedback`, `architect_review`,
`architect_approval`, `export_authorization`. `cad_modification` is refused. Decisions are ledger
records of a human statement bound to an artifact digest; they never alter engine artifacts, which keep
`architect_approval: NOT_GRANTED` and `cad_writes_permitted: false`.

`export` requires the input Drawing IR to be inside the project and a current
`export_authorization` whose `target_sha256` equals the IR digest (scope
`NEW_DXF_FILES_ONLY_NO_OVERWRITE`). `--overwrite` is never passed; each export gets a new version.

## Security

User/project data is never interpolated into a shell: steps map to fixed argv lists; floor/view IDs
must match `[A-Za-z0-9_.:-]{1,64}`. Outputs are confined to the project folder. Imported briefs,
books and CAD metadata are untrusted data. No MCP server or plugin is installed by this workflow.

## Demonstration and evaluation

- `python scripts/demo_synthetic_townhouse.py --dir <new-dir>` — scripted, deterministic replay of the
  workflow on the synthetic two-storey 4 × 20 m benchmark (brief INCOMPLETE gate, integrated refine
  48/48 supported checks, previews, refused unauthorized export, authorized F1/F2 DXF export, audit,
  round-trip, handoff). All decisions are marked synthetic; no approval is recorded.
- `evals/vn-house-design/cases.json` — behavioural cases for a **live** Claude Code session.
  `python scripts/run_skill_evals.py --out <dir>` collects transcripts in plan (read-only) mode for
  manual grading. Pytest only checks the case file structure; it is not an LLM evaluation.

## Not in scope

AutoCAD MCP integration, DWG modification, structural/MEP design, code certification, new
geometry engines, new LLM backends or multi-agent frameworks.
