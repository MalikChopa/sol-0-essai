"""Driving module M0: exploration noise, target choice and sun seeking (SPEC 4.2)."""
from __future__ import annotations

import math

import numpy as np

from rover.agent.energy import panel_factor
from rover.core.exact import to_int
from rover.core.rng import uniform

Arr = np.ndarray
_C = math.sqrt(0.5)
DIRS = ((1.0, 0.0), (_C, _C), (0.0, 1.0), (-_C, _C), (-1.0, 0.0), (-_C, -_C), (0.0, -1.0), (_C, -_C))
_TABLES: dict = {}


def babble_noise(keys: Arr, tick: int, amp: float, segment: int = 20) -> Arr:
    """xi (B, 2): held for `segment` ticks, uniform on [-amp, amp]; key independent of the batch (SPEC 3.2)."""
    seg = tick // segment
    j = 2 * seg + np.arange(2)
    return amp * (2.0 * uniform(np.asarray(keys)[:, None], j[None, :]) - 1.0)


def _sector_table(radius: int) -> tuple[Arr, Arr, Arr]:
    """Integer offsets (dx, dy) inside the disk of `radius` cells and the 45-degree sector (0..7) of each one."""
    t = _TABLES.get(radius)
    if t is None:
        r = np.arange(-radius, radius + 1)
        dy, dx = np.meshgrid(r, r, indexing="ij")
        dx, dy = dx.ravel(), dy.ravel()
        keep = (dx * dx + dy * dy <= radius * radius) & ((dx != 0) | (dy != 0))
        dx, dy = dx[keep], dy[keep]
        dots = np.stack([dx * d[0] + dy * d[1] for d in DIRS], axis=1)
        t = (dx, dy, np.argmax(dots, axis=1))
        _TABLES[radius] = t
    return t


def explore_target(x: float, y: float, win, mask: Arr, params) -> tuple[float, float]:
    """Among 8 directions k*45 degrees, the one with the most unexplored cells in its 45-degree sector within 40 cells
    (real mask; cells outside the window count as explored); ties -> smallest k; target at 30 cells."""
    P = params.get
    dx, dy, sec = _sector_table(int(P("brain.target_sector_r")))
    ix = to_int(np.floor(x + 0.5)) + dx - win.x0
    iy = to_int(np.floor(y + 0.5)) + dy - win.y0
    h, w = mask.shape
    inside = (ix >= 0) & (iy >= 0) & (ix < w) & (iy < h)
    unk = inside & (np.take(mask.ravel(), np.where(inside, iy * w + ix, 0)) == 0)
    cnt = np.bincount(sec[unk], minlength=8)
    k = int(np.argmax(cnt))
    d = float(P("brain.target_dist"))
    return x + d * DIRS[k][0], y + d * DIRS[k][1]


def sun_target(x: float, y: float, win, mask: Arr, sun, params) -> tuple[float, float] | None:
    """SEEK_SUN: among 16 candidate cells (8 directions x radii 6 and 12 <= sun_search_r), the explored ones; the one
    with the best `panel` factor at the current sun. None when none is explored."""
    R = float(params.get("brain.sun_search_r"))
    cx, cy = float(to_int(np.floor(x + 0.5))), float(to_int(np.floor(y + 0.5)))
    cand = [(cx + r * d[0], cy + r * d[1]) for r in (R / 2.0, R) for d in DIRS]
    px = np.asarray([c[0] for c in cand])
    py = np.asarray([c[1] for c in cand])
    ix = to_int(np.floor(px + 0.5)) - win.x0
    iy = to_int(np.floor(py + 0.5)) - win.y0
    h, w = mask.shape
    ok = (ix >= 1) & (iy >= 1) & (ix < w - 1) & (iy < h - 1)
    ok = ok & (np.take(mask.ravel(), np.where(ok, iy * w + ix, 0)) == 1)
    if not bool(np.any(ok)):
        return None
    gx, gy = win.gradient_at(np.where(ok, px, cx), np.where(ok, py, cy))
    score = np.where(ok, panel_factor(gx, gy, sun, params), -1.0)
    k = int(np.argmax(score))
    return float(px[k]), float(py[k])
