#!/usr/bin/env python3
"""Unit test for datalayer_spec.py. No browser and no network.

tests/datalayer_capture.json is real probe_datalayer.js output from
tests/fixture_site/datalayer_cases.html, captured in Chromium. That page
contains one of each data layer mistake the rules look for. To refresh the
capture after changing the probe, load the page in Chrome, run the probe and
save the result over the JSON file.

    python tests/test_datalayer_spec.py
"""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import datalayer_spec as ds  # noqa: E402

CAPTURE = json.loads((HERE / "datalayer_capture.json").read_text(encoding="utf-8"))


def ids(findings):
    return {f["id"]: f for f in findings}


def test_probe_never_returns_personal_values():
    text = json.dumps(CAPTURE)
    assert "jane@example.com" not in text and "@example" not in text
    kinds = {(p["path"], p["inUserData"]) for p in CAPTURE["pii"]}
    assert ("user.email", False) in kinds and ("user_data.email", True) in kinds


def test_ecommerce_rules():
    per_page = {"pages": [{"url": "https://shop.test/p", "template_label": "Product",
                           "datalayer": CAPTURE, "datalayer_expect": ["view_item", "purchase"]}]}
    _, st, rows, findings = ds.run(per_page, None, "ecommerce")
    f = ids(findings)
    for fid in ["DL_ECOM_LEGACY_SCHEMA", "DL_ECOM_NOT_CLEARED", "DL_ECOM_CURRENCY_INVALID",
                "DL_ECOM_DUPLICATE_PUSH", "DL_ECOM_REQUIRED_MISSING", "DL_ECOM_ITEM_ID_MISSING",
                "DL_ECOM_VALUE_NOT_NUMBER", "DL_PERSONAL_DATA", "DL_ECOM_VALUE_MISMATCH"]:
        assert fid in f, fid
    assert f["DL_ECOM_DUPLICATE_PUSH"]["severity"] == "High"          # purchase is critical
    assert f["DL_ECOM_VALUE_MISMATCH"]["confidence"] == "Inferred"
    status = {r["event"]: r["status"] for r in rows}
    assert status["add_to_cart"] == "Pushed, with gaps"                  # UA addToCart filed under GA4 name
    assert status["select_item"] == "Not tested"                         # never claimed absent
    assert status["purchase"] == "Pushed, with gaps"


def test_not_pushed_only_where_checked():
    empty = {"entries": [], "forms": [], "formVendors": [], "pii": []}
    per_page = {"pages": [{"url": "https://shop.test/c", "template_label": "Category",
                           "datalayer": empty, "datalayer_expect": ["view_item_list"]}]}
    _, _, rows, _ = ds.run(per_page, None, "ecommerce")
    status = {r["event"]: r["status"] for r in rows}
    assert status["view_item_list"] == "Not pushed"
    assert status["view_item"] == "Not tested"


def test_lead_rules_and_cross_check():
    journey = {"site_type": "lead_gen", "steps": [
        {"step": "generate_lead", "step_label": "Contact form", "status": "exercised",
         "expected_ga4_event": "generate_lead", "url": "https://shop.test/contact",
         "observed": [], "datalayer": CAPTURE}]}
    _, st, rows, findings = ds.run({"pages": []}, journey)
    f = ids(findings)
    assert st == "lead_gen"
    assert "DL_PUSHED_NOT_SENT" in f and f["DL_PUSHED_NOT_SENT"]["owner"] == "GTM"
    assert "DL_LEAD_USER_DATA_PRESENT" in f
    assert "DL_LEAD_NO_CLICK_ID_CAPTURE" not in f                        # the form has utm_source


def test_generic_submit_only():
    cap = {"baselineIndex": 0, "entries": [{"i": 3, "event": "gtm.formSubmit", "src": "push",
                                            "afterBaseline": True, "keys": {}}],
           "forms": [{"id": "f", "action": "same-origin", "fields": [], "hasEmailField": True,
                      "hiddenAttributionFields": [], "looksLikeSearch": False}],
           "formVendors": [], "pii": []}
    journey = {"site_type": "lead_gen", "steps": [
        {"step": "generate_lead", "status": "exercised", "expected_ga4_event": "generate_lead",
         "url": "https://x.test/contact", "observed": [], "datalayer": cap}]}
    _, _, _, findings = ds.run({"pages": []}, journey)
    f = ids(findings)
    assert "DL_LEAD_FROM_GENERIC_SUBMIT" in f
    assert "DL_LEAD_NO_CLICK_ID_CAPTURE" in f


def test_one_severity_per_issue():
    per_page = {"pages": [{"url": "u", "template_label": "P", "datalayer": CAPTURE}]}
    _, _, _, findings = ds.run(per_page, None, "ecommerce")
    out = ids(ds.dedupe_against({"GA4_EVENT_PARAM_MISSING"}, findings))
    assert out["DL_ECOM_REQUIRED_MISSING"]["severity"] == "Info"
    assert out["DL_ECOM_REQUIRED_MISSING"]["root_cause_of"] == ["GA4_EVENT_PARAM_MISSING"]
    assert out["DL_ECOM_LEGACY_SCHEMA"]["severity"] == "High"


def test_doc_and_csv():
    per_page = {"pages": [{"url": "u", "template_label": "P", "datalayer": CAPTURE}]}
    caps, st, rows, findings = ds.run(per_page, None, "mixed")
    with tempfile.TemporaryDirectory() as d:
        md, cv = Path(d) / "spec.md", Path(d) / "dl.csv"
        ds.write_doc(md, "https://shop.test", st, rows, caps, findings)
        ds.write_csv(cv, rows)
        text = md.read_text(encoding="utf-8")
        assert "dataLayer.push({ ecommerce: null });" in text
        assert "wpcf7mailsent" in text                                   # Contact Form 7 listener
        assert "## 4. Forms and lead tracking" in text
        assert cv.read_text(encoding="utf-8").startswith("event,status,key,type")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"{len(tests)} passed")
