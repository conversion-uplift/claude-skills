# Limitations — what runtime inspection can and cannot prove

This audit drives a real browser and inspects what the page is doing right now. That's powerful — but it doesn't see everything. Read this before you build the report so you don't over-claim. The report's "Methodology" section should reference this file.

## 1. The pre-consent pass is only as fresh as the browser state

The audit's "pre-consent" pass shows the tracking state of *the browser session you're inspecting*. If the user's regular browser has visited the site before, their consent choice is cached in cookies / localStorage / IndexedDB / first-party server-set cookies. The pre-consent pass will then reflect "returning visitor with previously-granted consent", which is fundamentally different from a "fresh visitor" view.

What you can do:

- **Strongly prefer running pre-consent inspection in an incognito Chrome window** with the extension connected to that incognito window. This gives you a guaranteed-empty cookie jar, localStorage, sessionStorage, and IndexedDB.
- If the user can't or won't use incognito, **explicitly mark the pre-consent column in the report as "current session state, not guaranteed-fresh"** and downgrade any Consent Mode v2 findings that depend on default-state observation.

What you can't do:

- `document.cookie = ''` does **not** clear HttpOnly cookies, path-scoped cookies, IndexedDB, or first-party server-set cookies. The cookie-clearing JS in earlier versions of this skill was theatre. Don't rely on it.
- Chrome MCP doesn't expose `chrome.browsingData.remove()`.

## 2. dataLayer index is not tag fire order

Earlier versions of this skill tried to detect "tag fired before consent default" by comparing dataLayer array indices. **This was wrong.** GTM evaluates the dataLayer asynchronously and tag firing depends on trigger conditions, not push order — a `gtag('config', 'G-XXX')` push at index 0 does not mean GA4 fired before a `gtag('consent', 'default', ...)` push at index 5. The current inspector deliberately does not make this claim.

If you genuinely need ordering data, use the GTM Preview/Debug mode in the user's GTM workspace — it shows trigger evaluation order with timestamps.

## 3. Resource Timing entries don't include HTTP status codes

`performance.getEntriesByType('resource')` tells you a request happened but not whether it succeeded. A site whose `/g/collect` returns 400 looks identical to one returning 204 in resource timing.

Mitigation: the workflow uses `mcp__claude-in-chrome__read_network_requests` after each pass to capture status codes, and `aggregate_findings.py` emits `TRACKING_ENDPOINT_HTTP_ERROR` for 4xx/5xx on tracking endpoints. **You must include the status codes in the per-page payload's `network_status_codes` field** for that rule to fire.

## 4. Performance buffers may be empty

`largest-contentful-paint`, `layout-shift`, and `event` PerformanceObservers buffer entries only when an observer is registered with `buffered: true` early in page load. If `inspect_all.js` runs after those events occurred and no observer was registered before, the buffers will be empty.

`probe_baseline.js` mitigates this by registering buffered observers straight after navigation so the delayed snapshot has something to read. But this only helps **from inspector-install time onward** — events that fired before the first inspector call may still be missing. Report nulls in the performance appendix as "—" not "0".

## 5. INP is approximated, not measured

True INP requires a Chrome-internal aggregation across the full session lifetime. The script uses the longest observed `event` entry as a proxy. This is **fine for "is anything dramatically slow?" screening but isn't the same number Chrome UX Report would publish**. Label it "INP approx" in the report. The aggregator only flags INP > 500ms to keep false positives down.

## 6. SPA tags often need a route change to fire

React/Vue/Next/Nuxt/SvelteKit sites typically wire GTM/gtag tags to the framework's router, not to `DOMContentLoaded`. Initial load can return `dataLayer_length: 0` even on healthy implementations. SKILL.md describes the route-change workaround (click an in-app nav link or use pushState); apply it whenever the first inspection comes back empty.

## 7. Geographic / IP-based behaviour is invisible

Sites that serve different content (or different tags) to different regions — including consent-banner suppression outside the EEA, or sGTM routing rules — will show the behaviour for **whatever country the connected browser appears to be in**. The audit cannot prove what an EEA visitor would see unless the connected browser is in the EEA (or behind a VPN there).

State this explicitly in the report methodology and ask the user where the browser is connecting from before drawing region-specific conclusions.

## 8. Strict CSP may block injected scripts

Some sites have a Content Security Policy that forbids inline script execution. Chrome extension content scripts usually bypass page CSP (different privilege boundary), but exceptions exist. If `inspect_all.js` returns an error about CSP or "Refused to execute", note it in the report and ask the user to add a permissive CSP for the audit run.

## 9. Ad blockers and privacy extensions

If the user's connected browser has uBlock Origin, Privacy Badger, Brave Shields, or similar, they'll block many of the same vendor endpoints you're trying to inspect. Always ask the user to disable content blockers for the audit window. If you can't be sure they did, mention this in the methodology — false-negative findings on Meta Pixel / Google Ads are otherwise misleading.

## 10. The audit captures the present, not the past

There's no way to know whether GA4 was firing yesterday or last quarter. Don't write recommendations that assume historical state ("GA4 has been broken since the migration"). Stick to present-tense observations.

## 11. Server-side validity is unobservable from the browser

The audit can confirm requests are sent to GA4 / sGTM / pixel endpoints, and can read HTTP status. It cannot confirm:

- Whether GA4 actually processed and stored the hit (server-side filters can drop it).
- Whether your sGTM container is correctly forwarding to GA4 — only the user can verify this in GA4's DebugView.
- Whether Google Ads conversions are landing in the right campaign.

Recommend the user verify in GA4 DebugView and the Google Ads conversions report after fixing any issues this audit surfaces.

---

## How to phrase this in the report

In the methodology section, include a short paragraph like:

> "This audit reflects the runtime tracking state observed by a real Chrome browser at the time of inspection. Runtime inspection cannot verify server-side processing, historical state, or behaviour for regions other than the browser's apparent location. Pre-consent results assume the browser was in an incognito window with no cached state. After implementing the recommendations below, verify in GA4 DebugView and your CMP's debug tools."

Tailor this if any of the above caveats applied to the specific audit (e.g. "the user ran the audit in their regular browser, so pre-consent findings should be interpreted as 'current session state' rather than 'fresh visitor state'").

## Language limits on absence (rule 4)

A scan that did not exercise a journey step has not tested it.

- **Automated mode** never writes "verified absent", "confirmed not firing" or
  "tested directly". Its wording is **"unverified rather than proven absent"**,
  and the methodology names which interactions were performed.
- **Journey mode** may use verified-absent language only for steps the user
  actually performed, and the step table must show that step as exercised.
- Absence of a request type from a page that was not fully network-recorded is
  never reportable at all. See `capture_and_claim_rules.md` rule 3.

## Consent testability (rule 2)

Pre-consent claims require a clean consent state, verified before the first
page load. On a profile that had already accepted, every observation is
post-consent: the run may report tag inventory, and must suppress all consent
findings, ratings and classifications.
