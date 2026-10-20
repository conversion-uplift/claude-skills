# Vendor detection signatures

## Contents

1. Google ecosystem
2. Social pixels
3. Session replay & heatmaps
4. CDPs / enterprise tag managers
5. Other commonly-encountered
6. Consent management platforms (CMPs)
7. Adding a new vendor
8. Vendor-embedded analytics: Snowplow and Salesfire

This is the canonical reference for how each supported tracking vendor is detected at runtime. The same signatures are encoded in `scripts/inspectors/vendor_detection.js` and `scripts/inspectors/network_analysis.js`.

Detection uses three independent signals, in order of reliability:

1. **Network request to the vendor's endpoint** — most authoritative because it proves the tag actually ran.
2. **Window global** (`window.fbq`, `window.hj`, etc.) — proves the SDK loaded.
3. **Script tag with vendor `src`** — proves the snippet is on the page.

Where possible we extract the vendor's *account id* (pixel id, measurement id, etc.) because the audit's cross-page checks depend on it (e.g. "is the GA4 measurement id the same on every page?").

## Google ecosystem

| Vendor | Window global | Script `src` pattern | Network endpoint | ID source |
|---|---|---|---|---|
| Google Tag Manager (client-side) | `window.google_tag_manager` | `googletagmanager.com/gtm.js?id=GTM-XXXX` | `googletagmanager.com/gtm.js` | URL `id=` param + keys of `google_tag_manager` matching `^GTM-` |
| Google gtag.js (standalone) | `window.gtag` | `googletagmanager.com/gtag/js?id=...` | `googletagmanager.com/gtag/js` | URL `id=` param |
| Google Analytics 4 | (via gtag) | `gtag/js?id=G-XXXX` | `google-analytics.com/g/collect`, `region1.google-analytics.com/g/collect` | URL `tid=` on /g/collect; or `id=G-XXX` on script |
| Google Ads | — | `googletagmanager.com/gtag/js?id=AW-XXXX`, `googleadservices.com/...` | `googleadservices.com/pagead/...`, `g.doubleclick.net/...` | URL `id=AW-XXX` |
| Floodlight / DoubleClick | — | `fls.doubleclick.net/...` | `doubleclick.net` | — |

### Universal Analytics (legacy)
GA Universal (`UA-XXXX`) was sunset in 2023. If it's still firing in 2026 that's a Critical finding — it's literally not collecting data — so the `tag_inventory.js` inspector tracks `UA-` config IDs separately.

## Social pixels

| Vendor | Window global | Script `src` pattern | Network endpoint | ID source |
|---|---|---|---|---|
| Meta (Facebook) Pixel | `window.fbq` | `connect.facebook.net/.../fbevents.js` | `facebook.com/tr?id=PIXEL&ev=EVENT` | URL `id=` on `/tr`; also `fbq.queue` items where `[0]==='init'` |
| LinkedIn Insight | `window._linkedin_data_partner_ids` | `snap.licdn.com/li.lms-analytics/insight.min.js` | `px.ads.linkedin.com/...` | `_linkedin_data_partner_ids` array |
| TikTok Pixel | `window.ttq` | `analytics.tiktok.com/i18n/pixel/events.js` | `analytics.tiktok.com/...` | keys of `ttq._i` |
| Pinterest Tag | `window.pintrk` | `s.pinimg.com/ct/core.js` | `ct.pinterest.com/...`, `s.pinimg.com/ct/...` | `pintrk.queue` `load` entries |
| X (Twitter) Pixel | `window.twq` | `static.ads-twitter.com/uwt.js` | `analytics.twitter.com/...`, `t.co/i/adsct` | (not extracted) |
| Snapchat Pixel | `window.snaptr` | `sc-static.net/scevent.min.js` | `tr.snapchat.com/...` | (not extracted) |
| Reddit Pixel | `window.rdt` | `redditstatic.com/ads/pixel.js` | `redditstatic.com/...` | (not extracted) |

## Session replay & heatmaps

