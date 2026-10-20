# Capture and claim rules — BOTH modes, non-negotiable

## Contents

1. 1. Google request counting — never call an Ads ping a GA4 hit
2. 2. Clean consent state — or no consent findings at all
3. 3. Recorder before navigation
4. 4. Confidence discipline
5. 5. Consent Mode — four-state classification
6. 6. Severity and figures
7. 7. Vendor-embedded analytics
8. 8. Fairness — the What's Working section carries real findings
9. 9. Verify every consent click actually registered
10. 10. Extract evidence as structured fields, never as raw URLs

These ten rules exist because each one prevents a wrong answer that a browser
audit is prone to give. They are not style preferences. They bind automated
mode and journey mode identically, and they override any other guidance in
this skill that conflicts with them.

Read this file before the first capture in either mode. Apply every rule
without being asked.

---

## 1. Google request counting — never call an Ads ping a GA4 hit

**Defect it prevents:** a Critical "GA4 fires twice" finding shipped at high
confidence. The two requests were a GA4 hit and a Google Ads ping ~10ms apart.

- A GA4 hit is **only** a `/g/collect` request carrying a `G-` measurement ID.
- `/ccm/collect` requests and any `AW-` tid are **Google Ads**. Never GA4.
  This includes `google.com/ccm/collect`, `ad.doubleclick.net/ccm/s/collect`
  and `pagead2.googlesyndication.com/ccm/collect`.
- **Collapse dual dispatch.** Two `/g/collect` requests, one to
  `*.google-analytics.com` and one to `*.analytics.google.com`, carrying the
  same `_s`, `sid` and `dl` within ~100ms, are ONE hit. This is normal when ad
  consent is granted. GA4 counts it once and so do we.
- A double-fire claim is only permitted when two hits reach the **same
  endpoint class** with **different `_s` values, or an identical `_s`
  repeated**.
- Evidence for any duplicate claim must print the **full hostname, `tid` and
  `_s` of each request**, side by side. Event name and timestamp are not
  enough.
- Every duplicate claim ends with the GA4 DebugView confirmation step.

Full pattern list: `duplicate_event_patterns.md`.

---

## 2. Clean consent state — or no consent findings at all

**Defect it prevents:** a run audited a browser profile that had already
accepted the target site's banner. Every observation was post-consent, so no
consent behaviour was testable, yet the report still discussed consent.

Before the first page load:

1. Clear the target site's cookies, localStorage, sessionStorage and IndexedDB,
   **or** connect to a fresh incognito context.
2. Verify no CMP choice is stored — no consent cookie, and the banner is
   actually visible on first load.
3. Record the verification in the per-page payload as
   `"clean_state": true`.

If a clean state cannot be achieved, set `"clean_state": false` and then:

- Say so **at the top of the report**, in the executive summary as well as the
  methodology. Not a footnote.
- **Suppress every consent-behaviour finding and rating.** No Consent Mode
  classification, no pre-consent claims, no consent grade contribution, no
  reject-parity check.
- A consented profile supports **tag-inventory observations only**. It can say
  which tags exist. It can never say how they behave around consent.

The aggregator enforces this: `clean_state: false` drops all `CONSENT_*` and
`CMP_*` findings and emits `CONSENT_NOT_TESTABLE` (Info) in their place.

---

## 3. Recorder before navigation

**Defect it prevents:** a run enabled network recording part-way through, lost
every HTTP status code, and then reported request types as absent from pages
that were never fully recorded.

- Call `read_network_requests` (and `read_console_messages`) **once before the
  first navigation** to start capture.
- If any page was loaded before recording began, **discard that page and
  reload it**. Do not keep partial captures.
- Never report the absence of a request type from a page that was not fully
  recorded. If coverage is partial, the finding is "not observed on the pages
  fully recorded", and the methodology names which pages those were.
- Resource Timing is a supplement, not a substitute: it has no status codes.
  Findings that depend on status codes (`TRACKING_ENDPOINT_HTTP_ERROR`)
  require the recorder.

---

## 4. Confidence discipline

**Defect it prevents:** browser-side guesses presented with the authority of
direct observation.

| What you have | Maximum confidence |
|---|---|
| The browser directly recorded it (request sent, script present, dataLayer push) | **High / Observed** |
| The cause lives inside GTM or GA4 account configuration — duplicate tags, trigger logic, conversion definitions, data retention, internal traffic filters | **Needs verification** (never High) |
| Heuristic pattern match — sGTM by subdomain, PII by regex, platform by signature | **Inferred** |

- Anything whose root cause is account configuration caps at **Needs
  verification**, regardless of how confident the symptom looks. You can see
  two hits; you cannot see which tag or trigger produced them.
- **Verified-absent language** — "tested directly and confirmed absent",
  "verified not firing" — is permitted **only when the relevant journey step
  was actually exercised**. That means journey mode, where a human performed
  the step.
