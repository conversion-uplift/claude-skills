# Documenting the data layer (ecommerce and lead forms)

Read this before running `probe_datalayer.js`. The aim is a specification a
developer can build from and a GTM owner can map tags to: what the site pushes
today, the gaps, and the target push for each event.

## Contents

1. Why the data layer gets its own check
2. Where to run the probe
3. Recording the output
4. Running the generator
5. What the statuses mean (claim discipline)
6. Ecommerce essentials
7. Lead form essentials
8. Who fixes what

## 1. Why the data layer gets its own check

`probe.js` sees what reached GA4 and the ad platforms. It cannot tell *why* an
event is wrong. The data layer is the contract between the site's developers
and the tag manager, so checking it splits every problem into one of two jobs:

- **Developer:** the push is missing, malformed, duplicated or carries
  personal data.
- **GTM owner:** the push is correct but no tag sent it, or a tag reads the
  wrong key.

Clients pay for that split: it ends the "is it the website or the tags?"
argument.

## 2. Where to run the probe

`probe_datalayer.js` is about 12KB, so run it on the pages that matter, not
every page. After `probe.js`, in the post-consent pass:

| Site type | Pages | Set `datalayer_expect` to |
|---|---|---|
| Ecommerce | Category or search results | `["view_item_list"]` |
| | Product | `["view_item"]` |
| | Basket (if it has its own URL) | `["view_cart"]` |
| | Checkout first page | `["begin_checkout"]` |
| Lead generation | Contact, quote, demo and booking pages | `[]` (form inventory) |
| | Thank-you page, fetched or visited directly | `[]` |

In journey mode, run it after **every** step, straight after `probe_delta.js`
(or `probe.js` when the step navigated). It marks entries pushed after
`probe_baseline.js` as `afterBaseline`, which is how a step finds its own
pushes. On a confirmation page reached by navigation the baseline is gone,
so every entry on that page belongs to the step.

Only put an event in `datalayer_expect` when that page should push it on
load. Interaction events (`add_to_cart`, `select_item`, `generate_lead`) are
judged from journey steps, never from a page load.

## 3. Recording the output

- Page records: `"datalayer": <probe output>` and `"datalayer_expect": [...]`
  in `audit_per_page.json`.
- Journey steps: `"datalayer": <probe output>` on the step record in
  `journey.json`.

The probe returns key names, types and a short list of safe values. It never
returns form field values, and an email or phone number anywhere in the data
layer comes back as a flag with its key path. Do not add values by hand.

## 4. Running the generator

After `aggregate_findings.py` (and `journey_checks.py` in journey mode):

```bash
python scripts/datalayer_spec.py --per-page audit_per_page.json \
  [--journey journey.json] --aggregated audit_aggregated.json \
  --output audit_aggregated.json --doc datalayer_spec_<domain>_<YYYYMMDD>.md \
  --csv datalayer_<domain>_<YYYYMMDD>.csv [--site-type ecommerce|lead_gen|mixed]
```

It adds `DL_*` findings, an Appendix C table for the Word report, a Markdown
specification for the developer and a CSV of every observed key. When a data
layer finding describes the same problem as a finding already graded (for
example a missing `currency` that also shows as `GA4_EVENT_PARAM_MISSING`),
it is kept as an Info "root cause" note so the grade is not docked twice.

Hand over the Markdown file with the report. It is the deliverable a
developer actually works from.

## 5. What the statuses mean (claim discipline)

| Status | Meaning | Allowed when |
|---|---|---|
| Pushed | Seen, well formed | The probe captured it |
| Pushed, with gaps | Seen, issues listed | The probe captured it |
| Not pushed | Checked and absent | The page or step that should push it was captured |
| Not tested | Nothing known | Anything else |

Never write "not pushed" for an event nobody exercised. In automated mode,
`add_to_cart` and `generate_lead` are almost always "Not tested".

## 6. Ecommerce essentials

The full target shapes are in `datalayer_contracts.json` and the generated
specification. The rules every push must follow:

- `dataLayer.push({ ecommerce: null })` before every ecommerce event. GTM
  merges pushes, so without the clear, items from one event leak into the next.
- `items[]` on every ecommerce event; each item has `item_id` or `item_name`
  (send both), plus `price` (number) and `quantity` (integer).
- `currency` (ISO 4217, upper case) whenever `value` is sent.
- `value`, `tax`, `shipping`, `price` are numbers: `24.99`, never `"£24.99"`.
- `purchase` once per order, on confirmation, with a unique `transaction_id`.
  A reload of the confirmation page must not push it again.
- The old Universal Analytics shape (`ecommerce.add.products[]`,
  `ecommerce.purchase.actionField`) is a High finding even when a GTM
  variable re-maps it, because every new tag has to repeat the mapping.
- Platform plugins (Shopify, WooCommerce, Magento) often push their own
  events alongside a GTM integration. Two pushes of the same event for one
  action is a duplicate, whichever plugin sent it.

## 7. Lead form essentials

- Fire `generate_lead` from the form platform's **success** signal, never
  from the submit click. GTM's built-in `gtm.formSubmit` and enhanced
  measurement's `form_submit` fire on the attempt, including failed
  validation, and often miss AJAX forms entirely.
- The probe lists the form platforms it recognises (`formVendors`) and the
  specification gives the success signal for each (HubSpot, Contact Form 7,
  Gravity Forms, Marketo, Calendly and others). Where a signal is marked
  "verify", say so in the report.
- Every lead push says which form it came from: `form_id`, `form_name`,
  `form_type`. Without them all leads are valued the same.
- Enhanced conversions data belongs under `user_data`, pushed after consent
  and read only by the Google tag's user-provided data variable. An email or
  phone number under any other key is a High finding.
- Hidden click-ID fields (`gclid`, `gbraid`, `wbraid`, `msclkid`, UTMs) let
  the CRM send qualified leads and sales back to the ad platforms. Their
  absence is Low and Inferred: the CRM may capture them another way.
- `qualify_lead`, `working_lead`, `close_convert_lead` and the rest of
  GA4's lead lifecycle come from the CRM (Measurement Protocol or offline
  import), not the website. Mention them; don't expect them in the browser.
- The rules in `journey_protocol.md` still bind: Claude never types into
  or submits a form. The person submits; the probe reads the result.

## 8. Who fixes what

Every `DL_*` finding carries an `owner`: **Developer** (the push) or **GTM**
(the tags reading it). The report prints it under the finding, and the
specification's summary table has a "Who fixes" column. Use the same split in
the covering message.
