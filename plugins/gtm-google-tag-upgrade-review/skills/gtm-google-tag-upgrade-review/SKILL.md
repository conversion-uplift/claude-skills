---
name: gtm-google-tag-upgrade-review
description: Reviews a Google Tag Manager container and its Google tags before Google's container upgrade (the change that merges the Google tag into GTM and turns GA4, Google Ads and Floodlight into destinations), working read-only in the browser through Claude in Chrome. Compares every Google tag setting, decides which tag's settings the container should keep, rates the risks (enhanced conversions, session timeout, consent, access, lookup tables, gtag.config triggers), and writes a Word report plus a draft covering email. Use when someone asks whether to accept the GTM "Optimize your container" upgrade, how to merge Google tags into GTM, which settings to keep in the upgrade wizard, or why the upgrade isn't being offered.
license: MIT. See LICENSE.
---

# GTM Google Tag Upgrade Review

Google is folding the Google tag into Google Tag Manager. The upgrade is opt-in: the GTM container becomes the Google tag, and GA4, Google Ads and Floodlight become destinations inside it. This skill checks whether a container can be upgraded safely, decides which Google tag's settings the container should keep, rates the risks, and writes a report the site owner or their client can act on.

**The review is read-only.** Never click Save, never run the upgrade wizard, never accept a suggested domain, and never publish. Only review containers you own or have permission to work on.

**Last verified: 22/10/2026.** Google is still rolling this out and the interface changes. Re-check the rules below against the sources at the end before relying on them, and say in the report which date they were checked.

## Step 1. Confirm the inputs

Ask the user, in one message:

1. The site and the GTM container (name or GTM-XXXXXXX ID).
2. Who the report is for: the site owner, a client, or internal use.
3. Whether they have a Word template to use. If not, build a plain, clean document (Step 7).

If a brand or house-style skill is installed, load it before writing anything.

## Step 2. What decides the risk (the rules)

These come from Google's documentation and testing shared in the GTM community. They're confirmed unless listed under "Still unverified".

1. **Only the container's settings apply.** After the upgrade, the container's Settings apply to every linked destination. Each tag's own settings in GA4 or Google Ads are ignored, and a destination tag can't switch a setting back on or tighten it for itself. Some early write-ups said a destination could apply "stricter" settings. Don't repeat that.
2. **Per-destination differences are tag parameters, not settings.** `send_page_view`, `server_container_url`, `user_id`, event parameters, `debug_mode`, `cookie_prefix` and `cookie_domain` stay on each tag and carry over.
3. **`linker` on a destination tag doesn't override the shared domain list.** In community testing, only the shared domains were decorated.
4. **If a destination needs different settings, don't link it.** Untick it in the wizard and it stays a legacy Google tag, with its own settings and its own gtag.js load. Google says Google tags will later become containers in their own right, which is where destination-specific settings are expected to live.
5. **The wizard asks which Google tag's settings to keep only when the settings differ.** That question is the signal. The "Get started" button appears whichever path you're on (from the banner, a destination on the map, or the Optimized column), so the button tells you nothing. Google's help page also describes a "Review details" path, which hadn't been seen in a live container at the date above.
6. **Access.** The wizard only offers Google tags whose GA4 property or Google Ads account the person running it can access. Accounts owned by another agency won't appear. Running it needs Edit in GTM, and publishing needs Publish.
7. **Read access.** Linking gives every user of each linked GA4 property and Google Ads account Read access to the whole container (tags, triggers, variables, Custom HTML). It's one-way, and permissions aren't versioned, so a rollback doesn't remove the access.
8. **Blockers.** In testing, a lookup table as the Google tag's measurement ID stopped the upgrade being offered, while a Constant variable or a typed ID worked. If the Google tag and the GA4 event tags use different IDs, the Overview shows each ID as a separate Google tag, and events land in a different property from the configuration.
9. **Separate changes to check anyway.**
   - Since 08/10/2026, `gtag('config')` commands appear in the data layer as `gtag.config` events. A Custom Event trigger matching `.*` can fire conversion tags twice, so it needs an exception for `gtag.config`.
   - Since 09/07/2026, a GTM- container runs any tag, while G- and AW- IDs run Google tags only.
   - A server-side route is unchanged: destination tag, then server container, then GA4. Requests to the server container aren't reduced.

