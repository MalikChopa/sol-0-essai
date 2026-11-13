/* Sol-0 live console: 640x360 palette-index buffer, same primitives and layout as src/rover/render (console, panels,
   brain_view, cam_view, vignettes). Draws from the stream-v2 view model only: no interpolation, no invented value.
   Ported line by line from the Python renderer; tests/page/ compares the buffers with the Python ones.
   Page v2 (live-rc14): every drawn text goes through T(o, id, english) and every option is optional; without options the buffer is
   byte for byte the rc13 one (= the Python one, tests/page/render.test.js). Options: o.t (table id -> text of the page language),
   o.en (English table, to recognise the engine's stage names), o.page (page-only layout fixes, DESIGN.md §8), o.right (header right
   text), o.rec (REC lit), o.dec (decimal separator), o.boxes (array: every text box drawn, for the tests). Accented capitals are drawn
   as a base glyph + a 2-row mark above it (ACCENTS, page side only: the 95 glyphs of the exported font are unchanged). */
(function (root) {
  'use strict';
  var W = 640, H = 360;
  var BG = 48, BG_SCAN = 49, BG_VIG = 50, REC = 51, NEG = 62, MARK = 63, TWIN = 24;
  var A = null, GLYPHS = null, STEPS = null, BOXES = null, NOBOX = 0, STRICT = false;
  // accent marks: 5 columns, bit 0 = row y - 2, bit 1 = row y - 1 (I18N.md §2); cedilla: two pixels under the glyph
  var MARKS = {acute: [0, 0, 2, 1, 0], grave: [0, 1, 2, 0, 0], circ: [0, 2, 1, 2, 0], uml: [0, 2, 0, 2, 0]};
  var ACCENTS = {'\u00c9': ['E', 'acute'], '\u00c8': ['E', 'grave'], '\u00ca': ['E', 'circ'], '\u00cb': ['E', 'uml'], '\u00c0': ['A', 'grave'],
                 '\u00c2': ['A', 'circ'], '\u00d4': ['O', 'circ'], '\u00ce': ['I', 'circ'], '\u00cf': ['I', 'uml'], '\u00db': ['U', 'circ'],
                 '\u00d9': ['U', 'grave'], '\u00dc': ['U', 'uml'], '\u00c7': ['C', 'ced']};

  function hud(n) { return 51 + Math.max(1, Math.min(10, n)); }
  function init(assets) {
    A = assets;
    GLYPHS = {};
    for (var i = 0; i < A.font.table.length; i++) {
      var h = A.font.table[i], c = [];
      for (var k = 0; k < 10; k += 2) c.push(parseInt(h.substr(k, 2), 16));
      GLYPHS[String.fromCharCode(32 + i)] = c;
    }
    STEPS = radialSteps(H, W, [500, 900]);
    return api;
  }

  // ---- primitives (src/rover/render/draw.py) ----
  function put(img, x, y, c) { if (x >= 0 && x < W && y >= 0 && y < H) img[y * W + x] = c; }
  function rect(img, x, y, w, h, c) {
    var x0 = Math.max(0, x), y0 = Math.max(0, y), x1 = Math.min(W, x + w), y1 = Math.min(H, y + h);
    if (x1 > x0 && y1 > y0) for (var yy = y0; yy < y1; yy++) img.fill(c, yy * W + x0, yy * W + x1);
    if (BOXES && c === BG) prune(x, y, w, h);
  }
  function frameRect(img, x, y, w, h, c) {
    rect(img, x, y, w, 1, c); rect(img, x, y + h - 1, w, 1, c); rect(img, x, y, 1, h, c); rect(img, x + w - 1, y, 1, h, c);
    if (BOXES && !NOBOX) BOXES.push({x: x, y: y, w: w, h: h, frame: true});      // tests: a text never crosses a frame
  }
  function line(img, x0, y0, x1, y1, c, dotted, thick) {
    var dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx + dy, n = 0;
    thick = thick || 1;
    for (;;) {
      if (!dotted || n % 2 === 0) { put(img, x0, y0, c); if (thick > 1) put(img, x0, y0 + 1, c); }
      if (x0 === x1 && y0 === y1) break;
      var e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
      n++;
    }
  }
  function disc(img, cx, cy, r, c) {
    var lim = r * r + Math.floor(r / 2);
    for (var dy = -r; dy <= r; dy++) for (var dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= lim) put(img, cx + dx, cy + dy, c);
  }
  function ring(img, cx, cy, r, c) {
    for (var dy = -r; dy <= r; dy++) for (var dx = -r; dx <= r; dx++) {
      var d = dx * dx + dy * dy;
      if (r * r - r <= d && d <= r * r + r) put(img, cx + dx, cy + dy, c);
    }
  }
  function cross(img, cx, cy, r, c) { line(img, cx - r, cy, cx + r, cy, c); line(img, cx, cy - r, cx, cy + r, c); }

  // ---- font (src/rover/render/font.py) ----
  function textWidth(s, scale) { return Math.max(0, s.length * 6 - 1) * (scale || 1); }
  function blk(img, px, py, scale, color) {
    if (px >= 0 && px < W && py >= 0 && py < H) {
      for (var yy = py; yy < Math.min(py + scale, H); yy++) img.fill(color, yy * W + px, yy * W + Math.min(px + scale, W));
    }
  }
  function hasAccent(s) { for (var i = 0; i < s.length; i++) if (ACCENTS[s[i]]) return true; return false; }
  function text(img, x, y, s, color, scale) {
    scale = scale || 1;
    var acc = false;
    for (var i = 0; i < s.length; i++) {
      var cols = GLYPHS[s[i]], mark = null;
      if (!cols && ACCENTS[s[i]]) { cols = GLYPHS[ACCENTS[s[i]][0]]; mark = ACCENTS[s[i]][1]; acc = true; }
      if (!cols) { if (STRICT) throw new Error('no glyph for ' + JSON.stringify(s[i]) + ' in ' + JSON.stringify(s)); cols = GLYPHS['?']; }
      for (var cx = 0; cx < 5; cx++) for (var ry = 0; ry < 7; ry++) if ((cols[cx] >> ry) & 1) blk(img, x + (i * 6 + cx) * scale, y + ry * scale, scale, color);
      if (mark === 'ced') { blk(img, x + (i * 6 + 2) * scale, y + 7 * scale, scale, color); blk(img, x + (i * 6 + 1) * scale, y + 8 * scale, scale, color); }
      else if (mark) for (var mx = 0; mx < 5; mx++) {
        var bits = MARKS[mark][mx];
        if (bits & 1) blk(img, x + (i * 6 + mx) * scale, y - 2 * scale, scale, color);
        if (bits & 2) blk(img, x + (i * 6 + mx) * scale, y - 1 * scale, scale, color);
      }
    }
    if (BOXES && !NOBOX) BOXES.push({x: x, y: acc ? y - 2 * scale : y, w: textWidth(s, scale), h: (acc ? 9 : 7) * scale, s: s, scale: scale, c: color});
    return [x, y, textWidth(s, scale), 7 * scale];
  }
  // page v2 (D16, o.page): a text laid on the CAM-1 image gets a 1 px dark outline (drawn in BG around it first); a reading aid only
  function textOn(img, x, y, s, color, scale, o) {
    if (o && o.page) {
      NOBOX++;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) if (dx || dy) text(img, x + dx, y + dy, s, BG, scale);
      NOBOX--;
    }
    return text(img, x, y, s, color, scale);
  }
  // the text of id `id` in the page language, else the English literal (the rc13 text); {name} replaced by v[name]
  function T(o, id, en, v) {
    var s = (o && o.t && typeof o.t[id] === 'string') ? o.t[id] : en;
    if (v) s = s.replace(/\{([a-z0-9_]+)\}/g, function (m, k) { return v[k] === undefined ? m : String(v[k]); });
    return s;
  }
  // a number formatted like Python, with the page's decimal separator (FR: comma, same width)
  function F(o, v, d, plus) { var s = fix(v, d, plus); return (o && o.dec === ',') ? s.replace('.', ',') : s; }
  // drawn texts are recorded only while a test gives an array (o.boxes); a BG rectangle that covers a recorded box erases it
  function setBoxes(b) { BOXES = b || null; }
  function prune(x, y, w, h) {
    if (!BOXES) return;
    for (var i = BOXES.length - 1; i >= 0; i--) {
      var b = BOXES[i];
      if (b.x >= x && b.y >= y && b.x + b.w <= x + w && b.y + b.h <= y + h) BOXES.splice(i, 1);
    }
  }

  // ---- number formatting identical to Python's %.Nf / %+.Nf (half-even on exact binary ties) ----
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function fix(v, d, plus) {
    if (!isNum(v)) return '--';
    var neg = v < 0 || Object.is(v, -0), a = Math.abs(v), s = a.toFixed(d);
    var long = a.toFixed(30), dot = long.indexOf('.'), tail = long.slice(dot + 1 + d);
    if (/^50*$/.test(tail)) {
      var kept = long.slice(0, dot + 1 + d).replace(/\.$/, '');
      var last = kept.replace('.', '').slice(-1);
      if (parseInt(last, 10) % 2 === 0) s = kept;
    }
    return (neg ? '-' : (plus ? '+' : '')) + s;
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function fl(v) { return Math.floor(v); }
  function pct(v) { return fl(v * 100.0 + 0.5); }

  // ---- vignette (src/rover/render/vignettes.py) ----
  function radialSteps(h, w, th) {
    var st = new Uint8Array(h * w);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var dx = x * 2 - (w - 1), dy = y * 2 - (h - 1);
      var rr = Math.floor(dx * dx * 1000 / (w * w)) + Math.floor(dy * dy * 1000 / (h * h)), n = 0;
      for (var i = 0; i < th.length; i++) if (rr >= th[i]) n++;
      st[y * w + x] = n;
    }
    return st;
  }
  function vignette(img, cam) {
    for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) {
      if (x >= cam[0] && x < cam[0] + cam[2] && y >= cam[1] && y < cam[1] + cam[3]) continue;
      if (img[y * W + x] === BG) { var s = STEPS[y * W + x]; img[y * W + x] = s >= 2 ? BG_VIG : (s === 1 ? BG_SCAN : BG); }
    }
  }

  // ---- helpers on the view model ----
  function modActive(m, stage) { return ({0: 0, 1: 1, 2: 1, 3: 3, 4: 4, 5: 5}[m] === undefined ? 99 : {0: 0, 1: 1, 2: 1, 3: 3, 4: 4, 5: 5}[m]) <= stage; }
  function batteryUnlocked(stage) { return A.m0_active[Math.min(Math.max(stage, 0), A.m0_active.length - 1)].indexOf(18) >= 0; }
  function batteryUnlockStage() { for (var s = 0; s < A.m0_active.length; s++) if (A.m0_active[s].indexOf(18) >= 0) return s; return A.m0_active.length; }
  function atan(x) {
    var C = A.atan_c, ax = Math.abs(x), big = ax > 1.0, t = big ? 1.0 / Math.max(ax, 1e-300) : ax;
    t = t / (1.0 + Math.sqrt(1.0 + t * t)); t = t / (1.0 + Math.sqrt(1.0 + t * t));
    var u = t * t, acc = C[C.length - 1];
    for (var i = C.length - 2; i >= 0; i--) acc = acc * u + C[i];
    var r = 4.0 * t * acc; if (big) r = A.half_pi - r;
    return x < 0.0 ? -r : r;
  }
  function tiltDeg(S) { return atan(Math.sqrt(S.pitch * S.pitch + S.roll * S.roll)) * 57.29577951308232; }
  function level(a) { return 1 + fl(9.0 * Math.min(1.0, Math.abs(a)) + 0.5); }
  function node(img, cx, cy, r, a) {
    if (a < 0) { disc(img, cx, cy, r, 48); ring(img, cx, cy, r, NEG); } else disc(img, cx, cy, r, hud(level(a)));
  }
  function label(img, x, y, t, c) { var a = hasAccent(t) ? 2 : 0; rect(img, x - 1, y - 1 - a, textWidth(t) + 2, 9 + a, BG); text(img, x, y, t, c, 1); }
  // the engine's stage name (data); in another language its translation, only when the name is the one the table knows for this stage
  function stageLabel(S, o) {
    var raw = String(S.stageName).toUpperCase(), id = 'c.stage.' + S.stage;
    if (o && o.t && o.en && o.en[id] === raw && typeof o.t[id] === 'string') return o.t[id];
    return raw;
  }
  function modeLabel(mode, o) { var en = A.mode_labels[mode]; return T(o, 'c.mode.' + mode, en === undefined ? String(mode) : en); }
  function lockedText(o) { return (o && o.page) ? hud(6) : hud(3); }      // M10: '???' texts legible in the page (frames stay hud(3))
  function hhmm(hour) { var hh = fl(hour), mm = fl((hour - hh) * 60.0); return pad2(hh) + ':' + pad2(mm); }
  function mkey(x, y) { return (x + 32768) * 65536 + (y + 32768); }

  // ---- brain layout (brain_view.py) ----
  var COL_IN = 360, COL_H = 440, COL_MID = 510, COL_OUT = 590, ZY0 = 56, ZH = 110, N_H = 16, N_OUT = 2, M4_Y = 166;
  function layout(stage) {
    var active = A.m0_active[stage], n = active.length, pitch = Math.min(10, Math.floor(ZH / n));
    var y0 = ZY0 + Math.floor((ZH - pitch * n) / 2) + Math.floor(pitch / 2), inY = {}, hY = [], oY = [];
    active.forEach(function (i, k) { inY[i] = y0 + k * pitch; });
    var yh = ZY0 + Math.floor((ZH - 6 * N_H) / 2) + 3;
    for (var j = 0; j < N_H; j++) hY.push(yh + 6 * j);
    for (var k2 = 0; k2 < N_OUT; k2++) oY.push(ZY0 + Math.floor(ZH * (k2 + 1) / (N_OUT + 1)));
    return {active: active, inY: inY, hY: hY, oY: oY};
  }
  // connections (excluded from the exact comparison, design P7): |W_ij * a_i| / max |W| of the layer
  function drawConnections(img, S, L) {
    if (!S.w) return;
    var w = S.w, x = S.x, h = S.hd, c1 = [], i, j, k, m1 = 1e-12, m2 = 1e-12;
    for (i = 0; i < L.active.length; i++) for (j = 0; j < N_H; j++) m1 = Math.max(m1, Math.abs(w[L.active[i] * N_H + j]));
    for (j = 0; j < N_H * N_OUT; j++) m2 = Math.max(m2, Math.abs(w[400 + j]));
    L.active.forEach(function (ii) { for (var jj = 0; jj < N_H; jj++) { var v = x[ii] * w[ii * N_H + jj]; c1.push([Math.abs(v), ii, jj, v < 0]); } });
    c1.sort(function (a, b) { return b[0] - a[0] || 0; });
    c1.slice(0, A.params.brain_top_l1).forEach(function (c) {
      if (c[0] > 0) conn(img, COL_IN, L.inY[c[1]], COL_H, L.hY[c[2]], c[0] / m1, c[3]);
    });
    for (j = 0; j < N_H; j++) for (k = 0; k < N_OUT; k++) {
      var v2 = h[j] * w[400 + j * N_OUT + k];
      if (Math.abs(v2) > 0) conn(img, COL_H, L.hY[j], COL_OUT, L.oY[k], Math.abs(v2) / m2, v2 < 0);
    }
  }
  function conn(img, x0, y0, x1, y1, f, neg) {
    var lvl = hud(1 + fl(9.0 * Math.min(1.0, f) + 0.5));
    line(img, x0, y0, x1, y1, neg ? NEG : lvl, neg, f > A.params.thick_frac ? 2 : 1);
  }

  function drawBrain(img, S, o) {
    var stage = S.stage, L = layout(stage), asleep = S.mode === 'SLEEP', i, j, k;
    frameRect(img, 336, 24, 296, 200, hud(4));
    text(img, 340, 28, T(o, 'c.brain.title', 'BRAIN | LIVE ACTIVATIONS'), hud(10), 1);
    var t = T(o, 'c.brain.locked', '??? = NOT UNLOCKED YET');
    text(img, 336 + 296 - 4 - textWidth(t), 28, t, hud(7), 1);
    if (modActive(2, stage) && S.z) {
      for (k = 0; k < 40; k++) {
        var v = Math.min(1.0, Math.max(0.0, S.z[k])), hh = fl(v * 12.0 + 0.5);
        rect(img, 340 + 3 * k, 50 - hh, 2, hh, hud(7));
      }
      text(img, 464, 40, T(o, 'c.brain.m2', 'M2 VISION'), hud(10), 1);
    } else { frameRect(img, 340, 38, 120, 12, hud(3)); text(img, 380, 40, '???', lockedText(o), 1); }
    if (o.connections !== false) drawConnections(img, S, L);
    L.active.forEach(function (ii) { node(img, COL_IN, L.inY[ii], 2, S.x[ii]); });
    for (j = 0; j < N_H; j++) node(img, COL_H, L.hY[j], 3, S.hd[j]);
    for (k = 0; k < N_OUT; k++) { node(img, COL_OUT, L.oY[k], 4, S.y[k]); text(img, COL_OUT + 8, L.oY[k] - 3, k ? T(o, 'c.brain.out.r', 'R') : T(o, 'c.brain.out.l', 'L'), hud(10), 1); }
    if (modActive(1, stage) && S.m1) {
      for (k = 0; k < 3; k++) {
        [[S.m1[k], hud(7)], [S.m1[3 + k], MARK]].forEach(function (pc, row) {
          var vv = pc[0] / S.m1max, n = fl(Math.min(1.0, Math.abs(vv)) * 22.0 + 0.5), xs = vv >= 0 ? COL_MID : COL_MID - n;
          rect(img, xs, 62 + 12 * k + 4 * row, Math.max(1, n), 3, pc[1]);
        });
        rect(img, COL_MID, 60 + 12 * k, 1, 11, hud(4));
      }
      label(img, 496, 52, T(o, 'c.brain.m1', 'M1 PREDICT'), hud(10));
    } else { rect(img, 484, 58, 52, 42, BG); frameRect(img, 484, 58, 52, 42, hud(3)); text(img, 498, 76, '???', lockedText(o), 1); }
    if (modActive(3, stage) && S.m3) {
      for (k = 0; k < 3; k++) node(img, COL_MID, 124 + 14 * k, 3, S.m3[k]);
      label(img, 496, 110, T(o, 'c.brain.m3', 'M3 ENERGY'), hud(10));
    } else { rect(img, 484, 106, 52, 52, BG); frameRect(img, 484, 106, 52, 52, hud(3)); text(img, 498, 130, '???', lockedText(o), 1); }
    if (modActive(4, stage) && S.m4 !== null && S.m4 !== undefined) {
      node(img, COL_MID, M4_Y, 3, S.m4); label(img, COL_MID + 8, M4_Y - 3, T(o, 'c.brain.m4', 'M4 SAMPLE'), hud(10));
    }
    var txt = T(o, 'c.brain.lr', 'L {u0} R {u1}', {u0: F(o, S.u[0], 2, true), u1: F(o, S.u[1], 2, true)});
    text(img, 336 + 296 - 4 - textWidth(txt), 172, txt, hud(10), 1);
    var xi0 = Math.abs(S.xi[0]), xi1 = Math.abs(S.xi[1]);
    if (Math.max(xi0, xi1) > 0.0) {
      text(img, 540, 181, T(o, 'c.brain.noise', 'NOISE'), hud(10), 1);
      [xi0, xi1].forEach(function (a, kk) { rect(img, 574 + 28 * kk, 182, Math.max(1, fl(Math.min(1.0, a) * 24.0 + 0.5)), 4, hud(7)); });
    }
    text(img, 340, 190, T(o, 'c.brain.intent', 'INTENT: {mode}', {mode: modeLabel(S.mode, o)}), hud(10), 1);
    if (asleep) text(img, 340, 172, T(o, 'c.brain.asleep', 'ASLEEP'), MARK, 1);
    for (var m = 0; m < 9; m++) {
      var on = modActive(m, stage), bx = 340 + 32 * m;
      frameRect(img, bx, 200, 30, 18, on ? hud(10) : hud(3));
      text(img, bx + 6, 205, on ? 'M' + m : '???', on ? hud(10) : lockedText(o), 1);
    }
  }

  // ---- CAM-1 (cam_view.py) ----
  function drawCam(img, cam, scanlines) {
    var h = cam.h, w = cam.w, sx = Math.floor(320 / w), sy = Math.floor(200 / h), bh = h * sy, oy = Math.floor((200 - bh) / 2);
    for (var y = 0; y < 200; y++) for (var x = 0; x < 320; x++) {
      var c = BG, yy = y - oy;
      if (yy >= 0 && yy < bh && x < w * sx) {
        c = cam.data[Math.floor(yy / sy) * w + Math.floor(x / sx)];
        if (scanlines && (y % 2) === 1) c += TWIN;
      }
      img[(24 + y) * W + 8 + x] = c;
    }
  }
  function drawOverlays(img, S, o) {
    var h = S.cam.h, w = S.cam.w, sx = Math.floor(320 / w), sy = Math.floor(200 / h), zw = w * sx, zh = h * sy, oy = Math.floor((200 - zh) / 2);
    var p = S.pose, c = p[2], s = p[3];
    if (S.stage >= 2 && S.target && S.mode !== 'SLEEP') {
      var dx = S.target[0] - p[0], dy = S.target[1] - p[1], fwd = dx * c + dy * s, lat = -dx * s + dy * c;
      if (fwd > 0.0) {
        var uw = lat / fwd / 0.7;
        if (uw >= -1.0 && uw <= 1.0) {
          var cx = 8 + fl((uw + 1.0) / 2.0 * zw), hor = 0.35 * h + S.pitch * 0.9 * h;
          var cy = 24 + oy + fl(Math.min(Math.max(hor, 0.0), h - 1.0) * sy);
          ring(img, cx, cy, 6, MARK); cross(img, cx, cy, 9, MARK);
        }
      }
    }
    if (batteryUnlocked(S.stage)) {
      var t = T(o, 'c.cam.bat', 'BAT {n}%', {n: fl(S.battery * 100.0 + 1e-9)});
      textOn(img, 8 + 320 - 4 - textWidth(t), 28, t, MARK, 1, o);
      if (S.sun[0] > 0.0 && S.mode !== 'SLEEP') {
        var f2 = S.sun[1] * c + S.sun[2] * s, l2 = -S.sun[1] * s + S.sun[2] * c, ax = 8 + 22, ay = 24 + 200 - 26;
        var ex = ax + fl(14.0 * l2 + 0.5), ey = ay - fl(14.0 * f2 + 0.5);
        ring(img, ax, ay, 16, hud(7)); line(img, ax, ay, ex, ey, MARK, false, 2); disc(img, ex, ey, 2, MARK);
        var sunT = T(o, 'c.cam.sun', 'SUN');
        // page mode: one row higher, so that the dark outline stays inside the CAM-1 frame (VERIF-rc14 M1: it erased the frame's row 224)
        textOn(img, (o && o.page) ? ax - fl(textWidth(sunT) / 2) : ax - 9, (o && o.page) ? ay + 18 : ay + 19, sunT, MARK, 1, o);
      }
    }
  }

  // ---- local map, telemetry (panels.py) ----
  function drawMap(img, S) {
    var MX = 8, MY = 232, x0 = fl(S.pose[0]) - 30, y0 = fl(S.pose[1]) - 30, cy, cx;
    for (cy = 0; cy < 60; cy++) for (cx = 0; cx < 60; cx++) {
      var g = S.map.get(mkey(x0 + cx, y0 + cy)), c = g === undefined ? BG : A.ramp[g - 1] + 3;
      var o = (MY + 2 * cy) * W + MX + 2 * cx;
      img[o] = c; img[o + 1] = c; img[o + W] = c; img[o + W + 1] = c;
    }
    frameRect(img, MX - 1, MY - 1, 122, 122, hud(4));
    function px(x, y) { return [MX + fl((x - x0) * 2.0), MY + fl((y - y0) * 2.0)]; }
    S.trail.forEach(function (q) {
      var ab = px(q[0], q[1]);
      if (ab[0] >= MX && ab[0] < MX + 120 && ab[1] >= MY && ab[1] < MY + 120) img[ab[1] * W + ab[0]] = hud(6);
    });
    if (S.target) {
      var tb = px(S.target[0], S.target[1]);
      if (tb[0] >= MX + 3 && tb[0] < MX + 120 - 3 && tb[1] >= MY + 3 && tb[1] < MY + 120 - 3) cross(img, tb[0], tb[1], 3, MARK);
    }
    var ab2 = px(S.pose[0], S.pose[1]), a = ab2[0], b = ab2[1], c = S.pose[2], s = S.pose[3];
    var tipx = a + fl(5.0 * c + 0.5), tipy = b + fl(5.0 * s + 0.5), lx = a - fl(2.0 * s + 0.5), ly = b + fl(2.0 * c + 0.5);
    var rx = a + fl(2.0 * s + 0.5), ry = b - fl(2.0 * c + 0.5);
    line(img, lx, ly, tipx, tipy, hud(10)); line(img, rx, ry, tipx, tipy, hud(10)); line(img, lx, ly, rx, ry, hud(10));
  }
  function telemetry(S, o) {
    var P = A.params, cm = S.speed * P.cell_m * 100.0 / P.tick_s, vmax = P.v_max * P.cell_m * 100.0 / P.tick_s, tl = tiltDeg(S);
    var bat = batteryUnlocked(S.stage) ? (isNum(S.battery) ? [fl(S.battery * 100.0 + 1e-9) + '%', S.battery] : ['--', 0]) : [T(o, 'c.tel.notyet', 'NOT YET'), null];
    return [[T(o, 'c.tel.speed', 'SPEED'), isNum(cm) ? F(o, cm, 2) + ' cm/s' : '--', isNum(cm) ? Math.min(1.0, cm / vmax) : 0], [T(o, 'c.tel.battery', 'BATTERY'), bat[0], bat[1]],
            [T(o, 'c.tel.tilt', 'TILT'), isNum(tl) ? F(o, tl, 1) + ' deg' : '--', isNum(tl) ? Math.min(1.0, tl / 35.0) : 0],
            [T(o, 'c.tel.slip', 'SLIP'), isNum(S.slip) ? fl(S.slip * 100.0 + 1e-9) + '%' : '--', isNum(S.slip) ? Math.min(1.0, Math.max(0.0, S.slip)) : 0]];
  }
  function drawTelemetry(img, S, o) {
    var TX = 136, TY = 232;
    frameRect(img, TX, TY, 248, 120, hud(4));
    text(img, TX + 4, TY + 4, T(o, 'c.tel.title', 'TELEMETRY'), hud(10), 1);
    telemetry(S, o).forEach(function (r, k) {
      var y = TY + 30 + 22 * k, bx = TX + 170;
      text(img, TX + 6, y + 4, r[0], hud(10), 1);
      text(img, TX + 54, y, r[1], hud(10), 2);
      // D1 (page): a locked value has no bar; « AT STAGE n » takes the bar's place instead of a line glued to the next row
      if (r[2] === null && o && o.page) { text(img, bx, y + 3, T(o, 'c.tel.atstage', 'AT STAGE {n}', {n: batteryUnlockStage()}), hud(7), 1); return; }
      frameRect(img, bx, y + 3, 68, 8, hud(4));
      if (r[2] === null) text(img, TX + 54, y + 15, T(o, 'c.tel.fromstage', 'FROM STAGE {n}', {n: batteryUnlockStage()}), hud(7), 1);
      else rect(img, bx + 1, y + 4, fl(66.0 * r[2]), 6, hud(10));
    });
  }

  // ---- ARM / SCAN instrument ----
  function armTitle(S, o) {
    if (S.asleep) return T(o, 'c.arm.off', 'ARM | OFF');
    if (S.mode === 'DRILL') return T(o, 'c.arm.drill', 'ARM | DRILL {p}%', {p: pct(S.drill)});
    if (S.locked) return T(o, 'c.arm.locked', 'ARM | LOCKED');
    return S.mode === 'DRIVE' ? T(o, 'c.arm.ready', 'ARM | READY') : T(o, 'c.arm.idle', 'ARM | IDLE');
  }
  function lockReason(S, o) {
    if (S.battery < A.params.drill_min_battery) return T(o, 'c.arm.lock.bat', 'LOCK: LOW BATTERY');
    if (S.nd >= A.params.drills_max) return T(o, 'c.arm.lock.day', 'LOCK: DAILY LIMIT');
    return T(o, 'c.arm.lock.cool', 'LOCK: COOLDOWN');
  }
  var CH = [['c.arm.ch.hrd', 'HRD'], ['c.arm.ch.r', 'R'], ['c.arm.ch.g', 'G'], ['c.arm.ch.b', 'B'], ['c.arm.ch.grn', 'GRN']];
  function drawArm(img, S, o) {
    text(img, 396, 236, armTitle(S, o), hud(10), 1);
    if (S.asleep || !S.armPatch) return;
    var z = A.params.arm_zoom, n = 16, y, x;
    for (y = 0; y < n * z; y++) for (x = 0; x < n * z; x++) img[(248 + y) * W + 398 + x] = S.armPatch[Math.floor(y / z) * n + Math.floor(x / z)];
    var cx = 398 + (n * z) / 2, cy = 248 + (n * z) / 2, lo = 398 - 3, hi = 398 + n * z + 2;
    rect(img, lo - 4, cy, 4, 1, MARK); rect(img, hi, cy, 4, 1, MARK); rect(img, cx, 248 - 4, 1, 4, MARK); rect(img, cx, 248 + n * z, 1, 4, MARK);
    var x0 = 504;
    if (!S.sample) text(img, x0, 250, T(o, 'c.arm.nosample', 'NO SAMPLE'), hud(7), 1);
    else CH.forEach(function (lab, k) {
      var v = Math.min(1.0, Math.max(0.0, S.sample.f[k])), yy = 250 + 10 * k;
      text(img, x0, yy, T(o, lab[0], lab[1]), hud(10), 1); rect(img, x0 + 24, yy, Math.max(0, fl(v * 100.0 + 0.5)), 6, hud(10));
    });
    text(img, x0, 306, (!S.sample || S.sample.g === null || S.sample.g === undefined) ? T(o, 'c.arm.gain.none', 'GAIN --')
      : T(o, 'c.arm.gain', 'GAIN {g} {n}', {g: F(o, S.sample.g, 2, true), n: S.sample.n ? T(o, 'c.arm.novel', 'NOVEL') : T(o, 'c.arm.same', 'SAME')}), hud(10), 1);
    text(img, x0, 316, T(o, 'c.arm.m4y', 'M4 Y {v}', {v: (S.m4 === null || S.m4 === undefined) ? '--' : F(o, S.m4, 2, true)}), hud(10), 1);
    text(img, x0, 326, T(o, 'c.arm.drills', 'DRILLS {n}/{m}', {n: S.nd, m: A.params.drills_max}), hud(10), 1);
    if (S.locked && S.mode !== 'DRILL') text(img, x0, 338, lockReason(S, o), hud(7), 1);
  }
  var SHAPE = null;
  function shape(img, x, y, lab) {
    if (lab < 0) { put(img, x, y, hud(4)); return; }
    var c = [MARK, hud(10), NEG, hud(7)][Math.floor(lab / 4) % 4], k = lab % 4;
    put(img, x, y, c);
    if (k === 1) [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) { put(img, x + d[0], y + d[1], c); });
    else if (k === 2) rect(img, x - 1, y - 1, 3, 3, c);
    else if (k === 3) [[1, 1], [-1, -1], [1, -1], [-1, 1]].forEach(function (d) { put(img, x + d[0], y + d[1], c); });
  }
  function scaleAxis(v, lo, hi, n) { return hi === lo ? Math.floor(n / 2) : fl((v - lo) * n / (hi - lo)); }
  function scanLine(S, o) {
    var sc = S.scan, kTxt = (sc && isNum(sc.k)) ? String(sc.k) : '--', axTxt = (sc && isNum(sc.ax)) ? sc.ax + '%' : '--';
    if (o && o.page && !(sc && sc.pts && sc.pts.length)) return T(o, 'c.scan.none', 'NO SCAN YET');     // M4: no « K 0 N 0 AX 0% »
    return T(o, 'c.scan.line', 'K {k} N {n} AX {a}', {k: kTxt, n: (sc && sc.pts ? sc.pts.length : '--'), a: axTxt});
  }
  function drawScan(img, S, o) {
    var box = A.params.scan_box, sc = S.scan, pts = sc ? sc.pts : [], k;
    text(img, 396, 236, T(o, 'c.scan.title', 'SCAN | 16 BANDS'), hud(10), 1);
    if (!S.spectrum) text(img, 396, 250, T(o, 'c.scan.nospec', 'NO SPECTRUM YET'), hud(7), 1);
    else {
      var sp = S.spectrum, top = Math.max.apply(null, sp), pk = 0;
      for (k = 0; k < 16; k++) { var hh = top > 0.0 ? fl(56 * sp[k] / top + 0.5) : 0; rect(img, 396 + 6 * k, 340 - hh, 4, hh, hud(10)); if (sp[k] > sp[pk]) pk = k; }
      text(img, 396, 250, T(o, 'c.scan.peak', 'PEAK B{k} {v}', {k: pk, v: F(o, sp[pk], 2)}), hud(10), 1);
    }
    frameRect(img, box[0] - 1, box[1] - 1, box[2] + 2, box[3] + 2, hud(4));
    if (pts.length) {
      var xlo = Infinity, xhi = -Infinity, ylo = Infinity, yhi = -Infinity;
      pts.forEach(function (q) { xlo = Math.min(xlo, q[1]); xhi = Math.max(xhi, q[1]); ylo = Math.min(ylo, q[2]); yhi = Math.max(yhi, q[2]); });
      var vis = pts.map(function (q, i) { return i; }), cap = A.params.scan_max_points;
      if (vis.length > cap) {
        var byId = vis.slice().sort(function (a, b) { return pts[b][0] - pts[a][0]; }).slice(0, cap).sort(function (a, b) { return a - b; });
        vis = byId;
      }
      var lastFresh = -1, lastKey = null;
      vis.forEach(function (i) {
        var q = pts[i], x = box[0] + scaleAxis(q[1], xlo, xhi, box[2] - 1), y = box[1] + scaleAxis(q[2], ylo, yhi, box[3] - 1);
        shape(img, x, y, q[3]);
        if (q[4] >= 0 && (lastKey === null || q[4] > lastKey[0] || (q[4] === lastKey[0] && q[0] > lastKey[1]))) { lastKey = [q[4], q[0]]; lastFresh = [x, y]; }
      });
      if (lastFresh !== -1) ring(img, lastFresh[0], lastFresh[1], 3, MARK);
    }
    text(img, box[0], 326, scanLine(S, o), hud(10), 1);
    var ct = T(o, 'c.scan.nocat', 'NO CATEGORY YET');
    if (S.cat >= 0) { var nm = sc && sc.names && sc.names[String(S.cat)]; ct = T(o, 'c.scan.cat', 'CAT-{n}{name} | CONF {c}', {n: S.cat, name: nm ? ' ' + String(nm).toUpperCase() : '', c: F(o, S.conf, 2)}); }
    text(img, 396, (o && o.page) ? 342 : 344, ct, hud(10), 1);      // D8 (page): off the bottom of the frame
  }
  function drawInstrument(img, S, o) {
    frameRect(img, 392, 232, 240, 120, hud(4));
    if (S.stage < 4) {
      text(img, 396, 236, T(o, 'c.scan.locked', 'SCAN | ???'), lockedText(o), 1);
      var t = T(o, 'c.scan.notdisc', 'INSTRUMENT NOT DISCOVERED');
      text(img, 392 + Math.floor((240 - textWidth(t)) / 2), 232 + 56, t, lockedText(o), 1);
      return;
    }
    if (S.stage === 4 || (S.stage >= 5 && S.mode === 'DRILL')) drawArm(img, S, o); else drawScan(img, S, o);
  }

  // ---- the console (console.py render_frame) ----
  // header band (y < 21): SOL-0, CAM-1, REC square, centred text, right text (also used by the page's bare and waiting views)
  function header(img, center, right, rec, o) {
    text(img, 8, 3, T(o, 'c.hdr.title', 'SOL-0'), hud(10), 2);
    text(img, 72, 6, T(o, 'c.hdr.cam', 'CAM-1'), hud(10), 1);
    rect(img, 112, 7, 7, 7, rec ? REC : hud(3));
    text(img, 122, 6, T(o, 'c.hdr.rec', 'REC'), hud(10), 1);
    var rx = 632 - textWidth(right), cx = Math.max(150, 150 + Math.floor((rx - 8 - 150 - textWidth(center)) / 2));
    if (center) text(img, cx, 6, center, hud(10), 1);
    if (right) text(img, rx, 6, right, hud(10), 1);
    rect(img, 0, 20, 640, 1, hud(2));
  }
  function sol4(S) { var s4 = typeof S.sol === 'number' ? ('0000' + S.sol).slice(-4) : '----'; return S.sol > 9999 ? S.sol : s4; }
  function centerText(S, o) { return T(o, 'c.hdr.center', 'SOL {n} | STAGE {s} {name}', {n: sol4(S), s: S.stage, name: stageLabel(S, o)}); }
  function camCenter(img, y, t, o) { return textOn(img, 8 + Math.floor((320 - textWidth(t)) / 2), y, t, MARK, 1, o); }
  function renderConsole(img, S, o) {
    o = o || {};
    var own = !!o.boxes && BOXES !== o.boxes;
    if (own) BOXES = o.boxes;
    img.fill(BG);
    var scan = o.scanlines !== false;
    // the live page may lack a value the parity renderer always has (no sol number, no sol start, no image yet): never "null", never
    // an image read with an unknown size; with all values present the drawing is unchanged (tests/page/render.test.js)
    var right = o.right !== undefined ? (o.right || '')
      : (typeof S.now === 'string' ? (o.contactLabel || 'LAST CONTACT') + ' ' + S.now.slice(0, 10) + ' ' + S.now.slice(11, 16) + ' UTC' : '');
    header(img, centerText(S, o), right, o.page ? o.rec === true : S.mode !== 'SLEEP', o);
    if (S.cam) drawCam(img, S.cam, scan);
    frameRect(img, 7, 23, 322, 202, hud(4));
    textOn(img, 12, 28, hhmm(S.hour), MARK, 1, o);
    if (S.cam) {
      var acu = T(o, 'c.cam.sensor', 'SENSOR {w}X{h} PX', {w: S.cam.w, h: S.cam.h});
      textOn(img, 8 + 320 - 4 - textWidth(acu), 24 + 200 - 11, acu, MARK, 1, o);
    } else camCenter(img, 24 + 100 + 9, T(o, 'c.cam.noimage', 'NO IMAGE YET'), o);
    if (S.stage === 0) camCenter(img, 24 + 100 - 3, T(o, 'c.cam.visionoff', 'VISION OFFLINE'), o);
    if (S.mode === 'SLEEP') camCenter(img, 44, modeLabel('SLEEP', o), o);
    if (S.mode === 'DRILL' || S.mode === 'ANALYZE') camCenter(img, 44, S.mode === 'DRILL' ? T(o, 'c.cam.drill', 'DRILL {p}%', {p: pct(S.drill)}) : modeLabel('ANALYZE', o), o);
    if (S.stuck) textOn(img, 12, 38, T(o, 'c.cam.stuck', 'STUCK'), MARK, 1, o);
    if (S.tipped) textOn(img, 12, 47, T(o, 'c.cam.tipped', 'TIPPED'), MARK, 1, o);
    if (S.cam) drawOverlays(img, S, o);
    drawBrain(img, S, o);
    drawMap(img, S);
    drawTelemetry(img, S, o);
    drawInstrument(img, S, o);
    vignette(img, [7, 23, 322, 202]);
    if (own) BOXES = null;
    return img;
  }
  // page views without a console to draw: the empty frames of the five panels (bare and waiting views, DESIGN.md §8 D3, M11)
  function emptyFrames(img) {
    frameRect(img, 7, 23, 322, 202, hud(4)); frameRect(img, 336, 24, 296, 200, hud(4)); frameRect(img, 7, 231, 122, 122, hud(4));
    frameRect(img, 136, 232, 248, 120, hud(4)); frameRect(img, 392, 232, 240, 120, hud(4));
  }

  var api = {init: init, renderConsole: renderConsole, fix: fix, scanLine: scanLine, text: text, textWidth: textWidth, rect: rect, frameRect: frameRect,
             hud: hud, W: W, H: H, BG: BG, MARK: MARK, NEG: NEG, mkey: mkey, layout: layout,
             T: T, F: F, textOn: textOn, header: header, centerText: centerText, stageLabel: stageLabel, modeLabel: modeLabel, hhmm: hhmm,
             camCenter: camCenter, emptyFrames: emptyFrames, vignette: function (img) { vignette(img, [7, 23, 322, 202]); },
             setBoxes: setBoxes, setStrict: function (v) { STRICT = !!v; }, hasAccent: hasAccent, ACCENTS: ACCENTS, MARKS: MARKS,
             batteryUnlocked: function (st) { return batteryUnlocked(st); }, batteryUnlockStage: function () { return batteryUnlockStage(); }};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0Console = api;
})(typeof self !== 'undefined' ? self : this);
