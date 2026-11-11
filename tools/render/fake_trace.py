"""Fictitious traces with the structure of sim/trace.py (frozen), for render tests and tools/render/gif_matrix.py.
Every value is invented here; nothing comes from a real sol."""
from __future__ import annotations

import numpy as np

from rover.core import consts
from rover.core.types import BrainSnapshot, FrameRecord, Progress, SolEvents, Trace

ACUITY = {0: (8, 6), 1: (8, 6), 2: (32, 20), 3: (80, 50), 4: (160, 100), 5: (160, 100)}
SIGMA = {"day": 0.25, "night": 0.6, "storm": 0.8, "stress": 10.0}
STAGE_NAMES = ["AWAKENING", "FIRST MOVES", "LEARNING TO DRIVE", "ENERGY", "SAMPLING", "ANALYSIS"]


def terrain(xs, ys):
    return ((xs // 8) + 3 * (ys // 8)) % 4


def _scene(w: int, h: int, rng, cond: str, night: bool, t: int, flicker: bool) -> np.ndarray:
    if night and not flicker:
        return np.full((h, w), 22, dtype=np.uint8)
    horizon = max(1, int(0.35 * h))
    ys, xs = np.indices((h, w))
    img = np.zeros((h, w), dtype=np.float64)
    base = np.where(xs * 3 // max(1, w) == 0, 0, np.where(xs * 3 // max(1, w) == 1, 6, 12))
    level = 4.0 - 3.0 * (ys - horizon) / max(1, h - horizon) + 0.7 * ((xs + t // 3) % 7 == 0)
    sigma = SIGMA[cond]
    level = level + sigma * (2 * rng.random((h, w)) - 1)
    idx = base + np.clip(np.floor(level + 0.5), 0, 5)
    sky = 18 + np.minimum(3, (4 * (horizon - ys)) // horizon)
    out = np.where(ys < horizon, sky, idx).astype(np.uint8)
    if flicker:
        out = np.full((h, w), 17 if t % 4 < 2 else 22, dtype=np.uint8)
    return out


def make_trace(stage: int = 2, cond: str = "day", seed: int = 1, sol: int = 42, n: int = 150, flicker: bool = False,
               acuity: tuple | None = None) -> Trace:
    rng = np.random.default_rng(seed)
    w, h = acuity or ACUITY[stage]
    active = list(consts.M0_ACTIVE[stage])
    theta = (rng.standard_normal(434) * 0.25).astype(np.float32)
    snap = BrainSnapshot(stage=stage, m0=theta, m1=None, m2_w=None, m2_mean=None, m2_var=None, m3=None)
    from rover.core.mlp_layout import unpack_mlp
    W1, b1, W2, b2 = unpack_mlp(theta.astype(np.float64), 24, 16, 2)
    frames, seen = [], {}
    x, y, hd = 0.0, 0.0, 0.3
    asleep_all = cond == "night"
    for k in range(n):
        hour = (5.0 + 0.16 * k) % 24.0
        sleep = (asleep_all and k < 100) or (cond != "night" and (k < 6 or k > 143))
        if sleep:
            mode = "SLEEP"
        else:
            mode = "BABBLE" if stage < 2 else ("SEEK_SUN" if stage >= 3 and k % 40 > 30 else "DRIVE")
        hd += 0.05 * float(np.sin(k / 9.0))
        c, s = float(np.cos(hd)), float(np.sin(hd))
        if not sleep:
            x, y = x + 0.5 * c, y + 0.5 * s
        xin = np.zeros(24)
        vals = rng.uniform(-1, 1, 24)
        for i in active:
            xin[i] = vals[i]
        if sleep:
            xin[:] = 0.0
        hh = np.tanh(xin @ W1 + b1)
        yy = np.tanh(hh @ W2 + b2)
        xi = np.zeros(2) if sleep or stage >= 2 and k % 20 else 0.15 * rng.uniform(-1, 1, 2)
        u = np.clip(yy + xi, -1, 1)
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                seen.setdefault((int(x) + dx, int(y) + dy), 8 * k)
        frames.append(FrameRecord(
            tick=8 * k, hour=hour, mode=mode,
            cam_index=_scene(w, h, rng, cond, sleep, k, flicker), cam_depth=np.zeros((h, w), dtype=np.uint8), D=24,
            z=None if stage == 0 or sleep else rng.random(40), f=None if stage == 0 or sleep else rng.uniform(-1, 1, 8),
            x=xin, h=hh, y=yy, u=u, xi=xi,
            m1_pred=None if stage == 0 else rng.uniform(-1, 1, 3), m1_meas=rng.uniform(-1, 1, 3),
            m3_out=None if stage < 3 or sleep else rng.uniform(-1, 1, 3),
            speed=0.0 if sleep else 0.2 * float(rng.random()), battery=0.4 + 0.5 * float(rng.random()),
            pitch=0.05 * float(np.sin(k)), roll=0.04 * float(np.cos(k)), slip=float(rng.random()) * 0.3,
            solar=0.0, sun_elev=0.0 if sleep else 0.8, sun_dx=0.6, sun_dy=-0.8,
            pose=(x, y, c, s), target=None if stage < 2 else (x + 10 * c - 2 * s, y + 10 * s + 2 * c),
            stuck=(k == 70 and stage >= 2), tipped=False, asleep=sleep))
    arr = np.asarray([[a, b, t] for (a, b), t in seen.items()], dtype=np.int64).reshape(-1, 3)
    ev = SolEvents(storm=cond == "storm", storm_left=1 if cond == "storm" else 0, view_scale=0.5 if cond == "storm" else 1.0,
                   solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
    return Trace(sol=sol, stage=stage, acuity=(w, h), frames=frames, snapshot=snap, events=ev, seen=arr)


def make_state(trace: Trace) -> dict:
    last = trace.frames[-1].pose
    trail = np.asarray([[i * 1.5, i * 0.7 + 3 * float(np.sin(i / 3.0)), 0] for i in range(20)], dtype=np.float32)
    return {"sol": trace.sol, "stage": {"id": trace.stage, "consolidation": False}, "trail": trail, "origin": [0, 0],
            "rover": {"x": last[0], "y": last[1], "c": last[2], "s": last[3]}, "overlays": []}


def make_progress(stage: int) -> Progress:
    return Progress(0.81, STAGE_NAMES[stage], "13/20 test courses (need 16)", "metric")
