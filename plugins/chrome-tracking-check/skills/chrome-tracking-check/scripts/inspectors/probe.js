// probe.js — THE inspector. Paste this into mcp__claude-in-chrome__javascript_tool
// (action: javascript_exec) after each navigation. ~5KB, readable, cheap to repeat.
//
// WHY IT IS SMALL AND READABLE
//   The JS tool takes the script text as an argument, so every call pays for the
//   whole script in tokens. A standard check needs about twenty calls, so the
//   inspector stays around 10KB. It also stays readable: an opaque or compressed
//   blob injected into a page is indistinguishable from an attack, and the safety
//   classifier rightly blocks it. Anyone installing this skill can read every line.
//
// REDACTION-RESISTANT BY DESIGN — read this before editing.
//   The Chrome extension redacts tool output that looks sensitive. In practice it
//   blanks: query strings, base64-ish path segments, and any hostname resembling a
//   JWT (which includes www.googletagmanager.com). Since this whole skill depends on
//   reading query parameters, NEVER return raw URLs. Extract the params you need into
//   named fields, and describe paths by segment classification. That is why the code
//   below looks indirect; it is deliberate.
//
// Returns one object. Do not add a top-level `return` — the IIFE value is the result.
// Top-level `await` FAILS in this tool despite its docs. Keep everything synchronous.

