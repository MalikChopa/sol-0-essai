"""Rollouts of M0 (SPEC 4.6) and the batched drive loop shared with the test battery (SPEC 4.7).

Common random numbers: every candidate of a generation sees the same starts, the same targets, the same slip
and camera noise (keys depend on the episode number m only, never on the position in the batch)."""
from __future__ import annotations

import math

import numpy as np

from rover.agent.body import RoverBatch
from rover.agent.camera import camera_spec, capture
from rover.agent.physics import physics_step
from rover.brain.mlp import m2_descriptors, mlp_forward, visual_features
from rover.agent.sensors import observe
from rover.config import Params
from rover.core import dmath
from rover.core.exact import fsum, to_int
from rover.core.rng import derive, uniform
from rover.core.types import NonFiniteError, SolEvents
from rover.world.chunks import Window, World
from rover.world.climate import sun_at

Arr = np.ndarray
CALM = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])


def window_for(world: World, xs: Arr, ys: Arr, margin: float) -> Window:
    """Materialised window (chunk aligned) covering the box of (xs, ys) widened by `margin` cells."""
    cs = world.cs
    cx0 = to_int(np.floor((float(np.min(xs)) - margin) / cs))
    cy0 = to_int(np.floor((float(np.min(ys)) - margin) / cs))
    cx1 = to_int(np.floor((float(np.max(xs)) + margin) / cs))
    cy1 = to_int(np.floor((float(np.max(ys)) + margin) / cs))
    return world.window(cx0, cy0, cx1, cy1)


def margin_cells(params: Params, stage: int, ticks: int) -> float:
    _, _, R, _ = camera_spec(stage, params)
    return float(math.ceil(params.get("rover.v_max") * ticks) + math.ceil(R) + 8)


def drive_batch(win: Window, params: Params, stage: int, thetas: Arr, m2: dict, x0: Arr, y0: Arr, c0: Arr, s0: Arr,
                target: Arr, sun, k_slip: Arr, k_cam: Arr, ticks: int, ev: SolEvents = CALM) -> dict:
    """Drive B rovers towards their own targets with their own M0 (xi = 0). Returns per-rover arrays:
    progress (sum of distance decreases), effort (sum |uL|+|uR|), arrived, arrive_tick, tipped, stuck."""
    P = params.get
    B = x0.shape[0]
    arrive_r = float(P("brain.arrive_r"))
    period = int(P("rover.cam_period"))
    n_in, n_h, n_out = int(P("brain.m0.n_in")), int(P("brain.m0.hidden")), int(P("brain.m0.n_out"))
    rb = RoverBatch.from_rover({"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": 1.0, "stuck": False, "tipped": False,
                                "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0],
                                "mode": "DRIVE", "safe_pending": []}, B)
    rb.x, rb.y, rb.c, rb.s = x0.copy(), y0.copy(), c0.copy(), s0.copy()
    W, H, _, D = camera_spec(stage, params)
    prev_u = np.zeros((B, 2))
    f = None
    d = np.sqrt((target[:, 0] - rb.x) ** 2 + (target[:, 1] - rb.y) ** 2)
    progress = np.zeros(B)
    effort = np.zeros(B)
    done = d < arrive_r
    arrive_tick = np.where(done, 0, -1)
    for tick in range(ticks):
        if bool(np.all(done)):
            break
        if tick % period == 0:
            cam = capture(rb, win, stage, sun, ev, k_cam, tick, params)
            z = m2_descriptors(cam.index, cam.depth, cam.D)
            f = visual_features(z, m2["mean"], m2["var"], m2["w"])
        x = observe(rb, stage, target, sun, f, prev_u, params)
        y, _ = mlp_forward(thetas, x, n_in, n_h, n_out)
        u = np.clip(y, -1.0, 1.0)
        u = np.where(done[:, None], 0.0, u)
        rb.asleep = done.copy()
        physics_step(rb, u, win, sun, ev, k_slip, tick, None, params)
        prev_u = u
        d2 = np.sqrt((target[:, 0] - rb.x) ** 2 + (target[:, 1] - rb.y) ** 2)
        act = ~done
        progress = progress + np.where(act, d - d2, 0.0)
        effort = effort + np.where(act, np.abs(u[:, 0]) + np.abs(u[:, 1]), 0.0)
        d = d2
        newly = act & (d2 < arrive_r)
        arrive_tick = np.where(newly, tick + 1, arrive_tick)
        done = done | newly
    if not (bool(np.all(np.isfinite(progress))) and bool(np.all(np.isfinite(rb.x)))):
        raise NonFiniteError("m0")
    return {"progress": progress, "effort": effort, "arrived": arrive_tick >= 0, "arrive_tick": arrive_tick,
            "tipped": rb.tipped.copy(), "stuck": rb.stuck.copy(), "d_end": d}


