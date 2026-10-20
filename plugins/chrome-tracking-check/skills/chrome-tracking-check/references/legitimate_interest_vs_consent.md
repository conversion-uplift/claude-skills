# Legitimate interest vs consent — what the audit flags and why

The audit's `PRIVACY_LEGITIMATE_INTEREST_FOR_ADS` rule fires when ad-related TCF v2 purposes (3, 4, 5, 6, 7) are granted only under `legitimateInterests` and not under `consents`. This is one of the most common GDPR/UK-GDPR non-compliance patterns and it routinely fails enforcement scrutiny.

## The legal hierarchy

UK-GDPR / EU-GDPR Article 6 lists six lawful bases for processing personal data. Two are relevant for analytics and advertising tracking:

- **Article 6(1)(a) — Consent.** A freely-given, specific, informed, unambiguous opt-in. The user can withdraw consent at any time and that withdrawal must be as easy as giving it.
- **Article 6(1)(f) — Legitimate interest.** The controller's legitimate interest, provided it's not overridden by the data subject's rights. Requires a documented Legitimate Interest Assessment (LIA).

For special-category data (Article 9 — health, race, political opinion, etc.) NEITHER is enough; you need an explicit Article 9 condition.

## Why the audit flags ad purposes via LI

1. **Google's own policy requires consent for ad personalisation.** As of Consent Mode v2 (March 2024) Google Ads and GA4 audience builders treat `ad_storage`, `ad_user_data`, and `ad_personalization` as consent-required. If a TCF string asserts purpose 3 (personalised ads) under LI only, Google's downstream systems will drop the bid or refuse audience inclusion regardless of what the IAB framework permits. The data is collected but useless.

2. **EDPB and national supervisory authorities have rejected LI for advertising.** The EDPB's 2024 opinion 28/2024 and earlier guidance is unambiguous that targeted advertising at the scale of TCF cannot rest on legitimate interest. CNIL, AEPD, Garante, and the ICO have all issued decisions against publishers and CMPs using LI as the lawful basis for ad personalisation.

3. **The IAB's own framework was found non-compliant.** The 2022 Belgian DPA decision against IAB Europe confirmed the TCF as deployed did not provide a valid lawful basis. TCF 2.2 (2024) tightened the consent vs LI distinction but the burden is still on the deploying publisher.

## TCF v2.2 purposes — quick map

| # | Purpose | Realistic basis |
|---|---|---|
| 1 | Store and access information on a device (cookies) | Consent (ePrivacy Directive Art. 5(3)) |
| 2 | Use limited data to select advertising | Consent recommended; LI risky |
| 3 | Create profiles for personalised advertising | **Consent only** |
| 4 | Use profiles to select personalised advertising | **Consent only** |
| 5 | Create profiles to personalise content | **Consent only** |
| 6 | Use profiles to select personalised content | **Consent only** |
| 7 | Measure advertising performance | Consent recommended; LI debatable |
| 8 | Measure content performance | LI defensible if narrow analytics use |
| 9 | Understand audiences through statistics | LI risky |
| 10 | Develop and improve services | LI defensible |
| 11 | Use limited data to select content | Consent recommended |

Two special features: precise geolocation and active device-fingerprinting both require consent.

## Analytics-specific nuance

The audit deliberately does NOT flag purposes 7 or 8 (measurement) via LI as Critical. A narrow LI argument exists for first-party analytics provided data is aggregated, IPs anonymised at collection, retention short, and a right-to-object mechanism is exposed. Where analytics feeds ad audiences, the LI defence collapses — that's why the audit focuses on ad purposes specifically.

## Confidence tier

The finding is **Observed** when `window.__tcfapi`'s cached response shows the LI-only pattern. If the cache isn't readable synchronously, the audit downgrades to **Verify** and recommends running the IAB validator manually.

## What the audit does NOT check

- Whether the LIA is documented in the privacy programme.
- Whether the consent banner has equal "Reject all" and "Accept all" prominence.
- Whether vendors in the CMP's vendor list match those actually loading.
- Whether the "withdraw consent" UI is as easy to find as the initial banner.

These remain manual checks for the analyst.
