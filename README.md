# Chrome Tracking Check: a free Claude skill for GA4, GTM and ad tracking

Chrome Tracking Check watches what your website actually sends to GA4, Google
Ads, Meta and the other platforms, using the Claude in Chrome extension, and
writes a Word report: findings rated by severity, the evidence for each, an A
to F grade, and CSV and JSON exports.

It has two modes:

- **Automated.** Claude loads a sample of your page templates before and after
  the cookie banner and checks GA4, GTM, Consent Mode, duplicate events, ad
  pixels and console errors.
- **Journey.** You add to basket, go through checkout, submit a form or place a
  test order. Claude records what was sent at each step and checks the
  conversion events fire once, with the right values, to every platform on the
  site. Claude never clicks submit or pay and never types into your forms.

The full guide, with the DevTools checks it automates, is at
[conversion-uplift.co.uk](https://conversion-uplift.co.uk/post/how-to-use-chrome-dev-tools-for-debugging-google-analytics-and-gtm/).

## What you need

- A paid Claude plan (Pro, Max, Team or Enterprise).
- [Claude in Chrome](https://chromewebstore.google.com/detail/claude/fcoeoabgfenejglbffodgkkbkcdhcgfn), signed in and connected.
- Code execution turned on (Settings, Capabilities). The scripts use Python and
  `python-docx`.
- The Claude desktop app, or Claude Code started with `claude --chrome`.

## Install

**In Claude (desktop or web):** download `chrome-tracking-check.zip` from
[Releases](../../releases), then go to Customize, Skills, click +, choose
Create skill, then Upload a skill, and upload the ZIP. Turn it on.

**In Claude Code:**

```
/plugin marketplace add conversion-uplift/claude-skills
/plugin install chrome-tracking-check@conversion-uplift
```

Then ask Claude to "check the tracking on https://yoursite.com", or "walk the
checkout with me and check the tracking" for journey mode.

## Read it before you install it

Do this with any skill, ours included. Everything the skill runs is in
`plugins/chrome-tracking-check/skills/chrome-tracking-check/`:

- `scripts/inspectors/probe.js` is the JavaScript it runs in your pages. It is
  about 10KB and readable. It reads the page, the data layer, cookie names and
  the measurement requests the page has made, and returns them to Claude. It
  sends nothing anywhere.
- Personal data stays in the page. URLs are reported as origin, path and
  parameter names. If an email address or phone number appears in a tracking
  request, the report records that it was there and where, never the value.
- The Python scripts run on your machine. `page_discovery.py` fetches your
  robots.txt, sitemap and homepage. `geo_lookup.py` calls ipinfo.io (which
  sees your public IP address) only if you agree and it is run with `--lookup`.
  Nothing else makes network calls.
- The rules that decide findings and grades are in
  `scripts/aggregate_findings.py` and `scripts/journey_checks.py`. If you think
  a finding is wrong, the rule that produced it is there to read.

## Use it on sites you're allowed to test

Automated mode only loads pages, as any visitor would. Journey mode is for
sites you own or have written permission to test: it asks you to confirm
before it starts. A test order on a live site is a real order. The skill
explains what that involves (emails, stock, ad platform conversions) and the
safer options before you decide.

## What it can't tell you

A browser check sees what the browser sent on the day. It can't see your GA4,
GTM or ad account settings, server-side Conversions API traffic, or whether
your consent set-up meets the law in your country. Findings that depend on
those are marked "Inferred" or "Verify". Confirm any fix in GA4 DebugView.

## Self-test

`tests/run_fixture.py` runs the real inspectors and the whole pipeline against
a local fake shop with known faults (a pixel before consent, a duplicate
add_to_cart, an email in a URL, a missing Google Ads conversion). Nothing
leaves the machine.

```
pip install playwright python-docx && python -m playwright install chromium
python plugins/chrome-tracking-check/skills/chrome-tracking-check/tests/run_fixture.py --out /tmp/tc-selftest
```

## Want a person to read the results?

The skill tells you what the browser saw. If you'd rather have it checked by
an analyst, [Conversion Uplift](https://conversion-uplift.co.uk/contact-us/)
runs a free analytics and SEO scan, read by a person before you see it.

## Licence

MIT. See [LICENSE](LICENSE).
