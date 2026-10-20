#!/usr/bin/env python3
"""normalise_probe.py — map probe.js output onto the snapshot shape the rules read.

probe.js returns a compact, redaction-resistant snapshot (ids, dataLayer,
consent, cookies, vendors, network.requests, seo, perf). The rules in
aggregate_findings.py read a richer shape (tag_inventory, network.ga4_hits,
events.events_seen, consent.consent_mode_detected, vendors by name, ...).
This module converts one into the other, so the rules run on what the probe
actually captured. Fields the probe cannot see are left empty, which means the
rules that depend on them stay silent rather than reporting an absence.

aggregate_findings.py calls normalise() on every snapshot that looks like
probe.js output. Already-normalised snapshots pass through unchanged.
"""

from __future__ import annotations
import re
from urllib.parse import unquote, urlencode

KEY_EVENT_CANDIDATES = {
    "purchase", "add_to_cart", "add_payment_info", "add_shipping_info",
    "begin_checkout", "view_item", "view_item_list", "select_item", "sign_up",
    "login", "generate_lead", "qualify_lead", "working_lead",
    "submit_application", "subscribe", "request_quote", "book_appointment"}
ENHANCED_MEASUREMENT_EVENTS = {
    "scroll", "click", "file_download", "view_search_results", "video_start",
    "video_progress", "video_complete", "form_start", "form_submit"}
GTM_INTERNAL = {"gtm.js", "gtm.dom", "gtm.load", "gtm.init", "gtm.init_consent",
                "consent", "config", "js", "set", "event", "gtag.config"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+44|\b0)7\d{9}\b")

# Vendor name -> (window globals, host patterns). Names match the rules.
VENDORS = {
    "Google Tag Manager": ((), ()),          # filled from ids below
    "Google Ads": ((), ("googleadservices.com", "doubleclick.net")),
    "Meta (Facebook) Pixel": (("fbq",), ("facebook.net", "facebook.com")),
    "TikTok Pixel": (("ttq",), ("tiktok.com",)),
    "LinkedIn Insight": (("lintrk",), ("licdn.com", "ads.linkedin.com")),
    "Microsoft Ads UET": (("uetq",), ("bat.bing.com",)),
    "Pinterest Tag": (("pintrk",), ("pinimg.com", "ct.pinterest.com")),
    "Snapchat Pixel": (("snaptr",), ("sc-static.net", "tr.snapchat.com")),
    "Reddit Pixel": (("rdt",), ("redditstatic.com", "alb.reddit.com")),
    "X (Twitter) Pixel": (("twq",), ("ads-twitter.com", "analytics.twitter.com")),
    "Microsoft Clarity": (("clarity",), ("clarity.ms",)),
    "Hotjar": (("hj",), ("hotjar.com", "hotjar.io")),
    "FullStory": (("FS",), ("fullstory.com",)),
    "Mouseflow": (("_mfq",), ("mouseflow.com",)),
    "Lucky Orange": ((), ("luckyorange.com", "luckyorange.net")),
    "Smartlook": ((), ("smartlook.com",)),
    "Segment": ((), ("segment.com", "segment.io")),
    "Tealium": (("utag",), ("tiqcdn.com",)),
    "HubSpot": (("_hsq",), ("hs-scripts.com", "hs-analytics.net", "hubspot.com")),
    "Klaviyo": (("klaviyo",), ("klaviyo.com",)),
}


def _ga4_param_names(raw):
    """GA4 wire names -> event parameter names (cu -> currency, pr1 -> items)."""
    out = set()
    for k in raw or []:
        if k == "cu":
            out.add("currency")
        elif re.fullmatch(r"pr\d+", k):
            out.add("items")
        elif k.startswith(("ep.", "epn.")):
            out.add(k.split(".", 1)[1])
    return out


def looks_like_probe(snap) -> bool:
    return (isinstance(snap, dict) and "ids" in snap
            and isinstance(snap.get("network"), dict)
            and "requests" in snap["network"] and "tag_inventory" not in snap)


def _uniq(xs):
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def _segs(r):
    return [s for s in (r.get("segments") or []) if isinstance(s, str)]


def _url(r):
    host = r.get("vendor") or ""
    if host == "(site origin)":
        host = "first-party"
    path = "/" + "/".join(s if isinstance(s, str) else "x" for s in r.get("segments") or [])
    q = urlencode({k: v for k, v in (r.get("params") or {}).items() if v is not None})
    return f"https://{host}{path}" + (f"?{q}" if q else "")


