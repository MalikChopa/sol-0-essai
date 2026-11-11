"""physics, energy, sensors: SPEC 3.1-3.4 (hypothesis properties, batch independence, sinking, tipping)."""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from rover.agent import observe, physics_step
from rover.agent.body import RoverBatch
from rover.agent.energy import energy_step
from rover.core import consts
from rover.core.rng import derive, gauss_ih4, uniform
from rover.core.types import SolEvents, Sun
from rover.world import sun_at

from agent_helpers import SEED, make_window, random_batch, rover_dict, take

NO_EV = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
STORM = SolEvents(storm=True, storm_left=1, view_scale=0.5, solar_factor=0.35, slip_add=0.05, new_overlays=[], kinds=["storm"])


def _batch(n=1, **kw):
    rb = RoverBatch.from_rover(rover_dict(**kw), n)
    return rb


def _keys(n, sol=1):
    return np.asarray([derive(SEED, "slip", sol, 0)] * n, dtype=np.uint64)


def _ramp(gx=0.0, gy=0.0):
    return lambda X, Y: gx * X + gy * Y


# ----- properties (hypothesis) -------------------------------------------------------------------------------------
@settings(max_examples=40)
@given(seed=st.integers(0, 10_000), gtype=st.sampled_from([0, 1, 2, 3]), slope=st.floats(-2.5, 2.5),
       amp=st.floats(0.0, 2.0), night=st.booleans(), storm=st.booleans())
def test_properties_over_random_runs(params, seed, gtype, slope, amp, night, storm):
    win = make_window(_ramp(slope * 0.7, slope * 0.3), gtype, size=(300, 300), x0=-150, y0=-150)
    n = 6
    rb = random_batch(n, seed, spread=20.0)
    sun = sun_at(seed % 600, 1100 if night else 600, params)
    ev = STORM if storm else NO_EV
    keys = np.asarray([derive(SEED, "slip", seed, 0, i) for i in range(n)], dtype=np.uint64)
    r = np.random.default_rng(seed)
    vmax = params.get("rover.v_max")
    back = params.get("rover.unstick_back")
    odo = rb.odometer.copy()
    for t in range(60):
        u = r.uniform(-amp, amp, (n, 2))
        x0, y0 = rb.x.copy(), rb.y.copy()
        was_stuck = rb.stuck.copy()
        physics_step(rb, u, win, sun, ev, keys, t, None, params)
        for f in ("x", "y", "c", "s", "battery", "slip", "pitch", "roll", "enc_l", "enc_r", "odometer"):
            assert np.all(np.isfinite(getattr(rb, f))), f
        assert np.all((rb.battery >= 0.0) & (rb.battery <= 1.0))
        assert np.all((rb.slip >= 0.0) & (rb.slip <= 1.0))
        step = np.sqrt((rb.x - x0) ** 2 + (rb.y - y0) ** 2)
        freed = was_stuck & ~rb.stuck
        assert np.all(step[~freed] <= vmax + 1e-12)                             # speed <= v_max (except the 0.5-cell back-off)
        assert np.all(step[freed] <= vmax + back + 1e-12)
        assert np.allclose(rb.c * rb.c + rb.s * rb.s, 1.0, atol=1e-12)
        assert np.all(rb.odometer >= odo - 1e-15)
        odo = rb.odometer.copy()
        assert np.all(np.abs(rb.enc_l) <= 1.0 + 2.0 * params.get("rover.omega_max") * params.get("rover.track") / vmax)


