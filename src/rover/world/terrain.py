"""Height, ground type and temperature of a block of cells (SPEC 2). Pure function of (seed, coordinates, world params, overlays)."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from rover.config import Params
from rover.core import consts
from rover.core.noise import fbm
from rover.core.rng import derive

Arr = np.ndarray


def _impact_delta(X: Arr, Y: Arr, o: dict, depth: float, rim: float) -> Arr:
    """Crater of radius r: bowl -depth*(1 - (d/r)^2) inside, rim bump up to +rim over [r, 1.3 r] (continuous at d = r)."""
    r = float(o["r"])
    dx = X - float(o["x"])
    dy = Y - float(o["y"])
    d = np.sqrt(dx * dx + dy * dy) / r
    bowl = -depth * (1.0 - d * d)
    t = (d - 1.0) / 0.3
    bump = rim * 4.0 * t * (1.0 - t)
    return np.where(d < 1.0, bowl, np.where(d < 1.3, bump, 0.0))


def block(seed: int, x0: int, y0: int, w: int, h: int, params: Params, overlays: Sequence[dict] = ()) -> tuple[Arr, Arr]:
    """(height m float64, gtype uint8), shape (h, w), cells x0..x0+w-1, y0..y0+h-1. One cell of halo for the slope.

    Overlays are applied in list order, to the height (halo included, so the slope is identical on both sides of a
    chunk border) and to the ground type (SPEC 2)."""
    P = params.get
    xs = x0 - 1 + np.arange(w + 2, dtype=np.float64)
    ys = y0 - 1 + np.arange(h + 2, dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)
    e = fbm(derive(seed, "height"), X, Y, P("world.h_octaves"), P("world.h_wavelength"), P("world.h_gain"))
    dune = fbm(derive(seed, "dune"), X, Y, P("world.dune_octaves"), P("world.dune_wavelength"))
    base = P("world.h_amp_m") * e * e + P("world.dune_amp_m") * dune
    force_rock = np.zeros((h + 2, w + 2), dtype=bool)
    force_dust = np.zeros((h + 2, w + 2), dtype=bool)
    for o in overlays:
        k = o["kind"]
        if k == "impact":
            base = base + _impact_delta(X, Y, o, P("events.impact_depth"), P("events.impact_rim"))
            force_rock = force_rock | (np.sqrt((X - o["x"]) * (X - o["x"]) + (Y - o["y"]) * (Y - o["y"])) < float(o["r"]) * 1.3)
        elif k == "anomaly":
            hit = (np.abs(X - o["x"]) <= float(o["r"])) & (np.abs(Y - o["y"]) <= float(o["r"]))
            base = base + np.where(hit, P("events.anomaly_height"), 0.0)
            force_dust = force_dust | hit
            force_rock = force_rock & ~hit
        # "deposit": composition only (P2), no effect on height or type
    gx = (base[1:-1, 2:] - base[1:-1, :-2]) * 0.5
    gy = (base[2:, 1:-1] - base[:-2, 1:-1]) * 0.5
    slope = np.sqrt(gx * gx + gy * gy) / P("world.cell_m")
    g = fbm(derive(seed, "grain"), X, Y, P("world.g_octaves"), P("world.g_wavelength"))[1:-1, 1:-1]
    ei = e[1:-1, 1:-1]
    rock = (slope > P("world.rock_slope")) | (g < P("world.rock_g")) | force_rock[1:-1, 1:-1]
    gt = np.where(rock, consts.GTYPE_ROCK,
                  np.where(ei > P("world.ice_e"), consts.GTYPE_ICE,
                           np.where(g < P("world.sand_g"), consts.GTYPE_SAND, consts.GTYPE_DUST)))
    gt = np.where(force_dust[1:-1, 1:-1], consts.GTYPE_DUST, gt)
    bump = P("world.rock_amp_m") * fbm(derive(seed, "rock"), X, Y, P("world.rock_octaves"), P("world.rock_wavelength"))[1:-1, 1:-1]
    height = base[1:-1, 1:-1] + np.where(gt == consts.GTYPE_ROCK, bump, 0.0)
    return height, np.asarray(gt, dtype=np.uint8)


def temperature(seed: int, x0: int, y0: int, w: int, h: int, params: Params) -> Arr:
    """T = fbm("temp", 3, 512) in [0, 1], shape (h, w) (SPEC 2, cold of the night)."""
    P = params.get
    X, Y = np.meshgrid(x0 + np.arange(w, dtype=np.float64), y0 + np.arange(h, dtype=np.float64))
    return fbm(derive(seed, "temp"), X, Y, P("world.t_octaves"), P("world.t_wavelength"))
