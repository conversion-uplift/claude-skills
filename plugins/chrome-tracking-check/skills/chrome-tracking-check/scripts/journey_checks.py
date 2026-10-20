#!/usr/bin/env python3
"""journey_checks.py — turn a human-led journey into findings.

In journey mode the site owner performs each step (add to basket, checkout,
form submission, and, if they choose, a real test purchase) while Claude
records what the browser sent. Claude writes one record per step to a journey
JSON file (schema in references/journey_protocol.md). This script applies the
same rules to every journey, so the findings do not depend on how Claude
phrased its notes:

  - expected GA4 event missing on a step that was exercised
  - expected GA4 event sent more than once for one action (distinct _s values)
  - ecommerce parameters missing (value, currency, items, transaction_id)
  - an ad platform that is on the site but did not receive the conversion
  - steps not exercised, recorded with the reason (never as "not firing")
  - steps that worked, recorded as positives

It appends the findings to the aggregated payload from aggregate_findings.py
and copies the journey into it, so severity_scorer.py and build_report.py pick
both up.

Usage:
    python journey_checks.py --journey journey.json \
        --aggregated audit_aggregated.json --output audit_aggregated.json
"""

from __future__ import annotations
import argparse, json, sys

ECOMMERCE_STEPS = ["view_item", "add_to_cart", "view_cart", "begin_checkout",
                   "add_shipping_info", "add_payment_info", "purchase"]
CONVERSION_EVENTS = {"purchase", "generate_lead"}
# Events that count as the expected one, when a site uses GA4's other names.
ALTERNATIVES = {
    "generate_lead": ["generate_lead", "form_submit", "sign_up", "contact"],
    "view_cart": ["view_cart"],
}
ECOM_NEEDS_VALUE = {"add_to_cart", "begin_checkout", "add_shipping_info",
                    "add_payment_info", "purchase", "view_item"}
PLATFORM_NAMES = {"ga4": "GA4", "google_ads": "Google Ads", "meta": "Meta",
                  "tiktok": "TikTok", "uet": "Microsoft Ads", "linkedin": "LinkedIn",
                  "pinterest": "Pinterest"}


def _finding(fid, *, title, description, recommendation, severity, url, detail,
             positive=False, confidence="Observed", category="Journey"):
    return {"id": fid, "title": title, "category": category,
            "description": description, "recommendation": recommendation,
            "severity": severity, "positive": positive, "confidence": confidence,
            "evidence": [{"url": url or "", "detail": detail}]}


def _merge(findings):
    """One finding per id, evidence rows combined, highest severity kept."""
    order = ["Critical", "High", "Medium", "Low", "Info"]
    out = {}
    for f in findings:
        if f["id"] not in out:
            out[f["id"]] = f
            continue
        g = out[f["id"]]
        g["evidence"].extend(f["evidence"])
        if order.index(f["severity"]) < order.index(g["severity"]):
            g["severity"] = f["severity"]
    return list(out.values())


