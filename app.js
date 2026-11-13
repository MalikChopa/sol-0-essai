/* Sol-0 live page v2: DOM glue (browser only). Reads assets.json, config.json and i18n.json (same origin), opens the stream, draws at
   most twice a second (one 640x360 rendering, copied to the whole console or to the panels, and to the enlarged panel), writes the
   status bar in the page language, routes the anchors (#<lang>/<tab>[/<part>]) without ever reloading. DESIGN.md (out/page-v2).
   The connection logic (stream, probe, offline, busy) is the rc13 one, unchanged. */
(function () {
  'use strict';
  var Live = self.Sol0Live, Con = self.Sol0Console, Route = self.Sol0Route, Lay = self.Sol0Layout;
  var doc = document, html = doc.documentElement, $ = function (id) { return doc.getElementById(id); };
  var route = Route.parse(location.hash, navigator.language || ''), lang = route.lang;
  var assets, cfg, TB = {en: {}, fr: {}}, ready = false;
  var S = Live.newView(), link = Live.makeLink(), es = null, buf = new Uint8Array(640 * 360), pal = null;
  var canvas = $('c'), ctx = canvas.getContext('2d'), img = ctx.createImageData(640, 360), hasImg = false;
  var lastLine = -Infinity, lastAria = -Infinity, openTimer = null, retryTimer = null, offlineShown = false;
  var lastWaitKey = null, lastDrawLabel = null, lastDrawLang = null, consoleDrawn = false, lastAnn = null, pendingDraw = false;
  var mode = null, modeAt = -Infinity, modeTimer = null, layoutQueued = false, ovId = null, opener = null, aboutY = 0, lastFs = -Infinity;
  var PCTX = {}, octx = null, dlg = $('ov'), hasDialog = false, limiter = null;
  var guard = Route.makeGuard(350, {now: now, setTimer: function (f, ms) { return setTimeout(f, ms); }});     // EF-87, every switch
  function now() { return Date.now(); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function tt(id, v) { return Live.tr({t: TB[lang]}, id, TB.en[id] !== undefined ? TB.en[id] : id, v); }
  function cls(el, c, on) { if (el && el.classList) { if (on) el.classList.add(c); else el.classList.remove(c); } }
  function attr(el, k, v) { if (el) { if (v === null) { if (el.removeAttribute) el.removeAttribute(k); } else el.setAttribute(k, v); } }
  function px(el, k, v) { if (el && el.style) el.style[k] = (typeof v === 'number') ? v + 'px' : v; }      // CSSOM only (CSP: no style attribute)
  function txtOpts() { return {t: TB[lang], en: TB.en, dec: lang === 'fr' ? ',' : '.', lang: lang, page: true, now: now()}; }
  function opts(lab) { var o = txtOpts(); o.scanlines = true; o.label = lab; return o; }

  // ---- drawing: one rendering, copied to every visible target ----
  function liveShown() { return route.tab === 'live' && !doc.hidden; }
  function draw() {
    if (offlineShown || !ready) return;
    if (!liveShown()) { pendingDraw = true; return; }
    pendingDraw = false;
    var lab = Live.label(link, S, now());
    if (!Live.canDraw(S)) {            // D3: the waiting card, redrawn only when what it says changes
      var key = waitCardKey(lab);
      lastDrawLabel = lab; lastDrawLang = lang;
      if (key === lastWaitKey) return;
      lastWaitKey = key; consoleDrawn = false;
      Live.renderWaiting(buf, S, opts(lab));
    } else {                           // RC12-verif I2: also a sol line without tick yet (bare view), never the previous sol's image
      lastWaitKey = null; consoleDrawn = true;
      Live.renderLive(buf, S, link, opts(lab));
      lastDrawLabel = lab; lastDrawLang = lang;
    }
    for (var i = 0; i < buf.length; i++) { var c = pal[buf[i]]; img.data[4 * i] = c[0]; img.data[4 * i + 1] = c[1]; img.data[4 * i + 2] = c[2]; img.data[4 * i + 3] = 255; }
    hasImg = true;
    blit();
    panelsState();
    if (route.tab === 'live' && route.sub && !ovId && panelActive(route.sub)) showPanel(route.sub);    // deep link once drawable
  }
  // what the waiting card says (VERIF-rc14 M4: the next sol's time only while it is ahead; the card is redrawn when it passes)
  function waitCardKey(lab) { return Live.waitKey(S, lab) + '|' + (Live.nextLeftS(S, now()) !== null ? S.nextUtc : '') + '|' + lang; }
  function cut(c2, id) { var p = Lay.PANELS[id]; c2.putImageData(img, -p[0], -p[1], p[0], p[1], p[2], p[3]); }
  function blit() {
    if (!hasImg) return;
    if (mode === 'panels') Lay.ORDER.forEach(function (id) { cut(PCTX[id], id); });
    else ctx.putImageData(img, 0, 0);
    if (ovId && octx) cut(octx, ovId);
  }
  // before a console is drawn (waiting card, bare view) only CAM-1 can be enlarged: the other frames are empty
  function panelActive(id) { return hasDialog && (id === 'cam' || (consoleDrawn && S.hasTick && !!S.camDims)); }
  function panelsState() {
    Lay.ORDER.forEach(function (id) {
      var on = panelActive(id);
      ['hit-', 'pb-'].forEach(function (p) { attr($(p + id), 'aria-disabled', on ? null : 'true'); });
    });
  }

  // ---- texts: badge, status bar, details, accessible summary ----
  function banner(lab) {
    var st = lab || Live.label(link, S, now()), el = $('state'), txt = tt('d.state.' + Live.stateKey(st));
    el.textContent = txt; el.dataset.state = st;
    if (txt !== lastAnn) { lastAnn = txt; $('stateann').textContent = txt; }       // announced once per change (UI-AUDIT M17)
    var sm = $('silentmsg'), t = now(), o = {t: TB[lang]};
    var msg = st === 'ENGINE SILENT' ? Live.silentText(S, t, lang, o) : (st === 'ENGINE HOLD' ? Live.holdText(S, t, lang, o)
      : (st === 'RESUMING' ? Live.resumeText(S, lang, o) : (st === 'SERVER BUSY' ? tt('d.busy.note') : null)));
    if (msg) { sm.textContent = msg; sm.hidden = false; } else sm.hidden = true;
  }
  function ageText(t) { return tt('d.age', {t: Live.fmtDuration(Live.dataAgeS(S, t))}); }
  function writeTexts(t) {
    var shown = Live.canDraw(S), o = txtOpts();
    if (shown && !offlineShown) {      // same rule as the canvas: the text never stays frozen on the previous sol
      $('line').textContent = Live.barLine(S, o);             // no tick yet: `--` for the tick values
      var ni = Live.noImageText(S, lang, o);
      $('age').textContent = ageText(t);                    // VERIF-rc14 I1: the age alone, never shortened by the bar
      $('noimg').textContent = ni ? '· ' + ni : '';
      $('stagebar').textContent = Live.stageBar(S, o);
      var sl = Live.seasonLine(S, o); $('season').textContent = sl ? sl : '';
    }
    var left = Live.nextLeftS(S, t);    // D3: shown even before anything can be drawn; null once `next` is past (never frozen at 0:00)
    $('next').textContent = left !== null ? tt('d.next', {t: S.nextUtc.slice(11, 19), m: Math.floor(left / 60), ss: pad(left % 60)}) : '';
    cls($('bar'), 'waitnext', left !== null);       // compact mode: the sol line gives its room to the next sol (live.css)
    if (ovId) $('ov-status').textContent = (shown && !offlineShown ? Live.barLine(S, o) : tt('d.state.' + Live.stateKey(Live.label(link, S, t)))) + ' · ' + ageText(t);
    if (t - lastAria >= 60000 && shown) { lastAria = t; $('summary').textContent = Live.summaryText(S, o, Live.fmtDuration(Live.dataAgeS(S, t)), assets.params); }
  }
  function textLines() {
    if (!ready) return;
    var t = now(), lab = Live.label(link, S, t);
    banner(lab);
    // the canvas follows the state too (header right text, REC, waiting card): a draw when the state or the language changed
    if (limiter && !offlineShown && (lab !== lastDrawLabel || lang !== lastDrawLang || (lastWaitKey !== null && !Live.canDraw(S) && waitCardKey(lab) !== lastWaitKey))) limiter.request();
    if (t - lastLine >= 900) { lastLine = t; writeTexts(t); }
  }

  // ---- stream (rc13) ----
  function onEvent(ev) {
    if (ev.e === 'hello' || ev.e === 'status') {
      Live.applyEvent(S, ev, now()); if (ev.e === 'hello') link.onHello(); banner();
      if (Live.canDraw(S)) limiter.request();       // RC12-verif I1: a status starts or ends RESUMING, the canvas says it too
      return;
    }
    Live.applyEvent(S, ev, now()); link.onEvent(S, ev);
    if (offlineShown) hideOffline();
    limiter.request();
  }
  function connect() {
    clearTimeout(retryTimer);
    if (es) { es.close(); es = null; }
    es = new EventSource(cfg.stream + '/stream');
    openTimer = setTimeout(function () { if (link.state === 'CONNECTING') fail(); }, Live.OPEN_TIMEOUT_MS);
    es.onopen = function () { clearTimeout(openTimer); link.onOk(); };
    ['hello', 'sol', 'poses', 'tick', 'learn', 'ff', 'attempt', 'phase', 'sol_end', 'published', 'status', 'restart'].forEach(function (n) {
      es.addEventListener(n, function (m) {
        var ev;
        try { ev = JSON.parse(m.data); } catch (e) { Live.countLine(S, now()); return; }   // unreadable: still one line of the snapshot count
        try { onEvent(ev); } catch (e) { /* ignore a malformed line */ }
      });
    });
    // the visitor's own stream broke: CONNECTING until the next hello (never ENGINE SILENT for a cut of the visitor's link)
    es.onerror = function () { es.close(); es = null; clearTimeout(openTimer); link.onLost(); banner(); probe(); };
  }
  function probe() {
    var ctl = new AbortController(), to = setTimeout(function () { ctl.abort(); }, 10000);
    fetch(cfg.stream + '/now.json', {cache: 'no-store', signal: ctl.signal}).then(function (r) {
      clearTimeout(to);
      link.onHttp(r.status);
      if (link.busy) { banner(); retryTimer = setTimeout(probe, Live.BUSY_POLL_MS); }
      else retryTimer = setTimeout(connect, 5000);
    }).catch(function () { clearTimeout(to); fail(); });
  }
  function fail() {
    link.onNetworkError(); banner();
    if (link.state === 'OFFLINE') { showOffline(); retryTimer = setTimeout(connect, Live.OFFLINE_RETRY_MS); }
    else retryTimer = setTimeout(connect, 5000);
  }
  // {t} is the time of the last successful publication (status.json det.last_success_utc), not the moment the server went offline
  function offlineNote(t, n) { return tt('d.off.note', {t: t, n: n}); }
  function offlineLines(off) { ['line', 'age', 'noimg', 'stagebar'].forEach(function (id) { $(id).hidden = off; }); }      // M13: not the live data
  function showOffline() {
    offlineShown = true; canvas.hidden = true; cls(html, 'offline', true); offlineLines(true); hidePanel();
    var g = $('off'); g.hidden = false; $('offimg').src = cfg.stateRaw + '/console.gif';
    var note = $('offnote');
    fetch(cfg.stateRaw + '/status.json', {cache: 'no-store'}).then(function (r) { return r.json(); }).then(function (j) {
      var n = (j.run && j.run.sol !== undefined) ? j.run.sol : (j.det && j.det.sol), u = (j.det && j.det.last_success_utc) || '';
      note.textContent = offlineNote(u.slice(11, 16) || '--:--', n === undefined ? '?' : n);
    }).catch(function () { note.textContent = offlineNote('--:--', '?'); });
  }
  function hideOffline() { offlineShown = false; canvas.hidden = false; cls(html, 'offline', false); offlineLines(false); $('off').hidden = true; }

  // ---- layout (DESIGN.md §3): sizes only, never a redraw ----
  function layout() {
    layoutQueued = false;
    var vw = self.innerWidth || 1280, vh = self.innerHeight || 800, dpr = self.devicePixelRatio || 1, t = now();
    var m = Lay.chooseMode(vw, vh);
    if (m !== mode) {
      if (mode !== null && t - modeAt < 500) {        // at most one mode change per 500 ms (EF-87), the latest state wins
        if (!modeTimer) modeTimer = setTimeout(function () { modeTimer = null; layout(); }, modeAt + 500 - t);
        return;
      }
      mode = m; modeAt = t; html.dataset.mode = m;
    }
    var compact = Lay.isCompact(mode, vh);
    cls(html, 'compact', compact);
    placeBars();
    if (mode === 'console') sizeConsole(vw, vh, dpr, compact); else sizePanels(vw, vh, dpr);
    if (ovId) sizeOverlay();
    blit();
  }
  function queueLayout() {
    if (layoutQueued) return;
    layoutQueued = true;
    if (typeof self.requestAnimationFrame === 'function') self.requestAnimationFrame(layout); else setTimeout(layout, 0);
  }
  // VERIF-rc14 I2: console mode has ONE status row: the stage and the next sol join #bar (live.css hides #bar2), so the console keeps its
  // size when the end-of-sol countdown appears; panels mode: they go back to the second row #bar2 (not sticky)
  function placeBars() {
    var into = $(mode === 'console' ? 'bar' : 'bar2');
    ['stagebar', 'next'].forEach(function (id) { var e = $(id); if (e && into && into.appendChild && e.parentNode !== into) into.appendChild(e); });
  }
  function sizeConsole(vw, vh, dpr, compact) {
    var st = $('stage'), box = Lay.consoleBox(vw, vh), w = st.clientWidth;
    if (w > 0 && st.getBoundingClientRect) {         // measured: the stage's width and top; « Details » under the fold in compact mode
      var sum = $('details');
      box = Lay.stageBox(vh, compact, w, st.getBoundingClientRect().top + (self.scrollY || 0), sum ? sum.offsetHeight : 0);
    }
    px(st, 'height', box.h);
    var f = Lay.fit(640, 360, box.w, box.h, dpr), c = $('console');
    px(c, 'width', f.cssW); px(c, 'height', f.cssH);
    px(c, 'left', f.floor ? 0 : Lay.snap(Math.max(0, (box.w - f.cssW) / 2), dpr)); px(c, 'top', f.floor ? 0 : Lay.snap(Math.max(0, (box.h - f.cssH) / 2), dpr));
    cls(st, 'wide', f.floor);
  }
  function sizePanels(vw, vh, dpr) {
    var st = $('stage'), sw = st.clientWidth > 0 ? st.clientWidth : vw - 2 * Lay.CHROME.margin, pp = Lay.panelsPlan(sw, vh, dpr);
    px(st, 'height', ''); cls(st, 'wide', false);
    Lay.ORDER.forEach(function (id) { var p = pp.panels[id], c = $('pc-' + id); px(c, 'width', p.cssW); px(c, 'height', p.cssH); });
    var g = pp.groups[2];
    cls($('g-maptel'), 'split', g.split); px($('g-maptel'), 'gap', g.split ? '' : g.gap);
  }
  function sizeOverlay() {
    var f = Lay.overlayFit(ovId, self.innerWidth || 1280, self.innerHeight || 800, self.devicePixelRatio || 1), oc = $('ov-c');
    px(oc, 'width', f.cssW); px(oc, 'height', f.cssH);
    $('ov-hint').hidden = !f.rotate;
  }

  // ---- the enlarged panel (DESIGN.md §4): a <dialog>, the same pixels at a larger scale, live ----
  function showPanel(id) {
    var p = Lay.PANELS[id], oc = $('ov-c'), first = !ovId;
    if (ovId !== id) { oc.width = p[2]; oc.height = p[3]; }
    ovId = id;
    $('ov-title').textContent = tt('n.panel.' + id);
    sizeOverlay();
    if (hasImg) cut(octx, id);                    // the picture is there BEFORE the dialog shows: never a black frame first
    links(); writeTexts(now());
    if (first && !dlg.open) { if (!opener) opener = $((mode === 'panels' ? 'pb-' : 'hit-') + id); dlg.showModal(); }
  }
  function hidePanel() {
    if (!ovId) return;
    var id = ovId;
    ovId = null;
    if (dlg.open) dlg.close();
    var back = (opener && opener.focus) ? opener : $((mode === 'panels' ? 'pb-' : 'hit-') + id);
    opener = null;
    if (back && back.focus) back.focus();
  }
  function openReq(id, btn) {
    if (!panelActive(id)) return;
    if (!ovId) opener = btn;
    var inOv = !!(self.history && history.state && history.state.ov === true);
    go({lang: lang, tab: 'live', sub: id}, inOv ? 'replace' : 'push', {ov: true});
  }
  function closeReq() {
    if (self.history && history.state && history.state.ov === true) history.back();      // the guarded popstate closes it
    else go({lang: lang, tab: 'live', sub: null}, 'replace', null);
  }
  function stepReq(d) {
    if (!ovId) return;
    var o = Lay.ORDER, i = o.indexOf(ovId), k, id = ovId;
    for (k = 1; k <= o.length; k++) { id = o[(i + d * k + 5 * o.length) % o.length]; if (panelActive(id)) break; }
    go({lang: lang, tab: 'live', sub: id}, 'replace', (self.history && history.state) || null);
  }

  // ---- anchors, tabs, language (DESIGN.md §6): no reload, every switch through the guard ----
  function go(r, how, state) {
    guard.request(function () {
      var h = Route.serialize(r);
      if (self.history && history.pushState) {
        if (how === 'push') history.pushState(state || null, '', h);
        else history.replaceState(state === undefined ? (history.state || null) : state, '', h);
      }
      apply(r, true);
    });
  }
  function onNav() { guard.request(function () { apply(Route.parse(location.hash, navigator.language || ''), true); }); }
  function setLang(l) {
    lang = l; html.lang = l;
    texts();
    lastAria = -Infinity;
    if (ready) { banner(); writeTexts(now()); if (limiter) limiter.request(); }
  }
  function texts() {
    attr(canvas, 'aria-label', tt('d.canvas')); attr($('offimg'), 'alt', tt('d.offimg')); attr($('tabs'), 'aria-label', tt('n.nav'));
    Lay.ORDER.forEach(function (id) {
      var n = tt('n.enlarge', {panel: tt('n.panel.' + id)});
      ['hit-', 'pb-'].forEach(function (p) { attr($(p + id), 'aria-label', n); attr($(p + id), 'title', n); });
    });
    attr($('ov-prev'), 'aria-label', tt('n.prev')); attr($('ov-prev'), 'title', tt('n.prev'));
    attr($('ov-next'), 'aria-label', tt('n.next')); attr($('ov-next'), 'title', tt('n.next'));
    attr($('langlink'), 'hreflang', lang === 'fr' ? 'en' : 'fr');
    fsLabel();
    if (ovId) $('ov-title').textContent = tt('n.panel.' + ovId);
    doc.title = route.tab === 'about' ? tt('n.tab.about') + ' · Sol-0' : tt('d.title');
  }
  function links() {
    var other = lang === 'fr' ? 'en' : 'fr';
    attr($('tab-live'), 'href', '#' + lang + '/live'); attr($('tab-about'), 'href', '#' + lang + '/about');
    attr($('tab-live'), 'aria-current', route.tab === 'live' ? 'page' : null); attr($('tab-about'), 'aria-current', route.tab === 'about' ? 'page' : null);
    attr($('skip'), 'href', '#' + lang + '/live'); attr($('toabout'), 'href', '#' + lang + '/about');
    attr($('langlink'), 'href', Route.serialize({lang: other, tab: route.tab, sub: route.sub}));
    if (ovId) {
      var h = tt('n.help', {panel: tt('n.panel.' + ovId)});
      attr($('ov-help'), 'href', '#' + lang + '/about/' + Route.HELP[ovId]); attr($('ov-help'), 'aria-label', h); attr($('ov-help'), 'title', h);
    }
  }
  function sectionInView(l) {      // the last section of the explainer whose title is above the top of the window
    var best = null;
    Route.SECTIONS.forEach(function (s) { var e = $(l + '-' + s); if (e && e.getBoundingClientRect && e.getBoundingClientRect().top <= 90) best = s; });
    return best;
  }
  function toSection(l, s) {
    var e = $(l + '-' + s);
    if (!e) return;
    if (e.scrollIntoView) e.scrollIntoView();
    if (e.focus) { try { e.focus({preventScroll: true}); } catch (x) { e.focus(); } }
  }
  function apply(r, user) {
    var prev = route, keep = (prev.tab === 'about' && r.tab === 'about' && prev.lang !== r.lang && !r.sub) ? sectionInView(prev.lang) : null;
    if (prev.tab === 'about' && r.tab !== 'about') aboutY = self.scrollY || 0;
    route = r;
    if (r.lang !== lang) setLang(r.lang);
    html.dataset.tab = r.tab;
    texts(); links();
    if (r.tab === 'live') {
      if (r.sub && panelActive(r.sub) && hasImg) showPanel(r.sub);
      else hidePanel();
      if (prev.tab !== 'live') { queueLayout(); if (limiter) limiter.request(); if (user) { var hl = $('h-live'); if (hl && hl.focus) hl.focus(); } }
    } else {
      hidePanel();
      if (r.sub) toSection(r.lang, r.sub);
      else if (keep) toSection(r.lang, keep);
      else if (prev.tab !== 'about' && self.scrollTo) self.scrollTo(0, aboutY);
      if (prev.tab !== 'about' && user && !r.sub) { var ha = $('h-about'); if (ha && ha.focus) { try { ha.focus({preventScroll: true}); } catch (x) { ha.focus(); } } }
    }
  }
  function fsLabel() { var b = $('fs'); if (b && ready) b.textContent = tt(doc.fullscreenElement ? 'n.fullscreen.exit' : 'n.fullscreen'); }

  function wire() {
    Lay.ORDER.forEach(function (id) {
      ['hit-', 'pb-'].forEach(function (p) { var b = $(p + id); b.addEventListener('click', function () { openReq(id, b); }); });
    });
    if (hasDialog) {
      dlg.addEventListener('cancel', function (e) { if (e && e.preventDefault) e.preventDefault(); closeReq(); });     // Esc
      dlg.addEventListener('close', function () {      // closed by the browser itself (VERIF-rc14 M2: never reopened by a draw meanwhile)
        if (ovId) { ovId = null; route = {lang: route.lang, tab: route.tab, sub: null}; go({lang: lang, tab: 'live', sub: null}, 'replace', null); }
      });
      dlg.addEventListener('click', function (e) { if (e && (e.target === dlg || e.target === $('ov-body'))) closeReq(); });
      dlg.addEventListener('keydown', function (e) {
        if (!e) return;
        if (e.key === 'ArrowLeft') { e.preventDefault(); stepReq(-1); } else if (e.key === 'ArrowRight') { e.preventDefault(); stepReq(1); }
      });
      $('ov-close').addEventListener('click', closeReq);
      $('ov-prev').addEventListener('click', function () { stepReq(-1); });
      $('ov-next').addEventListener('click', function () { stepReq(1); });
    }
    $('langlink').addEventListener('click', function (e) {
      if (e && e.preventDefault) e.preventDefault();
      go({lang: lang === 'fr' ? 'en' : 'fr', tab: route.tab, sub: route.sub}, 'replace');
    });
    $('skip').addEventListener('click', function (e) {
      if (e && e.preventDefault) e.preventDefault();
      go({lang: lang, tab: 'live', sub: null}, 'replace');
      var st = $('stage'); if (st && st.focus) st.focus();
    });
    if (self.addEventListener) {
      self.addEventListener('hashchange', onNav); self.addEventListener('popstate', onNav);
      self.addEventListener('resize', queueLayout); self.addEventListener('orientationchange', queueLayout);
    }
    if (self.visualViewport && self.visualViewport.addEventListener) self.visualViewport.addEventListener('resize', queueLayout);
    if (typeof self.ResizeObserver === 'function') {      // the header, the bars and the engine message move the stage's top
      try { var ro = new self.ResizeObserver(function () { queueLayout(); }); ['top', 'bar', 'bar2', 'silentmsg'].forEach(function (id) { ro.observe($(id)); }); } catch (x) { /* no observer */ }
    }
    if (doc.addEventListener) {
      doc.addEventListener('visibilitychange', function () { if (!doc.hidden && pendingDraw && limiter) limiter.request(); });
      doc.addEventListener('fullscreenchange', function () { fsLabel(); queueLayout(); });
    }
    var fs = $('fs');
    if (doc.fullscreenEnabled && html.requestFullscreen) {
      fs.hidden = false;
      fs.addEventListener('click', function () {        // a user gesture each time; at most one switch per 350 ms (EF-87)
        var t = now();
        if (t - lastFs < 350) return;
        lastFs = t;
        if (doc.fullscreenElement) doc.exitFullscreen(); else html.requestFullscreen();
      });
    }
  }

  Promise.all([fetch('assets.json').then(function (r) { return r.json(); }), fetch('config.json').then(function (r) { return r.json(); }),
               fetch('i18n.json').then(function (r) { return r.json(); })]).then(function (a) {
    assets = a[0]; cfg = a[1];
    var tb = a[2].strings;
    Object.keys(tb).forEach(function (k) { TB.en[k] = tb[k].en; TB.fr[k] = tb[k].fr; });
    Con.init(assets); Live.setConsole(Con);
    pal = assets.palette.map(function (h) { return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)]; });
    Lay.ORDER.forEach(function (id) { PCTX[id] = $('pc-' + id).getContext('2d'); });
    octx = $('ov-c').getContext('2d');
    hasDialog = !!(dlg && typeof dlg.showModal === 'function');
    cls(html, 'nodialog', !hasDialog);
    ready = true;
    html.lang = lang;
    wire();
    limiter = Live.makeLimiter({now: now, draw: draw, setTimer: function (f, ms) { return setTimeout(f, ms); },
                                minMs: (self.matchMedia && self.matchMedia('(prefers-reduced-motion: reduce)').matches) ? 1000 : Live.MIN_DRAW_MS});
    layout();
    var canon = Route.serialize(route);       // canonical anchor (#fr -> #fr/live), no new history entry
    if (location.hash !== canon && self.history && history.replaceState) history.replaceState(history.state || null, '', canon);
    apply(route, false);
    draw();                                    // the waiting card at once (never a black canvas)
    banner(); writeTexts(now());
    setInterval(textLines, 1000);
    connect();
  }).catch(function () {
    var el = $('state');
    el.textContent = TB[lang]['d.error'] || (lang === 'fr' ? "Erreur : la page n'a pas pu charger ses fichiers." : 'Error: the page could not load its files.');
  });
})();
