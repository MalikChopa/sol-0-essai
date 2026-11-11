"""Helpers of the agent tests (imported as `agent_helpers`): fictitious windows and rover batches."""
from __future__ import annotations

import numpy as np
import pytest

from rover.agent.body import RoverBatch
from rover.core import consts, dmath
from rover.core.rng import derive
from rover.world import World
from rover.world.chunks import Window

SEED = 31337


def rover_dict(**kw) -> dict:
    d = {"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": 1.0, "stuck": False, "tipped": False, "asleep": False,
         "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "BABBLE", "safe_pending": []}
    d.update(kw)
    return d


def make_window(height_fn, gtype, size=(400, 400), x0=-200, y0=-200, temp=None) -> Window:
    xs = x0 + np.arange(size[0], dtype=np.float64)
    ys = y0 + np.arange(size[1], dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)
    h = np.asarray(height_fn(X, Y), dtype=np.float64)
    g = np.full(h.shape, gtype, dtype=np.uint8)
    return Window(x0, y0, h, g, temp)


def random_batch(n: int, seed: int, spread: float = 80.0) -> RoverBatch:
    r = np.random.default_rng(seed)                       # test data only
    rb = RoverBatch.from_rover(rover_dict(), n)
    rb.x = r.uniform(-spread, spread, n)
    rb.y = r.uniform(-spread, spread, n)
    a = r.uniform(-3.1, 3.1, n)
    rb.c, rb.s = dmath.cos(a), dmath.sin(a)
    rb.battery = r.uniform(0.3, 1.0, n)
    return rb


def keys_for(n: int, domain: str = "cam", sol: int = 5) -> np.ndarray:
    return np.asarray([derive(SEED, domain, sol, 0, i) for i in range(n)], dtype=np.uint64)


def take(rb: RoverBatch, idx) -> RoverBatch:
    """Sub-batch (copy) of the rovers `idx`."""
    out = RoverBatch.from_rover(rover_dict(), len(idx))
    for f in ("x", "y", "c", "s", "battery", "stuck", "tipped", "asleep", "sink_n", "rev_n", "enc_l", "enc_r", "pitch",
              "roll", "slip", "solar_in", "odometer", "breakdowns", "forced_sleep_ticks", "forced"):
        setattr(out, f, np.asarray(getattr(rb, f))[idx].copy())
    return out

