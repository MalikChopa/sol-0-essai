"""Daily events (SPEC 2, EF-90, EF-91): storm, deposit, anomaly, comet impact. Pure function of (seed, sol, prev, rover position)."""
from __future__ import annotations

import math

import numpy as np

from rover.config import Params
from rover.core import dmath
from rover.core.exact import to_int
from rover.core.rng import derive, randint, uniform
from rover.core.types import SolEvents

# Draw indices inside the key derive(seed, "event", sol): 0..3 = the four occurrence tests; the rest are fixed parameters.
_K_STORM, _K_DEPOSIT, _K_ANOMALY, _K_IMPACT = 0, 1, 2, 3
_I_STORM_LEN = 10
_I_ANGLE = {"deposit": 20, "anomaly": 30, "impact": 40}
_I_DIST = {"deposit": 21, "anomaly": 31, "impact": 41}
_I_RADIUS = {"deposit": 22, "impact": 42}
_I_SUBST = 23


def _ri(key: int, idx: int, n: int) -> int:
    return int(randint(key, np.asarray(idx), n)[()])


def _cell(v) -> int:
    i = to_int(np.asarray(v))
    return int(i)


def _range(key: int, idx: int, lo: int, hi: int) -> int:
    return lo + _ri(key, idx, hi - lo + 1)


def _overlay(kind: str, key: int, rover_xy, dist_rng, params: Params, sol: int) -> dict:
    P = params.get
    ang = 2.0 * math.pi * float(uniform(key, np.asarray(_I_ANGLE[kind]))[()])
    d = dist_rng[0] + (dist_rng[1] - dist_rng[0]) * float(uniform(key, np.asarray(_I_DIST[kind]))[()])
    x = _cell(np.floor(rover_xy[0] + d * dmath.cos(ang) + 0.5))
    y = _cell(np.floor(rover_xy[1] + d * dmath.sin(ang) + 0.5))
    if kind == "deposit":
        r = _range(key, _I_RADIUS[kind], *P("events.deposit_radius"))
        return {"kind": kind, "x": x, "y": y, "r": r, "params": {"substance": _ri(key, _I_SUBST, int(P("events.deposit_substances")))}, "sol": int(sol)}
    if kind == "anomaly":
        return {"kind": kind, "x": x, "y": y, "r": 1, "params": {"height_m": P("events.anomaly_height")}, "sol": int(sol)}
    r = _range(key, _I_RADIUS[kind], *P("events.impact_radius"))
    return {"kind": kind, "x": x, "y": y, "r": r, "params": {"depth_m": P("events.impact_depth"), "rim_m": P("events.impact_rim")}, "sol": int(sol)}


def draw_events(seed: int, sol: int, prev: dict, rover_xy: tuple, params: Params) -> SolEvents:
    """`prev["storm_left"]` = sols of storm remaining after the previous sol; `storm_left` returned = remaining after this one.

    The occurrence of event k is `randint(derive(seed, "event", sol), k, one_in) == 0` (exact integer test)."""
    P = params.get
    key = derive(seed, "event", int(sol))
    left_prev = int(prev.get("storm_left", 0)) if prev else 0
    kinds = []
    storm_left = 0
    if left_prev > 0:                                            # no new storm during a storm
        storm = True
        storm_left = left_prev - 1
    else:
        storm = _ri(key, _K_STORM, int(P("events.storm_one_in"))) == 0
        if storm:
            lo, hi = P("events.storm_sols")
            storm_left = _range(key, _I_STORM_LEN, int(lo), int(hi)) - 1
    if storm:
        kinds.append("storm")
    overlays = []
    for kind, k, one_in in (("deposit", _K_DEPOSIT, "deposit_one_in"), ("anomaly", _K_ANOMALY, "anomaly_one_in"),
                            ("impact", _K_IMPACT, "impact_one_in")):
        if _ri(key, k, int(P("events." + one_in))) == 0:
            kinds.append(kind)
            overlays.append(_overlay(kind, key, rover_xy, P("events." + kind + "_dist"), params, sol))
    return SolEvents(storm=storm, storm_left=storm_left,
                     view_scale=P("events.storm_view") if storm else 1.0,
                     solar_factor=P("events.storm_solar") if storm else 1.0,
                     slip_add=P("events.storm_slip") if storm else 0.0,
                     new_overlays=overlays, kinds=kinds)
