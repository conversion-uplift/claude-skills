# Microconversion taxonomy

Microconversions are the leading-indicator events that sit between page-view and hard conversion. Hard conversions tell you whether the funnel works; microconversions tell you WHERE in the funnel users drop off. The aggregator emits `MICROCONVERSION_NOT_TRACKED` when GA4 is firing but no microconversion-shaped events are observed across the audited pages.

## Why CRO depends on them

A site that only tracks `purchase` or `generate_lead` is reporting a single bottom-of-funnel number. Without microconversions you cannot:

- Build a drop-off funnel chart (need progressively narrower events from awareness to conversion).
- Diagnose why conversion rate dropped (is fewer people landing? viewing products? starting checkout? abandoning at payment?).
- Define audience segments for personalisation ("engaged but unconverted", "abandoned at payment").
- Run experiments on funnel improvements (you'd never see an effect on conversion rate from a checkout copy change — you need `add_payment_info` to see the lift).

## Recommended microconversions by site type

### Ecommerce (transactional)

| Stage | Event | When to fire |
|---|---|---|
| Engagement | `scroll` | At 25/50/75 % depth (not 90 % default) |
| Engagement | `view_item` | On product detail page render |
| Engagement | `select_item` | When user clicks a product card |
| Engagement | `add_to_wishlist` | If wishlist exists |
| Engagement | `view_search_results` | With `search_term` populated |
| Intent | `add_to_cart` | On successful add |
| Intent | `view_cart` | On cart page render |
| Intent | `begin_checkout` | First step of checkout |
| Intent | `add_shipping_info` | Shipping step submitted |
| Intent | `add_payment_info` | Payment step submitted |
| Conversion | `purchase` | Order placed |

### Lead-gen (B2B / SaaS)

| Stage | Event | When to fire |
|---|---|---|
| Engagement | `scroll` | At quartiles |
| Engagement | `file_download` | PDF / case study / brochure |
| Engagement | `video_start` / `video_progress` / `video_complete` | Demo video, explainer |
| Engagement | `view_pricing` | Pricing page render — strong intent signal |
| Engagement | `view_search_results` | Internal search |
| Intent | `form_start` | First field focus in the lead form |
| Intent | `form_submit` | Form successfully submitted (not before validation) |
| Intent | `request_demo` / `book_appointment` | Calendly / scheduler completion |
| Intent | `subscribe` | Newsletter / blog signup |
| Conversion | `generate_lead` | When CRM creates an MQL — usually server-side |
| Conversion | `sign_up` | Free trial / account created |

### Content / publisher

| Stage | Event | When to fire |
|---|---|---|
| Engagement | `scroll` | Quartiles |
| Engagement | `video_progress` | At 25/50/75/100 % |
| Engagement | `select_item` | Recommended-article click |
| Engagement | `share` | With `method` parameter |
| Intent | `subscribe` | Newsletter signup |
| Intent | `sign_up` | Registration |

## Naming conventions

Stick to GA4-recommended event names (`scroll`, `view_item`, `add_to_cart`) where possible — they ship with built-in reports. Avoid camelCase or kebab-case; snake_case is the standard. Don't invent custom equivalents of recommended events (a `productView` custom event when GA4 has `view_item` just creates orphaned data).

## Common implementation mistakes

- **Firing `form_submit` on the form-submit click before validation succeeds.** Validation failures count as submits. Fix: fire on the form's success callback, or server-side from the thank-you page.
- **Scroll firing only at 90 %.** GA4 Enhanced Measurement's default. Replace with a custom GTM tag that fires at 25/50/75/90 with a `percent_scrolled` parameter.
- **Microconversions with no `value` parameter.** Even an estimated value (e.g. average lead value ÷ form-submit-to-MQL ratio) lets GA4 calculate "conversion value per session" properly.
- **Duplicate firing.** Enhanced Measurement auto-tracks `scroll`/`click`/`file_download`/`video_*`/`form_*` — if you also fire custom GTM tags for the same events, you double-count. See finding `ENHANCED_MEASUREMENT_DUPLICATE`.
- **Microconversions tracked but not marked as conversions.** Microconversions don't need to be marked as conversions in GA4 — they're funnel signals, not goals. Conflating the two inflates conversion counts.

## How the aggregator uses this list

The aggregator's `MICROCONVERSION_EVENTS` set (defined inline in `aggregate_findings.py`) is the union of the engagement+intent rows above. If a site has GA4 firing but zero of those events appear anywhere, `MICROCONVERSION_NOT_TRACKED` fires at severity High. The recommendation tells the user to pick 3-5 events relevant to their funnel from the table above.
