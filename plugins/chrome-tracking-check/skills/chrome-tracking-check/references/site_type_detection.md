# Site type & ecommerce platform detection

Site type controls which human-led journey runs (ecommerce or lead form) and
which expected events the journey checks look for. Platform identity
predicts the expected dataLayer shape and common duplication patterns, and is
named in the report.

## Site types

| Type | Signals |
|---|---|
| **Ecommerce** | cart/checkout URLs (`/cart`, `/checkout`, `/basket`), add-to-basket controls, `Product` schema.org markup, prices on listing pages, `Shopify`/Woo globals, currency symbols in CTAs |
| **Lead generation** | enquiry/contact/quote forms as primary CTAs, phone-number CTAs (`tel:` links in header), "request a demo/quote/callback", no cart |
| **Content / publisher** | article templates, ads/affiliate links, newsletter signups as primary conversion, no cart or enquiry emphasis |
| **Booking / ticketing** | date pickers, availability widgets, "book now"/"buy tickets", third-party booking iframes (often a separate domain — note the cross-domain implication) |

**If not confident, or the site is mixed (e.g. ecommerce plus lead forms):
STOP and ask the user with a multiple-choice question (AskUserQuestion) rather
than guessing.** A mixed site can run both walks; ask which conversion matters
most.

## Ecommerce platforms

Name the platform in the report. Signals in priority order (network > global >
markup):

| Platform | Signals |
|---|---|
| **Shopify** | `window.Shopify`, `cdn.shopify.com` scripts, `/cart.js`, `/cdn/shop/` asset paths, `Shopify.shop` domain. Expect Customer Events (`shopify_Y` pixels) and/or a GTM dataLayer; classic duplication: theme-embedded gtag + GTM + a Shopify app all firing GA4 |
| **WooCommerce** | `wp-content/plugins/woocommerce`, `wc-ajax` endpoints, `woocommerce` body classes. Duplication pattern: multiple GA plugins (Site Kit + WooCommerce Google Analytics + GTM) |
| **Magento / Adobe Commerce** | `mage-` prefixed globals/cookies, `Magento_` module paths in requireJS, `/static/version...` asset URLs |
| **BigCommerce** | `cdn*.bigcommerce.com` assets, `window.BCData`, `stencil` theme markers |
| **Salesforce Commerce Cloud** | `demandware` in URLs/cookies (`dwanonymous_*`, `/on/demandware.store/`), `dw` globals |
| **Shopware** | `window.Shopware`, `/widgets/` + `sw-` markers, `shopware` cookies |
| **PrestaShop** | `window.prestashop`, `presta` cookies, `/modules/ps_` asset paths |
| **Wix** | `wix.com` / `parastorage.com` scripts, `wixBiSession` |
| **Squarespace** | `squarespace.com` / `sqsp.net` scripts, `Static.SQUARESPACE_CONTEXT` |
| **Custom / headless** | `#__NEXT_DATA__` (Next.js) or `window.__NUXT__` (Nuxt) plus commerce API calls (`/api/cart`, GraphQL commerce mutations, `commercetools`/`shopify/storefront-api` endpoints). Report as "custom/headless (framework + commerce API)" |

Platform recipes live in `recipes/<platform>.json` — use them for template
URLs, expected interactions and known suppressions. Extend a recipe rather
than hard-coding platform knowledge elsewhere.

## Why platform matters for the audit

- **Expected dataLayer shape.** Shopify Customer Events vs a GTM ecommerce
  dataLayer vs Woo's plugin-generated pushes all look different; "no dataLayer
  ecommerce object" is normal on a Customer-Events-only Shopify store.
- **Common duplication patterns** per platform (see table above and
  `duplicate_event_patterns.md`).
- **Checkout reachability.** Shopify checkout (`checkout.shopify.com` or
  `/checkouts/`) restricts third-party scripts — GTM absent at checkout is a
  platform constraint, not necessarily a fault; say so honestly.
- **Suppression hygiene.** Platform cookies that look like PII but aren't
  (Shopify `_y`) are suppressed via recipe.
