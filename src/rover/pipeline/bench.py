"""`rover bench`: wall-clock of the steps of one sol (informative, never compared; EN-06 / EF-03 follow-up)."""
from __future__ import annotations

import time

from rover.config import Params
from rover.pipeline.sol import fresh_state, run_sol
from rover.state import Explored, encode_files

STEPS = ("fresh_state", "sol_nosave", "sol_render", "encode")


def bench(params: Params, only: list | None = None) -> dict:
    """Seconds per step (monotonic clock). Unknown names in `only` raise ValueError."""
    only = list(STEPS) if not only else list(only)
    for n in only:
        if n not in STEPS:
            raise ValueError(f"unknown bench step {n!r}; known: {','.join(STEPS)}")
    out = {}
    state = None
    res = None
    if "fresh_state" in only or any(n in only for n in STEPS[1:]):
        t = time.monotonic()
        state = fresh_state(params)
        out["fresh_state"] = round(time.monotonic() - t, 3)
    if "sol_nosave" in only:
        t = time.monotonic()
        run_sol(state, Explored(), params, "2026-11-11T07:17:00Z", render=False, narrative=False)
        out["sol_nosave"] = round(time.monotonic() - t, 3)
    if "sol_render" in only or "encode" in only:
        t = time.monotonic()
        res = run_sol(state, Explored(), params, "2026-11-11T07:17:00Z")
        out["sol_render"] = round(time.monotonic() - t, 3)
    if "encode" in only:
        t = time.monotonic()
        encode_files(res.state, res.explored, res.images, res.status)
        out["encode"] = round(time.monotonic() - t, 3)
    return {k: out[k] for k in only if k in out}
