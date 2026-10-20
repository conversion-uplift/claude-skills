// probe_baseline.js — run IMMEDIATELY after navigating, before any human interaction.
//
// Does two jobs:
//   1. Marks the dataLayer and resource-list positions so probe_delta.js can diff a
//      single guided-walk step instead of re-reading the whole page.
//   2. Installs buffered PerformanceObservers for LCP and CLS. These must be installed
//      to get field-equivalent lab values; performance.getEntriesByType() alone returns
//      nothing for largest-contentful-paint in this environment.
//
// Lab values captured this way are ALWAYS labelled "lab, single load — not the Google
// assessment" in the report. They are not CrUX. See references/limitations.md.

(() => {
  window.__tcBase = {
    dl: (window.dataLayer || []).length,
    res: performance.getEntriesByType('resource').length
  };
  window.__tcVitals = { lcp: null, cls: 0, shifts: 0, longestEvent: null };

  try {
    new PerformanceObserver(list => {
      const e = list.getEntries();
      window.__tcVitals.lcp = Math.round(e[e.length - 1].startTime);
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (e) {}

  try {
    new PerformanceObserver(list => {
      for (const shift of list.getEntries()) {
        if (!shift.hadRecentInput) { window.__tcVitals.cls += shift.value; window.__tcVitals.shifts++; }
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}

  // Not INP. INP needs real interactions over a real session; this is only the longest
  // event duration seen, and must never be reported as INP.
  try {
    new PerformanceObserver(list => {
      for (const ev of list.getEntries()) {
        const d = Math.round(ev.duration || 0);
        if (!window.__tcVitals.longestEvent || d > window.__tcVitals.longestEvent) window.__tcVitals.longestEvent = d;
      }
    }).observe({ type: 'event', buffered: true, durationThreshold: 16 });
  } catch (e) {}

  return { baselineSet: true, dl: window.__tcBase.dl, resources: window.__tcBase.res, url: location.origin + location.pathname };
})()
