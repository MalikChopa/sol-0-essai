"""map.png: explored area with 3-state fog of war, built from the real state (SPEC 7.6).

Unknown = BG; explored = camera ramp level 1; seen during the last sol (cells of Trace.seen) = level 3.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from rover.config import Params
from rover.core.consts import RAMP_BASE
from rover.core.exact import to_int
from rover.core.types import Trace
from rover.render import draw, font
from rover.render.gif import _palette_bytes
from rover.render.palette import BG, MARK, hud
from rover.state.explored import CH, Explored

ZX, ZY, ZW, ZH = 20, 30, 600, 330
_RAMP = np.asarray([RAMP_BASE[g] for g in range(4)], dtype=np.int64)


def frame_box(explored: Explored, state: dict) -> tuple:
    """Bounding box (x0, x1, y0, y1) of the explored chunks + 10 cells (or around the rover if nothing is explored)."""
    keys = explored.chunk_keys()
    r = state["rover"]
    if keys:
        return (min(k[0] for k in keys) * CH - 10, (max(k[0] for k in keys) + 1) * CH + 10,
                min(k[1] for k in keys) * CH - 10, (max(k[1] for k in keys) + 1) * CH + 10)
    rx, ry = to_int(np.floor(r["x"])), to_int(np.floor(r["y"]))
    return rx - 32, rx + 32, ry - 32, ry + 32


def _bar_length(P, scale_px_per_cell: float) -> tuple:
    cell_m = P("world.cell_m")
    best = (100, 100.0 / cell_m * scale_px_per_cell)
    for m in (100, 500, 1000, 5000):
        px = m / cell_m * scale_px_per_cell
        if px <= 300.0:
            best = (m, px)
    return best


def map_png(state: dict, explored: Explored, terrain, trace: Trace | None, params: Params) -> bytes:
    P = params.get
    mw, mh = P("render.map_size")
    img = np.full((mh, mw), BG, dtype=np.uint8)
    font.draw_text(img, 20, 12, "MAP | SOL-0", hud(10), 1)
    x0, x1, y0, y1 = frame_box(explored, state)
    bw, bh = x1 - x0, y1 - y0
    scale = min(P("render.map_px_per_cell_max"), ZW // bw, ZH // bh)
    step = 1
    if scale < 1:                                   # more cells than pixels: one cell sampled per pixel (nearest)
        scale = 1
        step = max(-(-bw // ZW), -(-bh // ZH))
    ncx, ncy = min(ZW // scale, -(-bw // step)), min(ZH // scale, -(-bh // step))
    mask = explored.window_mask(x0, y0, bw, bh)[::step, ::step][:ncy, :ncx]
    seen_full = np.zeros((bh, bw), dtype=np.uint8)
    if trace is not None and trace.seen.shape[0]:
        sx, sy = trace.seen[:, 0] - x0, trace.seen[:, 1] - y0
        ok = (sx >= 0) & (sy >= 0) & (sx < bw) & (sy < bh)
        seen_full[sy[ok], sx[ok]] = 1
    seen_now = seen_full[::step, ::step][:ncy, :ncx]
    gx, gy = np.meshgrid(x0 + step * np.arange(mask.shape[1], dtype=np.int64), y0 + step * np.arange(mask.shape[0], dtype=np.int64))
    known = mask == 1
    gt = np.zeros(mask.shape, dtype=np.int64)
    if bool(np.any(known)):
        gt[known] = terrain(gx[known], gy[known])
    level = np.where(seen_now == 1, 3, 1)
    cells = np.where(known, np.take(_RAMP, gt) + level, BG)
    big = np.repeat(np.repeat(cells, scale, axis=0), scale, axis=1)
    img[ZY:ZY + big.shape[0], ZX:ZX + big.shape[1]] = to_int(big, np.uint8)
    draw.frame_rect(img, ZX - 1, ZY - 1, ZW + 2, ZH + 2, hud(4))
    ppc = scale / step                                  # pixels per cell

    def px(cx, cy):
        return ZX + to_int(np.floor((cx - x0) * ppc)), ZY + to_int(np.floor((cy - y0) * ppc))

    def inside(a, b):
        return ZX <= a < ZX + ZW and ZY <= b < ZY + ZH

    tr = state["trail"]
    n = tr.shape[0]
    for k in range(1, n):
        a0, b0 = px(float(tr[k - 1, 0]), float(tr[k - 1, 1]))
        a1, b1 = px(float(tr[k, 0]), float(tr[k, 1]))
        if inside(a0, b0) and inside(a1, b1):
            draw.line(img, a0, b0, a1, b1, hud(3 + (7 * k) // max(1, n - 1)))
    ox, oy = px(state["origin"][0], state["origin"][1])
    if inside(ox, oy):
        for d in range(4):
            draw.rect(img, ox - d, oy - 3 + d, 2 * d + 1, 1, MARK)
    for ov in state.get("overlays", []):
        if ov.get("kind") == "anomaly" and ov.get("seen_sol", 0):
            ax, ay = px(ov["x"], ov["y"])
            if inside(ax, ay):
                for d in range(-3, 4):
                    draw.rect(img, ax - (3 - abs(d)), ay + d, 2 * (3 - abs(d)) + 1, 1, MARK)
    r = state["rover"]
    rx, ry = px(r["x"], r["y"])
    if inside(rx, ry):
        draw.ring(img, rx, ry, 4, hud(10))
        draw.ring(img, rx, ry, 3, hud(10))
    km2 = explored.cells() * P("world.cell_m") * P("world.cell_m") / 1e6
    t = "%.2f km2 explored" % km2
    font.draw_text(img, 620 - font.text_width(t), 12, t, hud(10), 1)
    bar_m, bar_px = _bar_length(P, ppc)
    bp = to_int(np.floor(bar_px))
    draw.rect(img, 20, mh - 30, bp, 2, hud(10))
    draw.rect(img, 20, mh - 33, 1, 8, hud(10))
    draw.rect(img, 20 + bp - 1, mh - 33, 1, 8, hud(10))
    font.draw_text(img, 20, mh - 20, "%d km" % (bar_m // 1000) if bar_m >= 1000 else "%d m" % bar_m, hud(10), 1)
    # legend: shape + text (state never carried by colour alone)
    lx, ly = 150, mh - 28
    for name, level_idx in (("explored", 1), ("seen this sol", 3)):
        draw.rect(img, lx, ly + 1, 8, 8, int(_RAMP[1]) + level_idx)
        draw.frame_rect(img, lx - 1, ly, 10, 10, hud(4))
        font.draw_text(img, lx + 14, ly + 1, name, hud(10), 1)
        lx += 14 + font.text_width(name) + 12
    for d in range(4):
        draw.rect(img, lx + 4 - d, ly + 1 + d, 2 * d + 1, 1, MARK)
    font.draw_text(img, lx + 14, ly + 1, "start", hud(10), 1)
    lx += 14 + font.text_width("start") + 12
    draw.ring(img, lx + 4, ly + 5, 4, hud(10))
    font.draw_text(img, lx + 14, ly + 1, "rover", hud(10), 1)
    lx += 14 + font.text_width("rover") + 12
    for d in range(-3, 4):
        draw.rect(img, lx + 4 - (3 - abs(d)), ly + 5 + d, 2 * (3 - abs(d)) + 1, 1, MARK)
    font.draw_text(img, lx + 14, ly + 1, "anomaly", hud(10), 1)
    im = Image.frombytes("P", (mw, mh), img.tobytes())
    im.putpalette(_palette_bytes())
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