def normalise(snap: dict) -> dict:
    if not looks_like_probe(snap):
        return snap
    ids = snap.get("ids") or {}
    dlr = snap.get("dataLayer") or {}
    con = snap.get("consent") or {}
    cookies = snap.get("cookies") or {}
    vend = snap.get("vendors") or {}
    net = snap.get("network") or {}
    perf = snap.get("perf") or {}
    reqs = net.get("requests") or []
    runtime = ids.get("runtimeContainers") or []

    # ---- network ----
    ga4_hits, ads_hits, fb_hits, li_hits, tt_hits, fp_collect, fp_loader = [], [], [], [], [], [], []
    g_loader, g_collect = [], []
    for r in reqs:
        segs, prm, host = _segs(r), r.get("params") or {}, r.get("vendor") or ""
        first = bool(r.get("firstParty"))
        tid = prm.get("tid") or ""
        rec = {"url": _url(r), "host": "first-party" if first else host,
               "start_time_ms": r.get("ms"), "gcs": prm.get("gcs"), "gcd": prm.get("gcd")}
        if tid.startswith("G-") and "g" in segs and "collect" in segs:
            ga4_hits.append({**rec, "measurement_id": tid, "event_name": prm.get("en"),
                             "seq": prm.get("_s"), "session_id": prm.get("sid"),
                             "doc_location": prm.get("dl"), "cid": prm.get("cid"),
                             "param_names": sorted(_ga4_param_names(r.get("paramNames"))),
                             "params_visible": bool(r.get("paramNames"))})
        elif tid.startswith("AW-") or "ccm" in segs or "1p-user-list" in segs or \
                ("pagead" in segs and r.get("role") == "measurement"):
            ads_hits.append(rec)
        if "facebook.com" in host and "tr" in segs:
            fb_hits.append({**rec, "pixel_id": prm.get("id"), "event_name": prm.get("ev")})
        if "linkedin" in host:
            li_hits.append(rec)
        if "tiktok" in host:
            tt_hits.append(rec)
        if r.get("role") == "loader":
            (fp_loader if first else g_loader if "google" in host else []).append(
                {"url": rec["url"], "host": rec["host"], "path": "/" + "/".join(segs)})
        elif "collect" in segs:
            (fp_collect if first else g_collect if "google" in host else []).append(
                {"url": rec["url"], "host": rec["host"], "path": "/" + "/".join(segs)})
    gw = net.get("gateway") or {}
    status = ("active" if fp_loader and fp_collect else
              "partial" if (fp_loader or fp_collect or gw.get("gtgHealthSeen")) else "not_detected")
    tag_gateway = {"status": status,
                   "measurement_paths": _uniq(h["path"] for h in fp_loader + fp_collect),
                   "first_party_loader_hits": fp_loader, "first_party_collect_hits": fp_collect,
                   "google_hosted_loader_hits": g_loader, "google_hosted_collect_hits": g_collect}

    # ---- tag inventory ----
    ga4_ids = _uniq([h["measurement_id"] for h in ga4_hits]
                    + [k for k in runtime if k.startswith("G-")]
                    + [i for i in ids.get("ga4") or [] if re.fullmatch(r"G-[A-Z0-9]{8,12}", i)])
    gtm_ids = _uniq((ids.get("gtm") or []) + [k for k in runtime if k.startswith("GTM-")])
    gtm_loads = [r for r in reqs if r.get("role") == "loader" and "gtm.js" in _segs(r)
                 and str((r.get("params") or {}).get("id", "")).startswith("GTM-")
                 and not (r.get("params") or {}).get("gtg_health")]
    per_id = {}
    for r in gtm_loads:
        per_id[r["params"]["id"]] = per_id.get(r["params"]["id"], 0) + 1
    gtag_loads = [r for r in reqs if r.get("role") == "loader" and "gtag" in _segs(r)]
    tag_inventory = {
        "ga4_measurement_ids": ga4_ids,
        "gtm_containers": gtm_ids,
        "universal_analytics_ids": ids.get("ua") or [],
        "aw_conversion_ids": _uniq((ids.get("ads") or []) + [k for k in runtime if k.startswith("AW-")]),
        "has_standalone_gtag": bool(gtag_loads),
        "gtm_load_count": len(gtm_loads),
        "gtm_loaded_multiple_times": any(n > 1 for n in per_id.values()),
        "gtm_referenced_not_loaded": [g for g in ids.get("gtm") or [] if runtime and g not in runtime],
        "dataLayer_sample": [{"event": e} for e in dlr.get("events") or []],
    }

    # ---- events ----
    # param_names stays None unless the parameters were readable in a GET hit:
    # batched POST bodies are invisible to Resource Timing, so "missing" would
    # be a guess. The contract rule skips events with param_names None.
    slots = {}
    for e in dlr.get("events") or []:
        if isinstance(e, str) and e not in GTM_INTERNAL:
            slots.setdefault(e, {"event_name": e, "sources": set(), "count": 0, "param_names": None})
            slots[e]["sources"].add("dataLayer"); slots[e]["count"] += 1
    for h in ga4_hits:
        n = h.get("event_name")
        if n:
            s = slots.setdefault(n, {"event_name": n, "sources": set(), "count": 0, "param_names": None})
            s["sources"].add("network"); s["count"] += 1
            if h.get("params_visible"):
                s["param_names"] = sorted(set(s["param_names"] or []) | set(h["param_names"]))
    seen = [{**s, "sources": sorted(s["sources"])} for s in sorted(slots.values(), key=lambda s: s["event_name"])]
    events = {
        "events_seen": seen,
        "key_events_observed": [s["event_name"] for s in seen if s["event_name"] in KEY_EVENT_CANDIDATES],
        "duplicate_event_sources": [s["event_name"] for s in seen
                                    if set(s["sources"]) == {"dataLayer", "network"}
                                    and s["event_name"] in ENHANCED_MEASUREMENT_EVENTS],
    }

    # ---- consent ----
    pushes = dlr.get("consentPushes") or []
    defaults = [p.get("state") or {} for p in pushes if p.get("cmd") == "default"]
    ics = con.get("ics") if isinstance(con.get("ics"), dict) else {}
    v2_keys = {"ad_user_data", "ad_personalization"}
    any_gcs = any(h.get("gcs") for h in ga4_hits + ads_hits)
    consent = {
        "consent_mode_detected": bool(pushes or ics or any_gcs),
        "v2_signals_present": bool(any(v2_keys & set(d) for d in defaults) or v2_keys & set(ics)
                                   or any(h.get("gcd") for h in ga4_hits + ads_hits)),
        "default_consent_call_found": bool(defaults),
        "update_consent_call_found": any(p.get("cmd") == "update" for p in pushes),
        "default_state_raw": defaults[0] if defaults else None,
        "region_targeting": [r for d in defaults for r in (d.get("region") or [])],
        "cmps_detected": con.get("cmpGlobals") or [],
        "tcf_api_present": "__tcfapi" in (con.get("cmpGlobals") or []),
        "google_cookies_before_choice": bool(cookies.get("google")),
        "banner_text_visible": con.get("bannerTextVisible"),
    }

    # ---- vendors ----
    globals_ = set((vend.get("globals") or {}).keys())
    hosts = set(net.get("thirdPartyHosts") or [])
    vendors = {}
    for name, (gl, hp) in VENDORS.items():
        present = bool(globals_ & set(gl)) or any(any(p in h for p in hp) for h in hosts)
        if name == "Google Tag Manager":
            present = bool(gtm_ids)
        if name == "Google Ads":
            present = present or bool(tag_inventory["aw_conversion_ids"]) or bool(ads_hits)
        vendors[name] = {"present": present, "ids": []}
    vendors["Meta (Facebook) Pixel"]["ids"] = _uniq(
        [re.sub(r"\D", "", x) for x in ids.get("metaPixel") or []] + [h.get("pixel_id") for h in fb_hits])

    # ---- personal data in payloads (values never kept) ----
    pii_hits = list(snap.get("pii") or []) if isinstance(snap.get("pii"), list) else []
    for r in ([] if pii_hits or isinstance(snap.get("pii"), list) else reqs):
        for k, v in (r.get("params") or {}).items():
            val = unquote(str(v or ""))
            if EMAIL.search(val):
                pii_hits.append({"kind": "email", "where": f"{r.get('vendor')} {k}"})
            elif PHONE.search(val):
                pii_hits.append({"kind": "phone", "where": f"{r.get('vendor')} {k}"})

    out = dict(snap)
    out.update({
        "ready": (snap.get("meta") or {}).get("ready"),
        "tag_inventory": tag_inventory,
        "network": {**net, "ga4_hits": ga4_hits, "google_ads_hits": ads_hits,
                    "facebook_hits": fb_hits, "linkedin_hits": li_hits, "tiktok_hits": tt_hits,
                    "third_party_hosts": sorted(hosts), "tag_gateway": tag_gateway,
                    "probable_sgtm_hits": [h for h in fp_collect], "snowplow": {}},
        "events": events,
        "consent": {**con, **consent},
        "vendors": vendors,
        "performance": {"web_vitals": {"lcp_ms": perf.get("lcpMs") or (perf.get("vitals") or {}).get("lcp"),
                                       "cls": (round((perf.get("vitals") or {}).get("cls"), 3)
                                               if (perf.get("vitals") or {}).get("cls") is not None else None),
                                       "inp_ms_approx": None},
                        "resource_counts": {"total": perf.get("resources"),
                                            "analytics_related": len(reqs)}},
        "pii": {"hits": pii_hits},
        "privacy": {"gpc_signal": (snap.get("privacy") or {}).get("gpc")},
    })
    return out
