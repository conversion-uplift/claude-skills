# Changelog

## chrome-tracking-check 1.1.0 (November 2026)

- **Data layer documentation.** New `probe_datalayer.js` reads the data layer's
  shape (key names and types, never values), forms (field names only) and the
  form platform. New `datalayer_spec.py` turns it into `DL_*` findings, a
  report appendix and a Markdown specification with the target push for every
  GA4 ecommerce event and for lead form submissions, plus the success signal
  for 20 form platforms.
- Checks: Universal Analytics ecommerce shape, pushes not cleared with
  `ecommerce: null`, missing `items`/`transaction_id`/`currency`, invalid
  currency codes, money sent as text, items without an ID or name, duplicate
  pushes, value that doesn't match the items, personal data outside
  `user_data`, leads counted from `gtm.formSubmit` only, lead events with no
  form identifier, and enquiry forms with no hidden click-ID fields.
- Every data layer finding names who fixes it (developer or GTM owner), and
  the journey cross-check says whether a gap is the push or the tag.
- One severity per issue: a data layer finding that explains a problem already
  graded becomes an Info root-cause note, so the grade is not docked twice.
- The Word report now shows Info findings that are not positives (causes,
  untestable checks) under "Notes for whoever fixes this". Previously they were
  dropped.
- Fix: `event_contracts.json` treated `value` and `currency` as required on
  `view_item`, `add_to_cart` and the other pre-purchase events. GA4 only
  requires `currency` when `value` is sent, so those events no longer raise
  `GA4_EVENT_PARAM_MISSING` for it.
- Self-test covers the data layer; new browser-free `test_datalayer_spec.py`.

## gtm-google-tag-upgrade-review 1.0.0 (October 2026)

First public release.

- Read-only review of a GTM container and its Google tags before Google's
  container upgrade, through Claude in Chrome.
- Compares all 12 Google tag settings, recommends which tag's settings the
  container should keep, and rates the risks (enhanced conversions, session
  timeout, consent, access, lookup tables, gtag.config triggers).
- Word report and a draft covering email. Rules last verified 22/10/2026.
- `scripts/build_zip.sh` now builds any skill in the repo (or all of them).

## chrome-tracking-check 1.0.0 (October 2026)

First public release.

- Automated mode: page discovery, two passes per page (before and after the
  cookie banner), deterministic rules, A to F grade, Word report, CSV, JSON
  and BigQuery exports.
- Journey mode: the site owner adds to basket, checks out, submits a form or
  places a test order while Claude records each step. Claude never clicks
  submit or pay and never types into forms.
- Personal data stays in the page: URLs are reported as origin, path and
  parameter names; emails and phone numbers are flagged, never recorded.
- Self-test against a local fake shop (`tests/run_fixture.py`).
