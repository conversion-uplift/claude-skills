#!/usr/bin/env python3
"""datalayer_spec.py - turn probe_datalayer.js captures into findings and a
data layer specification.

Input is what Claude already collected:
  - per-page records (audit_per_page.json) carrying "datalayer": <probe_datalayer.js output>
    and optionally "datalayer_expect": ["view_item", ...] (events that page should push)
  - journey steps (journey.json) carrying "datalayer": <probe_datalayer.js output>
    captured after the step. Only entries marked afterBaseline belong to the step.

Output:
  1. Findings appended to the aggregated payload (same shape as aggregate_findings.py),
     so severity_scorer.py and build_report.py pick them up. Every rule is deterministic.
  2. "datalayer_spec" added to the payload: the event-by-event status table the report
     renders as an appendix.
  3. --doc: a Markdown data layer specification a developer can build from: what the site
     pushes today, the gaps, the target push for every event, and the success listener for
     the form platform found on the site.
  4. --csv: one row per (event, key) observed, with its type and status.

Rules follow references/capture_and_claim_rules.md: an event is "not pushed" only where the
page or step that should push it was captured; otherwise it is "not tested". Personal data is
never written: the probe only returns flags, types and safe values.

Usage:
    python datalayer_spec.py --per-page audit_per_page.json [--journey journey.json] \
        --aggregated audit_aggregated.json --output audit_aggregated.json \
        [--site-type ecommerce|lead_gen|mixed] [--doc datalayer_spec.md] [--csv datalayer.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = json.loads((HERE.parent / "references" / "datalayer_contracts.json").read_text(encoding="utf-8"))
ECOM = CONTRACTS["ecommerce"]
LEAD = CONTRACTS["lead_gen"]
VENDORS = CONTRACTS["form_vendors"]
SEV_ORDER = ["Critical", "High", "Medium", "Low", "Info"]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class Findings:
    def __init__(self):
        self.by_id = {}

    def add(self, fid, *, title, description, recommendation, severity, url, detail,
            positive=False, confidence="Observed", category="Data layer", owner=None):
        f = self.by_id.get(fid)
        if f is None:
            f = self.by_id[fid] = {
                "id": fid, "title": title, "category": category, "description": description,
                "recommendation": recommendation, "severity": severity, "positive": positive,
                "confidence": confidence, "evidence": [], "_keys": set()}
            if owner:
                f["owner"] = owner
        elif SEV_ORDER.index(severity) < SEV_ORDER.index(f["severity"]):
            f["severity"] = severity
        key = (url or "", detail)
        if key not in f["_keys"]:
            f["_keys"].add(key)
            f["evidence"].append({"url": url or "", "detail": detail})

    def to_list(self):
        return [{k: v for k, v in f.items() if k != "_keys"} for f in self.by_id.values()]


# ---------------------------------------------------------------------------
# Collect captures
# ---------------------------------------------------------------------------

def _steps(journey):
    """Journey steps from journey.json ("steps") or a guided payload ("guided_walk")."""
    if not journey:
        return []
    if isinstance(journey, list):
        return journey
    return journey.get("steps") or journey.get("guided_walk") or []


def _status(step):
    if step.get("status"):
        return step["status"]
    return "skipped" if step.get("verified") is False and step.get("reason") else "exercised"


def _observed(step):
    return step.get("observed") or step.get("observed_events") or []


def collect(per_page, journey):
    """Return a list of captures: {label, url, expect, entries, forms, vendors, pii, source}."""
    caps = []
    for p in (per_page or {}).get("pages") or []:
        dl = p.get("datalayer")
        if not isinstance(dl, dict):
            continue
        caps.append({"label": p.get("template_label") or p.get("url"), "url": p.get("url") or dl.get("url"),
                     "expect": list(p.get("datalayer_expect") or []), "entries": dl.get("entries") or [],
                     "forms": dl.get("forms") or [], "vendors": dl.get("formVendors") or [],
                     "pii": dl.get("pii") or [], "source": "page", "step": None,
                     "truncated": bool(dl.get("entriesTruncated"))})
    for s in _steps(journey):
        dl = s.get("datalayer")
        if not isinstance(dl, dict) or _status(s) != "exercised":
            continue
        entries = dl.get("entries") or []
        if dl.get("baselineIndex") is not None:
            entries = [e for e in entries if e.get("afterBaseline")]
        expected = s.get("expected_ga4_event") or s.get("step")
        caps.append({"label": s.get("step_label") or expected, "url": s.get("url") or dl.get("url"),
                     "expect": [expected] if expected else [], "entries": entries,
                     "forms": dl.get("forms") or [], "vendors": dl.get("formVendors") or [],
                     "pii": [p for p in dl.get("pii") or []
                             if dl.get("baselineIndex") is None or p.get("i", 0) >= dl["baselineIndex"]],
                     "source": "journey", "step": s, "truncated": bool(dl.get("entriesTruncated"))})
    return caps


def infer_site_type(caps, journey, given):
    if given:
        return given
    if isinstance(journey, dict) and journey.get("site_type") in ("ecommerce", "lead_gen", "mixed"):
        return journey["site_type"]
    ecom = any(e.get("ecommerce") for c in caps for e in c["entries"])
    forms = any(not f.get("looksLikeSearch") and (f.get("hasEmailField") or f.get("hasPhoneField"))
                for c in caps for f in c["forms"])
    return "mixed" if ecom and forms else "ecommerce" if ecom else "lead_gen" if forms else "unknown"


# ---------------------------------------------------------------------------
# Ecommerce rules
# ---------------------------------------------------------------------------

def _fmt_keys(keys):
    return ", ".join(f"`{k}`" for k in keys)


def ecommerce_rules(caps, F, status):
    rules = CONTRACTS["_rules"]
    for c in caps:
        url, label = c["url"], c["label"]
        seen_fp = {}
        for e in c["entries"]:
            ec = e.get("ecommerce")
            name = e.get("event") or "(no event key)"
            if not ec:
                continue
            # A Universal Analytics push (event "addToCart", ecommerce.add.products) is filed
            # under its GA4 equivalent, so the summary says "pushed, with gaps", not "not pushed".
            row_name = name
            ua = ec.get("uaActions") or []
            if ec.get("shape") == "ua" and ua and ECOM["ua_to_ga4"].get(ua[0]) in ECOM["events"]:
                row_name = ECOM["ua_to_ga4"][ua[0]]
            contract = ECOM["events"].get(row_name)
            critical = bool(contract and contract.get("critical"))
            sev_main = "High" if critical else "Medium"
            row = status.setdefault(row_name, {"event": row_name, "observed_at": [], "issues": [], "keys": {},
                                               "item_keys": {}, "source": set()})
            if row_name != name:
                row["issues"].append(f"pushed as `{name}`")
            row["observed_at"].append(label)
            row["source"].add(e.get("src", "push"))
            row["keys"].update(e.get("keys") or {})
            row["item_keys"].update(ec.get("itemKeys") or {})

            if ec.get("shape") in ("ua", "mixed"):
                F.add("DL_ECOM_LEGACY_SCHEMA", title="Ecommerce data layer uses the old Universal Analytics shape",
                      description=("The site pushes ecommerce data as `ecommerce.<action>.products[]`. GA4 reads "
                                   "`ecommerce.items[]` with `item_id`/`item_name`, so GA4 ecommerce reports stay "
                                   "empty or partial unless every GA4 tag re-maps the old shape."),
                      recommendation=("Push the GA4 shape (see the data layer specification). If both shapes must "
                                      "run during a migration, push them as separate events and point GA4 tags at the new one."),
                      severity="High", url=url, owner="Developer",
                      detail=f"{label}: `{name}` pushed with {', '.join(ec.get('uaActions') or [])} (shape: {ec.get('shape')})")
                row["issues"].append("Universal Analytics shape")

            if rules.get("clear_ecommerce_before_push") and e.get("src") == "push" and ec.get("clearedBefore") is False:
                F.add("DL_ECOM_NOT_CLEARED", title="Ecommerce pushes are not cleared between events",
                      description=("GTM merges each push into its data model. Without `dataLayer.push({ ecommerce: null })` "
                                   "before each ecommerce event, items and values from the previous event can leak into "
                                   "the next one (for example, list items showing up on add_to_cart)."),
                      recommendation="Push `{ ecommerce: null }` immediately before every ecommerce event.",
                      severity="Medium", url=url, owner="Developer",
                      detail=f"{label}: `{name}` followed an earlier ecommerce push with no clear in between")
                row["issues"].append("not cleared")

            missing = []
            if contract:
                for k in contract["required"]:
                    if k == "items":
                        if not ec.get("itemCount"):
                            missing.append("items")
                    elif k == "currency":
                        if ec.get("currency") is None:
                            missing.append("currency")
                    elif k == "value":
                        if ec.get("valueType") is None:
                            missing.append("value")
                    elif k == "transaction_id":
                        if not ec.get("transactionId"):
                            missing.append("transaction_id")
            if rules.get("currency_required_when_value") and ec.get("valueType") and ec.get("currency") is None \
                    and "currency" not in missing:
                missing.append("currency (needed whenever value is set)")
            if missing:
                F.add("DL_ECOM_REQUIRED_MISSING", title="Ecommerce events are missing required data layer keys",
                      description=("GA4 drops the revenue, or the whole items breakdown, when these keys are absent. "
                                   "On `purchase`, a missing `transaction_id` also removes GA4's protection against "
                                   "counting the same order twice."),
                      recommendation="Add the missing keys to the push. The specification lists the target shape per event.",
                      severity=sev_main, url=url, owner="Developer",
                      detail=f"{label}: `{name}` missing {', '.join(missing)}")
                row["issues"].append("missing " + ", ".join(missing))

            if ec.get("currency") == "invalid":
                F.add("DL_ECOM_CURRENCY_INVALID", title="Currency is not a three-letter ISO 4217 code",
                      description="GA4 only converts and reports revenue for ISO 4217 codes such as GBP, EUR or USD.",
                      recommendation="Send `currency` as an upper-case three-letter code.",
                      severity=sev_main, url=url, owner="Developer",
                      detail=f"{label}: `{name}` currency is not a valid ISO code")
                row["issues"].append("invalid currency")

            for k in ("value", "tax", "shipping"):
                t = ec.get(k + "Type")
                if t and t != "number":
                    numeric = ec.get(k + "Numeric")
                    sev = "Low" if numeric else sev_main
                    F.add("DL_ECOM_VALUE_NOT_NUMBER", title="Monetary values are pushed as text, not numbers",
                          description=("A value such as \"£12.50\" or \"1,200.00\" is not a number, so GA4 records no "
                                       "revenue for it. A plain numeric string such as \"12.50\" usually works in GA4 "
                                       "but breaks some ad platform tags and custom JavaScript variables."),
                          recommendation="Push money as a number with a dot decimal and no symbol: `value: 12.5`.",
                          severity=sev, url=url, owner="Developer",
                          detail=f"{label}: `{name}` {k} is {t}{' (numeric text)' if numeric else ' (not numeric)'}")
                    row["issues"].append(f"{k} is {t}")
            if ec.get("itemKeys", {}).get("price") not in (None, "number"):
                F.add("DL_ECOM_VALUE_NOT_NUMBER", title="Monetary values are pushed as text, not numbers",
                      description=("A value such as \"£12.50\" is not a number, so GA4 records no item revenue for it."),
                      recommendation="Push `price` as a number: `price: 12.5`.",
                      severity="Low" if not critical else "Medium", url=url, owner="Developer",
                      detail=f"{label}: `{name}` item price is {ec['itemKeys']['price']}")
                row["issues"].append("item price not a number")

            if ec.get("itemsWithoutIdOrName"):
                F.add("DL_ECOM_ITEM_ID_MISSING", title="Items without an item_id or item_name",
                      description="GA4 discards an item that has neither `item_id` nor `item_name`.",
                      recommendation="Give every item at least `item_id` (your SKU) and `item_name`.",
                      severity=sev_main, url=url, owner="Developer",
                      detail=f"{label}: `{name}` has {ec['itemsWithoutIdOrName']} of {ec.get('itemCount')} items with neither")
                row["issues"].append("items without id/name")
            elif ec.get("itemCount") and (ec.get("itemsWithoutPrice") or ec.get("itemsWithoutQuantity")) \
                    and name in ("add_to_cart", "begin_checkout", "purchase", "view_cart"):
                parts = []
                if ec.get("itemsWithoutPrice"):
                    parts.append(f"{ec['itemsWithoutPrice']} without price")
                if ec.get("itemsWithoutQuantity"):
                    parts.append(f"{ec['itemsWithoutQuantity']} without quantity")
                F.add("DL_ECOM_ITEM_INCOMPLETE", title="Items without price or quantity",
                      description=("Item revenue and units sold in GA4 come from item `price` and `quantity`. GA4 "
                                   "assumes quantity 1 when it is missing, which under-counts multi-unit baskets."),
                      recommendation="Add `price` (number) and `quantity` (integer) to every item.",
                      severity="Low", url=url, owner="Developer",
                      detail=f"{label}: `{name}` items: {', '.join(parts)}")
                row["issues"].append("items incomplete")

            if isinstance(ec.get("value"), (int, float)) and isinstance(ec.get("itemSum"), (int, float)):
                gap = abs(ec["value"] - ec["itemSum"])
                if gap > max(0.05, 0.01 * max(ec["value"], ec["itemSum"])) and name in ("purchase", "begin_checkout", "view_cart", "add_to_cart"):
                    F.add("DL_ECOM_VALUE_MISMATCH", title="Event value does not match the items in it",
                          description=("The event `value` differs from the sum of item price x quantity. That can be "
                                       "deliberate (value excluding delivery or tax, or after a basket discount), so "
                                       "confirm the rule the business wants and apply it consistently."),
                          recommendation=("Agree one definition of `value` (usually items after discounts, excluding "
                                          "delivery and tax) and document it in the specification."),
                          severity="Low", url=url, owner="Developer", confidence="Inferred",
                          detail=f"{label}: `{name}` value {ec['value']} vs items {ec['itemSum']}")

            tx = (ec.get("transactionId") or {}).get("fp")
            sig = (name, ec.get("value"), ec.get("itemCount"), tx)
            if sig in seen_fp:
                F.add("DL_ECOM_DUPLICATE_PUSH", title="The same ecommerce event is pushed twice for one action",
                      description=("The data layer received two identical pushes. Unless the GTM trigger de-duplicates, "
                                   "every tag on that event fires twice, which inflates GA4 and ad platform conversions."),
                      recommendation="Push once per action. Check theme, app and plugin code that pushes the same event.",
                      severity=sev_main, url=url, owner="Developer",
                      detail=f"{label}: `{name}` pushed at positions {seen_fp[sig]} and {e.get('i')}")
                row["issues"].append("pushed twice")
            seen_fp[sig] = e.get("i")


# ---------------------------------------------------------------------------
# Journey cross-check: data layer vs what reached GA4
# ---------------------------------------------------------------------------

def cross_check(caps, F):
    for c in caps:
        step = c.get("step")
        if not step:
            continue
        expected = step.get("expected_ga4_event") or step.get("step")
        if not expected:
            continue
        names = {e.get("event") for e in c["entries"]}
        accept = set(step.get("accept_events") or [expected])
        if expected == "generate_lead":
            accept |= set(LEAD["lead_event_names"])
        pushed = bool(names & accept)
        sent = sum(int(o.get("ga4_hits", 1) or 0) for o in _observed(step) if o.get("name") in accept) > 0
        if pushed and not sent:
            F.add("DL_PUSHED_NOT_SENT", title="Data layer pushes that no GA4 tag sent",
                  description=("The site pushed the event into the data layer, but no GA4 hit followed. The data is "
                               "there; the gap is the tag or trigger in GTM (or consent blocking it)."),
                  recommendation=("In GTM Preview, open the event and check which tags fired and why the GA4 event tag "
                                  "did not (trigger event name, conditions, consent settings)."),
                  severity="Info", url=c["url"], owner="GTM", confidence="Observed",
                  detail=f"{c['label']}: `{expected}` pushed, not sent to GA4")
        elif sent and not pushed and expected != "generate_lead":
            F.add("DL_SENT_WITHOUT_PUSH", title="GA4 events sent without a matching data layer push",
                  description=("GA4 received the event but the data layer had no push for it at that step. The tag is "
                               "probably hard-coded or reads values from the page, which breaks when the page "
                               "design changes."),
                  recommendation="Move the event onto a data layer push and point the GTM tag at it.",
                  severity="Low", url=c["url"], owner="Developer", confidence="Inferred",
                  detail=f"{c['label']}: `{expected}` sent with no `{expected}` push")


# ---------------------------------------------------------------------------
# Lead generation rules
# ---------------------------------------------------------------------------

def lead_rules(caps, F, status, site_type):
    lead_names = set(LEAD["lead_event_names"])
    id_keys = set(LEAD["form_identifier_keys"])
    for c in caps:
        url, label = c["url"], c["label"]
        for e in c["entries"]:
            name = e.get("event")
            if name not in lead_names:
                continue
            row = status.setdefault(name, {"event": name, "observed_at": [], "issues": [], "keys": {},
                                           "item_keys": {}, "source": set()})
            row["observed_at"].append(label)
            row["source"].add(e.get("src", "push"))
            row["keys"].update(e.get("keys") or {})
            top = {k.split(".")[0] for k in (e.get("keys") or {})}
            if not (top & id_keys):
                F.add("DL_LEAD_NO_FORM_ID", title="Lead events do not say which form they came from",
                      description=("Without `form_id` or `form_name` on the lead event, GA4 and the ad platforms cannot "
                                   "split leads by form (contact vs quote vs brochure), so every form is valued the same."),
                      recommendation="Add `form_id`, `form_name` and `form_type` to the lead push.",
                      severity="Low", url=url, owner="Developer",
                      detail=f"{label}: `{name}` has no form identifier")
                row["issues"].append("no form identifier")
            ud = e.get("userData")
            if ud:
                plain = [f for f, t in ud["fields"].items() if t == "plain"]
                F.add("DL_LEAD_USER_DATA_PRESENT", title="Enhanced conversions data is available in the data layer",
                      description=("The lead push carries user-provided data for enhanced conversions "
                                   f"(`{ud['key']}`: {', '.join(sorted(ud['fields']))}). That improves Google Ads matching. "
                                   "It must only be read by the Google tag's user-provided data variable: never mapped "
                                   "to GA4 event parameters or to other vendors."),
                      recommendation=("In GTM, check which variables read this key and that only the Google tag / "
                                      "Google Ads tags use it, after consent."),
                      severity="Info", url=url, owner="GTM", confidence="Verify",
                      detail=f"{label}: `{name}` {ud['key']} fields {', '.join(sorted(ud['fields']))}"
                             + (f"; {len(plain)} in plain text (the Google tag hashes them)" if plain else ""))

        # A submitted form step that only produced GTM's generic form event.
        step = c.get("step")
        if step and (step.get("expected_ga4_event") == "generate_lead"):
            names = {e.get("event") for e in c["entries"]}
            if not (names & lead_names) and "gtm.formSubmit" in names:
                F.add("DL_LEAD_FROM_GENERIC_SUBMIT", title="Leads are counted from a generic form submit, not a confirmed success",
                      description=("The only data layer event at submission was GTM's built-in `gtm.formSubmit`. It fires "
                                   "on the submit attempt, including submissions that fail validation, and often not at "
                                   "all for AJAX forms. Lead counts and the Ads conversions built on them are unreliable."),
                      recommendation=("Push `generate_lead` from the form platform's success callback (the specification "
                                      "names the right one for the platform found) and trigger the GA4 and Ads tags on it."),
                      severity="Medium", url=c["url"], owner="Developer", confidence="Observed",
                      detail=f"{c['label']}: only gtm.formSubmit at submission")

    if site_type in ("lead_gen", "mixed"):
        lead_forms = [(c, f) for c in caps for f in c["forms"]
                      if not f.get("looksLikeSearch") and (f.get("hasEmailField") or f.get("hasPhoneField"))]
        if lead_forms and not any(f.get("hiddenAttributionFields") for _, f in lead_forms):
            c, f = lead_forms[0]
            F.add("DL_LEAD_NO_CLICK_ID_CAPTURE", title="Enquiry forms do not capture the ad click ID",
                  description=("None of the enquiry forms found carries a hidden `gclid` (or `gbraid`, `wbraid`, "
                               "`msclkid`, UTM) field. Without it the CRM cannot tell which leads came from ads, so "
                               "qualified leads and sales cannot be imported back to Google Ads to steer bidding."),
                  recommendation=("Add hidden click-ID and UTM fields filled from the landing URL (stored in a "
                                  "first-party cookie for later pages) and map them to CRM fields. Check first whether "
                                  "the CRM already captures them another way."),
                  severity="Low", url=c["url"], owner="Developer", confidence="Inferred",
                  detail=f"{len(lead_forms)} enquiry form(s) checked; no hidden attribution fields")


# ---------------------------------------------------------------------------
# Personal data in the data layer
# ---------------------------------------------------------------------------

def pii_rule(caps, F):
    for c in caps:
        outside = [p for p in c["pii"] if not p.get("inUserData")]
        if outside:
            F.add("DL_PERSONAL_DATA", title="Personal data sits in the data layer outside enhanced conversions",
                  description=("An email address or phone number is present in the data layer under a general key. "
                               "Any tag in the container can read it, and a variable mapped to it would send it to GA4 "
                               "(which Google's terms forbid) or to another vendor. Whether a tag actually sends it is "
                               "checked separately against the network payloads."),
                  recommendation=("Remove it from general keys. If it is needed for enhanced conversions, push it under "
                                  "`user_data` and read it only from the Google tag's user-provided data variable."),
                  severity="High", url=c["url"], owner="Developer",
                  detail=f"{c['label']}: " + "; ".join(sorted({f"{p['kind']} at {p['path']}" for p in outside})[:6]))


# ---------------------------------------------------------------------------
# Status table, positives
# ---------------------------------------------------------------------------

def build_status(caps, site_type, status):
    expected = []
    if site_type in ("ecommerce", "mixed"):
        expected += [e for e in ECOM["order"] if ECOM["events"][e]["fires"] != "server"]
    if site_type in ("lead_gen", "mixed"):
        expected += ["generate_lead"]
    captured_for = {}
    for c in caps:
        for ev in c["expect"]:
            captured_for.setdefault(ev, []).append(c["label"])
    rows = []
    for ev in expected + sorted(set(status) - set(expected)):
        row = status.get(ev)
        if ev == "generate_lead" and not row:
            row = next((status[n] for n in LEAD["lead_event_names"] if n in status), None)
        contract = ECOM["events"].get(ev) or LEAD["events"].get(ev) or {}
        if row:
            st = "Pushed, with gaps" if row["issues"] else "Pushed"
            keys = row["keys"]
        elif ev in captured_for:
            st, keys = "Not pushed", {}
        else:
            st, keys = "Not tested", {}
        owner = "-" if st == "Pushed" else "Developer" if st in ("Not pushed", "Pushed, with gaps") else "-"
        rows.append({
            "event": ev, "status": st, "where_expected": contract.get("where", ""),
            "observed_at": sorted(set((row or {}).get("observed_at") or [])),
            "checked_at": sorted(set(captured_for.get(ev, []))),
            "issues": sorted(set((row or {}).get("issues") or [])), "owner": owner,
            "keys": keys, "item_keys": (row or {}).get("item_keys") or {},
            "source": sorted((row or {}).get("source") or []),
        })
    return rows


def positives(rows, F):
    for r in rows:
        if r["status"] == "Pushed":
            F.add("DL_EVENTS_WELL_FORMED", title="Data layer events that match the GA4 specification",
                  description="These events were pushed with the keys and types GA4 needs.",
                  recommendation="No action needed. Keep the specification with the site's code so changes keep it.",
                  severity="Info", positive=True, url="",
                  detail=f"`{r['event']}` at {', '.join(r['observed_at'][:3])}")


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------

EXAMPLE_ITEM = {"item_id": "SKU_12345", "item_name": "Product name", "item_brand": "Brand",
                "item_category": "Category", "item_variant": "Blue / M", "price": 24.99, "quantity": 1}


KEY_ORDER = ["event", "transaction_id", "currency", "value", "tax", "shipping", "coupon",
             "shipping_tier", "payment_type", "item_list_id", "item_list_name", "items"]
EXAMPLES = {"transaction_id": "T_12345", "value": 24.99, "currency": "GBP", "tax": 4.17,
            "shipping": 3.99, "coupon": "SUMMER10", "shipping_tier": "Standard",
            "payment_type": "Card", "item_list_id": "category_shoes", "item_list_name": "Shoes",
            "items": [EXAMPLE_ITEM]}


def _js(v, indent=0):
    """Render a value as a JavaScript literal: unquoted keys, single-quoted strings."""
    pad, inner = "  " * indent, "  " * (indent + 1)
    if isinstance(v, dict):
        return "{\n" + ",\n".join(f"{inner}{k}: {_js(x, indent + 1)}" for k, x in v.items()) + f"\n{pad}}}"
    if isinstance(v, list):
        return "[" + ", ".join(_js(x, indent) for x in v) + "]"
    if isinstance(v, str):
        return "'" + v.replace("'", "\\'") + "'"
    return json.dumps(v)


def example_push(ev):
    c = ECOM["events"].get(ev)
    if c:
        keys = c["required"] + [k for k in c["recommended"] if k not in c["required"]]
        keys = sorted(keys, key=lambda k: KEY_ORDER.index(k) if k in KEY_ORDER else 50)
        body = {"event": ev, "ecommerce": {k: EXAMPLES.get(k, "") for k in keys}}
        return ("dataLayer.push({ ecommerce: null });  // clear the previous ecommerce object\n"
                "dataLayer.push(" + _js(body) + ");")
    if ev == "generate_lead":
        body = {"event": "generate_lead", "form_id": "contact_main", "form_name": "Contact us",
                "form_type": "enquiry", "lead_source": "website", "currency": "GBP", "value": 50}
        return ("// Push from the form platform's SUCCESS callback, not from the submit click.\n"
                "// value: an agreed average lead value, if the business has one.\n"
                "dataLayer.push(" + _js(body) + ");\n\n"
                "// Optional, for Google Ads enhanced conversions. Only after consent; read it ONLY\n"
                "// from the Google tag's user-provided data variable, never as a GA4 parameter.\n"
                "dataLayer.push({ event: 'user_data_ready', user_data: { email: '<from the form>', phone_number: '<E.164>' } });")
    return None


def _md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def write_doc(path, site, site_type, rows, caps, findings):
    vendors = sorted({v for c in caps for v in c["vendors"]})
    forms = [(c, f) for c in caps for f in c["forms"] if not f.get("looksLikeSearch")]
    L = [f"# Data layer specification: {site}", "",
         f"Observed on {date.today().strftime('%d/%m/%Y')} by Chrome Tracking Check. Site type: {site_type.replace('_', ' ')}.", "",
         "This document has three parts: what the site pushes into `window.dataLayer` today, what is missing "
         "or malformed, and the target push for each event. Values below are examples: the check records "
         "key names and types, never customer data.", "",
         "**Status meanings.** *Pushed*: seen and well formed. *Pushed, with gaps*: seen, with issues listed. "
         "*Not pushed*: the page or step that should push it was checked and nothing arrived. "
         "*Not tested*: nobody exercised that step in this check, so nothing is known.", "",
         "## 1. Summary", "",
         _md_table(["Event", "Status", "Should fire", "Seen at", "Issues", "Who fixes"],
                   [[f"`{r['event']}`", r["status"], r["where_expected"], ", ".join(r["observed_at"][:3]) or "-",
                     "; ".join(r["issues"]) or "-", r["owner"]] for r in rows]), ""]

    L += ["## 2. What the site pushes today", ""]
    seen = [r for r in rows if r["keys"]]
    if not seen:
        L += ["No ecommerce or lead events were pushed on the pages and steps checked.", ""]
    for r in seen:
        L += [f"### `{r['event']}`", "", f"Seen at: {', '.join(r['observed_at'])}. Pushed via: {', '.join(r['source']) or 'push'}.", ""]
        L += [_md_table(["Key", "Type"], [[f"`{k}`", t] for k, t in sorted(r["keys"].items()) if not k.startswith("ecommerce.items[]")])]
        if r["item_keys"]:
            L += ["", "Item keys: " + ", ".join(f"`{k}` ({t})" for k, t in sorted(r["item_keys"].items()))]
        if r["issues"]:
            L += ["", "**Gaps:** " + "; ".join(r["issues"]) + "."]
        L += [""]

    L += ["## 3. Target pushes", "",
          "Rules that apply to every ecommerce push:", "",
          "- Clear first: `dataLayer.push({ ecommerce: null })` before each ecommerce event.",
          "- Money is a number with a dot decimal and no symbol (`24.99`, not `\"£24.99\"`).",
          "- `currency` is an ISO 4217 code (`GBP`) and is required whenever `value` is sent.",
          "- Every item has `item_id` or `item_name` (send both), plus `price` and `quantity`.",
          "- Push once per action, after the action succeeded (the item really is in the basket).",
          "- `purchase` fires once per order, on the confirmation page, with a unique `transaction_id`; "
          "a reload must not push it again.", ""]
    targets = [r["event"] for r in rows if r["status"] != "Pushed"]
    for ev in targets:
        code = example_push(ev)
        if code:
            c = ECOM["events"].get(ev) or LEAD["events"].get(ev) or {}
            L += [f"### `{ev}`", "", f"Fire: {c.get('where', '')}.", "", "```js", code, "```", ""]
    if not targets:
        L += ["Every expected event was pushed well formed; no target changes.", ""]

    if site_type in ("lead_gen", "mixed") or forms:
        L += ["## 4. Forms and lead tracking", ""]
        if forms:
            L += [_md_table(["Page", "Form", "Posts to", "Fields", "Hidden attribution fields"],
                            [[c["label"], f.get("id") or f.get("name") or (f.get("classes") or "")[:30] or "(unnamed)",
                              f.get("action"), len(f.get("fields") or []),
                              ", ".join(f.get("hiddenAttributionFields") or []) or "none"] for c, f in forms[:20]]), ""]
        if vendors:
            L += ["Form platforms found, and the success signal to push `generate_lead` from:", ""]
            for v in vendors:
                info = VENDORS.get(v, {})
                L += [f"- **{info.get('label', v)}**: {info.get('listener', 'check the vendor documentation')}"
                      + (f" *{info['verify']}*" if info.get("verify") else "")]
            L += [""]
        else:
            L += ["No known form platform was detected. For a custom form, push `generate_lead` in the code "
                  "that handles a successful response (after the server accepted it), or on a thank-you page "
                  "that only a successful submission reaches.", ""]
        L += ["Lead lifecycle events (`qualify_lead`, `working_lead`, `close_convert_lead`, ...) come from the CRM, "
              "not the website. Send them with the Measurement Protocol or an offline conversion import, keyed "
              "on the click ID captured by the form.", ""]

    L += ["## 5. How to test a change", "",
          "1. Open GTM Preview, perform the action, and check the data layer tab for the push and its keys.",
          "2. In the same session, confirm the GA4 tag fired on that event and open GA4 DebugView to see the parameters arrive.",
          "3. Re-run Chrome Tracking Check (journey mode for basket, checkout and forms) and compare this document.", ""]
    open_f = [f for f in findings if f["category"] == "Data layer" and not f.get("positive")]
    if open_f:
        L += ["## 6. Data layer findings", ""]
        L += [_md_table(["Severity", "Finding", "Who fixes", "Evidence"],
                        [[f["severity"], f["title"], f.get("owner", "-"), f["evidence"][0]["detail"]] for f in
                         sorted(open_f, key=lambda x: SEV_ORDER.index(x["severity"]))]), ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event", "status", "key", "type", "issues", "seen_at"])
        for r in rows:
            keys = list(r["keys"].items()) + [(f"items[].{k}", t) for k, t in r["item_keys"].items()]
            for k, t in keys or [("", "")]:
                w.writerow([r["event"], r["status"], k, t, "; ".join(r["issues"]), " | ".join(r["observed_at"])])


# ---------------------------------------------------------------------------
# One severity per issue (capture_and_claim_rules.md rule 6)
# ---------------------------------------------------------------------------

# When the symptom is already a finding from aggregate_findings.py or journey_checks.py,
# the data layer finding becomes its root-cause note (Info, no deduction), so the grade
# is not docked twice for one problem.
SAME_ISSUE = {
    "DL_ECOM_REQUIRED_MISSING": {"GA4_EVENT_PARAM_MISSING"},
    "DL_ECOM_LEGACY_SCHEMA": {"GA4_ECOMMERCE_LEGACY_SCHEMA"},
    "DL_ECOM_ITEM_ID_MISSING": {"GA4_ECOMMERCE_ITEMS_INCOMPLETE"},
    "DL_ECOM_DUPLICATE_PUSH": {"JOURNEY_EVENT_DUPLICATE", "ENHANCED_MEASUREMENT_DUPLICATE"},
    "DL_PUSHED_NOT_SENT": {"EVENT_PUSHED_BUT_NOT_SENT"},
    "DL_SENT_WITHOUT_PUSH": {"EVENT_SENT_WITHOUT_DATALAYER"},
    "DL_PERSONAL_DATA": {"PII_LEAK_IN_PARAMS"},
}


def dedupe_against(existing_ids, findings):
    for f in findings:
        overlap = SAME_ISSUE.get(f["id"], set()) & existing_ids
        if overlap and not f.get("positive") and f["severity"] != "Info":
            f["root_cause_of"] = sorted(overlap)
            f["severity_note"] = (f"Was {f['severity']}; reported as Info because the same problem is "
                                  f"already graded as {', '.join(sorted(overlap))}. This finding names the cause.")
            f["severity"] = "Info"
    return findings


def custom_section(rows, vendors, site_type):
    """The same summary as a build_guided_report.py custom_sections entry."""
    table = [["Event", "Status", "Should fire", "Gaps", "Who fixes"]] + [
        [r["event"], r["status"], r["where_expected"], "; ".join(r["issues"]) or "-", r["owner"]] for r in rows]
    blocks = [{"heading": "Event by event", "table": table}]
    if vendors:
        blocks.append({"heading": "Form platforms found",
                       "bullets": [f"{VENDORS.get(v, {}).get('label', v)}: {VENDORS.get(v, {}).get('listener', '')}"
                                   for v in vendors]})
    return {"title": "Data Layer Specification",
            "intro": [f"What the site pushes into the data layer for each ecommerce and lead event, checked "
                      f"against the GA4 specification ({site_type.replace('_', ' ')} site). Not tested means "
                      "nobody performed that step, so nothing is known about it. The developer specification, "
                      "with the target code for every event, is supplied with this report."],
            "blocks": blocks,
            "close": "Key names and types only were recorded; no customer data was read."}


# ---------------------------------------------------------------------------

def run(per_page, journey, site_type=None):
    caps = collect(per_page, journey)
    st = infer_site_type(caps, journey, site_type)
    F, status = Findings(), {}
    ecommerce_rules(caps, F, status)
    lead_rules(caps, F, status, st)
    cross_check(caps, F)
    pii_rule(caps, F)
    rows = build_status(caps, st, status)
    positives(rows, F)
    for r in rows:
        r["source"] = list(r["source"])
    return caps, st, rows, F.to_list()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--per-page", required=True)
    ap.add_argument("--journey")
    ap.add_argument("--aggregated", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--site-type", choices=["ecommerce", "lead_gen", "mixed"])
    ap.add_argument("--doc", help="Write the Markdown data layer specification here.")
    ap.add_argument("--csv", help="Write the observed keys as CSV here.")
    a = ap.parse_args()
    per_page = json.loads(Path(a.per_page).read_text(encoding="utf-8"))
    journey = json.loads(Path(a.journey).read_text(encoding="utf-8")) if a.journey else None
    agg = json.loads(Path(a.aggregated).read_text(encoding="utf-8"))
    caps, st, rows, findings = run(per_page, journey, a.site_type)
    if not caps:
        sys.stderr.write("No datalayer captures found: add probe_datalayer.js output as \"datalayer\" "
                         "on page records or journey steps.\n")
    findings = dedupe_against({f.get("id") for f in agg.get("findings") or []}, findings)
    agg.setdefault("findings", []).extend(findings)
    vendors = sorted({v for c in caps for v in c["vendors"]})
    agg["datalayer_spec"] = {"site_type": st, "events": rows, "captures": len(caps), "form_vendors": vendors}
    # Guided reports render extra sections through custom_sections; append this one there.
    agg["datalayer_custom_section"] = custom_section(rows, vendors, st)
    Path(a.output).write_text(json.dumps(agg, indent=2), encoding="utf-8")
    site = agg.get("site") or per_page.get("site") or (caps[0]["url"] if caps else "site")
    if a.doc:
        write_doc(a.doc, site, st, rows, caps, findings)
    if a.csv:
        write_csv(a.csv, rows)
    print(f"Data layer: {len(caps)} captures, site type {st}, {len(rows)} events in the specification, "
          f"{len(findings)} findings ({sum(1 for f in findings if f.get('positive'))} positive)"
          + (f"; spec -> {a.doc}" if a.doc else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
