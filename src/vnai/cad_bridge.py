"""Controlled, read-only bridge between VNAI and real CAD documents.

Two backends:

* **Headless DXF** (``ezdxf``, in-process): opens files read-only and never saves them.
* **MCP** (a third-party AutoCAD MCP server over stdio JSON-RPC): VNAI launches the server
  from a local profile, discovers its tools at runtime and only forwards calls to tools that
  are (a) on the profile's read allowlist and (b) advertised by the server. If the server
  advertises any tool outside that allowlist, server-side read-only enforcement is treated as
  NOT_ENFORCED and every call is refused.

MCP responses are untrusted data. Nothing here writes CAD files; copy editing lives in
``vnai.cad_edit`` and only targets new headless DXF copies.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import shutil
import subprocess
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from vnai import __version__
from vnai.dxf_manifest import INSUNITS_TO_UNIT, compute_file_sha256, decode_doc_meta, decode_ir_xdata

PROFILE_CONTRACT = "vnai-cad-mcp-profile-v1"
DISCOVERY_CONTRACT = "vnai-cad-capabilities-v1"
INSPECTION_CONTRACT = "vnai-cad-inspection-v1"
COMPARISON_CONTRACT = "vnai-cad-comparison-v1"
MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_PAGE = 500
MAX_MCP_RESULT_CHARS = 200_000
WRITE_HINT = re.compile(
    r"(create|delete|erase|move|copy|rotate|scale|save|export|write|set|edit|modify|update|"
    r"insert|purge|run|exec|command|lisp|script|batch|plot|import|open|close|undo|redo)",
    re.IGNORECASE,
)
# Meta/proxy tools (generic dispatchers, tool search/call, batches, evaluators) could forward to
# arbitrary server tools and bypass the read allowlist; they are refused and cannot be overridden.
PROXY_HINT = re.compile(
    r"(call|invoke|dispatch|proxy|tool|batch|exec|run|command|lisp|script|eval|macro|pipeline)",
    re.IGNORECASE,
)
_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")
EXIT_CODES = {
    "VERIFIED_MATCH": 0,
    "INSPECTED": 0,
    "READY": 0,
    "CONNECTED_READ_ONLY": 0,
    "OK": 0,
    "INVALID": 1,
    "NOT_FOUND": 2,
    "INCOMPLETE": 3,
    "NOT_CONFIGURED": 3,
    "REFUSED": 3,
    "VERIFIED_MISMATCH": 4,
    "STALE": 4,
    "READ_ONLY_NOT_ENFORCED": 4,
    "INCOMPATIBLE_VERSION": 4,
    "CONNECTION_FAILED": 4,
    "MCP_ERROR": 4,
    "UNSUPPORTED": 5,
}
GOVERNANCE = {
    "cad_writes_permitted": False,
    "architect_approval": "NOT_GRANTED",
    "manual_autocad_acceptance_status": "PENDING_HUMAN_AUTOCAD_VERIFICATION",
}


class CadBridgeError(Exception):
    """Refusal or failure with a machine-readable status."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- MCP profile/client


def load_profile(path: Path) -> dict:
    """Load and validate a local MCP launch profile (kept out of git by the user)."""
    try:
        profile = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CadBridgeError("NOT_CONFIGURED", f"Cannot read MCP profile: {exc}") from exc
    errors = []
    if profile.get("contract") != PROFILE_CONTRACT:
        errors.append(f"contract must be {PROFILE_CONTRACT}")
    command = profile.get("command")
    if not (isinstance(command, list) and command and all(isinstance(c, str) for c in command)):
        errors.append("command must be a non-empty list of strings (no shell string)")
    tools = profile.get("read_tools")
    if not (isinstance(tools, list) and tools and all(isinstance(t, str) for t in tools)):
        errors.append("read_tools must list the allowlisted read-only tool names")
    elif any(WRITE_HINT.search(t) and t not in profile.get("read_tool_overrides", []) for t in tools):
        errors.append("read_tools contains a tool name that looks like a write/exec tool")
    if isinstance(tools, list) and any(isinstance(t, str) and PROXY_HINT.search(t) for t in tools):
        errors.append("read_tools contains a proxy/dispatch/batch/exec tool (not overridable)")
    if not isinstance(profile.get("env", {}), dict):
        errors.append("env must be an object")
    if errors:
        raise CadBridgeError("INVALID", "; ".join(errors))
    return profile


