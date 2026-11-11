"""Battery (fixed exam, categories, regression rule), rollouts (common random numbers, batch independence), act and learn."""
from __future__ import annotations

import copy
import math
from collections import Counter

import numpy as np
import pytest

from rover.agent.body import RoverBatch
from rover.brain.battery import (append_measure, battery_due, evaluate_regression, make_courses, run_battery)
from rover.brain.brain import ActCtx, Brain
from rover.brain.m0_drive import explore_target, sun_target
from rover.brain.rollouts import rollout_fitness
from rover.core.types import CamFrame, SolEvents
from rover.world.chunks import World
from rover.world.climate import sun_at

CALM = SolEvents(False, 0, 1.0, 1.0, 0.0, [], [])


@pytest.fixture(scope="module")
def world(params):
    return World(1, params)


def test_battery_courses_are_fixed_and_categorised(params):
    c = make_courses(1, params)
    assert Counter(x[6] for x in c) == {"flat": 5, "slope": 5, "sand": 5, "any": 5}
    assert c == make_courses(1, params)                               # fixed once and for all
    assert all(abs(math.hypot(x[4] - x[0], x[5] - x[1]) - 30.0) < 1e-6 for x in c)
    assert all(abs(x[0]) <= 256 and abs(x[1]) <= 256 for x in c)
    assert c != make_courses(2, params)


def test_battery_is_the_same_exam_every_sol_and_depends_only_on_theta(params, world):
    b = Brain.from_state(Brain.initial(params, 1), 2, params)
    a1 = run_battery(b, world, 2, params)
    a2 = run_battery(b, World(1, params, overlays=[{"kind": "impact", "x": 0, "y": 0, "r": 5, "params": {}, "sol": 3, "seen_sol": None}]), 2, params)
    assert a1.per_course == a2.per_course and a1.successes == sum(a1.per_course)
    assert len(a1.per_course) == 20 and len(a1.categories) == 20
    b2 = Brain.from_state(Brain.initial(params, 1), 2, params)
    b2.b["m0"]["theta"] = b2.b["m0"]["theta"] * np.float32(1.5)
    r = run_battery(b2, world, 2, params)
    assert 0 <= r.successes <= 20


def metrics_with(bat, sols, stage=2, low=0):
    return {"battery": list(bat), "battery_stage": [stage] * len(bat), "battery_sol": list(sols), "battery_low": low}


def test_regression_rule_counts_measures_not_sols(params):
    m = metrics_with([18, 19, 20], [10, 11, 12])
    v = evaluate_regression(m, 15, 2, params, {10, 11, 12})          # threshold 0.8 x 20 = 16: below
    assert v.low == 1 and v.restore_sol is None and v.threshold == 16.0
    m["battery_low"] = 1
    v = evaluate_regression(m, 15, 2, params, {10, 11, 12})          # second consecutive measure under: restore
    assert v.restore_sol == 12 and v.low == 0
    v = evaluate_regression(m, 15, 2, params, {10, 11})              # checkpoint of the best measure is gone
    assert v.restore_sol is None and v.warning == "battery_regress_no_checkpoint" and v.low == 0
    v = evaluate_regression(m, 16, 2, params, {12})                  # at the threshold: not low, counter reset
    assert v.low == 0 and v.restore_sol is None
    assert m["battery_low"] == 1                                      # pure: nothing mutated


def test_regression_window_is_the_last_five_measures_of_the_same_stage(params):
    m = {"battery": [20, 10, 11, 12, 13, 14], "battery_stage": [2, 2, 2, 2, 2, 2], "battery_sol": [1, 2, 3, 4, 5, 6], "battery_low": 0}
    assert evaluate_regression(m, 10, 2, params, {1, 2, 3, 4, 5, 6}).threshold == 0.8 * 14   # the 20 left the window
    m["battery_stage"] = [1, 2, 2, 2, 2, 2]
    assert evaluate_regression({"battery": [20, 1], "battery_stage": [1, 2], "battery_sol": [1, 2], "battery_low": 0},
                               0, 2, params, set()).threshold == 0.8 * 1      # other stage ignored
    assert evaluate_regression({"battery": [], "battery_stage": [], "battery_sol": [], "battery_low": 0}, 0, 2, params, set()).low == 0


