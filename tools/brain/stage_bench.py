"""Bench of the whole learning loop without the pipeline (J2 harness; the real loop is pipeline/sol.py, J5).

    PYTHONPATH=src python tools/brain/stage_bench.py --sols 60 --seed 1 [--out out/bench.csv]

Plays sols exactly in the order of ARCH 4 (events, safe mode, episode, learn, metrics, stage machine) with the brain
receiving the pair buffer and the consolidation flag. Prints one line per sol: stage, couples, R2, battery, timings."""
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

from rover import config, version                                         # noqa: E402
from rover.brain.battery import append_measure, evaluate_regression, run_battery   # noqa: E402
from rover.brain.brain import Brain                                       # noqa: E402
from rover.pipeline.sol import fresh_state                                # noqa: E402
from rover.sim.episode import run_episode                                 # noqa: E402
from rover.stages import safe_mode, step_stage                            # noqa: E402
from rover.state.explored import Explored                                 # noqa: E402
from rover.world.chunks import World                                      # noqa: E402
from rover.world.events import draw_events                                # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sols", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    params = config.load(ROOT / "config")
    P = params.get
    s = fresh_state(params, a.seed)
    ex = Explored()
    ckpt: dict = {}
    rows = []
    restores = {"learning": [0, 0], "consolidation": [0, 0]}
    for sol in range(1, a.sols + 1):
        t0 = time.monotonic()
        s["sol"] = sol
        world = World(s["world_seed"], params, s["overlays"])
        ev = draw_events(s["world_seed"], sol, s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
        s["rover"], safe = safe_mode(s["rover"], s["last_facts"], params)
        s["rover"]["safe_pending"] = safe
        stage = s["stage"]["id"]
        cons = s["stage"]["consolidation"]
        brain = Brain.from_state(s["brain"], stage, params, consolidation=cons, memory=s["memory"]["couples"])
        _, data, facts = run_episode(s, world, brain, ex, ev, params, record=False)
        t1 = time.monotonic()
        rep = brain.learn(data, world, sol, math.inf)
        t2 = time.monotonic()
        s["brain"] = brain.to_state()
        s["memory"]["couples"] = np.concatenate([s["memory"]["couples"], data.couples.astype(np.float32)])[-int(P("brain.m1.buffer")):]
        m = s["metrics"]
        m["couples"] += int(data.couples.shape[0])
        if rep["m1"] is not None:
            m["r2"] = (m["r2"] + [rep["m1"]["r2"]])[-30:]
        note = ""
        if rep["battery"] is not None:
            v = rep["battery"]["successes"]
            vd = evaluate_regression(m, v, stage, params, ckpt.keys())
            if vd.restore_sol is not None:
                s["brain"]["m0"] = copy.deepcopy(ckpt[vd.restore_sol])
                v = run_battery(Brain.from_state(s["brain"], stage, params), world, stage, params).successes
                note = f"restored<-{vd.restore_sol}"
            if vd.restore_sol is not None or vd.low or vd.warning:
                pass
            restores["consolidation" if cons else "learning"][1] += 1
            restores["consolidation" if cons else "learning"][0] += int(vd.restore_sol is not None)
            append_measure(m, v, stage, sol, vd.low)
        ckpt[sol] = copy.deepcopy(s["brain"]["m0"])
        for old in sorted(ckpt)[:-int(P("run.checkpoints"))]:
            del ckpt[old]
        m["breakdowns"] = (m["breakdowns"] + [facts["breakdowns"]])[-30:]
        ok = facts["breakdowns"] == 0 and facts["awake_cells"] >= P("stages.energy_min_cells")
        m["no_breakdown_streak"] = m["no_breakdown_streak"] + 1 if ok else 0
        s["rover"]["safe_pending"] = []
        dec = step_stage(s["stage"], m, sol, version.MAX_STAGE, params)
        s["stage"] = dec.stage
        low = stage >= 2 and facts["awake_cells"] < P("stages.no_progress_cells")
        s["last_facts"] = {"stuck": facts["stuck"], "tipped": facts["tipped"], "battery_min": facts["battery_min"],
                           "awake_cells": facts["awake_cells"],
                           "low_awake_streak": s["last_facts"]["low_awake_streak"] + 1 if low else 0}
        s["events"] = {"storm_left": ev.storm_left}
        r2 = rep["m1"]["r2"] if rep["m1"] else float("nan")
        bat = rep["battery"]["successes"] if rep["battery"] else -1
        line = (f"sol {sol:4d} stage {stage}{'C' if cons else ' '} couples {m['couples']:5d} r2 {r2:6.2f} battery {bat:3d} "
                f"cells {facts['awake_cells']:6.1f} breakdowns {facts['breakdowns']} ep {t1 - t0:5.1f}s learn {t2 - t1:5.1f}s "
                f"{'ADVANCE->' + str(s['stage']['id']) if dec.advanced else ''} {'recal' if dec.recalibrated else ''} {note} "
                f"safe {','.join(safe)}")
        print(line, flush=True)
        rows.append((sol, stage, m["couples"], r2, bat, facts["awake_cells"], facts["breakdowns"], t1 - t0, t2 - t1))
    print("battery restorations (restored/measures):", restores)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text("sol,stage,couples,r2,battery,cells,breakdowns,episode_s,learn_s\n" +
                               "".join(",".join(str(v) for v in r) + "\n" for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
