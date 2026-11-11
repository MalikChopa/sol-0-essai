"""Stage machine (SPEC 5): minimum durations, <= 2 recalibrations, version lock, progress never at 100 % before passage."""
from __future__ import annotations

import copy

import pytest
from hypothesis import given, strategies as st

from rover.stages import progress, safe_mode, step_stage


def new_stage():
    return {"id": 0, "entered_sol": 0, "sols_in_stage": 0, "threshold_scale": 1.0, "recalibrations": 0,
            "consolidation": False, "history": [[0, 0]]}


def new_metrics():
    return {"couples": 0, "r2": [], "r2_stable": 0, "battery": [], "battery_stage": [], "battery_sol": [], "battery_low": 0,
            "no_breakdown_streak": 0, "breakdowns": [], "novel": [], "ari": [], "ari_stable": 0}


def feed(m, stage, sol, draw):
    """Update the metrics like the pipeline does, from drawn fictitious values (couples, r2, battery, streak)."""
    c, r2, bat, streak = draw
    m["couples"] += c
    if stage["id"] >= 1:
        m["r2"] = (m["r2"] + [r2])[-30:]
    if stage["id"] >= 2:
        m["battery"] = (m["battery"] + [bat])[-30:]
        m["battery_stage"] = (m["battery_stage"] + [stage["id"]])[-30:]
        m["battery_sol"] = (m["battery_sol"] + [sol])[-30:]
    m["no_breakdown_streak"] = m["no_breakdown_streak"] + 1 if streak else 0


draws = st.lists(st.tuples(st.integers(0, 80), st.floats(-1.0, 1.0), st.integers(0, 20), st.booleans()),
                 min_size=1, max_size=400)


@given(draws, st.integers(0, 3))
def test_machine_invariants(params, ds, max_stage):
    stage, m = new_stage(), new_metrics()
    cfg = params.get("stages.stage")
    for sol, d in enumerate(ds, start=1):
        feed(m, stage, sol, d)
        before = copy.deepcopy(stage)
        dec = step_stage(stage, m, sol, max_stage, params)
        assert before == stage                                           # pure: the input is never mutated
        stage = dec.stage
        if dec.advanced:                                                 # minimum duration respected
            assert before["sols_in_stage"] + 1 >= cfg[before["id"]]["min"]
            assert stage["sols_in_stage"] == 0 and stage["id"] == before["id"] + 1
        assert stage["id"] <= max_stage                                  # version lock
        assert stage["recalibrations"] <= 2
        p = progress(stage, m, params)
        assert 0.0 <= p.fraction <= 1.0
        if not stage["consolidation"]:
            assert p.fraction < 1.0                                      # never 100 % without the passage
        assert stage["history"][-1][0] == stage["id"]


def test_recalibration_twice_then_never_forced(params):
    stage, m = new_stage(), new_metrics()
    seen = []
    for sol in range(1, 200):
        dec = step_stage(stage, m, sol, 3, params)
        stage = dec.stage
        if dec.recalibrated:
            seen.append((sol, stage["threshold_scale"], stage["recalibrations"]))
    cfg = params.get("stages.stage")[0]
    assert [s[0] for s in seen] == [3 * cfg["target"], 5 * cfg["target"]]
    assert abs(seen[1][1] - 0.81) < 1e-12 and stage["id"] == 0           # never a forced passage


def test_threshold_rounding_for_counts(params):
    stage, m = new_stage(), new_metrics()
    stage["threshold_scale"] = 0.9
    m["couples"] = 179
    assert not progress(stage, m, params).fraction >= 1.0
    p = progress(stage, m, params)
    assert p.value_text_en == "179/180 command-effect pairs"            # 200 x 0.9 shown as the current threshold


