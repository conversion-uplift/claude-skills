# GA4 event taxonomy — what to look for, what to recommend

## Contents

1. The four event categories GA4 cares about
2. Recommended events by site vertical
3. Required parameters per event
4. Schema differences: GA Universal → GA4
5. Reserved / restricted parameter names
6. Naming conventions
7. Verifying findings in GA4 DebugView
8. When the audit can't help

The aggregator references this doc when emitting findings about events, ecommerce schema, and conversion verification. Read it when explaining recommendations to the client.

## The four event categories GA4 cares about

| Category | Definition | Examples |
|---|---|---|
| Automatically collected | Fire without any code; you cannot turn off | `first_visit`, `session_start`, `user_engagement` |
| Enhanced Measurement | Fire if the Enhanced Measurement toggle is on for the Web Stream | `page_view`, `scroll`, `click` (outbound only), `view_search_results`, `video_*`, `file_download`, `form_start`, `form_submit` |
| Recommended | Predefined names that GA4 reports on with extra structure | `purchase`, `add_to_cart`, `sign_up`, `login`, `generate_lead`, `view_item`, etc. |
| Custom | Anything else | `cta_click_homepage_hero`, etc. |

The audit's `GA4_NO_KEY_EVENTS_OBSERVED` finding flags sites where none of the Recommended conversion-shaped events fire. The fix is almost always to implement the Recommended event with the right schema rather than invent a custom one — recommended events have ready-made reports.

## Recommended events by site vertical

### Ecommerce (transactional)

The full GA4 ecommerce funnel. Implement in this order:

- `view_item_list` — when a list of products is rendered (category page, search results)
- `select_item` — when a user clicks a product from a list
- `view_item` — on the product detail page
- `add_to_cart`
- `view_cart`
- `begin_checkout`
- `add_shipping_info`
- `add_payment_info`
- `purchase`
- `refund` — on cancellation/return

### Lead-gen (B2B / SaaS)

- `generate_lead` — primary conversion (any form submit that creates an MQL)
- `qualify_lead` — when sales qualifies the lead (server-side, via Measurement Protocol)
- `working_lead` — when sales engages
- `sign_up` — for free-trial signups
- `login` — for product logins
- `subscribe` — for newsletter / blog subscriptions
- `request_quote` — for quote requests
- `book_appointment` — for demo/meeting bookings

### Content / publisher

- `view_item` (treating articles as items)
- `select_item` (recommended-article clicks)
- `share` — when a user shares an article
- `subscribe` — newsletter signup
- `sign_up` — registration

## Required parameters per event

### `purchase` (and `refund`)

| Parameter | Required | Notes |
|---|---|---|
| `transaction_id` | Yes | Must be unique per order |
| `value` | Yes | Total order value |
| `currency` | Yes | ISO 4217 (e.g. `USD`, `GBP`) — without this, `value` is dropped |
| `coupon` | Optional | Order-level coupon |
| `shipping` | Optional | |
| `tax` | Optional | |
| `items` | Yes | Array of items — see schema below |

### `items[]` (every ecommerce event)

| Parameter | Required | Notes |
|---|---|---|
| `item_id` | Yes | Your SKU |
| `item_name` | Yes | Human-readable name |
| `price` | Recommended | Per-unit price |
| `quantity` | Recommended | Defaults to 1 |
| `currency` | Item-level optional (parent event is canonical) | Only set per-item if items are in different currencies |
| `item_brand`, `item_category`, `item_category2..5`, `item_variant`, `affiliation`, `coupon`, `discount`, `index`, `item_list_id`, `item_list_name`, `location_id`, `promotion_id`, `promotion_name` | Optional but recommended | Power GA4's item-scoped dimensions |

### `generate_lead`

| Parameter | Required | Notes |
|---|---|---|
| `value` | Optional | Estimated lead value if known |
| `currency` | Conditional | Required if `value` is set |
| `form_id` / `form_name` | Recommended | Custom params for distinguishing forms |

### `sign_up` / `login`

| Parameter | Required | Notes |
|---|---|---|
| `method` | Required | e.g. `Email`, `Google`, `SAML` |

## Schema differences: GA Universal → GA4

The audit's `GA4_ECOMMERCE_LEGACY_SCHEMA` finding fires when a site still uses the UA shape. Quick reference:

| GA Universal | GA4 |
|---|---|
| `ecommerce.purchase.actionField` | `ecommerce` (flattened — fields go directly on the event) |
| `ecommerce.purchase.products[]` | `ecommerce.items[]` (or `items[]` on the event) |
| `ecommerce.add.products[]` | `add_to_cart` event with `items[]` |
| `ecommerce.detail.products[]` | `view_item` event with `items[]` |
| `id` (product) | `item_id` |
| `name` (product) | `item_name` |
| `category` | `item_category` |
| `variant` | `item_variant` |

A common partial migration is to keep the GTM datalayer in UA shape and use a GTM Custom Template to translate. That works, but is brittle — sites should migrate the dataLayer at source.

## Reserved / restricted parameter names

Don't use these as event or parameter names:

- `_*` — anything starting with underscore is reserved by GA4
- `ga_*`, `google_*`, `firebase_*` — reserved namespaces
- `first_open`, `first_visit`, `session_start`, `user_engagement`, `app_*` — reserved event names

If you push these, GA4 silently drops the event.

## Naming conventions

GA4 strongly prefers `snake_case` for event and parameter names. CamelCase or kebab-case events do work but cannot be used in some Explorer report contexts. Standardise on `snake_case`.

## Verifying findings in GA4 DebugView

For every finding the audit emits, the client should verify in GA4 DebugView before and after the fix:

1. Open GA4 → Configure → DebugView.
2. Enable debug mode on the site, either by opening the page with the GA Debugger Chrome extension installed, or by appending `?_dbg=1` if a debug rule is set in GTM, or by using the GTM Preview Mode (which auto-enables `debug_mode: true`).
3. Trigger the action in question and watch the event stream.

The audit cannot verify any of this from the browser — it's a property-side check. Recommendations should always include "verify in DebugView" as the next step.

## When the audit can't help

The runtime audit cannot tell you:

- Whether a key event is **marked as a conversion** in GA4 (Admin → Events).
- Whether the event is **imported as a Google Ads conversion**.
- What the **data retention** setting is (Admin → Data Settings — default is 2 months, most marketers want 14).
- Whether **internal traffic is excluded** via IP filter (Admin → Data Streams → Tagging settings).
- Whether the **reporting identity** is User-ID, Device-ID, or Blended (Admin → Identity for reporting).
- Whether **BigQuery export** is enabled.

The report's recommendations roadmap should always include a final item: "Verify these property-side settings: data retention, internal traffic exclusion, conversion marking, reporting identity, BigQuery export."
