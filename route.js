/* Sol-0 live page v2: the anchor router (DESIGN.md §6). Loaded in <head>, synchronously: it sets the language, the tab and the layout
   mode on <html> before the first paint, so that nothing jumps at load. Pure functions are exported for node tests.
   Anchors: #<lang>/<tab>[/<part>]  e.g. #fr/live, #en/about, #fr/live/cam, #en/about/brain. No element id contains '/', so the browser
   never scrolls by itself: the page does (app.js). Old links #fr and #en still work (= live in that language). No storage, no cookie. */
(function (root) {
  'use strict';
  var PANEL_IDS = ['cam', 'brain', 'map', 'tel', 'inst'];
  // sections of the « How it works » tab (data-sec of the explainer), and short aliases
  var SECTIONS = ['intro', 'planet', 'body', 'brain', 'learn', 'camera', 'stages', 'console', 'live', 'real', 'journal', 'faq', 'glossary'];
  var ALIAS = {what: 'intro', map: 'console', telemetry: 'console', scan: 'console', words: 'glossary', top: 'intro'};
  // the section that explains each panel (help link of the enlarged panel)
  var HELP = {cam: 'camera', brain: 'brain', map: 'console', tel: 'console', inst: 'console'};

  function tokens(hash) {
    var h = String(hash === undefined || hash === null ? '' : hash).replace(/^#/, '').toLowerCase(), out = [];
    h.split('/').forEach(function (t) { if (/^[a-z0-9-]{1,32}$/.test(t)) out.push(t); });
    return out;
  }
  function parse(hash, navLang) {
    var t = tokens(hash), lang = null, tab = 'live', sub = null, i;
    for (i = 0; i < t.length; i++) if (t[i] === 'fr' || t[i] === 'en') { lang = t[i]; break; }
    if (!lang) lang = /^fr/i.test(String(navLang || '')) ? 'fr' : 'en';
    if (t.indexOf('about') >= 0) tab = 'about';
    for (i = 0; i < t.length; i++) {
      var x = t[i];
      if (x === 'fr' || x === 'en' || x === 'live' || x === 'about') continue;
      if (tab === 'live') { if (PANEL_IDS.indexOf(x) >= 0) { sub = x; break; } }
      else { var y = ALIAS[x] || x; if (SECTIONS.indexOf(y) >= 0) { sub = y; break; } }
    }
    return {lang: lang, tab: tab, sub: sub};
  }
  function serialize(r) { return '#' + r.lang + '/' + r.tab + (r.sub ? '/' + r.sub : ''); }
  function same(a, b) { return !!a && !!b && a.lang === b.lang && a.tab === b.tab && (a.sub || null) === (b.sub || null); }
  // EF-87 guard shared by every visual switch (tab, language, enlarge / close / next panel): at most one switch per `minMs`; a request
  // that comes sooner is applied at last + minMs, and only the latest request is applied (the ones in between are skipped).
  function makeGuard(minMs, o) {
    var last = -Infinity, timer = null, pending = null, applied = 0;
    function fire() { timer = null; var f = pending; pending = null; last = o.now(); applied++; if (f) f(); }
    return {
      request: function (fn) {
        pending = fn;
        if (timer !== null) return;
        var wait = last + minMs - o.now();
        if (wait <= 0) fire(); else timer = o.setTimer(fire, wait);
      },
      pending: function () { return timer !== null; },
      applied: function () { return applied; }
    };
  }
  function modeFor(w, h) { return w >= h ? 'console' : 'panels'; }

  var api = {PANEL_IDS: PANEL_IDS, SECTIONS: SECTIONS, ALIAS: ALIAS, HELP: HELP, parse: parse, serialize: serialize, same: same,
             makeGuard: makeGuard, modeFor: modeFor, tokens: tokens};
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  root.Sol0Route = api;
  // before the first paint: language, tab and layout mode on <html> (CSS shows the right view and the right language at once)
  if (typeof document !== 'undefined' && document.documentElement) {
    var r = parse(root.location ? root.location.hash : '', root.navigator ? root.navigator.language : '');
    var html = document.documentElement;
    html.lang = r.lang;
    if (html.dataset) {
      html.dataset.tab = r.tab;
      if (typeof root.innerWidth === 'number' && typeof root.innerHeight === 'number') html.dataset.mode = modeFor(root.innerWidth, root.innerHeight);
    }
  }
})(typeof self !== 'undefined' ? self : this);