def test_stage0_to_1_and_stage1_needs_three_stable_sols(params):
    stage, m = new_stage(), new_metrics()
    m["couples"] = 250
    for sol in range(1, 3):
        stage = step_stage(stage, m, sol, 3, params).stage
        assert stage["id"] == 0                                          # min 3 sols
    p = progress(stage, m, params)
    assert p.blocking == "min_duration" and p.fraction == 0.99 and p.value_text_en.endswith("| min duration 2/3 sols")
    stage = step_stage(stage, m, 3, 3, params).stage
    assert stage["id"] == 1
    m["r2"] = [0.8, 0.8, 0.5]
    for sol in range(4, 10):
        stage = step_stage(stage, m, sol, 3, params).stage
    assert stage["id"] == 1
    m["r2"] = [0.5, 0.8, 0.75, 0.71]
    stage = step_stage(stage, m, 10, 3, params).stage
    assert stage["id"] == 2 and stage["history"] == [[0, 0], [1, 3], [2, 10]]


def test_consolidation_at_max_stage(params):
    stage, m = new_stage(), new_metrics()
    stage.update(id=3, sols_in_stage=58)
    m["no_breakdown_streak"] = 25
    dec = step_stage(stage, m, 100, 3, params)
    assert dec.consolidation_started and dec.stage["consolidation"] and dec.stage["id"] == 3
    again = step_stage(dec.stage, m, 101, 3, params)
    assert not again.consolidation_started and again.stage["consolidation"]
    assert progress(dec.stage, m, params).blocking == "none"
    later = step_stage(dec.stage, m, 102, 4, params)                     # a newer code advances if the criterion still holds
    assert later.advanced and later.stage["id"] == 4 and not later.stage["consolidation"]


def test_progress_texts_match_spec_examples(params):
    stage, m = new_stage(), new_metrics()
    m["couples"] = 143
    assert progress(stage, m, params).value_text_en == "143/200 command-effect pairs"
    stage.update(id=1)
    m["r2"] = [0.5, 0.58]
    p = progress(stage, m, params)
    assert p.value_text_en == "R2 0.58 / 0.70 | stable 0/3 sols" and p.fraction == 0.0      # SPEC 5.3: min(R2/thr, series/3)
    m["r2"] = [0.5, 0.72, 0.8]
    p = progress(stage, m, params)
    assert p.value_text_en == "R2 0.80 / 0.70 | stable 2/3 sols" and abs(p.fraction - 2 / 3) < 1e-12
    m["r2"] = [0.5, 0.58]
    m["r2"] = [-0.4]
    assert progress(stage, m, params).fraction == 0.0                    # never negative
    stage.update(id=2, sols_in_stage=70)
    m["battery"], m["battery_stage"], m["battery_sol"] = [13], [2], [5]
    p = progress(stage, m, params)
    assert p.value_text_en == "13/20 test courses (need 16)" and abs(p.fraction - 13 / 16) < 1e-12
    stage.update(id=3)
    m["no_breakdown_streak"] = 12
    assert progress(stage, m, params).value_text_en == "12/20 sols without breakdown"


def test_safe_mode_actions_are_all_reported(params):
    rover = {"x": 5.0, "y": 2.0, "c": 1.0, "s": 0.0, "battery": 0.10, "stuck": True, "tipped": True, "asleep": True,
             "sink_n": 3, "rev_n": 2, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "SLEEP", "safe_pending": []}
    last = {"stuck": True, "tipped": True, "battery_min": 0.1, "awake_cells": 0, "low_awake_streak": 3}
    r, acts = safe_mode(rover, last, params)
    assert acts == ["freed", "righted", "recharged", "noise_doubled"]
    assert not r["stuck"] and not r["tipped"] and r["battery"] == params.get("rover.energy.safe_recharge")
    assert r["x"] == 4.0                                                 # 1 cell back along the heading
    r2, acts2 = safe_mode(rover, {"stuck": False, "tipped": False, "battery_min": 0.5, "awake_cells": 9, "low_awake_streak": 0}, params)
    assert acts2 == [] and r2 == rover


@pytest.mark.parametrize("sid", [0, 1, 2, 3])
def test_every_stage_has_a_window_compatible_minimum(params, sid):
    lows = {0: 3, 1: 6, 2: 60, 3: 59}                                     # SPEC 5.1 (stage 3 raised to the window bottom)
    assert params.get("stages.stage")[sid]["min"] >= lows[sid]
