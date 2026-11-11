"""Chunks (64x64), windows and the World facade (SPEC 6.3)."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from rover.config import Params
from rover.core.exact import to_int
from rover.world import terrain

Arr = np.ndarray


@dataclass(frozen=True)
class Chunk:
    cx: int
    cy: int
    height: Arr
    gtype: Arr
    temp: Arr = None        # added by J1: temperature field T in [0, 1] (SPEC 2)


@dataclass
class Window:
    x0: int
    y0: int
    height: Arr
    gtype: Arr          # [y - y0, x - x0]
    temp: Arr = None    # added by J1 (None for hand-made windows: T = 0.5 then)
    _cg: tuple = None   # lazy cell gradients (gx, gy), m per cell, for the camera shading

    def temp_at(self, x: Arr, y: Arr) -> Arr:
        if self.temp is None:
            return np.full(np.asarray(x).shape, 0.5, dtype=np.float64)
        ix = to_int(np.floor(np.asarray(x, dtype=np.float64) + 0.5)) - self.x0
        iy = to_int(np.floor(np.asarray(y, dtype=np.float64) + 0.5)) - self.y0
        hh, ww = self.temp.shape
        if not bool(np.all((ix >= 0) & (iy >= 0) & (ix <= ww - 1) & (iy <= hh - 1))):
            raise ValueError("position outside the materialised window")
        return self.temp[iy, ix]

    def cell_gradient(self) -> tuple[Arr, Arr]:
        """Centred difference of the cell heights (m per cell; equals gradient_at at integer positions), edge-replicated."""
        if self._cg is None:
            P = np.pad(self.height, 1, mode="edge")
            self._cg = ((P[1:-1, 2:] - P[1:-1, :-2]) * 0.5, (P[2:, 1:-1] - P[:-2, 1:-1]) * 0.5)
        return self._cg

    def _bilin_idx(self, x, y):
        fx = np.floor(np.asarray(x, dtype=np.float64) - self.x0)
        fy = np.floor(np.asarray(y, dtype=np.float64) - self.y0)
        tx = np.asarray(x, dtype=np.float64) - self.x0 - fx
        ty = np.asarray(y, dtype=np.float64) - self.y0 - fy
        ix, iy = to_int(fx), to_int(fy)
        hh, ww = self.height.shape
        if not bool(np.all((ix >= 0) & (iy >= 0) & (ix + 1 <= ww - 1) & (iy + 1 <= hh - 1))):
            raise ValueError("position outside the materialised window")
        return ix, iy, tx, ty

    def height_at(self, x: Arr, y: Arr) -> Arr:
        ix, iy, tx, ty = self._bilin_idx(x, y)
        H = self.height
        a = H[iy, ix] + (H[iy, ix + 1] - H[iy, ix]) * tx
        b = H[iy + 1, ix] + (H[iy + 1, ix + 1] - H[iy + 1, ix]) * tx
        return a + (b - a) * ty

    def gtype_at(self, x: Arr, y: Arr) -> Arr:
        ix = to_int(np.floor(np.asarray(x, dtype=np.float64) + 0.5)) - self.x0
        iy = to_int(np.floor(np.asarray(y, dtype=np.float64) + 0.5)) - self.y0
        hh, ww = self.gtype.shape
        if not bool(np.all((ix >= 0) & (iy >= 0) & (ix <= ww - 1) & (iy <= hh - 1))):
            raise ValueError("position outside the materialised window")
        return self.gtype[iy, ix]

    def gradient_at(self, x: Arr, y: Arr) -> tuple[Arr, Arr]:
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        gx = self.height_at(x + 0.5, y) - self.height_at(x - 0.5, y)
        gy = self.height_at(x, y + 0.5) - self.height_at(x, y - 0.5)
        return gx, gy

    def contains(self, x: Arr, y: Arr, margin: float) -> Arr:
        hh, ww = self.height.shape
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        return ((x >= self.x0 + margin) & (x <= self.x0 + ww - 1 - margin)
                & (y >= self.y0 + margin) & (y <= self.y0 + hh - 1 - margin))


class World:
    def __init__(self, seed: int, params: Params, overlays: Sequence[dict] = ()):
        self.seed = int(seed)
        self.params = params
        self.overlays = [dict(o) for o in overlays]      # applied in order at chunk generation (SPEC 2)
        self.cs = int(params.get("world.chunk"))
        self._cache: OrderedDict = OrderedDict()
        self._max = int(params.get("world.cache_chunks"))

    def chunk(self, cx: int, cy: int) -> Chunk:
        key = (int(cx), int(cy))
        c = self._cache.get(key)
        if c is not None:
            self._cache.move_to_end(key)
            return c
        x0, y0 = key[0] * self.cs, key[1] * self.cs
        h, g = terrain.block(self.seed, x0, y0, self.cs, self.cs, self.params, self.overlays)
        t = terrain.temperature(self.seed, x0, y0, self.cs, self.cs, self.params)
        c = Chunk(key[0], key[1], h, g, t)
        self._cache[key] = c
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return c

    def window(self, cx0: int, cy0: int, cx1: int, cy1: int) -> Window:
        cs = self.cs
        H = np.zeros(((cy1 - cy0 + 1) * cs, (cx1 - cx0 + 1) * cs), dtype=np.float64)
        G = np.zeros(H.shape, dtype=np.uint8)
        T = np.zeros(H.shape, dtype=np.float64)
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                c = self.chunk(cx, cy)
                H[(cy - cy0) * cs:(cy - cy0 + 1) * cs, (cx - cx0) * cs:(cx - cx0 + 1) * cs] = c.height
                G[(cy - cy0) * cs:(cy - cy0 + 1) * cs, (cx - cx0) * cs:(cx - cx0 + 1) * cs] = c.gtype
                T[(cy - cy0) * cs:(cy - cy0 + 1) * cs, (cx - cx0) * cs:(cx - cx0 + 1) * cs] = c.temp
        return Window(cx0 * cs, cy0 * cs, H, G, T)

    def add_overlay(self, overlay: dict) -> None:
        """Append an overlay and drop the cached chunks it touches (SPEC 2). Windows already built are not updated."""
        o = dict(overlay)
        self.overlays.append(o)
        reach = float(o["r"]) * 1.3 + 3.0
        cs = self.cs
        cx0 = (to_int(np.floor((o["x"] - reach) / cs)))
        cx1 = (to_int(np.floor((o["x"] + reach) / cs)))
        cy0 = (to_int(np.floor((o["y"] - reach) / cs)))
        cy1 = (to_int(np.floor((o["y"] + reach) / cs)))
        for key in [k for k in self._cache if cx0 <= k[0] <= cx1 and cy0 <= k[1] <= cy1]:
            del self._cache[key]

    def gtype_cells(self, xs: Arr, ys: Arr) -> Arr:
        xs = np.asarray(xs, dtype=np.int64)
        ys = np.asarray(ys, dtype=np.int64)
        out = np.zeros(xs.shape, dtype=np.uint8)
        cx = np.floor_divide(xs, self.cs)
        cy = np.floor_divide(ys, self.cs)
        for ky, kx in np.unique(np.stack([cy.ravel(), cx.ravel()], axis=1), axis=0).tolist():
            sel = (cx == kx) & (cy == ky)
            out[sel] = self.chunk(kx, ky).gtype[ys[sel] - ky * self.cs, xs[sel] - kx * self.cs]
        return out

    def composition_at(self, x: float, y: float) -> Arr:
        # J0 stub: owner J9a (P2). Uniform composition; never drawn in any image.
        n = int(self.params.get("world.n_substances"))
        return np.full(n, 1.0 / n)
