/* Sol-0 live page: the intro cinematic (consignes 51 and 52, out/cinematique/web/README.md). A DRAWN trailer marked ILLUSTRATION (the
   only exception to « all is real »), in a modal <dialog> ABOVE the live: app.js connects and draws underneath meanwhile, and at load
   the video is requested only once app.js has requested its stream (streamStarted(), or after WAIT_STREAM_MS if the page failed).
   First visit (`sol0.intro.seen` in the local storage, read and written in try/catch; without storage: at most once per page load): muted
   autoplay (playsinline), « Sound on / Sound off », « Skip » + Esc + a click outside the film; it closes at the end, never loops.
   prefers-reduced-motion or Save-Data: no autoplay, the header button « Watch the intro » only. Deep link #intro (#fr/intro,
   #en/intro): opens it (reduced motion: on its poster, the film waits for « Play the intro »). EF-87: every open and close goes through
   a switch guard shared with app.js (route.js SWITCH): one switch per 350 ms for the whole page; no transition. */
(function (root) {
  'use strict';
  var KEY = 'sol0.intro.seen', SRC = 'media/intro.mp4', POSTER = 'media/intro-poster.png', WAIT_STREAM_MS = 2000;
  var TYPE = 'video/mp4; codecs="avc1.64001E, mp4a.40.2"';
  function isDeepLink(hash) {
    var t = String(hash === undefined || hash === null ? '' : hash).replace(/^#/, '').toLowerCase().split('/');
    if (t.length === 2 && (t[0] === 'fr' || t[0] === 'en')) t.shift();
    return t.length === 1 && t[0] === 'intro';
  }
  // at load: 'play' (open, muted autoplay), 'open' (open on the poster, the film waits for a click), 'none'. A first visit that lands
  // on « How it works » or on an enlarged panel is left alone (no autoplay over what the visitor asked for; à re-valider).
  function decide(o) {
    if (!o.supported) return 'none';
    if (o.deep) return o.reduced ? 'open' : 'play';
    return (o.seen || o.reduced || o.saveData || o.tab !== 'live' || o.sub) ? 'none' : 'play';
  }
  var api = {KEY: KEY, SRC: SRC, POSTER: POSTER, TYPE: TYPE, WAIT_STREAM_MS: WAIT_STREAM_MS, isDeepLink: isDeepLink, decide: decide};
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = root.document, Route = root.Sol0Route, $ = function (id) { return doc.getElementById(id); };
  var dlg = $('intro'), box = $('intro-box'), v = $('intro-v'), btn = $('introbtn'), skip = $('intro-skip'), snd = $('intro-snd');
  var play = $('intro-play'), sOn = $('intro-snd-on'), sOff = $('intro-snd-off');
  var open = false, sound = false, opener = null, streamUp = false, waiting = false, waitTimer = null, gen = 0, ok = false;
  root.Sol0Intro = {isOpen: function () { return open; }, streamStarted: function () { streamUp = true; if (waiting) begin(); }};
  try { ok = !!(Route && dlg && typeof dlg.showModal === 'function' && v && typeof v.canPlayType === 'function' && v.canPlayType(TYPE) !== '' && btn); }
  catch (e) { ok = false; }
  if (!ok) return;                     // no <dialog> or no H.264: no intro, the button stays hidden
  var guard = Route.makeGuard(350, {now: function () { return Date.now(); }, setTimer: function (f, ms) { return setTimeout(f, ms); }, shared: Route.SWITCH});
  function seen() { try { return root.localStorage.getItem(KEY) === '1'; } catch (e) { return false; } }
  function remember() { try { root.localStorage.setItem(KEY, '1'); } catch (e) { /* no storage */ } }
  function media(q) { try { return !!(root.matchMedia && root.matchMedia(q).matches); } catch (e) { return false; } }
  function saveData() { try { var c = root.navigator && root.navigator.connection; return !!(c && c.saveData === true); } catch (e) { return false; } }
  function soundState() { v.muted = !sound; sOn.hidden = sound; sOff.hidden = !sound; }

  function show(auto, from, atLoad) {
    guard.request(function () {
      if (open) return;
      open = true; opener = from || null; gen++;
      soundState(); play.hidden = true;
      v.setAttribute('poster', POSTER);
      try { dlg.showModal(); } catch (e) { open = false; return; }
      if (!auto) { play.hidden = false; play.focus(); return; }
      skip.focus();
      if (atLoad && !streamUp) { waiting = true; waitTimer = setTimeout(begin, WAIT_STREAM_MS); } else begin();
    });
  }
  function begin() {
    waiting = false; clearTimeout(waitTimer);
    if (!open) return;
    var g = gen, p;
    play.hidden = true;
    if (v.getAttribute('src') !== SRC) v.setAttribute('src', SRC);
    try { p = v.play(); } catch (e) { refused(g); return; }
    if (p && typeof p.then === 'function') p.then(null, function () { refused(g); });
  }
  function refused(g) {              // autoplay refused (low power, browser rule): the poster and « Play the intro », no retry
    if (!open || g !== gen) return;
    var f = doc.activeElement === skip;
    play.hidden = false;
    if (f) play.focus();
  }
  function hide(mark) { if (mark) remember(); guard.request(closeNow); }
  function closeNow() { if (!open) return; ended(); if (dlg.open) dlg.close(); }
  function ended() {                 // also after a close by the browser itself (a switch too: the guard counts it)
    open = false; gen++; waiting = false; clearTimeout(waitTimer); Route.SWITCH.last = Date.now();
    try { v.pause(); } catch (e) { /* nothing to pause */ }
    if (v.getAttribute('src') !== null) { v.removeAttribute('src'); try { v.load(); } catch (e) { /* stops the download */ } }
    var back = (opener && opener.focus) ? opener : btn;
    opener = null;
    back.focus();
  }
  function nav() {                   // a link to #intro followed on the page; the anchor gives way to the canonical one at once
    if (!isDeepLink(root.location.hash)) return;
    try { root.history.replaceState(root.history.state || null, '', Route.serialize({lang: doc.documentElement.lang === 'fr' ? 'fr' : 'en', tab: 'live', sub: null})); } catch (e) { /* kept */ }
    show(!media('(prefers-reduced-motion: reduce)'), null, false);
  }

  v.addEventListener('playing', remember);
  v.addEventListener('ended', function () { hide(false); });
  v.addEventListener('error', function () { if (open && v.getAttribute('src') !== null) hide(false); });
  dlg.addEventListener('cancel', function (e) { if (e && e.preventDefault) e.preventDefault(); hide(true); });      // Esc
  dlg.addEventListener('close', function () { if (open) { remember(); ended(); } });
  dlg.addEventListener('click', function (e) { if (e && (e.target === dlg || e.target === box)) hide(true); });     // outside the film
  skip.addEventListener('click', function () { hide(true); });
  play.addEventListener('click', begin);
  snd.addEventListener('click', function () { sound = !sound; soundState(); });
  btn.addEventListener('click', function () { show(true, btn, false); });
  root.addEventListener('hashchange', nav);
  btn.hidden = false;
  var r = Route.parse(root.location.hash, root.navigator ? root.navigator.language : '');
  var what = decide({supported: true, deep: isDeepLink(root.location.hash), seen: seen(), reduced: media('(prefers-reduced-motion: reduce)'),
                     saveData: saveData(), tab: r.tab, sub: r.sub});
  if (what !== 'none') show(what === 'play', null, true);
})(typeof self !== 'undefined' ? self : this);
