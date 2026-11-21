# Controlled AutoCAD MCP integration (v0.2.1)

Status: **read-only MCP + headless DXF; copy-edit on new DXF copies only. Live AutoCAD mutation is
UNSUPPORTED. Live acceptance: PENDING_LIVE_ACCEPTANCE.**

## 1. Architecture

```
Claude Code (one agent) → skill vn-house-design (reference/autocad-mcp.md)
  → vnai project workflow (ledger, digests, decisions)
  → vnai cad bridge  ──► MCP stdio client + read allowlist ──► third-party AutoCAD MCP server (READ_ONLY)
                     └─► headless DXF backend (ezdxf, read-only)
  → vnai cad edit    ──► proposal → single-use authorization → NEW DXF copy → audit + read-back + compare
```

VNAI stays authoritative for requirements, revisions, Drawing IR, digests, decisions and export
manifests. The MCP server is only a window onto actual CAD documents; its output is untrusted data.

| Module | Role |
|---|---|
| `src/vnai/cad_bridge.py` | profile validation, MCP stdio client, discovery, read allowlist, headless inspection, comparison |
| `src/vnai/cad_edit.py` | change proposals, authorization check, isolated copy edit, read-back |
| `src/vnai/project_workflow.py` | decision kind `cad_copy_edit_authorization`; status lists `cad_copy_edits` |
| `tests/mock_autocad_mcp.py` | mock stdio server (readonly / leaky / crash / garbage / rpc_error) |

## 2. Provider assessment — `U-C4N/Autocad-MCP` (`autocad-mcp-pro`)

Facts as read on 2026-11-21 from the repository README, `pyproject.toml` and `server.py` (partial).
Not installed or executed in this batch.

| Item | Finding |
|---|---|
| Package / pin | `autocad-mcp-pro` **1.8.0**, tag v1.8.0 (commit `6f6a538`, 2026-11-06); MIT |
| Python | `>=3.11` (classifiers 3.11–3.13; 3.14 not declared) |
| Transport | stdio default (`autocad-mcp`); optional HTTP, loopback unless remote + token enabled |
| Backends | headless `ezdxf`; Windows COM (`[com]` extra, pywin32) tested only on AutoCAD 2026; DWG headless needs ODA converter/accoreconsole |
| Tools | ~257 registered (search mode shows 6). Full list **not verified**; includes writers (`entity_create_*`, `entity_move`, `drawing_save`, `cad_batch`, `entity_delete_many`) |
| Command execution | `system_run_command` (verb **denylist**, disabled by `DANGEROUS_COMMANDS_ENABLED`), `system_run_lisp` (`LISP_POLICY=read` default). README: "a guardrail, not a security boundary" |
| Server-side controls | `READ_ONLY=true`, `TOOL_ALLOWLIST` / `TOOL_DENYLIST` (refused tools not advertised), `ALLOWED_PATHS` (empty by default) |

**Decision.** Suitable only as a **read-only** provider launched with `READ_ONLY=true`, a tight
`TOOL_ALLOWLIST`, a denylist for both execution tools and `ALLOWED_PATHS`. VNAI adds its own layer: it
refuses every call unless the server advertises *only* allowlisted tools
(`VERIFIED_BY_TOOL_ADVERTISEMENT`). Live editing through this server is **not** enabled: its write tools
target the active document and its command guard is a denylist, so isolation of a copy cannot be
guaranteed. Editing is implemented headlessly by VNAI on new DXF copies. No fork was needed.

Python 3.14 compatibility, the exact read tool names (`drawing_info`, `entity_list` are assumed) and
their result shapes are **unverified** until a live `vnai cad doctor --probe` on a Windows workstation.

## 3. Windows setup (architect workstation)

1. Install VNAI (`docs/ARCHITECT_QUICKSTART.md`) and `uv` (`winget install astral-sh.uv`).
2. Review the pinned package yourself before use; never install `@latest` or unreviewed servers.
3. Copy `examples/cad-mcp/autocad-mcp-pro.profile.example.json` to e.g. `cad-mcp.local.json`
   (git-ignored), set the environment variable `VNAI_CAD_ALLOWED_PATHS` to your project folder.
4. Run `vnai cad doctor --profile cad-mcp.local.json --probe`. Adjust `read_tools`/`TOOL_ALLOWLIST`
   to the actual read tool names reported under `tools` — only tools that do not modify anything.
   If `read_only_enforcement` is `NOT_ENFORCED`, stop: the server exposes more than the allowlist.
5. Optional, for Claude Code to call the server directly (local scope, not committed):

   ```powershell
   claude mcp add --scope local --env READ_ONLY=true --env TOOL_ALLOWLIST=drawing_info,entity_list --env "TOOL_DENYLIST=system_run_command,system_run_lisp" autocad -- uvx --from "autocad-mcp-pro[com]==1.8.0" autocad-mcp
   ```

   and deny the execution tools in `.claude/settings.local.json`:
   `{"permissions": {"deny": ["mcp__autocad__system_run_command", "mcp__autocad__system_run_lisp"]}}`.
   Claude Code permission rules are enforced by the client; the server flags are the second layer.
   Prefer `vnai cad mcp-read`, which refuses anything outside the allowlist before it reaches the server.