| Vendor | Window global | Script `src` pattern | Network endpoint | ID source |
|---|---|---|---|---|
| Microsoft Clarity | `window.clarity` | `clarity.ms/tag/XXXX` | `clarity.ms` | URL path segment after `/tag/` |
| Hotjar | `window.hj`, `window._hjSettings` | `static.hotjar.com`, `script.hotjar.com` | `hotjar.com` | `_hjSettings.hjid` |
| FullStory | `window.FS`, `window._fs_host` | `edge.fullstory.com`, `fullstory.com/s/fs.js` | `fullstory.com` | `window._fs_org` |
| Mouseflow | `window._mfq` | `cdn.mouseflow.com` | `mouseflow.com` | — |
| Lucky Orange | `window.__lo_site_id` | `luckyorange.com`, `luckyorange.net` | `luckyorange.*` | `__lo_site_id` |
| Crazy Egg | `window.CE2` | `script.crazyegg.com` | `crazyegg.com` | — |
| Smartlook | `window.smartlook` | `web-sdk.smartlook.com` | `smartlook.com` | — |

## CDPs / enterprise tag managers

| Vendor | Window global | Script `src` pattern |
|---|---|---|
| Segment | `window.analytics` | `cdn.segment.com/analytics.js` |
| Tealium | `window.utag` | `tags.tiqcdn.com` |
| Adobe Launch / DTM | `window._satellite` | `assets.adobedtm.com` |
| mParticle | `window.mParticle` | `jssdkcdns.mparticle.com` |

## Other commonly-encountered

| Vendor | Window global | Script `src` pattern | ID source |
|---|---|---|---|
| Zoho (PageSense / SalesIQ / Analytics) | `window.$zoho`, `window.ZAnalyticsObject` | `zoho.com/(pagesense|salesiq|analytics)`, `zohopublic.com`, `cdn.zoho.com` | — |
| HubSpot | `window._hsq` | `js.hs-scripts.com/<id>.js`, `js.hsadspixel.net` | URL path numeric id |
| Intercom | `window.Intercom` | `widget.intercom.io`, `js.intercomcdn.com` | — |
| Drift | `window.drift` | `js.driftt.com` | — |

## Consent management platforms (CMPs)

These don't count as tracking but are detected to evaluate Consent Mode v2 wiring:

| CMP | Signal |
|---|---|
| OneTrust | `window.OneTrust`, `window.OnetrustActiveGroups`, `#onetrust-banner-sdk` |
| Cookiebot | `window.Cookiebot`, `#CybotCookiebotDialog` |
| Didomi | `window.Didomi` |
| Quantcast | `window.__tcfapi` + `window.__cmp` |
| Usercentrics | `window.UC_UI`, `script[src*="usercentrics"]` |
| Iubenda | `window._iub`, `script[src*="iubenda"]` |
| Osano | `window.Osano`, `script[src*="osano.com"]` |
| Klaro | `window.klaro` |
| Termly | `script[src*="termly.io"]` |
| CookieYes | `window.cookieyes`, `script[src*="cookieyes"]` |

Also: `typeof window.__tcfapi === 'function'` indicates IAB TCF v2 is wired up regardless of which CMP supplies it.

## Adding a new vendor

To support a new vendor, add its window globals, script hosts and network hosts to the matching blocks in `probe.js`. Also update this reference table.

## Vendor-embedded analytics: Snowplow and Salesfire

Full reporting rules: `capture_and_claim_rules.md` rule 7.

**Snowplow (generic)**
- Globals: `GlobalSnowplowNamespace`, `window.snowplow`, `_snaq`
- Trackers: `sp.js`, `sp/<version>.js`, `sp.min.js`
- Collectors: `/com.snowplowanalytics.snowplow/tp2`, `/i?e=` pixel endpoints
- Cookies: `_sp_id`, `_sp_ses` (first-party, only when self-hosted)

**Salesfire** (UK on-site search and personalisation; ships Snowplow inside)
- `cdn.salesfire.co.uk`, `hit.salesfire.co.uk`, `*.smartmetrics.co.uk`
- The Snowplow tracker is served from the Salesfire CDN, e.g.
  `cdn.salesfire.co.uk/sp/3.3.0.js`

**Classify before reporting:**

| Classification | Signals |
|---|---|
| **Owned** | Collector on a first-party domain, and/or first-party `_sp_id` / `_sp_ses` cookies |
| **Vendor-embedded** | Tracker and collector both on the vendor's domain, no first-party `_sp` cookies |

Vendor-embedded is rented telemetry, not an analytics asset the client owns.
Never count it as the site's analytics platform. If no site-owned analytics
platform is observed at all, that is the report's headline finding.
