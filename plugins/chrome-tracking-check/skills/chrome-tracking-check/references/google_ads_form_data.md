# Google Ads automatic form-data collection

Read this on any site running Google Ads (`AW-` tid) that has forms, which in
practice means every ecommerce and lead-gen site.

## What it is

Google Ads can detect and collect form interactions automatically, without a
tag being configured for the form and without the site owner necessarily
knowing it is on. It is adjacent to enhanced conversions but is **not** the
same thing: enhanced conversions is a deliberate configuration, whereas this
fires on Google's own automatic detection.

## Runtime signature

| Signal | What you see |
|---|---|
| Collection endpoint | a request whose path ends `/pagead/form-data/<ads-account-id>` |
| Event name | `en=form_start` on `/pagead/1p-user-list/<id>` and `/collect/<id>` |
| Hosts | `www.google.com`, `www.google.co.uk`, `googleads.g.doubleclick.net`, **or** the first-party Tag Gateway path where one exists |
| Consent | observed carrying `gcs=G111` after acceptance |

`probe.js` reports this as `network.adsFormData.formDataHits` and
`network.adsFormData.formStartEvents`.

## Why it matters, and the trap

**It fires on controls that are not conversion forms.** On one live site it triggered
when the tester clicked a **quantity spinner** on a product page, because the
input sits inside an ASP.NET `<form>`. That produces two distinct problems:

1. **Signal pollution.** Google Ads receives `form_start` from ordinary page
   furniture. Where a site has no real conversion events, as was the case
   there, `form_start` becomes the de facto bidding signal. Say so plainly in
   the report: it is a measurement finding, not just a privacy one.

2. **A personal-data pathway.** The same mechanism fires on checkout and
   contact forms carrying name, email, telephone and address. Whether field
   *values* are transmitted, and in what form, is the question that matters.

## How to report it, and what you must NOT do

**Claude never tests it by filling the form.** Entering contact details would
itself transmit data to Google, so the test creates the exposure it is trying
to measure. In journey mode the site owner may fill the form themselves, with
test data they have chosen and are happy to send (see
`journey_protocol.md`); tell them before they start if form-data collection is
firing on that page.

That means the honest reporting position is almost always:

> The mechanism is live and firing. Whether it captures checkout field values
> was not tested, because testing it would have transmitted data. Establishing
> what is actually collected needs a consented, monitored test alongside a
> review of the Google Ads account settings.

Severity and confidence:

- Mechanism observed firing: **Warning**, confidence **Needs account access**
  (the scope lives in account configuration, so rule 4 caps it).
- Personal data actually observed in a `form-data` payload: **Critical**. This
  is the one finding class that takes Privacy below the C pin (rule 6).
- Never write that data "is being sent to Google" when you observed only the
  endpoint firing. Write that the mechanism is active and name what is
  unverified.

## Remediation to recommend

- Review the Google Ads account: is automatic form-data collection deliberate,
  and is it scoped to real conversion forms?
- If it stays on, confirm it is gated behind the consent signal and that the
  privacy notice covers it. Frame as risk context, with the "worth confirming
  with your own legal and compliance advisers" hedge. Never legal advice.
- Where it fires on non-form controls, exclude those elements rather than
  accepting polluted bidding signal.
