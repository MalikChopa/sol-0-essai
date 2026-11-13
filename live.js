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
    return {sol: null, stage: 0, stageName: '', now: null, tickMs: 600, cam: null, camT: null, camMs: null, camDims: null, hour: 0, mode: 'BABBLE',
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
    S.sol = s; S.cam = null; S.camT = null; S.camMs = null; S.now = null; S.w = null; S.sunTimes = null; S.scan = null; S.trail = [];
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
  // Text shown instead of a black canvas when the engine is silent and no tick was ever received in this visit; data only.
  function silentText(S, nowMs, lang) {
    if (S.hasTick) return null;
    var s = (nowMs - S.engineLastMs) / 1000;
    if (S.neverSeen) return lang === 'fr' ? 'Le moteur ne tourne pas en ce moment : aucune donnée depuis le démarrage du serveur.'
                                          : 'The engine is not running right now: no data since the server started.';
    var d = fmtDuration(s);
    return lang === 'fr' ? 'Le moteur est silencieux depuis ' + d + '.' : 'The engine has been silent for ' + d + '.';
  }
  // Text under the canvas while the engine is on hold (engine.py `_hold`: it refused to go on, writes a `status` every minute and
  // computes no sol until it is restarted). The duration comes from the `phase hold` line (its age), shown only when known.
  function holdText(S, nowMs, lang) {
    if (S.phase !== 'hold') return null;
    var known = S.phaseSinceMs !== null && S.phaseSinceMs !== undefined, d = known ? fmtDuration(Math.ceil((nowMs - S.phaseSinceMs) / 1000)) : null;
    if (lang === 'fr') return (known ? 'Le moteur est en pause depuis ' + d : 'Le moteur est en pause') + ' : aucun nouveau sol avant un redémarrage du moteur.';
    return (known ? 'The engine has been on hold for ' + d : 'The engine is on hold') + ': no new sol until the engine is restarted.';
  }
  // M5: text under the canvas while the engine resumes (fresh restart, then a fresh status `episode`, no tick broadcast yet).
  function resumeText(S, lang) {
    if (!S.resuming) return null;
    return lang === 'fr' ? 'Le moteur a redémarré : il recalcule le sol en cours avant de reprendre la diffusion.'
                         : 'The engine restarted: it is recomputing the current sol before broadcasting again.';
  }
  // M4: said in the DOM (FR + EN) when the canvas has no CAM-1 image to show (the canvas itself says NO IMAGE YET, in English).
  function noImageText(S, lang) {
    if (S.cam || !canDraw(S)) return null;
    return lang === 'fr' ? "pas encore d'image" : 'no image yet';
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
  // Title of the pause view, or null when the canvas shows the episode (no pause view). RESUMING is a pause view whatever the last
  // phase line was (RC12-verif I1: after a restart the phase is unknown until a phase line comes).
  function pauseTitle(S) {
    var P = S.phase;
    if (P === 'hold') return 'ENGINE HOLD';
    if (S.resuming) return 'RESUMING';
    if (!P || P === 'episode') return null;
    return 'END OF SOL | ' + (P === 'learn' ? 'LEARNING' : (P === 'idle' ? 'WAITING' : String(P).toUpperCase()));
  }
  function drawPause(img, S) {
    var P = S.phase, lines = [], y, k, resuming = S.resuming && P !== 'hold';
    C.rect(img, 150, 3, 270, 12, C.BG);
    C.text(img, 160, 6, pauseTitle(S), C.hud(10), 1);
    if (S.cam && S.camT !== null) C.text(img, 12, 213, 'LAST FRAME T' + S.camT, C.MARK, 1);   // the tick that produced the image
    C.rect(img, 337, 25, 294, 198, C.BG);
    C.text(img, 340, 28, P === 'hold' ? 'BRAIN | ENGINE HOLD' : (resuming ? 'BRAIN | RESUMING' : (P === 'idle' ? 'BRAIN | END OF SOL' : 'BRAIN | LEARNING')), C.hud(10), 1);
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
    if (!S.hasTick || !S.camDims || S.stage > 2 || S.mode !== 'SLEEP' || !S.sunTimes) return null;     // no sol line known: stage unknown
    var d = (S.sunTimes.lever - S.hour + 24) % 24, min = Math.ceil(d * (S.ticksPerSol / 24) * S.tickMs / 60000);
    return 'NIGHT | SLEEPING | SUNRISE IN ' + min + ' MIN';
  }
  // season line (design 4.4): computed from the sol number and the sunrise/sunset times of the sol event; null if not provided
  function seasonText(S, tpl) {
    if (!S.seasonSols || !S.sunTimes || typeof S.sol !== 'number') return null;
    var yl = 4 * S.seasonSols, h = S.sunTimes.coucher - S.sunTimes.lever;
    return tpl.replace('{y}', Math.floor(S.sol / yl) + 1).replace('{d}', (S.sol % yl) + 1).replace('{n}', yl).replace('{h}', (Math.round(h * 10) / 10).toFixed(1));
  }
  // No sol line known (none seen in this visit, or the CAM-1 size proved the stage changed): stage, sol start, camera size and weights
  // are unknown, so the console (laid out by stage) is not drawn; only facts of the ticks: sol number, hour, NO IMAGE YET.
  // Also a sol line and no tick yet (RC12-verif I2): the sol number only (no hour, no tick value), NO IMAGE YET.
  function drawBare(img, S) {
    img.fill(C.BG);
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
  function renderLive(img, S, link) {
    if (!S.camDims || !S.hasTick) drawBare(img, S);
    else C.renderConsole(img, S, {scanlines: true, contactLabel: 'SOL START'});   // S.now = start time of the sol, not a contact time
    if (pauseTitle(S) !== null) drawPause(img, S);
    else { var nt = nightText(S); if (nt) C.text(img, 8 + Math.floor((320 - C.textWidth(nt)) / 2), 24 + 100 + 12, nt, C.MARK, 1); }
    return img;
  }

  var api = {b64: b64, newView: newView, applyEvent: applyEvent, makeLimiter: makeLimiter, makeLink: makeLink, label: label, silentText: silentText, dataAgeS: dataAgeS, fmtDuration: fmtDuration, engineSilent: engineSilent,
             holdText: holdText, resumeText: resumeText, noImageText: noImageText, nextLeftS: nextLeftS, canDraw: canDraw, pauseTitle: pauseTitle, lineText: lineText, extraLabel: extraLabel, countLine: function (S, nowMs) { return markEngine(S, {e: '?'}, nowMs); },
             renderLive: renderLive, nightText: nightText, seasonText: seasonText, setConsole: function (c) { C = c; }, valText: valText, progressText: progressText,
             MIN_DRAW_MS: MIN_DRAW_MS, BUSY_POLL_MS: BUSY_POLL_MS, OFFLINE_RETRY_MS: OFFLINE_RETRY_MS, OPEN_TIMEOUT_MS: OPEN_TIMEOUT_MS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0Live = api;
})(typeof self !== 'undefined' ? self : this);
