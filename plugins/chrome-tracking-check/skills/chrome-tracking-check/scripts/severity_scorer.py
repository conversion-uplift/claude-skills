#!/usr/bin/env python3
"""severity_scorer.py — confirm severities, compute score + A-F grade."""

from __future__ import annotations
import argparse, json, sys
from collections import Counter

SEVERITY_WEIGHTS = {"Critical": -15, "High": -8, "Medium": -4, "Low": -1, "Info": 0}

SEVERITY_RUBRIC = {
    "GA4_NOT_DETECTED": "Critical",
    "GA4_MISSING_ON_SOME_PAGES": "Critical",
    "GA4_MULTIPLE_MEASUREMENT_IDS": "High",
    "GA4_NO_PAGE_VIEW_EVENT": "High",
    "GA4_LEGACY_UA_DETECTED": "High",
    "GTM_NOT_DETECTED": "Medium",
    "GTM_DUPLICATE_CONTAINER": "High",
    "GTM_MULTIPLE_CONTAINERS": "Medium",
    "GTM_AND_STANDALONE_GTAG_BOTH": "Medium",
    "CONSENT_MODE_MISSING": "Critical",
    "CONSENT_MODE_V1_ONLY": "High",
    "CONSENT_MODE_DEFAULT_AFTER_TAGS": "Critical",
    "CONSENT_MODE_NO_REGION": "Info",
    "CMP_NOT_DETECTED": "Medium",
    "SGTM_DETECTED": "Info",
    "TAG_GATEWAY_DETECTED": "Info",
    "TAG_GATEWAY_PARTIAL": "Medium",
    "TAG_GATEWAY_BYPASSED": "Medium",
    "TAG_GATEWAY_CLAIMED_NOT_ACTIVE": "High",
    "CONSENT_MODE_CLASSIFICATION": "Info",
    "CONSENT_NOT_TESTABLE": "Info",
    "CMP_WORKING": "Info",
    "CONSENT_MODE_V2_CORRECT_DEFAULTS": "Info",
    "CORE_WEB_VITALS_PASSING": "Info",
    "GA4_IDS_CONSISTENT": "Info",
    "VENDOR_EMBEDDED_ANALYTICS": "Info",
    "NO_OWNED_ANALYTICS_PLATFORM": "Critical",
    "META_PIXEL_DUPLICATE": "Medium",
    "META_PIXEL_MULTIPLE_IDS": "Medium",
    "LINKEDIN_INSIGHT_PRESENT": "Info",
    "TIKTOK_PIXEL_PRESENT": "Info",
    "MULTIPLE_SESSION_REPLAY_TOOLS": "Low",
    "LCP_POOR": "Medium",
    "CLS_POOR": "Medium",
    "INP_POOR": "Medium",
    "EXCESSIVE_ANALYTICS_REQUESTS": "Low",
    "TAG_JAVASCRIPT_ERROR": "High",
    "TRACKING_ENDPOINT_HTTP_ERROR": "Critical",
    "GA4_ECOMMERCE_LEGACY_SCHEMA": "High",
    "GA4_ECOMMERCE_ITEMS_INCOMPLETE": "High",
    "GA4_NO_KEY_EVENTS_OBSERVED": "High",
    "ENHANCED_MEASUREMENT_DUPLICATE": "High",
    "GA4_LIKELY_CONVERSIONS_UNVERIFIED": "Info",
    "GA4_NO_CROSS_DOMAIN_LINKER": "High",
    "PII_LEAK_IN_PARAMS": "Critical",
    "EVENT_PUSHED_BUT_NOT_SENT": "High",
    "EVENT_SENT_WITHOUT_DATALAYER": "Medium",
    "GA4_CLIENT_ID_INCONSISTENT": "Critical",
    "SGTM_NOT_ACTUALLY_USED": "High",
    "GA4_EVENT_PARAM_MISSING": "Medium",
    "GEO_MISMATCH": "Medium",
    "EXPERIMENT_PLATFORM_NO_EXPOSURE_EVENT": "High",
    "EXPERIMENT_PERSONALISATION_COLLISION": "Medium",
    "FUNNEL_STAGE_EVENT_MISSING": "High",
    "MICROCONVERSION_NOT_TRACKED": "High",
    "PRIVACY_GPC_NOT_HONOURED": "Critical",
    "PRIVACY_GPP_MISSING_FOR_REGION": "High",
    "PRIVACY_LEGITIMATE_INTEREST_FOR_ADS": "High",
    "PRIVACY_SENSITIVE_PI_RISK": "Critical",
}


def normalise_severity(sev):
    if not sev: return "Medium"
    s = sev.strip().capitalize()
    return s if s in SEVERITY_WEIGHTS else "Medium"


# Rule 6 (references/capture_and_claim_rules.md): when Consent Mode is verified,
# consent findings cap at High. Only personal data in a payload reaches Critical
# on the consent/privacy axis. Basic Consent Mode never scores worse than
# not-detected, so its classification finding is Info and deducts nothing.
CONSENT_CRITICAL_ALLOWED = {"PRIVACY_SENSITIVE_PI_RISK", "PII_LEAK_IN_PARAMS"}


def cap_consent_severity(findings):
    verified = any(f.get("id") == "CONSENT_MODE_CLASSIFICATION" and f.get("positive")
                   for f in findings)
    if not verified:
        return findings
    for f in findings:
        fid = f.get("id", "")
        if (fid.startswith("CONSENT_") or fid.startswith("CMP_")) \
                and f.get("severity") == "Critical" and fid not in CONSENT_CRITICAL_ALLOWED:
            f["severity"] = "High"
            f["severity_capped"] = ("Capped from Critical: Consent Mode was verified on this "
                                    "site, so only personal data in a request payload reaches "
                                    "Critical on this axis.")
    return findings


def confirm_severity(finding):
    fid = finding.get("id", "")
    if fid in SEVERITY_RUBRIC:
        return SEVERITY_RUBRIC[fid]
    return normalise_severity(finding.get("severity", "Medium"))


def grade_from_score(score):
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "F"


def score_audit(payload):
    findings = payload.get("findings", []) or []
    score = 100
    counts = Counter()
    findings = cap_consent_severity(findings)
    for f in findings:
        sev = confirm_severity(f)
        f["severity"] = sev
        counts[sev] += 1
        if not f.get("positive"):
            score += SEVERITY_WEIGHTS.get(sev, 0)
    score = max(0, min(100, score))
    payload["score"] = score
    payload["grade"] = grade_from_score(score)
    payload["summary_counts"] = {
        "Critical": counts.get("Critical", 0),
        "High": counts.get("High", 0),
        "Medium": counts.get("Medium", 0),
        "Low": counts.get("Low", 0),
        "Info": counts.get("Info", 0),
        "Total": sum(counts.values()),
    }
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    with open(args.findings, "r", encoding="utf-8") as f:
        payload = json.load(f)
    scored = score_audit(payload)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(scored, f, indent=2)
    print(f"Score: {scored['score']} -> Grade {scored['grade']}")
    print(f"Counts: {scored['summary_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
