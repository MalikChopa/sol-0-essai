"""Reference fingerprints of the world package (ARCH 6): chunks (all layers), overlays, sun, events."""
from __future__ import annotations

import numpy as np

from rover.core.hashing import sha256_hex
from rover.world.chunks import World
from rover.world.climate import sun_at
from rover.world.events import draw_events


def _h(*arrays) -> str:
    return "sha256:" + sha256_hex(b"".join(np.asarray(a).tobytes() for a in arrays))


def fingerprints(params) -> dict:
    seed = int(params.get("run.world_seed"))
    w = World(seed, params)
    out = {}
    for (cx, cy) in ((0, 0), (-1, 3), (1000, -1000)):
        c = w.chunk(cx, cy)
        out[f"world.chunk_{cx}_{cy}"] = _h(c.height, c.gtype)
        out[f"world.temp_{cx}_{cy}"] = _h(c.temp)
    overlays = [{"kind": "impact", "x": 5, "y": 8, "r": 9, "params": {}, "sol": 1},
                {"kind": "anomaly", "x": -20, "y": 30, "r": 1, "params": {}, "sol": 2},
                {"kind": "deposit", "x": 40, "y": 40, "r": 5, "params": {"substance": 3}, "sol": 3}]
    wo = World(seed, params, overlays)
    win = wo.window(-1, 0, 0, 0)
    out["world.overlays"] = _h(win.height, win.gtype)
    for sol_tick in (0, 5, 150, 450):
        s = sun_at(sol_tick, np.arange(0, 1200, 37), params)
        out[f"world.sun_sol{sol_tick}"] = _h(s.elev, s.dir_x, s.dir_y, s.dir_z, s.hour)
    out["world.sun"] = _h(sun_at(7, np.arange(0, 1200, 37), params).elev)
    prev = {"storm_left": 0}
    acc = []
    for sol in range(1, 4001):
        ev = draw_events(seed, sol, prev, (0.0, 0.0), params)
        prev = {"storm_left": ev.storm_left}
        acc.append([int(ev.storm), ev.storm_left] + [x for o in ev.new_overlays for x in (o["x"], o["y"], o["r"])] + [-1])
    flat = [v for row in acc for v in row]
    out["world.events_4000"] = _h(np.asarray(flat, dtype=np.int64))
    return out