def rollout_starts(seed: int, sol: int, gen: int, m: int, cx: float, cy: float, params: Params) -> tuple:
    """Start (x, y, heading c, s) and target for episode m of a generation (SPEC 4.6); independent of the candidates."""
    P = params.get
    key = derive(seed, "m0start", sol, gen, m)
    u = uniform(key, np.arange(6))
    r = P("brain.es.start_radius") * math.sqrt(float(u[0]))
    a = 2.0 * math.pi * float(u[1])
    x = cx + r * float(dmath.cos(a))
    y = cy + r * float(dmath.sin(a))
    h = 2.0 * math.pi * float(u[2])
    lo, hi = P("brain.es.target_range")
    dist = lo + (hi - lo) * float(u[3])
    t = 2.0 * math.pi * float(u[4])
    return x, y, float(dmath.cos(h)), float(dmath.sin(h)), x + dist * float(dmath.cos(t)), y + dist * float(dmath.sin(t))


def rollout_fitness(world: World, params: Params, stage: int, thetas: Arr, m2: dict, sol: int, gen: int, m_eps: int,
                    center: tuple) -> Arr:
    """Fitness of N candidates (SPEC 4.6): mean over m_eps episodes of
    progress - 0.002*effort - 2*tipped - 1*stuck_at_end + 5*arrived."""
    P = params.get
    es = P("brain.es")
    N = thetas.shape[0]
    seed = world.seed
    T = int(es["ticks"])
    st = [rollout_starts(seed, sol, gen, m, center[0], center[1], params) for m in range(m_eps)]
    xs = np.asarray([s[0] for s in st] + [s[4] for s in st])
    ys = np.asarray([s[1] for s in st] + [s[5] for s in st])
    win = window_for(world, xs, ys, margin_cells(params, stage, T))
    sun = sun_at(sol, 600, params)
    cols = lambda i: np.tile(np.asarray([s[i] for s in st], dtype=np.float64), N)       # candidate-major, episode minor
    k_slip = np.asarray([derive(seed, "slip", sol, 1, gen, m) for m in range(m_eps)] * N, dtype=np.uint64)
    k_cam = np.asarray([derive(seed, "cam", sol, 1, gen, m) for m in range(m_eps)] * N, dtype=np.uint64)
    tgt = np.stack([cols(4), cols(5)], axis=1)
    th = np.repeat(thetas, m_eps, axis=0)
    r = drive_batch(win, params, stage, th, m2, cols(0), cols(1), cols(2), cols(3), tgt, sun, k_slip, k_cam, T)
    fit = (r["progress"] - es["energy_pen"] * r["effort"] - es["tip_pen"] * r["tipped"]
           - es["stuck_pen"] * (r["stuck"] & ~r["arrived"]) + es["arrive_bonus"] * r["arrived"])
    out = np.zeros(N)
    fr = fit.reshape(N, m_eps)
    for i in range(N):
        out[i] = fsum(fr[i]) / m_eps
    return out
