#!/usr/bin/env python3
"""
page_discovery.py — discover and cluster pages for the GA4 tracking audit.

Strategy, in order:
  1. Fetch /robots.txt; if it lists Sitemap: URLs, follow them.
  2. Otherwise try /sitemap.xml, /sitemap_index.xml, /sitemap1.xml.
  3. If a sitemap is a sitemap-index, follow each child sitemap.
  4. If no sitemap works, fall back to crawling the homepage: collect every
     same-origin link, dedupe by path pattern.
  5. Cluster URLs into "templates" by collapsing path segments that look like
     identifiers (numeric, slug-style, UUID-style) and pick at most one
     example per template.

Output: JSON list of {"url": ..., "template_label": ...}, root URL first.

Usage:
    python page_discovery.py --root-url https://example.com \
        --max-pages 15 --output /tmp/audit_pages.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from typing import Iterable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    sys.stderr.write("`requests` is required. Install with: pip install requests --break-system-packages\n")
    raise

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ChromeTrackingCheck/1.0; "
        "site-owner-run tracking check)"
    )
}
TIMEOUT = 15
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# ---------- Sitemap discovery ----------

def candidate_sitemap_urls(root: str) -> list[str]:
    parsed = urlparse(root)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml", f"{base}/sitemap1.xml"]


def sitemap_urls_from_robots(root: str) -> list[str]:
    parsed = urlparse(root)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = requests.get(robots_url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    return [line.split(":", 1)[1].strip()
            for line in resp.text.splitlines()
            if line.lower().startswith("sitemap:")]


def fetch_sitemap(url: str) -> list[str]:
    """Return URLs from a sitemap or sitemap index."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return []
    if resp.status_code != 200 or not resp.text.strip():
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    tag = root.tag.split("}")[-1]
    locs: list[str] = []
    if tag == "sitemapindex":
        for sm in root.findall("sm:sitemap/sm:loc", SITEMAP_NS):
            if sm.text:
                locs.extend(fetch_sitemap(sm.text.strip()))
    elif tag == "urlset":
        for u in root.findall("sm:url/sm:loc", SITEMAP_NS):
            if u.text:
                locs.append(u.text.strip())
    return locs


def discover_via_sitemap(root: str) -> list[str]:
    sitemaps = sitemap_urls_from_robots(root) or candidate_sitemap_urls(root)
    seen: list[str] = []
    seen_set: set[str] = set()
    for sm in sitemaps:
        for url in fetch_sitemap(sm):
            if url not in seen_set:
                seen.append(url)
                seen_set.add(url)
        if seen:
            return seen  # first sitemap that yielded anything wins
    return seen


# ---------- Homepage fallback crawl ----------

def discover_via_homepage(root: str) -> list[str]:
    try:
        resp = requests.get(root, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return [root]
    if resp.status_code != 200:
        return [root]

    parsed = urlparse(root)
    base_host = parsed.netloc.replace("www.", "")

    urls: list[str] = [root]
    seen: set[str] = {root}
    for match in re.finditer(r'href=["\']([^"\']+)["\']', resp.text, re.I):
        href = match.group(1).split("#")[0].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(root, href)
        ap = urlparse(absolute)
        if ap.scheme not in ("http", "https"):
            continue
        if ap.netloc.replace("www.", "") != base_host:
            continue
        if absolute not in seen:
            urls.append(absolute)
            seen.add(absolute)
    return urls


# ---------- Template clustering ----------

ID_SEGMENT = re.compile(
    r"^("
    r"\d+"                                             # numeric
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"  # UUID-ish
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[a-z0-9][a-z0-9\-_]{15,}"                       # long slug
    r"|p\d+|page-\d+"                                  # pagination
    r")$",
    re.I,
)


def template_key(url: str) -> str:
    """Collapse identifier-like segments to '{}' to form a template key."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    collapsed = ["{}" if ID_SEGMENT.match(p) else p.lower() for p in parts]
    if not collapsed:
        return "/ (homepage)"
    return "/" + "/".join(collapsed)


def label_template(key: str) -> str:
    if key == "/ (homepage)":
        return "Homepage"
    first = key.strip("/").split("/")[0] if key.strip("/") else ""
    mapping = {
        "product": "Product",
        "products": "Product",
        "shop": "Product",
        "category": "Category",
        "categories": "Category",
        "collection": "Category",
        "collections": "Category",
        "blog": "Blog post",
        "post": "Blog post",
        "posts": "Blog post",
        "news": "News article",
        "article": "Article",
        "articles": "Article",
        "checkout": "Checkout",
        "cart": "Cart",
        "thank-you": "Thank you",
        "thanks": "Thank you",
        "contact": "Contact",
        "about": "About",
        "pricing": "Pricing",
        "signup": "Sign up",
        "login": "Login",
        "search": "Search",
        "account": "Account",
    }
    return mapping.get(first, key)


# ---------- Orchestration ----------

def discover(root: str) -> list[str]:
    urls = discover_via_sitemap(root)
    if not urls:
        urls = discover_via_homepage(root)
    # Ensure root is present and first.
    urls = [u for u in urls if u != root]
    return [root] + urls


def sample_by_template(urls: Iterable[str], max_pages: int, root: str) -> list[dict]:
    """Pick at most one URL per template, capped at max_pages."""
    by_template: "OrderedDict[str, str]" = OrderedDict()
    by_template["/ (homepage)"] = root
    for u in urls:
        key = template_key(u)
        by_template.setdefault(key, u)
        if len(by_template) >= max_pages:
            break
    return [{"url": u, "template_label": label_template(k)}
            for k, u in by_template.items()][:max_pages]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root-url", required=True)
    ap.add_argument("--max-pages", type=int, default=15)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    urls = discover(args.root_url)
    sampled = sample_by_template(urls, args.max_pages, args.root_url)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({
            "root_url": args.root_url,
            "total_discovered": len(urls),
            "sampled_count": len(sampled),
            "pages": sampled,
        }, f, indent=2)

    print(f"Discovered {len(urls)} URLs, sampled {len(sampled)} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