def _expand_env(value: str) -> str:
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)


class McpStdioClient:
    """Minimal MCP client: newline-delimited JSON-RPC 2.0 over a child process's stdio."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None, timeout: float = 20.0):
        self.timeout = timeout
        self._id = 0
        full_env = dict(os.environ)
        full_env.update({k: _expand_env(str(v)) for k, v in (env or {}).items()})
        try:
            self.proc = subprocess.Popen(  # noqa: S603 - argv list, never a shell string
                [_expand_env(c) for c in command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise CadBridgeError("CONNECTION_FAILED", f"Cannot start MCP server: {exc}") from exc
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self._send(msg)
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise CadBridgeError("CONNECTION_FAILED", f"MCP timeout on {method}") from exc
            if line is None:
                raise CadBridgeError("CONNECTION_FAILED", f"MCP server exited during {method}")
            try:
                reply = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CadBridgeError("MCP_ERROR", "MCP server wrote non-JSON to stdout") from exc
            if not isinstance(reply, dict) or reply.get("id") != self._id:
                continue  # notifications/log messages are ignored
            if "error" in reply:
                err = reply["error"] if isinstance(reply["error"], dict) else {}
                raise CadBridgeError("MCP_ERROR", f"{method}: {str(err.get('message'))[:300]}")
            return reply.get("result")

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _send(self, msg: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise CadBridgeError("CONNECTION_FAILED", "MCP server stdin closed") from exc

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - best effort shutdown
            self.proc.kill()


class ControlledMcpSession:
    """Read-only adapter: VNAI-side allowlist + verified server-side tool restriction."""

    def __init__(self, profile: dict, timeout: float = 20.0):
        self.profile = profile
        self.client = McpStdioClient(profile["command"], profile.get("env"), timeout)
        self.allow = set(profile["read_tools"])
        self.server_info: dict = {}
        self.tools: list[dict] = []
        self.enforcement = "NOT_EVALUATED"

    def __enter__(self) -> ControlledMcpSession:
        try:
            init = self.client.request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "vnai-cad-bridge", "version": __version__},
                },
            ) or {}
            self.client.notify("notifications/initialized")
            self.server_info = {
                "name": str((init.get("serverInfo") or {}).get("name", ""))[:120],
                "version": str((init.get("serverInfo") or {}).get("version", ""))[:60],
                "protocol_version": str(init.get("protocolVersion", ""))[:40],
            }
            listed = self.client.request("tools/list") or {}
            self.tools = [
                {"name": str(t.get("name"))[:120],
                 "read_only_hint": bool((t.get("annotations") or {}).get("readOnlyHint", False))}
                for t in listed.get("tools", []) if isinstance(t, dict)
            ]
        except CadBridgeError:
            self.client.close()
            raise
        extra = sorted(t["name"] for t in self.tools if t["name"] not in self.allow)
        self.enforcement = "NOT_ENFORCED" if extra else "VERIFIED_BY_TOOL_ADVERTISEMENT"
        self.unexpected_tools = extra
        return self

    def __exit__(self, *exc: object) -> None:
        self.client.close()

    def version_status(self) -> str:
        pinned = self.profile.get("pinned_version")
        if not pinned:
            return "NOT_PINNED"
        return "MATCH" if self.server_info.get("version") == pinned else "INCOMPATIBLE_VERSION"

    def call_read(self, tool: str, arguments: dict | None = None) -> dict:
        """Forward one allowlisted read call; refuse everything else before it reaches the server."""
        advertised = {t["name"] for t in self.tools}
        if self.enforcement != "VERIFIED_BY_TOOL_ADVERTISEMENT":
            raise CadBridgeError(
                "READ_ONLY_NOT_ENFORCED",
                "Server advertises tools outside the read allowlist; all calls refused: "
                + ", ".join(self.unexpected_tools[:20]),
            )
        if self.version_status() == "INCOMPATIBLE_VERSION":
            raise CadBridgeError("INCOMPATIBLE_VERSION", f"Server version {self.server_info}")
        if tool not in self.allow or tool not in advertised or PROXY_HINT.search(tool):
            raise CadBridgeError("REFUSED", f"Tool '{tool}' is not an advertised allowlisted read tool")
        result = self.client.request("tools/call", {"name": tool, "arguments": arguments or {}}) or {}
        text = "".join(
            c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)
        )
        truncated = len(text) > MAX_MCP_RESULT_CHARS
        payload: Any = text[:MAX_MCP_RESULT_CHARS]
        if not truncated:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                pass
        return {
            "tool": tool,
            "is_error": bool(result.get("isError")),
            "truncated": truncated,
            "trust": "UNTRUSTED_THIRD_PARTY_DATA",
            "result": payload,
        }


def discover(profile_path: Path | None, probe: bool = False, timeout: float = 20.0) -> dict:
    """Runtime capability discovery with separate statuses for each layer."""
    report: dict[str, Any] = {
        "contract": DISCOVERY_CONTRACT,
        "engine_version": __version__,
        "claude_cli": "AVAILABLE" if shutil.which("claude") else "NOT_FOUND",
        "headless_dxf_backend": "NOT_AVAILABLE",
        "mcp_server_configured": "NOT_CONFIGURED",
        "mcp_server_connected": "NOT_ATTEMPTED",
        "read_only_enforcement": "NOT_EVALUATED",
        "server_version_check": "NOT_EVALUATED",
        "desktop_autocad_connected": "NOT_VERIFIED",
        "live_document_inspected": "NOT_ATTEMPTED",
        "server": None,
        "transport": None,
        "tools": [],
        "unexpected_tools": [],
        "live_document": None,
        "capabilities": {
            "read_only_inspection": "NOT_AVAILABLE",
            "live_cad_mutation": "UNSUPPORTED",
            "headless_copy_edit": "NOT_AVAILABLE",
        },
        "limitations": [
            "Live AutoCAD editing through MCP is not supported: VNAI never forwards write tools.",
            "Third-party MCP results are untrusted data and are bounded/truncated.",
            "A configured or mock connection is not a verified AutoCAD session.",
        ],
        "errors": [],
        **GOVERNANCE,
    }
    try:
        import ezdxf

        report["headless_dxf_backend"] = f"AVAILABLE (ezdxf {ezdxf.__version__})"
        report["capabilities"]["read_only_inspection"] = "HEADLESS_DXF"
        report["capabilities"]["headless_copy_edit"] = "SUPPORTED_NEW_COPY_ONLY"
    except ImportError:
        report["errors"].append("ezdxf missing: pip install -e .[cad]")
    if profile_path is None:
        report["status"] = "READY" if report["errors"] == [] else "INCOMPLETE"
        return report
    try:
        profile = load_profile(profile_path)
    except CadBridgeError as exc:
        report["mcp_server_configured"] = exc.status
        report["errors"].append(str(exc))
        report["status"] = exc.status
        return report
    report["mcp_server_configured"] = "CONFIGURED"
    report["transport"] = "stdio"
    report["profile"] = {
        "server_name": profile.get("server_name"),
        "package": profile.get("package"),
        "pinned_version": profile.get("pinned_version"),
        "read_tools": sorted(profile["read_tools"]),
        "env_keys": sorted(profile.get("env", {})),  # values never echoed
    }
    try:
        with ControlledMcpSession(profile, timeout) as session:
            report["mcp_server_connected"] = "CONNECTED"
            report["server"] = session.server_info
            report["tools"] = session.tools
            report["unexpected_tools"] = session.unexpected_tools
            report["read_only_enforcement"] = session.enforcement
            report["server_version_check"] = session.version_status()
            identity = profile.get("identity_tool")
            if probe and identity:
                try:
                    res = session.call_read(identity, {})
                    data = res["result"] if isinstance(res["result"], dict) else {}
                    backend = str(data.get("backend", ""))[:40]
                    report["live_document"] = {
                        k: data.get(k) for k in ("backend", "autocad_version", "document")
                    }
                    report["live_document_inspected"] = "INSPECTED" if not res["is_error"] else "FAILED"
                    if backend in set(profile.get("desktop_backend_values", [])):
                        report["desktop_autocad_connected"] = "REPORTED_BY_SERVER"
                    else:
                        report["desktop_autocad_connected"] = f"NOT_DESKTOP (backend={backend or '?'})"
                except CadBridgeError as exc:
                    report["live_document_inspected"] = exc.status
                    report["errors"].append(str(exc))
    except CadBridgeError as exc:
        report["mcp_server_connected"] = exc.status
        report["errors"].append(str(exc))
    if report["read_only_enforcement"] == "VERIFIED_BY_TOOL_ADVERTISEMENT":
        report["capabilities"]["read_only_inspection"] = "MCP_AND_HEADLESS_DXF"
    if report["mcp_server_connected"] != "CONNECTED":
        report["status"] = "CONNECTION_FAILED"
    elif report["read_only_enforcement"] == "NOT_ENFORCED":
        report["status"] = "READ_ONLY_NOT_ENFORCED"
    elif report["server_version_check"] == "INCOMPATIBLE_VERSION":
        report["status"] = "INCOMPATIBLE_VERSION"
    else:
        report["status"] = "CONNECTED_READ_ONLY"
    return report


def mcp_read(profile_path: Path, tool: str, arguments: dict | None = None) -> dict:
    profile = load_profile(profile_path)
    with ControlledMcpSession(profile) as session:
        out = session.call_read(tool, arguments)
    return {"contract": INSPECTION_CONTRACT, "backend": "MCP", "status": "OK",
            "server": session.server_info, **out, **GOVERNANCE}


# --------------------------------------------------------------------------- headless inspection


def _open_dxf(path: Path):
    import ezdxf
    from ezdxf.lldxf.const import DXFError

    path = Path(path)
    if not path.is_file():
        raise CadBridgeError("NOT_FOUND", f"Drawing not found: {path}")
    if path.suffix.lower() != ".dxf":
        raise CadBridgeError(
            "UNSUPPORTED",
            "Headless backend reads DXF only; DWG needs a live AutoCAD MCP read or a DXF copy "
            "saved by the architect.",
        )
    try:
        return ezdxf.readfile(str(path))
    except (DXFError, OSError, UnicodeDecodeError) as exc:
        raise CadBridgeError("INVALID", f"Cannot read DXF: {exc}") from exc


def _r(value: float) -> float:
    return round(float(value), 6) if math.isfinite(float(value)) else float("nan")


def _pt(p: Any) -> list[float]:
    return [_r(p[0]), _r(p[1])]


def entity_record(e: Any) -> dict:
    """Bounded, JSON-safe description of one entity (handles are informational only)."""
    t = e.dxftype()
    rec: dict[str, Any] = {"type": t, "layer": e.dxf.get("layer", "0"),
                           "handle": e.dxf.get("handle")}
    x = decode_ir_xdata(e)
    if x:
        rec["vnai_id"] = x.get("id")
        rec["source_geometry_id"] = x.get("src")
    try:
        if t == "LINE":
            rec["start"], rec["end"] = _pt(e.dxf.start), _pt(e.dxf.end)
        elif t == "LWPOLYLINE":
            pts = [_pt(p) for p in e.get_points("xy")]
            rec["closed"], rec["vertex_count"], rec["points"] = bool(e.closed), len(pts), pts[:64]
        elif t in {"CIRCLE", "ARC"}:
            rec["center"], rec["radius"] = _pt(e.dxf.center), _r(e.dxf.radius)
            if t == "ARC":
                rec["start_angle"], rec["end_angle"] = _r(e.dxf.start_angle), _r(e.dxf.end_angle)
        elif t == "TEXT":
            rec["text"], rec["insert"] = e.dxf.text, _pt(e.dxf.insert)
        elif t == "MTEXT":
            rec["text"], rec["insert"] = e.plain_text(), _pt(e.dxf.insert)
        elif t == "DIMENSION":
            rec["dimension_text"] = e.dxf.get("text", "")
            rec["defpoint"], rec["defpoint2"] = _pt(e.dxf.defpoint), _pt(e.dxf.get("defpoint2", (0, 0)))
            rec["defpoint3"] = _pt(e.dxf.get("defpoint3", (0, 0)))
            try:
                rec["measurement"] = _r(e.get_measurement())
            except Exception:  # noqa: BLE001 - unsupported dimension kinds stay explicit
                rec["measurement"] = "UNSUPPORTED"
        elif t == "INSERT":
            rec["block"], rec["insert"] = e.dxf.name, _pt(e.dxf.insert)
            rec["attributes"] = {a.dxf.tag: a.dxf.text for a in e.attribs}
        elif t == "HATCH":
            rec["pattern"], rec["path_count"] = e.dxf.pattern_name, len(e.paths)
    except Exception as exc:  # noqa: BLE001
        rec["read_error"] = str(exc)[:200]
    return rec


def inspect_dxf(
    path: Path,
    *,
    layer: str | None = None,
    entity_type: str | None = None,
    space: str = "model",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Read-only summary + one bounded page of entities. Verifies the file is not modified."""
    path = Path(path)
    before = compute_file_sha256(path) if path.is_file() else None
    doc = _open_dxf(path)
    limit = max(0, min(int(limit), MAX_PAGE))
    insunits = int(doc.header.get("$INSUNITS", 0))
    msp = doc.modelspace()
    layouts = []
    for lay in doc.layouts:
        layouts.append({"name": lay.name, "is_model_space": lay.name == "Model",
                        "entity_count": len(lay),
                        "viewports": sum(1 for e in lay if e.dxftype() == "VIEWPORT")})
    container = msp if space == "model" else doc.layouts.get(space)
    entities = [
        e for e in container
        if (layer is None or e.dxf.get("layer") == layer)
        and (entity_type is None or e.dxftype() == entity_type.upper())
    ]
    try:
        from ezdxf import bbox

        ext = bbox.extents(msp, fast=True)
        extents = {"min": _pt(ext.extmin), "max": _pt(ext.extmax),
                   "width": _r(ext.size.x), "height": _r(ext.size.y)} if ext.has_data else None
    except Exception:  # noqa: BLE001
        extents = None
    after = compute_file_sha256(path)
    return {
        "contract": INSPECTION_CONTRACT,
        "engine_version": __version__,
        "backend": "HEADLESS_DXF",
        "status": "INSPECTED",
        "drawing": {
            "path": path.as_posix(),
            "file_sha256": before,
            "dxf_version": doc.dxfversion,
            "vnai_meta": decode_doc_meta(doc) or None,
        },
        "units": {"insunits": insunits, "unit": INSUNITS_TO_UNIT.get(insunits, "UNKNOWN")},
        "coordinate_system": {"ucs": "WCS assumed (headless)", "extents_model_space": extents},
        "layers": [
            {"name": la.dxf.name, "color": la.dxf.get("color"), "linetype": la.dxf.get("linetype"),
             "off": la.is_off(), "frozen": la.is_frozen(), "locked": la.is_locked()}
            for la in doc.layers
        ],
        "layouts": layouts,
        "entity_counts": dict(sorted(Counter(e.dxftype() for e in msp).items())),
        "block_definitions": sorted(
            b.name for b in doc.blocks if not b.name.startswith("*")
        ),
        "page": {
            "space": space, "layer": layer, "entity_type": entity_type, "offset": offset,
            "limit": limit, "total": len(entities),
            "entities": [entity_record(e) for e in entities[offset:offset + limit]],
        },
        "source_unchanged": before == after,
        "not_evaluated": ["AutoCAD visual rendering", "fonts on workstation", "xrefs/images"],
        **GOVERNANCE,
    }


