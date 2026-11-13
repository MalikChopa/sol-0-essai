/* Sol-0 live page: DOM glue (browser only). Reads config.json (same origin), opens the stream, draws at most twice a second. */
(function () {
  'use strict';
  var Live = self.Sol0Live, Con = self.Sol0Console;
  var lang = (location.hash === '#fr' || (location.hash !== '#en' && /^fr/i.test(navigator.language || ''))) ? 'fr' : 'en';
  var assets, cfg, S = Live.newView(), link = Live.makeLink(), es = null, buf = new Uint8Array(640 * 360), pal = null;
  var canvas = document.getElementById('c'), ctx = canvas.getContext('2d'), img = ctx.createImageData(640, 360);
  var $ = function (id) { return document.getElementById(id); };
  var lastLine = 0, lastAria = 0, openTimer = null, retryTimer = null, offlineShown = false;
  function T() { return assets.i18n[lang]; }
  function now() { return Date.now(); }

  function draw() {
    if (!S.hasTick || offlineShown) return;
    Live.renderLive(buf, S, link);
    for (var i = 0; i < buf.length; i++) { var c = pal[buf[i]]; img.data[4 * i] = c[0]; img.data[4 * i + 1] = c[1]; img.data[4 * i + 2] = c[2]; img.data[4 * i + 3] = 255; }
    ctx.putImageData(img, 0, 0);
  }
  var limiter = null;
  function banner() {
    var st = Live.label(link, S, now()), el = $('state');
    el.textContent = ({'CONNECTING': T().connecting, 'LIVE': T().live, 'LEARNING': T().learning, 'OFFLINE': T().offline,
                       'SERVER BUSY': T().busy, 'REPLAY': T().replay, 'ENGINE SILENT': T().silent})[st] || st;
    el.dataset.state = st;
    var sm = $('silentmsg'), txt = (st === 'ENGINE SILENT') ? Live.silentText(S, now(), lang) : null;
    if (txt) { sm.textContent = txt; sm.hidden = false; } else sm.hidden = true;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function textLines() {
    var t = now();
    banner();
    if (t - lastLine >= 1000 && S.hasTick) {
      lastLine = t;
      var hh = Math.floor(S.hour), mm = Math.floor((S.hour - hh) * 60);
      $('line').textContent = T().line.replace('{s}', S.sol).replace('{hh}', pad(hh)).replace('{mm}', pad(mm)).replace('{mode}', S.mode)
        .replace('{b}', Math.floor(S.battery * 100 + 1e-9)).replace('{v}', Con.fix(S.speed * assets.params.cell_m * 100 / assets.params.tick_s, 2));
      $('age').textContent = T().age + ': ' + Math.max(0, Math.round((t - S.lastEventMs) / 1000)) + ' s';
      var st = Live.seasonText(S, T().season); $('season').textContent = st ? st : '';
      var nt = Live.nightText(S); $('night').textContent = nt ? nt : '';
      if (S.nextUtc && (S.phase === 'idle' || S.phase === 'hold')) {
        var left = Math.max(0, Math.round((Date.parse(S.nextUtc) - (S.serverUtc ? Date.parse(S.serverUtc) + (t - S.lastEventMs) : t)) / 1000));
        $('next').textContent = T().next.replace('{t}', S.nextUtc.slice(11, 19)) + ' (' + Math.floor(left / 60) + ':' + pad(left % 60) + ')';
      } else $('next').textContent = '';
    }
    if (t - lastAria >= 60000 && S.hasTick) { lastAria = t; $('summary').textContent = $('line').textContent; }
  }
  function onEvent(ev) {
    if (ev.e === 'hello' || ev.e === 'status') { Live.applyEvent(S, ev, now()); if (ev.e === 'hello') link.onHello(); banner(); return; }
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
      es.addEventListener(n, function (m) { try { onEvent(JSON.parse(m.data)); } catch (e) { /* ignore a malformed line */ } });
    });
    es.onerror = function () { es.close(); es = null; clearTimeout(openTimer); probe(); };
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
  function offlineNote(t, n) {
    var tpl = lang === 'fr' ? 'Serveur hors ligne. Dernier sol publié : {n}, à {t} UTC (enregistré, pas en direct).'
                            : 'Server offline. Last published sol: {n}, at {t} UTC (recorded, not live).';
    return tpl.replace('{t}', t).replace('{n}', n);
  }
  function showOffline() {
    offlineShown = true; canvas.hidden = true;
    var g = $('off'); g.hidden = false; $('offimg').src = cfg.stateRaw + '/console.gif';
    var note = $('offnote');
    fetch(cfg.stateRaw + '/status.json', {cache: 'no-store'}).then(function (r) { return r.json(); }).then(function (j) {
      var n = (j.run && j.run.sol !== undefined) ? j.run.sol : (j.det && j.det.sol), u = (j.det && j.det.last_success_utc) || '';
      note.textContent = offlineNote(u.slice(11, 16) || '--:--', n === undefined ? '?' : n);
    }).catch(function () { note.textContent = offlineNote('--:--', '?'); });
  }
  function hideOffline() { offlineShown = false; canvas.hidden = false; $('off').hidden = true; }

  Promise.all([fetch('assets.json').then(function (r) { return r.json(); }), fetch('config.json').then(function (r) { return r.json(); })]).then(function (a) {
    assets = a[0]; cfg = a[1];
    Con.init(assets); Live.setConsole(Con);
    pal = assets.palette.map(function (h) { return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)]; });
    document.documentElement.lang = lang;
    $('legend').textContent = T().legend; canvas.setAttribute('aria-label', T().aria); document.title = T().title;
    $('langlink').href = lang === 'fr' ? '#en' : '#fr'; $('langlink').textContent = lang === 'fr' ? 'English' : 'Français';
    $('langlink').addEventListener('click', function () { setTimeout(function () { location.reload(); }, 0); });
    limiter = Live.makeLimiter({now: now, draw: draw, setTimer: function (f, ms) { return setTimeout(f, ms); }});
    setInterval(textLines, 1000);
    connect();
  }).catch(function () { $('state').textContent = 'ERROR'; });
})();
