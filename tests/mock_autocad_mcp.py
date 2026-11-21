"""Mock AutoCAD MCP server (stdio, newline-delimited JSON-RPC) for tests only.

Modes: readonly | leaky | crash | garbage | rpc_error. Every tools/call is appended to --log so
tests can prove refused tools never reached the server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

READ_TOOLS = [
    {"name": "drawing_info", "annotations": {"readOnlyHint": True}},
    {"name": "entity_list", "annotations": {"readOnlyHint": True}},
]
WRITE_TOOLS = [{"name": "entity_move"}, {"name": "system_run_command"}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="readonly")
    ap.add_argument("--dxf")
    ap.add_argument("--log")
    ap.add_argument("--version", default="1.8.0")
    a = ap.parse_args()
    if a.mode == "crash":
        return 3
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method, rid = msg["method"], msg["id"]
        if a.mode == "garbage":
            print("this is not json", flush=True)
            continue
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "mock-autocad-mcp", "version": a.version}}
        elif method == "tools/list":
            result = {"tools": READ_TOOLS + (WRITE_TOOLS if a.mode == "leaky" else [])}
        elif method == "tools/call":
            name = msg["params"]["name"]
            if a.log:
                with open(a.log, "a", encoding="utf-8") as fh:
                    fh.write(name + "\n")
            if a.mode == "rpc_error":
                print(json.dumps({"jsonrpc": "2.0", "id": rid,
                                  "error": {"code": -32000, "message": "document busy"}}), flush=True)
                continue
            if name == "drawing_info":
                data = open(a.dxf, "rb").read() if a.dxf else b""
                body = {"backend": "mock", "autocad_version": None,
                        "document": {"name": "Tầng 1 — bản vẽ.dxf",
                                     "sha256": hashlib.sha256(data).hexdigest()}}
            else:
                off = int(msg["params"].get("arguments", {}).get("offset", 0))
                body = {"items": [{"type": "LINE", "layer": "A-WALL"}] * 3, "offset": off}
            result = {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}
        else:
            result = {}
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}, ensure_ascii=False),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    sys.exit(main())
