/* Sol-0 live page: the explorable map's maths (consigne 53; tests/page/map.test.js): integer device pixels per map pixel, bounded
   panning; map.json's transforms (cells, as the poses) and SHA-256 fingerprints. */
(function (root) {
  'use strict';
  var LEVELS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32];      // device pixels per map pixel
  function fitLevel(iw, ih, vw, vh, dpr) {           // the largest level that shows the whole map (at least 1)
    var k = Math.min(vw * dpr / iw, vh * dpr / ih), best = LEVELS[0];
    LEVELS.forEach(function (l) { if (l <= k + 1e-9) best = l; });
    return best;
  }
  function step(k, d) { var i = LEVELS.indexOf(k); return LEVELS[Math.max(0, Math.min(LEVELS.length - 1, (i < 0 ? 0 : i) + d))]; }
  function nearLevel(k) {                            // pinch: the level nearest to a continuous scale (log distance)
    var best = LEVELS[0];
    LEVELS.forEach(function (l) { if (Math.abs(Math.log(l / k)) < Math.abs(Math.log(best / k))) best = l; });
    return best;
  }
  function clampAxis(t, size, view) { return size <= view ? Math.min(Math.max(t, 0), view - size) : Math.min(Math.max(t, view - size), 0); }
  // a view: level k, CSS size of the map, offset snapped to the device pixel then bounded
  function view(iw, ih, vw, vh, dpr, k, tx, ty) {
    var w = iw * k / dpr, h = ih * k / dpr;
    return {k: k, w: w, h: h, tx: clampAxis(Math.round(tx * dpr) / dpr, w, vw), ty: clampAxis(Math.round(ty * dpr) / dpr, h, vh)};
  }
  function reset(iw, ih, vw, vh, dpr) {
    var k = fitLevel(iw, ih, vw, vh, dpr);
    return view(iw, ih, vw, vh, dpr, k, (vw - iw * k / dpr) / 2, (vh - ih * k / dpr) / 2);
  }
  // zoom to level k2 keeping the map point under (cx, cy) (view coordinates) in place
  function zoomAt(v, k2, cx, cy, iw, ih, vw, vh, dpr) {
    var f = k2 / v.k;
    return view(iw, ih, vw, vh, dpr, k2, cx - (cx - v.tx) * f, cy - (cy - v.ty) * f);
  }
  // map.json (src/rover/render/map_meta.py): `full` (map-full.png), `area` (map.png's frame), sha256 of each. A transform t: pixel =
  // t.ox + floor((x - t.x0) * t.p), inside [t.ox, t.ox + t.w). Malformed: null. Never guessed: `cropped` unknown = cropped.
  function num(v) { return typeof v === 'number' && isFinite(v); }
  function int(v) { return num(v) && Math.floor(v) === v; }
  function dim(v) { return int(v) && v >= 1 && v <= 4096; }
  function hex(v) {                                  // SHA-256: map.json's text or a digest's bytes
    if (typeof v === 'string') return /^[0-9a-f]{64}$/.test(v) ? v : null;
    var s = '';
    if (v && v.byteLength === 32) new Uint8Array(v).forEach(function (x) { s += (x < 16 ? '0' : '') + x.toString(16); });
    return s || null;
  }
  function parseMeta(txt) {
    var j = null, f, c, e, a, full = null, ov = null;
    if (typeof txt !== 'string' || txt.length > 262144) return null;
    try { j = JSON.parse(txt); } catch (x) { return null; }
    if (!j || typeof j !== 'object' || !int(j.sol) || j.sol < 0 || !num(j.cell_m) || !(j.cell_m > 0)) return null;
    f = j.full; a = j.area;
    if (f && typeof f === 'object' && dim(f.w) && dim(f.h) && int(f.x0) && int(f.y0) && (f.px_per_cell === 1 || f.px_per_cell === 2)) {
      c = f.cells; e = f.explored;
      full = {ox: 0, oy: 0, x0: f.x0, y0: f.y0, p: f.px_per_cell, w: f.w, h: f.h, cropped: f.cropped !== false,
              cells: (Array.isArray(c) && dim(c[0]) && dim(c[1])) ? c : [f.w / f.px_per_cell, f.h / f.px_per_cell],
              explored: (Array.isArray(e) && e.length === 4 && e.every(int) && e[2] >= 1 && e[3] >= 1 && e[2] <= 1e6 && e[3] <= 1e6) ? e : null,
              sha: hex(f.sha256)};
    }
    if (a && typeof a === 'object' && dim(j.w) && dim(j.h) && [a.x, a.y, a.x0, a.y0].every(int) && [a.w, a.h, a.scale, a.step].every(dim) &&
        a.x >= 0 && a.y >= 0 && a.x + a.w <= j.w && a.y + a.h <= j.h) {
      ov = {ox: a.x, oy: a.y, x0: a.x0, y0: a.y0, p: a.scale / a.step, w: a.w, h: a.h, sha: hex(j.sha256)};
    }
    return {sol: j.sol, cell_m: j.cell_m, full: full, ov: ov};
  }
  function toPx(t, x, y) { return [t.ox + Math.floor((x - t.x0) * t.p), t.oy + Math.floor((y - t.y0) * t.p)]; }
  function inImg(t, a) { return a[0] >= t.ox && a[1] >= t.oy && a[0] < t.ox + t.w && a[1] < t.oy + t.h; }
  function isPng(b, max) {
    if (!b || typeof b.byteLength !== 'number' || b.byteLength < 33 || b.byteLength > max) return false;
    var u = new Uint8Array(b, 0, 8), sig = [137, 80, 78, 71, 13, 10, 26, 10];
    for (var i = 0; i < 8; i++) if (u[i] !== sig[i]) return false;
    return true;
  }
  var api = {LEVELS: LEVELS, fitLevel: fitLevel, step: step, nearLevel: nearLevel, clampAxis: clampAxis, view: view, reset: reset, zoomAt: zoomAt,
             parseMeta: parseMeta, hex: hex, toPx: toPx, inImg: inImg, isPng: isPng};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0Map = api;
})(typeof self !== 'undefined' ? self : this);
