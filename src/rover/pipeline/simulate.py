"""`rover simulate`: the same run_sol without rendering or writing (ARCH 4)."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from rover.config import Params
from rover.core.hashing import sha256_hex
from rover.pipeline.sol import fresh_state, run_sol
from rover.state import Explored, core_bytes, core_for_compare


def simulate(n_sols: int, params: Params, seed: int, report: Path | None, workers: int = 1,
             start: tuple | None = None) -> dict:
    """`workers` is accepted and ignored: the learning code runs single-process (same result for any value).
    `start` (addition J5, `--from DIR`) = (state, explored) loaded by the CLI; the seed is then the state's."""
    state, explored = (fresh_state(params, seed), Explored()) if start is None else (start[0], start[1].copy())
    rows = ["sol,stage,couples,distance_m,awake_cells,breakdowns,attempts"]
    keep = int(params.get("run.checkpoints"))
    ckpts: dict = {}                    # in-memory twin of state/checkpoints/ : {sol: loader of the checkpoint's M0} (same last `keep` sols)
    for _ in range(n_sols):
        res = run_sol(state, explored, params, "1970-01-01T00:00:00Z", render=False, narrative=False, deadline=float("inf"),
                      ckpts=dict(ckpts))
        state, explored = res.state, res.explored
        m0 = copy.deepcopy(state["brain"]["m0"])
        ckpts[int(state["sol"])] = (lambda m0=m0: m0)
        for old in sorted(ckpts)[:-keep]:
            del ckpts[old]
        f = res.facts
        rows.append("%d,%d,%d,%.3f,%.3f,%d,%d" % (state["sol"], state["stage"]["id"], state["metrics"]["couples"],
                                                f.get("distance_m", 0.0), f.get("awake_cells", 0.0),
                                                f.get("breakdowns", 0), state["health"]["attempts"]))
    if report is not None:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"sols": n_sols, "stage": state["stage"]["id"], "cells": explored.cells(),
            "core_sha256": sha256_hex(core_bytes(core_for_compare(state))), "state": state, "explored": explored}