**Still unverified:**

- What causes the "Optimize your Tag Manager container" message that can stay on GA4 event tags after the upgrade, even when the destination shows as optimised and linked. Test with Preview's Hits sent tab instead.
- Whether "start from scratch" in the wizard defaults user-provided data to off. Advise against "start from scratch".
- Whether turning user-provided data collection off on one GA4 property stops only that property receiving it.

## Step 3. The settings and what each one risks

Names as they appear on the Google tag's Settings screen. Google notes there that some settings apply only to specific destinations.

| Setting | Applies to | Risk if it changes |
|---|---|---|
| Manage automatic event detection | GA4 (and Ads for page views) | Low |
| Configure your domains | All | Low for conversions, but the list also carries the Ads click cookie across domains. Dropping a checkout domain loses attribution for its conversions |
| Allow user-provided data capabilities, plus how it's collected (code, automatic detection with data types and exclusions, CSS selectors or JS variables) | All | **High.** Off in the container means off for Google Ads enhanced conversions |
| Collect Universal Analytics events | GA4 | None |
| Extract data from your page | All | **High** if the Ads tag relies on its selector rules for enhanced conversions and the kept settings don't have them |
| Define internal traffic | GA4 | Reporting only |
| List unwanted referrals | GA4 | Reporting only |
| Adjust session timeout (hours, minutes, engaged-session seconds) | GA4 | **High** if non-default. Sessions and engagement rate change from the day of publishing |
| Override cookie settings | GA4 | Low (GA4 cookies only) |
| Manage data transmission (restrict ads data, plus additional settings) | Ads and analytics | Medium |
| Override consent mode defaults (ads and analytics, by region) | GA4, Ads, CM360 | Medium |
| Manage default consent settings for data collection (EEA) | Ads | Medium if Ads had "mark as consented" and the kept settings don't |

## Step 4. Gather the evidence in the browser

Use Claude in Chrome on tagmanager.google.com, in a tab the user is signed in to. Note what you read; change nothing.

**4.1 Container overview** (`#/container/accounts/<acc>/containers/<cid>/workspaces/<ws>`):

- Read the page text for the Google tags map: each Google tag's name and IDs, and the destinations with their tag counts.
- Read **Pending Changes**. Any unpublished change in the workspace would go live with the upgrade, so record it.
- Clicking a Google tag on the map shows its tag references: every tag that uses that ID.
- The container **Settings** page shows whether any destinations are linked yet.

**4.2 Each Google tag's settings.** Go to `#/home`, open the **Google tags** tab and find each ID. Duplicate names like "Untitled tag" are common, so find the link in the same row as the ID and navigate to its href (`#/container/accounts/<a>/containers/<c>/workspaces/0/config`). On the config page:

- Note the **Tag quality** line and open "View N issues". Additional domains detected can point to test sites or sister sites.
- Click **Show more** (`[aria-label="Show more settings"]`), then open every setting in Step 3.
- Settings open as stacked side sheets (`.gtm-sheet-wrapper`). Close each one with `i.gtm-sheet-header__close` before opening the next. Otherwise later reads return the stale sheet.
- Toggles are `MD-SWITCH` elements with `aria-checked`. Checkboxes are `GTM-CHECKBOX` elements with `.checked`. Radios are read from `aria-checked`.
- Open settings **one or two per script call**. Longer loops time out.
- **Take screenshots of** these, because their values don't come through the DOM reads: user-provided data (expand Exclusions), extract data rules, session timeout (script reads can come back blocked as sensitive), Manage data transmission > Additional settings, and Configure your domains (suggested domains vs conditions).

Helper to paste once per page (the functions survive hash navigation):

