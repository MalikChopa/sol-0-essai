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
    return {sol: null, stage: 0, stageName: '', now: null, slot0: null, tickMs: 600, cam: null, camT: null, camMs: null, camDims: null, hour: 0, mode: 'BABBLE',
            pose: [0, 0, 1, 0], target: null, battery: 0, speed: 0, pitch: 0, roll: 0, slip: 0, sun: [0, 0, 0], stuck: false,
            tipped: false, asleep: false, locked: false, drill: 0, nd: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0),
            hd: new Array(16).fill(0), y: [0, 0], z: null, m1: null, m1max: 1e-12, m3: null, m4: null, armPatch: null, sample: null,
            spectrum: null, cat: -1, conf: 0, scan: null, trail: [], map: new Map(), w: null, t: -1, sunTimes: null, ticksPerSol: 1200,
            hasTick: false, sunVec: null, solar: 0, learn: null, learnVals: {}, phases: [], phase: null, nextUtc: null, solEnd: null, published: null,
            serverUtc: null, engineSilentS: 0, engineLastMs: null, serverOffsetMs: 0, helloMs: null, exact: false, snapLeft: 0, snapTickAgeS: null,
            snapCamAgeS: null, snapPhaseAgeS: null, burst: false, replaySol: null, replayMaxT: -1, replaySolEnd: false, neverSeen: false, lastEventMs: 0,
            lastTickMs: 0, phaseSinceMs: null, attempt: null, ff: null, resumeArmed: false, resuming: false};
  }
  // Connection and engine-liveness fields: they describe the visit, not the sol, so a `sol` line keeps them.
  var LINK_KEYS = ['serverUtc', 'engineSilentS', 'engineLastMs', 'serverOffsetMs', 'helloMs', 'exact', 'snapLeft', 'snapTickAgeS', 'snapCamAgeS',
                   'snapPhaseAgeS', 'burst', 'replaySol', 'replayMaxT', 'replaySolEnd', 'neverSeen'];
  function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : null; }
  function mapKey(x, y) { return (x + 32768) * 65536 + (y + 32768); }
  // Engine liveness is a time, not a flag. `hello` carries the age of the engine's last line (`engine_silent_s`); right after it the
  // server replays a snapshot of OLD lines which proves nothing about the engine.
  // Exact mode (server live-rc11 and later, web.py `HelloState.lines`): hello says how many snapshot lines follow (`snap_n`), sent in
  // the order the server read them (so the last phase / tick applied is the engine's current one), and how old the last tick, the last
  // tick with a CAM-1 image (live-rc12) and the last phase line are (`tick_age_s`, `cam_age_s`, `phase_age_s`). The first `snap_n`
  // lines after hello are the replay, every later line is fresh.
  // Fallback (older server, no `snap_n`): the rc10 rule below. A line is fresh only if the replay cannot contain it: a `status` or a
  // `restart` (never replayed), a `sol` of another sol than the replayed one, or a `tick` newer than the newest `t` of `poses`.
  function markEngine(S, ev, nowMs) {
    var n = nowMs || 0;
    if (ev.e === 'hello') {
      S.engineSilentS = ev.engine_silent_s || 0; S.engineLastMs = n - S.engineSilentS * 1000; S.helloMs = n;
      S.serverOffsetMs = ev.server_utc ? Date.parse(ev.server_utc) - n : 0;
      S.neverSeen = S.engineSilentS >= 1000000;
      S.exact = typeof ev.snap_n === 'number' && ev.snap_n >= 0;
      S.resumeArmed = false; S.resuming = false;      // a restart seen before this connection proves nothing about the ticks since
      if (S.exact) {
        S.snapLeft = ev.snap_n; S.snapTickAgeS = num(ev.tick_age_s); S.snapCamAgeS = num(ev.cam_age_s); S.snapPhaseAgeS = num(ev.phase_age_s);
        S.burst = false;
      } else {
        S.snapLeft = 0; S.snapTickAgeS = null; S.snapCamAgeS = null; S.snapPhaseAgeS = null;
        S.burst = true; S.replaySol = null; S.replayMaxT = -1; S.replaySolEnd = false;
      }
      return false;
    }
    if (S.exact) {
      if (S.snapLeft > 0) { S.snapLeft--; return false; }
      S.neverSeen = false; S.engineLastMs = n;
      return true;
    }
    if (S.burst) {      // fallback for an older server (rc10 rule, unchanged)
      if (ev.e === 'sol') { if (S.replaySol === null) { S.replaySol = ev.s; S.replayMaxT = -1; return false; } if (ev.s === S.replaySol) return false; }
      else if (ev.e === 'poses') { var ts = ev.t || []; S.replayMaxT = ts.length ? ts[ts.length - 1] : -1; return false; }
      else if (ev.e === 'tick') { if (typeof ev.t !== 'number' || ev.t <= S.replayMaxT) return false; }
      else if (ev.e === 'sol_end') { S.replaySolEnd = true; return false; }
      else if (ev.e !== 'status' && ev.e !== 'restart') return false;     // status and restart are never replayed
    }
    S.burst = false; S.neverSeen = false; S.engineLastMs = n;
    return true;
  }
  // When was a replayed line written (page clock)? Exact mode: hello's receive time minus the age the server measured; fallback: at
  // most as recent as the engine's last line. Null = unknown.
  function replayedAt(S, ageS) {
    if (S.exact) return (ageS !== null && S.helloMs !== null) ? S.helloMs - ageS * 1000 : S.engineLastMs;
    return S.engineLastMs;
  }
  // When was a replayed CAM-1 image written? `cam_age_s` when the server gives it (live-rc12); an older server: the rc11 rule (the
  // date of the replayed tick). Never younger than the replayed tick: the image comes from that tick or an earlier one.
  function replayedCamAt(S, tickAt) {
    var at = (S.exact && S.snapCamAgeS !== null && S.helloMs !== null) ? S.helloMs - S.snapCamAgeS * 1000 : tickAt;
    return (typeof tickAt === 'number' && typeof at === 'number') ? Math.min(at, tickAt) : at;
  }
  function applyEvent(S, ev, nowMs) {
    var n = nowMs || 0;
    S.lastEventMs = n;
    var fresh = markEngine(S, ev, nowMs);
    switch (ev.e) {
      case 'hello': S.serverUtc = ev.server_utc; break;
      case 'sol': {
        var keep = {}, nv = newView(), i;
        for (i = 0; i < LINK_KEYS.length; i++) keep[LINK_KEYS[i]] = S[LINK_KEYS[i]];
        for (var k in nv) S[k] = nv[k];
        for (var kk in keep) S[kk] = keep[kk];
        S.lastEventMs = nowMs || 0;
        S.sol = (typeof ev.s === 'number') ? ev.s : null; S.stage = ev.stage; S.stageName = ev.stage_name || ''; S.now = ev.now; S.tickMs = ev.tick_ms || 600;
        S.slot0 = (typeof ev.slot0 === 'number' && isFinite(ev.slot0)) ? ev.slot0 : null;     // start of the sol's 15-min slot (ms, UTC)
        S.replay = ev.replay === true; S.seasonSols = ev.season_sols || 0; S.camDims = ev.cam; S.w = (ev.w && typeof ev.w === 'object') ? f32(ev.w.m0) : null; S.sunTimes = ev.sun || null; if (ev.ticks) S.ticksPerSol = ev.ticks;
        if (ev.scan0) {   // producer format: {n, explained, xy, labels, ids?, k?, names?}; k and names only when the engine provides them
          var sc0 = ev.scan0, ids = sc0.ids || null;
          S.scan = {pts: (sc0.xy || []).map(function (p, i) { return [ids ? ids[i] : i, p[0], p[1], sc0.labels[i], -1]; }),
                    k: (sc0.k === undefined ? null : sc0.k), ax: Math.floor(sc0.explained * 100 + 0.5), names: sc0.names || {}};
        }
        break;
      }
      case 'tick': {
        var at = fresh ? n : replayedAt(S, S.snapTickAgeS);
        applyTick(S, ev, at, fresh ? n : replayedCamAt(S, at));
        if (fresh) { S.resumeArmed = false; S.resuming = false; }   // the engine broadcasts again: the resume is over
        break;
      }
      case 'learn': {
        var L = S.learn;
        if (!L || L.mod !== ev.mod) { L = S.learn = {mod: ev.mod, gen: 0, of: 0, best: null, mean: null, bars: []}; }
        L.gen = ev.gen; L.of = ev.of; L.best = ev.best; L.mean = ev.mean;
        if (ev.best !== null && ev.best !== undefined) { L.bars.push(ev.best); if (L.bars.length > 12) L.bars.shift(); }
        if (ev.val) S.learnVals[ev.mod] = {val: ev.val, gen: ev.gen, of: ev.of};
        break;
      }
      case 'phase':
        // fallback only (older server, snapshot not in order): a replayed 'idle' of a sol with ticks and no sol_end predates the episode
        if (!S.exact && !fresh && ev.ph === 'idle' && S.replaySol !== null && S.replayMaxT >= 0 && !S.replaySolEnd) break;
        S.phase = ev.ph; S.nextUtc = ev.next || null;          // each phase line carries its own `next` (idle only); never a stale one
        S.phaseSinceMs = fresh ? n : (S.exact ? replayedAt(S, S.snapPhaseAgeS) : null);
        if (fresh) S.resuming = false;                       // a new phase line says what the engine does now
        if (ev.ph === 'learn') { S.learn = null; S.learnVals = {}; S.phases = []; S.solEnd = null; }
        if (S.phases.indexOf(ev.ph) < 0) S.phases.push(ev.ph);
        break;
      case 'sol_end': S.solEnd = ev; break;
      case 'restart':     // the engine restarted: the old episode's tick gap no longer applies
        if (fresh) { S.phase = null; S.nextUtc = null; S.resumeArmed = true; S.resuming = false; }
        break;
      case 'status':
        // M5 (live-rc12, à re-valider): after a fresh restart and before the first fresh tick, a fresh status saying `episode` means the
        // engine is recomputing the sol it was in (engine.py R2: the ticks already due are computed without being broadcast)
        if (fresh && S.resumeArmed) S.resuming = ev.phase === 'episode';
        break;
      case 'published': S.published = ev; break;
      case 'ff': S.ff = ev; break;
      case 'attempt':
        S.attempt = ev;
        // an engine attempt failed (k >= 0; the publisher writes k = -1): the engine retries without broadcasting ticks (engine.py `_drive`)
        if (typeof ev.k === 'number' && ev.k >= 0 && S.phase === 'episode') S.phase = null;
        break;
      default: break;
    }
    return S;
  }
  // M3 (live-rc12): a tick of another sol than the one shown, without its `sol` line (the engine resumed a sol it had not announced):
  // the sol number becomes the tick's, and nothing that belongs to the previous sol stays on screen (image, start time, weights, sun
  // times, trail, learning and end-of-sol values). The stage and the CAM-1 size stay the last known ones (they only change with the
  // stage); an image of another size is refused in applyTick.
  function solChanged(S, s) {
    S.sol = s; S.cam = null; S.camT = null; S.camMs = null; S.now = null; S.slot0 = null; S.w = null; S.sunTimes = null; S.scan = null; S.trail = [];
    S.z = null; S.m1max = 1e-12; S.armPatch = null; S.sample = null; S.spectrum = null; S.cat = -1; S.conf = 0;
    S.learn = null; S.learnVals = {}; S.phases = []; S.solEnd = null; S.attempt = null; S.ff = null;
  }
  function decodeCam(S, ev) {    // the image only when its size is the known CAM-1 size (sol line), else null
    var d = S.camDims, data = null;
    if (typeof ev.cam !== 'string') return null;
    try { data = b64(ev.cam); } catch (e) { data = null; }
    if (!d || typeof d.w !== 'number' || typeof d.h !== 'number' || !(d.w > 0 && d.h > 0) || !data) return null;
    if (data.length !== d.w * d.h) { S.camDims = null; return null; }    // another CAM-1 size: the stage changed, its facts are unknown
    return {w: d.w, h: d.h, data: data};
  }
  function applyTick(S, ev, nowMs, camMs) {
    if (typeof ev.s === 'number' && ev.s !== S.sol) solChanged(S, ev.s);
    S.t = ev.t; S.hour = ev.hr; S.mode = ev.m; S.pose = ev.p; S.target = ev.tg; S.battery = ev.b; S.speed = ev.v;
    S.pitch = ev.pi; S.roll = ev.ro; S.slip = ev.sl; S.solar = ev.so;
    if (ev.sd) S.sunVec = ev.sd;
    S.sun = S.sunVec ? [S.sunVec[0], S.sunVec[1], S.sunVec[2]] : [0, 0, 0];
    S.stuck = (ev.fl & 1) !== 0; S.tipped = (ev.fl & 2) !== 0; S.asleep = (ev.fl & 4) !== 0; S.locked = (ev.fl & 16) !== 0;   // bit 16 = arm locked (written by the producer from TickView.arm_locked)
    S.u = ev.u; S.xi = ev.xi; S.x = ev.x; S.hd = ev.hd; S.y = ev.y; S.m1 = ev.m1 ? ev.m1[0].concat(ev.m1[1]) : null; S.m3 = ev.m3; S.m4 = ev.m4;
    S.drill = ev.dr; S.nd = ev.nd; S.hasTick = true; S.lastTickMs = nowMs || 0; S.phase = 'episode';
    if (S.m1) for (var i = 0; i < S.m1.length; i++) S.m1max = Math.max(S.m1max, Math.abs(S.m1[i]));
    if (ev.cam !== undefined) {
      S.cam = decodeCam(S, ev);                 // M4: no image rather than an image read with the wrong size
      S.camT = S.cam ? ev.t : null; S.camMs = S.cam ? (camMs === undefined ? (nowMs || 0) : camMs) : null;
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
    // M1 (live-rc12): the visitor's own stream broke (app.js es.onerror). Until the next hello the page knows nothing new about the
    // engine: CONNECTING, never ENGINE SILENT (label() only judges the engine in LIVE / LEARNING). OFFLINE / SERVER BUSY stay.
    L.onLost = function () { if (L.state !== 'OFFLINE' && L.state !== 'SERVER BUSY') L.state = 'CONNECTING'; };
    L.onEvent = function (S, ev) {
      L.failures = 0; L.busy = false;
      if (ev.e === 'phase') L.state = ['learn', 'narrative', 'render', 'check', 'save'].indexOf(ev.ph) >= 0 ? 'LEARNING' : 'LIVE';
      else if (ev.e === 'tick' || ev.e === 'sol') L.state = 'LIVE';
      else if (L.state === 'CONNECTING') L.state = 'LIVE';
    };
    return L;
  }
  // Engine silence: no engine line for SILENT_S (any kind; a replayed line is not one), or in an episode no tick for TICK_GAP_MS.
  // The engine writes a `status` every 60 s while it waits (idle, hold, retries), so the same 120 s limit holds in every phase.
  function engineQuiet(S, nowMs) {
    return S.engineLastMs !== null && S.engineLastMs !== undefined && nowMs - S.engineLastMs > SILENT_S * 1000;
  }
  function engineSilent(S, nowMs) {
    if (S.engineLastMs === null || S.engineLastMs === undefined) return false;
    if (engineQuiet(S, nowMs)) return true;
    return S.phase === 'episode' && S.hasTick && nowMs - S.lastTickMs > TICK_GAP_MS;
  }
  function replaying(S) { return S.exact && S.snapLeft > 0; }
  // RC12-verif I2 (live-rc13): what the page may show, on the canvas (app.js draw) and in the text lines: a tick of this visit, or a
  // `sol` line once the snapshot is complete. A `sol` line without any tick yet (the start of a sol, or a late start whose `ff`
  // catch-up is computed without broadcast) shows the bare view (sol number, NO IMAGE YET): never the previous sol's image, never the
  // console filled with newView defaults. During the snapshot (or the burst of an older server) the page waits for the rest of it.
  function canDraw(S) {
    if (S.hasTick) return true;
    if (typeof S.sol !== 'number') return false;
    return !(S.exact ? S.snapLeft > 0 : S.burst);
  }
  function label(L, S, nowMs) {
    if (L.state === 'LIVE' || L.state === 'LEARNING') {
      if (replaying(S)) return engineQuiet(S, nowMs) ? 'ENGINE SILENT' : 'CONNECTING';   // the snapshot is not complete yet
      if (engineSilent(S, nowMs)) return 'ENGINE SILENT';
      if (S.phase === 'hold') return 'ENGINE HOLD';
      if (S.resuming) return 'RESUMING';
    }
    if (L.state === 'LIVE' && S.replay) return 'REPLAY';
    return L.state;
  }
  // Banner texts that assets.json (generated by tools/live/export_assets.py) does not have yet; FR + EN.
  // (Kept here, not moved to export_assets.py I18N: see docs/milestones/LIVE.md, « Âge de l'image et reprises ».)
  var EXTRA_LABELS = {'ENGINE HOLD': {en: 'ENGINE ON HOLD', fr: 'MOTEUR EN PAUSE'}, 'RESUMING': {en: 'RESUMING', fr: 'REPRISE'}};
  function extraLabel(st, lang) { var x = EXTRA_LABELS[st]; return x ? (lang === 'fr' ? x.fr : x.en) : null; }
  // Age of the data on screen = age of the OLDEST thing drawn: max(age of the last tick (telemetry, brain), age of the drawn CAM-1
  // image, which comes every `cam_period` ticks only and may be much older after a restart); no tick: the engine's last line.
  // Dates are receive times (fresh lines) or the server's read times (cam_age_s, tick_age_s): rounded UP to the second, the shown age
  // is never below the true age to the second; it can be below the exact age by the server's read delay plus the network transit
  // (not measured).
  function dataAgeS(S, nowMs) {
    var ref;
    if (S.hasTick) {
      ref = S.lastTickMs;
      if (S.cam && typeof S.camMs === 'number') ref = Math.min(ref, S.camMs);
    } else ref = (S.engineLastMs === null || S.engineLastMs === undefined) ? S.lastEventMs : S.engineLastMs;
    return Math.max(0, Math.ceil((nowMs - ref) / 1000));
  }
  // Seconds left before `next` on the server clock (hello's server_utc), or null when there is no next or it is already past:
  // never a countdown frozen at 0:00.
  function nextLeftS(S, nowMs) {
    if (!S.nextUtc || S.phase !== 'idle') return null;
    var at = Date.parse(S.nextUtc);
    if (!isFinite(at)) return null;
    var left = Math.floor((at - (nowMs + (S.serverOffsetMs || 0))) / 1000);
    return left > 0 ? left : null;
  }
  function fmtDuration(sec) {
    var s = Math.max(0, Math.floor(sec)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h > 0) return h + ' h ' + m + ' min';
    if (m > 0) return m + ' min ' + r + ' s';
    return r + ' s';
  }
  // ---- texts (page v2): T(o, id, english, vars) with o.t = table of the page language (pages/live/i18n.json); without a table the
  // English literal, or for the DOM texts below the rc13 French when lang === 'fr' (DOM_FR = i18n.json fr, tests/page/i18n.test.js)
  function tr(o, id, en, v) {
    var s = (o && o.t && typeof o.t[id] === 'string') ? o.t[id] : en;
    if (v) s = s.replace(/\{([a-z0-9_]+)\}/g, function (m, k) { return v[k] === undefined ? m : String(v[k]); });
    return s;
  }
  var DOM_FR = {'d.silent.never': 'Le moteur ne tourne pas en ce moment : aucune donnée depuis le démarrage du serveur.',
                'd.silent.for': 'Le moteur est silencieux depuis {d}.',
                'd.hold.known': 'Le moteur est en pause depuis {d} : aucun nouveau sol avant un redémarrage du moteur.',
                'd.hold.unknown': 'Le moteur est en pause : aucun nouveau sol avant un redémarrage du moteur.',
                'd.resume': 'Le moteur a redémarré : il recalcule le sol en cours avant de reprendre la diffusion.',
                'd.noimage': "pas encore d'image"};
  function domO(lang, o) { return (o && o.t) ? o : (lang === 'fr' ? {t: DOM_FR} : null); }
  // Text shown instead of a black canvas when the engine is silent and no tick was ever received in this visit; data only.
  function silentText(S, nowMs, lang, o) {
    if (S.hasTick) return null;
    var s = (nowMs - S.engineLastMs) / 1000, q = domO(lang, o);
    if (S.neverSeen) return tr(q, 'd.silent.never', 'The engine is not running right now: no data since the server started.');
    return tr(q, 'd.silent.for', 'The engine has been silent for {d}.', {d: fmtDuration(s)});
  }
  // Text under the canvas while the engine is on hold (engine.py `_hold`: it refused to go on, writes a `status` every minute and
  // computes no sol until it is restarted). The duration comes from the `phase hold` line (its age), shown only when known.
  function holdText(S, nowMs, lang, o) {
    if (S.phase !== 'hold') return null;
    var known = S.phaseSinceMs !== null && S.phaseSinceMs !== undefined, q = domO(lang, o);
    if (!known) return tr(q, 'd.hold.unknown', 'The engine is on hold: no new sol until the engine is restarted.');
    return tr(q, 'd.hold.known', 'The engine has been on hold for {d}: no new sol until the engine is restarted.',
              {d: fmtDuration(Math.ceil((nowMs - S.phaseSinceMs) / 1000))});
  }
  // M5: text under the canvas while the engine resumes (fresh restart, then a fresh status `episode`, no tick broadcast yet).
  function resumeText(S, lang, o) {
    if (!S.resuming) return null;
    return tr(domO(lang, o), 'd.resume', 'The engine restarted: it is recomputing the current sol before broadcasting again.');
  }
  // M4: said in the DOM when the canvas has no CAM-1 image to show.
  function noImageText(S, lang, o) {
    if (S.cam || !canDraw(S)) return null;
    return tr(domO(lang, o), 'd.noimage', 'no image yet');
  }
  // The text line under the canvas (template `line` of assets.json, FR or EN). Tick values only once a tick of this sol was received;
  // before it (a `sol` line, no tick yet) `--` for each of them, never a default of newView. With a tick: the rc12 text, unchanged.
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function lineText(S, tpl, params) {
    var s = typeof S.sol === 'number' ? S.sol : '--';
    if (!S.hasTick) return tpl.replace('{s}', s).replace('{hh}', '--').replace('{mm}', '--').replace('{mode}', '--').replace('{b}', '--').replace('{v}', '--');
    var hh = Math.floor(S.hour), mm = Math.floor((S.hour - hh) * 60);
    return tpl.replace('{s}', s).replace('{hh}', pad2(hh)).replace('{mm}', pad2(mm)).replace('{mode}', S.mode)
      .replace('{b}', Math.floor(S.battery * 100 + 1e-9)).replace('{v}', C.fix(S.speed * params.cell_m * 100 / params.tick_s, 2));
  }
  // ---- pause views (design 9.3) ----
  var MOD_NAMES = {m0: 'M0 DRIVE', m1: 'M1 PREDICT', m2: 'M2 VISION', m3: 'M3 ENERGY', m4: 'M4 SAMPLE', m5: 'M5 CATEGORIES', battery: 'TEST COURSES'};
  function valText(mod, v, o) {
    var x = v.val || {};
    var n = function (q) { return (typeof q === 'number' && isFinite(q)) ? String(q) : '--'; };
    var f2 = function (q) { return (o && o.dec === ',') ? C.fix(q, 2).replace('.', ',') : C.fix(q, 2); };
    // v.of = number of learning generations, NOT the number of courses: never paired with the count of successes
    if (mod === 'battery') return tr(o, 'c.pause.battery', 'TEST COURSES {n} PASSED', {n: n(x.successes)});
    if (mod === 'm1') return tr(o, 'c.pause.r2', 'R2 {v}', {v: f2(x.r2)});
    if (mod === 'm2') return tr(o, 'c.pause.explained', 'EXPLAINED {v}', {v: f2(x.explained)});
    if (mod === 'm5') return tr(o, 'c.pause.ari', 'K {k} | ARI {a}', {k: (typeof x.k === 'number' ? x.k : '--'), a: f2(x.ari)});
    return null;
  }
  var C = null;
  // producer: sol_end.progress = {fraction, label, value, blocking} (views.py progress_dict); `text` / `value` are the engine's English
  // words. Page v2 in French: the percentage of `fraction` when there is one (à re-valider), else the engine's text as it is (data).
  function progressText(p, o) {
    if (!p || typeof p !== 'object') return null;
    var pc = (typeof p.fraction === 'number' && isFinite(p.fraction)) ? Math.floor(p.fraction * 100 + 0.5) + '%' : null;
    if (o && o.lang === 'fr' && pc !== null) return pc;
    var t = (typeof p.text === 'string' && p.text) ? p.text : (typeof p.value === 'string' ? p.value : null);
    if (t) return t;
    return pc;
  }
  // Title of the pause view, or null when the canvas shows the episode (no pause view). RESUMING is a pause view whatever the last
  // phase line was (RC12-verif I1: after a restart the phase is unknown until a phase line comes). English: it is also the view key.
  function pauseTitle(S) {
    var P = S.phase;
    if (P === 'hold') return 'ENGINE HOLD';
    if (S.resuming) return 'RESUMING';
    if (!P || P === 'episode') return null;
    return 'END OF SOL | ' + (P === 'learn' ? 'LEARNING' : (P === 'idle' ? 'WAITING' : String(P).toUpperCase()));
  }
  var PH_EN = {learn: 'LEARNING', idle: 'WAITING', narrative: 'NARRATIVE', render: 'RENDER', check: 'CHECK', save: 'SAVE'};
  function phaseText(ph, o) { return tr(o, 'c.pause.ph.' + ph, PH_EN[ph] || String(ph).toUpperCase()); }
  // the same title in the page language
  function pauseTitleText(S, o) {
    var P = S.phase;
    if (P === 'hold') return tr(o, 'c.pause.hold', 'ENGINE HOLD');
    if (S.resuming) return tr(o, 'c.pause.resuming', 'RESUMING');
    if (!P || P === 'episode') return null;
    return tr(o, 'c.pause.endofsol', 'END OF SOL | {ph}', {ph: phaseText(P, o)});
  }
  function drawPause(img, S, o) {
    var page = !!(o && o.page), P = S.phase, y, k, resuming = S.resuming && P !== 'hold';
    var right = page ? (o.right || '') : '', rx = 632 - C.textWidth(right);
    C.rect(img, 150, 3, page ? rx - 4 - 150 : 270, 12, C.BG);     // page: up to the right text (never a piece of the centred text left)
    C.text(img, 160, 6, pauseTitleText(S, o), C.hud(10), 1);
    if (S.cam && S.camT !== null) {         // the tick that produced the image
      var lf = tr(o, 'c.pause.lastframe', 'LAST FRAME T{n}', {n: S.camT});
      if (page) C.textOn(img, 8 + 320 - 4 - C.textWidth(lf), 202, lf, C.MARK, 1, o);     // D13: clear of the SUN compass
      else C.text(img, 12, 213, lf, C.MARK, 1);
    }
    C.rect(img, 337, 25, 294, 198, C.BG);
    C.text(img, 340, 28, P === 'hold' ? tr(o, 'c.pause.brain.hold', 'BRAIN | ENGINE HOLD') : (resuming ? tr(o, 'c.pause.brain.resuming', 'BRAIN | RESUMING')
      : (P === 'idle' ? tr(o, 'c.pause.brain.end', 'BRAIN | END OF SOL') : tr(o, 'c.pause.brain.learn', 'BRAIN | LEARNING'))), C.hud(10), 1);
    y = 44;
    var f2 = function (q) { return (o && o.dec === ',') ? C.fix(q, 2, true).replace('.', ',') : C.fix(q, 2, true); };
    if (S.learn && (P === 'learn' || P === 'narrative' || P === 'render' || P === 'check' || P === 'save')) {
      var L = S.learn;
      C.text(img, 340, y, tr(o, 'c.pause.mod.' + L.mod, MOD_NAMES[L.mod] || String(L.mod).toUpperCase()), C.hud(10), 2); y += 20;
      C.text(img, 340, y, tr(o, 'c.pause.gen', 'GEN {g}/{n}', {g: L.gen, n: L.of}), C.hud(10), 1); y += 12;
      if (L.best !== null && L.best !== undefined) { C.text(img, 340, y, tr(o, 'c.pause.best', 'BEST {v}', {v: f2(L.best)}), C.hud(10), 1); y += 10; }
      if (L.mean !== null && L.mean !== undefined) { C.text(img, 340, y, tr(o, 'c.pause.mean', 'MEAN {v}', {v: f2(L.mean)}), C.hud(10), 1); y += 10; }
      var lo = Math.min.apply(null, L.bars.concat([0])), hi = Math.max.apply(null, L.bars.concat([0])), span = hi - lo || 1;
      for (k = 0; k < L.bars.length; k++) {
        var hh = Math.max(1, Math.floor(30 * (L.bars[k] - lo) / span));
        C.rect(img, 340 + 22 * k, 125 - hh, 18, hh, C.hud(7));
      }
    }
    y = 134;
    Object.keys(S.learnVals).forEach(function (m) {
      var t = valText(m, S.learnVals[m], o);
      if (t && y < 205) { C.text(img, 340, y, t, C.hud(10), 1); y += 10; }
    });
    // M6 (page): the phases in the order they came (S.phases), not a fixed order
    var order = page ? S.phases.filter(function (ph) { return ph === 'render' || ph === 'check' || ph === 'save'; }) : ['render', 'check', 'save'];
    order.forEach(function (ph) {
      if (S.phases.indexOf(ph) >= 0 && y < 215) {
        C.text(img, 340, y, S.phase === ph ? tr(o, 'c.pause.running', '{ph} ...', {ph: phaseText(ph, o)}) : tr(o, 'c.pause.done', '{ph} OK', {ph: phaseText(ph, o)}), C.hud(7), 1);
        y += 10;
      }
    });
    if (S.solEnd && (P === 'idle' || P === 'hold')) {
      var E = S.solEnd, rows = [[tr(o, 'c.sol.sol', 'SOL'), S.sol], [tr(o, 'c.sol.stage', 'STAGE'), E.stage], [tr(o, 'c.sol.progress', 'PROGRESS'), progressText(E.progress, o)],
                                 [page ? null : tr(o, 'c.sol.distance', 'DISTANCE M'), E.distance_m], [tr(o, 'c.sol.targets', 'TARGETS'), E.targets],
                                 [tr(o, 'c.sol.retries', 'RETRIES'), E.attempts], [tr(o, 'c.sol.courses', 'COURSES PASSED'), E.battery_successes]];
      y = 44;
      rows.forEach(function (r) {
        if (r[1] === undefined || r[1] === null) return;
        // M5 (page): « DISTANCE 735 M », the stream's value rounded to the metre
        var t = r[0] === null ? tr(o, 'c.sol.distm', 'DISTANCE {d} M', {d: (typeof r[1] === 'number' && isFinite(r[1])) ? Math.round(r[1]) : String(r[1]).toUpperCase()})
          : r[0] + ' ' + String(r[1]).toUpperCase();
        C.text(img, 340, y, t, C.hud(10), 1); y += 12;
      });
    }
    if (page) C.vignette(img);        // M7: the cleared rectangles get the vignette back
  }
  function nightText(S, o) {
    if (!S.hasTick || !S.camDims || S.stage > 2 || S.mode !== 'SLEEP' || !S.sunTimes) return null;     // no sol line known: stage unknown
    if (o && o.page) {    // D7 / UI-AUDIT I12: the sunrise on the rover's clock (sol.sun.lever), never an estimate of real minutes
      var lv = S.sunTimes.lever;
      if (typeof lv !== 'number' || !isFinite(lv)) return null;
      var h = Math.floor(lv), m = Math.floor((lv - h) * 60.0);
      return tr(o, 'c.night', 'NIGHT | SLEEPING | SUNRISE {hh}:{mm}', {hh: pad2(h), mm: pad2(m)});
    }
    var d = (S.sunTimes.lever - S.hour + 24) % 24, min = Math.ceil(d * (S.ticksPerSol / 24) * S.tickMs / 60000);
    return 'NIGHT | SLEEPING | SUNRISE IN ' + min + ' MIN';
  }
  // season line (design 4.4): computed from the sol number and the sunrise/sunset times of the sol event; null if not provided.
  // Page v2 (D6): `seasonLine` says SOL d/n (the sol's place in the planet's year) and DAYLIGHT (simulated day length), FR decimal comma.
  // VERIF-rc14 I3: d = sol % n, counted from 0 like the sols (the engine's season phase is (sol % year) / year, world/climate.py):
  // in year 1 « SOL d » is the sol shown by the bar and the canvas, never a second number for the same word.
  function seasonText(S, tpl) {
    if (!S.seasonSols || !S.sunTimes || typeof S.sol !== 'number') return null;
    var yl = 4 * S.seasonSols, h = S.sunTimes.coucher - S.sunTimes.lever;
    return tpl.replace('{y}', Math.floor(S.sol / yl) + 1).replace('{d}', (S.sol % yl) + 1).replace('{n}', yl).replace('{h}', (Math.round(h * 10) / 10).toFixed(1));
  }
  function seasonLine(S, o) {
    if (!S.seasonSols || !S.sunTimes || typeof S.sol !== 'number') return null;
    var yl = 4 * S.seasonSols, h = (Math.round((S.sunTimes.coucher - S.sunTimes.lever) * 10) / 10).toFixed(1);
    return tr(o, 'd.season', 'YEAR {y} · SOL {d}/{n} · DAYLIGHT {h} h', {y: Math.floor(S.sol / yl) + 1, d: S.sol % yl, n: yl,
                                                                          h: (o && o.dec === ',') ? h.replace('.', ',') : h});
  }
  // No sol line known (none seen in this visit, or the CAM-1 size proved the stage changed): stage, sol start, camera size and weights
  // are unknown, so the console (laid out by stage) is not drawn; only facts of the ticks: sol number, hour, NO IMAGE YET.
  // Also a sol line and no tick yet (RC12-verif I2): the sol number only (no hour, no tick value), NO IMAGE YET.
  function drawBare(img, S, o) {
    img.fill(C.BG);
    if (o && o.page) {      // M11: the same header as the console (stage when the sol line is known), the five empty frames
      var center = S.camDims ? C.centerText(S, o) : (typeof S.sol === 'number' ? tr(o, 'c.bare.sol', 'SOL {n}', {n: S.sol > 9999 ? S.sol : ('0000' + S.sol).slice(-4)}) : '');
      C.header(img, center, o.right || '', false, o);
      C.emptyFrames(img);
      if (S.hasTick && typeof S.hour === 'number' && isFinite(S.hour)) C.textOn(img, 12, 28, C.hhmm(S.hour), C.MARK, 1, o);
      C.camCenter(img, 24 + 100 + 9, tr(o, 'c.cam.noimage', 'NO IMAGE YET'), o);
      C.vignette(img);
      return img;
    }
    C.text(img, 8, 3, 'SOL-0', C.hud(10), 2);
    C.text(img, 72, 6, 'CAM-1', C.hud(10), 1);
    if (typeof S.sol === 'number') C.text(img, 160, 6, 'SOL ' + (S.sol > 9999 ? S.sol : ('0000' + S.sol).slice(-4)), C.hud(10), 1);
    C.rect(img, 0, 20, 640, 1, C.hud(2));
    C.frameRect(img, 7, 23, 322, 202, C.hud(4));
    if (S.hasTick && typeof S.hour === 'number' && isFinite(S.hour)) {
      var hh = Math.floor(S.hour), mm = Math.floor((S.hour - hh) * 60.0);
      C.text(img, 12, 28, (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm, C.MARK, 1);
    }
    var t = 'NO IMAGE YET';
    C.text(img, 8 + Math.floor((320 - C.textWidth(t)) / 2), 24 + 100 + 9, t, C.MARK, 1);
    return img;
  }
  // ---- page v2: state words, header right text, REC, waiting card, status bar texts ----
  var STATE_KEY = {'CONNECTING': 'connecting', 'LIVE': 'live', 'LEARNING': 'learning', 'OFFLINE': 'offline', 'SERVER BUSY': 'busy',
                   'REPLAY': 'replay', 'ENGINE SILENT': 'silent', 'ENGINE HOLD': 'hold', 'RESUMING': 'resuming'};
  var WAIT_EN = {connecting: 'CONNECTING', live: 'WAITING FOR DATA', idle: 'WAITING FOR THE NEXT SOL', learning: 'LEARNING', replay: 'REPLAY',
                 silent: 'ENGINE SILENT', hold: 'ENGINE ON HOLD', busy: 'SERVER BUSY', resuming: 'RESUMING', offline: 'OFFLINE'};
  function stateKey(label) { return STATE_KEY[label] || 'connecting'; }
  function waitText(key, o) { return tr(o, 'c.wait.' + key, WAIT_EN[key] || WAIT_EN.connecting); }
  // D17: the header's right text says the state when the console is not live (same words as the badge); else D2: the real start of
  // the sol's slot (`slot0` of the sol line, UTC), nothing when unknown (older server, sol without its line). Never S.now.
  function headerRight(S, o, label) {
    if (label && label !== 'LIVE' && label !== 'LEARNING' && label !== 'REPLAY') return waitText(stateKey(label), o);
    if (typeof S.slot0 !== 'number' || !isFinite(S.slot0)) return '';
    var d = new Date(S.slot0);
    return tr(o, 'c.hdr.right', 'SOL START {hh}:{mm} UTC', {hh: pad2(d.getUTCHours()), mm: pad2(d.getUTCMinutes())});
  }
  // D14: REC is lit only while fresh ticks are drawn (state LIVE, no pause view, a tick, awake)
  function recOn(S, label) { return label === 'LIVE' && pauseTitle(S) === null && S.hasTick && S.mode !== 'SLEEP'; }
  // the waiting card's key: what it says (D3)
  function waitKey(S, label) {
    var k = stateKey(label || 'CONNECTING');
    if (k === 'live' && S.phase === 'idle') k = 'idle';
    else if (k === 'live' && ['learn', 'narrative', 'render', 'check', 'save'].indexOf(S.phase) >= 0) k = 'learning';
    return k;
  }
  // D3: nothing to draw yet (no sol line, or the snapshot is not complete): the frames, what the page knows, and the time of the next
  // sol when the engine announced it (fixed time, no countdown on the canvas: the countdown is in #next). No value of any sol.
  // VERIF-rc14 M4: the time only while it is ahead (same rule as #next, `nextLeftS`; o.now = the page's clock), never a past time.
  function renderWaiting(img, S, o) {
    o = o || {};
    img.fill(C.BG);
    C.header(img, '', '', false, o);
    C.emptyFrames(img);
    var k = waitKey(S, o.label);
    C.camCenter(img, 24 + 100 - 8, waitText(k, o), o);
    if (nextLeftS(S, typeof o.now === 'number' ? o.now : Date.now()) !== null) {
      var d = new Date(Date.parse(S.nextUtc));
      C.camCenter(img, 24 + 100 + 6, tr(o, 'c.wait.next', 'NEXT SOL {hh}:{mm}:{ss} UTC', {hh: pad2(d.getUTCHours()), mm: pad2(d.getUTCMinutes()), ss: pad2(d.getUTCSeconds())}), o);
    }
    C.vignette(img);
    return img;
  }
  // what the rover is doing, in the page language: the pause title, the night text, else the mode (same words as the canvas)
  function activityText(S, o) {
    var pt = pauseTitleText(S, o);
    if (pt !== null) return pt;
    if (!S.hasTick) return '--';
    var nt = nightText(S, o);
    if (nt) return nt.split(' | ').join(' · ');
    return C.modeLabel(S.mode, o);
  }
  // status bar line (#line, starts with SOL: the bench reads the sol number there): no tick yet -> `--`, never a default of newView
  function barLine(S, o) {
    var s = typeof S.sol === 'number' ? S.sol : '--', hh = '--', mm = '--';
    if (S.hasTick) { hh = Math.floor(S.hour); mm = pad2(Math.floor((S.hour - hh) * 60)); hh = pad2(hh); }
    return tr(o, 'd.line', 'SOL {s} · {hh}:{mm} · {act}', {s: s, hh: hh, mm: mm, act: activityText(S, o)});
  }
  function stageBar(S, o) {
    if (!S.stageName) return '';
    return tr(o, 'd.stagebar', 'STAGE {s} · {name}', {s: S.stage, name: C.stageLabel(S, o)});
  }
  // the accessible sentence (#summary, at most once a minute)
  function summaryText(S, o, ageTxt, params) {
    var s = typeof S.sol === 'number' ? S.sol : '--';
    if (!S.hasTick) return tr(o, 'd.summary.none', 'Sol {s}: no step received yet, data age {t}.', {s: s, t: ageTxt});
    var hh = Math.floor(S.hour), mm = Math.floor((S.hour - hh) * 60), act = activityText(S, o).split(' | ').join(', ').split(' · ').join(', ').toLowerCase();
    var bat = C.batteryUnlocked(S.stage) ? tr(o, 'd.summary.bat', 'battery {b}%', {b: Math.floor(S.battery * 100 + 1e-9)})
      : tr(o, 'd.summary.batlocked', 'battery shown from stage {n}', {n: C.batteryUnlockStage()});
    var v = C.F(o, S.speed * params.cell_m * 100 / params.tick_s, 2);
    return tr(o, 'd.summary', "Sol {s}, {hh}:{mm} on the rover's clock, {act}, {bat}, speed {v} cm/s, data age {t}.",
              {s: s, hh: pad2(hh), mm: pad2(mm), act: act, bat: bat, v: v, t: ageTxt});
  }
  function renderLive(img, S, link, o) {
    if (!o || !o.page) {          // rc13 drawing (the tests of the state machine and the bench keys use it)
      if (!S.camDims || !S.hasTick) drawBare(img, S);
      else C.renderConsole(img, S, {scanlines: true, contactLabel: 'SOL START'});   // S.now: sol nominal time (rc13 label, D2)
      if (pauseTitle(S) !== null) drawPause(img, S);
      else { var nt0 = nightText(S); if (nt0) C.text(img, 8 + Math.floor((320 - C.textWidth(nt0)) / 2), 24 + 100 + 12, nt0, C.MARK, 1); }
      return img;
    }
    // page v2: o = {page, t, en, dec, lang, label (Live.label at draw time), boxes?}; right text and REC follow the state
    o.right = headerRight(S, o, o.label);
    o.rec = recOn(S, o.label);
    if (o.scanlines === undefined) o.scanlines = true;
    C.setBoxes(o.boxes || null);
    if (!S.camDims || !S.hasTick) drawBare(img, S, o);
    else C.renderConsole(img, S, o);
    if (pauseTitle(S) !== null) drawPause(img, S, o);
    else {
      var nt = nightText(S, o);
      if (nt) C.camCenter(img, S.cam ? 24 + 100 + 12 : 148, nt, o);       // D12: under NO IMAGE YET when there is no image
    }
    C.setBoxes(null);
    return img;
  }

  var api = {b64: b64, newView: newView, applyEvent: applyEvent, makeLimiter: makeLimiter, makeLink: makeLink, label: label, silentText: silentText, dataAgeS: dataAgeS, fmtDuration: fmtDuration, engineSilent: engineSilent,
             holdText: holdText, resumeText: resumeText, noImageText: noImageText, nextLeftS: nextLeftS, canDraw: canDraw, pauseTitle: pauseTitle, lineText: lineText, extraLabel: extraLabel, countLine: function (S, nowMs) { return markEngine(S, {e: '?'}, nowMs); },
             renderLive: renderLive, nightText: nightText, seasonText: seasonText, setConsole: function (c) { C = c; }, valText: valText, progressText: progressText,
             tr: tr, pauseTitleText: pauseTitleText, headerRight: headerRight, recOn: recOn, waitKey: waitKey, stateKey: stateKey, renderWaiting: renderWaiting,
             activityText: activityText, barLine: barLine, stageBar: stageBar, seasonLine: seasonLine, summaryText: summaryText,
             STATE_KEY: STATE_KEY, WAIT_EN: WAIT_EN, MOD_NAMES: MOD_NAMES, PH_EN: PH_EN, DOM_FR: DOM_FR,
             MIN_DRAW_MS: MIN_DRAW_MS, BUSY_POLL_MS: BUSY_POLL_MS, OFFLINE_RETRY_MS: OFFLINE_RETRY_MS, OPEN_TIMEOUT_MS: OPEN_TIMEOUT_MS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0Live = api;
})(typeof self !== 'undefined' ? self : this);
