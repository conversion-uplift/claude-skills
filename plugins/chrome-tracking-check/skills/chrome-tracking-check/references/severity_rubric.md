# Severity rubric and grading

## Contents

1. Severity tiers
2. Scoring
3. Grade bands
4. Severity caps (agency standard)
5. Permitted figures
6. Confidence tiers
7. Finding ID quick reference
8. When the rubric disagrees with the aggregator
9. Why not weight by page count

## Severity tiers

| Tier | Meaning | Point deduction | Examples |
|---|---|---|---|
| **Critical** | Measurement is broken or compliance is at risk. Fix this week. | -15 | GA4 not firing; tags fire before consent default; Universal Analytics still loading; Consent Mode v2 missing on an EEA/UK site |
| **High** | Data is being collected but distorted, duplicated, or inconsistent. Fix this month. | -8 | Multiple GA4 measurement IDs; duplicate GTM container on the same page; Consent Mode v1 only; GA4 loaded but no page_view |
| **Medium** | Operational waste or minor risk. Fix this quarter. | -4 | No CMP detected; multiple Meta Pixel IDs; both GTM and standalone gtag; LCP > 4s |
| **Low** | Inefficiency or convention. Fix when convenient. | -1 | Multiple session-replay tools loaded together; Consent Mode default with no region; >30 analytics requests |
| **Info** | Positive signal or contextual data point. No deduction. | 0 | sGTM detected; LinkedIn Insight detected; TikTok Pixel detected |

## Scoring

Start at 100. Apply each finding's deduction once (a finding that affects 10 pages still deducts once — page count is evidence, not multiplier). Clamp final score to [0, 100].

## Grade bands

| Grade | Score | Plain English |
|---|---|---|
| **A** | 90–100 | Tracking is in a healthy state. Small refinements only. |
| **B** | 80–89 | Solid foundation, a few notable issues. Fix high-severity items. |
| **C** | 70–79 | Working but with meaningful gaps or risks. Plan a remediation sprint. |
| **D** | 60–69 | Significant problems likely affecting reporting and ad optimisation. Stop and fix before relying on the data. |
| **F** | <60 | Tracking is broken in ways that will materially affect business decisions. Treat as urgent. |

## Severity caps (agency standard)

These override the tier table above:

- **Verified Consent Mode caps consent findings at High.** If the four-state
  classification is advanced-verified-cookieless or basic, no consent finding
  may be Critical, and the consent axis cannot drive an E/F grade.
- **Personal data observed in a request payload is the only Critical/E-F path**
  on the consent and privacy axis.
- **Basic Consent Mode never scores worse than not-detected.**
- **Consent Mode with no region parameter is observation tier.** Record it;
  it never affects the grade.
- **One severity per issue.** The executive summary, the finding, the roadmap
  and any covering email state the same severity, and cross-references point at
  the section the finding actually lives in.
- **Consent findings are suppressed entirely** when the run could not establish
  a clean consent state (`clean_state: false`).

## Permitted figures

No percentage may appear in a report unless it was directly measured in this
capture (request counts, timings, page counts). No industry loss or uplift
figures.

## Confidence tiers

Severity tells the reader how bad a finding is. Confidence tells the reader how sure we are. The two are independent — a Critical finding can be Observed (definitely happening) or Inferred (heuristic suggests it). Confidence is rendered in the report directly under the severity badge.

| Tier | Meaning | Examples |
|---|---|---|
| **Observed** | Directly visible in the runtime — script tag present, network request fired, dataLayer event pushed | `GA4_NOT_DETECTED`, `GTM_DUPLICATE_CONTAINER`, `GA4_ECOMMERCE_LEGACY_SCHEMA`, `TRACKING_ENDPOINT_HTTP_ERROR`, `TAG_JAVASCRIPT_ERROR` |
| **Inferred** | Derived from heuristics — pattern matching, cross-source comparison, regex | `SGTM_DETECTED`, `ENHANCED_MEASUREMENT_DUPLICATE`, `PII_LEAK_IN_PARAMS`, `GA4_NO_KEY_EVENTS_OBSERVED`, `GA4_NO_CROSS_DOMAIN_LINKER` |
| **Verify** | Cannot be checked from the browser — needs property-side confirmation in the GA4 UI | `GA4_LIKELY_CONVERSIONS_UNVERIFIED`, anything covered in the "What the audit can't help" section of `ga4_event_taxonomy.md` |