# --------------------------------------------------------------------------- comparison


def _ir_view(ir: dict, view_id: str | None, floor_id: str | None) -> dict | None:
    for view in (ir.get("model_space") or {}).get("views", []):
        if (view_id and view.get("view_id") == view_id) or (
            not view_id and floor_id and view.get("floor_id") == floor_id
            and view.get("view_kind") == "floor_plan"
        ):
            return view
    return None


_SEVERITY = ["VERIFIED_MATCH", "UNKNOWN", "VERIFIED_MISMATCH", "MISSING_ENTITY"]


def compare_cad(
    ir: dict,
    dxf_path: Path,
    *,
    floor_id: str | None = None,
    view_id: str | None = None,
    expected_sha256: str | None = None,
) -> dict:
    """Compare an actual DXF with a VNAI Drawing IR via the existing handle-free verifier."""
    from vnai.dxf_roundtrip import verify_dxf_roundtrip

    dxf_path = Path(dxf_path)
    doc = _open_dxf(dxf_path)
    sha = compute_file_sha256(dxf_path)
    meta = decode_doc_meta(doc)
    insunits = int(doc.header.get("$INSUNITS", 0))
    report: dict[str, Any] = {
        "contract": COMPARISON_CONTRACT,
        "engine_version": __version__,
        "drawing": {"path": dxf_path.as_posix(), "file_sha256": sha},
        "vnai_revision": {"drawing_ir_digest": ir.get("drawing_ir_digest"),
                          "drawing_meta_ir_digest": meta.get("drawing_ir_digest")},
        "units": {"cad": INSUNITS_TO_UNIT.get(insunits, "UNKNOWN"),
                  "vnai": (ir.get("model_space") or {}).get("units")},
        "checks": {},
        "by_source_geometry": {},
        "unlinked_cad_entities": {},
        "visual_correctness": "NOT_EVALUATED",
        "autocad_handles_used_for_identity": False,
        **GOVERNANCE,
    }
    checks = report["checks"]
    checks["drawing_digest"] = (
        "NOT_EVALUATED" if expected_sha256 is None
        else "VERIFIED_MATCH" if expected_sha256 == sha else "STALE"
    )
    report["vnai_revision"]["drawing_meta_geometry_digest"] = meta.get("geom_dims_digest")
    if not meta.get("geom_dims_digest"):
        checks["ir_link"] = "UNKNOWN"  # drawing not produced by VNAI or metadata stripped
    elif meta["geom_dims_digest"] != ir.get("geometry_and_dimensions_digest"):
        checks["ir_link"] = "STALE"  # drawing came from another geometry/dimension revision
    elif meta.get("drawing_ir_digest") == ir.get("drawing_ir_digest"):
        checks["ir_link"] = "VERIFIED_MATCH"
    else:
        checks["ir_link"] = "GEOMETRY_MATCH_PRESENTATION_DIFFERS"
    view = _ir_view(ir, view_id, floor_id)
    if view is None:
        report["comparison_status"] = "INCOMPLETE"
        report["reason"] = "View/floor not found in the Drawing IR"
        return report
    report["view_id"] = view["view_id"]
    if report["units"]["cad"] == "UNKNOWN":
        checks["units"] = "UNKNOWN"
        report["comparison_status"] = "INCOMPLETE"
        report["reason"] = "Drawing units ($INSUNITS) unknown; ask the architect before comparing."
        return report
    checks["units"] = "VERIFIED_MATCH" if report["units"]["cad"] == report["units"]["vnai"] else (
        "CONVERTED"
    )
    rt = verify_dxf_roundtrip(ir, dxf_path, view_id=view["view_id"],
                              target_units=report["units"]["cad"])
    report["semantic_verification"] = {
        k: rt.get(k) for k in ("roundtrip_status", "equivalence_status", "checked_entity_count",
                               "max_numeric_error", "coord_tolerance", "semantic_fingerprint")
    }
    report["unicode_text_verification"] = rt.get("unicode_text_verification")
    ids_missing = {m if isinstance(m, str) else m.get("entity_id") for m in rt.get("missing_entities", [])}
    ids_bad: dict[str, list[str]] = {}
    for m in rt.get("mismatches", []):
        ids_bad.setdefault(m.get("entity_id"), []).append(f"{m.get('code')}: {m.get('message')}"[:240])
    src_of: dict[str, str] = {}
    for ent in view.get("entities", []):
        src_of[ent["id"]] = ent.get("source_geometry_id") or "?"
    groups: dict[str, dict] = {}
    for ent_id, src in sorted(src_of.items()):
        state = ("MISSING_ENTITY" if ent_id in ids_missing
                 else "VERIFIED_MISMATCH" if ent_id in ids_bad else "VERIFIED_MATCH")
        g = groups.setdefault(src, {"status": "VERIFIED_MATCH", "entities": 0, "issues": []})
        g["entities"] += 1
        if _SEVERITY.index(state) > _SEVERITY.index(g["status"]):
            g["status"] = state
        if state != "VERIFIED_MATCH":
            g["issues"].append({"entity_id": ent_id, "status": state,
                                "detail": ids_bad.get(ent_id, ["missing in drawing"])[:3]})
    for ent_id in sorted(set(ids_bad) - set(src_of)):
        groups.setdefault("?", {"status": "UNKNOWN", "entities": 0, "issues": []})["issues"].append(
            {"entity_id": ent_id, "status": "UNKNOWN", "detail": ids_bad[ent_id][:3]})
    report["by_source_geometry"] = groups
    unlinked = Counter(
        e.dxftype() for e in doc.modelspace()
        if decode_ir_xdata(e) is None or decode_ir_xdata(e).get("id") not in src_of
    )
    report["unlinked_cad_entities"] = {
        "status": "UNKNOWN" if unlinked else "NONE",
        "counts": dict(sorted(unlinked.items())),
        "note": "CAD entities without a VNAI link cannot be matched; reported, not judged.",
    }
    report["extra_entities"] = rt.get("extra_entities", [])[:50]
    worst = max((g["status"] for g in groups.values()), key=_SEVERITY.index, default="UNKNOWN")
    if "STALE" in (checks["drawing_digest"], checks["ir_link"]):
        status = "STALE"
    elif worst in {"MISSING_ENTITY", "VERIFIED_MISMATCH"} or rt.get("extra_entities"):
        status = "VERIFIED_MISMATCH"
    elif rt.get("equivalence_status") in {"LOSSLESS_EQUIVALENT", "NUMERICALLY_EQUIVALENT"}:
        status = "VERIFIED_MATCH"
    else:
        status = "VERIFIED_MISMATCH" if rt.get("roundtrip_status") == "MISMATCH" else "INCOMPLETE"
    report["comparison_status"] = status
    report["summary"] = dict(sorted(Counter(g["status"] for g in groups.values()).items()))
    return report
