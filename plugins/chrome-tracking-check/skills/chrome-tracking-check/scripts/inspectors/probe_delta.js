// probe_delta.js — run after each human-performed guided-walk step.
//
// Reports ONLY what changed since probe_baseline.js ran, so a walk step costs a small
// tool call rather than a full page re-read. If the step navigated to a new page,
// window.__tcBase is gone; the script says so and you should treat the new page as a
// fresh probe.js capture instead.
//
// The dataLayer entries it returns are summarised, never dumped. GTM's gtm.formInteract
// payload embeds the entire form element and serialises to tens of thousands of tokens.

(() => {
  const base = window.__tcBase || null;
  if (!base) return { navigated: true, note: 'Baseline lost — the step navigated. Run probe.js on the new page.', url: location.origin + location.pathname };

  const dl = window.dataLayer || [];
  const newEntries = dl.slice(base.dl);
  const allRes = performance.getEntriesByType('resource');
  const newRes = allRes.slice(base.res);
  const host = location.hostname;

  const KNOWN = ['g', 'ccm', 'collect', 'pagead', '1p-user-list', 'form-data', 'rmkt', 'tp2', 'x', 'sf', 'tr'];
  const seg = s => KNOWN.includes(s) ? s : { len: s.length };

  const hits = [];
  newRes.forEach(r => {
    let u; try { u = new URL(r.name); } catch (e) { return; }
    const q = u.searchParams;
    if (!(q.has('gcs') || q.has('tid') || q.has('en') || /\/(collect|form-data|1p-user-list|tp2|tr)$|\/x\/sf$/.test(u.pathname))) return;
    hits.push({
      route: u.hostname === host ? 'first-party' : u.hostname,
      segments: u.pathname.split('/').filter(Boolean).map(seg),
      en: q.get('en'), tid: q.get('tid'), gcs: q.get('gcs'),
      ms: Math.round(r.startTime)
    });
  });

  // Summarise, never dump. Note the ecommerce object separately if present.
  const summarised = newEntries.map(e => {
    if (!e || typeof e !== 'object') return { raw: String(e).slice(0, 60) };
    const name = e.event || e[0] || '(unnamed)';
    const out = { event: name };
    if (e.ecommerce) {
      out.ecommerce = {
        keys: Object.keys(e.ecommerce),
        itemCount: Array.isArray(e.ecommerce.items) ? e.ecommerce.items.length : null,
        value: e.ecommerce.value !== undefined ? e.ecommerce.value : null,
        currency: e.ecommerce.currency || null
      };
    }
    if (name === 'gtm.formInteract' || name === 'gtm.formSubmit') {
      out.formField = e['gtm.interactedFormFieldId'] || null;
      out.formName = e['gtm.interactedFormName'] || null;
    }
    return out;
  });

  const ECOM = ['view_item', 'add_to_cart', 'view_cart', 'begin_checkout', 'add_shipping_info',
    'add_payment_info', 'purchase', 'select_item', 'view_item_list', 'remove_from_cart'];

  return {
    navigated: false,
    url: location.origin + location.pathname,
    dataLayerGrew: dl.length - base.dl,
    newEntries: summarised,
    ecommerceEventsSeen: ECOM.filter(n => dl.some(e => e && e.event === n)),
    ecommerceEventsAbsent: ECOM.filter(n => !dl.some(e => e && e.event === n)),
    newTrackingHits: hits,
    newResourceCount: newRes.length,
    vitals: window.__tcVitals || null
  };
})()
