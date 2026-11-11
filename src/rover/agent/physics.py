"""Physics step (SPEC 3.2), vectorised over B rovers, in place."""
from __future__ import annotations

import numpy as np

from rover.agent.energy import energy_step
from rover.config import Params
from rover.core import consts, dmath
from rover.core.rng import gauss_ih4
from rover.core.types import SolEvents, Sun
from rover.world.chunks import Window

Arr = np.ndarray
_NAMES = ("rock", "sand", "dust", "ice")


def physics_step(rb, u: Arr, win: Window, sun: Sun, ev: SolEvents, keys: Arr, tick: int, drilling: Arr | None,
                 params: Params) -> None:
    R = params.get("rover")
    cm = params.get("world.cell_m")
    u = np.clip(np.asarray(u, dtype=np.float64), -1.0, 1.0)
    u = np.where(rb.asleep[:, None], 0.0, u)
    gt = win.gtype_at(rb.x, rb.y)                                              # 1. ground
    gx, gy = win.gradient_at(rb.x, rb.y)
    temp = win.temp_at(rb.x, rb.y)
    pitch = (gx * rb.c + gy * rb.s) / cm
    roll = (-gx * rb.s + gy * rb.c) / cm
    ul, ur = u[:, 0], u[:, 1]                                                  # 2. commands
    v_cmd = R["v_max"] * (ul + ur) * 0.5
    w_cmd = R["v_max"] * (ur - ul) / R["track"]
    n = np.abs(gauss_ih4(keys, np.asarray(tick)))                              # 3. slip
    mu = np.take(np.asarray([R["mu"][k] for k in _NAMES]), gt)
    sig = np.take(np.asarray([R["slip_sigma"][k] for k in _NAMES]), gt)
    fs = np.clip(1.0 - R["k_up"] * np.maximum(0.0, pitch) + R["k_down"] * np.maximum(0.0, -pitch), 0.0, R["fs_max"])
    k = np.clip(mu * fs * (1.0 - np.minimum(0.9, sig * n + ev.slip_add)), 0.0, 1.0)
    moving = np.abs(v_cmd) > 1e-6                                              # 4. effective motion
    v = v_cmd * k
    w = np.clip(w_cmd * k, -R["omega_max"], R["omega_max"])
    slip = np.where(moving, 1.0 - k, 0.0)
    blocked = rb.stuck | rb.tipped
    cmd = moving | (np.abs(w_cmd) > 1e-6)
    v = np.where(blocked, 0.0, v)
    w = np.where(blocked, 0.0, w)
    slip = np.where(blocked, np.where(cmd, 1.0, 0.0), slip)
    rb.c, rb.s = dmath.rot(rb.c, rb.s, w)                                      # 5. heading, position
    rb.x = rb.x + v * rb.c
    rb.y = rb.y + v * rb.s
    sinking = (gt == consts.GTYPE_SAND) & (slip > R["sink_slip"]) & ~blocked   # 6. sink, unstick, tip
    rb.sink_n = np.where(sinking, rb.sink_n + 1, 0)
    rb.stuck = rb.stuck | (rb.sink_n >= R["sink_ticks"])
    rev = rb.stuck & (ul < R["unstick_u"]) & (ur < R["unstick_u"])
    rb.rev_n = np.where(rev, rb.rev_n + 1, 0)
    free = rb.stuck & (rb.rev_n >= R["unstick_ticks"])
    rb.x = np.where(free, rb.x - R["unstick_back"] * rb.c, rb.x)
    rb.y = np.where(free, rb.y - R["unstick_back"] * rb.s, rb.y)
    rb.stuck = rb.stuck & ~free
    rb.rev_n = np.where(free, 0, rb.rev_n)
    rb.sink_n = np.where(free, 0, rb.sink_n)
    rb.tipped = rb.tipped | (np.abs(roll) > R["tip_roll"]) | (np.abs(pitch) > R["tip_pitch"])
    rb.enc_l = (v - w * R["track"] * 0.5) / R["v_max"]
    rb.enc_r = (v + w * R["track"] * 0.5) / R["v_max"]
    rb.odometer = rb.odometer + np.abs(v)
    rb.pitch, rb.roll, rb.slip = pitch, roll, slip
    energy_step(rb, u, pitch, gx, gy, sun, ev, params, drilling, temp)               # 7. energy
