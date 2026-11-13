/* Sol-0 live page v2: layout maths (DESIGN.md §3), pure functions (node tests: tests/page/layout.test.js).
   One 640x360 rendering, cut into panels by copying pixels. Landscape window: the whole console, as large as the window allows;
   portrait window: the panels stacked, each as wide as the screen. Scale: an integer number of device pixels per console pixel when it
   fills enough of the space, else fractional; never under one device pixel per console pixel (a column would vanish: a value lies). */
(function (root) {
  'use strict';
  // panel rectangles in console pixels, frames included (console.js)
  var PANELS = {cam: [7, 23, 322, 202], brain: [336, 24, 296, 200], map: [7, 231, 122, 122], tel: [136, 232, 248, 120], inst: [392, 232, 240, 120]};
  var ORDER = ['cam', 'brain', 'map', 'tel', 'inst'];
  var GROUPS = [['cam'], ['brain'], ['map', 'tel'], ['inst']];
  var GAP = 4;                       // console pixels between the panels of a group
  // CSS heights (live.css: #top, #bar, html.compact #top / #bar, the view's bottom padding in compact mode; tests/page/layout.test.js)
  var CHROME = {header: 44, bar: 32, details: 28, margin: 8, compact: 32, compactBar: 26, compactBottom: 4, overlayBar: 44};
  var W = 640, H = 360;

  // fit a natW x natH picture in a box (CSS px) at device pixel ratio dpr
  function fit(natW, natH, boxW, boxH, dpr) {
    dpr = dpr || 1;
    var s = Math.min(boxW / natW, boxH / natH), sd = s * dpr, k = Math.floor(sd + 1e-9), thr = dpr < 2 ? 0.80 : 0.90, scale, integer, floor = false;
    if (!(sd >= 1)) { scale = 1 / dpr; integer = true; floor = true; }             // one device pixel per console pixel at least
    else if (k >= 1 && k / sd >= thr) { scale = k / dpr; integer = true; }
    else { var devW = Math.floor(natW * sd + 1e-6); scale = devW / (natW * dpr); integer = false; }
    return {cssW: natW * scale, cssH: natH * scale, scale: scale, integer: integer, floor: floor, k: integer ? Math.round(scale * dpr) : null};
  }
  function chooseMode(vw, vh) { return vw >= vh ? 'console' : 'panels'; }
  function isCompact(mode, vh) { return mode === 'console' && vh < 500; }
  function insetOf(i) { return {l: (i && i.l) || 0, r: (i && i.r) || 0, t: (i && i.t) || 0, b: (i && i.b) || 0}; }
  // the console box from what the page measures (app.js): the stage's width, its top in the page, the height of « Details ». Console
  // mode has one status row above the stage (the stage and the next sol join #bar: the console's size never changes at the end of a
  // sol). Compact mode (phone in landscape): « Details » is under the fold, only the view's bottom padding is kept (VERIF-rc14 I2).
  function stageBox(vh, compact, stageW, stageTop, detailsH) {
    var below = compact ? CHROME.compactBottom : Math.min(detailsH > 0 ? detailsH : CHROME.details, 40) + 2 * CHROME.margin;
    return {w: stageW, h: Math.max(160, Math.floor(vh - stageTop - below))};
  }
  // the console box, from the window size and the CSS heights (when the page cannot measure #stage, and the tests): the same function
  // as the measured path, with the stage's top = the header and the status row
  function consoleBox(vw, vh, ins) {
    ins = insetOf(ins);
    var w = vw - Math.max(CHROME.margin, ins.l) - Math.max(CHROME.margin, ins.r), compact = isCompact('console', vh);
    var top = ins.t + (compact ? CHROME.compact + CHROME.compactBar : CHROME.header + CHROME.bar);
    return stageBox(vh - ins.b, compact, w, top, CHROME.details);
  }
  // panels (portrait): each group fits {stage width, 0.7 x window height}; a group of several panels is split into single panels when
  // it would be under 1.25x its natural size side by side
  function panelsPlan(stageW, vh, dpr) {
    var box = {w: stageW, h: 0.7 * vh}, out = {groups: [], panels: {}};
    GROUPS.forEach(function (g) {
      var natW = 0, natH = 0;
      g.forEach(function (id, i) { natW += PANELS[id][2] + (i ? GAP : 0); natH = Math.max(natH, PANELS[id][3]); });
      var split = g.length > 1 && box.w / natW < 1.25;
      if (!split) {
        var f = fit(natW, natH, box.w, box.h, dpr);
        g.forEach(function (id) { out.panels[id] = {cssW: PANELS[id][2] * f.scale, cssH: PANELS[id][3] * f.scale, scale: f.scale, integer: f.integer, floor: f.floor}; });
        out.groups.push({ids: g, split: false, gap: GAP * f.scale});
      } else {
        g.forEach(function (id) { out.panels[id] = fitPanel(id, box.w, box.h, dpr); });
        out.groups.push({ids: g, split: true, gap: 0});
      }
    });
    return out;
  }
  function fitPanel(id, boxW, boxH, dpr) { var p = PANELS[id], f = fit(p[2], p[3], boxW, boxH, dpr); return f; }
  // the enlarged panel: the window minus 8 px each side (and safe areas), minus the 44 px bar
  function overlayFit(id, vw, vh, dpr, ins) {
    ins = insetOf(ins);
    var w = vw - Math.max(CHROME.margin, ins.l) - Math.max(CHROME.margin, ins.r), h = vh - 2 * CHROME.margin - CHROME.overlayBar - ins.t - ins.b;
    var f = fitPanel(id, w, h, dpr), p = PANELS[id];
    f.rotate = vw < vh && p[2] > p[3] && f.scale < 1.5;          // « rotate your device » hint
    return f;
  }
  // whole plan for a window (tests; the page measures #stage instead of using consoleBox when it can)
  function plan(vw, vh, dpr, ins) {
    var mode = chooseMode(vw, vh), r = {mode: mode, compact: isCompact(mode, vh)};
    if (mode === 'console') { var b = consoleBox(vw, vh, ins); r.box = b; r.console = fit(W, H, b.w, b.h, dpr); }
    else {
      ins = insetOf(ins);
      var sw = vw - Math.max(CHROME.margin, ins.l) - Math.max(CHROME.margin, ins.r);
      r.stageW = sw; var pp = panelsPlan(sw, vh, dpr); r.panels = pp.panels; r.groups = pp.groups;
    }
    r.overlay = {};
    ORDER.forEach(function (id) { r.overlay[id] = overlayFit(id, vw, vh, dpr, ins); });
    return r;
  }
  // position of each panel on the whole console, in % (the clickable zones .hit-* of live.css)
  function cssPercents(id) {
    var p = PANELS[id];
    return {left: 100 * p[0] / W, top: 100 * p[1] / H, width: 100 * p[2] / W, height: 100 * p[3] / H};
  }
  // a CSS offset rounded to the device pixel (an integer scale stays crisp)
  function snap(v, dpr) { dpr = dpr || 1; return Math.round(v * dpr) / dpr; }

  var api = {PANELS: PANELS, ORDER: ORDER, GROUPS: GROUPS, GAP: GAP, CHROME: CHROME, fit: fit, chooseMode: chooseMode, isCompact: isCompact,
             consoleBox: consoleBox, stageBox: stageBox, panelsPlan: panelsPlan, overlayFit: overlayFit, plan: plan, cssPercents: cssPercents, snap: snap};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Sol0Layout = api;
})(typeof self !== 'undefined' ? self : this);