- Automated mode never uses verified-absent language. Its wording is
  "unverified rather than proven absent". A page-load scan that saw no
  `add_to_cart` did not test add-to-cart.

---

## 5. Consent Mode — four-state classification

**Defect it prevents:** reporting a working Basic-mode implementation as
"Consent Mode absent".

Classify into exactly one of four states. Never render any of them as
"absent".

**1. Advanced — verified cookieless.** All three must hold:
   - Pre-consent Google measurement requests carry a denied signal (`gcs=G100`);
   - No Google cookies written before the visitor chooses;
   - Hits upgrade cleanly to `gcs=G111` after acceptance.

**2. Advanced — not verified.** Consent Mode signals are present but one or
   more of the three checks above could not be confirmed. Say which one.

**3. Basic.** All three required:
   - A consent default of denied is present;
   - **No Google measurement requests fire pre-consent**;
   - Hits show `gcs=G111` after accept.

   When excluding "Google measurement requests", **exclude the GTM container
   and the gtag.js loader themselves** — loading the library is not
   measurement. Only collection endpoints count.

   Implication copy for Basic (use close to this wording): *"Consent gates
   correctly, but because no cookieless pings are sent before consent, Google
   has nothing to model from. Visitors who decline are never recorded at all,
   so there are no modelled conversions."*

   **Basic never scores worse than not-detected.** It is a legitimate,
   working configuration, and it is more privacy-conservative than Advanced.

**4. Not classifiable.** Evidence was insufficient. Render as "not
   classifiable from this scan", name the missing evidence, and give the
   Tag Assistant / DebugView step that would settle it. Never as "absent".

**Region parameter.** Note separately when a consent default carries no
`region`: denied-by-default then applies worldwide, which is usually
unintended outside the EEA/UK. This is **observation tier** — record it, never
let it affect the grade.

---

## 6. Severity and figures

- When Consent Mode is **verified**, consent findings **cap at High**.
- The only route to **Critical** (and to an E/F grade) on the consent and
  privacy axis is **personal data observed in a request payload**.
- **The Privacy-risk letter pin.** Verified cookieless Consent Mode **pins the
  Privacy-risk category at C**. Non-Google tags that fire, or set identifiers,
  before or after a consent choice are High-tier warnings *within* that C. They
  do not drag the letter to D. Only personal data observed in a payload rates
  Privacy lower than C.

  This is the single most-misread rule in the kit, so state the pin in the
  scorecard basis every time you apply it, in words close to: *"House rule
  applied: verified cookieless Consent Mode holds this letter at C. [Vendor]
  firing after rejection is a High-tier warning within that C. Only personal
  data in a payload rates lower, and none was observed."* Writing the rule into
  the basis is what makes the grade reproducible by someone else.

  **Worked example.** Consent Mode verified cookieless, banner and reject
  parity both clean on Google, but two chat and recommendation vendors set
  persistent identifiers after an explicit rejection. Correct answer: Privacy
  **C**, with two High-tier warnings. Reading the post-rejection finding as
  breaking a floor, and grading it D, is the mistake this rule prevents. There
  is no floor-breaking clause. There is a pin.
- **One severity per issue.** The executive summary, the finding itself, the
  roadmap and any covering email must all state the same severity, and any
  cross-reference must point at the section the finding actually lives in.
- **Percentages.** No percentage may appear in a report unless it was directly
  measured in this capture — request counts, timings, page counts. Do not
  quote industry loss or uplift figures. Invented precision is the
  fastest way to lose a technical reader.

---

## 7. Vendor-embedded analytics

**Defect it prevents:** treating a vendor's telemetry as the client's
analytics platform, and missing "this site has no analytics" as the headline.

Recognise:

- **Snowplow (generic)** — `GlobalSnowplowNamespace`, `window.snowplow`,
  `/com.snowplowanalytics.snowplow/tp2`, `/i?e=` collector pixels, `sp.js` /
  `sp/<version>.js` trackers, `_sp_id` / `_sp_ses` cookies.
- **Salesfire** — `*.salesfire.co.uk` (`cdn.`, `hit.`), `*.smartmetrics.co.uk`.
  Salesfire ships a Snowplow tracker inside its own product.

Then classify:

| Classification | Signals | How to report it |
|---|---|---|
| **Owned** | Collector on a first-party domain, and/or `_sp_id` / `_sp_ses` first-party cookies | A genuine analytics asset. Note it alongside GA4 rather than instead of it. |
| **Vendor-embedded** | Tracker script and collector both on the vendor's domain, no first-party `_sp` cookies | Rented telemetry, not an analytics asset the client owns |

Wording for vendor-embedded (use close to this): *"This is telemetry powering a
product the client rents, not an analytics asset they own. The data lands in
the vendor's pipeline. The client cannot query it, model it, or attribute
against it."*