(() => {
  const uniq = a => Array.from(new Set(a));
  const html = document.documentElement.outerHTML;
  const inline = Array.from(document.querySelectorAll('script:not([src])')).map(s => s.textContent || '').join('\n');
  const srcs = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
  const grab = re => uniq(html.match(re) || []);
  const dl = Array.isArray(window.dataLayer) ? window.dataLayer : [];
  const cookies = document.cookie.split(';').map(s => s.trim().split('=')[0]).filter(Boolean);
  let ls = []; try { ls = Object.keys(localStorage); } catch (e) { ls = ['BLOCKED']; }
  const host = location.hostname;

  // Personal data never leaves the page. URLs are reported as origin + path +
  // parameter NAMES; any email or UK mobile number in a value is recorded as a
  // flag (kind + where), never as the value itself.
  const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, PHONE = /(?:\+44|\b0)7\d{9}\b/;
  const pii = [];
  const flag = (val, where) => {
    let v = String(val || ''); try { v = decodeURIComponent(v); } catch (e) {}
    if (EMAIL.test(v)) pii.push({ kind: 'email', where });
    else if (PHONE.test(v)) pii.push({ kind: 'phone', where });
  };
  const scrub = (u, where) => {
    try {
      const x = new URL(u, location.href);
      x.searchParams.forEach((v, k) => flag(v, (where || 'url') + ' ' + k));
      const names = Array.from(new Set(Array.from(x.searchParams.keys())));
      return x.origin + x.pathname + (names.length ? '?' + names.join(',') : '');
    } catch (e) { return null; }
  };

  // Known path segments. Anything else is reported by length + character class only,
  // which both survives redaction and reveals random gateway prefixes.
  const KNOWN = ['g', 'j', 'a', 'ccm', 'collect', 'pagead', '1p-user-list', 'form-data', 'rmkt',
    'gtm', 'gtag', 'js', 'gtm.js', 'td', 'tp2', 'i', 'x', 'sf', 'tr', 's', 'conversion',
    'viewthroughconversion', 'debug', 'sgtm', 'server', 'stape'];
  const seg = s => KNOWN.includes(s) ? s : { len: s.length, cls: /^[a-z]+$/.test(s) ? 'lower' : /^[a-z0-9-]+$/.test(s) ? 'alnum' : 'mixed' };

  // ---- Network: classify every measurement-ish request ----
  const PARAMS = ['tid', 'gcs', 'gcd', 'en', '_s', 'sid', 'cid', 'dl', 'id', 'gtm', 'npa',
    'gtg_health', 'tag_exp', 'dma', 'ep.ads_data_redaction', 'did', 'tids', 'v', 't', 'ev'];
  const requests = [];
  performance.getEntriesByType('resource').forEach(r => {
    let u; try { u = new URL(r.name); } catch (e) { return; }
    const p = u.pathname, q = u.searchParams;
    const measurement = q.has('gcs') || q.has('tid') || q.has('en') ||
      /\/(collect|tp2|form-data|1p-user-list|rmkt)$|\/collect\/|\/i$|\/x\/sf$|\/tr$/.test(p);
    const loader = /gtm\.js|gtag\/js|gtag\.js/.test(p) || q.has('gtg_health');
    if (!measurement && !loader) return;
    const params = {};
    PARAMS.forEach(k => { if (q.has(k)) params[k] = q.get(k); });
    q.forEach((v, k) => flag(v, u.hostname + ' ' + k));
    if (params.dl) params.dl = scrub(params.dl, 'dl');
    if (params.dr) params.dr = scrub(params.dr, 'dr');
    requests.push({
      firstParty: u.hostname === host,
      vendor: u.hostname === host ? '(site origin)' : u.hostname,
      segments: p.split('/').filter(Boolean).map(seg),
      role: loader ? 'loader' : 'measurement',
      params,
      paramCount: Array.from(q.keys()).length,
      paramNames: measurement ? uniq(Array.from(q.keys())).slice(0, 60) : [],
      serverTiming: (r.serverTiming || []).map(s => s.name),
      protocol: r.nextHopProtocol || null,
      bytes: r.transferSize,
      ms: Math.round(r.startTime)
    });
  });

  // Rule 1 counting. /ccm/collect and AW- tids are Google Ads, never GA4.
  const ga4Hits = requests.filter(r => r.params.tid && /^G-/.test(r.params.tid) &&
    r.segments.some(s => s === 'collect') && r.segments.some(s => s === 'g'));
  const adsHits = requests.filter(r => (r.params.tid && /^AW-/.test(r.params.tid)) ||
    r.segments.includes('ccm') || r.segments.includes('1p-user-list'));

  // ---- Tag Gateway (see references/tag_gateway_detection.md) ----
  const gateway = {
    gtgHealthSeen: requests.some(r => r.params.gtg_health),
    firstPartyCollect: requests.filter(r => r.firstParty && r.role === 'measurement').length,
    directGoogleCollect: requests.filter(r => !r.firstParty && r.role === 'measurement' &&
      /google|doubleclick/i.test(r.vendor)).length,
    loaderFirstParty: requests.some(r => r.firstParty && r.role === 'loader'),
    cloudflareServerTiming: requests.some(r => r.firstParty && r.serverTiming.some(n => /^cf/i.test(n)))
  };

  // ---- Google Ads automatic form-data collection ----
  const adsFormData = {
    formDataHits: requests.filter(r => r.segments.includes('form-data')).length,
    formStartEvents: requests.filter(r => r.params.en === 'form_start').length
  };

  // ---- Consent ----
  let ics = null;
  try {
    const e = window.google_tag_data && window.google_tag_data.ics && window.google_tag_data.ics.entries;
    if (e) ics = Object.fromEntries(Object.entries(e).map(([k, v]) =>
      [k, { default: v.default, update: v.update, region: v.region, implicit: v.implicit }]));
  } catch (e) { ics = 'ERROR'; }
  const CMP = ['OneTrust', 'Cookiebot', '__tcfapi', 'Osano', 'Klaro', 'CookieControl', 'usercentrics',
    'Didomi', '__cmp', 'CookieConsent', 'Termly', 'cookieyes', 'axeptio', 'Cookiehub', '_iub', '__gpp'];

  // ---- Vendors ----
  const globals = {};
  ['gtag', 'fbq', 'ttq', 'lintrk', 'uetq', 'pintrk', 'snaptr', 'rdt', 'clarity', 'hj', 'FS',
    '_mfq', 'analytics', 'utag', '_hsq', 'klaviyo', 'snowplow', 'Shopify', 'Tawk_API'
  ].forEach(g => { if (typeof window[g] !== 'undefined') globals[g] = typeof window[g]; });

  const metaOf = n => { const el = document.querySelector('meta[name="' + n + '"],meta[property="' + n + '"]'); return el ? el.content : null; };
  const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => {
    try { const j = JSON.parse(s.textContent); const t = x => x && x['@type'];
      return Array.isArray(j) ? j.map(t).join(',') : (j['@graph'] ? j['@graph'].map(t).join(',') : t(j)); }
    catch (e) { return 'PARSE_ERROR'; }
  });

  let lcp = null; try { const e = performance.getEntriesByType('largest-contentful-paint'); if (e.length) lcp = Math.round(e[e.length - 1].startTime); } catch (e) {}
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const links = Array.from(document.querySelectorAll('a[href]'));

  return {
    meta: { url: scrub(location.href, 'page'), title: document.title, ready: document.readyState },
    pii,
    privacy: { gpc: navigator.globalPrivacyControl === true },
    ids: {
      ga4: grab(/G-[A-Z0-9]{6,12}/g), gtm: grab(/GTM-[A-Z0-9]{4,9}/g), ads: grab(/AW-[0-9]{9,12}/g),
      ua: grab(/UA-\d{4,10}-\d{1,4}/g),
      metaPixel: uniq(inline.match(/fbq\(\s*['"]init['"]\s*,\s*['"](\d{10,20})['"]/g) || []),
      clarity: grab(/clarity\.ms\/tag\/[a-z0-9]+/g),
      runtimeContainers: Object.keys(window.google_tag_manager || {}).filter(k => /^(G-|GTM-|AW-|DC-)/.test(k))
    },
    // A container in `ids.gtm` but NOT in runtimeContainers is referenced yet never loads.
    dataLayer: {
      length: dl.length,
      events: dl.map(e => e && (e.event || e[0])).filter(Boolean),
      hasEcommerce: dl.some(e => e && e.ecommerce),
      ecommerceEvents: dl.filter(e => e && e.ecommerce).map(e => e.event || '(no event name)'),
      consentPushes: dl.filter(e => e && e[0] === 'consent').map(e => ({ cmd: e[1], state: e[2] }))
    },
    consent: {
      ics,
      cmpGlobals: CMP.filter(g => typeof window[g] !== 'undefined'),
      // CMPs (Clickio, others) mirror the choice into localStorage as well as a cookie.
      // Clearing only cookies leaves the choice in force. See capture rule 2.
      consentCookies: cookies.filter(n => /consent|cmp|lxG|onetrust|cookiebot|osano|didomi|euconsent/i.test(n)),
      consentStorage: ls.filter(n => /consent|cmp|lxG|onetrust|cookiebot|osano|didomi|euconsent/i.test(n)),
      bannerTextVisible: /cookie|consent|privacy/i.test((document.body.innerText || '').slice(0, 4000))
    },
    cookies: {
      all: cookies,
      google: cookies.filter(n => /^(_ga|_gid|_gcl|_gac|FPID|FPLC|FPAU|IDE)/.test(n)),
      vendor: cookies.filter(n => /^(sf_|_sp_|twk|Tawk|_fbp|_fbc|_uet|_ttp|li_|_scid)/.test(n)),
      snowplowStorage: ls.filter(n => /snowplow|_sp_|lscache-sf_/.test(n)).length
    },
    vendors: { globals, trackingScripts: srcs.filter(u => /googletagmanager|google-analytics|googleadservices|doubleclick|facebook|fbevents|tiktok|licdn|bat\.bing|clarity|hotjar|fullstory|mouseflow|snowplow|salesfire|smartmetrics|segment|tealium|klaviyo|hubspot|pinterest|snapchat|reddit|criteo|doofinder|tawk|trustpilot/i.test(u)).length },
    network: {
      requests,
      ga4CollectCount: ga4Hits.length,
      adsHitCount: adsHits.length,
      gateway,
      adsFormData,
      thirdPartyHosts: uniq(performance.getEntriesByType('resource').map(r => { try { return new URL(r.name).hostname; } catch (e) { return ''; } }).filter(h => h && h !== host))
    },
    seo: {
      title: document.title, titleLen: document.title.length,
      description: metaOf('description'), robots: metaOf('robots'),
      canonical: (document.querySelector('link[rel=canonical]') || {}).href || null,
      h1: Array.from(document.querySelectorAll('h1')).map(h => h.textContent.trim().slice(0, 90)),
      hreflang: Array.from(document.querySelectorAll('link[rel=alternate][hreflang]')).map(l => l.hreflang),
      jsonldTypes: ld, microdataItems: document.querySelectorAll('[itemscope]').length,
      ogTitle: !!metaOf('og:title'), ogImage: !!metaOf('og:image'), twitterCard: !!metaOf('twitter:card'),
      lang: document.documentElement.lang, gscVerification: !!document.querySelector('meta[name="google-site-verification"]'),
      internalLinks: links.filter(a => { try { return new URL(a.href).hostname === host; } catch (e) { return false; } }).length,
      totalLinks: links.length
    },
    perf: { lcpMs: lcp, ttfbMs: Math.round(nav.responseStart || 0), domCompleteMs: Math.round(nav.domComplete || 0), loadMs: Math.round(nav.loadEventEnd || 0), transferKb: Math.round((nav.transferSize || 0) / 1024), resources: performance.getEntriesByType('resource').length, vitals: window.__tcVitals || null }
  };
})()
