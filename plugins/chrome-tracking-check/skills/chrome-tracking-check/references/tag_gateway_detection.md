# Google tag gateway for advertisers — detection and verification

## Contents

1. What it is
2. Why it needs its own rule
3. Tag Gateway vs server-side GTM
4. What the inspector captures
5. Findings emitted
6. The three positive signals (confirmed in the field)
7. Verifying a claim by hand
8. Routing is per-endpoint, and step 1 above is not a veto
9. Honest limits

Read this when a site claims to use Tag Gateway, or when the inspector reports
anything under `network.tag_gateway`.

## What it is

Tag Gateway lets a site serve the Google tag, and the collection endpoints it
calls, from its **own origin** through a CDN mapping (Cloudflare is the
documented path) or a server-side tagging deployment. The browser sees requests
to the site's own domain instead of `googletagmanager.com` and
`google-analytics.com`. The point is resilience: first-party delivery is
materially harder for ad blockers and browser tracking prevention to strip out.

## Why it needs its own rule

**It fails silently.** The Google-side toggle in Google Ads or Tag Manager can
be set while the CDN half was never mapped. The tag then falls back to normal
`googletagmanager.com` delivery and everything keeps working. No error, no
missing data, no broken report. The client believes they have blocker
resilience they do not have, and nothing in a normal QA pass would tell them.

## Tag Gateway vs server-side GTM

| | Tag Gateway | Server-side GTM |
|---|---|---|
| Host | **Same origin as the page** (`www.example.com`) | Usually a **subdomain** (`sgtm.example.com`, `metrics.example.com`) |
| Path | Customer-chosen measurement path prefix | `/gtm/`, or the vendor's path |
| What it moves | Delivery of the Google tag and its endpoints | Tag execution itself, server-side |

Same-origin is the discriminator the inspector uses. A tracking-style subdomain
is classified as sGTM (`probable_sgtm_hits`); same-origin loader and collection
paths are classified as Gateway (`tag_gateway`). A site can run both.

## What the inspector captures

`probe.js` reports the gateway signals in its `network` block:

```json
{
  "status": "active | partial | not_detected",
  "first_party_loader_hits":   [{"url": "...", "path": "/abc123/gtag/js"}],
  "first_party_collect_hits":  [{"url": "...", "path": "/abc123/g/collect"}],
  "google_hosted_loader_hits": [{"url": "...", "host": "googletagmanager.com"}],
  "google_hosted_collect_hits":[{"url": "...", "host": "region1.analytics.google.com"}],
  "measurement_paths": ["/abc123"]
}
```

`not_detected` is the normal state for most sites and is **not, by itself, a
finding**.

## Findings emitted

| ID | Severity | Fires when |
|---|---|---|
| `TAG_GATEWAY_DETECTED` | Info (positive) | `status == active` |
| `TAG_GATEWAY_BYPASSED` | Medium | Gateway active but collection ALSO goes direct to Google |
| `TAG_GATEWAY_PARTIAL` | Medium | `status == partial` |
| `TAG_GATEWAY_CLAIMED_NOT_ACTIVE` | High | `status == not_detected` **and** the claim flag is set |

### The claim flag

```bash
python scripts/aggregate_findings.py --per-page ... --output ... --claimed-tag-gateway
```

or `"claimed_tag_gateway": true` in the per-page payload. Without it, absence
stays silent: most sites do not run Gateway and must not be marked down for it.
With it, absence becomes an evidenced High finding, which is the most useful
thing this rule does when someone believes Gateway is already on.

## The three positive signals (confirmed in the field)

Look for these before anything else. Together they are conclusive.

1. **`gtg_health=1` on a loader request.** A second request appears for
   `googletagmanager.com/gtm.js?id=<container>&gtg_health=1`. "gtg" is Google
   tag gateway, and this is the tag's own gateway health probe. **No other
   Google product emits this parameter**, so its presence is the single
   strongest signal available from the browser. The inspector surfaces it as
   `network.gateway.gtgHealthSeen`.

