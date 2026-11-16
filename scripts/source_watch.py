"""Gentle link-health checker for curated official sources; NOT a publication crawler.

No external data can be promoted to approved rules by this script.
Network may block requests: log UNKNOWN rather than claiming a source is gone.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


def probe_url(url: str, timeout: int = 8) -> dict:
    req = Request(url, headers={"User-Agent": "VNAI-SourceAudit/0.1 (+manual-review)"}, method="HEAD")
    try:
        with urlopen(req, timeout=timeout) as response:
            return {
                "status": "ACCESSIBLE" if 200 <= response.status < 400 else "UNKNOWN",
                "http_status": response.status,
                "last_modified": response.headers.get("Last-Modified"),
                "etag": response.headers.get("ETag"),
            }
    except HTTPError as exc:
        return {"status": "UNKNOWN", "http_status": exc.code, "reason": "HTTP refusal or error"}
    except (URLError, TimeoutError, OSError) as exc:
        return {"status": "UNKNOWN", "reason": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check curated source URL accessibility")
    parser.add_argument("--watchlist", default="sources/watchlist.yaml")
    parser.add_argument("--out", default="outputs/source-watch.json")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()
    data = yaml.safe_load(Path(args.watchlist).read_text(encoding="utf-8"))
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "URL_HEALTH_ONLY_NOT_NEW_PUBLICATIONS",
        "needs_human_review": True,
        "items": [],
    }
    for source in data.get("sources", []):
        result["items"].append(
            {"id": source["id"], "url": source["url"], **probe_url(source["url"], args.timeout)}
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"URL source health report: {out} (no automatic content approval)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