```js
window.__closeAll = async () => { for (let i = 0; i < 5; i++) { const c = [...document.querySelectorAll('i.gtm-sheet-header__close')].filter(e => e.getBoundingClientRect().width > 0).pop(); if (!c) break; c.click(); await new Promise(r => setTimeout(r, 1200)); } };
window.__open = async (name) => { await __closeAll(); const row = [...document.querySelectorAll('[role=button],[tabindex="0"]')].find(b => (b.innerText || '').split('\n')[0].trim() === name); if (!row) return name + ': not found'; row.click(); await new Promise(r => setTimeout(r, 4000)); const panel = [...document.querySelectorAll('.gtm-sheet-wrapper')].pop(); return { name, txt: panel.innerText.slice(0, 1500), states: [...panel.querySelectorAll('md-switch,gtm-checkbox,[aria-checked]')].filter(e => e.getBoundingClientRect().width > 0).map(e => (e.getAttribute('aria-label') || e.innerText || '').slice(0, 70).replace(/\n/g, ' ') + ' = ' + (e.checked ?? e.getAttribute('aria-checked'))) }; };
```

These selectors were correct on the date above. If one returns nothing, read the page text instead and say which values came from screenshots.

**4.3 The container itself:**

- **Tags list.** Google tags (ID typed, Constant or lookup table; firing triggers; exceptions; firing option), Google Ads conversion and User-provided Data Event tags ("Include user-provided data" and the variable used), Conversion Linker, GA4 event tags and their exceptions.
- **Variables.** The table shows 50 rows. Set the "Show rows" select to ALL with `select.value=...; dispatchEvent(new Event('change',{bubbles:true}))`. Variable names aren't links, so click the element whose exact text is the name. Open the Google Tag Configuration Settings and Event Settings variables (`server_container_url`, `user_id`, hashed email) and the User-Provided Data variable (manual or automatic, which data layer fields).
- **Triggers.** Note every Custom Event trigger, and any exception triggers such as a "Not Live Site" hostname filter. The list doesn't show event names, so flag `.*` and `gtag.config` as a Preview check rather than claiming a pass.

## Step 5. Decide

1. **Do the settings match?** If yes, it's the simple path. If no, the wizard will ask which tag's settings to keep.
2. **Which tag's settings to keep.** Default to the tag whose settings carry the highest-risk values. Usually that's GA4, when it has a non-default session timeout or the broader user-provided data detection. Choose the Ads tag only when Ads relies on settings GA4 lacks (user-provided data on, extract-data rules) and GA4's own settings are defaults. Where both sides hold something important, set the container to the union: merge domain lists, keep user-provided data on, and match consent settings to the site's banner and privacy notice, not to whichever tag is looser. Say that in the report.
3. **Does any destination need its own settings?** Raise it whenever it's true, but it's a reason to **leave that destination out**, not to stop the upgrade. Leave a destination out when:
   - Ads relies on a setting GA4 can't share.
   - The consent banner and privacy notice support a consent setting for one destination only.
   - The destination's account is managed by another agency that wants it kept separate.
4. **Rate each risk** High, Medium or Low, with what will be done and a named owner (your team, the site owner, the Ads account owner). Always consider:
   - The wrong choice in the wizard.
   - Unpublished workspace changes.
   - Read access for linked accounts.
   - Access to the Ads account.
   - Broader or narrower user-provided data detection.
   - `gtag.config` and Custom Event triggers.
   - Server-side routing.
   - Lookup tables or mismatched IDs (blockers).
5. **Other observations.** Put anything the upgrade doesn't cause in its own section, marked as not blocking the upgrade. Examples: missing exceptions sending test traffic to live GA4, no internal traffic rules, redundant triggers.

Show the user a short summary in the chat (verdict, the differing settings, the top risks) before building the report.

## Step 6. Write the report

Title as a question: "Should <Site> Merge Its Google Tags Into GTM?" Sections, in order:

