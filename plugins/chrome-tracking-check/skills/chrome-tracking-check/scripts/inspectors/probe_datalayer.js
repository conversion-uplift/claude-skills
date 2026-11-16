// probe_datalayer.js — document the page's data layer and its forms, safely.
//
// Run it after probe.js on any page where ecommerce or lead events matter
// (product, category, basket, checkout, confirmation, contact, thank-you), and
// after each journey step. Its output goes into the page or step record as
// "datalayer"; scripts/datalayer_spec.py turns it into findings and a data
// layer specification a developer can work from.
//
// WHAT IT RETURNS, AND WHAT IT NEVER RETURNS
//   - The SHAPE of every dataLayer entry: key paths and their types.
//   - Values only for a short list of safe keys (event, currency, numeric
//     value / tax / shipping, form_id, form_name, form_type, lead_source,
//     method, payment_type, shipping_tier, item_list_name). Each is capped
//     at 40 characters and dropped if it looks like an email or phone number.
//   - transaction_id as length + a short fingerprint, so a reused or repeated
//     order ID can be spotted without recording the ID.
//   - Forms as field NAMES and types. Field values are never read.
//   - Email or phone numbers anywhere in the data layer are recorded as a flag
//     with the key path, never the value.
//
// Synchronous on purpose: top-level await fails in javascript_tool. The IIFE
// value is the result. If probe_baseline.js ran, entries pushed after it are
// marked afterBaseline: true, which is how a journey step finds its own pushes.