### Confidence discipline (mandatory)

- **High / Observed is reserved for what the browser directly recorded.**
- Any finding whose cause lives inside **GTM or GA4 account configuration** —
  duplicate tags, trigger logic, conversion definitions, retention, internal
  traffic filters — caps at **Needs verification**, however obvious the symptom
  looks. You can see two hits; you cannot see which trigger produced them.
- **Verified-absent language** ("tested directly and confirmed absent",
  "verified not firing") is permitted **only in journey mode, and only for a
  journey step a human actually exercised**. Automated mode always writes
  "unverified rather than proven absent".

The audit's scoring math uses severity only — confidence does not affect the score. A Critical Inferred finding still deducts 15 points; the user is just warned to verify it before acting.

## Finding ID quick reference

For lookup when updating the scorer rubric:

```
GA4_NOT_DETECTED                  Critical  Observed
GA4_MISSING_ON_SOME_PAGES         Critical  Observed
GA4_MULTIPLE_MEASUREMENT_IDS      High      Observed
GA4_NO_PAGE_VIEW_EVENT            High      Observed
GA4_LEGACY_UA_DETECTED            High      Observed
GA4_ECOMMERCE_LEGACY_SCHEMA       High      Observed
GA4_ECOMMERCE_ITEMS_INCOMPLETE    High      Observed
GA4_NO_KEY_EVENTS_OBSERVED        High      Inferred
ENHANCED_MEASUREMENT_DUPLICATE    High      Inferred
GA4_NO_CROSS_DOMAIN_LINKER        High      Inferred
GA4_LIKELY_CONVERSIONS_UNVERIFIED Info      Verify
GTM_NOT_DETECTED                  Medium    Observed
GTM_DUPLICATE_CONTAINER           High      Observed
GTM_MULTIPLE_CONTAINERS           Medium    Observed
GTM_AND_STANDALONE_GTAG_BOTH      Medium    Observed
CONSENT_MODE_MISSING              Critical  Observed
CONSENT_MODE_V1_ONLY              High      Observed
CONSENT_MODE_NO_REGION            Low       Observed
CMP_NOT_DETECTED                  Medium    Observed
SGTM_DETECTED                     Info      Inferred
META_PIXEL_DUPLICATE              Medium    Observed
META_PIXEL_MULTIPLE_IDS           Medium    Observed
PII_LEAK_IN_PARAMS                Critical  Inferred
TAG_JAVASCRIPT_ERROR              High      Observed
TRACKING_ENDPOINT_HTTP_ERROR      Critical  Observed
MULTIPLE_SESSION_REPLAY_TOOLS     Low       Observed
LCP_POOR / CLS_POOR / INP_POOR    Medium    Observed
EXCESSIVE_ANALYTICS_REQUESTS      Low       Observed
```

## When the rubric disagrees with the aggregator

`scripts/severity_scorer.py` will override the aggregator's per-finding severity using the `SEVERITY_RUBRIC` dictionary keyed by finding `id`. The rubric is authoritative — if you think a different severity is correct, change the rubric, not the per-finding emission.

## Why not weight by page count

A `GA4_MISSING_ON_SOME_PAGES` finding that hits 1 page is almost as serious as one that hits 50: the *category* of problem is the same, and the remediation work (configuring the GA4 base tag correctly in GTM) is the same. Reporting it once with multiple evidence rows keeps the report scannable and the grade comparable across audits.

The only exception is when *every* page is broken — that's typically already covered by a different, more severe finding ID (e.g. `GA4_NOT_DETECTED` instead of `GA4_MISSING_ON_SOME_PAGES`).
