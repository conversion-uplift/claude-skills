# Changelog

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
