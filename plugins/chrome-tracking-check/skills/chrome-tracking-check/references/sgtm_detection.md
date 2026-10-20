# Server-side GTM (sGTM) detection heuristics

Server-side GTM is a positive signal — it's an investment in first-party measurement and is harder to block than client-side. The audit flags it as **Info** (positive finding), not as a deficiency.

> **Not the same as Google tag gateway.** sGTM normally lives on a tracking-style
> *subdomain*; Tag Gateway serves from the site's *own origin* behind a measurement
> path. The inspector separates them on that basis. See
> [`tag_gateway_detection.md`](tag_gateway_detection.md).

## What sGTM looks like at runtime

The browser doesn't know it's talking to a server container; it just sees requests to what looks like the site's own domain. There's no `window.sgtm` object. Detection is purely network-based.

### Strong signals

1. **`/g/collect` on a non-Google host.** Google Analytics' collection endpoint path is `/g/collect`. If a request to this path goes to anything other than `google-analytics.com`, `analytics.google.com`, or `regionN.google-analytics.com`, sGTM is proxying GA4 hits. Strong evidence.

2. **`/gtm/` path on the first-party domain.** The default sGTM URL pattern is `https://sgtm.example.com/gtm/`. If the audit sees first-party requests to `/gtm/...`, that's the default sGTM router.

3. **Tracking-style subdomain on the first-party domain.** Common patterns: `sgtm.example.com`, `server.example.com`, `tagging.example.com`, `metrics.example.com`, `track.example.com`, `st.example.com`. If those subdomains are serving collection requests, that's sGTM (or a similar first-party proxy).

### Weaker signals

- A first-party `_dc_gtm_*` or `_gcl_*` cookie that's `HttpOnly` (browser-visible cookies tend to be JS-set; HttpOnly ones come from the server, suggesting sGTM is setting them).
- Long opaque cookie values on the first-party domain that look like server-issued identifiers.

The runtime audit doesn't reliably see HttpOnly cookies (they're not in `document.cookie`), so the audit relies on the three strong signals above.

## What the audit emits

`scripts/inspectors/probe.js` reports a `probableSgtmHits` array on each pass. The aggregator emits a single `SGTM_DETECTED` finding with severity Info if any pass on any page has hits.

Example evidence row:

```
URL: https://example.com/
Detail: Server-side GTM detected — first-party requests to
        https://sgtm.example.com/g/collect?tid=G-XXXXXXX&en=page_view
```

## What this means for the rest of the audit

When sGTM is present, the "Analytics requests" column in the per-page performance appendix may undercount, because requests go to first-party hosts. That's expected — note it in the methodology section of the report so the reader doesn't misread the number as evidence of less tracking.

## False positives to watch for

- A site that serves its own analytics dashboard at `/gtm/` (unrelated to Google).
- A site that proxies *something else* (not GA4) through a tracking-style subdomain.

If `probableSgtmHits` matches but no `/g/collect` path is present, mention in the finding that sGTM is *probable* rather than confirmed.
