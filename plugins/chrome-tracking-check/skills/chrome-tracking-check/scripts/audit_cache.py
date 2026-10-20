#!/usr/bin/env python3
"""
audit_cache.py — persist and diff GA4 tracking audit runs per domain.

Cache location:  ~/.chrome-tracking-check/cache/<domain>/
Each successful run writes:
  - latest_scored.json     (the scored payload — basis for the diff)
  - latest_per_page.json   (per-page inspector snapshots — basis for hash skip)
  - latest_meta.json       (run_id, timestamp, docx_path, skill_commit_hash)
  - history/<YYYYMMDDTHHMMSS>_scored.json   (every run, retained)

CLI:
  python audit_cache.py save \
    --site https://example.com \
    --scored /tmp/scored.json \
    --per-page /tmp/per_page.json \
    --docx /tmp/report.docx

  python audit_cache.py diff \
    --site https://example.com \
    --scored /tmp/scored.json \
    --output /tmp/change_summary.json

  python audit_cache.py page-hashes \
    --site https://example.com \
    --output /tmp/known_hashes.json
"""

from __future__ import annotations
import argparse, json, shutil, sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


CACHE_ROOT = Path.home() / ".chrome-tracking-check" / "cache"


def _domain(site: str) -> str:
    h = urlparse(site).hostname or "site"
    return h.replace("www.", "")


def _cache_dir(site: str) -> Path:
    d = CACHE_ROOT / _domain(site)
    d.mkdir(parents=True, exist_ok=True)
    (d / "history").mkdir(exist_ok=True)
    return d


def save(site: str, scored_path: Path, per_page_path: Path, docx_path: Path | None) -> Path:
    cdir = _cache_dir(site)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    shutil.copy(scored_path, cdir / "latest_scored.json")
    shutil.copy(per_page_path, cdir / "latest_per_page.json")
    shutil.copy(scored_path, cdir / "history" / f"{ts}_scored.json")
    meta = {
        "run_at_utc": ts,
        "site": site,
        "docx_path": str(docx_path) if docx_path else None,
    }
    with open(cdir / "latest_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return cdir


def diff(site: str, new_scored: dict) -> dict:
    """Return a change_summary: new / resolved / unchanged / changed_evidence."""
    cdir = _cache_dir(site)
    prev_path = cdir / "latest_scored.json"
    if not prev_path.exists():
        return {
            "has_previous_run": False,
            "previous_run_at_utc": None,
            "new": [], "resolved": [], "unchanged": [], "evidence_changed": [],
        }
    with open(prev_path, "r", encoding="utf-8") as f:
        prev = json.load(f)

    def index(findings: list[dict]) -> dict[str, dict]:
        out = {}
        for f in findings or []:
            out[f.get("id", "")] = f
        return out

    prev_idx = index(prev.get("findings"))
    new_idx = index(new_scored.get("findings"))

    new_ids = set(new_idx) - set(prev_idx)
    resolved_ids = set(prev_idx) - set(new_idx)
    common_ids = set(new_idx) & set(prev_idx)

    def slim(f: dict) -> dict:
        return {
            "id": f.get("id", ""), "title": f.get("title", ""),
            "severity": f.get("severity", ""), "confidence": f.get("confidence", ""),
            "evidence_count": len(f.get("evidence") or []),
        }

    evidence_changed = []
    unchanged = []
    for fid in common_ids:
        a = prev_idx[fid]; b = new_idx[fid]
        a_ev = sorted([(e.get("url",""), e.get("detail","")) for e in a.get("evidence") or []])
        b_ev = sorted([(e.get("url",""), e.get("detail","")) for e in b.get("evidence") or []])
        if a_ev != b_ev:
            evidence_changed.append({"id": fid, "title": b.get("title",""),
                                     "previous_evidence_count": len(a_ev),
                                     "new_evidence_count": len(b_ev)})
        else:
            unchanged.append(slim(b))

    try:
        with open(cdir / "latest_meta.json", "r", encoding="utf-8") as f:
            prev_meta = json.load(f)
        prev_at = prev_meta.get("run_at_utc")
    except Exception:
        prev_at = None

    return {
        "has_previous_run": True,
        "previous_run_at_utc": prev_at,
        "previous_score": prev.get("score"),
        "previous_grade": prev.get("grade"),
        "new": [slim(new_idx[i]) for i in sorted(new_ids)],
        "resolved": [slim(prev_idx[i]) for i in sorted(resolved_ids)],
        "evidence_changed": evidence_changed,
        "unchanged": unchanged,
    }


def page_hashes(site: str) -> dict[str, str]:
    """Return {url: content_hash} from the last cached per-page payload."""
    cdir = _cache_dir(site)
    pp_path = cdir / "latest_per_page.json"
    if not pp_path.exists(): return {}
    with open(pp_path, "r", encoding="utf-8") as f:
        pp = json.load(f)
    out = {}
    for p in pp.get("pages") or []:
        h = p.get("content_hash")
        if h: out[p["url"]] = h
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("save")
    s.add_argument("--site", required=True)
    s.add_argument("--scored", required=True, type=Path)
    s.add_argument("--per-page", required=True, type=Path)
    s.add_argument("--docx", type=Path)

    d = sub.add_parser("diff")
    d.add_argument("--site", required=True)
    d.add_argument("--scored", required=True, type=Path)
    d.add_argument("--output", required=True, type=Path)

    h = sub.add_parser("page-hashes")
    h.add_argument("--site", required=True)
    h.add_argument("--output", required=True, type=Path)

    args = ap.parse_args()

    if args.cmd == "save":
        cdir = save(args.site, args.scored, args.per_page, args.docx)
        print(f"Saved to {cdir}")
    elif args.cmd == "diff":
        with open(args.scored, "r", encoding="utf-8") as f: new = json.load(f)
        change = diff(args.site, new)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(change, f, indent=2)
        print(f"Diff written to {args.output}; previous_run: {change['has_previous_run']}")
    elif args.cmd == "page-hashes":
        h_map = page_hashes(args.site)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(h_map, f, indent=2)
        print(f"{len(h_map)} known hashes -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
