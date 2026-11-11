"""Reference fingerprints of the agent package: camera (12 poses x 4 acuities, batch 1 / 12 / 96, night, storm) and physics."""
from __future__ import annotations

import numpy as np

from rover.agent.body import RoverBatch
from rover.agent.camera import capture
from rover.agent.physics import physics_step
from rover.core import dmath
from rover.core.hashing import sha256_hex
from rover.core.rng import derive
from rover.world.chunks import World
from rover.world.climate import sun_at
from rover.world.events import draw_events


def _fp(*arrays) -> str:
    return "sha256:" + sha256_hex(b"".join(np.asarray(a).tobytes() for a in arrays))


def _rover() -> dict:
    return {"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": 1.0, "stuck": False, "tipped": False, "asleep": False,
            "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "BABBLE", "safe_pending": []}


def poses(n: int) -> RoverBatch:
    """n fictitious poses (rover i has the pose of i mod 12) with distinct physical keys' worth of identity."""
    j = np.arange(n) % 12
    ang = j * 0.5236
    rb = RoverBatch.from_rover(_rover(), n)
    rb.x = j.astype(np.float64) * 7.0 - 40.0
    rb.y = j.astype(np.float64) * -5.0 + 20.0
    rb.c, rb.s = dmath.cos(ang), dmath.sin(ang)
    rb.pitch = j.astype(np.float64) * 0.02 - 0.1
    return rb


def fingerprints(params) -> dict:
    seed = int(params.get("run.world_seed"))
    w = World(seed, params)
    win = w.window(-3, -3, 3, 3)
    sun = sun_at(3, 600, params)
    ev = draw_events(seed, 3, {}, (0.0, 0.0), params)
    out = {}
    rb12 = poses(12)
    keys12 = np.asarray([derive(seed, "cam", 3, 0)] * 12, dtype=np.uint64)
    for stage in (0, 2, 3, 4):
        f = capture(rb12, win, stage, sun, ev, keys12, 16, params)
        out[f"agent.camera_stage{stage}_b12"] = _fp(f.index, f.depth)
        rb1 = poses(1)
        f1 = capture(rb1, win, stage, sun, ev, keys12[:1], 16, params)
        out[f"agent.camera_stage{stage}_b1"] = _fp(f1.index, f1.depth)
    rb96 = poses(96)
    keys96 = np.asarray([derive(seed, "cam", 3, 1 + i // 12, i % 12) for i in range(96)], dtype=np.uint64)
    for stage in (0, 3):
        f = capture(rb96, win, stage, sun, ev, keys96, 24, params)
        out[f"agent.camera_stage{stage}_b96"] = _fp(f.index, f.depth)
    night = sun_at(3, 1100, params)
    storm = type(ev)(storm=True, storm_left=1, view_scale=0.5, solar_factor=0.35, slip_add=0.05, new_overlays=[], kinds=["storm"])
    for stage in (2, 3):
        f = capture(rb12, win, stage, night, ev, keys12, 8, params)
        out[f"agent.camera_night_stage{stage}"] = _fp(f.index, f.depth)
        f = capture(rb12, win, stage, sun, storm, keys12, 8, params)
        out[f"agent.camera_storm_stage{stage}"] = _fp(f.index, f.depth)
    # physics: 12 rovers, 300 ticks, commands from the PRNG, day then night
    rb = poses(12)
    rb.x = rb.x * 0.5
    kslip = np.asarray([derive(seed, "slip", 3, 0)] * 12, dtype=np.uint64)
    from rover.core.rng import uniform
    for t in range(300):
        tick = 450 + 3 * t
        u = np.stack([uniform(derive(seed, "babble", t), np.arange(12)) * 2.0 - 1.0,
                      uniform(derive(seed, "babble", t, 1), np.arange(12)) * 2.0 - 1.0], axis=1)
        physics_step(rb, u, win, sun_at(3, tick, params), ev, kslip, tick, None, params)
    out["agent.physics_300"] = _fp(rb.x, rb.y, rb.c, rb.s, rb.battery, rb.stuck, rb.tipped, rb.slip, rb.odometer)
    return out