1. **Summary.** A shaded callout with the recommendation in bold and the tag IDs. Then three short paragraphs: which settings to keep and what changes for each destination, what the wrong choice would cost, and what needs sorting before publishing.
2. **What the Upgrade Changes.** Four short paragraphs from Step 2.
3. **What We Checked.** Date, scope, and that it was read-only.
4. **How the Google Tags Compare.** Only the settings that differ, with columns: setting (and what it applies to), tag 1, tag 2, "If we keep <tag 1>'s settings", "If we keep <tag 2>'s settings".
5. **Risks of Merging.** Columns: risk, rating, what we'll do, owner.
6. **Should Different Settings Per Destination Stop the Merge?** Answer it for this container, then list when you'd leave a destination out.
7. **Benefits of Merging.**
   - One script instead of one gtag.js per Google tag.
   - One place for settings, so they can't disagree again (give the number that differ now).
   - A tested change in a workspace with a version to roll back to.
   - The new Google Analytics and Google Ads destination tag types sit on the upgraded set-up. The old Google tag and Conversion Linker are marked legacy, and no forced migration had been announced at the date above.
8. **Next Steps.** Numbered, each with a bold owner:
   1. Approve Read access.
   2. Confirm Ads access.
   3. Handle any pending workspace change.
   4. Export the container and note the rollback version.
   5. Run the upgrade with the chosen settings.
   6. Test in Preview: consent denied and accepted, page_view once per page, a test purchase with value, currency, transaction ID and hashed user data reaching Ads, the server container receiving requests, and no Custom Event trigger firing on `gtag.config`.
   7. Publish with a clear version name and check the same day.
   8. Day 1 and day 7 checks: enhanced conversions match rate, purchases by conversion time, GA4 sessions and engagement rate against the previous week.
9. **Other Observations.**
10. **Appendix: Settings That Already Match.**

**Content rules:**

- State only what was seen. Where something wasn't verified (event names on Custom Event triggers, where test traffic comes from), say it will be checked in Preview.
- Don't name individual colleagues in a client-facing report: say "an edit made in the workspace".
- Never use one client's container as an example in another client's report.
- Plain English and Title Case headings. Keep prices out of the report; if the user wants a price, it belongs in the covering email.

## Step 7. Build the Word file

If the user gave a template, work on a copy: unzip it, keep the first paragraph (usually the logo) and the `<w:sectPr>`, and replace everything in between with the report body built as XML. If not, build a plain document with the `docx` skill.