(() => {
  const dl = Array.isArray(window.dataLayer) ? window.dataLayer : [];
  const base = window.__tcBase ? window.__tcBase.dl : null;
  const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, PHONE = /(?:\+44\s?|\b0)7\d{3}\s?\d{6}\b|\+\d{10,14}\b/;
  const HASHED = /^[a-f0-9]{64}$/i;
  const SAFE = ['event', 'currency', 'form_id', 'form_name', 'form_type', 'lead_source', 'lead_type',
    'method', 'payment_type', 'shipping_tier', 'item_list_name', 'item_list_id', 'content_type'];
  const NUM = ['value', 'tax', 'shipping', 'discount'];
  const USER_DATA = ['user_data', 'enhanced_conversion_data', 'ec_data', 'userData'];
  const SKIP = /^gtm\.(js|dom|load|init|init_consent|timer|historyChange|historyChange-v2|scrollDepth|elementVisibility|video)$/;
  const isEl = v => typeof Element !== 'undefined' && v instanceof Element;
  const typeOf = v => v === null ? 'null' : Array.isArray(v) ? 'array' : isEl(v) ? 'element' : typeof v;
  const fp = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return h.toString(16).slice(-6); };
  const pii = [];
  const piiCheck = (v, path, i) => {
    if (typeof v !== 'string') return false;
    if (EMAIL.test(v)) { pii.push({ i, path, kind: 'email' }); return true; }
    if (PHONE.test(v)) { pii.push({ i, path, kind: 'phone' }); return true; }
    return false;
  };

  // Key paths with types, depth 3, arrays summarised by their first element.
  const shape = (obj, prefix, out, depth, i) => {
    if (depth > 3 || !obj || typeof obj !== 'object' || isEl(obj)) return out;
    Object.keys(obj).slice(0, 40).forEach(k => {
      if (/^gtm\.(element|triggers|uniqueEventId|start|priorityId)/.test(k)) return;
      const v = obj[k], path = prefix ? prefix + '.' + k : k;
      out[path] = typeOf(v);
      piiCheck(v, path, i);
      if (Array.isArray(v) && v.length && typeof v[0] === 'object') shape(v[0], path + '[]', out, depth + 1, i);
      else if (typeOf(v) === 'object') shape(v, path, out, depth + 1, i);
    });
    return out;
  };

  const UA_ACTIONS = ['detail', 'add', 'remove', 'checkout', 'checkout_option', 'purchase', 'refund', 'impressions', 'click', 'promoView', 'promoClick'];
  const ecomSummary = (ec, i) => {
    const ua = UA_ACTIONS.filter(a => ec && ec[a]);
    const items = Array.isArray(ec.items) ? ec.items
      : ua.length && ec[ua[0]] && Array.isArray(ec[ua[0]].products) ? ec[ua[0]].products
      : Array.isArray(ec.impressions) ? ec.impressions : [];
    const itemKeys = {};
    items.slice(0, 50).forEach(it => Object.keys(it || {}).forEach(k => {
      const t = typeOf(it[k]); itemKeys[k] = itemKeys[k] && itemKeys[k] !== t ? 'mixed' : t;
    }));
    let sum = 0, sumOk = items.length > 0;
    items.forEach(it => {
      const p = Number(it && it.price), q = it && it.quantity !== undefined ? Number(it.quantity) : 1;
      if (typeof (it && it.price) !== 'number' || isNaN(p) || isNaN(q)) sumOk = false; else sum += p * q;
    });
    const tx = ec.transaction_id !== undefined ? ec.transaction_id : ua.length && ec[ua[0]].actionField ? ec[ua[0]].actionField.id : undefined;
    const out = {
      shape: Array.isArray(ec.items) ? (ua.length ? 'mixed' : 'ga4') : ua.length ? 'ua' : 'none',
      uaActions: ua,
      currencyType: typeOf(ec.currency),
      currency: typeof ec.currency === 'string' ? (/^[A-Z]{3}$/.test(ec.currency) ? ec.currency : 'invalid') : null,
      itemCount: items.length,
      itemKeys,
      itemsWithoutIdOrName: items.filter(it => !it || (it.item_id === undefined && it.item_name === undefined && it.id === undefined && it.name === undefined)).length,
      itemsWithoutPrice: items.filter(it => !it || it.price === undefined).length,
      itemsWithoutQuantity: items.filter(it => !it || it.quantity === undefined).length,
      itemSum: sumOk ? Math.round(sum * 100) / 100 : null,
      transactionId: tx === undefined || tx === null || tx === '' ? null : { type: typeOf(tx), len: String(tx).length, fp: fp(String(tx)) }
    };
    NUM.forEach(k => {
      if (ec[k] === undefined) return;
      out[k + 'Type'] = typeOf(ec[k]);
      if (typeof ec[k] === 'number') out[k] = ec[k];
      else if (typeof ec[k] === 'string') out[k + 'Numeric'] = /^-?\d+(\.\d+)?$/.test(ec[k].trim());
    });
    return out;
  };

  const userData = obj => {
    for (const k of USER_DATA) {
      const ud = obj && obj[k];
      if (ud && typeof ud === 'object') {
        const keys = {};
        Object.keys(ud).slice(0, 20).forEach(f => {
          const v = ud[f];
          keys[f] = typeof v !== 'string' ? typeOf(v) : HASHED.test(v) ? 'hashed' : (EMAIL.test(v) || PHONE.test(v)) ? 'plain' : 'string';
        });
        return { key: k, fields: keys };
      }
    }
    return null;
  };

  const entries = [], skipped = {};
  let lastEcomCleared = true, ecomPushes = 0;
  dl.forEach((e, i) => {
    if (!e || typeof e !== 'object') return;
    let name, params, src = 'push';
    if (e[0] === 'event' && typeof e[1] === 'string') { name = e[1]; params = e[2] || {}; src = 'gtag'; }
    else if (e[0] !== undefined) return;  // gtag config / consent / set commands: covered by probe.js
    else { name = e.event || null; params = e; }
    if ('ecommerce' in e && (e.ecommerce === null || e.ecommerce === undefined)) { lastEcomCleared = true; if (!name) return; }
    if (name && SKIP.test(name)) { skipped[name] = (skipped[name] || 0) + 1; return; }
    const ec = src === 'gtag' ? (params.items || params.value !== undefined ? params : null) : (e.ecommerce && typeof e.ecommerce === 'object' ? e.ecommerce : null);
    const rec = { i, event: name || '(no event key)', src, afterBaseline: base !== null && i >= base };
    rec.keys = shape(params, '', {}, 0, i);
    if (ec) {
      ecomPushes++;
      rec.ecommerce = ecomSummary(ec, i);
      rec.ecommerce.clearedBefore = src === 'gtag' ? true : lastEcomCleared;
      lastEcomCleared = false;
    }
    const safe = {};
    SAFE.forEach(k => {
      const v = params[k];
      if (typeof v === 'string' && v && !EMAIL.test(v) && !PHONE.test(v)) safe[k] = v.slice(0, 40);
    });
    if (Object.keys(safe).length) rec.safeValues = safe;
    const ud = userData(params) || (e.ecommerce && userData(e.ecommerce));
    if (ud) rec.userData = ud;
    if (name === 'gtm.formSubmit' || name === 'gtm.formInteract') {
      rec.form = { id: (e['gtm.elementId'] || '').slice(0, 40) || null, classes: (e['gtm.elementClasses'] || '').slice(0, 60) || null };
    }
    entries.push(rec);
  });
  // user_data values are expected to be personal data; record them as a separate kind.
  const udPaths = new Set();
  entries.forEach(r => r.userData && Object.keys(r.userData.fields).forEach(f => udPaths.add(r.i + ':' + r.userData.key + '.' + f)));
  const piiOut = pii.map(p => ({ ...p, inUserData: udPaths.has(p.i + ':' + p.path) || USER_DATA.some(k => p.path.startsWith(k + '.')) }));

  // ---- Forms: names and types only, never values ----
  const ATTR = /^(gclid|gbraid|wbraid|fbclid|msclkid|ttclid|li_fat_id|utm_[a-z]+|_ga|client_id|landing_page|referrer)$/i;
  const host = location.hostname;
  const forms = Array.from(document.forms).slice(0, 15).map(f => {
    const fields = Array.from(f.elements).filter(el => el.name || el.id).slice(0, 30);
    let action = 'none';
    const raw = f.getAttribute('action');
    if (raw && /^javascript:/i.test(raw)) action = 'javascript';
    else if (raw) { try { const u = new URL(raw, location.href); action = u.hostname === host ? 'same-origin' : 'third-party: ' + u.hostname.split('.').join(' '); } catch (err) { action = 'unparseable'; } }
    if (raw && /example|placeholder|yourprovider|localhost/i.test(raw)) action = 'placeholder';
    const submit = f.querySelector('button[type=submit],input[type=submit],button:not([type])');
    return {
      id: (f.id || '').slice(0, 40) || null, name: (f.getAttribute('name') || '').slice(0, 40) || null,
      classes: (f.className && typeof f.className === 'string' ? f.className : '').slice(0, 60) || null,
      action, method: (f.method || 'get').toLowerCase(),
      fields: fields.map(el => ({ name: (el.name || el.id).slice(0, 40), type: (el.type || el.tagName).toLowerCase(), required: !!el.required })),
      hasEmailField: fields.some(el => el.type === 'email' || /e-?mail/i.test(el.name || '')),
      hasPhoneField: fields.some(el => el.type === 'tel' || /phone|tel|mobile/i.test(el.name || '')),
      hiddenAttributionFields: fields.filter(el => el.type === 'hidden' && ATTR.test(el.name || '')).map(el => el.name),
      submitLabel: submit ? (submit.innerText || submit.value || '').trim().slice(0, 40) : null,
      looksLikeSearch: fields.length <= 2 && fields.some(el => el.type === 'search' || /^(q|s|search|query)$/i.test(el.name || ''))
    };
  });

  // ---- Form platform detection: decides which success listener to recommend ----
  const has = s => { try { return !!document.querySelector(s); } catch (err) { return false; } };
  const iframe = re => Array.from(document.querySelectorAll('iframe[src]')).some(f => re.test(f.src));
  const VENDORS = {
    hubspot: () => !!window.hbspt || has('form.hs-form, .hs-form-frame, [data-hs-forms-root]') || iframe(/hsforms|hubspot/),
    marketo: () => !!window.MktoForms2 || has('form.mktoForm'),
    gravity_forms: () => !!window.gform || has('.gform_wrapper'),
    contact_form_7: () => has('.wpcf7'),
    wpforms: () => has('.wpforms-form'),
    ninja_forms: () => has('.nf-form-cont'),
    elementor: () => has('form.elementor-form'),
    fluent_forms: () => has('form.frm-fluent-form'),
    formidable: () => has('.frm_forms'),
    webflow: () => has('.w-form'),
    squarespace: () => has('.sqs-block-form, [data-form-id]') && !!window.Static,
    klaviyo: () => has('.klaviyo-form, [class*="kl-private"]') || !!window._klOnsite,
    mailchimp: () => Array.from(document.forms).some(f => /list-manage\.com/.test(f.action)),
    salesforce_web_to_lead: () => Array.from(document.forms).some(f => /salesforce\.com\/servlet\/servlet\.WebToLead/i.test(f.action)),
    pardot: () => iframe(/pardot|go\.pardot|pi\.pardot/),
    dynamics_365: () => has('[data-form-block-id], .d365-mkt-config') || iframe(/dynamics\.com/),
    typeform: () => !!window.tf || has('[data-tf-widget],[data-tf-popup]') || iframe(/typeform\.com/),
    jotform: () => iframe(/jotform/),
    calendly: () => !!window.Calendly || iframe(/calendly\.com/),
    shopify_contact: () => Array.from(document.forms).some(f => /\/contact(#|$)/.test(f.getAttribute('action') || ''))
  };
  const formVendors = Object.keys(VENDORS).filter(k => { try { return VENDORS[k](); } catch (err) { return false; } });

  return {
    url: location.origin + location.pathname,
    dataLayerLength: dl.length,
    baselineIndex: base,
    entries: entries.slice(-80),
    entriesTruncated: entries.length > 80,
    ecommercePushes: ecomPushes,
    skippedGtmEvents: skipped,
    pii: piiOut,
    forms,
    formVendors
  };
})()
