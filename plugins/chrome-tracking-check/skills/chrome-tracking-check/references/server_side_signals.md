# Client-side vs server-side classification — per platform, with the uplift framing

For **every** measurement/ad platform detected, classify collection as one of:

- **Client-side only** — all hits go direct from the browser to the vendor's
  own domains. Exposed to ad blockers and browser tracking prevention.
- **Server-side / first-party present** — hits route through a first-party or
  server-side endpoint before reaching the vendor.
- **Hybrid** — some events first-party, some direct.

This classification appears per-platform in the report's "Client-Side vs
Server-Side Tag Management" section (see the report spec).

## Detection signals (server-side / first-party present)

| Signal | What it looks like | Applies to |
|---|---|---|
| First-party GA4 collection | `/g/collect` on any non-Google host (esp. subdomains of the audited site) | GA4, sGTM |
| Default sGTM router | first-party requests to `/gtm/...` | sGTM |
| Tracking-style subdomain | `sgtm.`, `ss.`, `server.`, `tagging.`, `metrics.`, `track.`, `st.`, `data.`, `analytics.` on the first-party domain serving collection requests | any |
| Stape-style domains | requests to `*.stape.io`, `*.stape.net`, or Stape's custom-loader path patterns (`/e7d5bs.js`-style obfuscated loaders on the first-party domain) | any |
| Google Tag Gateway | gtm.js / gtag/js AND `/g/collect` served from the site's **own origin** behind a customer-chosen measurement path (not a subdomain, that is sGTM). See `references/tag_gateway_detection.md`; the inspector emits `network.tag_gateway`. A claimed-but-absent Gateway is a High finding because it fails silently | GA4, Ads |
| First-party-served gtm.js/gtag.js | the GTM/gtag library itself loading from the site's own domain | GA4, Ads |
| First-party fbevents relay | `fbevents.js` from a first-party domain; Meta `/tr` hits proxied first-party; `_fbp`/`_fbc` relayed in sGTM payloads | Meta (CAPI hint) |
| eventID on pixel events | Meta browser events carrying `eventID` — deduplication hint that CAPI is running server-side | Meta |
| TikTok Events API hints | ttq events carrying `event_id`; first-party TikTok relays | TikTok |

**Caveat for the report:** Conversions API / Events API traffic is
server-to-server and *not directly visible from the browser*. Say "indications
of", never "confirmed", unless the client confirms. HttpOnly first-party
cookies (server-set `_gcl_*`, `FPID`) are a supporting signal but not visible
in `document.cookie`.

## Value framing — no unmeasured figures

Wherever a platform's collection is classified **client-side only**, highlight
it as an improvement area in the findings and the roadmap. Do not quote
industry loss or uplift percentages: no figure may appear in the report unless
it was measured in this capture (request counts, timings). Say instead:

> Client-side collection is exposed to ad blockers, browser extensions and
> browser tracking protection, so some conversions will not be recorded. The
> size of the gap depends on your audience and devices. You can measure it on
> your own site by blocking the tag manager in DevTools (Request conditions)
> and repeating a test conversion. Server-side tagging is not a silver bullet:
> it does not remove the need for consent, and a poor client-side
> implementation moved server-side is still a poor implementation.

Server-side migration sits in **Priority 2 or Priority 3** of the remediation
roadmap (never Priority 1: broken measurement and compliance risks come
first), always carrying the wording above.

## Session-replay tooling rule (Hotjar / Microsoft Clarity)

If **Hotjar** is detected, ALWAYS add a recommendation:

- **Microsoft Clarity is free and its free tier is more complete — Hotjar's
  free plan is not worth having.**
- If the client appears to be on **paid Hotjar**: frame Clarity as a **cost
  saving to evaluate** (like-for-like session recordings and heatmaps at zero
  licence cost).
- If they are on **free Hotjar**: recommend **switching outright**.
- You usually cannot tell free vs paid from the browser — if unknown, present
  both framings ("if you are paying for Hotjar… / if you are on the free
  plan…").
- If **Clarity is already present alongside Hotjar**: flag the overlap — two
  session-recording tools means duplicated page weight and doubled privacy
  surface. Keep one (Clarity, on cost grounds).
- Whichever tool is kept **must sit behind the consent banner** — session
  recording before consent is a privacy finding in its own right.