Formatting that works well (swap the colours for the user's brand):

- Body font Roboto with an Arial fallback, text colour #262223.
- Styles: Title 22pt bold; Subtitle 13pt in the accent colour; Meta 9pt grey with an accent bottom border; Heading 15pt bold with keepNext and outline level 0; Body 10.5pt.
- A bullet list and a decimal list added to `numbering.xml` with new abstractNum and num IDs, inserted before the first `<w:num `.
- Tables: header row in the accent colour with white bold text, alternate row shading, a "High" rating in accent bold.
  - Set `tblW`, `gridCol` and every `tcW` in DXA, summing to the page's text width (9026 for A4 with 2.54cm margins).
  - In `tblPr`, put `tblBorders` **before** `tblLayout`, or validation fails.
  - Use `tblHeader` and `cantSplit` on rows.
- Callout: a one-cell table with a thick accent left border and a light fill.
- Validate the file (the `docx` skill's validator), render it to PDF and images, and look at every page before handing it over.

## Step 8. Draft the covering email

Plain paragraphs, no headings or bullet lists. If an email connector is available, create a **draft** only. Never send it. Check for an existing unsent draft on the same subject first and update it rather than leaving two.

Write it in this order:

1. One sentence saying what was reviewed.
2. **The recommendation as its own paragraph, straight after that sentence:** go ahead (or not), which tags to link, and which tag's settings to keep. Then "The full report is attached."
3. What the upgrade changes, in two or three sentences, with the tag IDs. Say it's opt-in, so nothing changes until it's published.
4. Why the settings choice comes up, and what changes for each destination. Link it to any open issue the recipient already knows about, and say whether the upgrade fixes it.
5. Why the choice matters, with the specific setting values.
6. Before publishing: the Read access the recipient should check and approve, and the permissions you'll need.
7. What happens next: pending workspace changes first, then the upgrade, Preview tests, and checks on the day and a week later.
8. Other observations, in one short paragraph, marked as separate from the upgrade.

**Example email** (an illustrative online shop; all names and IDs are placeholders):

> Subject: Merging Your Google Tags Into GTM: Our Review and Recommendation
>
> Hi Sam,
>
> We've reviewed whether Example Garden Shop should take up Google's upgrade that merges your Google tags into Google Tag Manager.
>
> Our recommendation is to go ahead with the upgrade, link both the GA4 and Google Ads tags to the container, and keep the GA4 tag's settings when GTM asks which to use. The full report is attached.
>
> Once the container is upgraded, the GA4 tag (G-XXXXXXXXXX) and the Google Ads tag (AW-XXXXXXXXX) become destinations inside GTM, and one set of settings applies to both. Google says tags will fire and send the same data as they do now. The upgrade is opt-in, so nothing changes until we publish it.
>
> The two tags don't have the same settings at the moment, which is why GTM will ask which to keep. Keeping the GA4 tag's settings leaves GA4 reporting exactly as it is. The one change for Google Ads is that automatic detection of customer details on the site widens from email only to email, phone number and address. Enhanced conversions on purchases keep using the customer data sent with each order, so the upgrade doesn't affect them.
>
> The choice matters because your GA4 tag uses a 4 hour 30 minute session timeout and counts a session as engaged after 60 seconds. Keeping the Ads tag's settings would reset those to Google's defaults of 30 minutes and 10 seconds, and sessions and engagement rate would change overnight.
>
> Before we publish, please note that linking the tags gives everyone with access to your GA4 property and Google Ads account read-only access to the whole GTM container. Please check who has access to both and let us know you're happy with that. To make the upgrade we'll need full admin permissions, so we'll be in touch if any of our permissions need changing.
>
> On our side, there's an earlier change waiting in the GTM workspace. We'll check it and publish it on its own first, so the upgrade goes live by itself. Then we'll run the upgrade, test it in GTM Preview with a test purchase reaching Google Ads, and check the numbers on the day and again a week later.
>
> The report also lists a few things the upgrade doesn't cause but that are worth fixing. The GA4 tag is picking up traffic from what looks like a development site, and GA4 has no internal traffic rules set up. We can pick these up separately.
>
> Kind regards,
>
> [Your name]

## Self-check

- Every one of the 12 settings was read on every Google tag, including the user-provided data detail, the session timeout values and the data transmission additional settings.
- Pending workspace changes, lookup tables or mismatched IDs, Ads access and Read access are each covered.
- The recommendation names which tag's settings to keep and says, for this container, whether any destination should be left out.
- Nothing in the container, GA4 or Ads was changed. No sheet was saved and no wizard was run.
- The report states the date the rules were checked, marks anything unverified, and every rendered page has been looked at.
- Tell the user what wasn't verified, so they can check it before the report goes out.

## Sources

- Google Tag Manager Help, Updates to Google tag and Google Tag Manager: https://support.google.com/tagmanager/answer/17079602
- Google Help, Optimize your Google Tag Manager container: https://support.google.com/analytics/answer/16659369
- Google Tag Manager release notes: https://support.google.com/tagmanager/answer/4620708
- Google Help, Configure your Google tag settings: https://support.google.com/tagmanager/answer/12131703
- Google Help, Data transmission controls: https://support.google.com/tagmanager/answer/16054531
- Simo Ahava, Optimized Tagging Experience for Google Tag Manager: https://www.simoahava.com/analytics/optimized-tagging-experience-google-tag-manager/
- Stape, Google Tag & GTM updates: https://stape.io/news/google-tag-gtm-updates

Written by Conversion Uplift (https://conversion-uplift.co.uk) from container reviews and testing in October 2026.
