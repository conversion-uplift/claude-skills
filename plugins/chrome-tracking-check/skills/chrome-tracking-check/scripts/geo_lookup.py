#!/usr/bin/env python3
"""
geo_lookup.py — best-effort browser apparent geo lookup for the audit run.

One HTTP call to ipinfo.io's free endpoint. Output JSON has:
    {
      "country": "GB",
      "region": "England",
      "city": "London",
      "ip": "8.8.8.8",
      "source": "ipinfo.io",
      "ok": true,
      "error": null
    }

OFF BY DEFAULT. The lookup sends the machine's public IP address to ipinfo.io,
so it only runs when the user has agreed and `--lookup` is passed. Without it
the script emits a stub `{"ok": false, "skipped": true}` and exits 0; the
aggregator treats missing geo as "unknown" without complaint.

If the network call fails (offline, blocked, rate-limited), the script also
emits `{"ok": false, "error": "..."}` and exits 0 — geo is never fatal.

Output goes to --output (path) and the same JSON is printed to stdout for
inline use. Caller decides whether to persist.

Usage:
    python geo_lookup.py --output /tmp/geo.json            # stub, no network call
    python geo_lookup.py --lookup --output /tmp/geo.json   # only with the user's OK
"""

from __future__ import annotations
import argparse, json, sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ENDPOINT = "https://ipinfo.io/json"
TIMEOUT_S = 5
USER_AGENT = "chrome-tracking-check/1.0"


def lookup() -> dict:
    req = Request(ENDPOINT, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "source": "ipinfo.io"}
    return {
        "ok": True,
        "source": "ipinfo.io",
        "country": (payload.get("country") or "").upper() or None,
        "region": payload.get("region"),
        "city": payload.get("city"),
        "ip": payload.get("ip"),
        "error": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--lookup", action="store_true",
                    help="Call ipinfo.io. Sends this machine's public IP; only with the user's OK.")
    ap.add_argument("--no-geo", action="store_true",
                    help="Kept for compatibility: same as the default (no network call).")
    args = ap.parse_args()
    result = lookup() if (args.lookup and not args.no_geo) else {"ok": False, "skipped": True, "source": None}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
