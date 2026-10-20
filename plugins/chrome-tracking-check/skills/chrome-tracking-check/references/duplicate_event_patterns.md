# Duplicate event detection — first-class check

## Contents

1. The counting rule — apply BEFORE claiming any GA4 duplicate
2. Patterns to test
3. Where the data comes from
4. Evidence format (side-by-side)

Duplicate events silently inflate conversions, distort ad bidding, and destroy
trust in reporting. Every audit (automated or journey) explicitly tests the
patterns below. **Compare network hits per action, not just dataLayer pushes**
— a single dataLayer push consumed by two tags produces two network hits, and
that is the duplication that matters.

Each duplicate found becomes a finding whose evidence shows the **two request
URLs (or two initiators) side by side**.

> The counting rule below is rule 1 of
> [`capture_and_claim_rules.md`](capture_and_claim_rules.md) and is enforced in
> code by `collapse_dual_dispatch()` in `aggregate_findings.py`. The aggregator
> collapses dual dispatch before any duplicate rule sees the hits.

## The counting rule — apply BEFORE claiming any GA4 duplicate

Requests are not events. Three separate Google requests can carry
`en=page_view` on one consented page load, and only one of them is GA4:

1. `*.google-analytics.com` or `*.analytics.google.com` `/g/collect` with a
   `tid=G-…` measurement ID — **this is the GA4 hit**.
2. `pagead2.googlesyndication.com/ccm/collect` with `tid=AW-…` — the Google
   Ads tag ping. NOT GA4.
3. `google.com/ccm/collect` — the Ads tag's paired request. NOT GA4.

Rules, in order:

- A GA4 page_view is ONLY a `/g/collect` request with a `G-` measurement ID.
  Never count `/ccm/collect`, or any `AW-` tid, as GA4 — a GA4 hit and an Ads
  ping routinely land ~10ms apart and look like a double-fire if you count
  requests by event name alone.
- Collapse dual dispatch: when ad consent is granted, GA4 can send the SAME
  logical hit to `*.google-analytics.com` AND `*.analytics.google.com`. Two
  `/g/collect` requests with the same `_s`, `sid` and `dl` within ~100ms are
  ONE hit (GA4 reports count them once).
- Only report a genuine double-fire when two `/g/collect` hits with `G-` tids
  go to the same endpoint class with DIFFERENT `_s` values (or an identical
  `_s` repeated), and recommend confirming in GA4 DebugView before grading it
  above Medium confidence.
- Evidence for any duplicate claim must cite each request's full hostname,
  `tid` and `_s` value — never just the event name and timestamps.

## Patterns to test

### 1. Same GA4 Measurement ID loaded twice — the classic double page_view
- Signal: the same `G-XXXX` appears both in a standalone
  `googletagmanager.com/gtag/js?id=G-XXXX` script AND is configured inside a
  GTM container on the same page.
- Confirm: **two** `/g/collect?...&en=page_view` hits with the same `tid` on
  one page load.
- Finding: `GA4_DOUBLE_LOAD_GTAG_AND_GTM` (High). Evidence = both script srcs
  + both collect URLs.

### 2. Duplicate conversion/funnel events on one action
- `page_view`, `add_to_cart`, `begin_checkout`, `purchase`, `generate_lead` /
  `form_submit` firing **twice** for a single user action.
- Method (journey mode): after each user-performed step, count `/g/collect`
  hits per event name in the network diff. Two `en=add_to_cart` hits for one
  click = duplicate.
- Method (automated): count per page-load; two `en=page_view` with the same
  `tid` = duplicate.
- Finding: `GA4_DUPLICATE_EVENT_ON_ACTION` (High; Critical if `purchase` or
  lead events — those feed ad bidding and revenue reporting directly).

### 3. Enhanced Measurement overlapping with GTM-tagged events
- GA4 Enhanced Measurement auto-fires `scroll`, `form_submit`, `form_start`,
  `click` (outbound), `file_download`, `video_*`, `view_search_results`.
- If GTM also fires an identically-named event, GA4 receives both.
- Heuristic: two hits with the same `en=` but different initiators/sources, or
  an `en=scroll|form_submit` hit with `_ee=1` (Enhanced Measurement marker)
  **plus** a same-named event visible as a dataLayer push consumed by GTM.
- Finding: `ENHANCED_MEASUREMENT_DUPLICATE` (High, Inferred — recommend
  checking the GA4 web stream's Enhanced Measurement toggles against the GTM
  container's tags).

### 4. Same Meta Pixel ID initialised twice
- Signal: `fbq.queue`/`fbq.getState()` shows the same pixel id in two `init`
  calls, or the `fbevents.js` snippet appears both hard-coded and inside GTM.
- Confirm: two `facebook.com/tr?id=<same-id>&ev=PageView` hits per load.
- Also applies to TikTok (`ttq._i` same id twice), UET (two `bat.bing.com`
  loads with the same tag id), LinkedIn (same partner id twice).
- Finding: `PIXEL_DOUBLE_INIT` (Medium; High if conversion events duplicate).

### 5. Duplicate transaction risk (deduplication hygiene)
- `purchase`/lead events with **missing or blank `transaction_id`** — GA4
  cannot deduplicate repeat fires (page refresh on the thank-you page =
  double revenue).
- Meta Pixel + CAPI both apparently in play (browser pixel present AND
  first-party/sGTM relay signals per `server_side_signals.md`) with **no
  `eventID`** visible on browser pixel events — no deduplication hint means
  Meta may count twice.
- Finding: `TRANSACTION_DEDUP_RISK` (High, Inferred).

## Where the data comes from

- `probe.js` → tag inventory (script srcs, config ids, dataLayer
  sample), `vendors` (pixel ids and init counts), `network` (request URLs).
- `read_network_requests` → per-request URL + status; use `clear: true`
  between steps so each diff is attributable to one action.
- Existing aggregator rules `GTM_DUPLICATE_CONTAINER`, `META_PIXEL_DUPLICATE`,
  `GTM_AND_STANDALONE_GTAG_BOTH`, `ENHANCED_MEASUREMENT_DUPLICATE` already
  cover part of this; the journey adds the **per-action network diff**
  evidence they can't get from a static load.

## Evidence format (side-by-side)

```
Duplicate add_to_cart — one click, two GA4 hits:
  1. https://region1.google-analytics.com/g/collect?tid=G-AAAA&en=add_to_cart  (initiator: gtag/js hard-coded)
  2. https://region1.google-analytics.com/g/collect?tid=G-AAAA&en=add_to_cart  (initiator: gtm.js GTM-BBBB)
```
