# DSAR readiness — data classification for access and erasure requests

A Data Subject Access Request (DSAR) under UK-GDPR Article 15 (Right of Access) or an erasure request under Article 17 (Right to Erasure) requires the controller to identify and produce — or delete — every piece of personal data held about an identifiable individual. The runtime audit captures what data the *tracking layer* collects; this document explains how the audit's outputs feed a DSAR-ready data classification.

## Data categories the audit can identify

The runtime inspector + aggregator surfaces these categories (all observable in the browser, none in server-side stores):

| Category | Source in the audit | Identifiable? |
|---|---|---|
| GA4 `client_id` (`_ga` cookie) | `tag_inventory.ga4_measurement_ids` + `network.ga4_hits[*].cid` | Persistent pseudo-identifier — yes |
| GA4 `user_id` (if set) | `config.configs[*].options.user_id` | Direct identifier when populated |
| Meta Pixel external_id / fbp / fbc | `vendors["Meta (Facebook) Pixel"].ids` | Persistent pseudo-identifier |
| Server-side GTM identifiers | `network.probable_sgtm_hits` | First-party identifiers |
| Email / phone / CC patterns | `pii.hits` (FNV-hashed) | Direct identifier — leak |
| IP address | Not directly observable, but implied by every beacon | Pseudo-identifier per ICO |
| Precise geolocation | `privacy.sensitive_pi_categories_seen.precise_geo` | Direct identifier |
| Device/browser fingerprint surface | `vendors` + `performance.navigation` | Pseudo-identifier |
| Behavioural events (page_view, scroll, etc.) | `events.events_seen` | Linkable to client_id |

The audit doesn't enumerate every individual visitor's data — that's a server-side query — but it tells the analyst WHICH systems hold WHICH categories so a DSAR can be routed.

## DSAR-routing matrix (built from the audit's outputs)

For each detected vendor in Appendix A (Tag inventory) or the new `processor_inventory.csv`:

1. **Is the vendor a processor or joint controller?** See `VENDOR_ROLE_MAP` in `aggregate_findings.py`. Processors respond to YOUR DSAR request; joint controllers may respond directly to the data subject under their own privacy notice (you still have an obligation to route).
2. **What identifier does the vendor key on?** GA4 = `client_id` + optional `user_id`. Meta Pixel = `external_id` / `fbp` / `fbc`. Send the appropriate identifier to the vendor's DSAR endpoint.
3. **What's the vendor's DSAR endpoint or process?** Listed in their privacy policy (column `privacy_policy_url` in the processor inventory). Most major vendors have a self-serve portal — Google: `https://support.google.com/analytics/answer/9019185`; Meta: `https://www.facebook.com/help/contact/180237885820953`.
4. **What's the response SLA?** UK-GDPR requires 1 month; GDPR same; CCPA 45 days extendable to 90. Build a tracker.

## DSAR-readiness checklist (off-platform; the analyst owns these)

The audit can't verify these — they're internal-process questions — but the recommendations roadmap should include them whenever a DSAR is requested:

1. **Identifier inventory documented.** Every system that holds personal data is listed with the identifier it keys on, the retention period, and the data export format.
2. **Identifier-resolution pipeline.** Given a user's email or phone, can the operations team produce the GA4 client_id, the Meta external_id, the CRM ID, and the support ticket history within the legal window? If the linkage is manual, document it.
3. **Erasure cascading.** When erasure is requested, the deletion order matters — start with the systems that are the source of truth (CRM), then derive the identifiers to delete from downstream systems (warehouse, analytics, ad platforms). Document the order.
4. **Vendor SLA in the data processing agreement.** Each Article 28 contract should commit the vendor to a response SLA that's tighter than your 1-month obligation (typically 14 days). Verify your DPAs include this.
5. **Reidentification risk on "deleted" data.** Some analytics platforms (GA4 included) keep aggregated reports indefinitely. Confirm that the "deletion" you request truly removes the record from raw event tables, not just from individual exports.
6. **DSAR audit log.** Every received DSAR is logged with the request date, identifier, action taken (access/erasure/portability/rectification), and completion date. Supervisory authorities can ask for the log.
7. **Right-to-portability format.** Article 20 portability requires "structured, commonly used, machine-readable format". Most vendors export JSON or CSV; confirm your aggregation script can join them on the user identifier.

## What the audit's processor_inventory.csv contains

| Column | Use in DSAR workflow |
|---|---|
| `audit_date` | Date the inventory was generated |
| `page_url` | Which template the vendor was observed on |
| `vendor` | Name (matches `VENDOR_ROLE_MAP`) |
| `role` | Processor / Joint controller / Unknown |
| `privacy_policy_url` | Vendor's privacy policy — first stop for DSAR endpoint |
| `ids_observed_semicolon` | Container/pixel/measurement IDs to include in your DSAR request |
| `art28_contract_required` | "Yes" for processors (you need a DPA); "Joint-controller agreement" otherwise |

A privacy counsel reviewing this CSV gets, in one row per vendor, exactly what's needed to triage an incoming DSAR within the legal window.

## Tying back to other audit findings

The DSAR-readiness picture worsens when paired with other findings:

- `PII_LEAK_IN_PARAMS` Critical — raw PII is in URLs/dataLayer, so the vendor's "deletion" of analytics data may still leave the email in their query-string logs. Plan a vendor-side cache purge in addition to the analytics deletion.
- `GA4_CLIENT_ID_INCONSISTENT` Critical — if `client_id` differs across requests on the same page, your DSAR's `client_id` argument may resolve to only a fraction of the user's data. Fix the inconsistency before relying on DSAR-by-client_id.
- `SGTM_DETECTED` Info — server-side GTM holds first-party copies of the data sent to vendors. Confirm the sGTM logs are included in your retention/erasure scope.
- `PRIVACY_SENSITIVE_PI_RISK` Critical — Article 9 special-category data raises the bar; deletion alone isn't enough, you must also document the original legal basis and the steps taken to mitigate.