def test_append_measure_bounds_and_consolidation_rate(params):
    m = metrics_with(list(range(30)), list(range(30)))
    append_measure(m, 7, 2, 99, 1)
    assert len(m["battery"]) == 30 and m["battery"][-1] == 7 and m["battery_sol"][-1] == 99 and m["battery_low"] == 1
    assert battery_due(5, False, params) and battery_due(8, True, params) and not battery_due(9, True, params)


def test_rollout_candidate_fitness_is_independent_of_the_batch(params, world):
    b = Brain.initial(params, 1)
    th = np.repeat(b["m0"]["theta"].astype(np.float64)[None, :], 5, axis=0)
    th[1] *= 2.0
    th[3] = th[1]
    f5 = rollout_fitness(world, params, 2, th, b["m2"], 4, 0, 2, (0.0, 0.0))
    f1 = rollout_fitness(world, params, 2, th[1:2], b["m2"], 4, 0, 2, (0.0, 0.0))
    assert f5[1] == f5[3]                                              # same theta, same draws: common random numbers
    assert f5[1] == f1[0]                                              # one rover alone = same bytes as in a batch of 10
    assert f5[0] == f5[2] == f5[4]
    assert np.all(np.isfinite(f5))


def _ctx(world, params, stage, tick=0, mask=None, sol=3):
    win = world.window(-1, -1, 0, 0)
    sun = sun_at(sol, tick, params)
    return ActCtx(sol=sol, tick=tick, stage=stage, sun=sun, ev=CALM, win=win,
                  explored_mask=np.zeros((0, 0), dtype=np.uint8) if mask is None else mask, explore_scale=1.0,
                  keys_babble=np.asarray([123], dtype=np.uint64))


def _rb(x=0.0, y=0.0, battery=1.0, forced=False):
    return RoverBatch.from_rover({"x": x, "y": y, "c": 1.0, "s": 0.0, "battery": battery, "stuck": False, "tipped": False,
                                  "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0],
                                  "mode": "DRIVE", "safe_pending": []}, 1), forced


def test_target_goes_towards_unexplored_cells(params, world):
    win = world.window(-1, -1, 0, 0)
    mask = np.ones(win.height.shape, dtype=np.uint8)                   # everything explored ...
    iy, ix = 0 - win.y0, 0 - win.x0
    mask[iy - 3:iy + 4, ix + 1:ix + 41] = 0                           # ... except a strip to the east
    tx, ty = explore_target(0.0, 0.0, win, mask, params)
    assert (tx, ty) == (30.0, 0.0)
    mask[:] = 1
    mask[iy + 1:iy + 41, ix - 3:ix + 4] = 0                           # a strip to the north (y up) only
    tx, ty = explore_target(0.0, 0.0, win, mask, params)
    assert abs(tx) < 1e-9 and ty == 30.0
    z = np.zeros(win.height.shape, dtype=np.uint8)                    # nothing explored: deterministic, at 30 cells
    t = explore_target(0.0, 0.0, win, z, params)
    assert t == explore_target(0.0, 0.0, win, z, params) and abs(math.hypot(*t) - 30.0) < 1e-9


def test_sun_target_needs_explored_cells(params, world):
    win = world.window(-1, -1, 0, 0)
    sun = sun_at(3, 600, params)
    assert sun_target(0.0, 0.0, win, np.zeros(win.height.shape, dtype=np.uint8), sun, params) is None
    t = sun_target(0.0, 0.0, win, np.ones(win.height.shape, dtype=np.uint8), sun, params)
    assert t is not None and 11.9 <= math.hypot(t[0], t[1]) + 6.1