def check_step(step, present_platforms):
    found = []
    label = step.get("step_label") or step.get("step", "step")
    expected = step.get("expected_ga4_event") or step.get("step")
    url = step.get("url", "")
    status = step.get("status", "exercised")
    who = step.get("performed_by", "user")

    if status == "skipped":
        found.append(_finding(
            "JOURNEY_STEP_NOT_TESTED", title="Journey steps not tested",
            description=("These steps were not performed, so this check says nothing "
                         "about whether their tracking works."),
            recommendation=("Run them in a later journey, ideally on staging or with a "
                            "test order you can cancel or refund."),
            severity="Info", url=url,
            detail=f"{label}: not tested ({step.get('reason') or 'no reason given'})"))
        return found
    if status == "no_separate_step":
        found.append(_finding(
            "JOURNEY_SINGLE_PAGE_CHECKOUT", title="Checkout steps share one page",
            description=("Basket, delivery and payment are on one URL, so events such as "
                         "begin_checkout, add_shipping_info and add_payment_info have no "
                         "page of their own to fire on."),
            recommendation=("Fire those events from interaction triggers (the delivery "
                            "form completing, a payment method being chosen) rather than "
                            "page views."),
            severity="Low", url=url, detail=f"{label}: no separate step exists"))
        return found

    accept = set(step.get("accept_events") or ALTERNATIVES.get(expected, [expected]))
    observed = [o for o in (step.get("observed") or []) if o.get("name") in accept]
    is_conv = expected in CONVERSION_EVENTS
    sev_main = "High" if is_conv else "Medium"

    if not observed or sum(int(o.get("ga4_hits", 1) or 0) for o in observed) == 0:
        found.append(_finding(
            "JOURNEY_EVENT_MISSING", title="Expected GA4 events missing from the journey",
            description=("A person performed these steps and the browser recorded no GA4 "
                         "hit for the expected event. Because the step was exercised, this "
                         "is a tested absence, not an untested one."),
            recommendation=("Check the trigger for each event in GTM Preview, then confirm "
                            "the fix in GA4 DebugView by repeating the step."),
            severity=sev_main, url=url,
            detail=f"{label} (performed by {who}): no {expected} hit"))
        return found

    ok = True
    for o in observed:
        distinct = int(o.get("distinct_s_count", 1) or 1)
        if distinct > 1:
            ok = False
            found.append(_finding(
                "JOURNEY_EVENT_DUPLICATE", title="GA4 events sent more than once for one action",
                description=("The same event left the browser with different _s values for "
                             "one action, so GA4 counts it more than once. Paired hits to "
                             "google-analytics.com and analytics.google.com with the same _s "
                             "were already counted as one."),
                recommendation=("Open the hit's Initiator tab in DevTools to see which script "
                                "sent each copy. The usual cause is a hard-coded gtag snippet "
                                "alongside a GTM tag, or a GTM tag duplicating enhanced "
                                "measurement. Confirm in GA4 DebugView."),
                severity=sev_main, url=url,
                detail=f"{label}: {o.get('name')} sent {distinct} times"
                       + (f" (_s {', '.join(str(s) for s in o['s_values'])})"
                          if o.get("s_values") else "")))
        missing = []
        if expected in ECOM_NEEDS_VALUE:
            if o.get("value") in (None, ""):
                missing.append("value")
            if not o.get("currency"):
                missing.append("currency")
            if not o.get("item_count"):
                missing.append("items")
        if expected == "purchase" and not o.get("transaction_id"):
            missing.append("transaction_id")
        if missing:
            ok = False
            found.append(_finding(
                "JOURNEY_ECOMMERCE_PARAMS_MISSING",
                title="Ecommerce events missing required parameters",
                description=("GA4 needs value and currency to report revenue, an items array "
                             "for product reports, and a unique transaction_id on purchase to "
                             "avoid counting the same order twice."),
                recommendation=("Add the missing fields to the data layer push for each event "
                                "and map them in the GA4 event tag."),
                severity="High" if expected == "purchase" else "Medium", url=url,
                detail=f"{label}: {o.get('name')} missing {', '.join(missing)}"))

    received = step.get("platforms_received") or {}
    if is_conv:
        for p in present_platforms:
            if p == "ga4":
                continue
            if not received.get(p):
                ok = False
                found.append(_finding(
                    "JOURNEY_AD_PLATFORM_GAP",
                    title="Ad platforms on the site that did not receive the conversion",
                    description=("These platforms load on the site but no conversion hit "
                                 "reached them from the browser at the conversion step. If "
                                 "they are not sent server-side either, their bidding has "
                                 "nothing to optimise towards."),
                    recommendation=("Check whether the platform receives this conversion "
                                    "server-side (Conversions API, enhanced conversions or "
                                    "server-side GTM). If not, add the conversion tag and "
                                    "test it in this journey again."),
                    severity="Medium", url=url, confidence="Inferred",
                    detail=f"{label}: no {PLATFORM_NAMES.get(p, p)} conversion hit in the browser"))

    if ok:
        found.append(_finding(
            "JOURNEY_STEPS_VERIFIED", title="Journey steps that tracked correctly",
            description=("A person performed these steps and the expected GA4 event was "
                         "sent once, with the parameters it needs."),
            recommendation="No action needed. Re-run the journey after tracking changes.",
            severity="Info", positive=True, url=url,
            detail=f"{label}: {expected} sent once"))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journey", required=True)
    ap.add_argument("--aggregated", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    with open(a.journey, encoding="utf-8") as f:
        journey = json.load(f)
    with open(a.aggregated, encoding="utf-8") as f:
        agg = json.load(f)
    if not journey.get("permission_confirmed"):
        sys.stderr.write("Journey refused: permission_confirmed is not true. The user must "
                         "confirm they own the site or have written permission to test it.\n")
        return 2
    present = journey.get("platforms_present") or []
    new = []
    for step in journey.get("steps") or []:
        got = check_step(step, present)
        if step.get("status", "exercised") == "exercised":
            step["issues"] = [f["evidence"][0]["detail"].split(": ", 1)[-1]
                              for f in got if not f.get("positive")]
        new.extend(got)
    new = _merge(new)
    agg.setdefault("findings", []).extend(new)
    agg["journey"] = journey
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(agg, f, indent=2)
    print(f"Journey: {len(journey.get('steps') or [])} steps, {len(new)} findings added "
          f"({sum(1 for n in new if n.get('positive'))} positive).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
