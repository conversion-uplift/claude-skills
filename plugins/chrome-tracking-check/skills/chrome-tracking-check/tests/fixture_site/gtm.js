// Stand-in for a GTM container, for the self-test only. It behaves like a
// small real setup: GA4 with Consent Mode, a Google Ads remarketing hit and
// a Meta pixel that (deliberately) fires before consent.
(function () {
  var granted = document.cookie.indexOf('tc_consent=granted') > -1;
  window.google_tag_manager = window.google_tag_manager || {};
  window.google_tag_manager['GTM-TEST123'] = {};
  window.google_tag_manager['G-TEST1234'] = {};
  window.google_tag_manager['AW-999999'] = {};
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ event: 'gtm.js', 'gtm.start': Date.now() });
  window.__s = 0;
  var sid = '1700000000', cid = '111.222';
  if (granted) { document.cookie = '_ga=GA1.1.' + cid + '; path=/'; }
  window.ga4hit = function (en, extra, dupe) {
    window.__s += 1;
    var gcs = granted ? 'G111' : 'G100';
    var gcd = granted ? '13r3r3r3r5' : '13p3p3p3p5';
    var q = 'v=2&tid=G-TEST1234&gtm=45je&gcs=' + gcs + '&gcd=' + gcd + '&cid=' + cid +
      '&sid=' + sid + '&_s=' + window.__s + '&dl=' + encodeURIComponent(location.href) +
      '&en=' + en + (extra || '');
    new Image().src = 'https://region1.google-analytics.com/g/collect?' + q;
    new Image().src = 'https://region1.analytics.google.com/g/collect?' + q; // paired copy, same _s
  };
  window.ga4hit('page_view');
  new Image().src = 'https://googleads.g.doubleclick.net/pagead/viewthroughconversion/999999/?random=1&gcs=' + (granted ? 'G111' : 'G100');
  var s = document.createElement('script');
  s.src = 'https://connect.facebook.net/en_US/fbevents.js'; document.head.appendChild(s);
  window.fbq = function (a, ev) { new Image().src = 'https://www.facebook.com/tr?id=4444&ev=' + ev; };
  window.fbq('track', 'PageView');
  // Replay ecommerce pushes made before the container loaded.
  window.dataLayer.forEach(function (e) { if (e && e.event === 'view_item') window.ga4hit('view_item', '&cu=GBP&epn.value=12.5&pr1=idSKU1~nmTest%20mug~pr12.5~qt1'); });
})();
