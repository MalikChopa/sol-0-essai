/* Sol-0 live page: the « 3D » tab (out/vue3d/DESIGN.md, prototype out/vue3d/proto). Software renderer (palette indices, 320 px
   wide, scaled up crisp) of the page state S only (live.js: map, heights, relief). No terrain code: a cell never seen stays in the
   fog. World (x, y cells; h m) -> render (x, -y, h / cell_m), z up: the map's orientation. mount() = DOM, at the first opening. */
(function (root) {
  'use strict';
  // engine constants, checked by tests/page/view3d.test.js
  var P0 = {cell_m: 5, track: 0.5, eye_m: 2.0, fov_tan: 0.7, radius: [8, 8, 14, 24, 40, 40], v_max: 0.25, omega_max: 0.6,
            shade_flat: 0.5, relief_gain: 20.0, light_gain: 0.75, night_elev: 0.05, tip_roll: 0.58, tip_pitch: 0.70, tick_s: 72};
  var RAMP = [0, 6, 12, 12], SKY0 = 18, NIGHT_SKY = 22, NIGHT_GROUND = 23, FOG = 48, RED = 51, MARK = 63, SUN = 17;
  var WIN = 30, NEAR = 0.05, FOV_V = 40 * Math.PI / 180, DEG = Math.PI / 180;
  // body style (m): only the track (2.5 m) and the eye height (2 m) are real
  var BODY = {wheelR: 0.5, wheelW: 0.35, boxL: 1.8, boxW: 1.9, boxH: 0.6, boxZ: 0.35, panelL: 2.2, panelW: 1.6, armLen: 1.3};
  // side of u[k]'s wheel: u[0] = the (-s, c) side = the rover's right (SPEC §1, y south; MIRROR.md)
  var CMD_SIDE = [1, -1];
  var CAM_LIM = {orbit: {el: [10, 89], dist: [8, 200]}, behind: {dist: [8, 60]}, top: {side: [16, 400]}};
  var CAPS = {az: 120, el: 60, zoom: 2, follow: 45, lagS: 0.5};      // deg/s, deg/s, x per s, deg/s, s (DESIGN §8 R2, R6)

  function hud(n) { return 51 + Math.max(1, Math.min(10, n)); }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function mapKey(x, y) { return (x + 32768) * 65536 + (y + 32768); }        // = live.js
  function fin(v) { return typeof v === 'number' && isFinite(v); }
  function wrap(a) { a = (a + Math.PI) % (2 * Math.PI); if (a < 0) a += 2 * Math.PI; return a - Math.PI; }

  // ---- maths ----
  function toRender(x, y, hM, cm) { return [x, -y, hM / (cm || P0.cell_m)]; }
  // sd = [e, dx, dy] (world) -> L as camera.py, (dx, dy) renormalised; null if malformed
  function sunVector(sd) {
    if (!Array.isArray(sd) || sd.length < 3 || !fin(sd[0]) || !fin(sd[1]) || !fin(sd[2])) return null;
    var e = clamp(sd[0], 0, 1), n = Math.sqrt(sd[1] * sd[1] + sd[2] * sd[2]), sxy = Math.sqrt(Math.max(0, 1 - e * e));
    return n > 0.5 && n < 1.5 ? [sd[1] / n * sxy, sd[2] / n * sxy, e] : null;
  }
  // ground colour = CAM-1's formula (camera.py), no random part nor haze; g = gradient (m per cell)
  function groundIndex(type, gx, gy, L, e, P) {
    P = P || P0;
    if (!(type >= 0 && type <= 3)) return FOG;
    if (!L || !(e >= P.night_elev)) return NIGHT_GROUND;
    var nx = -gx / P.cell_m, ny = -gy / P.cell_m, np = (nx * L[0] + ny * L[1] + L[2]) / Math.sqrt(nx * nx + ny * ny + 1);
    var lam = clamp(P.shade_flat + P.relief_gain * (np - e), 0, 1);
    return RAMP[type] + clamp(Math.floor(5 * P.light_gain * e * (0.55 + 0.45 * lam) + 0.5), 0, 5);
  }
  // published heights (mapKey -> cm), bilinear as Window.height_at; null if one of the 4 is unknown
  function hAt(H, x, y) { var v = H.get(mapKey(x, y)); return v === undefined ? null : v / 100; }
  function heightAt(H, x, y) {
    if (!H) return null;
    var fx = Math.floor(x), fy = Math.floor(y), tx = x - fx, ty = y - fy;
    var a = hAt(H, fx, fy), b = hAt(H, fx + 1, fy), c = hAt(H, fx, fy + 1), d = hAt(H, fx + 1, fy + 1);
    if (a === null || b === null || c === null || d === null) return null;
    var p = a + (b - a) * tx;
    return p + (c + (d - c) * tx - p) * ty;
  }
  // slope as Window.gradient_at (±0.5 cell), m per cell; null if unknown
  function slopeAt(H, x, y) {
    var a = heightAt(H, x + 0.5, y), b = heightAt(H, x - 0.5, y), c = heightAt(H, x, y + 0.5), d = heightAt(H, x, y - 0.5);
    return (a === null || b === null || c === null || d === null) ? null : [a - b, c - d];
  }
  // mean of the published centres of the smallest square (1 to 3 cells around the nearest cell) that has any, or null
  function nearH(H, x, y) {
    for (var r = 1, i, j, a, s, n; r <= 3; r++) {
      for (s = n = 0, j = -r; j <= r; j++) for (i = -r; i <= r; i++) if ((a = hAt(H, Math.round(x) + i, Math.round(y) + j)) !== null) { s += a; n++; }
      if (n) return s / n;
    }
    return null;
  }
  function pitchRoll(g, c, s, cm) { return [(g[0] * c + g[1] * s) / cm, (-g[0] * s + g[1] * c) / cm]; }
  // the stream's pi, ro (previous tick's heading) -> gradient
  function gradFromTilt(pi, ro, c, s, cm) { return [(pi * c - ro * s) * cm, (pi * s + ro * c) * cm]; }
  // body frame (world cells): fwd, lat (the (−s, c) side), up; g = null: flat
  function bodyFrame(pose, g, cm) {
    cm = cm || P0.cell_m;
    var hn = Math.hypot(pose[2], pose[3]), c = pose[2] / hn, s = pose[3] / hn;
    var n = nrm(g ? [-g[0] / cm, -g[1] / cm, 1] : [0, 0, 1]), f = nrm([c, s, -(n[0] * c + n[1] * s) / n[2]]);
    return {fwd: f, lat: [n[1] * f[2] - n[2] * f[1], n[2] * f[0] - n[0] * f[2], n[0] * f[1] - n[1] * f[0]], up: n};
  }
  // real motion (m) of each side between two consecutive ticks (physics.py), or null for a jump: nothing guessed then
  function wheelStep(p0, p1, P) {
    P = P || P0;
    if (!p0 || !p1) return null;
    var dx = p1[0] - p0[0], dy = p1[1] - p0[1], v = dx * p1[2] + dy * p1[3], side = -dx * p1[3] + dy * p1[2];
    var w = wrap(Math.atan2(p1[3], p1[2]) - Math.atan2(p0[3], p0[2]));
    if (Math.abs(v) > 1.05 * P.v_max || Math.abs(w) > 1.05 * P.omega_max || Math.abs(side) > 0.01) return null;
    return {plus: (v - w * P.track / 2) * P.cell_m, minus: (v + w * P.track / 2) * P.cell_m, v: v, w: w};
  }

  // ---- mesh: the known cells of the 60 × 60 window (as the console's map), none other ----
  function meshFromCells(map, heights, cx, cy, relief) {
    var x0 = Math.floor(cx) - WIN, y0 = Math.floor(cy) - WIN, cells = [], waiting = 0, corner = new Map(), cm = P0.cell_m;
    function cornerH(x, y) { // corner (x + 0.5, y + 0.5): mean of the published centres around it
      var k = mapKey(x, y), v = corner.get(k), s = 0, n = 0, a, i, j;
      if (v !== undefined) return v;
      for (j = 0; j <= 1; j++) for (i = 0; i <= 1; i++) { a = hAt(heights, x + i, y + j); if (a !== null) { s += a; n++; } }
      corner.set(k, v = n ? s / n : null);
      return v;
    }
    function nb(x, y, h) { var v = hAt(heights, x, y); return v === null ? h : v; }
    for (var yy = y0; yy < y0 + 2 * WIN; yy++) for (var xx = x0; xx < x0 + 2 * WIN; xx++) {
      var g = map.get(mapKey(xx, yy));
      if (!(g >= 1 && g <= 4)) continue;
      var c = {x: xx, y: yy, g: g - 1, h: 0, gx: 0, gy: 0};
      if (relief) { // no published height yet: in the fog
        var h = hAt(heights, xx, yy);
        if (h === null) { waiting++; continue; }
        c.h = h; c.gx = (nb(xx + 1, yy, h) - nb(xx - 1, yy, h)) * 0.5; c.gy = (nb(xx, yy + 1, h) - nb(xx, yy - 1, h)) * 0.5;
      }
      cells.push(c);
    }
    var per = relief ? 4 : 2, tri = new Float64Array(cells.length * per * 9), cell = new Int32Array(cells.length * per), t = 0;
    function put(i, ax, ay, ah, bx, by, bh, qx, qy, qh) {
      var o = t * 9;
      tri[o] = ax; tri[o + 1] = -ay; tri[o + 2] = ah / cm; tri[o + 3] = bx; tri[o + 4] = -by; tri[o + 5] = bh / cm;
      tri[o + 6] = qx; tri[o + 7] = -qy; tri[o + 8] = qh / cm; cell[t++] = i;
    }
    cells.forEach(function (q, i) {     // a cell covers [k - 0.5, k + 0.5[ (chunks.gtype_at)
      var L = q.x - 0.5, R = q.x + 0.5, T = q.y - 0.5, B = q.y + 0.5;
      if (!relief) { put(i, L, T, 0, R, T, 0, R, B, 0); put(i, L, T, 0, R, B, 0, L, B, 0); return; }
      var hLT = cornerH(q.x - 1, q.y - 1), hRT = cornerH(q.x, q.y - 1), hRB = cornerH(q.x, q.y), hLB = cornerH(q.x - 1, q.y);
      put(i, q.x, q.y, q.h, L, T, hLT, R, T, hRT); put(i, q.x, q.y, q.h, R, T, hRT, R, B, hRB);
      put(i, q.x, q.y, q.h, R, B, hRB, L, B, hLB); put(i, q.x, q.y, q.h, L, B, hLB, L, T, hLT);
    });
    return {x0: x0, y0: y0, cells: cells, tri: tri, cell: cell, n: t, relief: !!relief, waiting: waiting, cornerH: cornerH};
  }
  function shadeMesh(mesh, L, e, P) { return Uint8Array.from(mesh.cells, function (c) { return groundIndex(c.g, c.gx, c.gy, L, e, P); }); }

  // ---- spectator camera: aimed at the rover, never a roll ----
  function camDefault(pose) { return {mode: 'orbit', az: Math.atan2(-pose[3], pose[2]) + Math.PI + 35 * DEG, el: 30 * DEG, dist: 25, side: 50}; }
  function clampCam(c) {
    return {mode: c.mode, az: wrap(c.az), el: clamp(c.el, CAM_LIM.orbit.el[0] * DEG, CAM_LIM.orbit.el[1] * DEG),
            dist: clamp(c.dist, CAM_LIM.orbit.dist[0], c.mode === 'behind' ? CAM_LIM.behind.dist[1] : CAM_LIM.orbit.dist[1]),
            side: clamp(c.side, CAM_LIM.top.side[0], CAM_LIM.top.side[1])};
  }
  // one step towards b within the speed caps (R2)
  function stepCam(a, b, dt) {
    var m = CAPS.az * DEG * dt, r = Math.pow(CAPS.zoom, dt), o = {mode: b.mode, az: wrap(a.az + clamp(wrap(b.az - a.az), -m, m))};
    m = CAPS.el * DEG * dt; o.el = a.el + clamp(b.el - a.el, -m, m);
    o.dist = clamp(b.dist, a.dist / r, a.dist * r); o.side = clamp(b.side, a.side / r, a.side * r);
    return o;
  }
  function settled(a, b) { return Math.abs(wrap(a.az - b.az)) < 1e-4 && Math.abs(a.el - b.el) < 1e-4 && Math.abs(a.dist / b.dist - 1) < 1e-4 && Math.abs(a.side / b.side - 1) < 1e-4; }
  function nrm(v) { var n = Math.hypot(v[0], v[1], v[2]); return [v[0] / n, v[1] / n, v[2] / n]; }
  function viewOf(cam, tg, W, H) {
    var eye, fw, rt, up, cm = P0.cell_m;
    if (cam.mode === 'top') { eye = [tg[0], tg[1], tg[2] + cam.side / 2 / Math.tan(FOV_V / 2) / cm]; fw = [0, 0, -1]; rt = [1, 0, 0]; up = [0, 1, 0]; }
    else {
      var el = cam.mode === 'behind' ? Math.atan2(6, 15) : cam.el, dd = cam.dist / cm, ce = Math.cos(el);
      eye = [tg[0] + dd * ce * Math.cos(cam.az), tg[1] + dd * ce * Math.sin(cam.az), tg[2] + dd * Math.sin(el)];
      fw = nrm([tg[0] - eye[0], tg[1] - eye[1], tg[2] - eye[2]]); rt = nrm([fw[1], -fw[0], 0]);
      up = [rt[1] * fw[2] - rt[2] * fw[1], rt[2] * fw[0] - rt[0] * fw[2], rt[0] * fw[1] - rt[1] * fw[0]];
    }
    return {eye: eye, fw: fw, rt: rt, up: up, f: (H / 2) / Math.tan(FOV_V / 2), W: W, H: H, target: tg};
  }
  function toCam(v, p) {
    var dx = p[0] - v.eye[0], dy = p[1] - v.eye[1], dz = p[2] - v.eye[2];
    return [dx * v.rt[0] + dy * v.rt[1] + dz * v.rt[2], dx * v.up[0] + dy * v.up[1] + dz * v.up[2], dx * v.fw[0] + dy * v.fw[1] + dz * v.fw[2]];
  }
  function scr(v, c) { return [v.W / 2 + v.f * c[0] / c[2], v.H / 2 - v.f * c[1] / c[2], 1 / c[2]]; }
  function project(v, p) { var c = toCam(v, p); return c[2] < NEAR ? null : scr(v, c); }

  // ---- rasteriser: palette indices + 1/z buffer ----
  function makeTarget(W, H) { return {W: W, H: H, img: new Uint8Array(W * H), z: new Float32Array(W * H)}; }
  function fillTri(T, a, b, c, col, bias) { // [sx, sy, 1/z]; pixel centres
    var W = T.W, area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]), tmp;
    if (!(Math.abs(area) > 1e-12)) return;
    if (area < 0) { tmp = b; b = c; c = tmp; area = -area; }
    var x0 = Math.max(0, Math.floor(Math.min(a[0], b[0], c[0]))), x1 = Math.min(W - 1, Math.ceil(Math.max(a[0], b[0], c[0])));
    var y0 = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1]))), y1 = Math.min(T.H - 1, Math.ceil(Math.max(a[1], b[1], c[1])));
    var A0 = b[1] - c[1], B0 = c[0] - b[0], A1 = c[1] - a[1], B1 = a[0] - c[0], A2 = a[1] - b[1], B2 = b[0] - a[0];
    var inv = 1 / area, zb = 1 + (bias || 0), img = T.img, zz = T.z;
    for (var y = y0; y <= y1; y++) {
      var py = y + 0.5, px = x0 + 0.5;
      var w0 = A0 * (px - b[0]) + B0 * (py - b[1]), w1 = A1 * (px - c[0]) + B1 * (py - c[1]), w2 = A2 * (px - a[0]) + B2 * (py - a[1]);
      for (var x = x0, i = y * W + x0; x <= x1; x++, i++, w0 += A0, w1 += A1, w2 += A2) {
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        var iz = (w0 * a[2] + w1 * b[2] + w2 * c[2]) * inv * zb;
        if (iz > zz[i]) { zz[i] = iz; img[i] = col; }
      }
    }
  }
  function drawTri(T, v, p, q, r, col, bias) {    // render points, clipped against the near plane
    var pts = [toCam(v, p), toCam(v, q), toCam(v, r)], out = [], k;
    for (k = 0; k < 3; k++) {
      var P = pts[k], Q = pts[(k + 1) % 3], pin = P[2] >= NEAR;
      if (pin) out.push(P);
      if (pin !== (Q[2] >= NEAR)) { var t = (NEAR - P[2]) / (Q[2] - P[2]); out.push([P[0] + (Q[0] - P[0]) * t, P[1] + (Q[1] - P[1]) * t, NEAR]); }
    }
    for (k = 0; k < out.length; k++) out[k] = scr(v, out[k]);
    for (k = 1; k + 1 < out.length; k++) fillTri(T, out[0], out[k], out[k + 1], col, bias);
  }
  function putPx(T, x, y, iz, col, bias) {
    if (x < 0 || y < 0 || x >= T.W || y >= T.H) return;
    var i = y * T.W + x, z = iz * (1 + bias);
    if (z >= T.z[i]) { T.img[i] = col; T.z[i] = z; }
  }
  // polyline (a null breaks it), depth interpolated, a small bias forward
  function polyline(T, v, pts, col, bias) {
    var prev = null;
    pts.forEach(function (q) {
      var p = q ? project(v, q) : null;
      if (p && prev) seg(T, prev, p, col, bias); else if (p) putPx(T, Math.floor(p[0]), Math.floor(p[1]), p[2], col, bias);
      prev = p;
    });
  }
  function seg(T, a, b, col, bias) {
    var x0 = Math.floor(a[0]), y0 = Math.floor(a[1]), x1 = Math.floor(b[0]), y1 = Math.floor(b[1]), n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
    if (n > 4 * (T.W + T.H)) return;
    for (var i = 0; i <= n; i++) { var t = n ? i / n : 0; putPx(T, Math.round(x0 + (x1 - x0) * t), Math.round(y0 + (y1 - y0) * t), a[2] + (b[2] - a[2]) * t, col, bias); }
  }

  // ---- scene ----
  // a ground point for markers (null where the relief is unknown: not drawn)
  function gp(sc, x, y, lift) { var h = sc.relief ? heightAt(sc.heights, x, y) : 0; return h === null ? null : [x, -y, h / P0.cell_m + (lift || 0)]; }
  function groundLine(sc, x0, y0, x1, y1) {
    var n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 0.25)), pts = [];
    for (var i = 0; i <= n; i++) pts.push(gp(sc, x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, 0.01));
    return pts;
  }
  // body coordinates (m): forward, lat, up; origin on the ground under the centre
  function boxFaces(f0, f1, l0, l1, u0, u1) {
    var c = function (i, j, k) { return [[f0, f1][i], [l0, l1][j], [u0, u1][k]]; };
    return [[c(0, 0, 1), c(1, 0, 1), c(1, 1, 1), c(0, 1, 1)], [c(0, 0, 0), c(0, 1, 0), c(1, 1, 0), c(1, 0, 0)],
            [c(1, 0, 0), c(1, 1, 0), c(1, 1, 1), c(1, 0, 1)], [c(0, 0, 0), c(0, 0, 1), c(0, 1, 1), c(0, 1, 0)],
            [c(0, 1, 0), c(0, 1, 1), c(1, 1, 1), c(1, 1, 0)], [c(0, 0, 0), c(1, 0, 0), c(1, 0, 1), c(0, 0, 1)]];
  }
  function wheelFaces(side, ang) { // 8 facets + one mark
    var B = BODY, lc = side * P0.track * P0.cell_m / 2, l0 = lc - B.wheelW / 2, l1 = lc + B.wheelW / 2, rim = [], faces = [], k, R = B.wheelR;
    for (k = 0; k < 8; k++) rim.push([R * Math.cos(ang + k * Math.PI / 4), R + R * Math.sin(ang + k * Math.PI / 4)]);
    for (k = 0; k < 8; k++) { var p = rim[k], q = rim[(k + 1) % 8]; faces.push([[p[0], l0, p[1]], [q[0], l0, q[1]], [q[0], l1, q[1]], [p[0], l1, p[1]]]); }
    faces.push(rim.map(function (r) { return [r[0], l0, r[1]]; }), rim.map(function (r) { return [r[0], l1, r[1]]; }).reverse());
    var lo = side > 0 ? l1 + 0.01 : l0 - 0.01;
    return {faces: faces, mark: [[0, lo, R], [R * 0.95 * Math.cos(ang), lo, R + R * 0.95 * Math.sin(ang)]]};
  }
  // o: {trail, cone, wheel, prevPose, lastAlt, prevU, lab (u[0], u[1]), font}; relief only with S.relief (a valid lmh of this sol)
  function buildScene(S, o) {
    o = o || {};
    var pose = S.pose, cm = P0.cell_m, ev = S.events, relief = !!(S.relief && S.heights && S.heights.size);
    var sc = {relief: relief, heights: S.heights || null, pose: pose, map: S.map, stage: S.stage | 0, t: S.t, mode: S.mode,
              flags: {tipped: !!S.tipped, locked: !!S.locked}, u: o.prevU || null, target: S.target, path: S.path || [],
              showTrail: o.trail !== false, showCone: o.cone !== false, viewScale: (ev && fin(ev.view_scale)) ? ev.view_scale : 1,
              wheel: o.wheel || [0, 0], pitch: S.pitch, roll: S.roll, lab: o.lab, font: o.font};
    sc.L = sunVector(S.sunVec); sc.e = sc.L ? sc.L[2] : 0; sc.night = !sc.L || sc.e < P0.night_elev;
    // on the relief: published heights at the pose, else the last altitude (else the nearest published ones) and the stream's tilt;
    // none within 3 cells (a new visitor): drawn flat, never an invented altitude (VERIF-PAGE I1)
    var g = null, src = 'flat', h = relief ? heightAt(sc.heights, pose[0], pose[1]) : null, sl, pp = o.prevPose;
    if (h !== null) src = 'relief';
    else if (relief && (h = fin(o.lastAlt) ? o.lastAlt : nearH(sc.heights, pose[0], pose[1])) !== null) src = 'pending';
    if (h === null) sc.relief = false;
    else if ((sl = slopeAt(sc.heights, pose[0], pose[1]))) g = sl;
    else if (pp && fin(S.pitch) && fin(S.roll)) { g = gradFromTilt(S.pitch, S.roll, pp[2], pp[3], cm); src = 'pending'; }
    sc.alt = h || 0; sc.altSrc = src; sc.frame = bodyFrame(pose, g, cm);
    return sc;
  }
  function bodyPoint(sc, b) {          // body coordinates (m) -> render point
    var F = sc.frame, cm = P0.cell_m, f = function (j) { return (b[0] * F.fwd[j] + b[1] * F.lat[j] + b[2] * F.up[j]) / cm; };
    return [sc.pose[0] + f(0), -(sc.pose[1] + f(1)), sc.alt / cm + f(2)];
  }
  // body face shading (style): 0.35 + 0.65·max(0, n·L), 6 levels; night: tops hud(2), sides 22
  function faceCol(sc, pts, ramp, dark, ctr) {
    var a = pts[0], b = pts[1], c = pts[2], ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    var n = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx], nn = Math.hypot(n[0], n[1], n[2]) || 1, m = [0, 0, 0], k, j;
    for (k = 0; k < pts.length; k++) for (j = 0; j < 3; j++) m[j] += pts[k][j] / pts.length;
    if ((m[0] - ctr[0]) * n[0] + (m[1] - ctr[1]) * n[1] + (m[2] - ctr[2]) * n[2] < 0) nn = -nn;
    if (sc.night) return n[2] / nn > 0.5 ? hud(2) : NIGHT_SKY;
    return ramp + clamp(Math.floor(6 * (0.35 + 0.65 * Math.max(0, (n[0] * sc.L[0] - n[1] * sc.L[1] + n[2] * sc.L[2]) / nn))) - (dark ? 2 : 0), 0, 5);
  }
  function drawFaces(T, v, sc, faces, ramp, dark, ctrBody) {
    var ctr = bodyPoint(sc, ctrBody);
    faces.forEach(function (fc) {
      var f = fc.map(function (b) { return bodyPoint(sc, b); }), col = faceCol(sc, f, ramp, dark, ctr);
      for (var k = 1; k + 1 < f.length; k++) drawTri(T, v, f[0], f[k], f[k + 1], col, 0);
    });
  }
  function boxPart(T, v, sc, f0, f1, l0, l1, u0, u1, ramp, dark) { drawFaces(T, v, sc, boxFaces(f0, f1, l0, l1, u0, u1), ramp, dark, [(f0 + f1) / 2, (l0 + l1) / 2, (u0 + u1) / 2]); }
  function drawBody(T, v, sc) {
    var B = BODY, hl = B.boxL / 2, hw = B.boxW / 2, E = P0.eye_m, pz = B.boxZ + B.boxH + 0.02, k, bp = function (b) { return bodyPoint(sc, b); };
    boxPart(T, v, sc, -hl, hl, -hw, hw, B.boxZ, B.boxZ + B.boxH, 12, false);                              // box
    boxPart(T, v, sc, -B.panelL / 2, B.panelL / 2, -B.panelW / 2, B.panelW / 2, pz, pz + 0.05, 0, false);    // panel, parallel to the body
    boxPart(T, v, sc, hl - 0.3, hl - 0.16, -0.07, 0.07, pz, E - 0.2, 12, true);                         // mast
    boxPart(T, v, sc, hl - 0.45, hl - 0.05, -0.2, 0.2, E - 0.2, E + 0.2, 12, false);                    // head: the eye at 2 m (real)
    var lens = [[hl - 0.04, -0.1, E - 0.08], [hl - 0.04, 0.1, E - 0.08], [hl - 0.04, 0.1, E + 0.08], [hl - 0.04, -0.1, E + 0.08]].map(bp), lc = sc.night ? hud(8) : MARK;
    drawTri(T, v, lens[0], lens[1], lens[2], lc, 0.002); drawTri(T, v, lens[0], lens[2], lens[3], lc, 0.002);
    if (sc.stage >= 4) { // arm (style), unfolded in DRILL
      var tip = bp(sc.mode === 'DRILL' ? [hl + B.armLen - 0.9, 0.35, 0.02] : [hl + 0.08, 0.35, B.boxZ + 0.05]), tp = project(v, tip);
      polyline(T, v, [bp([hl, 0.35, B.boxZ + B.boxH - 0.1]), tip], sc.night ? hud(4) : 14, 0.004);
      if (tp) putPx(T, Math.floor(tp[0]), Math.floor(tp[1]), tp[2], sc.flags.locked ? RED : hud(9), 0.01);
    }
    for (k = 0; k < 2; k++) {
      var side = CMD_SIDE[k], wf = wheelFaces(side, sc.wheel[k]);
      drawFaces(T, v, sc, wf.faces, 12, true, [0, side * P0.track * P0.cell_m / 2, B.wheelR]);
      polyline(T, v, wf.mark.map(bp), sc.night ? hud(6) : 17, 0.004);
      // the command that made this step (u of the previous tick, VERIF-PAGE I2): an arrow beside the wheel, dim if ignored (asleep)
      if (!sc.u) continue;
      var u = fin(sc.u.u[k]) ? clamp(sc.u.u[k], -1, 1) : 0, ls = side * (P0.track * P0.cell_m / 2 + 0.45), len = 1.6 * u;
      var col = sc.u.z ? hud(2) : hud(8), a1 = bp([len, ls, 0.05]), sg = len > 0 ? 0.35 : -0.35;
      polyline(T, v, [bp([0, ls, 0.05]), a1], col, 0.01);
      if (Math.abs(len) > 0.15) polyline(T, v, [bp([len - sg, ls - 0.25, 0.05]), a1, bp([len - sg, ls + 0.25, 0.05])], col, 0.01);
    }
    // the console's letter beside each wheel, unless its foot is hidden (brief 56)
    for (k = 0; k < 2 && sc.lab; k++) letter(T, project(v, bp([0, CMD_SIDE[k] * (P0.track * P0.cell_m / 2 + 1.1), 0.05])), sc.lab[k], sc.font);
  }
  function letter(T, q, s, F) { // console font, centred on q
    var h = q && F && s && F[s.charCodeAt(0) - 32], x = q && Math.round(q[0]) - 2, y = q && Math.round(q[1]) - 3, i;
    if (h && x >= 0 && y >= 0 && x + 5 <= T.W && y + 7 <= T.H && q[2] * 1.01 >= T.z[(y + 3) * T.W + x + 2])
      for (i = 0; i < 35; i++) if (parseInt(h.substr(i / 7 << 1, 2), 16) >> i % 7 & 1) T.img[(y + i % 7) * T.W + x + (i / 7 | 0)] = hud(9);
  }
  function drawMarkers(T, v, sc) {
    var p = sc.pose, k, ft = P0.fov_tan, ln = function (a, b, c, d, col, bias) { polyline(T, v, groundLine(sc, a, b, c, d), col, bias); };
    if (sc.showCone) { // CAM-1's footprint (camera.py)
      var R = P0.radius[clamp(sc.stage, 0, 5)] * sc.viewScale, c = p[2], s = p[3];
      var ax = p[0] + R * (c - s * ft), ay = p[1] + R * (s + c * ft), bx = p[0] + R * (c + s * ft), by = p[1] + R * (s - c * ft);
      ln(p[0], p[1], ax, ay, hud(4), 0.004); ln(p[0], p[1], bx, by, hud(4), 0.004); ln(ax, ay, bx, by, hud(4), 0.004);
    }
    if (sc.night) sc.mesh.cells.forEach(function (q) { // night: soil borders (guides)
      var r = sc.map.get(mapKey(q.x + 1, q.y)), d = sc.map.get(mapKey(q.x, q.y + 1));
      if (r !== undefined && r - 1 !== q.g) ln(q.x + 0.5, q.y - 0.5, q.x + 0.5, q.y + 0.5, hud(2), 0.003);
      if (d !== undefined && d - 1 !== q.g) ln(q.x - 0.5, q.y + 0.5, q.x + 0.5, q.y + 0.5, hud(2), 0.003);
    });
    if (sc.showTrail) sc.path.forEach(function (q) {
      var tp = gp(sc, q[0], q[1], 0.01), pp = tp && project(v, tp);
      if (pp) { var x = Math.floor(pp[0]), y = Math.floor(pp[1]); putPx(T, x, y, pp[2], hud(6), 0.004); if (pp[2] > 0.15) putPx(T, x + 1, y, pp[2], hud(6), 0.004); }
    });
    var tg = sc.target, ring = [];
    if (tg && fin(tg[0]) && fin(tg[1])) {
      for (k = 0; k <= 24; k++) ring.push(gp(sc, tg[0] + 0.6 * Math.cos(k * Math.PI / 12), tg[1] + 0.6 * Math.sin(k * Math.PI / 12), 0.01));
      polyline(T, v, ring, MARK, 0.004);
      ln(tg[0] - 0.9, tg[1], tg[0] + 0.9, tg[1], MARK, 0.004); ln(tg[0], tg[1] - 0.9, tg[0], tg[1] + 0.9, MARK, 0.004);
    }
  }
  function horizonRow(v) { var hz = Math.hypot(v.fw[0], v.fw[1]); return hz < 1e-9 ? -Infinity : v.H / 2 + v.f * v.fw[2] / hz; }   // no roll
  function drawOverlays(T, v, sc) {
    var W = T.W, H = T.H, img = T.img, k, out = {};
    function px(x, y, c) { if (x >= 0 && y >= 0 && x < W && y < H) img[y * W + x] = c; }
    function ln(x0, y0, x1, y1, c) { var n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)); for (var i = 0; i <= n; i++) { var t = n ? i / n : 0; px(Math.round(x0 + (x1 - x0) * t), Math.round(y0 + (y1 - y0) * t), c); } }
    // tilt gauges: the real atan(pi), atan(ro); red beyond the tip limits; a dash at tick 0
    var gs = [[sc.pitch, P0.tip_pitch], [sc.roll, P0.tip_roll]];
    for (k = 0; k < 2; k++) {
      var x0 = 4 + k * 20, y0 = H - 20, cx = x0 + 8, cy = y0 + 8, tv = gs[k][0], c3 = hud(3);
      ln(x0, y0, x0 + 16, y0, c3); ln(x0, y0 + 16, x0 + 16, y0 + 16, c3); ln(x0, y0, x0, y0 + 16, c3); ln(x0 + 16, y0, x0 + 16, y0 + 16, c3);
      if (sc.t === 0 || !fin(tv)) { ln(cx - 3, cy, cx + 3, cy, c3); continue; }
      var a = Math.atan(tv), dx = Math.cos(a) * 6, dy = Math.sin(a) * 6;
      ln(Math.round(cx - dx), Math.round(cy + dy), Math.round(cx + dx), Math.round(cy - dy), (Math.abs(tv) > gs[k][1] || sc.flags.tipped) ? RED : hud(8));
    }
    // +y arrow and a scale bar at the rover's distance
    var t0 = v.target, a0 = project(v, t0), a1 = project(v, [t0[0], t0[1] - 1, t0[2]]);
    if (a0 && a1) {
      var ddx = a1[0] - a0[0], ddy = a1[1] - a0[1], dn = Math.hypot(ddx, ddy), ppm = v.f * a0[2] / P0.cell_m, m = 200, steps = [1, 2, 5, 10, 20, 50, 100, 200];
      if (dn > 1e-6) { var ex = Math.round(W - 14 + 7 * ddx / dn), ey = Math.round(H - 12 + 7 * ddy / dn); ln(W - 14, H - 12, ex, ey, hud(6)); px(ex, ey, MARK); }
      for (k = 0; k < steps.length; k++) if (steps[k] * ppm >= 16) { m = steps[k]; break; }
      var L = Math.round(m * ppm), bx = W - 28 - L, by = H - 6;
      if (L >= 4 && L <= W / 2) { ln(bx, by, bx + L, by, hud(6)); ln(bx, by - 2, bx, by, hud(6)); ln(bx + L, by - 2, bx + L, by, hud(6)); out.scaleM = m; }
    }
    return out;
  }
  // a frame: sc = buildScene() + mesh, col
  function raster(sc, cam, T) {
    var W = T.W, H = T.H, img = T.img, k, i, y, v = viewOf(cam, bodyPoint(sc, [0, 0, 1.0]), W, H), hr = horizonRow(v), m = sc.mesh, tri = m.tri;
    T.z.fill(0);
    for (y = 0; y < H; y++) img.fill(y + 0.5 < hr ? (sc.night ? NIGHT_SKY : SKY0 + Math.min(3, Math.floor(4 * Math.max(0, hr - y) / Math.max(1, hr)))) : FOG, y * W, (y + 1) * W);
    if (!sc.night) { // the sun, in the sky only
      var L = sc.L, sp = project(v, [v.eye[0] + L[0] * 1e4, v.eye[1] - L[1] * 1e4, v.eye[2] + L[2] * 1e4]);
      if (sp && sp[1] < hr) for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
        var sx = Math.floor(sp[0]) + dx, sy = Math.floor(sp[1]) + dy;
        if (sx >= 0 && sy >= 0 && sx < W && sy < H && sy + 0.5 < hr) img[sy * W + sx] = SUN;
      }
    }
    for (k = 0; k < m.n; k++) { i = k * 9; drawTri(T, v, [tri[i], tri[i + 1], tri[i + 2]], [tri[i + 3], tri[i + 4], tri[i + 5]], [tri[i + 6], tri[i + 7], tri[i + 8]], sc.col[m.cell[k]], 0); }
    drawMarkers(T, v, sc);
    drawBody(T, v, sc);
    return {view: v, horizon: hr, scaleM: drawOverlays(T, v, sc).scaleM || null};
  }

  // ---- EF-87: port of render/photosens.py ----
  function root5(y) { var lo = 0, hi = 1; for (var i = 0; i < 60; i++) { var m = (lo + hi) * 0.5; if (m * m * m * m * m < y) lo = m; else hi = m; } return (lo + hi) * 0.5; }
  function lin(c8) { var c = c8 / 255.0; if (c <= 0.04045) return c / 12.92; var b = (c + 0.055) / 1.055, b2 = b * b, b4 = b2 * b2; return root5(b4 * b4 * b4); }
  function lumTable(pal) { return pal.map(function (h) { return 0.2126 * lin(parseInt(h.substr(1, 2), 16)) + 0.7152 * lin(parseInt(h.substr(3, 2), 16)) + 0.0722 * lin(parseInt(h.substr(5, 2), 16)); }); }
  function isTransition(a, b, lum) {
    var n = 0;
    for (var i = 0; i < a.length; i++) { var x = lum[a[i]], y = lum[b[i]]; if (Math.abs(x - y) >= 0.1 && Math.min(x, y) < 0.8) n++; }
    return n * 4 >= a.length;
  }
  // a 4th transition in 1 s waits (the latest frame only) until the window allows
  function makeFlashGuard(o) {
    var last = null, times = [], pending = null, timer = null, shown = 0, held = 0;
    function attempt() {
      timer = null;
      if (!pending) return;
      var now = o.now(), f = pending;
      if (last && f.length === last.length && isTransition(last, f, o.lum)) {
        times = times.filter(function (t) { return t > now - 1000; });
        if (times.length >= 3) { held++; timer = o.setTimer(attempt, Math.max(1, times[0] + 1000 - now)); return; }
        times.push(now);
      }
      pending = null; last = f; shown++; o.show(f, now);
    }
    return {offer: function (frame) { pending = new Uint8Array(frame); if (timer === null) attempt(); }, stats: function () { return {shown: shown, held: held}; }};
  }

  // ---- texts (DOM; tt = i18n.json) ----
  function soilShares(map, cx, cy) {
    var n = [0, 0, 0, 0], tot = 0, x0 = Math.floor(cx) - WIN, y0 = Math.floor(cy) - WIN;
    for (var y = y0; y < y0 + 2 * WIN; y++) for (var x = x0; x < x0 + 2 * WIN; x++) { var g = map.get(mapKey(x, y)); if (g >= 1 && g <= 4) { n[g - 1]++; tot++; } }
    return {n: n, tot: tot};
  }
  // « Describe the scene », from S only
  function describe(S, tt, act, flat) {
    if (!S.hasTick) return tt('d.v3.wait');
    var p = S.pose, a = [tt('d.v3.s.act', {a: act})], tg = S.target, L = sunVector(S.sunVec), sh = soilShares(S.map, p[0], p[1]), ss = [], k;
    if (tg && fin(tg[0]) && fin(tg[1])) {
      var dx = tg[0] - p[0], dy = tg[1] - p[1], fw = dx * p[2] + dy * p[3], lt = -dx * p[3] + dy * p[2];
      a.push(tt('d.v3.s.target', {d: Math.round(Math.hypot(dx, dy) * P0.cell_m), w: tt(fw >= 0 ? 'd.v3.s.ahead' : 'd.v3.s.behind') +
        (Math.abs(lt) > 0.2 * Math.abs(fw) ? tt(lt > 0 ? 'd.v3.s.right' : 'd.v3.s.left') : '')}));
    }
    a.push(!L || L[2] < P0.night_elev ? tt('d.v3.s.night') : tt('d.v3.s.day', {e: Math.round(Math.asin(L[2]) / DEG)}));
    for (k = 0; k < 4; k++) if (sh.n[k]) ss.push(Math.round(100 * sh.n[k] / sh.tot) + ' % ' + tt('d.v3.soil' + k));
    if (ss.length) a.push(tt('d.v3.s.soils', {l: ss.join(', ')}));
    if (S.t === 0) a.push(tt('d.v3.s.reset'));
    else if (fin(S.pitch) && fin(S.roll)) a.push(tt('d.v3.tilt', {p: Math.round(Math.atan(S.pitch) / DEG), r: Math.round(Math.atan(S.roll) / DEG)}));
    a.push(tt(S.relief && !flat ? 'd.v3.s.relief' : 'd.v3.s.flat'));
    var s = a.join(tt('d.v3.s.sep')) + '.';
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ---- DOM glue (browser only) ----
  function advanceWheels(wheel, ws) { for (var k = 0; k < 2; k++) wheel[k] -= (CMD_SIDE[k] > 0 ? ws.plus : ws.minus) / BODY.wheelR; return wheel; }
  function toOrbit(c) { // without a jump
    return c.mode === 'orbit' ? c : clampCam(c.mode === 'top' ? {mode: 'orbit', az: c.az, el: 89 * DEG, dist: c.side / 2 / Math.tan(FOV_V / 2), side: c.side}
                                                              : {mode: 'orbit', az: c.az, el: Math.atan2(6, 15), dist: c.dist, side: c.side});
  }
  // o: {$, tt, palette, reduced, now, visible(), off(), act(S), mode(m), dec()}
  function mount(o) {
    var $ = o.$, cv = $('v3-c'), st = $('v3-stage'), ctx = cv.getContext('2d'), rgba = Uint32Array.from(o.palette, function (h) {
      return (255 << 24 | parseInt(h.substr(5, 2), 16) << 16 | parseInt(h.substr(3, 2), 16) << 8 | parseInt(h.substr(1, 2), 16)) >>> 0; });
    var W = 320, H = 180, T = makeTarget(W, H), imgData = null, cw = -1, ch = -1, small = false, times = [], tt = o.tt;
    var S = null, meshKey = '', mesh = null, col = null, colSd = null, want = null, shown = null, trail = true, cone = true, reduced = !!o.reduced;
    var raf = null, lastMs = 0, drag = null, wheel = [0, 0], prevPose = null, lastPose = null, prevU = null, lastU = null, lastT = null, lastSol = null, lastAlt = null, info = {}, ann = null;
    var guard = makeFlashGuard({lum: lumTable(o.palette), now: o.now, setTimer: function (f, ms) { return setTimeout(f, ms); }, show: function (f) {
      if (f.length !== W * H) return;
      if (!imgData || imgData.width !== W || imgData.height !== H) imgData = ctx.createImageData(W, H);
      var u = new Uint32Array(imgData.data.buffer);
      for (var i = 0; i < f.length; i++) u[i] = rgba[f[i]];
      ctx.putImageData(imgData, 0, 0);
    }});
    // 320 wide (240 if slow), height from the box (120..240), integer scale
    function fit() {
      var dpr = self.devicePixelRatio || 1, nh = clamp(Math.round(W * (ch || 180) / (cw || 320)), 120, 240);
      if (nh !== H || cv.width !== W) { H = nh; T = makeTarget(W, H); cv.width = W; cv.height = H; }
      var s = Math.max(1, Math.floor(Math.min(cw * dpr / W, ch * dpr / H)) || 1);
      cv.style.width = (W * s / dpr) + 'px'; cv.style.height = (H * s / dpr) + 'px';
    }
    function draw() {
      if (!o.visible() || !S) return;
      if (S.hasTick && !o.off()) {
        if (st.clientWidth !== cw || st.clientHeight !== ch) { cw = st.clientWidth; ch = st.clientHeight; fit(); }
        var sc = buildScene(S, {trail: trail, cone: cone, wheel: wheel, prevPose: prevPose, lastAlt: lastAlt, prevU: prevU, lab: [tt('c.brain.out.r'), tt('c.brain.out.l')], font: o.font});
        var key = [Math.floor(S.pose[0]), Math.floor(S.pose[1]), S.map.size, sc.relief ? S.heights.size : -1, S.sol].join();
        if (key !== meshKey) { mesh = meshFromCells(S.map, sc.relief ? S.heights : null, S.pose[0], S.pose[1], sc.relief); meshKey = key; col = null; }
        if (!col || colSd !== S.sunVec) { col = shadeMesh(mesh, sc.L, sc.e); colSd = S.sunVec; }
        sc.mesh = mesh; sc.col = col;
        if (sc.altSrc === 'relief') lastAlt = sc.alt;
        if (!shown) shown = want = clampCam(camDefault(S.pose));
        var t0 = o.now(), r = raster(sc, shown, T);
        // DESIGN §7.3: median > 20 ms on 10 frames -> 240 px, once
        times.push(o.now() - t0); if (times.length > 10) times.shift();
        if (!small && times.length === 10 && times.slice().sort(function (a, b) { return a - b; })[5] > 20) { small = true; W = 240; cw = -1; }
        info = {relief: sc.relief, altSrc: sc.altSrc, alt: sc.alt, u: sc.u, waiting: mesh.waiting, scaleM: r.scaleM, night: sc.night};
        guard.offer(T.img);
      }
      texts();
    }
    function dec(v, d) { var s = v.toFixed(d); return o.dec() === ',' ? s.replace('.', ',') : s; }
    // DOM texts; the live region speaks of changes only
    function texts() {
      var r = !!(S && S.relief && info.relief !== false), md = S ? o.mode(S.mode) : '', a = [], f = [], p, hh, mm, live = !!(S && S.hasTick) && !o.off();
      cv.hidden = !live; $('v3-wait').hidden = live;
      $('v3-wait').textContent = tt(o.off() ? 'd.v3.off' : 'd.v3.wait');
      $('v3-badge').textContent = tt(r ? 'd.v3.badge.relief' : 'd.v3.badge.flat');
      [['v3-stage', 'n.v3.aria'], ['v3-c', 'n.v3.img'], ['v3-in', 'n.map.in'], ['v3-out', 'n.map.out']].forEach(function (x) { $(x[0]).setAttribute('aria-label', tt(x[1])); });
      ['orbit', 'behind', 'top'].forEach(function (m) { $('v3-' + m).setAttribute('aria-pressed', String(!!shown && shown.mode === m)); });
      if (live) {
        p = S.pose;
        a.push(tt('d.v3.cap', {v: Math.round((Math.atan2(p[2], -p[3]) / DEG + 360) % 360)}));
        if (S.t === 0) a.push(tt('d.v3.reset0'));
        else if (fin(S.pitch) && fin(S.roll)) a.push(tt('d.v3.tilt', {p: dec(Math.atan(S.pitch) / DEG, 1), r: dec(Math.atan(S.roll) / DEG, 1)}));
        if (fin(S.speed)) a.push(dec(S.speed * P0.cell_m * 100 / P0.tick_s, 2) + ' cm/s');
        if (fin(S.hour)) { hh = Math.floor(S.hour); mm = Math.floor((S.hour - hh) * 60); a.push(tt('d.v3.clock', {v: (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm})); }
        if (S.target && fin(S.target[0]) && fin(S.target[1])) a.push(tt('d.v3.target', {v: Math.round(Math.hypot(S.target[0] - p[0], S.target[1] - p[1]) * P0.cell_m)}));
        a.push(md);
        if (S.stuck) f.push(tt('c.cam.stuck'));
        if (S.tipped) f.push(tt('c.cam.tipped'));
        if (S.locked) f.push(tt('c.arm.locked').split(' | ').join(' '));
        if (f.length) a.push(f.join(', '));
        var an = tt('d.v3.ann', {m: md, d: tt(info.night ? 'd.v3.night' : 'd.v3.day'), s: S.stage, l: tt(r ? 'd.v3.badge.relief' : 'd.v3.badge.flat')});
        if (an !== ann) { if (ann !== null) $('v3-said').textContent = an; ann = an; }
      }
      $('v3-read').textContent = a.join(' · ');
      f = [];
      if (a.length) {
        if (info.relief && info.waiting) f.push(tt('d.v3.pend', {n: info.waiting}));
        if (info.relief && info.altSrc === 'pending') f.push(tt('d.v3.pendalt'));
        if (S.asleep || S.mode === 'SLEEP') f.push(tt('d.v3.asleep'));
        if (info.night) f.push(tt('d.v3.l.night'));
        if (info.scaleM) f.push(tt('d.v3.scale', {m: info.scaleM}));
        if (small) f.push(tt('d.v3.small'));
        if (reduced) f.push(tt('d.v3.reduced'));
      }
      $('v3-pend').textContent = f.join(' · ');
    }
    function kick() { if (raf === null) raf = requestAnimationFrame(loop); }
    function loop(ts) {
      raf = null;
      if (!shown || !want) return;
      if (lastMs && ts - lastMs < 33) { kick(); return; } // <= 30 images/s
      var dt = lastMs ? Math.min(0.1, (ts - lastMs) / 1000) : 1 / 30, a = stepCam(shown, want, dt), m = CAPS.follow * DEG * dt;
      lastMs = ts;
      if (want.mode === 'behind') a.az = wrap(shown.az + clamp(wrap(want.az - shown.az), -m, m));
      shown = a; draw();
      if (!settled(shown, want)) kick(); else lastMs = 0;
    }
    function setWant(c) { // inertia <= 0.5 s (R6)
      var w = clampCam(c), m = CAPS.az * DEG * CAPS.lagS;
      w.az = wrap(shown.az + clamp(wrap(w.az - shown.az), -m, m));
      m = CAPS.el * DEG * CAPS.lagS; w.el = clamp(w.el, shown.el - m, shown.el + m);
      want = clampCam(w);
      if (reduced) { shown = want; draw(); } else kick();
    }
    function cut(c) { shown = want = clampCam(c); draw(); } // a cut (R3)
    var acc = [0, 0], stepT = [];
    function rotateBy(daz, del) {
      if (!shown) return;
      if (shown.mode !== 'orbit') cut(toOrbit(shown));
      if (reduced) { // R7: steps, <= 3 per second
        acc[0] += daz / DEG; acc[1] += del / DEG;
        var t = o.now(), sa = Math.abs(acc[0]) >= 15 ? (acc[0] > 0 ? 15 : -15) : 0, se = Math.abs(acc[1]) >= 10 ? (acc[1] > 0 ? 10 : -10) : 0;
        stepT = stepT.filter(function (x) { return x > t - 1000; });
        if ((sa || se) && stepT.length < 3) { acc[0] -= sa; acc[1] -= se; stepT.push(t); cut({mode: 'orbit', az: shown.az + sa * DEG, el: shown.el + se * DEG, dist: shown.dist, side: shown.side}); }
        return;
      }
      setWant({mode: 'orbit', az: want.az + daz, el: want.el + del, dist: want.dist, side: want.side});
    }
    function zoomW(f) { if (want) setWant({mode: want.mode, az: want.az, el: want.el, dist: want.dist * f, side: want.side * f}); }
    var api = {
      // each line: wheel motion, previous pose; a new sol cuts
      update: function (state) {
        S = state;
        if (!S.hasTick) return;
        if (S.t !== lastT || S.sol !== lastSol) {
          var cont = lastPose !== null && S.sol === lastSol && S.t === lastT + 1, ws = cont ? wheelStep(lastPose, S.pose) : null;
          if (ws) advanceWheels(wheel, ws);
          prevPose = cont ? lastPose : null; prevU = cont ? lastU : null;
          if (!cont) lastAlt = null;         // a jump: the last altitude no longer applies
          lastU = Array.isArray(S.u) ? {u: S.u, z: !!S.asleep || S.mode === 'SLEEP'} : null;
          if (lastSol !== null && S.sol !== lastSol) shown = want = null;
          lastPose = S.pose.slice(); lastT = S.t; lastSol = S.sol;
        }
        if (shown && shown.mode === 'behind') {
          if (reduced) shown.az = want.az = -Math.PI / 2; // R7: north fixed
          else want.az = Math.atan2(-S.pose[3], S.pose[2]) + Math.PI;
        }
      },
      draw: function (state) { if (state) api.update(state); draw(); if (shown && want && !reduced && !settled(shown, want)) kick(); },
      texts: texts,
      setMode: function (m) {
        if (!S || !S.hasTick) return;
        var c = camDefault(S.pose); c.mode = m;
        if (m === 'behind') { c.dist = Math.hypot(6, 15); c.az = reduced ? -Math.PI / 2 : Math.atan2(-S.pose[3], S.pose[2]) + Math.PI; }
        cut(c);
      },
      recenter: function () { if (S && S.hasTick) cut(camDefault(S.pose)); },
      turn: function (d, e) { if (shown) { var c = toOrbit(shown); cut({mode: 'orbit', az: c.az + d * DEG, el: c.el + e * DEG, dist: c.dist, side: c.side}); } },
      zoom: function (f) { if (shown) cut({mode: shown.mode, az: shown.az, el: shown.el, dist: shown.dist * f, side: shown.side * f}); },
      setTrail: function (b) { trail = !!b; $('v3-trail').checked = trail; draw(); },
      setCone: function (b) { cone = !!b; $('v3-cone').checked = cone; draw(); },
      describe: function () { if (S) $('v3-said').textContent = describe(S, tt, o.act(S), info.relief === false); },
      info: function () { return info; }, guardStats: function () { return guard.stats(); }, camera: function () { return shown; }
    };
    cv.addEventListener('pointerdown', function (e) {
      if (cv.setPointerCapture) { try { cv.setPointerCapture(e.pointerId); } catch (x) { /* no capture */ } }
      (drag = drag || {})[e.pointerId] = [e.clientX, e.clientY]; if (st.focus) st.focus();
    });
    cv.addEventListener('pointermove', function (e) {
      var p = drag && drag[e.pointerId], ids = drag ? Object.keys(drag) : [];
      if (!p) return;
      if (ids.length >= 2) {                       // pinch: distance
        var q = drag[String(ids[0]) === String(e.pointerId) ? ids[1] : ids[0]], d0 = Math.hypot(p[0] - q[0], p[1] - q[1]), d1 = Math.hypot(e.clientX - q[0], e.clientY - q[1]);
        if (d0 > 10 && d1 > 10) zoomW(d0 / d1);
      } else rotateBy(-(e.clientX - p[0]) * 0.4 * DEG, (e.clientY - p[1]) * 0.3 * DEG);
      drag[e.pointerId] = [e.clientX, e.clientY];
    });
    ['pointerup', 'pointercancel'].forEach(function (n) { cv.addEventListener(n, function (e) { if (drag) { delete drag[e.pointerId]; if (!Object.keys(drag).length) drag = null; } }); });
    cv.addEventListener('wheel', function (e) { if (e.preventDefault) e.preventDefault(); zoomW(e.deltaY > 0 ? 1.25 : 0.8); }, {passive: false});
    cv.addEventListener('dblclick', api.recenter);
    st.addEventListener('keydown', function (e) {
      var K = {ArrowLeft: [-15, 0], ArrowRight: [15, 0], ArrowUp: [0, 10], ArrowDown: [0, -10]}, M = {1: 'orbit', 2: 'behind', 3: 'top'}, x = e.key;
      if (K[x]) api.turn(K[x][0], K[x][1]);
      else if (x === '+' || x === '=') api.zoom(0.8); else if (x === '-' || x === '_') api.zoom(1.25); else if (x === '0') api.recenter();
      else if (M[x]) api.setMode(M[x]); else if (x === 't' || x === 'T') api.setTrail(!trail); else if (x === 'c' || x === 'C') api.setCone(!cone);
      else return;
      if (e.preventDefault) e.preventDefault();
    });
    ['orbit', 'behind', 'top'].forEach(function (m) { $('v3-' + m).addEventListener('click', function () { api.setMode(m); }); });
    $('v3-in').addEventListener('click', function () { api.zoom(0.8); });
    $('v3-out').addEventListener('click', function () { api.zoom(1.25); });
    $('v3-re').addEventListener('click', api.recenter);
    $('v3-trail').addEventListener('change', function (e) { api.setTrail(e.target.checked); });
    $('v3-cone').addEventListener('change', function (e) { api.setCone(e.target.checked); });
    $('v3-desc').addEventListener('click', api.describe);
    return api;
  }

  var api = {P0: P0, BODY: BODY, CMD_SIDE: CMD_SIDE, CAPS: CAPS, CAM_LIM: CAM_LIM, FOG: FOG, NIGHT_GROUND: NIGHT_GROUND, NIGHT_SKY: NIGHT_SKY, RAMP: RAMP,
             toRender: toRender, sunVector: sunVector, groundIndex: groundIndex, heightAt: heightAt, slopeAt: slopeAt, pitchRoll: pitchRoll,
             gradFromTilt: gradFromTilt, bodyFrame: bodyFrame, wheelStep: wheelStep, meshFromCells: meshFromCells, shadeMesh: shadeMesh,
             camDefault: camDefault, clampCam: clampCam, stepCam: stepCam, viewOf: viewOf, project: project, horizonRow: horizonRow,
             makeTarget: makeTarget, buildScene: buildScene, raster: raster, lumTable: lumTable, isTransition: isTransition,
             makeFlashGuard: makeFlashGuard, describe: describe, advanceWheels: advanceWheels, toOrbit: toOrbit, settled: settled, mapKey: mapKey, wrap: wrap, mount: mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0View3D = api;
})(typeof self !== 'undefined' ? self : this);