def test_forward_speed_on_flat_rock(params):
    win = make_window(_ramp(), consts.GTYPE_ROCK)
    rb = _batch(1)
    physics_step(rb, np.asarray([[1.0, 1.0]]), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
    n = abs(float(gauss_ih4(_keys(1), np.asarray(0))[0]))
    k = 1.0 * 1.0 * (1.0 - min(0.9, 0.03 * n))
    assert rb.x[0] == pytest.approx(0.25 * k, abs=1e-12) and rb.y[0] == 0.0
    assert rb.slip[0] == pytest.approx(1.0 - k, abs=1e-12)
    assert rb.odometer[0] == pytest.approx(0.25 * k)


def test_turning_in_place_and_encoders(params):
    win = make_window(_ramp(), consts.GTYPE_ROCK)
    rb = _batch(1)
    physics_step(rb, np.asarray([[-1.0, 1.0]]), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
    assert abs(rb.x[0]) < 1e-12 and rb.s[0] > 0 and rb.slip[0] == 0.0         # v_cmd = 0 -> slip 0
    assert rb.enc_l[0] < 0 < rb.enc_r[0]


def test_slip_noise_sigma_by_ground(params):
    """Mean slip on flat ground grows with the ground sigma and falls with mu: ROCK < DUST < SAND < ICE (1 - mu and noise)."""
    out = {}
    for name, g in (("rock", 0), ("sand", 1), ("dust", 2), ("ice", 3)):
        win = make_window(_ramp(), g)
        rb = _batch(200)
        keys = np.asarray([derive(SEED, "slip", 1, 0, i) for i in range(200)], dtype=np.uint64)
        physics_step(rb, np.ones((200, 2)), win, sun_at(1, 600, params), NO_EV, keys, 0, None, params)
        out[name] = float(np.mean(rb.slip))
    assert out["rock"] < out["dust"] < out["sand"] < out["ice"]
    assert out["rock"] == pytest.approx(0.03 * 0.8, abs=0.02)


def test_storm_adds_slip(params):
    win = make_window(_ramp(), consts.GTYPE_ROCK)
    a, b = _batch(1), _batch(1)
    physics_step(a, np.ones((1, 2)), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
    physics_step(b, np.ones((1, 2)), win, sun_at(1, 600, params), STORM, _keys(1), 0, None, params)
    assert b.slip[0] - a.slip[0] == pytest.approx(0.05)


def test_uphill_is_slower_downhill_not_faster_than_vmax(params):
    # heading +x; ramp up in +x (pitch > 0) then down
    for gx, cmp in ((1.0, "slower"), (-1.0, "capped")):
        win = make_window(_ramp(gx, 0.0), consts.GTYPE_ROCK)
        rb = _batch(1)
        physics_step(rb, np.ones((1, 2)), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
        if cmp == "slower":
            assert rb.x[0] < 0.25 * 0.8
        else:
            assert rb.x[0] <= 0.25 + 1e-12


def test_sinking_then_freeing_by_reversing(params):
    """SAND uphill (pitch 0.3 -> slip > 0.5): stuck after 8 ticks; only reversing both wheels frees it after 6 ticks, 0.5 cell back."""
    win = make_window(_ramp(1.5, 0.0), consts.GTYPE_SAND)
    rb = _batch(1)
    sun = sun_at(1, 600, params)
    fwd = np.asarray([[1.0, 1.0]])
    for t in range(7):
        physics_step(rb, fwd, win, sun, NO_EV, _keys(1), t, None, params)
        assert not rb.stuck[0] and rb.slip[0] > 0.5
    physics_step(rb, fwd, win, sun, NO_EV, _keys(1), 7, None, params)
    assert rb.stuck[0]                                                         # 8th tick
    x_stuck = rb.x[0]
    for t in range(8, 14):                                                    # still pushing forward: stays stuck, no motion
        physics_step(rb, fwd, win, sun, NO_EV, _keys(1), t, None, params)
        assert rb.stuck[0] and rb.x[0] == x_stuck and rb.slip[0] == 1.0
    rev = np.asarray([[-1.0, -1.0]])
    for t in range(14, 19):
        physics_step(rb, rev, win, sun, NO_EV, _keys(1), t, None, params)
        assert rb.stuck[0]
    physics_step(rb, rev, win, sun, NO_EV, _keys(1), 19, None, params)         # 6th reversing tick
    assert not rb.stuck[0] and rb.x[0] == pytest.approx(x_stuck - 0.5 * rb.c[0], abs=1e-12)
    assert rb.sink_n[0] == 0 and rb.rev_n[0] == 0


def test_partial_reverse_does_not_free(params):
    win = make_window(_ramp(1.5, 0.0), consts.GTYPE_SAND)
    rb = _batch(1, stuck=True)
    for t in range(20):
        physics_step(rb, np.asarray([[-1.0, 0.0]]), win, sun_at(1, 600, params), NO_EV, _keys(1), t, None, params)
    assert rb.stuck[0]


def test_no_sinking_on_other_ground(params):
    for g in (0, 2, 3):
        win = make_window(_ramp(1.5, 0.0), g)
        rb = _batch(1)
        for t in range(30):
            physics_step(rb, np.ones((1, 2)), win, sun_at(1, 600, params), NO_EV, _keys(1), t, None, params)
        assert not rb.stuck[0]


@pytest.mark.parametrize("axis,limit", [("pitch", 0.70), ("roll", 0.58)])
def test_tipping_at_threshold(params, axis, limit):
    sun = sun_at(1, 600, params)
    cm = params.get("world.cell_m")
    for factor, expect in ((0.97, False), (1.03, True)):
        g = limit * cm * factor
        win = make_window(_ramp(g, 0.0) if axis == "pitch" else _ramp(0.0, g), consts.GTYPE_ROCK)
        rb = _batch(1)
        physics_step(rb, np.zeros((1, 2)), win, sun, NO_EV, _keys(1), 0, None, params)
        assert bool(rb.tipped[0]) is expect, (axis, factor)


def test_tipped_is_sticky_and_blocks(params):
    cm = params.get("world.cell_m")
    sun = sun_at(1, 600, params)
    steep = make_window(_ramp(0.8 * cm, 0.0), consts.GTYPE_ROCK)
    rb = _batch(1)
    physics_step(rb, np.ones((1, 2)), steep, sun, NO_EV, _keys(1), 0, None, params)
    assert rb.tipped[0]
    flat = make_window(_ramp(), consts.GTYPE_ROCK)
    x = rb.x[0]
    physics_step(rb, np.ones((1, 2)), flat, sun, NO_EV, _keys(1), 1, None, params)
    assert rb.tipped[0] and rb.x[0] == x and rb.slip[0] == 1.0                 # tipped until safe mode clears it
    physics_step(rb, np.zeros((1, 2)), flat, sun, NO_EV, _keys(1), 2, None, params)
    assert rb.slip[0] == 0.0


def test_asleep_zeroes_the_commands(params):
    win = make_window(_ramp(), consts.GTYPE_ROCK)
    rb = _batch(1, asleep=True)
    physics_step(rb, np.ones((1, 2)), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
    assert rb.x[0] == 0.0 and rb.slip[0] == 0.0


def test_commands_are_clipped(params):
    win = make_window(_ramp(), consts.GTYPE_ROCK)
    a, b = _batch(1), _batch(1)
    physics_step(a, np.asarray([[5.0, 5.0]]), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
    physics_step(b, np.asarray([[1.0, 1.0]]), win, sun_at(1, 600, params), NO_EV, _keys(1), 0, None, params)
    assert a.x[0] == b.x[0] and a.battery[0] == b.battery[0]


# ----- batch independence and common random numbers ------------------------------------------------------------------
@pytest.mark.parametrize("B", [1, 7, 96])
def test_batch_independence_physics(params, win, B):
    """Rover i evolves identically alone and inside a batch of 96 (same bytes after 120 ticks)."""
    n = 96
    rb = random_batch(n, 11, spread=40.0)
    keys = np.asarray([derive(SEED, "slip", 4, 1, 2, i) for i in range(n)], dtype=np.uint64)
    r = np.random.default_rng(12)
    us = r.uniform(-1, 1, (120, n, 2))
    sel = [0] if B == 1 else [5, 90, 31, 2, 64, 77, 18][:B]
    sub = take(rb, sel)
    for t in range(120):
        sun = sun_at(4, 400 + t, params)
        physics_step(rb, us[t], win, sun, NO_EV, keys, t, None, params)
        physics_step(sub, us[t][sel], win, sun, NO_EV, keys[sel], t, None, params)
    for f in ("x", "y", "c", "s", "battery", "stuck", "tipped", "slip", "odometer", "sink_n", "rev_n", "forced"):
        assert getattr(sub, f).tobytes() == np.asarray(getattr(rb, f))[sel].tobytes(), f


def test_common_random_numbers_same_key_same_draw(params, win):
    """Two candidates of one ES generation (same episode m, same K_slip) see the same slip noise whatever their command or place."""
    k = np.asarray([derive(SEED, "slip", 2, 1, 3, 0)] * 3, dtype=np.uint64)
    rb = _batch(3)
    rb.x = np.asarray([0.0, 10.0, -30.0])
    u = np.asarray([[1.0, 1.0], [0.5, 0.5], [1.0, 1.0]])
    physics_step(rb, u, win, sun_at(2, 500, params), NO_EV, k, 17, None, params)
    n = abs(float(gauss_ih4(k[:1], np.asarray(17))[0]))
    assert n == abs(float(gauss_ih4(k[1:2], np.asarray(17))[0]))
    assert rb.slip[0] != 0.0 and rb.slip[1] != 0.0
    # equal state + equal key + equal command => identical result in any slot
    a = take(random_batch(2, 3), [0, 0])
    k2 = np.asarray([derive(SEED, "slip", 2, 1, 3, 0)] * 2, dtype=np.uint64)
    physics_step(a, np.asarray([[0.7, 0.2], [0.7, 0.2]]), win, sun_at(2, 500, params), NO_EV, k2, 5, None, params)
    assert a.x[0] == a.x[1] and a.y[0] == a.y[1] and a.slip[0] == a.slip[1]


def test_distinct_keys_distinct_noise(params):
    win = make_window(_ramp(), consts.GTYPE_SAND)
    rb = _batch(2)
    keys = np.asarray([derive(SEED, "slip", 1, 0, 0), derive(SEED, "slip", 1, 0, 1)], dtype=np.uint64)
    physics_step(rb, np.ones((2, 2)), win, sun_at(1, 600, params), NO_EV, keys, 0, None, params)
    assert rb.slip[0] != rb.slip[1]


# ----- energy ---------------------------------------------------------------------------------------------------------
def _sun(elev, dz=None, day_length=12.0):
    z = np.float64(elev)
    return Sun(elev=z, dir_x=np.float64(1.0), dir_y=np.float64(0.0), dir_z=z, hour=np.float64(12.0), day_length=day_length)


def test_energy_idle_cost_and_solar_gain(params):
    E = params.get("rover.energy")
    flat = np.zeros(1)
    rb = _batch(1, battery=0.5)
    energy_step(rb, np.zeros((1, 2)), flat, flat, flat, _sun(1.0), NO_EV, params, None)
    solar = E["solar"] * 1.0 * (E["panel_base"] + (1 - E["panel_base"]) * 1.0)    # flat ground, sun straight up
    assert rb.battery[0] == pytest.approx(0.5 + solar - E["base"])
    assert rb.solar_in[0] == pytest.approx(solar)


def test_energy_night_heating_depends_on_temperature(params):
    E = params.get("rover.energy")
    flat = np.zeros(1)
    out = []
    for T in (0.0, 1.0):
        rb = _batch(1, battery=0.5)
        energy_step(rb, np.zeros((1, 2)), flat, flat, flat, _sun(0.0, day_length=12.0), NO_EV, params, None, np.asarray([T]))
        out.append(0.5 - rb.battery[0])
    assert out[0] > out[1] > E["base"] - 1e-15                                   # colder ground: more heating
    cold0 = min(1.0, max(0.0, 1.0 - (0.6 * 0.0 + 0.4 * 0.5)))                   # L = 12 h -> sin(2 pi phi) = 0 -> warmth 0.5
    assert out[0] == pytest.approx(E["base"] + E["heater"] * (1 + cold0))


def test_energy_motor_cost_and_slope_factor(params):
    E = params.get("rover.energy")
    flat = np.zeros(1)
    a = _batch(1, battery=0.5); b = _batch(1, battery=0.5)
    energy_step(a, np.asarray([[1.0, 1.0]]), flat, flat, flat, _sun(0.0), NO_EV, params, None, np.asarray([0.5]))
    energy_step(b, np.asarray([[1.0, 1.0]]), np.asarray([0.3]), flat, flat, _sun(0.0), NO_EV, params, None, np.asarray([0.5]))
    assert (0.5 - b.battery[0]) - (0.5 - a.battery[0]) == pytest.approx(E["motor"] * 2.0 * 0.3, abs=1e-12)


def test_breakdown_forced_sleep_and_resume(params):
    E = params.get("rover.energy")
    flat = np.zeros(1)
    rb = _batch(1, battery=E["cutoff"] + 1e-6)
    night = _sun(0.0)
    energy_step(rb, np.zeros((1, 2)), flat, flat, flat, night, NO_EV, params, None, np.asarray([0.5]))
    assert rb.forced[0] and rb.breakdowns[0] == 1 and rb.forced_sleep_ticks[0] == 1
    for _ in range(50):                                                           # still forced at 0.15..0.40, one breakdown only
        energy_step(rb, np.zeros((1, 2)), flat, flat, flat, night, NO_EV, params, None, np.asarray([0.5]))
    assert rb.forced[0] and rb.breakdowns[0] == 1
    rb.battery[:] = E["resume"] - 1e-9
    energy_step(rb, np.zeros((1, 2)), flat, flat, flat, _sun(1.0), NO_EV, params, None)
    assert not rb.forced[0]


@settings(max_examples=40)
@given(b0=st.floats(0.0, 1.0), elev=st.floats(0.0, 1.0), u=st.floats(-1.0, 1.0), pitch=st.floats(-1.0, 1.0),
       storm=st.booleans())
def test_battery_always_in_unit_interval(params, b0, elev, u, pitch, storm):
    rb = _batch(1, battery=b0)
    for _ in range(5):
        energy_step(rb, np.asarray([[u, -u]]), np.asarray([pitch]), np.zeros(1), np.zeros(1), _sun(elev), STORM if storm else NO_EV,
                    params, None)
        assert 0.0 <= rb.battery[0] <= 1.0


def test_storm_cuts_solar(params):
    flat = np.zeros(1)
    a, b = _batch(1, battery=0.5), _batch(1, battery=0.5)
    energy_step(a, np.zeros((1, 2)), flat, flat, flat, _sun(0.8), NO_EV, params, None)
    energy_step(b, np.zeros((1, 2)), flat, flat, flat, _sun(0.8), STORM, params, None)
    assert b.solar_in[0] == pytest.approx(0.35 * a.solar_in[0])


def test_immobile_day_covers_idle_cost_all_year(params):
    """SPEC 3.3 calibration constraint, as the model computes it on flat ground at T = 0.5 (the J7 criterion is measured later)."""
    flat = np.zeros(1)
    worst = 9.0
    for sol in range(0, 600, 10):
        rb = _batch(1, battery=1.0)
        tot = 0.0
        for tick in range(1200):
            sun = sun_at(sol, tick, params)
            before = 0.5
            rb.battery[:] = 0.5
            energy_step(rb, np.zeros((1, 2)), flat, flat, flat, sun, NO_EV, params, None, np.asarray([0.5]))
            tot += rb.battery[0] - before
        worst = min(worst, tot)
    assert worst > -0.05, worst          # recorded as measured, not an acceptance figure of J1 (SPEC leaves it to J7)


# ----- sensors --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("stage", [0, 1, 2, 3, 4, 5])
def test_observe_masks_by_stage(params, stage):
    rb = random_batch(4, 1, spread=10.0)
    rb.enc_l[:] = 0.3; rb.enc_r[:] = -0.2; rb.pitch[:] = 0.2; rb.roll[:] = -0.1; rb.slip[:] = 0.4
    sun = sun_at(3, 300, params)
    feats = np.full((4, 8), 0.7)
    target = np.asarray([[5.0, 5.0]] * 4)
    x = observe(rb, stage, target, sun, feats, np.full((4, 2), 0.1), params)
    assert x.shape == (4, 24)
    act = set(consts.M0_ACTIVE[stage])
    for i in range(24):
        if i not in act:
            assert np.all(x[:, i] == 0.0), i
    assert len(act) == (5, 5, 18, 22, 24, 24)[stage]
    assert np.all(np.abs(x) <= 1.0 + 1e-12)


def test_observe_values(params):
    rb = _batch(1, battery=0.6)
    rb.x[:] = 1.0; rb.y[:] = 2.0; rb.c[:] = 0.0; rb.s[:] = 1.0                 # heading +y
    rb.pitch[:] = 0.8                                                           # x2 then clipped to 1
    sun = sun_at(3, 300, params)
    x = observe(rb, 4, np.asarray([[1.0, 22.0]]), sun, np.zeros((1, 8)), np.zeros((1, 2)), params)
    assert x[0, 2] == 1.0
    assert x[0, 15] == pytest.approx(1.0) and x[0, 16] == pytest.approx(0.0, abs=1e-12)   # target straight ahead
    assert x[0, 17] == pytest.approx(0.5)                                         # 20 cells / 40
    assert x[0, 18] == 0.6 and x[0, 19] == pytest.approx(float(sun.elev))
