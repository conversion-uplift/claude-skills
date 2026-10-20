# Google Consent Mode v2 — expected state and gotchas

## Contents

1. What v2 requires
2. What the runtime should look like
3. Four-state classification — apply this before any failure mode
4. Common failure modes
5. What the audit checks
6. Pre-consent vs post-consent

## What v2 requires

Consent Mode v2 (mandatory since March 2024 for any advertiser serving EEA/UK users with Google Ads or GA4 audiences/conversions) requires **four** signals, not the two from v1.

| Signal | Purpose |
|---|---|
| `ad_storage` | (v1) Cookies for advertising |
| `analytics_storage` | (v1) Cookies for analytics |
| `ad_user_data` | (v2) Send user data to Google for ads |
| `ad_personalization` | (v2) Use data for personalised ads |

A site that only sends `ad_storage` and `analytics_storage` is "Consent Mode v1 only" — a finding of severity **High**.

## What the runtime should look like

The very first thing in the dataLayer (before any GTM/gtag init) should be a default consent call:

```js
gtag('consent', 'default', {
  ad_storage:           'denied',
  ad_user_data:         'denied',
  ad_personalization:   'denied',
  analytics_storage:    'denied',
  region:               ['EEA', 'GB'],
  wait_for_update:      500,
});
```

Then, after the CMP captures user consent, an update call:

```js
gtag('consent', 'update', {
  ad_storage:         'granted',
  ad_user_data:       'granted',
  ad_personalization: 'granted',
  analytics_storage:  'granted',
});
```

`wait_for_update` (in milliseconds) tells Google's tags to hold beacons that long so the update can arrive first. Typical values are 500-2000ms. Missing or 0 = tags may fire with default-denied state and lose data.

## Four-state classification — apply this before any failure mode

Every audit classifies Consent Mode into exactly ONE of four states. **None of
them is ever rendered as "absent".**

**1. Advanced, verified cookieless.** All three must hold:
   - pre-consent Google measurement requests carry a denied signal (`gcs=G100`);
   - no Google cookies are written before the visitor chooses;
   - hits upgrade cleanly to `gcs=G111` after acceptance.

**2. Advanced, not verified.** Signals are present but one of the three checks
   above could not be confirmed. Name which one.

**3. Basic.** All three required:
   - a consent default of denied is present;
   - **no Google measurement requests fire pre-consent**;
   - hits show `gcs=G111` after accept.

   When judging "no Google measurement requests", **exclude the GTM container
   and the gtag.js loader themselves**. Loading the library is not measurement;
   only collection endpoints count.

   Implication copy: *"Consent gates correctly, but because no cookieless pings
   are sent before consent, Google has nothing to model from. Visitors who
   decline are never recorded at all, so there are no modelled conversions."*

   **Basic never scores worse than not-detected.** It is a legitimate, working
   and more privacy-conservative configuration.

**4. Not classifiable.** Evidence was insufficient. Render as "not classifiable
   from this scan", name the missing evidence, and give the Tag Assistant or
   DebugView step that would settle it.

**Severity cap.** When Consent Mode is verified (state 1 or 3), consent
findings cap at **High**. The only route to Critical on this axis is personal
data observed in a request payload.

**Testability gate.** All of the above requires a clean consent state. If the
profile had already accepted, classification is not possible and the run emits
`CONSENT_NOT_TESTABLE` instead. See `capture_and_claim_rules.md` rule 2.

## Common failure modes

1. **No `consent('default', ...)` call at all.** Tags fire with no consent signal. For Google Ads conversions in the EEA this means measurement is effectively off. → finding `CONSENT_MODE_MISSING`, **Critical**.
2. **Default consent fires AFTER the first GA4 `event` or `config`.** Ordering is wrong; tags fired without honouring defaults. → `CONSENT_MODE_DEFAULT_AFTER_TAGS`, **Critical**.
3. **Only v1 signals (`ad_storage`, `analytics_storage`) present.** v2-required signals missing. → `CONSENT_MODE_V1_ONLY`, **High**.
4. **No `region` parameter.** Denied-by-default then applies worldwide, including non-EEA users. Usually unintended outside the EEA/UK. → `CONSENT_MODE_NO_REGION`, **observation tier: record it, never let it affect the grade**.
5. **CMP present but no consent calls.** The CMP is decorative, not wired to Google tags. → flag both `CMP_NOT_DETECTED` (if missed) and a custom note in the report.
6. **Default = granted everywhere.** Some implementations set everything to `granted` by default and never call `update`. This satisfies the runtime but violates the legal intent — flag as Medium with a note recommending review.

## What the audit checks

`scripts/inspectors/probe.js` reads `window.dataLayer` in order and emits:

- `consentModeDetected` — any `['consent', ...]` entry exists
- `defaultConsentCallFound` — `['consent', 'default', ...]` exists
- `updateConsentCallFound` — `['consent', 'update', ...]` exists
- `defaultStateRaw` — the actual payload passed to default
- `v2SignalsPresent` — both `ad_user_data` and `ad_personalization` present in the default payload
- `waitForUpdateMs` — value of `wait_for_update`
- `regionTargeting` — array of regions
- `tagsFiredBeforeDefault` — any GA4 `config`/`event` whose dataLayer index is *before* the first default-consent index

## Pre-consent vs post-consent

The audit runs each page twice:

- **Pre-consent**: tells us what defaults are. The "Critical" check is whether *any tags fired before defaults*.
- **Post-consent**: tells us what tags are actually consent-gated. If GA4 events are identical pre- and post-consent, either Consent Mode isn't wired or everything was defaulted to `granted`.

The comparison between the two passes is itself evidence in the report.
