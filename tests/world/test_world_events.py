"""events: SPEC 2 probabilities, storm rules, overlays (fictitious seeds)."""
from __future__ import annotations

import pytest

from rover.world.events import draw_events

SEED = 777


@pytest.fixture(scope="module")
def sols100k(params):
    """100 000 consecutive sols with the storm state carried forward: counts and the free-sol denominator."""
    prev = {"storm_left": 0}
    n = {"storm_sols": 0, "starts": 0, "free": 0, "deposit": 0, "anomaly": 0, "impact": 0}
    evs = []
    for sol in range(1, 100001):
        free = prev["storm_left"] == 0
        ev = draw_events(SEED, sol, prev, (10.0, -4.0), params)
        n["free"] += free
        n["starts"] += free and ev.storm
        n["storm_sols"] += ev.storm
        for k in ("deposit", "anomaly", "impact"):
            n[k] += k in ev.kinds
        prev = {"storm_left": ev.storm_left}
        evs.append(ev)
    return n, evs


def test_storm_start_frequency_1_in_40_within_10_percent(sols100k):
    n, _ = sols100k
    p = n["starts"] / n["free"]
    assert abs(p - 1 / 40) / (1 / 40) < 0.10, p


def test_deposit_frequency_within_10_percent(sols100k):
    n, _ = sols100k
    assert abs(n["deposit"] - 100000 / 200) / (100000 / 200) < 0.10, n["deposit"]


def test_rare_events_within_three_sigma(sols100k):
    """1/1000 and 1/3000 over 100 000 sols: expected 100 and 33.3 ; +-10 % is under 1 sigma for them, so 3 sigma is used."""
    n, _ = sols100k
    assert abs(n["anomaly"] - 100) < 3 * 10.0, n["anomaly"]
    assert abs(n["impact"] - 100000 / 3000) < 3 * 5.8, n["impact"]


def test_storm_lasts_1_to_3_sols_and_never_restarts_inside(sols100k):
    _, evs = sols100k
    starts = [ev for prev, ev in zip([None] + evs[:-1], evs) if ev.storm and (prev is None or prev.storm_left == 0)]
    assert starts and {ev.storm_left + 1 for ev in starts} == {1, 2, 3}      # duration 1..3 sols, all three occur
    # inside one storm, storm_left strictly decreases to 0
    for a, b in zip(evs, evs[1:]):
        if a.storm_left > 0:
            assert b.storm and b.storm_left == a.storm_left - 1


def test_effects_of_a_storm(params, sols100k):
    _, evs = sols100k
    st = [e for e in evs if e.storm][0]
    assert st.view_scale == 0.5 and st.solar_factor == 0.35 and st.slip_add == 0.05 and "storm" in st.kinds
    ok = [e for e in evs if not e.storm][0]
    assert ok.view_scale == 1.0 and ok.solar_factor == 1.0 and ok.slip_add == 0.0


def test_overlays_geometry(sols100k):
    _, evs = sols100k
    seen = {"deposit": 0, "anomaly": 0, "impact": 0}
    for ev in evs:
        for o in ev.new_overlays:
            seen[o["kind"]] += 1
            d = ((o["x"] - 10.0) ** 2 + (o["y"] + 4.0) ** 2) ** 0.5
            lo, hi = {"deposit": (30, 60), "anomaly": (30, 60), "impact": (80, 150)}[o["kind"]]
            assert lo - 1.5 <= d <= hi + 1.5
            assert isinstance(o["x"], int) and isinstance(o["y"], int)
            if o["kind"] == "impact":
                assert 6 <= o["r"] <= 12
            if o["kind"] == "deposit":
                assert 4 <= o["r"] <= 8 and 0 <= o["params"]["substance"] < 12
            if o["kind"] == "anomaly":
                assert o["r"] == 1
    assert all(v > 0 for v in seen.values())


def test_pure_function_of_inputs(params):
    for sol in (1, 99, 12345):
        a = draw_events(SEED, sol, {"storm_left": 0}, (3.0, 4.0), params)
        b = draw_events(SEED, sol, {"storm_left": 0}, (3.0, 4.0), params)
        assert a == b
    assert draw_events(SEED, 5, {"storm_left": 2}, (0.0, 0.0), params).storm_left == 1
    assert draw_events(SEED, 5, {}, (0.0, 0.0), params).storm_left in (0, 1, 2)
