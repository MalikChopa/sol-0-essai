"""sim.episode driving the frozen trace (J5): determinism, recording on/off, salt, mutation scope."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from rover.brain.brain import Brain
from rover.pipeline import fresh_state
from rover.sim.episode import run_episode
from rover.state import Explored, core_bytes
from rover.world import World, draw_events


def _play(params, state, record=True, salt=0):
    s = copy.deepcopy(state)
    s["sol"] = state["sol"] + 1
    world = World(s["world_seed"], params, s["overlays"])
    ev = draw_events(s["world_seed"], s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    brain = Brain.from_state(s["brain"], s["stage"]["id"], params)
    ex = Explored()
    out = run_episode(s, world, brain, ex, ev, params, salt=salt, record=record)
    return s, ex, out


@pytest.fixture(scope="module")
def state0(params):
    return fresh_state(params)


def test_same_inputs_same_outputs(params, state0):
    s1, e1, (t1, d1, f1) = _play(params, state0)
    s2, e2, (t2, d2, f2) = _play(params, state0)
    assert f1 == f2 and s1["rover"] == s2["rover"]
    assert e1.to_regions() == e2.to_regions()
    assert np.array_equal(d1.couples, d2.couples) and np.array_equal(d1.path, d2.path)
    assert len(t1.frames) == len(t2.frames) and len(t1.frames) > 0
    for a, b in zip(t1.frames, t2.frames):
        assert a.tick == b.tick and a.mode == b.mode and np.array_equal(a.cam_index, b.cam_index)
    assert np.array_equal(t1.seen, t2.seen)


def test_recording_off_changes_nothing_else(params, state0):
    s1, e1, (t1, d1, f1) = _play(params, state0, record=True)
    s2, e2, (t2, d2, f2) = _play(params, state0, record=False)
    assert t1 is not None and t2 is None
    assert f1 == f2 and s1["rover"] == s2["rover"] and e1.to_regions() == e2.to_regions()
    assert np.array_equal(d1.couples, d2.couples)


def test_trace_is_the_frozen_contract(params, state0):
    s, ex, (t, d, f) = _play(params, state0)
    assert t.sol == 1 and t.stage == 0
    assert t.seen.ndim == 2 and t.seen.shape[1] == 3 and t.seen.shape[0] > 0
    # every cell the trace says was seen is explored in the mask, and nothing else is
    for x, y, _ in t.seen.tolist()[:50]:
        assert int(ex.window_mask(x, y, 1, 1)[0, 0]) == 1
    assert ex.cells() == t.seen.shape[0]
    assert d.couples.shape[1] == 10 and d.path.shape[1] == 3
    for k in ("distance_m", "awake_cells", "breakdowns", "stuck", "tipped", "battery_min"):
        assert k in f


def test_episode_only_touches_the_rover_and_explored(params, state0):
    before = copy.deepcopy(state0)
    s, ex, _ = _play(params, state0)
    for d in (before, s):
        d.pop("rover"), d.pop("sol")
    assert core_bytes(before) == core_bytes(s)                  # everything else (brain, memory, trail...) is unchanged


def test_salt_is_accepted_and_keeps_the_episode_valid(params, state0):
    s, ex, (t, d, f) = _play(params, state0, salt=2)
    assert 0.0 <= s["rover"]["battery"] <= 1.0 and np.isfinite(d.couples).all()
