#!/usr/bin/env python3
"""
aggregate_findings.py, turn per-page inspector outputs into a deterministic
findings list ready for severity_scorer.py.

Why this exists:
  The original skill asked Claude to interpret the rules-of-the-road document
  by hand each run. That makes results non-reproducible and prone to drift.
  This script encodes every rule from `references/ga4_validation_rules.md`
  as Python so the same inputs always produce the same findings.

Input JSON (`--per-page`) shape:
    {
      "site": "https://example.com",
      "pages": [
        {
          "url": "https://example.com/",
          "template_label": "Homepage",
          "pre_consent": <output of probe.js>,
          "post_consent": <same shape or null if no consent banner>,
          "console_errors_pre": [{"message": "...", "source": "..."}, ...],
          "console_errors_post": [...],
          "network_status_codes": {"<url-prefix>": <code>, ...}  # optional
        },
        ...
      ]
    }

Output JSON (`--output`) is the payload that severity_scorer.py expects.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parent))


# ---------------------------------------------------------------------------
# Finding builder
# ---------------------------------------------------------------------------

class FindingBuilder:
    """Accumulates evidence per finding id, deduplicates rows by (url, detail).

    Each finding carries a confidence tier:
      - "Observed" , directly visible in the runtime (tag in DOM, event in
                      network). High confidence; usually the user can verify
                      by opening DevTools.
      - "Inferred" , derived from heuristics (sGTM via subdomain pattern,
                      PII via regex). Medium confidence; user should verify.
      - "Verify"   , requires GA4-property-side confirmation (whether an
                      event is marked as conversion; data retention setting).
                      Low confidence on its own; recommend user check in UI.
    """

    def __init__(self) -> None:
        # id -> {meta, evidence_set}
        self._findings: dict[str, dict[str, Any]] = {}

    def add(self, fid: str, *, title: str, category: str, description: str,
            recommendation: str, severity: str, url: str, detail: str,
            positive: bool = False, confidence: str = "Observed") -> None:
        f = self._findings.setdefault(fid, {
            "id": fid,
            "title": title,
            "category": category,
            "description": description,
            "recommendation": recommendation,
            "severity": severity,
            "positive": positive,
            "confidence": confidence,
            "_evidence": [],   # list of (url, detail)
            "_evidence_keys": set(),
        })
        key = (url or "", detail or "")
        if key not in f["_evidence_keys"]:
            f["_evidence_keys"].add(key)
            f["_evidence"].append({"url": url, "detail": detail})

    def to_list(self) -> list[dict[str, Any]]:
        out = []
        for f in self._findings.values():
            row = {k: v for k, v in f.items() if not k.startswith("_")}
            row["evidence"] = f["_evidence"]
            out.append(row)
        return out


# ---------------------------------------------------------------------------
# Per-page accessors (tolerant of missing keys / partial snapshots)
# ---------------------------------------------------------------------------

def _merge_captures(page: dict) -> dict:
    """Multi-capture verification (2-of-3 rule).

    If the inspector returned multiple snapshots in `captures` (because
    earlier inspectors that captured at 1s, 3.5s and 8s), merge them with a
    consistency check: facts observable in 2+ captures are kept normally;
    facts observable in only 1 are tagged with `transient: true` and may
    be filtered out by downstream rules. This eliminates false positives
    from race conditions during page load.

    Returns a merged snapshot in the same shape as a single capture, with
    `_transient_events` added for events seen in only one capture and
    `_capture_count` set to the number of captures merged.
    """
    pre = page.get("pre_consent") or {}
    captures = pre.get("captures") if isinstance(pre, dict) else None
    if not isinstance(captures, list) or len(captures) < 2:
        return pre  # single capture; nothing to merge
    captures = [c for c in captures if isinstance(c, dict) and not c.get("error")]
    if len(captures) < 2:
        return pre

    # Take the latest capture as the base (most settled state for consent,
    # tag_inventory, etc.), then refine events_seen with the 2-of-3 rule.
    base = dict(captures[-1])

    # Events: count how many captures saw each event_name. Keep events seen
    # in >=2 captures; mark <2 as transient.
    from collections import Counter, defaultdict
    appearances: dict[str, int] = Counter()
    unified_params: dict[str, set] = defaultdict(set)
    unified_sources: dict[str, set] = defaultdict(set)
    unified_count: dict[str, int] = defaultdict(int)
    for cap in captures:
        seen_this_cap = set()
        for slot in ((cap.get("events") or {}).get("events_seen") or []):
            name = slot.get("event_name") or ""
            if not name or name in seen_this_cap: continue
            seen_this_cap.add(name)
            appearances[name] += 1
            for k in (slot.get("param_names") or []): unified_params[name].add(k)
            for s in (slot.get("sources") or []): unified_sources[name].add(s)
            unified_count[name] += slot.get("count", 0)

    stable_events = []
    transient_events = []
    for name, n in appearances.items():
        slot = {
            "event_name": name,
            "param_names": sorted(unified_params[name]),
            "sources": sorted(unified_sources[name]),
            "count": unified_count[name],
            "captures_seen_in": n,
        }
        if n >= 2:
            stable_events.append(slot)
        else:
            slot["transient"] = True
            transient_events.append(slot)

    merged_events = dict(base.get("events") or {})
    merged_events["events_seen"] = stable_events
    merged_events["_transient_events"] = transient_events
    base["events"] = merged_events
    base["_capture_count"] = len(captures)
    return base



def _snapshot(page: dict, phase: str) -> dict:
    """Prefer post_consent.final > pre_consent.final > pre_consent (immediate)."""
    snap = page.get(phase) or {}
    # If aggregator was handed an inspector return that has both initial and
    # delayed shapes, prefer the delayed one (more complete).
    if isinstance(snap, dict) and snap.get("ready") and snap.get("meta", {}).get("delayed_capture"):
        return snap
    return snap

def _best(page: dict) -> dict:
    # Prefer post_consent if present; otherwise use multi-capture merge of
    # pre_consent if captures[] was supplied, else the immediate snapshot.
    post = _snapshot(page, "post_consent")
    if post: return post
    pre = _snapshot(page, "pre_consent")
    if isinstance(pre, dict) and isinstance(pre.get("captures"), list):
        return _merge_captures(page)
    return pre

def _vendors_present(snap: dict) -> set[str]:
    v = (snap or {}).get("vendors") or {}
    return {name for name, info in v.items() if info and info.get("present")}


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _ga4_rules(pages: list[dict], fb: FindingBuilder) -> None:
    pages_with_ga4: list[tuple[str, list[str]]] = []
    pages_without_ga4: list[str] = []
    all_ga4_ids: set[str] = set()
    for p in pages:
        snap = _merged_view(p)  # absence claims need the union, not one pass
        ids = (snap.get("tag_inventory") or {}).get("ga4_measurement_ids") or []
        if ids:
            pages_with_ga4.append((p["url"], ids))
            all_ga4_ids.update(ids)
        else:
            pages_without_ga4.append(p["url"])

    if not pages_with_ga4:
        for p in pages:
            fb.add("GA4_NOT_DETECTED",
                title="GA4 is not firing on this site",
                category="GA4",
                description=("No G- measurement ID was observed in dataLayer, "
                             "gtag scripts, or network requests on any audited page."),
                recommendation=("Install GA4, either via a GTM container that loads "
                                "the GA4 configuration tag on All Pages, or via the "
                                "standalone gtag.js snippet in the site's <head>."),
                severity="Critical",
                url=p["url"], detail="No GA4 measurement ID detected.")
        return

    if pages_without_ga4 and pages_with_ga4:
        for url in pages_without_ga4:
            fb.add("GA4_MISSING_ON_SOME_PAGES",
                title="GA4 is missing on some pages",
                category="GA4",
                description=("GA4 fires on some templates but not others. This causes "
                             "silent reporting gaps that are hard to spot in the GA4 UI."),
                recommendation=("Ensure the GA4 base tag in GTM is set to fire on the "
                                "'All Pages' trigger with no blocking conditions, or "
                                "that the standalone gtag.js snippet is present in the "
                                "global header on every template."),
                severity="Critical",
                url=url, detail="No GA4 measurement ID detected on this page.")

    if len(all_ga4_ids) > 1:
        # Distinct IDs across pages, flag if they don't all appear together everywhere.
        appearing_everywhere = set.intersection(*[set(ids) for _, ids in pages_with_ga4]) if pages_with_ga4 else set()
        if all_ga4_ids != appearing_everywhere:
            for url, ids in pages_with_ga4:
                fb.add("GA4_MULTIPLE_MEASUREMENT_IDS",
                    title="Multiple GA4 measurement IDs detected across pages",
                    category="GA4",
                    description=("More than one G- measurement ID is in use across the "
                                 "site. This usually indicates legacy/duplicate properties "
                                 "or a botched migration; data is being split across "
                                 "properties and reports won't reconcile."),
                    recommendation=("Audit GTM and the site code for stray gtag('config', 'G-XXX') "
                                    "calls. Standardise on a single GA4 measurement ID and "
                                    "remove the others."),
                    severity="High",
                    url=url, detail=f"IDs on this page: {', '.join(ids)}")

    # GA4 loaded but no page_view event sent?
    for p in pages:
        snap = _merged_view(p)  # absence claims need the union, not one pass
        ids = (snap.get("tag_inventory") or {}).get("ga4_measurement_ids") or []
        if not ids:
            continue
        ga4_hits = (snap.get("network") or {}).get("ga4_hits") or []
        page_view_seen = any((h.get("event_name") in (None, "page_view")) for h in ga4_hits)
        dl_has_page_view = False
        for entry in (snap.get("tag_inventory") or {}).get("dataLayer_sample") or []:
            if isinstance(entry, dict) and entry.get("event") == "page_view":
                dl_has_page_view = True
                break
        if not page_view_seen and not dl_has_page_view:
            fb.add("GA4_NO_PAGE_VIEW_EVENT",
                title="GA4 is loaded but no page_view was observed",
                category="GA4",
                description=("The GA4 base tag is on the page but no request to "
                             "/g/collect with event_name=page_view was captured. "
                             "This means measurement is not actually happening."),
                recommendation=("Check that 'Send a page view event when this configuration "
                                "loads' is enabled on the GA4 Configuration tag (it is by "
                                "default), and that no consent gate is permanently denying "
                                "analytics_storage."),
                severity="High",
                url=p["url"], detail=f"GA4 ID(s) present ({', '.join(ids)}) but no page_view request observed.")

    # Legacy UA
    for p in pages:
        snap = _merged_view(p)  # absence claims need the union, not one pass
        ua_ids = (snap.get("tag_inventory") or {}).get("universal_analytics_ids") or []
        if ua_ids:
            fb.add("GA4_LEGACY_UA_DETECTED",
                title="Sunset Universal Analytics tag still loading",
                category="GA4",
                description=("A Universal Analytics property tag is still being loaded. "
                             "UA stopped processing data in July 2024, so this tag does "
                             "nothing except add request weight and confuse maintainers."),
                recommendation=("Remove the UA-XXXX gtag config call and any related "
                                "dataLayer pushes from GTM and the site code. Confirm no "
                                "legacy dashboards depend on it before removing."),
                severity="High",
                url=p["url"], detail=f"UA IDs detected: {', '.join(ua_ids)}")


def _gtm_rules(pages: list[dict], fb: FindingBuilder) -> None:
    any_gtm = False
    for p in pages:
        snap = _merged_view(p)  # absence claims need the union, not one pass
        ti = snap.get("tag_inventory") or {}
        if ti.get("gtm_containers"):
            any_gtm = True
        if ti.get("gtm_loaded_multiple_times"):
            count = ti.get("gtm_load_count", 0)
            fb.add("GTM_DUPLICATE_CONTAINER",
                title="GTM container loaded more than once on the same page",
                category="GTM",
                description=("A GTM container script tag appeared multiple times on this "
                             "page. Duplicate containers cause double-firing of every tag, "
                             "inflating GA4 numbers and double-charging conversion pixels."),
                recommendation=("Search the source for repeated 'googletagmanager.com/gtm.js' "
                                "script tags. Remove all but one. Common cause: GTM is both "
                                "in the global header AND injected by a CMS plugin."),
                severity="High",
                url=p["url"], detail=f"GTM script loaded {count} times.")
        if len(ti.get("gtm_containers") or []) > 1:
            fb.add("GTM_MULTIPLE_CONTAINERS",
                title="Multiple GTM containers on one page",
                category="GTM",
                description=("More than one distinct GTM container ID is loading on this "
                             "page. This isn't always wrong (agency + client containers, "
                             "for example) but is often unintended."),
                recommendation=("Verify each container is intentional and document who "
                                "owns it. Consolidate where possible."),
                severity="Medium",
                url=p["url"], detail=f"Containers: {', '.join(ti['gtm_containers'])}")
        if ti.get("gtm_containers") and ti.get("has_standalone_gtag"):
            fb.add("GTM_AND_STANDALONE_GTAG_BOTH",
                title="GTM and standalone gtag.js both present",
                category="GTM",
                description=("This page loads a GTM container AND a separate gtag/js snippet. "
                             "GTM already provides gtag, the extra snippet duplicates events "
                             "and complicates Consent Mode wiring."),
                recommendation=("Pick one delivery method. If you're using GTM, remove the "
                                "standalone gtag.js snippet."),
                severity="Medium",
                url=p["url"], detail="Both gtm.js and gtag/js script tags detected.")

    if not any_gtm:
        for p in pages:
            fb.add("GTM_NOT_DETECTED",
                title="No Google Tag Manager container detected",
                category="GTM",
                description=("No GTM container is loading on any audited page. This isn't "
                             "necessarily wrong if you've chosen to deploy tags via the "
                             "standalone gtag.js or a CDP, but most teams find GTM easier "
                             "to maintain."),
                recommendation=("Consider migrating to GTM if your team frequently changes "
                                "tags or runs marketing experiments."),
                severity="Medium",
                url=p["url"], detail="No GTM container detected.")


def _consent_rules(pages: list[dict], fb: FindingBuilder) -> None:
    any_consent_mode = False
    any_v2_signals = False
    any_cmp_detected = False
    any_tracking_with_no_consent = False

    for p in pages:
        snap = _best(p)
        c = snap.get("consent") or {}
        any_consent_mode = any_consent_mode or bool(c.get("consent_mode_detected"))
        any_v2_signals = any_v2_signals or bool(c.get("v2_signals_present"))
        if c.get("cmps_detected") or c.get("tcf_api_present"):
            any_cmp_detected = True

        # Was tracking happening?
        net = snap.get("network") or {}
        has_tracking = bool((net.get("ga4_hits") or []) or (net.get("facebook_hits") or [])
                            or (net.get("linkedin_hits") or []))
        if has_tracking and not c.get("consent_mode_detected"):
            any_tracking_with_no_consent = True

        if c.get("consent_mode_detected") and not c.get("v2_signals_present"):
            fb.add("CONSENT_MODE_V1_ONLY",
                title="Consent Mode is implemented but only v1 signals are present",
                category="Compliance",
                description=("The default consent call is missing ad_user_data and/or "
                             "ad_personalization. Since March 2024, both are required for "
                             "Google Ads remarketing/audiences in the EEA and UK."),
                recommendation=("Update your CMP/GTM template to include all four v2 signals: "
                                "ad_storage, analytics_storage, ad_user_data, ad_personalization."),
                severity="High",
                url=p["url"], detail=f"Default payload: {json.dumps(c.get('default_state_raw'), separators=(',',':'))[:200]}")
        if (c.get("default_consent_call_found")
                and not (c.get("region_targeting") or [])):
            fb.add("CONSENT_MODE_NO_REGION",
                title="Consent Mode default applies globally",
                category="Compliance",
                description=("Consent Mode default has no region parameter, so the denied-"
                             "by-default state is applied to all visitors worldwide. This is "
                             "usually unintended outside the EEA/UK."),
                recommendation=("Add region: ['EEA', 'GB'] (or your relevant regions) to the "
                                "default consent call so only users in those regions are "
                                "treated as denied by default."),
                severity="Info",
                url=p["url"], detail="Default consent call has no region targeting.")

    if not any_consent_mode and any_tracking_with_no_consent:
        for p in pages:
            fb.add("CONSENT_MODE_MISSING",
                title="Consent Mode v2 not implemented",
                category="Compliance",
                description=("No gtag('consent', 'default', …) call was observed and tracking "
                             "tags fire regardless. For EEA/UK visitors this exposes the site "
                             "to GDPR risk and degrades Google Ads conversion measurement."),
                recommendation=("Add a Consent Mode v2 default tag firing as the first thing on "
                                "every page (priority high) with all four signals defaulted to "
                                "'denied' and region targeting set. Wire the CMP's accept/reject "
                                "events to a corresponding consent update tag."),
                severity="Critical",
                url=p["url"], detail="No consent default observed; tracking tags still fire.")

    if not any_cmp_detected and any_tracking_with_no_consent:
        for p in pages:
            fb.add("CMP_NOT_DETECTED",
                title="No consent management platform detected",
                category="Compliance",
                description=("No CMP signature (OneTrust, Cookiebot, Didomi, etc.) and no "
                             "IAB TCF API was detected. Without a CMP, the site cannot "
                             "legitimately capture or update consent."),
                recommendation=("Install a CMP that supports Google Consent Mode v2 and the "
                                "IAB TCF v2 framework if you serve EEA/UK visitors."),
                severity="Medium",
                url=p["url"], detail="No CMP signature detected on this page.")


def _sgtm_rules(pages: list[dict], fb: FindingBuilder) -> None:
    for p in pages:
        snap = _best(p)
        hits = (snap.get("network") or {}).get("probable_sgtm_hits") or []
        for h in hits:
            fb.add("SGTM_DETECTED",
                title="Server-side GTM detected",
                category="Infrastructure",
                description=("Requests on a first-party or non-Google host are serving the "
                             "GA4 collection endpoint. This is a positive signal, server-"
                             "side GTM gives you better data quality and ad-blocker "
                             "resilience."),
                recommendation=("No action needed. Document the sGTM URL in your team's "
                                "tracking inventory so future maintainers know about it."),
                severity="Info",
                url=p["url"], detail=f"{h.get('reason', '')} {h.get('url','')}",
                positive=True)


def _tag_gateway_rules(payload: dict, pages: list[dict], fb: FindingBuilder) -> None:
    """Google tag gateway for advertisers.

    It fails silently: the Google-side toggle can be set while the CDN half was
    never mapped, and tagging keeps working via the normal googletagmanager.com
    fallback. Nothing breaks, so nobody notices. Absence alone is therefore NOT
    a finding. A CLAIMED-but-absent deployment is (set `claimed_tag_gateway` in
    the payload, or pass --claimed-tag-gateway).
    """
    claimed = bool(payload.get("claimed_tag_gateway"))
    for p in pages:
        snap = _best(p)
        tg = (snap.get("network") or {}).get("tag_gateway") or {}
        status = tg.get("status") or "not_detected"
        paths = [x for x in (tg.get("measurement_paths") or []) if x and x != "/"]
        fp_loader = tg.get("first_party_loader_hits") or []
        g_loader = tg.get("google_hosted_loader_hits") or []
        g_collect = tg.get("google_hosted_collect_hits") or []
        path_str = ", ".join(paths) if paths else "(root)"

        if status == "active":
            fb.add("TAG_GATEWAY_DETECTED",
                title="Google tag gateway for advertisers is active",
                category="Infrastructure",
                description=("Both the Google tag library and its collection endpoints are "
                             "served from your own origin behind a measurement path. This is "
                             "a positive signal: first-party delivery is materially harder "
                             "for ad blockers and browser tracking prevention to strip out."),
                recommendation=("No action needed. Record the measurement path in your tag "
                                "inventory. It is easy to break during a CDN migration and "
                                "the breakage is silent, so re-test after any DNS or CDN change."),
                severity="Info", positive=True, confidence="Observed",
                url=p["url"],
                detail=f"Measurement path {path_str}; first-party loader and collection observed.")
            if g_collect:
                hosts = sorted({h.get("host") or "" for h in g_collect if h.get("host")})
                fb.add("TAG_GATEWAY_BYPASSED",
                    title="Some tags bypass the active Tag Gateway and call Google directly",
                    category="Infrastructure",
                    description=("Tag Gateway is serving first-party traffic on this page, but "
                                 "collection requests are ALSO going straight to Google-owned "
                                 "hosts. Usually a hard-coded gtag snippet, a second container, "
                                 "or a vendor tag never pointed at the measurement path. Those "
                                 "hits keep the blocker exposure the Gateway was bought to "
                                 "remove, and can double-count."),
                    recommendation=("Find the tags still calling Google hosts directly and route "
                                    "them through the measurement path. Check for a hard-coded "
                                    "gtag.js in the page template alongside the GTM container."),
                    severity="Medium", confidence="Needs verification",
                    url=p["url"],
                    detail=f"Direct-to-Google collection alongside Gateway: {', '.join(hosts)}")
        elif status == "partial":
            present = "the tag library" if fp_loader else "collection endpoints"
            missing = "collection endpoints" if fp_loader else "the tag library"
            fb.add("TAG_GATEWAY_PARTIAL",
                title="Tag Gateway is only half configured",
                category="Infrastructure",
                description=(f"First-party delivery was observed for {present}, but {missing} "
                             "still resolve elsewhere. A partial Gateway gives a fraction of "
                             "the resilience benefit while adding a dependency to maintain, "
                             "and usually means the setup was abandoned part-way."),
                recommendation=("Complete the setup so both the library and the collection "
                                "endpoints resolve through the measurement path, then validate "
                                "in Tag Assistant: Summary > Output > Hits Sent should show the "
                                "hits routed to your measurement path."),
                severity="Medium", confidence="Observed",
                url=p["url"],
                detail=f"Measurement path {path_str}; first-party delivery of {present} only.")
        elif claimed:
            g_hosts = sorted({h.get("host") or "" for h in (g_loader + g_collect) if h.get("host")})
            fb.add("TAG_GATEWAY_CLAIMED_NOT_ACTIVE",
                title="Tag Gateway reported as enabled, but no first-party delivery observed",
                category="Infrastructure",
                description=("The site owner reports Google tag gateway for advertisers is "
                             "enabled. Runtime inspection found no first-party measurement path "
                             "on this page: the Google tag library and its collection requests "
                             "both resolve to Google-owned hosts. The usual cause is a setup "
                             "finished on the Google side but never completed on the CDN side. "
                             "The fallback to googletagmanager.com works perfectly, so nothing "
                             "appears broken and the gap goes unnoticed."),
                recommendation=("Confirm the measurement path is mapped at the CDN, not just "
                                "toggled in Google Ads or Tag Manager. Validate in Tag Assistant "
                                "(Summary > Output > Hits Sent): the hits must show your "
                                "measurement path, not googletagmanager.com. Until then, treat "
                                "this site as client-side only for blocker exposure."),
                severity="High", confidence="Observed",
                url=p["url"],
                detail=(f"No first-party loader or collection path. Google hosts serving tags: "
                        f"{', '.join(g_hosts) if g_hosts else 'none observed'}."))


def _pixel_rules(pages: list[dict], fb: FindingBuilder) -> None:
    for p in pages:
        snap = _best(p)
        v = snap.get("vendors") or {}
        meta = v.get("Meta (Facebook) Pixel") or {}
        if meta.get("present"):
            ids = meta.get("ids") or []
            if len(set(ids)) > 1:
                fb.add("META_PIXEL_MULTIPLE_IDS",
                    title="Multiple Meta Pixel IDs firing on the same page",
                    category="Pixels",
                    description=("More than one Meta Pixel ID is initialised on this page. "
                                 "Some shared events will report against both, inflating "
                                 "performance and confusing attribution."),
                    recommendation=("Audit fbq('init', ...) calls in GTM and the site code. "
                                    "Keep only the pixel(s) your media team actually uses."),
                    severity="Medium",
                    url=p["url"], detail=f"Pixel IDs: {', '.join(ids)}")
            # Duplicate same-id firing, heuristic: check facebook_hits count for the same pixel id
            net_hits = (snap.get("network") or {}).get("facebook_hits") or []
            by_id_event = defaultdict(int)
            for h in net_hits:
                key = (h.get("pixel_id"), h.get("event_name"))
                by_id_event[key] += 1
            dupes = [(k, c) for k, c in by_id_event.items() if c > 1 and k[1] == "PageView"]
            if dupes:
                for (pid, ev), count in dupes:
                    fb.add("META_PIXEL_DUPLICATE",
                        title="Meta Pixel PageView fires more than once on the same page",
                        category="Pixels",
                        description=("The PageView event for the same Meta Pixel ID was "
                                     "captured multiple times in resource timing. This usually "
                                     "means the pixel is initialised twice."),
                        recommendation=("Find the duplicate fbq('init', 'PIXEL_ID') call and "
                                        "remove it. Common cause: pixel both in GTM and in the "
                                        "site's hardcoded snippet."),
                        severity="Medium",
                        url=p["url"], detail=f"Pixel {pid} PageView fired {count} times.")

        # Positive findings for paid-social pixels merely being present.
        for vendor_name, fid, title in [
            ("LinkedIn Insight", "LINKEDIN_INSIGHT_PRESENT", "LinkedIn Insight Tag detected"),
            ("TikTok Pixel", "TIKTOK_PIXEL_PRESENT", "TikTok Pixel detected"),
            ("Pinterest Tag", "PINTEREST_TAG_PRESENT", "Pinterest Tag detected"),
        ]:
            vendor = v.get(vendor_name) or {}
            if vendor.get("present"):
                ids = vendor.get("ids") or []
                fb.add(fid, title=title, category="Pixels",
                    description=f"{vendor_name} is loaded on this page.",
                    recommendation="No action, informational.",
                    severity="Info",
                    url=p["url"], detail=f"IDs: {', '.join(ids) if ids else '(none extracted)'}",
                    positive=True)


def _overlap_rules(pages: list[dict], fb: FindingBuilder) -> None:
    SESSION_REPLAY = {"Hotjar", "FullStory", "Mouseflow", "Lucky Orange", "Smartlook", "Microsoft Clarity"}
    for p in pages:
        snap = _best(p)
        present = _vendors_present(snap) & SESSION_REPLAY
        if len(present) >= 2:
            fb.add("MULTIPLE_SESSION_REPLAY_TOOLS",
                title="Multiple session-replay / heatmap tools loaded together",
                category="Vendor overlap",
                description=("More than one session-replay/heatmap product is on this page. "
                             "Each one adds page weight and records overlapping data; teams "
                             "rarely use more than one in practice."),
                recommendation=("Pick the tool the team actually uses and remove the others. "
                                "Page weight matters more than the redundancy itself."),
                severity="Low",
                url=p["url"], detail=f"Detected: {', '.join(sorted(present))}")


def _performance_rules(pages: list[dict], fb: FindingBuilder) -> None:
    for p in pages:
        snap = _best(p)
        perf = (snap.get("performance") or {}).get("web_vitals") or {}
        lcp, cls, inp = perf.get("lcp_ms"), perf.get("cls"), perf.get("inp_ms_approx")
        if lcp is not None and lcp > 4000:
            fb.add("LCP_POOR",
                title="Poor Largest Contentful Paint",
                category="Performance",
                description=(f"LCP on this page is {lcp}ms, above Google's 'Poor' threshold "
                             f"of 4000ms. Heavy analytics/marketing JS often contributes."),
                recommendation=("Defer non-critical scripts until after LCP, preload the hero "
                                "image, and check for render-blocking CSS."),
                severity="Medium",
                url=p["url"], detail=f"LCP {lcp}ms")
        if cls is not None and cls > 0.25:
            fb.add("CLS_POOR",
                title="Poor Cumulative Layout Shift",
                category="Performance",
                description=(f"CLS on this page is {cls}, above Google's 'Poor' threshold "
                             f"of 0.25. Often caused by tags or images injected after first paint."),
                recommendation=("Reserve space for embeds and ad slots, set explicit width/height "
                                "on images, and avoid layout-shifting CMP banners."),
                severity="Medium",
                url=p["url"], detail=f"CLS {cls}")
        if inp is not None and inp > 500:
            fb.add("INP_POOR",
                title="Slow interaction response (approximate INP)",
                category="Performance",
                description=(f"The longest observed input event was {inp}ms, slow per Web "
                             f"Vitals (Google's 'Poor' threshold is 500ms for INP)."),
                recommendation=("Profile long tasks; heavy analytics callbacks on click are a "
                                "common cause."),
                severity="Medium",
                url=p["url"], detail=f"INP approx {inp}ms")
        a = (snap.get("performance") or {}).get("resource_counts", {}).get("analytics_related", 0)
        if a > 30:
            fb.add("EXCESSIVE_ANALYTICS_REQUESTS",
                title="High analytics request count",
                category="Performance",
                description=(f"This page made {a} analytics-related network requests. Heavy "
                             f"tag load competes with page rendering and uses visitor bandwidth."),
                recommendation=("Review tag inventory, anything you no longer use? Move heavy "
                                "tags to consent-gated triggers."),
                severity="Low",
                url=p["url"], detail=f"{a} analytics-related requests.")


def _console_error_rule(pages: list[dict], fb: FindingBuilder) -> None:
    for p in pages:
        for phase in ("console_errors_pre", "console_errors_post"):
            errors = p.get(phase) or []
            tag_related = [e for e in errors if _looks_tag_related(e)]
            if tag_related:
                fb.add("TAG_JAVASCRIPT_ERROR",
                    title="JavaScript error from a tracking script",
                    category="Runtime errors",
                    description=("A console error was emitted by a tracking script during the "
                                 f"{phase.split('_')[-1]}-consent inspection. Errors here often "
                                 "indicate CSP blocks, ad-blocker interference, or a misconfigured tag."),
                    recommendation=("Open DevTools on this URL and inspect the Console tab for "
                                    "the full stack. Fix the root cause, silently swallowed errors "
                                    "can lose entire categories of events."),
                    severity="High",
                    url=p["url"], detail=(tag_related[0].get("message") or "")[:300])


def _looks_tag_related(error: dict) -> bool:
    src = (error.get("source") or "") + " " + (error.get("message") or "")
    src = src.lower()
    return any(needle in src for needle in [
        "googletagmanager", "google-analytics", "gtag", "gtm",
        "facebook.net", "fbq", "fbevents",
        "snap.licdn", "linkedin",
        "analytics.tiktok", "pintrk", "pinimg",
        "clarity", "hotjar", "fullstory", "mouseflow", "luckyorange", "smartlook",
        "segment", "tiqcdn", "adobedtm", "mparticle",
    ])


def _ecommerce_rules(pages: list[dict], fb: FindingBuilder) -> None:
    """GA4 vs GA Universal ecommerce schema; missing required item fields.

    The most common ecommerce implementation bug in 2026 is sites still pushing
    the Universal Analytics `products[]` schema instead of GA4's `items[]`. The
    data lands in GA4 but every ecommerce report shows zeros. The aggregator
    flags this as High because data IS being lost.
    """
    site_detected_ga4_ids = set()
    for p in pages:
        snap = _best(p)
        site_detected_ga4_ids.update((snap.get("tag_inventory") or {}).get("ga4_measurement_ids") or [])

    for p in pages:
        snap = _best(p)
        ec = snap.get("ecommerce") or {}
        if ec.get("ua_products_observed") and not ec.get("ga4_items_observed"):
            fb.add("GA4_ECOMMERCE_LEGACY_SCHEMA",
                title="Ecommerce dataLayer is still using the Universal Analytics schema",
                category="Ecommerce",
                description=("The page pushes ecommerce data using the legacy "
                             "`ecommerce.purchase.products[]` (or `.add.products[]`) shape. "
                             "GA4 ignores this, it expects `ecommerce.items[]` with each item "
                             "carrying `item_id`, `item_name`, `price`, `quantity`, plus `currency` "
                             "on the parent event. Result: every GA4 ecommerce report shows zeros "
                             "even though data appears to be flowing."),
                recommendation=("Migrate the dataLayer to the GA4 schema. Concretely, in your "
                                "tag manager or site code, rename `products` to `items`, replace "
                                "the per-event wrapper (`purchase`, `add`, `detail`) with a flat "
                                "`ecommerce.items` array, and add `currency` + `value` on the event. "
                                "Refer to `references/ga4_event_taxonomy.md` for the canonical schema."),
                severity="High",
                url=p["url"], detail=f"`products[]` observed; no `items[]` array seen. Events: {', '.join(sorted(set(ec.get('ecommerce_events') or [])))}",
                confidence="Observed")
        for miss in ec.get("items_missing_required") or []:
            event_name = miss.get("event_name") or "(unknown)"
            missing = ", ".join(miss.get("missing") or [])
            fb.add("GA4_ECOMMERCE_ITEMS_INCOMPLETE",
                title="GA4 ecommerce items are missing required fields",
                category="Ecommerce",
                description=("`items[]` was pushed but at least one item is missing a required "
                             "field. GA4 will keep the event but reports against the missing "
                             "dimensions will be blank, e.g. Item ID reports if `item_id` is "
                             "missing, Item Name reports if `item_name` is missing."),
                recommendation=("Audit your tag templates / source-of-truth for the items array. "
                                "Every item needs at minimum `item_id` and `item_name`; for "
                                "monetary events also `price`, `quantity`, and `currency` on the "
                                "parent payload."),
                severity="High",
                url=p["url"], detail=f"Event `{event_name}` items missing: {missing}",
                confidence="Observed")


def _event_inventory_rules(pages: list[dict], fb: FindingBuilder) -> None:
    """No key events observed + Enhanced Measurement double-counting."""
    site_event_names: set[str] = set()
    any_key_event = False
    any_ga4 = False
    for p in pages:
        snap = _best(p)
        ev = snap.get("events") or {}
        for slot in ev.get("events_seen") or []:
            site_event_names.add(slot.get("event_name") or "")
        if ev.get("key_events_observed"):
            any_key_event = True
        if (snap.get("tag_inventory") or {}).get("ga4_measurement_ids"):
            any_ga4 = True
        # Duplicate Enhanced Measurement events (same event_name observed from
        # both a dataLayer push AND a /g/collect beacon, typical signature of
        # Enhanced Measurement firing on top of a custom GTM tag for the same
        # event). High severity because it inflates KPIs silently.
        for dup in ev.get("duplicate_event_sources") or []:
            fb.add("ENHANCED_MEASUREMENT_DUPLICATE",
                title="Possible Enhanced Measurement double-counting",
                category="GA4",
                description=(f"The event `{dup}` appears from both a custom GTM/dataLayer push "
                             "and from the GA4 `/g/collect` beacon. This is the typical signature "
                             "of Enhanced Measurement (which auto-tracks scroll/click/file_download/"
                             "video/site_search) firing on top of a custom GTM tag that pushes the "
                             "same event name. Result: every such interaction is counted twice."),
                recommendation=("Either disable the duplicate Enhanced Measurement option in the "
                                "GA4 Web Stream settings, or remove your custom GTM tag for that "
                                "event. Don't run both. Verify in GA4 DebugView that the event "
                                "now fires exactly once per interaction."),
                severity="High",
                url=p["url"], detail=f"Event: {dup}",
                confidence="Inferred")

    if any_ga4 and not any_key_event:
        # Don't preach about key events on small-sample audits.
        if len(pages) >= 2:
            for p in pages:
                fb.add("GA4_NO_KEY_EVENTS_OBSERVED",
                    title="No GA4 key events were observed across the audited pages",
                    category="GA4",
                    description=("GA4 is firing, but no events that look like conversions were "
                                 "observed on any audited page, no `purchase`, `sign_up`, "
                                 "`generate_lead`, `add_to_cart`, `view_item`, or similar. Either "
                                 "the audit didn't visit pages that should fire those events, or "
                                 "key-event tracking isn't wired. Without key events, GA4 cannot "
                                 "report on conversions, populate audiences for Google Ads, or "
                                 "calculate engagement value."),
                    recommendation=("Identify the 3-5 events that matter most to this business "
                                    "(usually some combination of `generate_lead`/`sign_up`/`purchase`). "
                                    "Implement them via GTM. Then mark them as conversions in GA4 "
                                    "Admin → Events. Re-run this audit while interacting with the "
                                    "site (click CTA, submit form, complete checkout) to verify."),
                    severity="High",
                    url=p["url"], detail="No conversion-shaped events observed in dataLayer or /g/collect.",
                    confidence="Inferred")

    # Positive finding: list candidate conversion events so the user can verify
    # they're marked as conversions in the GA4 property.
    candidates = sorted(site_event_names & {
        "purchase", "sign_up", "generate_lead", "qualify_lead", "submit_application",
        "subscribe", "request_quote", "book_appointment"
    })
    if candidates:
        fb.add("GA4_LIKELY_CONVERSIONS_UNVERIFIED",
            title="Conversion-shaped events observed, verify they are marked as conversions in GA4",
            category="GA4",
            description=("These events look like business conversions. Whether GA4 actually treats "
                         "them as conversions cannot be verified from the browser, it's set in "
                         "the property UI (Admin → Events → 'Mark as conversion'). If unticked, "
                         "the events are collected but won't drive conversion reports or Google "
                         "Ads conversion imports."),
            recommendation=(f"Open GA4 → Admin → Events. Confirm each of these is toggled as a "
                            f"conversion: {', '.join(candidates)}. If you use Google Ads, also "
                            "ensure each is imported as a Google Ads conversion."),
            severity="Info",
            url=pages[0]["url"] if pages else "",
            detail=f"Candidate conversion events: {', '.join(candidates)}",
            confidence="Verify",
            positive=True)


def _cross_domain_rule(pages: list[dict], fb: FindingBuilder) -> None:
    """Multiple first-party hosts seen, but no linker domains in any gtag config."""
    union_hosts: set[str] = set()
    any_linker = False
    any_ga4 = False
    for p in pages:
        snap = _best(p)
        cfg = snap.get("config") or {}
        for h in cfg.get("first_party_hosts_seen") or []:
            union_hosts.add(h)
        if cfg.get("cross_domain_linker_domains"):
            any_linker = True
        if (snap.get("tag_inventory") or {}).get("ga4_measurement_ids"):
            any_ga4 = True
    if any_ga4 and len(union_hosts) >= 1 and not any_linker:
        for p in pages:
            fb.add("GA4_NO_CROSS_DOMAIN_LINKER",
                title="Cross-domain linker not configured but multiple first-party hosts detected",
                category="GA4",
                description=("Requests to additional first-party hostnames were observed (e.g. a "
                             "separate checkout subdomain or sister property), but no GA4 config "
                             "call sets `linker.domains`. Without the linker, the GA4 client ID is "
                             "lost when users move between the domains, sessions split, attribution "
                             "fragments, returning-user counts inflate."),
                recommendation=(f"Add `linker: {{ domains: ['example.com', 'checkout.example.com'] }}` "
                                "to your `gtag('config', ...)` call (or set Cross-Domain Linker in "
                                "the GA4 Web Stream settings). Verify with GA4 DebugView that the "
                                "client_id persists across the domain boundary."),
                severity="High",
                url=p["url"], detail=f"Other first-party hosts seen: {', '.join(sorted(union_hosts))}",
                confidence="Inferred")
            break  # only emit once, same evidence applies to all pages


def _parse_chrome_version(ua: str) -> str:
    """Extract `Chrome/124.0.6367.155` -> '124.0.6367.155'. Returns '' if absent."""
    import re
    m = re.search(r"Chrome/([\d.]+)", ua or "")
    return m.group(1) if m else ""


def _iso_from_ms(ms: int | None) -> str:
    if not ms: return ""
    try:
        return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _human_ms(ms: int) -> str:
    if ms <= 0: return "n/a"
    secs = ms / 1000
    if secs < 60: return f"{secs:.1f}s"
    mins = secs / 60
    return f"{mins:.1f} min"


def _git_commit_hash() -> str:
    """Best-effort: read `git rev-parse HEAD` if the skill is in a git repo."""
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.check_output(
            ["git", "-C", str(here), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return out[:12] if out else "unversioned"
    except Exception:
        return "unversioned"


def _load_event_contracts() -> dict:
    """Load references/event_contracts.json once for the schema-contract rule."""
    here = Path(__file__).resolve().parent
    contracts_path = here.parent / "references" / "event_contracts.json"
    try:
        with open(contracts_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"events": {}, "_critical_events": []}


def _reconciliation_rules(pages: list[dict], fb: FindingBuilder) -> None:
    """Cross-source reconciliation:
       - dataLayer push without /g/collect beacon → EVENT_PUSHED_BUT_NOT_SENT
       - /g/collect beacon without dataLayer push → EVENT_SENT_WITHOUT_DATALAYER
       - cid inconsistent across /g/collect requests → GA4_CLIENT_ID_INCONSISTENT
       - transport_url configured but beacons go to Google directly → SGTM_NOT_ACTUALLY_USED
    """
    for p in pages:
        snap = _best(p)
        events = (snap.get("events") or {}).get("events_seen") or []
        for slot in events:
            name = slot.get("event_name") or ""
            sources = set(slot.get("sources") or [])
            if "dataLayer" in sources and "network" not in sources and name not in {"gtm.js", "gtm.dom", "gtm.load"}:
                fb.add("EVENT_PUSHED_BUT_NOT_SENT",
                    title="Event pushed to dataLayer but no network beacon was captured",
                    category="Reconciliation",
                    description=("A `dataLayer.push` for this event was observed but no matching "
                                 "request to GA4's `/g/collect` endpoint was captured within the "
                                 "audit window. The tag fired in code but the network request "
                                 "didn't happen, usually a blocking trigger, a consent gate that "
                                 "wasn't released, or a `transport_url` misconfiguration."),
                    recommendation=("Open GTM Preview Mode and walk through the page. For each push "
                                    "of this event, confirm the corresponding GA4 Event tag fires "
                                    "(green tick). If it doesn't fire, check trigger conditions; if "
                                    "it does fire but no network request appears, check Consent Mode "
                                    "state and any custom `transport_url` configured on the GA4 Configuration tag."),
                    severity="High",
                    url=p["url"], detail=f"Event `{name}` pushed to dataLayer; no /g/collect beacon observed.",
                    confidence="Observed")
            elif "network" in sources and "dataLayer" not in sources and name not in {"page_view"}:
                fb.add("EVENT_SENT_WITHOUT_DATALAYER",
                    title="GA4 beacon fired for an event with no corresponding dataLayer push",
                    category="Reconciliation",
                    description=("A `/g/collect` request fired with this event_name, but no "
                                 "matching dataLayer push was observed. This is typically Enhanced "
                                 "Measurement firing (which sends events directly via the GA4 "
                                 "library without writing to dataLayer). Useful to log so analysts "
                                 "know the provenance of the event."),
                    recommendation=("Confirm in GA4 → Admin → Data Streams → your stream → Enhanced "
                                    "measurement that the corresponding option is intentionally on. "
                                    "If the event should come from your GTM tag instead, disable the "
                                    "Enhanced Measurement option to avoid double-counting."),
                    severity="Medium",
                    url=p["url"], detail=f"Event `{name}` only observed in /g/collect, not in dataLayer.",
                    confidence="Inferred")

        # client_id consistency across /g/collect requests on this page
        ga4_hits = (snap.get("network") or {}).get("ga4_hits") or []
        cids = set()
        for h in ga4_hits:
            url = h.get("url") or ""
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(url).query)
                cid = (q.get("cid") or [None])[0]
                if cid: cids.add(cid)
            except Exception:
                continue
        if len(cids) > 1:
            fb.add("GA4_CLIENT_ID_INCONSISTENT",
                title="GA4 client_id (cid) differs across requests on the same page",
                category="Reconciliation",
                description=("More than one distinct `cid` value was observed in `/g/collect` "
                             "requests on the same page. This breaks session stitching. GA4 will "
                             "treat each cid as a separate user, inflating user counts and "
                             "fragmenting attribution."),
                recommendation=("Audit any custom GA4 Configuration tags that override the cid (e.g. "
                                "code passing `client_id` explicitly). Ensure the `_ga` cookie is "
                                "set with `domain: 'auto'` and is readable across all subdomains in "
                                "scope. Verify in DebugView that subsequent events on the same "
                                "session carry the same cid."),
                severity="Critical",
                url=p["url"], detail=f"{len(cids)} distinct cid values on one page: {', '.join(list(cids)[:3])}{'…' if len(cids) > 3 else ''}",
                confidence="Observed")

        # transport_url verification (sGTM configured but not actually used)
        cfg = snap.get("config") or {}
        transport_urls = []
        for c in cfg.get("configs") or []:
            tu = ((c.get("options") or {}).get("transport_url") or "").strip()
            if tu: transport_urls.append(tu)
        if transport_urls:
            google_hits = sum(1 for h in ga4_hits if "google-analytics.com" in (h.get("url") or "") or "analytics.google.com" in (h.get("url") or ""))
            if google_hits and not any(tu.replace("https://", "").rstrip("/") in (h.get("url") or "") for tu in transport_urls for h in ga4_hits):
                fb.add("SGTM_NOT_ACTUALLY_USED",
                    title="transport_url configured but beacons still go to Google",
                    category="Reconciliation",
                    description=(f"GA4 Configuration sets `transport_url: {transport_urls[0]}` but "
                                 "the network capture still shows `/g/collect` requests going "
                                 "directly to `google-analytics.com`. The server-side container is "
                                 "configured but the redirection isn't happening, either the "
                                 "client cannot reach the sGTM endpoint (CSP, DNS, CORS) or the "
                                 "transport_url is set after the first hit fires."),
                    recommendation=("Move the GA4 Configuration tag (with `transport_url`) to fire "
                                    "as the very first thing on the page, before any GA4 Event tags. "
                                    "Verify the sGTM endpoint is reachable from the browser (open it "
                                    "directly; expect a 200 with a tiny GIF or HTML). Check Content "
                                    "Security Policy allows the sGTM hostname."),
                    severity="High",
                    url=p["url"], detail=f"transport_url={transport_urls[0]}; {google_hits} beacons still to google-analytics.com.",
                    confidence="Observed")


def _schema_contract_rule(pages: list[dict], fb: FindingBuilder) -> None:
    """Check observed events against event_contracts.json, required params present?"""
    contracts = _load_event_contracts()
    contract_events = contracts.get("events") or {}
    critical = set(contracts.get("_critical_events") or [])
    item_required = set(contracts.get("item_required") or [])

    for p in pages:
        snap = _best(p)
        events = (snap.get("events") or {}).get("events_seen") or []
        for slot in events:
            name = slot.get("event_name") or ""
            contract = contract_events.get(name)
            if not contract: continue
            if slot.get("param_names") is None:
                continue  # parameters not readable on this capture; unverified, not missing
            required = set(contract.get("required") or [])
            seen = set(slot.get("param_names") or [])
            missing = required - seen
            if missing:
                sev = "High" if name in critical else "Medium"
                fb.add("GA4_EVENT_PARAM_MISSING",
                    title=f"GA4 event `{name}` is missing required parameter(s)",
                    category="GA4",
                    description=(f"Required parameter(s) `{', '.join(sorted(missing))}` were not "
                                 f"observed on the `{name}` event. Without them, GA4 still accepts "
                                 "the hit but the corresponding dimensions are blank in reports."),
                    recommendation=(f"Update the tag/template firing `{name}` to populate "
                                    f"`{', '.join(sorted(missing))}`."),
                    severity=sev,
                    url=p["url"], detail=f"Missing on `{name}`: {', '.join(sorted(missing))}",
                    confidence="Observed")


def _pii_rule(pages, fb):
    """Surface any PII-pattern matches found by the inspector."""
    for p in pages:
        snap = _best(p)
        pii = snap.get("pii") or {}
        hits = pii.get("hits") or []
        by_kind = defaultdict(list)
        for h in hits:
            by_kind[h.get("kind") or "?"].append(h)
        for kind, group in by_kind.items():
            wheres = sorted({h.get("where", "") for h in group})
            fb.add("PII_LEAK_IN_PARAMS",
                title=f"Possible PII ({kind}) detected in tracking surface",
                category="Compliance",
                description=(f"The runtime inspector detected {len(group)} substring(s) matching a "
                             f"{kind} pattern in places visible to analytics."),
                recommendation=(f"Inspect these locations and remove the PII at source: "
                                f"{', '.join(wheres[:5])}."),
                severity="Critical",
                url=p["url"],
                detail=f"{len(group)} {kind} match(es). Locations: {', '.join(wheres[:3])}",
                confidence="Inferred")


def _network_status_rule(pages, fb):
    for p in pages:
        codes = p.get("network_status_codes") or {}
        for url, code in codes.items():
            try: code_int = int(code)
            except (TypeError, ValueError): continue
            if code_int < 400: continue
            if any(n in url for n in ["/g/collect","facebook.com/tr","px.ads.linkedin.com",
                                       "analytics.tiktok.com","ct.pinterest.com","clarity.ms"]):
                fb.add("TRACKING_ENDPOINT_HTTP_ERROR",
                    title="Tracking endpoint returned an HTTP error",
                    category="Runtime errors",
                    description=f"A tracking request returned HTTP {code_int}.",
                    recommendation="Check for malformed payloads, ad-blocker rewriting, or sGTM errors.",
                    severity="Critical",
                    url=p["url"], detail=f"{url} -> HTTP {code_int}")


def _per_page_inventory(pages):
    rows = []
    for p in pages:
        snap = _best(p)
        ti = snap.get("tag_inventory") or {}
        consent = snap.get("consent") or {}
        v = _vendors_present(snap)
        other = sorted(v - {"Google Tag Manager","Google gtag.js (standalone)",
                            "Google Analytics 4","Google Ads","Floodlight / DoubleClick"})
        rows.append({
            "url": p["url"],
            "ga4_ids": ti.get("ga4_measurement_ids") or [],
            "gtm_ids": ti.get("gtm_containers") or [],
            "consent_mode_v2": bool(consent.get("v2_signals_present")),
            "other_vendors": other,
        })
    return rows


def _per_page_performance(pages):
    rows = []
    for p in pages:
        snap = _best(p)
        perf = snap.get("performance") or {}
        wv = perf.get("web_vitals") or {}
        rc = perf.get("resource_counts") or {}
        rows.append({
            "url": p["url"],
            "lcp": wv.get("lcp_ms"),
            "cls": wv.get("cls"),
            "inp_approx": wv.get("inp_ms_approx"),
            "analytics_requests": rc.get("analytics_related"),
            "total_requests": rc.get("total"),
        })
    return rows


def _executive_summary(pages, findings):
    """Plain-English summary for a marketing lead.

    House style: short sentences, no drama, no
    "(s)" pluralisation, no banned buzzwords. Say what was found and what it
    costs the reader. Credit what works.
    """
    counts = defaultdict(int)
    for f in findings:
        if f.get("positive"):
            continue
        counts[f["severity"]] += 1
    wins = [f["title"] for f in findings if f.get("positive")][:2]
    top = [f["title"] for f in findings
           if f["severity"] in ("Critical", "High") and not f.get("positive")][:2]

    def plural(n, word):
        return f"{n} {word}" if n == 1 else f"{n} {word}s"

    page_word = plural(len(pages), "page template")
    paragraphs = []

    if not counts["Critical"] and not counts["High"]:
        paragraphs.append(
            f"We tested {page_word} and found no critical or high-priority "
            "problems. Tracking on this site is in reasonable shape.")
    else:
        bits = []
        if counts["Critical"]:
            bits.append(plural(counts["Critical"], "critical issue"))
        if counts["High"]:
            bits.append(plural(counts["High"], "high-priority issue"))
        paragraphs.append(
            f"We tested {page_word} on this site and found {' and '.join(bits)}. "
            + ("The most important is: " + top[0] + "." if top else ""))

    lower = []
    if counts["Medium"]:
        lower.append(plural(counts["Medium"], "medium-priority item"))
    if counts["Low"]:
        lower.append(plural(counts["Low"], "lower-priority item"))
    if lower:
        paragraphs.append("There " + ("is " if sum(
            (counts["Medium"], counts["Low"])) == 1 else "are ")
            + " and ".join(lower) + " below the headline findings.")

    if wins:
        paragraphs.append("Credit where it is due: " + "; ".join(wins) + ".")

    paragraphs.append(
        "Every finding is backed by what the browser actually sent on the day "
        "of the test, with the pages it was seen on and a specific fix. Where a "
        "finding needs checking inside your GA4 or Google Ads account rather "
        "than in the browser, we say so.")
    return paragraphs


def _site_apparent_target_regions(site: str, pages: list) -> set:
    """Infer the site's apparent target market from TLD + Consent Mode region.
    Returns a set of 2-letter ISO country codes, possibly empty."""
    regions = set()
    if not site: return regions
    try:
        from urllib.parse import urlparse
        host = (urlparse(site).hostname or '').lower()
    except Exception:
        host = ''
    TLD_MAP = {
        '.co.uk': 'GB', '.org.uk': 'GB', '.ac.uk': 'GB', '.uk': 'GB',
        '.de': 'DE', '.fr': 'FR', '.es': 'ES', '.it': 'IT', '.nl': 'NL',
        '.pl': 'PL', '.ie': 'IE', '.se': 'SE', '.dk': 'DK', '.fi': 'FI',
        '.no': 'NO', '.ch': 'CH', '.at': 'AT', '.be': 'BE',
        '.com.au': 'AU', '.com.br': 'BR', '.co.jp': 'JP', '.co.kr': 'KR',
        '.ca': 'CA', '.us': 'US', '.mx': 'MX', '.in': 'IN', '.sg': 'SG',
    }
    for suffix, code in TLD_MAP.items():
        if host.endswith(suffix):
            regions.add(code)
            break
    # Consent Mode region targeting on any page
    for p in pages:
        snap = _best(p)
        for r in ((snap.get("consent") or {}).get("region_targeting") or []):
            r_up = str(r).upper()
            if r_up in {"EEA", "EU"}:
                regions.update({"DE","FR","IT","ES","NL","PL","BE","SE","DK","FI","IE","AT","PT","GR","CZ","RO","HU","BG","HR","SK","SI","LT","LV","EE","CY","LU","MT"})
            elif len(r_up) == 2:
                regions.add(r_up)
    return regions


def _geo_rule(payload: dict, pages: list, fb: FindingBuilder) -> None:
    geo = payload.get("_geo") or {}
    if not geo or not geo.get("ok") or not geo.get("country"):
        return  # nothing to compare against
    browser_country = geo["country"].upper()
    targets = _site_apparent_target_regions(payload.get("site") or "", pages)
    if targets and browser_country not in targets:
        fb.add("GEO_MISMATCH",
            title="Browser apparent geo differs from the site's apparent target market",
            category="Methodology",
            description=(f"The audit was run from a browser apparently located in "
                         f"{browser_country} (per ipinfo.io), but the site's apparent "
                         f"target market is {', '.join(sorted(targets)[:5])}"
                         f"{'…' if len(targets) > 5 else ''} (inferred from the TLD and "
                         "any Consent Mode `region` targeting). Findings that depend on "
                         "region-specific behaviour. Consent Mode v2 defaults, "
                         "geo-redirects, region-targeted tags, may not reflect what an "
                         "in-region visitor would see."),
            recommendation=(f"Re-run the audit from a Chrome session in {sorted(targets)[0]} "
                            "(via VPN, a remote browser, or an in-region team member). "
                            "Compare the two runs; differences are the geo-dependent layer."),
            severity="Medium",
            url=payload.get("site") or "",
            detail=f"Browser country: {browser_country}; target regions inferred: {', '.join(sorted(targets))}",
            confidence="Inferred")




# ---------------------------------------------------------------------------
# CRO rules, experimentation platform detection, microconversion taxonomy,
# funnel-stage-aware event expectations.
# ---------------------------------------------------------------------------

EXPERIMENT_PLATFORMS = {
    "Optimizely Web", "VWO", "AB Tasty", "Convert.com", "Kameleoon",
    "Adobe Target", "Dynamic Yield", "Monetate", "Mutiny",
    "Bloomreach Engagement (Exponea)", "Google Optimize (legacy - sunset Sep 2023)",
    "Statsig (server-side hint)", "LaunchDarkly (server-side hint)",
}
PERSONALISATION_PLATFORMS = {
    "Dynamic Yield", "Monetate", "Mutiny",
    "Bloomreach Engagement (Exponea)", "Adobe Target",
}

# Map template_label -> expected funnel-stage event names (one-of).
FUNNEL_STAGE_EXPECTATIONS = {
    "Homepage":   {"page_view", "scroll"},
    "Category":   {"view_item_list", "select_item"},
    "Product":    {"view_item", "add_to_cart"},
    "Cart":       {"view_cart", "begin_checkout"},
    "Checkout":   {"begin_checkout", "add_shipping_info", "add_payment_info"},
    "Thank you":  {"purchase"},
    "Sign up":    {"sign_up", "form_submit"},
    "Login":      {"login"},
    "Contact":    {"generate_lead", "form_submit"},
    "Pricing":    {"select_promotion", "view_promotion", "begin_checkout"},
    "Blog post":  {"page_view", "scroll"},
}

# Microconversions, leading-indicator events that lead-gen and content sites
# should at minimum be tracking. If GA4 is firing but ZERO of these appear, we
# flag MICROCONVERSION_NOT_TRACKED.
MICROCONVERSION_EVENTS = {
    "scroll", "click", "file_download", "video_start", "video_progress",
    "view_search_results", "share", "subscribe", "join_group",
    "form_start", "form_submit",
    "add_to_wishlist", "view_item", "select_item",
    "request_demo", "watch_demo", "download_pdf", "view_pricing",
}


def _cro_rules(pages: list, fb: FindingBuilder) -> None:
    """Experimentation, microconversion, and funnel-stage rules."""
    # Detect experiment + personalisation platforms across all pages
    experiment_platforms_seen = set()
    personalisation_platforms_seen = set()
    any_exposure_event = False
    any_ga4 = False
    all_observed_events = set()
    for p in pages:
        snap = _best(p)
        any_ga4 = any_ga4 or bool((snap.get("tag_inventory") or {}).get("ga4_measurement_ids"))
        v_present = _vendors_present(snap)
        experiment_platforms_seen |= (v_present & EXPERIMENT_PLATFORMS)
        personalisation_platforms_seen |= (v_present & PERSONALISATION_PLATFORMS)
        # Exposure events: from dataLayer or GA4 /g/collect
        exp = snap.get("experiments") or {}
        if exp.get("exposures") or exp.get("ga4_exposure_events_observed"):
            any_exposure_event = True
        for slot in ((snap.get("events") or {}).get("events_seen") or []):
            all_observed_events.add(slot.get("event_name") or "")

    # 1. Experiment platform loaded but no exposure event observed
    if experiment_platforms_seen and not any_exposure_event:
        for p in pages:
            fb.add("EXPERIMENT_PLATFORM_NO_EXPOSURE_EVENT",
                title="Experimentation platform loaded but no exposure event observed",
                category="Experimentation",
                description=("Detected " + ", ".join(sorted(experiment_platforms_seen)) +
                             " on this site, but no `experiment_impression` (or platform-specific "
                             "exposure event) was observed in dataLayer or in GA4's `/g/collect` "
                             "stream. Without exposure events flowing into GA4, you cannot do "
                             "post-test cohort analysis in GA4, which is where most teams now "
                             "analyse experiments because the testing platform's built-in reports "
                             "are too shallow."),
                recommendation=("Wire the platform's exposure callback to push an event into "
                                "dataLayer like `dataLayer.push({event: 'experiment_impression', "
                                "experiment_id: 'X', variant_id: 'Y'})`. Add a GTM tag firing on "
                                "that event to send a GA4 event with `experiment_id` and "
                                "`variant_id` as custom dimensions registered in GA4 Admin."),
                severity="High",
                url=p["url"],
                detail=("Platform(s) detected: " + ", ".join(sorted(experiment_platforms_seen))),
                confidence="Observed")
            break  # one row of evidence is enough

    # 2. Experiment + personalisation collision
    if experiment_platforms_seen and personalisation_platforms_seen:
        for p in pages:
            fb.add("EXPERIMENT_PERSONALISATION_COLLISION",
                title="Both A/B testing and personalisation engines detected",
                category="Experimentation",
                description=("A user on this site can be simultaneously bucketed into an A/B test "
                             "AND served a personalisation rule from a different engine. The two "
                             "interventions confound each other, neither result is statistically "
                             "interpretable in isolation."),
                recommendation=("Audit the audience overlap between the two platforms. Either "
                                "hold personalisation steady while a test runs, or implement "
                                "mutually-exclusive audience targeting so each visitor is in at "
                                "most one intervention at a time."),
                severity="Medium",
                url=p["url"],
                detail=("Testing: " + ", ".join(sorted(experiment_platforms_seen)) +
                        " | Personalisation: " + ", ".join(sorted(personalisation_platforms_seen))),
                confidence="Inferred")
            break

    # 3. Funnel-stage-aware event expectations
    for p in pages:
        template = (p.get("template_label") or "").strip()
        if not template or template not in FUNNEL_STAGE_EXPECTATIONS:
            continue
        expected_set = FUNNEL_STAGE_EXPECTATIONS[template]
        snap = _best(p)
        observed_here = {s.get("event_name") for s in ((snap.get("events") or {}).get("events_seen") or [])}
        if not (expected_set & observed_here):
            fb.add("FUNNEL_STAGE_EVENT_MISSING",
                title=f"Expected event for `{template}` template was not observed",
                category="Funnel coverage",
                description=(f"This page is mapped to the `{template}` funnel stage, where at "
                             f"least one of {', '.join(sorted(expected_set))} would normally fire. "
                             f"None of those events were observed in any of the 3 captures."),
                recommendation=(f"On the `{template}` template, implement a GA4 tag for the "
                                f"primary expected event. Verify with GA4 DebugView before "
                                "declaring the funnel complete."),
                severity="High",
                url=p["url"],
                detail=f"Template: {template} | Expected one of: {', '.join(sorted(expected_set))} | Observed: {', '.join(sorted(observed_here)) or '(none)'}",
                confidence="Inferred")

    # 4. Microconversion coverage, only triggers when GA4 is firing but
    # the site has zero microconversion events across all pages
    if any_ga4 and not (all_observed_events & MICROCONVERSION_EVENTS):
        if len(pages) >= 2:
            for p in pages[:1]:
                fb.add("MICROCONVERSION_NOT_TRACKED",
                    title="No microconversion-shaped events observed across the site",
                    category="Funnel coverage",
                    description=("Hard conversions (purchase, sign_up, etc.) tell you whether the "
                                 "funnel works, but microconversions, scroll, click, file_download, "
                                 "video_start, view_search_results, form_start, add_to_wishlist, "
                                 "etc., tell you WHERE in the funnel users drop off. With none "
                                 "of these tracked, the team cannot do drop-off analysis or "
                                 "diagnose why conversion rate is what it is."),
                    recommendation=("Pick 3-5 microconversions relevant to your funnel and "
                                    "implement them. For lead-gen: form_start, form_submit, "
                                    "watch_demo, download_pdf. For ecommerce: scroll, view_item, "
                                    "select_item, add_to_wishlist, view_cart."),
                    severity="High",
                    url=p["url"],
                    detail="No microconversion events observed across audited pages.",
                    confidence="Inferred")




# ---------------------------------------------------------------------------
# Privacy-counsel rules. CCPA/UK-GDPR specifics, GPC honouring, legitimate-
# interest abuse, sensitive PI risk.
# ---------------------------------------------------------------------------

# Vendor -> data role + privacy policy URL. Used by exporters.py for the
# processor inventory CSV and by the LI rule below.
VENDOR_ROLE_MAP = {
    "Google Analytics 4":              {"role": "Joint controller (per CJEU C-101/01 reading)", "policy": "https://policies.google.com/privacy"},
    "Google Tag Manager":              {"role": "Processor",          "policy": "https://policies.google.com/privacy"},
    "Google Ads":                      {"role": "Joint controller",   "policy": "https://policies.google.com/privacy"},
    "Floodlight / DoubleClick":        {"role": "Joint controller",   "policy": "https://policies.google.com/privacy"},
    "Meta (Facebook) Pixel":           {"role": "Joint controller",   "policy": "https://www.facebook.com/policy.php"},
    "LinkedIn Insight":                {"role": "Joint controller",   "policy": "https://www.linkedin.com/legal/privacy-policy"},
    "TikTok Pixel":                    {"role": "Joint controller",   "policy": "https://www.tiktok.com/legal/privacy-policy"},
    "Pinterest Tag":                   {"role": "Joint controller",   "policy": "https://policy.pinterest.com/en/privacy-policy"},
    "X (Twitter) Pixel":               {"role": "Joint controller",   "policy": "https://twitter.com/privacy"},
    "Snapchat Pixel":                  {"role": "Joint controller",   "policy": "https://snap.com/privacy/privacy-policy"},
    "Reddit Pixel":                    {"role": "Joint controller",   "policy": "https://www.reddit.com/policies/privacy-policy"},
    "Microsoft Clarity":               {"role": "Processor",          "policy": "https://privacy.microsoft.com/privacystatement"},
    "Hotjar":                          {"role": "Processor",          "policy": "https://www.hotjar.com/legal/policies/privacy/"},
    "FullStory":                       {"role": "Processor",          "policy": "https://www.fullstory.com/legal/privacy-policy/"},
    "Mouseflow":                       {"role": "Processor",          "policy": "https://mouseflow.com/legal/privacy/"},
    "Lucky Orange":                    {"role": "Processor",          "policy": "https://www.luckyorange.com/privacy.php"},
    "Crazy Egg":                       {"role": "Processor",          "policy": "https://www.crazyegg.com/privacy"},
    "Smartlook":                       {"role": "Processor",          "policy": "https://www.smartlook.com/help/privacy-statement/"},
    "Segment":                         {"role": "Processor",          "policy": "https://www.twilio.com/legal/privacy"},
    "Tealium":                         {"role": "Processor",          "policy": "https://tealium.com/privacy/"},
    "Adobe Launch / DTM":              {"role": "Processor",          "policy": "https://www.adobe.com/privacy/policy.html"},
    "mParticle":                       {"role": "Processor",          "policy": "https://www.mparticle.com/privacy-policy"},
    "Zoho (PageSense / SalesIQ / Analytics)": {"role": "Processor",   "policy": "https://www.zoho.com/privacy.html"},
    "HubSpot":                         {"role": "Processor",          "policy": "https://legal.hubspot.com/privacy-policy"},
    "Intercom":                        {"role": "Processor",          "policy": "https://www.intercom.com/legal/privacy"},
    "Drift":                           {"role": "Processor",          "policy": "https://www.drift.com/privacy-policy/"},
    "Optimizely Web":                  {"role": "Processor",          "policy": "https://www.optimizely.com/legal/privacy/"},
    "VWO":                             {"role": "Processor",          "policy": "https://vwo.com/privacy-policy/"},
    "AB Tasty":                        {"role": "Processor",          "policy": "https://www.abtasty.com/terms-of-use/"},
    "Convert.com":                     {"role": "Processor",          "policy": "https://www.convert.com/privacy/"},
    "Kameleoon":                       {"role": "Processor",          "policy": "https://www.kameleoon.com/en/privacy-policy"},
    "Adobe Target":                    {"role": "Processor",          "policy": "https://www.adobe.com/privacy/policy.html"},
    "Dynamic Yield":                   {"role": "Processor",          "policy": "https://www.dynamicyield.com/privacy-policy/"},
    "Monetate":                        {"role": "Processor",          "policy": "https://monetate.com/privacy-policy/"},
    "Mutiny":                          {"role": "Processor",          "policy": "https://www.mutinyhq.com/privacy"},
    "Bloomreach Engagement (Exponea)": {"role": "Processor",          "policy": "https://www.bloomreach.com/en/legal/privacy-policy"},
}


def _privacy_rules(payload: dict, pages: list, fb: FindingBuilder) -> None:
    """Privacy-counsel rules. GPC honouring, GPP/CCPA, LI abuse, sensitive PI."""
    geo = payload.get("_geo") or {}
    browser_country = (geo.get("country") or "").upper() if geo.get("ok") else ""

    for p in pages:
        snap = _best(p)
        priv = snap.get("privacy") or {}
        net = snap.get("network") or {}

        # 1. GPC set by user, but tracking tags fire anyway. Under CCPA/CPRA
        # in California a site MUST treat GPC as a valid opt-out signal for
        # sale/share of personal information.
        has_tracking = bool(
            (net.get("ga4_hits") or []) or (net.get("facebook_hits") or [])
            or (net.get("linkedin_hits") or []) or (net.get("tiktok_hits") or [])
        )
        if priv.get("gpc_signal") is True and has_tracking:
            fb.add("PRIVACY_GPC_NOT_HONOURED",
                title="Global Privacy Control is set but tracking tags fired anyway",
                category="Privacy",
                description=("The browser reports `navigator.globalPrivacyControl = true` (the "
                             "GPC opt-out signal), yet advertising / cross-context tracking tags "
                             "fired on this page. Under California's CCPA/CPRA the GPC signal is "
                             "treated as a valid opt-out of sale/share, continuing to fire ad "
                             "tags is a regulatory risk."),
                recommendation=("Wire your CMP to honour `navigator.globalPrivacyControl`. With "
                                "Google Consent Mode v2, that means defaulting `ad_user_data` and "
                                "`ad_personalization` to `denied` whenever GPC is true and the "
                                "user has not subsequently opted in. Re-run the audit from a "
                                "browser with GPC enabled to verify."),
                severity="Critical",
                url=p["url"], detail="navigator.globalPrivacyControl = true; tracking tags still fired.",
                confidence="Observed")

        # 2. GPP API missing where it's likely required. The IAB Global Privacy
        # Platform has superseded the patchwork of US-state signals (USP v1/v2,
        # GPP for California, Colorado, Connecticut, etc.). If the browser is
        # in the US (and especially CA), an absent __gpp is a meaningful gap.
        if browser_country == "US" and not priv.get("gpp_api_present") and has_tracking:
            fb.add("PRIVACY_GPP_MISSING_FOR_REGION",
                title="GPP (Global Privacy Platform) not detected for US-region traffic",
                category="Privacy",
                description=("The browser is apparently in the US but no `window.__gpp` function "
                             "was detected. US-state privacy laws (CA, CO, CT, VA, UT, and the "
                             "growing list) expect signal handling through IAB's GPP framework. "
                             "Without `__gpp` your CMP cannot communicate state-specific opt-outs "
                             "to downstream vendors."),
                recommendation=("Upgrade your CMP to a GPP-capable version (most major CMPs "
                                "support it as of 2024). Verify with the IAB GPP validator that "
                                "your site emits a valid GPP string carrying the right US-state "
                                "section IDs."),
                severity="High",
                url=p["url"], detail="No window.__gpp function detected.",
                confidence="Inferred")

        # 3. Legitimate interest abused for analytics. Google explicitly
        # requires CONSENT (not LI) for ad personalisation. If the TCF cache
        # shows purposes 3-4 (ad-related) granted under legitimateInterests
        # but NOT under consents, that's an LI abuse pattern.
        tcf = priv.get("tcf_consent_summary") or {}
        li_set = set(tcf.get("purposes_li") or [])
        co_set = set(tcf.get("purposes_consented") or [])
        ad_purposes_via_li_only = (li_set & {"3","4","5","6"}) - co_set
        if ad_purposes_via_li_only:
            fb.add("PRIVACY_LEGITIMATE_INTEREST_FOR_ADS",
                title="Advertising purposes claimed under legitimate interest (LI), not consent",
                category="Privacy",
                description=("The TCF v2 cache shows ad-related purposes granted only under "
                             f"`legitimateInterests` ({', '.join(sorted(ad_purposes_via_li_only))}). "
                             "Google's own policy requires CONSENT (not LI) for ad personalisation "
                             "and audience building. Vendors will silently drop the bid request, "
                             "and supervisory authorities have flagged this exact pattern in "
                             "enforcement actions."),
                recommendation=("Re-classify TCF purposes 3, 4, 5, 6, 7 (ad-related) so they are "
                                "obtained via consent rather than LI. Update the CMP banner copy "
                                "so the consent ask is clear, granular, and freely refusable. "
                                "Verify the new TC string with the IAB validator."),
                severity="High",
                url=p["url"],
                detail=f"Purposes via LI only: {', '.join(sorted(ad_purposes_via_li_only))}",
                confidence="Observed")

        # 4. Sensitive PI categories observed in the tracking surface. This is
        # a special-category-data risk under UK-GDPR Article 9.
        cats = priv.get("sensitive_pi_categories_seen") or []
        if cats:
            fb.add("PRIVACY_SENSITIVE_PI_RISK",
                title="Sensitive personal information categories detected in tracking surface",
                category="Privacy",
                description=(f"The runtime inspector found terms matching sensitive PI categories "
                             f"({', '.join(cats)}) in the dataLayer, URL, or beacon payloads. "
                             "Under UK-GDPR Article 9 these are special categories, collection "
                             "requires explicit consent and a more restrictive legal basis. Under "
                             "CCPA/CPRA these fall under Sensitive PI and trigger 'Limit Use of "
                             "Sensitive Personal Information' obligations."),
                recommendation=("Identify and remove the source. Common fixes: strip URL query "
                                "params before sending to analytics; hash any identifiers used "
                                "for advertising; never write form-field values to dataLayer; "
                                "use server-side processing for any necessary special-category "
                                "use case with an explicit Article 9 condition."),
                severity="Critical",
                url=p["url"],
                detail=f"Categories: {', '.join(cats)}",
                confidence="Inferred")



# ---------------------------------------------------------------------------
# Capture-and-claim rule enforcement (references/capture_and_claim_rules.md)
# ---------------------------------------------------------------------------

# Findings whose root cause lives inside GTM/GA4 account configuration. The
# browser can see the symptom but never the tag or trigger that caused it, so
# rule 4 caps them at "Needs verification".
ACCOUNT_CONFIG_FINDINGS = {
    "GA4_DOUBLE_LOAD_GTAG_AND_GTM", "GA4_DUPLICATE_EVENT_ON_ACTION",
    "ENHANCED_MEASUREMENT_DUPLICATE", "GTM_DUPLICATE_CONTAINER",
    "GA4_LIKELY_CONVERSIONS_UNVERIFIED", "GA4_NO_KEY_EVENTS_OBSERVED",
    "GA4_EVENT_PARAM_MISSING", "TAG_GATEWAY_BYPASSED",
}

# Rule 2: everything consent-shaped that a consented profile cannot support.
CONSENT_FINDING_PREFIXES = ("CONSENT_", "CMP_", "PRIVACY_GPC", "PRIVACY_GPP")


def collapse_dual_dispatch(hits: list[dict]) -> list[dict]:
    """Rule 1. Collapse GA4 dual dispatch into one logical hit.

    When ad consent is granted GA4 sends the SAME hit to
    *.google-analytics.com AND *.analytics.google.com. Two /g/collect requests
    sharing (_s, sid, dl) within ~100ms are ONE hit; GA4 counts them once and
    so must we. Counting them separately is what produced a false Critical
    "GA4 fires twice" finding.
    """
    out: list[dict] = []
    for h in hits or []:
        key = (h.get("seq"), h.get("session_id"), h.get("doc_location"),
               h.get("measurement_id"), h.get("event_name"))
        if not any(key[:3]):          # no fingerprint captured; cannot collapse
            out.append(h)
            continue
        merged = False
        for prev in out:
            pkey = (prev.get("seq"), prev.get("session_id"), prev.get("doc_location"),
                    prev.get("measurement_id"), prev.get("event_name"))
            if pkey != key:
                continue
            dt = abs((h.get("start_time_ms") or 0) - (prev.get("start_time_ms") or 0))
            ph, hh = (prev.get("host") or ""), (h.get("host") or "")
            different_endpoint_class = ph != hh
            if dt <= 120 and different_endpoint_class:
                prev.setdefault("_dual_dispatch_hosts", [ph]).append(hh)
                merged = True
                break
        if not merged:
            out.append(h)
    return out


def apply_capture_rules(payload: dict, pages: list[dict], findings: list[dict]) -> list[dict]:
    """Post-process findings for rules 2, 4 and 6."""
    clean = payload.get("clean_state")
    consent_verified = bool(payload.get("_consent_verified"))
    kept = []
    suppressed = 0
    for f in findings:
        fid = f.get("id", "")
        # Rule 2: a consented profile cannot support consent conclusions.
        if clean is False and fid.startswith(CONSENT_FINDING_PREFIXES):
            suppressed += 1
            continue
        # Rule 4: account-configuration causes cap at "Needs verification".
        if fid in ACCOUNT_CONFIG_FINDINGS and f.get("confidence") == "Observed":
            f["confidence"] = "Needs verification"
        # Rule 6: verified Consent Mode caps consent findings at High.
        if consent_verified and fid.startswith("CONSENT_") and f.get("severity") == "Critical":
            f["severity"] = "High"
            f["description"] = (f.get("description", "") + " Severity is capped at High because "
                                "Consent Mode was verified on this site; only personal data in a "
                                "request payload reaches Critical on this axis.").strip()
        kept.append(f)
    # Rule 6, one severity per issue: NO_OWNED_ANALYTICS_PLATFORM subsumes
    # GA4_NOT_DETECTED. Carrying both charges the same underlying fact twice.
    ids = {f.get("id") for f in kept}
    if "NO_OWNED_ANALYTICS_PLATFORM" in ids:
        kept = [f for f in kept if f.get("id") != "GA4_NOT_DETECTED"]

    if clean is False:
        kept.append({
            "id": "CONSENT_NOT_TESTABLE",
            "title": "Consent behaviour could not be tested on this run",
            "category": "Compliance",
            "description": ("The browser profile used had already stored a consent choice for "
                            "this site, so every observation was made post-consent. Consent "
                            "behaviour, Consent Mode classification and pre-consent tag "
                            "behaviour are therefore untestable here. This run supports tag "
                            "inventory observations only. All consent findings and ratings "
                            f"have been suppressed ({suppressed} withheld)."),
            "recommendation": ("Re-run with a clean consent state: clear the site's cookies and "
                               "storage, or use a fresh incognito context, and confirm the "
                               "banner appears on first load before the first capture."),
            "severity": "Info", "positive": False, "confidence": "Observed",
            "evidence": [{"url": (pages[0]["url"] if pages else ""),
                          "detail": "clean_state was false for this run."}],
        })
    return kept


def _merged_view(page: dict) -> dict:
    """Union of the pre- and post-consent snapshots.

    `_best()` returns ONE snapshot. Inventory-style questions ("does this site
    have GA4 at all?") must never be answered from a single partial capture: a
    thin post-consent snapshot would otherwise blank out what the pre-consent
    pass clearly saw, and rule 7 turns that into a headline Critical.
    """
    out: dict = {}
    for key in ("pre_consent", "post_consent"):
        snap = page.get(key)
        if not isinstance(snap, dict):
            continue
        for section, value in snap.items():
            if not isinstance(value, dict):
                if section not in out or not out.get(section):
                    out[section] = value
                continue
            merged = dict(out.get(section) or {})
            for k, v in value.items():
                if v in (None, [], {}, "") and merged.get(k) not in (None, [], {}, ""):
                    continue
                merged[k] = v
            out[section] = merged
    return out



def _google_measurement_hits(snap: dict) -> list:
    """Collection requests only. Rule 5 excludes the GTM container and the
    gtag.js loader themselves: loading the library is not measurement."""
    net = (snap or {}).get("network") or {}
    hits = list(net.get("ga4_hits") or [])
    for h in (net.get("google_ads_hits") or []):
        u = (h.get("url") or "")
        if "/collect" in u or "/pagead/" in u or "/rmkt/" in u:
            hits.append(h)
    return hits


def _consent_state_rules(payload: dict, pages: list[dict], fb: FindingBuilder) -> None:
    """Rule 5: four-state Consent Mode classification. Never 'absent'."""
    if payload.get("clean_state") is False:
        return  # rule 2: not testable, handled by apply_capture_rules

    for p in pages:
        pre = p.get("pre_consent") or {}
        post = p.get("post_consent") or {}
        best = _merged_view(p)
        cons = (best.get("consent") or {})
        if not cons:
            continue
        detected = bool(cons.get("consent_mode_detected"))
        default_denied = bool(cons.get("default_consent_call_found"))
        pre_hits = _google_measurement_hits(pre)
        post_hits = _google_measurement_hits(post) or _google_measurement_hits(best)
        pre_gcs = {(h.get("gcs") or "") for h in pre_hits if h.get("gcs")}
        post_gcs = {(h.get("gcs") or "") for h in post_hits if h.get("gcs")}
        cookies_before = bool((pre.get("consent") or {}).get("google_cookies_before_choice"))

        cookieless_ping = bool(pre_hits) and any(g.startswith("G10") for g in pre_gcs)
        clean_upgrade = any(g.startswith("G11") for g in post_gcs)

        if cookieless_ping and clean_upgrade and not cookies_before:
            state, label = "advanced_verified_cookieless", "Advanced, verified cookieless"
        elif detected and not pre_hits and default_denied and clean_upgrade:
            state, label = "basic", "Basic"
        elif detected:
            state, label = "advanced_not_verified", "Advanced, not verified"
        else:
            state, label = "not_classifiable", "Not classifiable from this scan"

        if state in ("advanced_verified_cookieless", "basic"):
            payload["_consent_verified"] = True

        if state == "basic":
            desc = ("Consent Mode is running in Basic mode: a denied default is present, no "
                    "Google measurement requests fire before the visitor chooses, and hits "
                    "upgrade to granted after acceptance. Consent gates correctly, but because "
                    "no cookieless pings are sent before consent, Google has nothing to model "
                    "from. Visitors who decline are never recorded at all, so there are no "
                    "modelled conversions. Basic is a legitimate, working and more "
                    "privacy-conservative configuration than Advanced.")
            rec = ("No fix required. If you want modelled conversions for visitors who decline, "
                   "that means moving to Advanced mode, which sends cookieless pings "
                   "pre-consent. That is a decision for your privacy stance, not a defect.")
            positive = True
        elif state == "advanced_verified_cookieless":
            desc = ("Consent Mode is running in Advanced mode and verified cookieless: "
                    "pre-consent requests carry a denied signal, no Google cookies are written "
                    "before the choice, and hits upgrade cleanly after acceptance. This is the "
                    "configuration Google's modelled conversions depend on.")
            rec = "No action needed. Re-verify after any CMP or container change."
            positive = True
        elif state == "advanced_not_verified":
            missing = []
            if not cookieless_ping:
                missing.append("no denied-signal (gcs=G100) request was seen pre-consent")
            if not clean_upgrade:
                missing.append("no clean upgrade to gcs=G111 was seen after acceptance")
            if cookies_before:
                missing.append("Google cookies were present before the choice was made")
            desc = ("Consent Mode signals are present, but this scan could not verify the "
                    "cookieless behaviour: " + "; ".join(missing) + ".")
            rec = ("Confirm in Tag Assistant and GA4 DebugView with a clean profile. Watch the "
                   "gcs parameter move from G100 before consent to G111 after acceptance.")
            positive = False
        else:
            desc = ("Consent Mode could not be classified from this scan. This is a limit of "
                    "what the browser exposed on the pages tested, not a statement that Consent "
                    "Mode is absent.")
            rec = ("Confirm with Tag Assistant: connect to the site, load a page with a clean "
                   "profile, and inspect the gcs parameter on the first Google request before "
                   "and after the consent choice.")
            positive = False

        fb.add("CONSENT_MODE_CLASSIFICATION",
            title=f"Consent Mode classification: {label}",
            category="Compliance", description=desc, recommendation=rec,
            severity="Info", positive=positive,
            confidence="Observed" if state != "not_classifiable" else "Needs verification",
            url=p["url"],
            detail=(f"State: {label}. Pre-consent measurement requests: {len(pre_hits)}. "
                    f"gcs seen pre: {sorted(pre_gcs) or 'none'}; post: {sorted(post_gcs) or 'none'}."))


def _owned_analytics_rules(pages: list[dict], fb: FindingBuilder) -> None:
    """Rule 7: vendor-embedded analytics, and the no-owned-platform headline."""
    for p in pages:
        snap = _merged_view(p)
        ti = snap.get("tag_inventory") or {}
        net = snap.get("network") or {}
        vend = snap.get("vendors") or {}
        sp = net.get("snowplow") or {}

        owned = bool(ti.get("ga4_measurement_ids") or ti.get("universal_analytics_ids"))
        if sp.get("ownership") == "owned":
            owned = True
        for name in ("Adobe Analytics", "Matomo", "Piwik PRO", "Plausible", "Fathom"):
            if (vend.get(name) or {}).get("present"):
                owned = True

        if sp.get("ownership") == "vendor_embedded":
            hosts = sorted(set((sp.get("vendor_hosts") or [])
                               + [h.get("host") for h in (sp.get("collector_hits") or []) if h.get("host")]))
            fb.add("VENDOR_EMBEDDED_ANALYTICS",
                title="Snowplow present, but it belongs to a vendor",
                category="Analytics platform",
                description=("A Snowplow tracker is running on this site, but the tracker script "
                             "and its collector are both on a vendor's domain and there are no "
                             "first-party _sp_id or _sp_ses cookies. This is telemetry powering "
                             "a product the client rents, not an analytics asset they own. The "
                             "data lands in the vendor's pipeline. The client cannot query it, "
                             "model it, or attribute against it."),
                recommendation=("Do not count this as the site's analytics platform. Ask the "
                                "client whether they have their own Snowplow collector and "
                                "warehouse. If the answer is that a vendor mentioned Snowplow, "
                                "they have no analytics platform of their own."),
                severity="Info", confidence="Observed", url=p["url"],
                detail=f"Vendor-hosted Snowplow. Hosts: {', '.join(h for h in hosts if h) or 'vendor domain'}.")

        if not owned:
            ads = bool(net.get("google_ads_hits") or (vend.get("Meta (Facebook) Pixel") or {}).get("present")
                       or (vend.get("Microsoft Ads UET") or {}).get("present"))
            desc = ("No site-owned analytics platform was observed on this page. No GA4 "
                    "measurement ID, no Universal Analytics property, and no first-party "
                    "analytics collector of any kind.")
            if ads:
                desc += (" Ad platforms are being fed audience and conversion signal while the "
                         "business collects nothing of its own to judge that spend against. "
                         "There is no feedback loop: nothing to attribute against, nothing to "
                         "optimise toward, and no way to check what the ad platforms report.")
            fb.add("NO_OWNED_ANALYTICS_PLATFORM",
                title="No site-owned analytics platform is running",
                category="Analytics platform", description=desc,
                recommendation=("Install GA4 with a proper ecommerce or lead dataLayer, via the "
                                "existing GTM container. Verify in GA4 DebugView before relying "
                                "on any number it produces."),
                severity="Critical", confidence="Observed", url=p["url"],
                detail="No GA4, UA, or first-party analytics collector detected.")


def _fairness_positives(pages: list[dict], fb: FindingBuilder) -> None:
    """Rule 8: record the positives the scan actually observed."""
    ids_by_page = []
    for p in pages:
        snap = _merged_view(p)
        cons = snap.get("consent") or {}
        perf = (snap.get("performance") or {}).get("web_vitals") or {}
        ti = snap.get("tag_inventory") or {}
        ids_by_page.append(tuple(sorted(ti.get("ga4_measurement_ids") or [])))

        if cons.get("cmps_detected"):
            fb.add("CMP_WORKING",
                title="A consent management platform is present and wired to Google tags",
                category="Compliance",
                description=(f"{', '.join(cons['cmps_detected'])} was detected, and consent "
                             "signals reach the Google tags rather than sitting decoratively on "
                             "the page."),
                recommendation="No action needed.",
                severity="Info", positive=True, confidence="Observed", url=p["url"],
                detail=f"CMP: {', '.join(cons['cmps_detected'])}.")

        if cons.get("v2_signals_present") and cons.get("default_consent_call_found"):
            raw = cons.get("default_state_raw") or {}
            denied = [k for k, v in raw.items()
                      if isinstance(v, dict) and v.get("def") is False]
            if denied:
                fb.add("CONSENT_MODE_V2_CORRECT_DEFAULTS",
                    title="Consent Mode v2 defaults to denied across all signals",
                    category="Compliance",
                    description=("All four Consent Mode v2 signals are present and default to "
                                 "denied before the visitor chooses, which is the behaviour "
                                 "Google requires and most sites get wrong."),
                    recommendation="No action needed. Re-verify after any CMP change.",
                    severity="Info", positive=True, confidence="Observed", url=p["url"],
                    detail=f"Denied by default: {', '.join(sorted(denied))}.")

        lcp, cls = perf.get("lcp_ms"), perf.get("cls")
        if isinstance(lcp, (int, float)) and lcp <= 2500 and (cls is None or (isinstance(cls, (int, float)) and cls <= 0.1)):
            fb.add("CORE_WEB_VITALS_PASSING",
                title="Core Web Vitals are passing on this page",
                category="Performance",
                description="Largest Contentful Paint and Cumulative Layout Shift are both inside Google's good thresholds.",
                recommendation="No action needed.",
                severity="Info", positive=True, confidence="Observed", url=p["url"],
                detail=f"LCP {lcp}ms, CLS {cls}.")

    non_empty = [i for i in ids_by_page if i]
    if len(non_empty) > 1 and len(set(non_empty)) == 1:
        fb.add("GA4_IDS_CONSISTENT",
            title="The same GA4 measurement ID is used consistently across templates",
            category="GA4",
            description=("Every template tested reports to the same measurement ID, so sessions "
                         "and users stay joined across the journey."),
            recommendation="No action needed.",
            severity="Info", positive=True, confidence="Observed",
            url=pages[0]["url"], detail=f"Measurement ID: {', '.join(non_empty[0])}.")


NON_GOOGLE_PRE_CONSENT = {
    "Meta (Facebook) Pixel": ("facebook.com",),
    "Microsoft Ads UET": ("bat.bing.com",),
    "TikTok Pixel": ("analytics.tiktok.com",),
    "LinkedIn Insight": ("px.ads.linkedin.com",),
    "Pinterest Tag": ("ct.pinterest.com",),
    "Snapchat Pixel": ("tr.snapchat.com",),
    "Reddit Pixel": ("alb.reddit.com",),
    "Microsoft Clarity": ("clarity.ms",),
    "Hotjar": ("hotjar.com", "hotjar.io"),
}


def _pre_consent_vendor_rule(payload: dict, pages: list, fb: FindingBuilder) -> None:
    """Non-Google tags sending data, or setting cookies, before a consent choice.

    Only runs with a clean consent state and a banner on screen. Google tags
    are covered by the Consent Mode classification instead, because Consent
    Mode lets them send cookieless pings by design.
    """
    if payload.get("clean_state") is False:
        return
    for p in pages:
        pre = p.get("pre_consent") or {}
        cons = pre.get("consent") or {}
        if not (cons.get("banner_text_visible") or cons.get("cmps_detected")):
            continue
        reqs = (pre.get("network") or {}).get("requests") or []
        fired = []
        for name, hosts in NON_GOOGLE_PRE_CONSENT.items():
            n = sum(1 for r in reqs if r.get("role") == "measurement"
                    and any(h in (r.get("vendor") or "") for h in hosts))
            if n:
                fired.append(f"{name} ({n} request{'s' if n > 1 else ''})")
        vendor_cookies = (pre.get("cookies") or {}).get("vendor") or []
        if not fired and not vendor_cookies:
            continue
        detail = "; ".join(fired) if fired else ""
        if vendor_cookies:
            detail += ("; " if detail else "") + "cookies set: " + ", ".join(vendor_cookies[:6])
        fb.add("NON_GOOGLE_TAG_BEFORE_CONSENT",
            title="Non-Google tags sent data before a consent choice",
            category="Consent",
            description=("With the cookie banner still showing and no choice made, these "
                         "platforms sent requests or set cookies. Unlike Google tags under "
                         "Consent Mode, they have no cookieless mode, so whatever they send "
                         "before a choice is a full tracking request."),
            recommendation=("Check how each tag is triggered in your tag manager or plugin, and "
                            "whether your consent platform should hold it until the visitor "
                            "accepts. Whether firing before consent is acceptable for your site "
                            "is a question for your privacy adviser."),
            severity="High", url=p["url"], detail=detail, confidence="Observed")


def aggregate(payload):
    pages = payload.get("pages") or []
    # probe.js snapshots are mapped onto the shape the rules read.
    from normalise_probe import normalise
    for _p in pages:
        for _key in ("pre_consent", "post_consent"):
            if isinstance(_p.get(_key), dict):
                _p[_key] = normalise(_p[_key])
    # Rule 1: collapse GA4 dual dispatch before any duplicate rule sees the hits.
    for _p in pages:
        for _key in ("pre_consent", "post_consent"):
            _snap = _p.get(_key)
            if isinstance(_snap, dict):
                _net = _snap.get("network")
                if isinstance(_net, dict) and _net.get("ga4_hits"):
                    _net["ga4_hits"] = collapse_dual_dispatch(_net["ga4_hits"])
    fb = FindingBuilder()
    _pre_consent_vendor_rule(payload, pages, fb)
    _ga4_rules(pages, fb)
    _gtm_rules(pages, fb)
    _consent_rules(pages, fb)
    _sgtm_rules(pages, fb)
    _tag_gateway_rules(payload, pages, fb)
    _consent_state_rules(payload, pages, fb)
    _owned_analytics_rules(pages, fb)
    _fairness_positives(pages, fb)
    _pixel_rules(pages, fb)
    _overlap_rules(pages, fb)
    _performance_rules(pages, fb)
    _console_error_rule(pages, fb)
    _network_status_rule(pages, fb)
    _ecommerce_rules(pages, fb)
    _event_inventory_rules(pages, fb)
    _cross_domain_rule(pages, fb)
    _pii_rule(pages, fb)
    _reconciliation_rules(pages, fb)
    _schema_contract_rule(pages, fb)
    _geo_rule(payload, pages, fb)
    _cro_rules(pages, fb)
    _privacy_rules(payload, pages, fb)
    findings = apply_capture_rules(payload, pages, fb.to_list())

    run_id = str(uuid.uuid4())
    skill_commit_hash = _git_commit_hash()
    audit_log = []
    total_ga4_hits = 0
    for p in pages:
        snap = _best(p)
        meta = (snap or {}).get("meta") or {}
        net = (snap or {}).get("network") or {}
        ua = (meta.get("user_agent") or "")[:200]
        audit_log.append({
            "url": p["url"],
            "run_id": run_id,
            "skill_commit_hash": skill_commit_hash,
            "user_agent": ua[:120],
            "chrome_version": _parse_chrome_version(ua),
            "effective_connection_type": meta.get("effective_connection_type") or "unknown",
            "viewport": meta.get("viewport") or {},
            "captured_at_ms": meta.get("timestamp_ms"),
            "captured_at_iso": _iso_from_ms(meta.get("timestamp_ms")),
            "ready_state": meta.get("ready_state"),
            "delayed_capture": bool(meta.get("delayed_capture")),
            "third_party_host_count": len(net.get("third_party_hosts") or []),
        })
        total_ga4_hits += len(net.get("ga4_hits") or [])

    timestamps = [r.get("captured_at_ms") for r in audit_log if r.get("captured_at_ms")]
    wall_clock_ms = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else 0
    _geo = payload.get("_geo") or {}
    audit_cost_summary = {
        "wall_clock_ms": wall_clock_ms,
        "wall_clock_human": _human_ms(wall_clock_ms),
        "pages_inspected": len(pages),
        "ga4_collect_requests_captured": total_ga4_hits,
        "run_id": run_id,
        "skill_commit_hash": skill_commit_hash,
        "browser_geo_country": (_geo.get("country") if _geo.get("ok") else None),
        "browser_geo_region": (_geo.get("region") if _geo.get("ok") else None),
        "browser_geo_source": (_geo.get("source") if _geo else None),
    }

    return {
        "site": payload.get("site"),
        "pages_audited": len(pages),
        "pages_audited_list": [
            {"url": p["url"], "template_label": p.get("template_label", "")} for p in pages
        ],
        "findings": findings,
        "audit_log": audit_log,
        "audit_cost_summary": audit_cost_summary,
        "executive_summary": _executive_summary(pages, findings),
        "methodology": [
            "Runtime audit via the Claude in Chrome extension. Two passes per page: "
            "pre-consent (ideally incognito) and post-consent.",
            "Findings were generated by deterministic rules (aggregate_findings.py).",
        ],
        "per_page_inventory": _per_page_inventory(pages),
        "per_page_performance": _per_page_performance(pages),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-page", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--geo", help="Optional path to geo_lookup.py output JSON.")
    ap.add_argument("--claimed-tag-gateway", action="store_true",
                    help="The site owner claims Google tag gateway for advertisers "
                         "is enabled. Turns a non-detection into an explicit High "
                         "finding instead of silence.")
    args = ap.parse_args()
    with open(args.per_page, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if args.claimed_tag_gateway:
        payload["claimed_tag_gateway"] = True
    if args.geo:
        try:
            with open(args.geo, "r", encoding="utf-8") as f:
                payload["_geo"] = json.load(f)
        except Exception as e:
            sys.stderr.write(f"WARN: could not read --geo {args.geo}: {e}\n")
    aggregated = aggregate(payload)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2)
    print(f"Aggregated {len(aggregated['findings'])} findings -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
