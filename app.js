/* Sol-0 live page v2: DOM glue (browser only). Reads assets.json, config.json and i18n.json (same origin), opens the stream, draws at
   most twice a second (one 640x360 rendering, copied to the whole console or to the panels, and to the enlarged panel), writes the
   status bar in the page language, routes the anchors (#<lang>/<tab>[/<part>]) without ever reloading. DESIGN.md (out/page-v2).
   Consigne 53: minimal status bar, explorable map tab, CAM-1's size.
   The connection logic (stream, probe, offline, busy) is the rc13 one, unchanged. */
(function () {
  'use strict';
  var Live = self.Sol0Live, Con = self.Sol0Console, Route = self.Sol0Route, Lay = self.Sol0Layout, MV = self.Sol0Map;
  var doc = document, html = doc.documentElement, $ = function (id) { return doc.getElementById(id); };
  var route = Route.parse(location.hash, navigator.language || ''), lang = route.lang;
  var assets, cfg, birth = null, TB = {en: {}, fr: {}}, ready = false;
  var S = Live.newView(), link = Live.makeLink(), es = null, buf = new Uint8Array(640 * 360), pal = null;
  var canvas = $('c'), ctx = canvas.getContext('2d'), img = ctx.createImageData(640, 360), hasImg = false;
  var lastLine = -Infinity, lastAria = -Infinity, openTimer = null, retryTimer = null, offlineShown = false;
  var lastWaitKey = null, lastDrawLabel = null, lastDrawLang = null, consoleDrawn = false, lastAnn = null, pendingDraw = false;
  var mode = null, modeAt = -Infinity, modeTimer = null, layoutQueued = false, ovId = null, opener = null, aboutY = 0, lastFs = -Infinity;
  var PCTX = {}, octx = null, dlg = $('ov'), hasDialog = false, limiter = null, V3 = null;
  var reduced = !!(self.matchMedia && self.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var guard = Route.makeGuard(350, {now: now, setTimer: function (f, ms) { return setTimeout(f, ms); }, shared: Route.SWITCH});     // EF-87, every switch (intro.js included)
  function now() { return Date.now(); }
  // the intro cinematic (intro.js) lies above the page: a deep-linked panel waits until it is closed (never two dialogs at once)
  function introOpen() { try { return !!(self.Sol0Intro && self.Sol0Intro.isOpen()); } catch (e) { return false; } }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function tt(id, v) { return Live.tr({t: TB[lang]}, id, TB.en[id] !== undefined ? TB.en[id] : id, v); }
  function cls(el, c, on) { if (el && el.classList) { if (on) el.classList.add(c); else el.classList.remove(c); } }
  function attr(el, k, v) { if (el) { if (v === null) { if (el.removeAttribute) el.removeAttribute(k); } else el.setAttribute(k, v); } }
  function px(el, k, v) { if (el && el.style) el.style[k] = (typeof v === 'number') ? v + 'px' : v; }      // CSSOM only (CSP: no style attribute)
  function txtOpts() { return {t: TB[lang], en: TB.en, dec: lang === 'fr' ? ',' : '.', lang: lang, page: true, now: now()}; }
  function opts(lab) { var o = txtOpts(); o.scanlines = true; o.label = lab; return o; }

  // ---- drawing: one rendering, copied to every visible target ----
  function liveShown() { return route.tab === 'live' && !doc.hidden; }
  // SEC-14: a state made incoherent by a malformed stream line never stops the next draws or the texts (errors are dropped; the
  // drawing itself is bounded: console.js line() and text(), live.js checks what a line may change)
  function draw() { try { drawNow(); } catch (e) { /* the next draw starts again from the state */ } }
  function drawNow() {
    if (offlineShown || !ready) return;
    if (route.tab === 'map' && !doc.hidden) mapTrail();
    if (route.tab === '3d' && !doc.hidden && v3()) V3.draw(S);
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
    if (route.tab === 'live' && route.sub && !ovId && panelActive(route.sub) && !introOpen()) showPanel(route.sub);    // deep link once drawable
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
      var on = id === 'map' || panelActive(id);        // the map panel opens the map tab, always
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
  function ageText(t, id) { return tt(id || 'd.age', {t: Live.fmtDuration(Live.dataAgeS(S, t))}); }
  function writeTexts(t) { try { writeTextsNow(t); } catch (e) { /* SEC-14: the next second writes them again */ } }
  function writeTextsNow(t) {
    var shown = Live.canDraw(S), o = txtOpts();
    if (shown && !offlineShown) {      // same rule as the canvas: the text never stays frozen on the previous sol
      $('line').textContent = Live.barLine(S, o);             // no tick yet: `--` for the tick values
      $('solst').textContent = Live.solStage(S, o);
      var ni = Live.noImageText(S, lang, o), cn = Live.camNote(S, o, assets.params.acuity);
      ['camnote', 'camnote2', 'camdet'].forEach(function (id) { $(id).textContent = cn; });
      $('age').textContent = ageText(t, 'd.age.bar');       // VERIF-rc14 I1: the age alone, never shortened by the bar
      $('noimg').textContent = ni ? '· ' + ni : '';
      $('stagebar').textContent = Live.stageBar(S, o);
      var sl = Live.seasonLine(S, o); $('season').textContent = sl ? sl : '';
      $('alive').textContent = birth === null ? '' : Live.aliveText(birth, t + (S.serverOffsetMs || 0), S.sol, lang, o);   // the build's birth fact, the stream's sol
    }
    var left = Live.nextLeftS(S, t);    // D3: shown even before anything can be drawn; null once `next` is past (never frozen at 0:00)
    $('next').textContent = left !== null ? tt('d.next', {t: Live.timeBoth(Date.parse(S.nextUtc), true, txtOpts()), m: Math.floor(left / 60), ss: pad(left % 60)}) : '';
    if (ovId) $('ov-status').textContent = (shown && !offlineShown ? Live.barLine(S, o) : tt('d.state.' + Live.stateKey(Live.label(link, S, t)))) + ' · ' + ageText(t);
    if (t - lastAria >= 60000 && shown) { lastAria = t; $('summary').textContent = Live.summaryText(S, o, Live.fmtDuration(Live.dataAgeS(S, t)), assets.params); }
  }
  function textLines() {
    if (!ready) return;
    var t = now(), lab = Live.label(link, S, t);
    try { banner(lab); } catch (e) { /* SEC-14 */ }
    // the canvas follows the state too (header right text, REC, waiting card): a draw when the state or the language changed
    if (limiter && !offlineShown && (lab !== lastDrawLabel || lang !== lastDrawLang || (lastWaitKey !== null && !Live.canDraw(S) && waitCardKey(lab) !== lastWaitKey))) limiter.request();
    if (t - lastLine >= 900) {
      lastLine = t; writeTexts(t);
      if (route.tab === 'map' && !doc.hidden) { if (mapDue(t)) mapLoad(); else mapTexts(); }
      if (V3 && route.tab === '3d') V3.texts();
    }
  }

  // ---- stream (rc13) ----
  function onEvent(ev) {
    if (ev.e === 'hello' || ev.e === 'status') {
      Live.applyEvent(S, ev, now()); if (ev.e === 'hello') link.onHello(); banner();
      if (Live.canDraw(S)) limiter.request();       // RC12-verif I1: a status starts or ends RESUMING, the canvas says it too
      return;
    }
    Live.applyEvent(S, ev, now()); link.onEvent(S, ev);
    if (V3) V3.update(S);
    if (ev.e === 'published') mapPublished();
    if (offlineShown) hideOffline();
    limiter.request();
  }
  function connect() {
    clearTimeout(retryTimer);
    if (es) { es.close(); es = null; }
    es = new EventSource(cfg.stream + '/stream');
    openTimer = setTimeout(function () { if (link.state === 'CONNECTING') fail(); }, Live.OPEN_TIMEOUT_MS);
    es.onopen = function () { clearTimeout(openTimer); link.onOk(); };
    ['hello', 'sol', 'poses', 'tick', 'lmh', 'snh', 'learn', 'ff', 'attempt', 'phase', 'sol_end', 'published', 'status', 'restart'].forEach(function (n) {
      es.addEventListener(n, function (m) {
        var ev;
        try { ev = JSON.parse(m.data); } catch (e) { Live.countLine(S, now()); return; }   // unreadable: still one line of the snapshot count
        try { onEvent(ev); } catch (e) { /* ignore a malformed line */ }
      });
    });
    // the visitor's own stream broke: CONNECTING until the next hello (never ENGINE SILENT for a cut of the visitor's link)
    es.onerror = function () { es.close(); es = null; clearTimeout(openTimer); link.onStreamError(); link.onLost(); banner(); probe(); };
  }
  // SEC-04: /now.json says `streams_full: true` (web.py) when every stream place is taken; a body that is not a small JSON object
  // says nothing (false)
  function streamsFull(t) {
    if (typeof t !== 'string' || t.length > 262144) return false;
    try { var j = JSON.parse(t); return !!j && typeof j === 'object' && j.streams_full === true; } catch (e) { return false; }
  }
  function probe() {
    var ctl = new AbortController(), to = setTimeout(function () { ctl.abort(); }, 10000);
    function done(status, full) {
      clearTimeout(to);
      link.onHttp(status, full);
      // busy: the server said it (503, 429, streams_full) -> ask /now.json again in 9 s; repeated failures -> try the stream in 9 s
      if (link.busy) { banner(); retryTimer = setTimeout(link.hard ? probe : connect, Live.BUSY_POLL_MS); }
      else retryTimer = setTimeout(connect, 5000);
    }
    fetch(cfg.stream + '/now.json', {cache: 'no-store', signal: ctl.signal}).then(function (r) {
      if (!(r.status >= 200 && r.status < 300) || typeof r.text !== 'function') { done(r.status, false); return; }
      r.text().then(function (t) { done(r.status, streamsFull(t)); }, function () { done(r.status, false); });
    }).catch(function () { clearTimeout(to); fail(); });
  }
  function fail() {
    link.onNetworkError(); banner();
    if (link.state === 'OFFLINE') { showOffline(); retryTimer = setTimeout(connect, Live.OFFLINE_RETRY_MS); }
    else retryTimer = setTimeout(connect, 5000);
  }
  // {t} is the time of the last successful publication (status.json det.last_success_utc), not the moment the server went offline
  function offlineNote(t, n) { return tt('d.off.note', {t: t, n: n}); }
  function offlineLines(off) { ['line', 'solst', 'age', 'noimg', 'stagebar', 'alive', 'camdet'].forEach(function (id) { $(id).hidden = off; }); }      // M13: not the live data
  // SEC-15 (FRONT-03): what the offline mode reads from the `state` branch is checked. Only the configured branch (config.json, built
  // from --repo) is read; status.json is a small JSON object whose sol is a whole number and whose time is an ISO UTC date; the
  // published console.gif is shown as a STILL (its first frame, drawn once on a canvas): the animation plays only after a click on
  // « Play the animation » (EF-87: never an animated image without a choice of the visitor, at most one switch per 350 ms).
  var STATE_RE = /^https:\/\/raw\.githubusercontent\.com\/[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}\/state$/;
  var UTC_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/, GIF_MAX = 2 * 1024 * 1024, STATUS_MAX = 65536, offAnim = false, offGen = 0;
  function stateUrl(f) { return (cfg && typeof cfg.stateRaw === 'string' && STATE_RE.test(cfg.stateRaw)) ? cfg.stateRaw + '/' + f : null; }
  function statusFacts(t) {
    var j = null, out = {n: '?', u: ''};
    if (typeof t !== 'string' || t.length > STATUS_MAX) return out;
    try { j = JSON.parse(t); } catch (e) { return out; }
    if (!j || typeof j !== 'object') return out;
    var run = (j.run && typeof j.run === 'object') ? j.run : {}, det = (j.det && typeof j.det === 'object') ? j.det : {};
    var n = run.sol !== undefined ? run.sol : det.sol;
    if (typeof n === 'number' && isFinite(n) && Math.floor(n) === n && n >= 0) out.n = n;
    if (typeof det.last_success_utc === 'string' && UTC_RE.test(det.last_success_utc)) out.u = det.last_success_utc;
    return out;
  }
  function isGif(buf) {
    if (!buf || typeof buf.byteLength !== 'number' || buf.byteLength < 13 || buf.byteLength > GIF_MAX) return false;
    var b = new Uint8Array(buf, 0, 6), sig = String.fromCharCode(b[0], b[1], b[2], b[3], b[4], b[5]);
    return sig === 'GIF87a' || sig === 'GIF89a';
  }
  function offStill(gen) {
    var url = stateUrl('console.gif');
    if (!url || typeof self.createImageBitmap !== 'function' || typeof self.Blob !== 'function') return;
    fetch(url, {cache: 'no-store'}).then(function (r) {
      if (!r.ok || typeof r.arrayBuffer !== 'function') return null;
      return r.arrayBuffer();
    }).then(function (buf) {
      if (!isGif(buf)) return null;
      return self.createImageBitmap(new self.Blob([buf], {type: 'image/gif'}));      // the first frame (the default image of a GIF)
    }).then(function (bm) {
      if (!bm) return;
      var ok = bm.width > 0 && bm.height > 0 && bm.width <= 2048 && bm.height <= 2048;
      if (ok && offlineShown && gen === offGen) {
        var c = $('offc'), x = c.getContext('2d');
        c.width = bm.width; c.height = bm.height; x.imageSmoothingEnabled = false; x.drawImage(bm, 0, 0);
        c.hidden = false; $('offplay').hidden = false; offPlayLabel();
      }
      if (bm.close) bm.close();
    }).catch(function () { /* no still: the note says the server is offline */ });
  }
  function offPlayLabel() { var b = $('offplay'); if (b) b.textContent = tt(offAnim ? 'n.offstop' : 'n.offplay'); }
  function offShowAnim(on) {
    var im = $('offimg'), url = stateUrl('console.gif');
    offAnim = !!(on && url && offlineShown);
    if (offAnim) im.src = url; else attr(im, 'src', null);
    im.hidden = !offAnim; $('offc').hidden = offAnim;
    offPlayLabel();
  }
  function showOffline() {
    offlineShown = true; canvas.hidden = true; cls(html, 'offline', true); offlineLines(true); hidePanel();
    var g = $('off'), gen = ++offGen; g.hidden = false;
    offAnim = false; $('offimg').hidden = true; attr($('offimg'), 'src', null); $('offc').hidden = true; $('offplay').hidden = true;
    var note = $('offnote'), url = stateUrl('status.json');
    function say(f) { note.textContent = offlineNote(Live.timeBoth(Date.parse(f.u), false, txtOpts()) || tt('d.t.none'), f.n); }
    offStill(gen);
    if (!url) { say(statusFacts(null)); return; }
    fetch(url, {cache: 'no-store'}).then(function (r) { return (r.ok && typeof r.text === 'function') ? r.text() : null; })
      .then(function (t) { say(statusFacts(t)); }).catch(function () { say(statusFacts(null)); });
  }
  function hideOffline() {
    offlineShown = false; canvas.hidden = false; cls(html, 'offline', false); offlineLines(false); $('off').hidden = true;
    offAnim = false; attr($('offimg'), 'src', null); $('offimg').hidden = true; $('offc').hidden = true; $('offplay').hidden = true;
  }

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
    if (mode === 'console') sizeConsole(vw, vh, dpr, compact); else sizePanels(vw, vh, dpr);
    if (ovId) sizeOverlay();
    if (MP.v && route.tab === 'map') mapFit(false);
    blit();
  }
  function queueLayout() {
    if (layoutQueued) return;
    layoutQueued = true;
    if (typeof self.requestAnimationFrame === 'function') self.requestAnimationFrame(layout); else setTimeout(layout, 0);
  }
  function sizeConsole(vw, vh, dpr, compact) {
    var st = $('stage'), box = Lay.consoleBox(vw, vh), w = st.clientWidth;
    if (w > 0 && st.getBoundingClientRect) {         // measured: the stage's width and top
      var sum = $('camnote');
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

  // ---- the map tab (consigne 53; LIVE.md). Live track only over an image map.json proves: same SHA-256, or else the whole detailed
  // map at its size. raw.githubusercontent.com keeps a file 5 min: an image read < 6 min after its map.json was first seen is read again.
  var MAP_MAX = 4 * 1024 * 1024, MAP_EVERY = 600000, MAP_CDN = 360000;
  var MP = {gen: 0, at: -Infinity, due: 0, err: false, meta: null, jt: null, jtAt: 0, imgAt: 0, h: null, sure: false, full: false,
            whole: false, tf: null, mis: false, sol: null, utc: null, iw: 0, ih: 0, v: null, out: false, ptr: {}, pinch: null, zAt: -Infinity, acc: 0};
  function getMap(f, bin) {
    var url = stateUrl(f);
    return url ? fetch(url, {cache: 'no-store'}).then(function (r) { return r.ok ? (bin ? r.arrayBuffer() : r.text()) : null; })
      .catch(function () { return null; }) : Promise.resolve(null);
  }
  function getPng(f) {          // {bm, h}: bitmap, SHA-256 (null without crypto.subtle: http)
    return getMap(f, true).then(function (b) {
      var c = self.crypto && self.crypto.subtle;
      if (!MV.isPng(b, MAP_MAX) || typeof self.createImageBitmap !== 'function') return null;
      return self.createImageBitmap(new self.Blob([b], {type: 'image/png'})).then(function (bm) {
        function r(d) { return {bm: bm, h: MV.hex(d)}; }
        if (bm.width <= 4096 && bm.height <= 4096) return c ? c.digest('SHA-256', b).then(r, r) : r(null);
        if (bm.close) bm.close();
        return null;
      }, function () { return null; });
    });
  }
  function mapDue(t) { return MP.iw ? (MP.due ? t >= MP.due : t - MP.at >= MAP_EVERY) : t - MP.at >= 60000; }      // no map yet: once a minute
  function mapLoad() {
    var gen = ++MP.gen, meta = null, jt = null, facts = null, full = false;
    MP.at = now(); if (MP.at >= MP.due) MP.due = 0;
    getMap('map.json', false).then(function (j) {
      jt = typeof j === 'string' ? j : null; meta = MV.parseMeta(jt);
      return getMap('status.json', false);
    }).then(function (st) {
      facts = statusFacts(st); full = !!(meta && meta.full) && !(MP.whole && meta.full.cropped);
      if (MP.iw && MP.sure && jt !== null && jt === MP.jt && full === MP.full) return 0;        // same map, image checked: not read again
      return getPng(full ? 'map-full.png' : 'map.png').then(function (r) { if (r || !full) return r; full = false; return getPng('map.png'); });
    }).then(function (r) {
      if (gen === MP.gen) mapSet(meta, jt, facts, r, full); else if (r && r.bm.close) r.bm.close();
    }).catch(function () { if (gen === MP.gen) { MP.err = !MP.iw; mapTexts(); } });
  }
  function mapSet(m, jt, f, r, full) {
    var t = now(), bm = r && r.bm, tf, h;
    if (bm) {
      var c = $('mapimg'), tc = $('maptrail'), x = c.getContext('2d');
      if (bm.width !== MP.iw || bm.height !== MP.ih) MP.v = null;
      c.width = tc.width = bm.width; c.height = tc.height = bm.height;
      x.imageSmoothingEnabled = false; x.drawImage(bm, 0, 0);
      if (bm.close) bm.close();
      if (jt !== MP.jt) MP.jtAt = t;
      MP.iw = c.width; MP.ih = c.height; MP.full = full; MP.jt = jt; MP.h = r.h; MP.imgAt = t;
    } else if (r !== 0) { MP.err = !MP.iw; mapTexts(); return; }        // nothing read: the last map stays
    tf = m ? (MP.full ? m.full : m.ov) : null; h = tf && tf.sha;
    MP.err = false; MP.meta = m;
    if (h && MP.h) { MP.mis = h !== MP.h; MP.sure = !MP.mis; MP.tf = MP.sure ? tf : null; }
    else {
      MP.mis = !!tf && MP.full && (tf.w !== MP.iw || tf.h !== MP.ih);
      MP.tf = tf && MP.full && !tf.cropped && !MP.mis ? tf : null;
      MP.sure = !MP.mis && MP.imgAt - MP.jtAt >= MAP_CDN;
      if (!MP.sure) MP.due = MP.jtAt + MAP_CDN;
    }
    if (MP.mis) MP.due = t + MAP_CDN;                 // two publications (CDN): read again in 6 min
    MP.sol = m ? m.sol : (typeof f.n === 'number' ? f.n : null);
    MP.utc = (f.u && MP.sol !== null && f.n === MP.sol) ? Date.parse(f.u) : null;    // only the same sol's status.json
    if (route.tab === 'map') mapFit(!MP.v);
    mapTrail(); mapTexts();
  }
  function mapPublished() { MP.due = now() + MAP_CDN; }
  function mapShow() {
    if (mapDue(now())) mapLoad(); else mapFit(!MP.v);
    mapTrail(); mapTexts();
  }
  function agoText(sec) { return sec < 60 ? Live.fmtDuration(sec) : Live.aliveDuration(sec, {t: TB[lang]}); }
  function km(n, cm) { var v = String(Math.round(n * cm / 100) / 10); return lang === 'fr' ? v.replace('.', ',') : v; }
  function mapTexts() {
    var lab, note = '', m = MP.meta, f = m && MP.full ? m.full : null, age = MP.utc !== null ? (now() + (S.serverOffsetMs || 0) - MP.utc) / 1000 : null;
    if (!MP.iw) lab = tt(MP.err ? 'd.map.error' : 'd.map.loading');
    else {
      lab = MP.sol === null ? tt('d.map.label.nosol') : (age !== null && age >= 0 ? tt('d.map.label', {n: MP.sol, t: agoText(age)}) : tt('d.map.label.noage', {n: MP.sol}));
      if (!m) note = tt('d.map.nometa');
      else if (MP.mis) note = tt('d.map.mismatch');
      else if (!MP.tf) note = tt('d.map.unchecked');
      else note = (S.path.length && typeof S.sol === 'number') ? tt('d.map.track', {s: S.sol, n: S.path.length}) + (MP.out ? ' ' + tt('d.map.out') : '') : tt('d.map.notrack');
      if (f && f.cropped) note += ' ' + tt('d.map.cropped', {w: f.cells[0], h: f.cells[1], kw: km(f.cells[0], m.cell_m), kh: km(f.cells[1], m.cell_m)}) +
        (f.explored ? ' ' + tt('d.map.explored', {w: f.explored[2], h: f.explored[3]}) : '');
    }
    $('maplabel').textContent = lab; $('mapnote').textContent = note; attr($('mapview'), 'aria-label', lab);
    $('mapzoom').textContent = MP.v ? '×' + MP.v.k : '';
    var wb = $('map-whole'); wb.hidden = !(m && m.full && m.full.cropped); wb.textContent = tt(MP.full ? 'n.map.whole' : 'n.map.detail');
  }
  // the live track: each pose of the sol, one map pixel; the last pose as an amber cross
  function mapTrail() {
    var c = $('maptrail'), x = c.getContext ? c.getContext('2d') : null, tf = MP.tf, a;
    MP.out = false;
    if (!x || !MP.iw) return;
    x.clearRect(0, 0, MP.iw, MP.ih);
    if (!tf) return;
    x.fillStyle = assets.palette[Con.MARK];
    S.path.forEach(function (q) { var p = MV.toPx(tf, q[0], q[1]); if (MV.inImg(tf, p)) x.fillRect(p[0], p[1], 1, 1); });
    if (!S.hasTick) return;
    a = MV.toPx(tf, S.pose[0], S.pose[1]); MP.out = !MV.inImg(tf, a);
    x.fillStyle = assets.palette[Con.hud(10)];
    if (!MP.out) { x.fillRect(a[0] - 2, a[1], 5, 1); x.fillRect(a[0], a[1] - 2, 1, 5); }
  }
  function mvBox() { var e = $('mapview'); return [e.clientWidth || (self.innerWidth || 1280) - 18, e.clientHeight || Math.max(220, (self.innerHeight || 800) - 190)]; }
  function mapFit(re) {
    if (!MP.iw) return;
    var b = mvBox(), d = self.devicePixelRatio || 1;
    MP.v = (re || !MP.v) ? MV.reset(MP.iw, MP.ih, b[0], b[1], d) : MV.view(MP.iw, MP.ih, b[0], b[1], d, MP.v.k, MP.v.tx, MP.v.ty);
    mapPlace();
  }
  function mapPlace() {
    var v = MP.v;
    px($('mapwrap'), 'left', v.tx); px($('mapwrap'), 'top', v.ty);
    ['mapimg', 'maptrail'].forEach(function (id) { px($(id), 'width', v.w); px($(id), 'height', v.h); });
    $('mapzoom').textContent = '×' + v.k;
  }
  function mapPan(dx, dy) {
    if (!MP.v) return;
    var b = mvBox();
    MP.v = MV.view(MP.iw, MP.ih, b[0], b[1], self.devicePixelRatio || 1, MP.v.k, MP.v.tx + dx, MP.v.ty + dy);
    mapPlace();
  }
  // EF-87: a new scale or image at most every 350 ms (as the anchor switches)
  function zOk() { var t = now(); if (t - MP.zAt < 350) return false; MP.zAt = t; return true; }
  function mapReset() { if (MP.v && zOk()) mapFit(true); }
  function mapZoomTo(k, cx, cy) {
    var b = mvBox();
    if (!MP.v || k === MP.v.k || !zOk()) return;
    MP.v = MV.zoomAt(MP.v, k, cx === undefined ? b[0] / 2 : cx, cy === undefined ? b[1] / 2 : cy, MP.iw, MP.ih, b[0], b[1], self.devicePixelRatio || 1);
    mapPlace();
  }
  function mapZoom(d, cx, cy) { if (MP.v) mapZoomTo(MV.step(MP.v.k, d), cx, cy); }

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
    attr($('offc'), 'aria-label', tt('d.offstill')); attr($('mdesc'), 'content', tt('d.desc')); offPlayLabel();
    Lay.ORDER.forEach(function (id) {
      var n = id === 'map' ? tt('n.openmap') : tt('n.enlarge', {panel: tt('n.panel.' + id)});
      ['hit-', 'pb-'].forEach(function (p) { attr($(p + id), 'aria-label', n); attr($(p + id), 'title', n); });
    });
    attr($('ov-prev'), 'aria-label', tt('n.prev')); attr($('ov-prev'), 'title', tt('n.prev'));
    attr($('ov-next'), 'aria-label', tt('n.next')); attr($('ov-next'), 'title', tt('n.next'));
    ['in', 'out'].forEach(function (k) { attr($('map-' + k), 'aria-label', tt('n.map.' + k)); attr($('map-' + k), 'title', tt('n.map.' + k)); });
    attr($('langlink'), 'hreflang', lang === 'fr' ? 'en' : 'fr');
    fsLabel();
    if (ovId) $('ov-title').textContent = tt('n.panel.' + ovId);
    doc.title = route.tab === 'live' ? tt('d.title') : tt({map: 'n.tab.map', '3d': 'n.v3.title'}[route.tab] || 'n.tab.about') + ' · Sol-0';
    if (ready) mapTexts();
    if (V3) V3.texts();
  }
  function links() {
    var other = lang === 'fr' ? 'en' : 'fr';
    ['live', 'map', '3d', 'about'].forEach(function (k) { attr($('tab-' + k), 'href', '#' + lang + '/' + k); attr($('tab-' + k), 'aria-current', route.tab === k ? 'page' : null); });
    attr($('map-3d'), 'href', '#' + lang + '/3d'); attr($('v3-map'), 'href', '#' + lang + '/map');
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
      if (r.sub && panelActive(r.sub) && hasImg && !introOpen()) showPanel(r.sub);     // under the intro: at the next draw after it
      else hidePanel();
      if (prev.tab !== 'live') { queueLayout(); if (limiter) limiter.request(); if (user) { var hl = $('h-live'); if (hl && hl.focus) hl.focus(); } }
    } else if (r.tab === 'map') {
      hidePanel(); mapShow();
      if (prev.tab !== 'map' && user) { var hm = $('h-map'); if (hm && hm.focus) hm.focus(); }
    } else if (r.tab === '3d') {
      hidePanel(); if (v3()) V3.draw(S);
      if (prev.tab !== '3d' && user) { var h3 = $('h-3d'); if (h3 && h3.focus) h3.focus(); }
    } else {
      hidePanel();
      if (r.sub) toSection(r.lang, r.sub);
      else if (keep) toSection(r.lang, keep);
      else if (prev.tab !== 'about' && self.scrollTo) self.scrollTo(0, aboutY);
      if (prev.tab !== 'about' && user && !r.sub) { var ha = $('h-about'); if (ha && ha.focus) { try { ha.focus({preventScroll: true}); } catch (x) { ha.focus(); } } }
    }
  }
  // the 3D tab (view3d.js): created at its first opening; same state S, same limiter, no other connection
  function v3() {
    if (!V3 && ready && self.Sol0View3D) {
      try {
        V3 = self.Sol0View3D.mount({$: $, tt: tt, palette: assets.palette, font: assets.font.table, reduced: reduced, now: now, visible: function () { return route.tab === '3d' && !doc.hidden; },
          off: function () { return offlineShown; }, act: function (s) { return Live.activityText(s, txtOpts()).toLowerCase(); },
          mode: function (m) { return Con.modeLabel(m, txtOpts()); }, dec: function () { return lang === 'fr' ? ',' : '.'; }});
      } catch (e) { V3 = null; }
    }
    return V3;
  }
  function fsLabel() { var b = $('fs'); if (b && ready) b.textContent = tt(doc.fullscreenElement ? 'n.fullscreen.exit' : 'n.fullscreen'); }

  function wire() {
    Lay.ORDER.forEach(function (id) {
      ['hit-', 'pb-'].forEach(function (p) {
        var b = $(p + id);
        b.addEventListener('click', function () { if (id === 'map') go({lang: lang, tab: 'map', sub: null}, 'push'); else openReq(id, b); });
      });
    });
    wireMap();
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
    $('offplay').addEventListener('click', function () { guard.request(function () { offShowAnim(!offAnim); }); });     // EF-87
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
      try { var ro = new self.ResizeObserver(function () { queueLayout(); }); ['top', 'bar', 'silentmsg'].forEach(function (id) { ro.observe($(id)); }); } catch (x) { /* no observer */ }
    }
    if (doc.addEventListener) {
      doc.addEventListener('keydown', function (e) {      // Esc or a click outside closes « Details »
        var d = $('details');
        if (e && e.key === 'Escape' && d.open) { d.open = false; var b = $('infobtn'); if (b.focus) b.focus(); }
      });
      doc.addEventListener('click', function (e) { var d = $('details'); if (d.open && d.contains && !d.contains(e.target)) d.open = false; });
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

  // the map's controls: drag (mouse, finger, pen), pinch, wheel, keys (arrows, + / -, 0) and buttons
  function wireMap() {
    var mv = $('mapview');
    function rel(e) { var r = mv.getBoundingClientRect ? mv.getBoundingClientRect() : {left: 0, top: 0}; return [e.clientX - r.left, e.clientY - r.top]; }
    function two() { var k = Object.keys(MP.ptr), a = MP.ptr[k[0]], b = MP.ptr[k[1]]; return {d: Math.hypot(a[0] - b[0], a[1] - b[1]), x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2}; }
    mv.addEventListener('pointerdown', function (e) {
      MP.ptr[e.pointerId] = [e.clientX, e.clientY];
      if (mv.setPointerCapture) { try { mv.setPointerCapture(e.pointerId); } catch (x) { /* no capture */ } }
      MP.pinch = (Object.keys(MP.ptr).length === 2 && MP.v) ? {d: two().d, k: MP.v.k} : null;
    });
    mv.addEventListener('pointermove', function (e) {
      var q = MP.ptr[e.pointerId], n = Object.keys(MP.ptr).length;
      if (!q) return;
      MP.ptr[e.pointerId] = [e.clientX, e.clientY];
      if (n === 1) mapPan(e.clientX - q[0], e.clientY - q[1]);
      else if (n === 2 && MP.pinch && MP.pinch.d > 0) { var p = two(), r = rel({clientX: p.x, clientY: p.y}); mapZoomTo(MV.nearLevel(MP.pinch.k * p.d / MP.pinch.d), r[0], r[1]); }
    });
    ['pointerup', 'pointercancel'].forEach(function (n) { mv.addEventListener(n, function (e) { delete MP.ptr[e.pointerId]; MP.pinch = null; }); });
    mv.addEventListener('wheel', function (e) {
      if (e.preventDefault) e.preventDefault();
      MP.acc += e.deltaY * (e.deltaMode ? 40 : 1);
      if (Math.abs(MP.acc) >= 50) { var r = rel(e); mapZoom(MP.acc < 0 ? 1 : -1, r[0], r[1]); MP.acc = 0; }
    }, {passive: false});
    mv.addEventListener('keydown', function (e) {
      var A = {ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40]}, k = e.key;
      if (A[k]) mapPan(A[k][0], A[k][1]);
      else if (k === '+' || k === '=') mapZoom(1);
      else if (k === '-' || k === '_') mapZoom(-1);
      else if (k === '0') mapReset();
      else return;
      if (e.preventDefault) e.preventDefault();
    });
    $('map-in').addEventListener('click', function () { mapZoom(1); });
    $('map-out').addEventListener('click', function () { mapZoom(-1); });
    $('map-reset').addEventListener('click', mapReset);
    $('map-whole').addEventListener('click', function () { if (zOk()) { MP.whole = !MP.whole; mapLoad(); } });
  }

  Promise.all([fetch('assets.json').then(function (r) { return r.json(); }), fetch('config.json').then(function (r) { return r.json(); }),
               fetch('i18n.json').then(function (r) { return r.json(); })]).then(function (a) {
    assets = a[0]; cfg = a[1]; birth = Live.birthMs(cfg && cfg.birth_utc);
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
                                minMs: reduced ? 1000 : Live.MIN_DRAW_MS});
    layout();
    var canon = Route.serialize(route);       // canonical anchor (#fr -> #fr/live), no new history entry
    if (location.hash !== canon && self.history && history.replaceState) history.replaceState(history.state || null, '', canon);
    apply(route, false);
    draw();                                    // the waiting card at once (never a black canvas)
    banner(); writeTexts(now());
    setInterval(textLines, 1000);
    connect();
    // the stream is requested first; only then may the intro (intro.js) start loading its video: it never delays the live
    try { if (self.Sol0Intro) self.Sol0Intro.streamStarted(); } catch (e) { /* the intro never stops the page */ }
  }).catch(function () {
    var el = $('state');
    el.textContent = TB[lang]['d.error'] || (lang === 'fr' ? "Erreur : la page n'a pas pu charger ses fichiers." : 'Error: the page could not load its files.');
  });
})();