def test_act_stage2_target_sleep_and_modes(params, world):
    b = Brain.from_state(Brain.initial(params, 1), 2, params)
    rb, _ = _rb()
    cam = CamFrame(index=np.full((1, 20, 32), 5, dtype=np.uint8), depth=np.full((1, 20, 32), 40, dtype=np.uint8), seen=None, D=40)
    out = b.act(rb, cam, _ctx(world, params, 2, tick=600))
    assert out.mode == ["DRIVE"] and out.f.shape == (1, 8) and out.z.shape == (1, 40) and out.m3_out is None
    assert b.target is not None and b.target.shape == (1, 2)
    assert np.all(np.isfinite(out.u)) and out.x.shape == (1, 24)
    rbf, _ = _rb(battery=0.1)
    rbf.forced = np.asarray([True])
    out = b.act(rbf, None, _ctx(world, params, 2, tick=601))
    assert out.mode == ["SLEEP"] and float(np.sum(np.abs(out.x))) == 0.0 and float(np.sum(np.abs(out.u))) == 0.0


def test_act_stage3_m3_decides_and_records_its_outputs(params, world):
    b = Brain.from_state(Brain.initial(params, 1), 3, params)
    rb, _ = _rb()
    modes, outs = set(), []
    for tick in range(0, 60):
        out = b.act(rb, None, _ctx(world, params, 3, tick=tick))
        modes.add(out.mode[0])
        outs.append(out.m3_out.copy())
    assert out.m3_out.shape == (1, 3) and modes <= {"DRIVE", "SEEK_SUN", "SLEEP"}
    assert all(o.tobytes() == outs[0].tobytes() for o in outs[:20])      # decision held for 20 ticks
    assert b.last_m3_x.shape == (1, 8) and b.last_m3_h.shape == (1, 8)
    assert float(b.last_m3_x[0, 7]) == 1.0


def test_learn_stage0_does_nothing_and_stage1_trains_m1_m2(params, world):
    from brain_synth import synthetic_couples
    from rover.core.types import SolData
    z = np.stack([np.linspace(0, 1, 40) * (1 + 0.1 * i) for i in range(30)])
    data = SolData(couples=synthetic_couples(60, per_sol=6), frames_z=z, path=np.zeros((0, 3)), breakdowns=0, samples=[])
    b0 = Brain.from_state(Brain.initial(params, 1), 0, params)
    assert b0.learn(data, world, 5, math.inf) == {"m1": None, "m2": None, "m0": None, "m3": None, "truncated_at": None, "battery": None}
    b1 = Brain.from_state(Brain.initial(params, 1), 1, params)
    rep = b1.learn(data, world, 5, math.inf)
    assert rep["m1"]["steps"] == 200 and rep["m2"]["explained"] >= 0.0 and rep["m0"] is None and rep["battery"] is None
    assert b1.b["m2"]["n_sols"] == 1


def test_learn_stage2_runs_es_and_battery_and_honours_the_deadline(params, world):
    from rover.core.types import SolData
    empty = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=[])
    b = Brain.from_state(Brain.initial(params, 1), 2, params)
    th0 = b.b["m0"]["theta"].copy()
    rep = b.learn(empty, world, 1, -1.0)                              # deadline already passed: stops after one generation
    assert rep["m0"]["gens"] == 1 and rep["truncated_at"] == {"module": "m0", "gen": 1}
    assert b.b["m0"]["theta"].tobytes() != th0.tobytes() and rep["battery"]["successes"] >= 0
    bb = Brain.from_state(Brain.initial(params, 1), 2, params)
    bb.learn(empty, world, 1, -1.0)
    assert bb.b["m0"]["theta"].tobytes() == b.b["m0"]["theta"].tobytes()   # deterministic


def test_consolidation_learns_in_maintenance_only(params, world):
    from rover.core.types import SolData
    empty = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=[])
    b = Brain.from_state(Brain.initial(params, 1), 3, params, consolidation=True)
    rep = b.learn(empty, world, 8, math.inf)
    assert rep["m0"]["gens"] == 2 and rep["m3"]["gens"] == 2 and rep["battery"] is not None
    rep = Brain.from_state(Brain.initial(params, 1), 3, params, consolidation=True).learn(empty, world, 9, math.inf)
    assert rep["battery"] is None                                      # one sol in four in consolidation
