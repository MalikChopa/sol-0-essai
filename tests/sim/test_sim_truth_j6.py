"""J6 truth tests of the episode adapters (F-01 target, F-02 M3 + SEEK_SUN, F-03 M1 pair, A7 anomaly seen).

Every displayed value of the trace comes from the real brain and the real physics: these tests tie the trace fields to the
data they claim to show."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from rover.brain.brain import Brain
from rover.brain.m1_model import predict
from rover.pipeline import fresh_state
from rover.sim.episode import run_episode
from rover.state import Explored
from rover.world import World, draw_events


def _play(params, state, stage, overlays=None):
    s = copy.deepcopy(state)
    s["sol"] = 3
    s["stage"]["id"] = stage
    if overlays is not None:
        s["overlays"] = overlays
    world = World(s["world_seed"], params, s["overlays"])
    ev = draw_events(s["world_seed"], s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    brain = Brain.from_state(s["brain"], stage, params)
    out = run_episode(s, world, brain, Explored(), ev, params)
    return s, brain, out


@pytest.fixture(scope="module")
def stage3(params):
    return _play(params, fresh_state(params), 3)


def test_target_of_the_image_is_the_brain_target_and_counts_arrivals(stage3):
    s, brain, (trace, data, facts) = stage3
    tg = [f.target for f in trace.frames]
    assert all(t is not None and len(t) == 2 and np.isfinite(t[0]) and np.isfinite(t[1]) for t in tg)
    assert tg[-1] == (float(brain.target[0, 0]), float(brain.target[0, 1]))      # last recorded = last target of act
    assert isinstance(facts["targets_reached"], int) and facts["targets_reached"] >= 0
    assert len(set(tg)) >= 2, "targets are renewed during a sol (period or arrival)"


def test_no_target_before_stage_2(params):
    _, _, (trace, _, facts) = _play(params, fresh_state(params), 1)
    assert all(f.target is None for f in trace.frames)
    assert facts["targets_reached"] == 0


def test_m3_out_is_recorded_from_stage_3(params, stage3):
    _, _, (trace, _, _) = stage3
    outs = [f.m3_out for f in trace.frames]
    assert all(o is not None and o.shape == (3,) and np.all(np.isfinite(o)) for o in outs)
    _, _, (t2, _, _) = _play(params, fresh_state(params), 2)
    assert all(f.m3_out is None for f in t2.frames)


def test_m1_pair_comes_from_one_segment_of_the_couples(params):
    """F-03: m1_pred and m1_meas of an image are the prediction and the measure of the SAME segment (a row of data.couples)."""
    s, brain, (trace, data, _) = _play(params, fresh_state(params), 1)
    P = params.get
    seen = [(f.m1_pred, f.m1_meas) for f in trace.frames if f.m1_pred is not None]
    assert seen, "no M1 pair recorded at stage 1"
    assert all(f.m1_meas is not None for f in trace.frames if f.m1_pred is not None)
    n = int(P("brain.m1.hidden"))
    ok = 0
    for pred, meas in seen:
        for row in data.couples:
            want = predict(brain.b["m1"], row[None, :5], n)[0]
            if np.array_equal(meas, row[5:8]) and np.array_equal(pred, want):
                ok += 1
                break
    assert ok == len(seen)


def test_no_m1_pair_at_stage_0(params):
    _, _, (trace, _, _) = _play(params, fresh_state(params), 0)
    assert all(f.m1_pred is None and f.m1_meas is None for f in trace.frames)


def test_anomaly_in_front_of_the_rover_becomes_seen(params):
    """A7: seen_sol is set exactly when a cell of the anomaly enters trace.seen; facts.anomaly_seen follows."""
    base = fresh_state(params)
    _, _, (trace0, _, f0) = _play(params, base, 2, overlays=[])
    assert f0["anomaly_seen"] is False
    cells = np.asarray(trace0.seen)[:, :2]
    assert len(cells) > 0
    cx, cy = int(cells[0, 0]), int(cells[0, 1])
    ov = [{"kind": "anomaly", "x": cx, "y": cy, "r": 1, "params": {"height_m": 4.0}, "sol": 1, "seen_sol": None}]
    s, _, (trace, _, facts) = _play(params, base, 2, overlays=ov)
    seen = np.asarray(trace.seen)[:, :2]
    inside = bool(np.any((np.abs(seen[:, 0] - cx) <= 1) & (np.abs(seen[:, 1] - cy) <= 1)))
    assert inside == facts["anomaly_seen"] == bool(s["overlays"][0]["seen_sol"])
    assert facts["anomaly_seen"] is True and s["overlays"][0]["seen_sol"] == 3


def test_anomaly_far_away_stays_unseen(params):
    ov = [{"kind": "anomaly", "x": 5000, "y": 5000, "r": 1, "params": {"height_m": 4.0}, "sol": 1, "seen_sol": None}]
    s, _, (_, _, facts) = _play(params, fresh_state(params), 2, overlays=ov)
    assert facts["anomaly_seen"] is False and not s["overlays"][0]["seen_sol"]


def _play_forced_mode(params, mode):
    """Same sol, same brain, same commands; only the mode reported to the episode is forced (to isolate F-02)."""
    import dataclasses
    s = copy.deepcopy(fresh_state(params))
    s["sol"] = 3
    s["stage"]["id"] = 2
    world = World(s["world_seed"], params, s["overlays"])
    ev = draw_events(s["world_seed"], s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    brain = Brain.from_state(s["brain"], 2, params)
    real_act = brain.act

    def act(rb, cam, ctx):
        o = real_act(rb, cam, ctx)
        return dataclasses.replace(o, mode=[mode] * len(o.mode))
    brain.act = act
    return run_episode(s, world, brain, Explored(), ev, params)


def test_seek_sun_adds_the_panel_one_bonus_to_battery_and_solar_in(params):
    """F-02: SEEK_SUN = panel 1 (SPEC 4.8): with identical commands, daylight gives a larger solar input and a higher
    battery than DRIVE, tick by tick never lower, and never in the dark."""
    (td, _, fd), (ts, _, fs) = _play_forced_mode(params, "DRIVE"), _play_forced_mode(params, "SEEK_SUN")
    assert [f.mode for f in ts.frames] == ["SEEK_SUN"] * len(ts.frames)
    sd, ss = [f.solar for f in td.frames], [f.solar for f in ts.frames]
    assert len(sd) == len(ss) and all(b >= a - 1e-9 for a, b in zip(sd, ss))
    day = [i for i, f in enumerate(ts.frames) if f.sun_elev > 0.05]
    assert day and any(ss[i] > sd[i] + 1e-6 for i in day)
    assert all(abs(ss[i] - sd[i]) < 1e-9 for i, f in enumerate(ts.frames) if f.sun_elev <= 0.0)
    assert sum(f.battery for f in ts.frames) > sum(f.battery for f in td.frames)


def test_arrival_is_counted_when_the_target_is_within_arrive_r(params):
    """F-01: a target placed under the rover is an arrival (distance < brain.arrive_r)."""
    s = copy.deepcopy(fresh_state(params))
    s["sol"] = 3
    s["stage"]["id"] = 2
    world = World(s["world_seed"], params, s["overlays"])
    ev = draw_events(s["world_seed"], s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    brain = Brain.from_state(s["brain"], 2, params)
    real_act = brain.act
    pos = (s["rover"]["x"], s["rover"]["y"])
    calls = {"n": 0}

    def act(rb, cam, ctx):
        o = real_act(rb, cam, ctx)
        if calls["n"] == 0:                                   # first tick: the brain's target is on the rover
            brain.target = np.asarray([[float(rb.x[0]), float(rb.y[0])]])
        calls["n"] += 1
        return o
    brain.act = act
    _, _, facts = run_episode(s, world, brain, Explored(), ev, params)
    assert facts["targets_reached"] >= 1 and pos is not None
