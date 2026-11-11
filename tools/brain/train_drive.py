"""Acceptance bench of M0 (ARCH 10 J2): learn to drive by ES alone, then play the fixed battery.

    PYTHONPATH=src python tools/brain/train_drive.py --gens 300 --seed 1

Runs the real `Brain.learn` sol after sol (stage 2: 12 generations per sol, battery after each sol, regression rule of
SPEC 4.7 with 5 checkpoints) on an empty pair buffer; reports per-sol scores, the restoration rate and the duration.
Exit code 0 if the final score is >= --need (default 16/20)."""
from __future__ import annotations

import argparse
import copy
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rover import config                                    # noqa: E402
from rover.brain.battery import append_measure, evaluate_regression, run_battery   # noqa: E402
from rover.brain.brain import Brain                         # noqa: E402
from rover.core.types import SolData                        # noqa: E402
from rover.world.chunks import World                        # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--need", type=int, default=16)
    ap.add_argument("--stage", type=int, default=2)
    a = ap.parse_args(argv)
    params = config.load(ROOT / "config")
    gens_per_sol = int(params.get("brain.es.gens_learn"))
    world = World(a.seed, params)
    state = Brain.initial(params, a.seed)
    metrics = {"battery": [], "battery_stage": [], "battery_sol": [], "battery_low": 0}
    ckpt: dict = {}
    empty = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=[])
    t0 = time.monotonic()
    restores = measures = 0
    first = run_battery(Brain.from_state(state, a.stage, params), world, a.stage, params)
    print(f"initial battery: {first.successes}/20")
    last = first.successes
    n_sols = int(math.ceil(a.gens / gens_per_sol))
    for sol in range(1, n_sols + 1):
        ts = time.monotonic()
        b = Brain.from_state(state, a.stage, params)
        if sol == n_sols and a.gens % gens_per_sol:
            params_gens = a.gens % gens_per_sol
            es = dict(params.get("brain.es"))
            es["gens_learn"] = params_gens
            params = type(params)(data={**params.data, "brain": {**params.data["brain"], "es": es}}, hash=params.hash)
            b = Brain.from_state(state, a.stage, params)
        rep = b.learn(empty, world, sol, math.inf)
        state = b.to_state()
        res = rep["battery"]
        v = res["successes"]
        verdict = evaluate_regression(metrics, v, a.stage, params, ckpt.keys())
        note = ""
        if verdict.restore_sol is not None:
            state["m0"] = copy.deepcopy(ckpt[verdict.restore_sol])
            v = run_battery(Brain.from_state(state, a.stage, params), world, a.stage, params).successes
            restores += 1
            note = f" RESTORED from sol {verdict.restore_sol} -> {v}/20"
        elif verdict.warning:
            note = " (" + verdict.warning + ")"
        append_measure(metrics, v, a.stage, sol, verdict.low)
        measures += 1
        ckpt[sol] = copy.deepcopy(state["m0"])
        for old in sorted(ckpt)[:-5]:
            del ckpt[old]
        last = v
        print(f"sol {sol:3d}  gens {rep['m0']['gens']:2d}  battery {v:2d}/20  {time.monotonic() - ts:5.1f} s{note}")
    dur = time.monotonic() - t0
    rate = restores / measures if measures else 0.0
    print(f"final {last}/20 (need {a.need}); best {max(metrics['battery'])}/20; restorations {restores}/{measures} "
          f"({rate:.2f}); duration {dur:.1f} s; gens {a.gens}; seed {a.seed}")
    return 0 if last >= a.need else 1


if __name__ == "__main__":
    sys.exit(main())
