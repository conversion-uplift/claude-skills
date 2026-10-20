# GA4 validation rules — cross-page checks and finding IDs

These are the canonical findings the aggregation phase emits. Each has a stable `id` so the report builder and severity scorer can look it up. Don't invent new IDs — extend this table instead.

## How aggregation works

After Phase 2 (per-page inspection), you have an array of per-page audit results, each containing:

```
{
  url, template_label,
  pre_consent: {
    tag_inventory: {...},     // from probe.js
    consent: {...},           // from probe.js
    vendors: {...},           // from probe.js
    performance: {...},       // from probe.js and probe_baseline.js
    network: {...},           // from probe.js
  },
  post_consent: { ...same shape... },
}
```

Walk the array, run the rules below, and emit findings with one evidence row per matching page.

## Rules

### GA4 coverage

| id | When to emit | Severity | Suggested title |
|---|---|---|---|
| `GA4_NOT_DETECTED` | No page has any `G-` measurement id in either pass | Critical | "GA4 is not firing on this site" |
| `GA4_MISSING_ON_SOME_PAGES` | At least one page has `G-` IDs but ≥1 page has none | Critical | "GA4 is missing on some pages" |
| `GA4_MULTIPLE_MEASUREMENT_IDS` | Distinct set of `G-XXX` IDs across pages has count > 1 (and they don't all appear on every page) | High | "Multiple GA4 measurement IDs detected" |
| `GA4_NO_PAGE_VIEW_EVENT` | GA4 detected but no `page_view` event in dataLayer or no `/g/collect?...&en=page_view` in network | High | "GA4 is loaded but not sending page_view" |
| `GA4_LEGACY_UA_DETECTED` | Any `UA-` config id present | High | "Sunset Universal Analytics tag still loading" |

### GTM

| id | When to emit | Severity | Title |
|---|---|---|---|
| `GTM_NOT_DETECTED` | No GTM container on any page | Medium | "No Google Tag Manager container detected" |
| `GTM_DUPLICATE_CONTAINER` | Same GTM-XXX loaded ≥2 times on a single page | High | "GTM container loaded twice on the same page" |
| `GTM_MULTIPLE_CONTAINERS` | ≥2 distinct GTM containers loaded on the same page | Medium | "Multiple GTM containers on one page" |
| `GTM_AND_STANDALONE_GTAG_BOTH` | Same page has both `gtm.js` AND a standalone `gtag/js?id=...` script | Medium | "GTM and standalone gtag.js both present" |

### Consent Mode v2

| id | When to emit | Severity | Title |
|---|---|---|---|
| `CONSENT_MODE_MISSING` | `consentModeDetected: false` on every page AND any tracking tag fires | Critical | "Consent Mode v2 not implemented" |
| `CONSENT_MODE_V1_ONLY` | `consentModeDetected: true` but `v2SignalsPresent: false` | High | "Consent Mode v1 only — v2 signals missing" |
| `CONSENT_MODE_DEFAULT_AFTER_TAGS` | Any page has `tagsFiredBeforeDefault.length > 0` | Critical | "Tags fire before Consent Mode default is set" |
| `CONSENT_MODE_NO_REGION` | Default consent calls present but `regionTargeting` is empty | Low | "Consent Mode default applies globally" |
| `CMP_NOT_DETECTED` | No CMP signature matched on any page AND no `__tcfapi` | Medium | "No consent management platform detected" |

### Server-side GTM

| id | When to emit | Severity | Title |
|---|---|---|---|
| `SGTM_DETECTED` | `probableSgtmHits` non-empty on any page | Info | "Server-side GTM detected (positive signal)" |

### Marketing pixels

| id | When | Severity | Title |
|---|---|---|---|
| `META_PIXEL_DUPLICATE` | Same pixel id loaded ≥2 times on one page | Medium | "Meta Pixel loads twice on the same page" |
| `META_PIXEL_MULTIPLE_IDS` | ≥2 distinct Meta Pixel IDs firing on the same page | Medium | "Multiple Meta Pixel IDs firing" |
| `LINKEDIN_INSIGHT_PRESENT` | LinkedIn Insight detected (informational unless duplicated) | Info | "LinkedIn Insight Tag detected" |
| `TIKTOK_PIXEL_PRESENT` | TikTok Pixel detected | Info | "TikTok Pixel detected" |

### Tool overlap

| id | When | Severity | Title |
|---|---|---|---|
| `MULTIPLE_SESSION_REPLAY_TOOLS` | ≥2 of (Hotjar, FullStory, Mouseflow, Lucky Orange, Smartlook, Clarity) detected on the same page | Low | "Multiple session-replay/heatmap tools loaded together" |

Note: this is severity Low not because it's harmless — it's wasteful and increases page weight — but because it doesn't break measurement. Mention the page-weight cost in the recommendation.

### Performance context (informational, but graded)

| id | When | Severity | Title |
|---|---|---|---|
| `LCP_POOR` | Any page has LCP > 4000ms | Medium | "Poor Largest Contentful Paint" |
| `CLS_POOR` | Any page has CLS > 0.25 | Medium | "Poor Cumulative Layout Shift" |
| `INP_POOR` | Any page has INP_approx > 500ms | Medium | "Slow interaction response (INP)" |
| `EXCESSIVE_ANALYTICS_REQUESTS` | Any page has >30 analytics-related resource requests | Low | "High analytics request count" |

## Writing the description and recommendation

For each finding emitted, the aggregator should populate:

- `description` — what was observed, in plain English, with specifics ("Pages /pricing and /contact have no `G-` measurement id in either consent state").
- `recommendation` — the fix, written so a marketing lead can hand it to a developer. Be specific. Don't say "fix tracking", say "Configure the GA4 base tag in GTM to fire on All Pages".
- `evidence` — array of `{url, detail}`. Detail should be the specific observation for that URL, not generic copy.

## Positive findings

Emit a positive finding when the site does something correctly that's worth calling out — Consent Mode v2 fully wired, server-side GTM in place, consistent measurement IDs across templates. Set `"positive": true` so the report builder routes it to the "What's working well" section.
