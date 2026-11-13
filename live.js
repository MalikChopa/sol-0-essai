/* Sol-0 live page: stream-v2 reducer, connection states, draw limiter, pause views. No third-party script.
   Pure logic (testable with `node --test tests/page/`) is exported; the DOM glue only runs in a browser. */
(function (root) {
  'use strict';
  var MIN_DRAW_MS = 500;            // <= 2 redraws per second (EF-87)
  var SILENT_S = 120, TICK_GAP_MS = 5000;
  var BUSY_POLL_MS = 9000, OFFLINE_RETRY_MS = 60000, OPEN_TIMEOUT_MS = 10000, FAILS_TO_OFFLINE = 3;

  function b64(s) {
    if (s === null || s === undefined) return null;
    var bin = atob(s), n = bin.length, u = new Uint8Array(n);
    for (var i = 0; i < n; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  function f32(s) { var u = b64(s); return u ? new Float32Array(u.buffer.slice(u.byteOffset, u.byteOffset + u.length)) : null; }

  // ---- stream v2 reducer ----
  function newView() {
    return {sol: null, stage: 0, stageName: '', now: '1970-01-01T00:00:00Z', tickMs: 600, cam: null, camDims: null, hour: 0, mode: 'BABBLE',
            pose: [0, 0, 1, 0], target: null, battery: 0, speed: 0, pitch: 0, roll: 0, slip: 0, sun: [0, 0, 0], stuck: false,
            tipped: false, asleep: false, locked: false, drill: 0, nd: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0),
            hd: new Array(16).fill(0), y: [0, 0], z: null, m1: null, m1max: 1e-12, m3: null, m4: null, armPatch: null, sample: null,
            spectrum: null, cat: -1, conf: 0, scan: null, trail: [], map: new Map(), w: null, t: -1, sunTimes: null, ticksPerSol: 1200,
            hasTick: false, sunVec: null, solar: 0, learn: null, learnVals: {}, phases: [], phase: null, nextUtc: null, solEnd: null, published: null,
            serverUtc: null, engineSilentS: 0, engineLastMs: null, serverOffsetMs: 0, burst: false, replaySol: null, replayMaxT: -1, neverSeen: false, lastEventMs: 0, lastTickMs: 0, attempt: null, ff: null};
  }
  function mapKey(x, y) { return (x + 32768) * 65536 + (y + 32768); }
  // Engine liveness is a time, not a flag. `hello` carries the age of the engine's last line; right after it the server replays a
  // snapshot of OLD lines which proves nothing (web.py `_State.lines()`: sol, poses, then the last lm / cam / tick lines, which
  // are up to THREE ticks with different `t`, then learn, sol_end, phase). `poses` exists only in that snapshot and its last `t`
  // is the newest replayed tick. So, after hello, a line is fresh only if the replay cannot contain it: a `status` (never
  // replayed), a `sol` of another sol than the replayed one, or a `tick` newer than the newest replayed tick. No timing guess.
  function markEngine(S, ev, nowMs) {
    var n = nowMs || 0;
    if (ev.e === 'hello') {
      S.engineSilentS = ev.engine_silent_s || 0; S.engineLastMs = n - S.engineSilentS * 1000;
      S.serverOffsetMs = ev.server_utc ? Date.parse(ev.server_utc) - n : 0;
      S.burst = true; S.replaySol = null; S.replayMaxT = -1; S.neverSeen = S.engineSilentS >= 1000000; return;
    }
    if (S.burst) {
      if (ev.e === 'sol') { if (S.replaySol === null) { S.replaySol = ev.s; S.replayMaxT = -1; return; } if (ev.s === S.replaySol) return; }
      else if (ev.e === 'poses') { var ts = ev.t || []; S.replayMaxT = ts.length ? ts[ts.length - 1] : -1; return; }
      else if (ev.e === 'tick') { if (typeof ev.t !== 'number' || ev.t <= S.replayMaxT) return; }
      else if (ev.e !== 'status') return;
    }
    S.burst = false; S.neverSeen = false; S.engineLastMs = n;
  }
  function applyEvent(S, ev, nowMs) {
    S.lastEventMs = nowMs || 0;
    markEngine(S, ev, nowMs);
    switch (ev.e) {
      case 'hello': S.serverUtc = ev.server_utc; break;
      case 'sol': {
        var keep = {serverUtc: S.serverUtc, engineSilentS: S.engineSilentS, engineLastMs: S.engineLastMs, serverOffsetMs: S.serverOffsetMs, burst: S.burst, replaySol: S.replaySol, replayMaxT: S.replayMaxT, neverSeen: S.neverSeen};
        var fresh = newView();
        for (var k in fresh) S[k] = fresh[k];
        for (var kk in keep) S[kk] = keep[kk];
        S.lastEventMs = nowMs || 0;
        S.sol = ev.s; S.stage = ev.stage; S.stageName = ev.stage_name || ''; S.now = ev.now; S.tickMs = ev.tick_ms || 600;
        S.replay = ev.replay === true; S.seasonSols = ev.season_sols || 0; S.camDims = ev.cam; S.w = (ev.w && typeof ev.w === 'object') ? f32(ev.w.m0) : null; S.sunTimes = ev.sun || null; if (ev.ticks) S.ticksPerSol = ev.ticks;
        if (ev.scan0) {   // producer format: {n, explained, xy, labels, ids?, k?, names?}; k and names only when the engine provides them
          var sc0 = ev.scan0, ids = sc0.ids || null;
          S.scan = {pts: (sc0.xy || []).map(function (p, i) { return [ids ? ids[i] : i, p[0], p[1], sc0.labels[i], -1]; }),
                    k: (sc0.k === undefined ? null : sc0.k), ax: Math.floor(sc0.explained * 100 + 0.5), names: sc0.names || {}};
        }
        break;
      }
      case 'tick': applyTick(S, ev, nowMs); break;
      case 'learn': {
        var L = S.learn;
        if (!L || L.mod !== ev.mod) { L = S.learn = {mod: ev.mod, gen: 0, of: 0, best: null, mean: null, bars: []}; }
        L.gen = ev.gen; L.of = ev.of; L.best = ev.best; L.mean = ev.mean;
        if (ev.best !== null && ev.best !== undefined) { L.bars.push(ev.best); if (L.bars.length > 12) L.bars.shift(); }
        if (ev.val) S.learnVals[ev.mod] = {val: ev.val, gen: ev.gen, of: ev.of};
        break;
      }
      case 'phase':
        S.phase = ev.ph; S.nextUtc = ev.next || S.nextUtc;
        if (ev.ph === 'learn') { S.learn = null; S.learnVals = {}; S.phases = []; S.solEnd = null; }
        if (S.phases.indexOf(ev.ph) < 0) S.phases.push(ev.ph);
        break;
      case 'sol_end': S.solEnd = ev; break;
      case 'published': S.published = ev; break;
      case 'ff': S.ff = ev; break;
      case 'attempt': S.attempt = ev; break;
      default: break;
    }
    return S;
  }
  function applyTick(S, ev, nowMs) {
    S.t = ev.t; S.hour = ev.hr; S.mode = ev.m; S.pose = ev.p; S.target = ev.tg; S.battery = ev.b; S.speed = ev.v;
    S.pitch = ev.pi; S.roll = ev.ro; S.slip = ev.sl; S.solar = ev.so;
    if (ev.sd) S.sunVec = ev.sd;
    S.sun = S.sunVec ? [S.sunVec[0], S.sunVec[1], S.sunVec[2]] : [0, 0, 0];
    S.stuck = (ev.fl & 1) !== 0; S.tipped = (ev.fl & 2) !== 0; S.asleep = (ev.fl & 4) !== 0; S.locked = (ev.fl & 16) !== 0;   // bit 16 = arm locked (written by the producer from TickView.arm_locked)
    S.u = ev.u; S.xi = ev.xi; S.x = ev.x; S.hd = ev.hd; S.y = ev.y; S.m1 = ev.m1 ? ev.m1[0].concat(ev.m1[1]) : null; S.m3 = ev.m3; S.m4 = ev.m4;
    S.drill = ev.dr; S.nd = ev.nd; S.hasTick = true; S.lastTickMs = nowMs || 0; S.phase = 'episode';
    if (S.m1) for (var i = 0; i < S.m1.length; i++) S.m1max = Math.max(S.m1max, Math.abs(S.m1[i]));
    if (ev.cam !== undefined) {
      S.cam = {w: S.camDims.w, h: S.camDims.h, data: b64(ev.cam)};
      S.z = ev.z || null; S.trail.push(ev.p);
      var sn = ev.sn || [];
      var snt = ev.snt || [];   // soil type + 1 of each newly seen cell, aligned with sn
      for (var j = 0; j < sn.length && j < snt.length; j++) S.map.set(mapKey(sn[j][0], sn[j][1]), snt[j]);
      if (ev.lm) {              // {x0, y0, d}: soil type per cell, 255 = unknown
        var g = b64(ev.lm.d);
        for (var cy = 0; cy < 60; cy++) for (var cx = 0; cx < 60; cx++) { var v = g[cy * 60 + cx]; if (v !== 255) S.map.set(mapKey(ev.lm.x0 + cx, ev.lm.y0 + cy), v + 1); }
      }
      if (S.stage >= 4) S.armPatch = ev.arm ? b64(ev.arm.p) : null;
    }
    if (ev.smp && ev.smp.f) S.sample = {f: ev.smp.f, g: ev.smp.g, n: ev.smp.n};
    if (ev.spc) {
      if (ev.spc.v) S.spectrum = ev.spc.v;
      if (ev.spc.cat !== undefined) { S.cat = ev.spc.cat; S.conf = ev.spc.conf; }
      if (S.scan) (ev.spc.pts || []).forEach(function (p) { S.scan.pts.push([p[0], p[1], p[2], p[3], ev.t]); });
    }
  }

  // ---- redraw limiter: the latest state, at most 1 draw per MIN_DRAW_MS ----
  function makeLimiter(o) {
    var last = -Infinity, timer = null, minMs = o.minMs || MIN_DRAW_MS;
    function fire() { timer = null; last = o.now(); o.draw(); }
    return {
      request: function () {
        if (timer !== null) return;
        var wait = last + minMs - o.now();
        if (wait <= 0) fire(); else timer = o.setTimer(fire, wait);
      },
      pending: function () { return timer !== null; }
    };
  }

  // ---- connection states ----
  function makeLink() {
    var L = {state: 'CONNECTING', failures: 0, busy: false, lastOkMs: null};
    L.onOk = function () { L.failures = 0; L.busy = false; if (L.state === 'OFFLINE' || L.state === 'SERVER BUSY') L.state = 'CONNECTING'; };
    L.onHttp = function (status) {
      if (status === 503 || status === 429) { L.state = 'SERVER BUSY'; L.busy = true; L.failures = 0; return; }
      if (status >= 200 && status < 300) L.onOk();
    };
    L.onNetworkError = function () {
      L.busy = false; L.failures++;
      if (L.failures >= FAILS_TO_OFFLINE) L.state = 'OFFLINE';
    };
    // a received hello is a successful contact (the engine verdict is label()'s job)
    L.onHello = function () { L.failures = 0; L.busy = false; if (L.state === 'CONNECTING') L.state = 'LIVE'; };
    L.onEvent = function (S, ev) {
      L.failures = 0; L.busy = false;
      if (ev.e === 'phase') L.state = ['learn', 'narrative', 'render', 'check', 'save'].indexOf(ev.ph) >= 0 ? 'LEARNING' : 'LIVE';
      else if (ev.e === 'tick' || ev.e === 'sol') L.state = 'LIVE';
      else if (L.state === 'CONNECTING') L.state = 'LIVE';
    };
    return L;
  }
  // Engine silence: no line (any kind, after the snapshot) for SILENT_S, or in an episode no tick for TICK_GAP_MS.
  // The engine writes a `status` every 60 s while idle, so the same 120 s limit holds in every phase.
  function engineSilent(S, nowMs) {
    if (S.engineLastMs === null || S.engineLastMs === undefined) return false;
    var quiet = nowMs - S.engineLastMs;
    if (quiet > SILENT_S * 1000) return true;
    return S.phase === 'episode' && S.lastTickMs > 0 && nowMs - S.lastTickMs > TICK_GAP_MS;
  }
  function label(L, S, nowMs) {
    if ((L.state === 'LIVE' || L.state === 'LEARNING') && engineSilent(S, nowMs)) return 'ENGINE SILENT';
    if (L.state === 'LIVE' && S.replay) return 'REPLAY';
    return L.state;
  }
  function fmtDuration(sec) {
    var s = Math.max(0, Math.floor(sec)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h > 0) return h + ' h ' + m + ' min';
    if (m > 0) return m + ' min ' + r + ' s';
    return r + ' s';
  }
  // Text shown instead of a black canvas when the engine is silent and no tick was ever received in this visit; data only.
  function silentText(S, nowMs, lang) {
    if (S.hasTick) return null;
    var s = (nowMs - S.engineLastMs) / 1000;
    if (S.neverSeen) return lang === 'fr' ? 'Le moteur ne tourne pas en ce moment : aucune donnée depuis le démarrage du serveur.'
                                          : 'The engine is not running right now: no data since the server started.';
    var d = fmtDuration(s);
    return lang === 'fr' ? 'Le moteur est silencieux depuis ' + d + '.' : 'The engine has been silent for ' + d + '.';
  }
  // ---- pause views (design 9.3) ----
  var MOD_NAMES = {m0: 'M0 DRIVE', m1: 'M1 PREDICT', m2: 'M2 VISION', m3: 'M3 ENERGY', m4: 'M4 SAMPLE', m5: 'M5 CATEGORIES', battery: 'TEST COURSES'};
  function valText(mod, v) {
    var x = v.val || {};
    var n = function (q) { return (typeof q === 'number' && isFinite(q)) ? String(q) : '--'; };
    // v.of = number of learning generations, NOT the number of courses: never paired with the count of successes
    if (mod === 'battery') return 'TEST COURSES ' + n(x.successes) + ' PASSED';
    if (mod === 'm1') return 'R2 ' + C.fix(x.r2, 2);
    if (mod === 'm2') return 'EXPLAINED ' + C.fix(x.explained, 2);
    if (mod === 'm5') return 'K ' + (typeof x.k === 'number' ? x.k : '--') + ' | ARI ' + C.fix(x.ari, 2);
    return null;
  }
  var C = null;
  // producer: sol_end.progress = {fraction, text, blocking} (status.json); anything else is not displayed
  function progressText(p) {
    if (!p || typeof p !== 'object') return null;
    var t = (typeof p.text === 'string' && p.text) ? p.text : (typeof p.value === 'string' ? p.value : null);
    if (t) return t;
    return (typeof p.fraction === 'number' && isFinite(p.fraction)) ? Math.floor(p.fraction * 100 + 0.5) + '%' : null;
  }
  function drawPause(img, S) {
    var P = S.phase, lines = [], y, k;
    C.rect(img, 150, 3, 270, 12, C.BG);
    C.text(img, 160, 6, 'END OF SOL | ' + (P === 'learn' ? 'LEARNING' : (P === 'idle' || P === 'hold' ? 'WAITING' : String(P).toUpperCase())), C.hud(10), 1);
    if (S.hasTick) C.text(img, 12, 213, 'LAST FRAME T' + S.t, C.MARK, 1);
    C.rect(img, 337, 25, 294, 198, C.BG);
    C.text(img, 340, 28, P === 'idle' || P === 'hold' ? 'BRAIN | END OF SOL' : 'BRAIN | LEARNING', C.hud(10), 1);
    y = 44;
    if (S.learn && (P === 'learn' || P === 'narrative' || P === 'render' || P === 'check' || P === 'save')) {
      var L = S.learn;
      C.text(img, 340, y, MOD_NAMES[L.mod] || String(L.mod).toUpperCase(), C.hud(10), 2); y += 20;
      C.text(img, 340, y, 'GEN ' + L.gen + '/' + L.of, C.hud(10), 1); y += 12;
      if (L.best !== null && L.best !== undefined) { C.text(img, 340, y, 'BEST ' + C.fix(L.best, 2, true), C.hud(10), 1); y += 10; }
      if (L.mean !== null && L.mean !== undefined) { C.text(img, 340, y, 'MEAN ' + C.fix(L.mean, 2, true), C.hud(10), 1); y += 10; }
      var lo = Math.min.apply(null, L.bars.concat([0])), hi = Math.max.apply(null, L.bars.concat([0])), span = hi - lo || 1;
      for (k = 0; k < L.bars.length; k++) {
        var hh = Math.max(1, Math.floor(30 * (L.bars[k] - lo) / span));
        C.rect(img, 340 + 22 * k, 125 - hh, 18, hh, C.hud(7));
      }
    }
    y = 134;
    Object.keys(S.learnVals).forEach(function (m) {
      var t = valText(m, S.learnVals[m]);
      if (t && y < 205) { C.text(img, 340, y, t, C.hud(10), 1); y += 10; }
    });
    ['render', 'check', 'save'].forEach(function (ph) {
      if (S.phases.indexOf(ph) >= 0 && y < 215) { C.text(img, 340, y, ph.toUpperCase() + (S.phase === ph ? ' ...' : ' OK'), C.hud(7), 1); y += 10; }
    });
    if (S.solEnd && (P === 'idle' || P === 'hold')) {
      var E = S.solEnd, rows = [['SOL', S.sol], ['STAGE', E.stage], ['PROGRESS', progressText(E.progress)], ['DISTANCE M', E.distance_m], ['TARGETS', E.targets],
                                 ['RETRIES', E.attempts], ['COURSES PASSED', E.battery_successes]];
      y = 44;
      rows.forEach(function (r) { if (r[1] !== undefined && r[1] !== null) { C.text(img, 340, y, r[0] + ' ' + String(r[1]).toUpperCase(), C.hud(10), 1); y += 12; } });
    }
  }
  function nightText(S) {
    if (S.stage > 2 || S.mode !== 'SLEEP' || !S.sunTimes) return null;
    var d = (S.sunTimes.lever - S.hour + 24) % 24, min = Math.ceil(d * (S.ticksPerSol / 24) * S.tickMs / 60000);
    return 'NIGHT | SLEEPING | SUNRISE IN ' + min + ' MIN';
  }
  // season line (design 4.4): computed from the sol number and the sunrise/sunset times of the sol event; null if not provided
  function seasonText(S, tpl) {
    if (!S.seasonSols || !S.sunTimes || typeof S.sol !== 'number') return null;
    var yl = 4 * S.seasonSols, h = S.sunTimes.coucher - S.sunTimes.lever;
    return tpl.replace('{y}', Math.floor(S.sol / yl) + 1).replace('{d}', (S.sol % yl) + 1).replace('{n}', yl).replace('{h}', (Math.round(h * 10) / 10).toFixed(1));
  }
  function renderLive(img, S, link) {
    C.renderConsole(img, S, {scanlines: true, contactLabel: 'SOL START'});   // S.now = start time of the sol, not a contact time
    var pause = S.phase && S.phase !== 'episode';
    if (pause) drawPause(img, S);
    else { var nt = nightText(S); if (nt) C.text(img, 8 + Math.floor((320 - C.textWidth(nt)) / 2), 24 + 100 + 12, nt, C.MARK, 1); }
    return img;
  }

  var api = {b64: b64, newView: newView, applyEvent: applyEvent, makeLimiter: makeLimiter, makeLink: makeLink, label: label, silentText: silentText, fmtDuration: fmtDuration, engineSilent: engineSilent,
             renderLive: renderLive, nightText: nightText, seasonText: seasonText, setConsole: function (c) { C = c; }, valText: valText, progressText: progressText,
             MIN_DRAW_MS: MIN_DRAW_MS, BUSY_POLL_MS: BUSY_POLL_MS, OFFLINE_RETRY_MS: OFFLINE_RETRY_MS, OPEN_TIMEOUT_MS: OPEN_TIMEOUT_MS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0Live = api;
})(typeof self !== 'undefined' ? self : this);