**When no site-owned analytics platform is observed at all**, that is the
headline finding of the report — not a sub-point. If ad tags are present,
pair it with the ads-without-a-feedback-loop copy: *"Ad platforms are being
fed audience and conversion signal while the business collects nothing of its
own to judge that spend against."*

---

## 8. Fairness — the What's Working section carries real findings

**Defect it prevents:** "no positive findings recorded" printed for a site with
a correctly-defaulting Consent Mode v2 implementation. That is a reporting gap,
not a fact about the site.

The scan must actively record positives, not just failures. Emit a positive
(`"positive": true`) for each of these when observed:

- A consent banner that appears and functions;
- Consent Mode verified (Advanced-verified or Basic — both count);
- Consent Mode v2 with all four signals correctly defaulting to denied;
- Core Web Vitals passing;
- SEO fundamentals in place (title, description, H1, canonical, valid
  structured data);
- Consistent measurement IDs across templates;
- Server-side collection or Tag Gateway in place;
- Tracking endpoints all returning 2xx.

"No positive findings were recorded" is only permissible when the scan genuinely
observed none of the above. Before printing it, check the payload again — on a
site with a working CMP it is almost always wrong.

---

## 9. Verify every consent click actually registered

**Defect it prevents:** a run clicked "Reject all and Close" via an element
reference returned by `find`. The click silently did not register. The banner
reappeared on the next page, which looks exactly like "this CMP does not
persist a rejection" — a serious and completely false finding that was one
step from being written up.

Consent findings are the ones clients forward to their legal advisers. Never
record one from an unverified click.

After **every** accept, reject or preferences click, before recording anything:

1. **Confirm the banner is gone.** Test the banner's own text against
   `document.body.innerText`, not the element reference you clicked.
2. **Confirm a consent record now exists** — a CMP cookie, a CMP localStorage
   key, or a `consent` push in the dataLayer with the expected state.
3. **Confirm the direction matches the button.** A reject that produces
   `granted` signals means you hit the wrong control. This happens: banners
   place Accept and Reject at mirrored positions, and a stale coordinate from
   an earlier screenshot lands on the opposite button.

If any of the three fails, the click did not do what you think. Re-click and
re-verify. **Prefer clicking by coordinate from a fresh screenshot over an
element ref for consent controls** — `find` may return several refs for the
same visible button, including hidden duplicates that swallow the click.

**Then walk at least two further pages** before claiming anything about
persistence. One page proves the click worked; it does not prove the choice
survives navigation.

### The localStorage mirror

Many CMPs (Clickio confirmed, others likely) store the choice in **both** a
cookie and localStorage. Clearing cookies alone leaves the choice in force:
the banner does not reappear, and an audit that assumes "no banner shown" will
report a fresh-visitor state it never actually reached, or conclude the site
has no CMP at all.

Rule 2's clean state therefore means cookies **and** localStorage **and**
sessionStorage, followed by an explicit check that **the banner is visibly
back**. Banner-reappears is the pass condition for a clean state. Nothing else
is.

---

## 10. Extract evidence as structured fields, never as raw URLs

**Defect it prevents:** an entire capture returned as `[BLOCKED]` placeholders,
leaving the audit unable to tell a GA4 hit from a Google Ads ping — the exact
distinction rule 1 depends on.

The Chrome extension redacts tool output that pattern-matches as sensitive.
Observed in practice, it blanks:

- **query strings** on returned URLs,
- **base64-looking path segments**,
- **hostnames that resemble a JWT**, which includes `www.googletagmanager.com`,
- **`document.cookie`** in full, intermittently.

This skill is built entirely on reading query parameters, so returning raw URLs
does not work. In the page script:

- Parse with `new URL()` and return **named fields**: `tid`, `gcs`, `gcd`,
  `en`, `_s`, `sid`, `cid`, `gtg_health`. Named scalars survive.
- Describe paths by **segment classification**: match each segment against a
  known list (`g`, `ccm`, `collect`, `pagead`, `1p-user-list`, `form-data`,
  `tp2`) and report anything unrecognised as `{len, charClass}` only. This is
  how you identify a random Tag Gateway prefix without ever printing it.
- Return **cookie names only**, never values, and prefer counts and boolean
  presence flags over content.
- Report hostnames as first-party-or-not plus a vendor label, and fall back to
  the registrable domain if a full hostname is blanked.

`scripts/inspectors/probe.js` already does all of this. If you extend it, keep
the property; a helpful-looking `return {url: r.name}` will silently destroy
the evidence base of the whole audit.

**Also true of the network recorder:** `read_network_requests` has been
observed returning **first-party requests only**, despite documenting
cross-origin capture. Do not conclude a third-party request is absent from its
output. Cross-check against Resource Timing, and note that Resource Timing
carries no status codes, so rule 3's `TRACKING_ENDPOINT_HTTP_ERROR` findings
are only available for hosts the recorder actually returned. Say which those
were.