Never commit `.mcp.json`, `*.local.json`, tokens or personal paths (`.gitignore` covers them).

## 4. Contracts and statuses

* `vnai-cad-capabilities-v1` — `claude_cli`, `headless_dxf_backend`, `mcp_server_configured`,
  `mcp_server_connected`, `read_only_enforcement`, `server_version_check`,
  `desktop_autocad_connected` (`REPORTED_BY_SERVER` only for a COM backend), `live_document_inspected`.
* `vnai-cad-inspection-v1` — units, layers, layouts, counts, extents, one page (≤500) of entities,
  `source_unchanged` (SHA-256 before/after).
* `vnai-cad-comparison-v1` — wraps `dxf-roundtrip-verification-v1`; identity by VNAI XDATA ids and
  `source_geometry_id`, never AutoCAD handles. Statuses: `VERIFIED_MATCH`, `VERIFIED_MISMATCH`,
  `MISSING_ENTITY`, `UNKNOWN` (unlinked entities), `NOT_EVALUATED` (visual), `UNSUPPORTED` (DWG
  headless), `STALE` (digest / geometry revision), `INCOMPLETE` (unknown units, missing view).
* `vnai-cad-change-proposal-v1` — source path + SHA-256, VNAI revision, target copy, operations
  (`translate_source_geometry`, `replace_text`), affected ids, bbox before/after, stale dimensions,
  verification plan, rollback, risks. `edit_permission: NOT_GRANTED`.
* `vnai-cad-copy-edit-v1` — `APPLIED_VERIFIED`, `APPLIED_VERIFICATION_FAILED`, `FAILED_NO_OUTPUT`,
  `INTERRUPTED_UNCERTAIN`; audit, read-back (changed ids == proposed ids), `source_unchanged`,
  comparison with VNAI, `copy_edit_permission` scoped to one copy. `cad_writes_permitted: false`.

Exit codes: 0 OK/match, 1 invalid, 2 not found, 3 incomplete/refused, 4 mismatch/stale/not enforced/
connection, 5 unsupported.

## 5. Safeguards (enforced in code, tested)

- Calls to non-allowlisted or non-advertised tools are refused before reaching the server; a server
  advertising extra tools blocks all calls. Profiles with write-looking tool names or shell strings
  are rejected. Proxy/meta tools (`call_tool`, tool search, batch, invoke, eval, exec, script…) can
  never be allowlisted, even with `read_tool_overrides`. Env values are never echoed.
- Copy target: `<project>/exports` must not be a symlink/junction/alias (resolved path must equal
  the lexical one); target is exactly `exports/<name>.dxf`; temp files are created exclusively
  (`mkstemp`); the edit runs on a snapshot of the exact bytes whose SHA-256 was just rechecked.
- Edits require an unused `cad_copy_edit_authorization` whose digest equals the proposal file; any
  edit of the proposal invalidates it. `export_authorization`, selection and approval do not unlock it.
- Before writing: source SHA-256, Drawing IR SHA-256, operation allowlist and target path
  (`<project>/exports/*.dxf`, not existing, not the source) are re-checked. Write = temp file + hard
  link (fails instead of overwriting). Failures are recorded, never retried; an unfinished attempt
  blocks re-execution as `INTERRUPTED_UNCERTAIN`.
- Authorization ≠ authentication: the ledger records who *said* they authorize; it proves nothing
  about identity.

## 6. Live acceptance checklist (PENDING_LIVE_ACCEPTANCE)

On a Windows workstation with AutoCAD 2026, Claude Code and a reviewed `autocad-mcp-pro==1.8.0`:

1. `vnai cad doctor --profile … --probe` → `CONNECTED_READ_ONLY`, `VERIFIED_BY_TOOL_ADVERTISEMENT`,
   `desktop_autocad_connected: REPORTED_BY_SERVER`, `live_document_inspected: INSPECTED`. Save output.
2. Scenario A — "Đọc bản vẽ tầng 1 đang mở, cho tôi biết các layer và kích thước tổng thể." Confirm
   the drawing's modified flag/undo history is unchanged in AutoCAD.
3. Scenario B — save the drawing as DXF; "Đối chiếu bản vẽ tầng 1 với phương án VNAI hiện tại."
   Check per-element statuses against what you see.
4. Scenario C — "Tôi muốn chuyển cửa D01 sang vị trí khác. Hãy đề xuất phương án trước." Confirm no
   file in the project or AutoCAD changed.
5. Scenario D — authorize in your own words; open the new `*-cadedit-vNNN.dxf` in AutoCAD; verify the
   moved door, untouched original, stale dimensions as listed, fonts/hatches/dimension rendering.
6. Try `system_run_command` via Claude: it must be refused/denied. Record transcripts with
   `python scripts/run_skill_evals.py --case E12-cad-inspect` etc. (cases E12–E15).

## 7. Known limits

DWG headless, MCP-side editing, associative dimension regeneration, collision checks of edited
copies, paper-space edits, xrefs/images and AutoCAD visual verification are not supported or not
evaluated. Mock tests prove the enforcement layer, not compatibility with the real server.