2. **Collection on the site's own origin, under a random prefix, ending in
   Google's own endpoint path.** The observed shape is
   `https://www.example.com/{random}/{random}/ccm/collect` for Google Ads, or
   `/{random}/g/collect` for GA4. The tell is that the *final* segments are
   Google's verbatim endpoint (`ccm/collect`, `g/collect`) while the leading
   segments are opaque. That is why `probe.js` classifies segments against a
   known list and reports unrecognised ones as `{len, charClass}`: it reveals
   the prefix pattern without printing anything the redactor will blank.

3. **A Cloudflare `Server-Timing` header on those first-party hits.**
   `serverTiming: ["cfExtPri"]` is emitted by Cloudflare, the documented
   delivery partner. Corroborating, not conclusive on its own.

## Verifying a claim by hand

1. **Loader host.** Where does `gtm.js` / `gtag/js` come from? If it is
   `www.googletagmanager.com`, Gateway is not serving the library.
2. **Collection host.** Where does `/g/collect` go? `region1.analytics.google.com`
   or `www.google-analytics.com` means collection is direct.
3. **Measurement path.** List the site's top-level paths. A Gateway deployment
   has a path prefix proxying Google traffic.

## Routing is per-endpoint, and step 1 above is not a veto

**Defect this prevents:** reading "the loader comes from googletagmanager.com,
therefore no Gateway" and missing a Gateway that was demonstrably live.

A deployment is routinely **partial**. On one live site the browser
recorded, on the same page loads:

- `gtm.js` served by `www.googletagmanager.com` (loader NOT first-party), and
- `/pagead/form-data/...` routed **through** the first-party gateway path, and
- `/ccm/collect`, `/pagead/1p-user-list/...` and remarketing hits going
  **direct** to `www.google.com`, `www.google.co.uk`, `ad.doubleclick.net` and
  `googleads.g.doubleclick.net`.

So classify **per endpoint**, not per site, and let `gtg_health` outrank the
loader host:

| Observed | Status | Finding |
|---|---|---|
| `gtg_health` present, all measurement first-party, loader first-party | `active` | `TAG_GATEWAY_DETECTED` (Info, positive) |
| `gtg_health` present, some measurement first-party, some direct | `partial` | `TAG_GATEWAY_BYPASSED` (Medium) |
| `gtg_health` present, no first-party measurement observed | `partial` | `TAG_GATEWAY_PARTIAL` (Medium) |
| No `gtg_health`, no first-party measurement | `not_detected` | silent, unless the claim flag is set |

When reporting `partial`, say **which** endpoints route first-party and which
go direct, and give the commercial consequence plainly: blocker resilience
applies only where traffic actually goes first-party. Note the case worth
flagging hardest — a gateway that carries the consent-denied cookieless pings
while the consented hits that actually carry conversion signal go direct is
protecting the traffic that needs it least.

Cause always caps at **Medium / needs verification** (rule 4): the browser sees
routing, not the Cloudflare mapping or the Google-side toggle.

Supporting signals: `FPID` / `FPLC` cookies suggest server-set first-party
identifiers (Gateway or sGTM); their absence alongside JS-set `_ga` and
`_gcl_au` points to plain client-side. A Cloudflare `cf-ray` header is
consistent with the documented setup but proves nothing on its own.

**Google's own validation**, which the report always recommends rather than
substitutes for: Tag Assistant, connect to the site, navigate to fire tags,
then **Summary > Output > Hits Sent**, and confirm the hits route to the
measurement path.

## Honest limits

- A negative on the pages tested is not a negative site-wide. Gateway can be
  mapped for a subset of paths, or on a separate checkout domain. Say "not
  active on the pages tested".
- Consent state matters. If tags are suppressed pre-consent, re-test after
  consent before concluding anything about delivery.
- The browser sees the effect, not the CDN configuration. A routed request
  proves it works; an absent one proves it is not working *here*.
- Never write that the client was wrong. Write what was observed, then give the
  Tag Assistant step so they can confirm it themselves.
