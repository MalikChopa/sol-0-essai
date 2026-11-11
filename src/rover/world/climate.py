"""Seasons and the sun (SPEC 2)."""
from __future__ import annotations

import math

import numpy as np

from rover.config import Params
from rover.core import dmath
from rover.core.types import Sun

Arr = np.ndarray


def sun_at(sol: int, tick, params: Params) -> Sun:
    P = params.get
    year = 4 * int(P("world.season_sols"))
    phi = (int(sol) % year) / year
    sp = dmath.sin(2.0 * math.pi * phi)
    L = P("world.day_base_h") + P("world.day_amp_h") * sp
    t = np.asarray(tick, dtype=np.float64)
    h = P("run.start_hour") + 24.0 * t / P("run.ticks_per_sol")
    h = h - 24.0 * np.floor(h / 24.0)
    lever = 12.0 - L / 2.0
    u = (h - lever) / L
    su = dmath.sin(math.pi * u)
    elev = np.maximum(0.0, su) * ((1.0 - P("world.elev_season_amp")) + P("world.elev_season_amp") * sp)
    ax = dmath.cos(math.pi * u)
    ay = -0.35 * su
    n = np.sqrt(ax * ax + ay * ay)
    return Sun(elev=elev, dir_x=ax / n, dir_y=ay / n, dir_z=elev, hour=h, day_length=float(L))
