# Funnel-stage event expectations

The aggregator's `FUNNEL_STAGE_EVENT_MISSING` rule maps each page's `template_label` (set by page_discovery.py or by a recipe) to a funnel stage, and checks that at least one expected event for that stage was observed across the multi-capture inspection. The template→stage map is encoded in `aggregate_findings.py` (`FUNNEL_STAGE_EXPECTATIONS`); this doc is the human-readable source-of-truth.

## Default template → expected-events map

| Template label   | Funnel stage      | Expected events (one-of)                                  |
|------------------|-------------------|-----------------------------------------------------------|
| Homepage         | Awareness         | `page_view`, `scroll`                                     |
| Category         | Consideration     | `view_item_list`, `select_item`                           |
| Product          | Consideration     | `view_item`, `add_to_cart`                                |
| Cart             | Intent            | `view_cart`, `begin_checkout`                             |
| Checkout         | Intent            | `begin_checkout`, `add_shipping_info`, `add_payment_info` |
| Thank you        | Conversion        | `purchase`                                                |
| Sign up          | Conversion        | `sign_up`, `form_submit`                                  |
| Login            | Retention         | `login`                                                   |
| Contact          | Conversion        | `generate_lead`, `form_submit`                            |
| Pricing          | Intent            | `select_promotion`, `view_promotion`, `begin_checkout`    |
| Blog post        | Awareness         | `page_view`, `scroll`                                     |

## How the audit assigns templates

`page_discovery.py` clusters URLs by path-segment patterns and labels them with the simplest match (e.g. URLs under `/products/<slug>` collapse to `Product`). Platform recipes in `recipes/` can override this mapping (Shopify ships with explicit `Product`, `Cart`, `Account login` labels; WooCommerce ships with `Shop`, `Category`, `Cart`, `Checkout`).

When a page's template_label does NOT appear in the table above, the aggregator skips the rule for that page rather than emit a false positive. So a custom template (`Knowledge base`, `Press release`) won't trigger the rule unless you extend the map.

## Extending the map for a specific client

Edit `FUNNEL_STAGE_EXPECTATIONS` in `aggregate_findings.py` for one-off audits, or — better — add the expectations to a custom recipe in `recipes/<client>.json` and have the recipe loader merge them in. Recipes are the right place for site-specific knowledge ("our Wishlist template uses `add_to_wishlist` not `add_to_cart`") because they travel with the platform.

## Why "one-of" not "all-of"

A Product page rendering `view_item` is healthy; the additional `add_to_cart` will only fire if the user clicks the button. The audit visits without clicking unless an interaction is scripted by the recipe. Requiring all expected events would create false positives on every static inspection. The rule's intent is "is *any* meaningful event firing here?", not "is every event firing?".

If you want a stricter test that asserts the click-driven events too, use the recipe's `interactions` array to script the click and re-run the inspection. The aggregator will then see the additional event in the captures and the rule passes more strongly.

## What the rule catches in practice

The most common failure pattern in real audits: a marketing team migrates a site (CMS rebuild, A/B test rollout) and ships GA4 firing `page_view` on every URL, but the Product template's `view_item` tag wasn't ported. GA4 reports look fine because pageviews are healthy, but the ecommerce-funnel report is blank from `view_item` onwards. The audit flags this as `FUNNEL_STAGE_EVENT_MISSING` on Product, with severity High and confidence Inferred.

## Pairing with the microconversion rule

`MICROCONVERSION_NOT_TRACKED` is the site-wide version of this check — "no microconversions anywhere on the site". `FUNNEL_STAGE_EVENT_MISSING` is the template-level version — "this specific stage has nothing firing". The two together give you both the bird's-eye view ("the site has no funnel signal") and the surgical view ("the Cart template specifically is broken").
