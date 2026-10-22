# Changelog

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
