#!/usr/bin/env python3
"""Self-test: run the real inspectors against a local fake shop, then the
whole pipeline (aggregate, journey, score, report, exports).

Needs Playwright for Python and a Chromium build:
    pip install playwright && python -m playwright install chromium
    python tests/run_fixture.py --out /tmp/tc-selftest

Nothing leaves the machine: every request is answered locally.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SITE = HERE / "fixture_site"
INSPECT = SKILL / "scripts" / "inspectors"
BASE = "https://shop.test"


def js(name):
    return (INSPECT / name).read_text()


def route(r):
    u = urlparse(r.request.url)
    if u.hostname == "shop.test":
        f = SITE / (u.path.lstrip("/") or "index.html")
        if f.is_file():
            return r.fulfill(status=200, body=f.read_text(), content_type="text/html")
        return r.fulfill(status=404, body="not found")
    if u.hostname == "www.googletagmanager.com" and u.path == "/gtm.js":
        return r.fulfill(status=200, body=(SITE / "gtm.js").read_text(),
                         content_type="application/javascript")
    if u.path.endswith(".js"):
        return r.fulfill(status=200, body="", content_type="application/javascript")
    return r.fulfill(status=204, body="")


def run_eval(page, name):
    return page.evaluate(js(name))


def ga4_from_resources(page, since=0):
    """What Claude reads with Resource Timing: GA4 hits as named fields."""
    return page.evaluate("""(since) => performance.getEntriesByType('resource').slice(since)
      .map(r => { try { return new URL(r.name) } catch (e) { return null } })
      .filter(u => u && u.pathname === '/g/collect')
      .map(u => ({host: u.hostname, en: u.searchParams.get('en'), s: u.searchParams.get('_s'),
                  sid: u.searchParams.get('sid'), dl: u.searchParams.get('dl'),
                  value: u.searchParams.get('epn.value'), cu: u.searchParams.get('cu'),
                  tid: u.searchParams.get('tid'), tx: u.searchParams.get('ep.transaction_id'),
                  items: [...u.searchParams.keys()].filter(k => /^pr\\d+$/.test(k)).length}))""", since)


def other_platforms(page):
    return page.evaluate("""() => {
      const h = performance.getEntriesByType('resource').map(r => r.name);
      return {google_ads: h.some(x => /googleadservices|doubleclick\\.net\\/pagead|\\/ccm\\/collect/.test(x) && /conversion\\//.test(x) && !/viewthroughconversion/.test(x)),
              meta: h.some(x => /facebook\\.com\\/tr/.test(x)), meta_events: h.filter(x => /facebook\\.com\\/tr/.test(x)).map(x => new URL(x).searchParams.get('ev'))};
    }""")


def step_record(step, label, who, url, expected, hits, plats):
    seen = {}
    for h in hits:
        if h["en"] != expected:
            continue
        key = (h["s"], h["sid"], h["dl"])  # paired hosts with same _s = one hit
        seen.setdefault(key, h)
    obs = []
    if seen:
        first = list(seen.values())[0]
        obs.append({"name": expected, "ga4_hits": len(seen), "distinct_s_count": len(seen),
                    "s_values": sorted(int(k[0]) for k in seen),
                    "value": float(first["value"]) if first["value"] else None,
                    "currency": first["cu"], "item_count": first["items"],
                    "transaction_id": first["tx"], "source": "GTM"})
    return {"step": expected, "step_label": label, "performed_by": who, "status": "exercised",
            "url": url.split("?")[0], "expected_ga4_event": expected, "observed": obs,
            "platforms_received": {"ga4": bool(seen), "google_ads": plats["google_ads"],
                                   "meta": plats["meta"]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--chromium", default=os.environ.get("CHROMIUM_PATH"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    pages = []
    with sync_playwright() as p:
        kw = {"executable_path": a.chromium} if a.chromium else {}
        browser = p.chromium.launch(**kw)

        # ---- automated mode: two passes per page in fresh contexts ----
        for path, label in [("/", "Homepage"), ("/product.html", "Product"), ("/checkout.html", "Checkout")]:
            rec = {"url": BASE + path, "template_label": label, "network_status_codes": {},
                   "interactions_performed": "none"}
            for pass_name in ("pre_consent", "post_consent"):
                ctx = browser.new_context(ignore_https_errors=True)
                ctx.route("**/*", route)
                pg = ctx.new_page()
                errs = []
                pg.on("console", lambda m: errs.append({"message": m.text, "source": "console"}) if m.type == "error" else None)
                pg.on("response", lambda r: rec["network_status_codes"].__setitem__(r.url.split("?")[0], r.status))
                pg.goto(BASE + path)
                if pass_name == "post_consent":
                    pg.click("#accept")
                    pg.reload()
                run_eval(pg, "probe_baseline.js")
                pg.wait_for_timeout(2000)
                rec[pass_name] = run_eval(pg, "probe.js")
                rec["console_errors_pre" if pass_name == "pre_consent" else "console_errors_post"] = errs
                ctx.close()
            pages.append(rec)

        # ---- journey mode: the test plays the person ----
        ctx = browser.new_context(ignore_https_errors=True)
        ctx.route("**/*", route)
        pg = ctx.new_page()
        pg.goto(BASE + "/"); pg.click("#accept")
        steps = []
        pg.goto(BASE + "/product.html"); run_eval(pg, "probe_baseline.js"); pg.wait_for_timeout(1000)
        steps.append(step_record("view_item", "Product page", "claude", pg.url, "view_item",
                                 ga4_from_resources(pg), other_platforms(pg)))
        n = len(pg.evaluate("performance.getEntriesByType('resource')"))
        run_eval(pg, "probe_baseline.js")
        pg.click("#add"); pg.wait_for_timeout(1000)          # the person adds to basket
        delta = run_eval(pg, "probe_delta.js")
        assert not delta["navigated"], delta
        steps.append(step_record("add_to_cart", "Add to basket", "user", pg.url, "add_to_cart",
                                 ga4_from_resources(pg, n), other_platforms(pg)))
        pg.click("text=Checkout"); pg.wait_for_load_state(); pg.wait_for_timeout(1000)   # the person
        steps.append(step_record("begin_checkout", "Go to checkout", "user", pg.url, "begin_checkout",
                                 ga4_from_resources(pg), other_platforms(pg)))
        steps.append({"step": "add_shipping_info", "step_label": "Delivery details", "performed_by": "user",
                      "status": "no_separate_step", "url": pg.url.split("?")[0], "expected_ga4_event": "add_shipping_info"})
        pg.fill("input[name=email]", "test@example.com")                       # the person
        pg.click("#pay"); pg.wait_for_load_state(); pg.wait_for_timeout(1000)             # the person
        conf = run_eval(pg, "probe.js")
        steps.append(step_record("purchase", "Test purchase", "user", pg.url, "purchase",
                                 ga4_from_resources(pg), other_platforms(pg)))
        ctx.close(); browser.close()
    journey = {"site_type": "ecommerce", "permission_confirmed": True,
               "platforms_present": ["ga4", "google_ads", "meta"],
               "test_purchase": "fixture order on the local test shop", "steps": steps}
    (out / "journey.json").write_text(json.dumps(journey, indent=1))
    # Pages reached during the journey go into the per-page file too, so the
    # page-level rules (personal data in payloads, consent) run on them.
    pages.append({"url": conf["meta"]["url"].split("?")[0], "template_label": "Journey: order confirmation",
                  "pre_consent": None, "post_consent": conf, "interactions_performed": "test purchase by the person"})
    per_page = out / "audit_per_page.json"
    per_page.write_text(json.dumps({"clean_state": True, "pages": pages}, indent=1))

    S = SKILL / "scripts"
    def py(*args):
        print("$", " ".join(str(x) for x in args[1:3]), "...")
        subprocess.run([sys.executable, *map(str, args)], check=True)
    py(S / "aggregate_findings.py", "--per-page", per_page, "--output", out / "agg.json")
    py(S / "journey_checks.py", "--journey", out / "journey.json", "--aggregated", out / "agg.json", "--output", out / "agg.json")
    py(S / "severity_scorer.py", "--findings", out / "agg.json", "--output", out / "scored.json")
    py(S / "build_report.py", "--scored", out / "scored.json", "--site", BASE, "--output", out / "tracking_check_shop_test.docx")
    py(S / "exporters.py", "--scored", out / "scored.json", "--per-page", per_page, "--site", BASE, "--output-dir", out)
    sc = json.loads((out / "scored.json").read_text())
    print("Grade", sc["grade"], sc["score"], sc["summary_counts"])
    for f in sc["findings"]:
        print(f" - [{f['severity']}{'+' if f.get('positive') else ''}] {f['id']}: {f['title']}")


if __name__ == "__main__":
    main()
