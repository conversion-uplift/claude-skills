# CRO capability checklist — what runtime inspection can and can't prove

The audit can detect experimentation platforms, exposure events, microconversions, and funnel-stage event coverage from the browser. It can't see the platform-side machinery that determines whether the resulting data is trustworthy. The recommendations roadmap should always close with these off-platform checks.

## Experimentation platform-side checks (the analyst must verify in the platform UI)

For every running experiment, confirm in your A/B-testing tool:

1. **Sample Ratio Mismatch (SRM)** — the expected split (e.g. 50/50) matches the actual split within a chi-square p-value of 0.01 or better. Skewed splits invalidate every downstream result. Most platforms surface this; if yours doesn't, run a chi-square test on the daily exposure counts.
2. **Sticky assignment** — a returning visitor sees the same variant across sessions. Verify by clearing only your bucketing cookie, returning to the page, and confirming the variant flips. Re-set the cookie and confirm stickiness over multiple visits.
3. **Mutually-exclusive audiences** — when running concurrent tests, ensure visitors in test A are excluded from test B (or that exposure is explicitly orthogonal and the team is comfortable with combined treatment effects).
4. **Naming convention compliance** — every experiment follows the team's standard (e.g. `YYYY-MM-DD_PageType_Hypothesis_Variant`). Easy to enforce; easy to skip.
5. **Statistical-significance thresholds** — confirm the platform isn't surfacing significance below the team's pre-agreed alpha (commonly 0.05) and that sequential-testing controls (always-valid p-values, group sequential designs) are turned on if results are peeked at regularly.
6. **Holdout group health** — for personalisation platforms, verify a holdout group (typically 5-10%) is preserved and that holdout vs treated conversion rates are reported alongside the lift.
7. **QA-mode parameters** — confirm `?optimizely=preview`, `?_vwo_x=`, `?abTastyAddTrack` etc. are NOT in any URL the audit visited. Those bypass bucketing and would invalidate the exposure data.

## CDP / data-quality checks (analyst verifies in the CDP and warehouse)

8. **Identity stitching** — anonymous browsing sessions are joined to logged-in user records after authentication; the join window is at least 30 days; reverse-join (logged-in user later browsing anonymously) is also handled.
9. **Microconversion stream completeness** — at least 3-5 microconversions per primary conversion type are flowing into the warehouse, and the analyst can build a drop-off funnel chart from them.
10. **Cohort retention dashboards** — at least one cohort retention chart exists per primary segment (new vs returning, by acquisition channel) and is consulted in monthly reviews.
11. **LTV / repeat-purchase tracking** — for ecommerce, transaction_id and customer_id are joined so LTV can be computed; for SaaS, MRR is joined to acquisition event.

## Server-side experimentation (audit gets a partial hint only)

If LaunchDarkly, Statsig, Eppo, or similar are detected in the page bundle, confirm with the engineering team:

12. **Server-side exposure events are forwarded to the analytics layer** — typically via Segment or a webhook. Server-side flag evaluations are invisible to the browser; without explicit forwarding, the analytics layer has no idea who saw what.
13. **Sticky feature-flag assignment across page loads** — same user, same flag value over time. Verify with a logged-in account and the platform's debug panel.
14. **Feature flag cleanup** — flags older than 90 days that are 100% rolled out should be removed from code to prevent stale-flag-induced bugs.

## Personalisation engine collisions (the audit warns; the analyst confirms)

The audit emits `EXPERIMENT_PERSONALISATION_COLLISION` when both an A/B testing platform and a personalisation engine are detected on the same page. Verify:

15. **Audience exclusivity** — the personalisation engine's audience rules explicitly exclude the test's audience, OR the test's audience explicitly excludes the personalised cohort.
16. **Effect stacking documented** — if both run simultaneously, the team has decided which engine "owns" the variant and is reporting the combined effect explicitly.

## Naming conventions and documentation

17. **Event taxonomy is documented** — every custom event in GA4 has an entry in a Notion/Confluence doc with: trigger description, parameter list, owner, last modified.
18. **Experiment-hypothesis register** — every running experiment has a linked one-pager with hypothesis, primary metric, MDE, planned end date.
19. **Tag governance** — GTM workspace changes are reviewed; container versions are tagged with release notes; production publishes require approval.

## Why this matters

A runtime audit that says "Optimizely is loaded and exposure events fire" is necessary but not sufficient. If the platform has SRM on half the experiments, sticky assignment is broken, or feature flags are stale, the team is making product decisions on noise. This checklist is what a senior CRO consultant runs in parallel to the runtime audit — and what the audit's recommendations roadmap should always link back to.
