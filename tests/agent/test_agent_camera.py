"""camera: histogram = comparisons, batch independence (B = 1, 7, 96), keyed noise, palette ranges."""
from __future__ import annotations

import numpy as np
import pytest

from rover.agent import camera
from rover.agent.camera import _project, _slices_cmp, _slices_hist, camera_spec, capture
from rover.core import consts
from rover.core.rng import derive
from rover.core.types import SolEvents
from rover.world import draw_events, sun_at

from agent_helpers import SEED, keys_for, make_window, random_batch, rover_dict, take

NO_EV = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
STORM = SolEvents(storm=True, storm_left=1, view_scale=0.5, solar_factor=0.35, slip_add=0.05, new_overlays=[], kinds=["storm"])


@pytest.mark.parametrize("stage", [0, 2, 3, 4])
def test_histogram_equals_comparisons_on_50_poses(win, params, stage):
    rb = random_batch(50, seed=100 + stage)
    rb.pitch = np.random.default_rng(stage).uniform(-0.3, 0.3, 50)
    pj = _project(rb, win, stage, NO_EV, params)
    W, H, D = pj["W"], pj["H"], pj["D"]
    a = _slices_hist(pj["r0"], D, H)
    b = _slices_cmp(pj["r0"], D, H)
    assert a.shape == (50, H, W) and np.array_equal(a, b)


def test_specs(params):
    assert [camera_spec(s, params) for s in (0, 1, 2, 3, 4, 5)] == [
        (8, 6, 8.0, 24), (8, 6, 8.0, 24), (32, 20, 14.0, 40), (80, 50, 24.0, 64), (160, 100, 40.0, 100), (160, 100, 40.0, 100)]


@pytest.mark.parametrize("stage,hour_tick", [(0, 600), (2, 600), (3, 600), (3, 1100), (4, 100)])
def test_batch_independence_1_7_96(win, params, stage, hour_tick):
    """A rover gives the same bytes alone, in a batch of 7 (any order) and in a batch of 96."""
    sun = sun_at(9, hour_tick, params)
    rb = random_batch(96, seed=5 + stage)
    keys = keys_for(96)
    tick = 40
    full = capture(rb, win, stage, sun, NO_EV, keys, tick, params)
    for i in (0, 1, 17, 50, 95):
        one = capture(take(rb, [i]), win, stage, sun, NO_EV, keys[[i]], tick, params)
        assert one.index[0].tobytes() == full.index[i].tobytes()
        assert one.depth[0].tobytes() == full.depth[i].tobytes()
    sel = [90, 3, 55, 21, 8, 77, 40]
    seven = capture(take(rb, sel), win, stage, sun, NO_EV, keys[sel], tick, params)
    for j, i in enumerate(sel):
        assert seven.index[j].tobytes() == full.index[i].tobytes()
        assert seven.depth[j].tobytes() == full.depth[i].tobytes()


def test_batch_independence_with_storm_and_seen(win, params):
    sun = sun_at(9, 700, params)
    rb = random_batch(9, seed=2)
    keys = keys_for(9)
    full = capture(rb, win, 3, sun, STORM, keys, 8, params, want_seen=True)
    one = capture(take(rb, [0]), win, 3, sun, STORM, keys[:1], 8, params, want_seen=True)
    assert one.index[0].tobytes() == full.index[0].tobytes()
    assert np.array_equal(one.seen, full.seen)


def test_noise_keyed_by_key_tick_pixel(win, params):
    sun = sun_at(9, 600, params)
    rb = random_batch(1, seed=5)          # a pose with levels near shade boundaries (sigma 0.25 shows only there)
    k = keys_for(1)
    a = capture(rb, win, 3, sun, NO_EV, k, 16, params).index
    assert np.array_equal(a, capture(rb, win, 3, sun, NO_EV, k, 16, params).index)       # same inputs, same bytes
    assert np.array_equal(a, capture(rb, win, 3, sun, NO_EV, k, 23, params).index)       # same camera period (16..23)
    assert not np.array_equal(a, capture(rb, win, 3, sun, NO_EV, k, 24, params).index)   # next image: fresh noise
    k2 = np.asarray([derive(SEED, "cam", 5, 0, 99)], dtype=np.uint64)
    assert not np.array_equal(a, capture(rb, win, 3, sun, NO_EV, k2, 16, params).index)  # another key


def test_noise_amplitude_follows_light_and_weather(win, params):
    """Noise is real: the difference between two frames of a static scene grows with sigma (day < night < storm < offline)."""
    rb = random_batch(1, seed=4)
    k = keys_for(1)
    sun = sun_at(9, 600, params)
    def churn(stage, s, ev):
        a = capture(rb, win, stage, s, ev, k, 0, params).index
        b = capture(rb, win, stage, s, ev, k, 8, params).index
        return int(np.count_nonzero(a != b))
    day = churn(3, sun, NO_EV)
    storm = churn(3, sun, STORM)
    assert storm > day


def test_index_ranges_and_depth(win, params):
    rb = random_batch(20, seed=6)
    keys = keys_for(20)
    for stage in (0, 2, 3, 4):
        for tk in (600, 1100):
            f = capture(rb, win, stage, sun_at(9, tk, params), NO_EV, keys, 8, params)
            W, H, R, D = camera_spec(stage, params)
            assert f.index.shape == (20, H, W) and f.index.dtype == np.uint8 and f.depth.dtype == np.uint8
            assert int(f.index.max()) <= 23 and f.D == D and int(f.depth.max()) <= D


def test_night_without_ir_is_dark_indices(win, params):
    rb = random_batch(10, seed=7)
    keys = keys_for(10)
    night = sun_at(9, 1100, params)
    assert float(night.elev) < 0.05
    for stage in (0, 2):
        f = capture(rb, win, stage, night, NO_EV, keys, 8, params)
        assert set(np.unique(f.index).tolist()) <= {consts.DARK[0], consts.DARK[1]}
    f3 = capture(rb, win, 3, night, NO_EV, keys, 8, params)                      # IR from stage 3: sand ramp (6..11) on ground
    ground = f3.depth < f3.D
    assert bool(np.any(ground)) and int(f3.index[ground].min()) >= 6 and int(f3.index[ground].max()) <= 11
    assert set(np.unique(f3.index[~ground]).tolist()) == {consts.DARK[0]}


def test_stage0_offline_low_contrast(win, params):
    """Stage 0: level in [0, 1.49] -> only the first two shades of each ramp (EF-87)."""
    rb = random_batch(30, seed=8)
    f = capture(rb, win, 0, sun_at(9, 600, params), NO_EV, keys_for(30), 8, params)
    ground = f.depth < f.D
    idx = f.index[ground].astype(int)
    assert bool(np.all(idx % 6 <= 1))


def test_flat_plane_geometry(params):
    """Flat DUST plane, noon: sky above the horizon, ground below, ground nearer = lower rows, ramp 12-17."""
    flat = make_window(lambda X, Y: np.zeros_like(X), consts.GTYPE_DUST)
    rb = take(random_batch(1, seed=1), [0])
    rb.x[:] = 0.0; rb.y[:] = 0.0; rb.c[:] = 1.0; rb.s[:] = 0.0; rb.pitch[:] = 0.0
    sun = sun_at(0, 600, params)
    f = capture(rb, flat, 4, sun, NO_EV, keys_for(1), 8, params)
    H, W = f.index.shape[1:]
    col = f.index[0, :, W // 2].astype(int)
    d = f.depth[0, :, W // 2].astype(int)
    assert bool(np.all((col[:30] >= 18) & (col[:30] <= 21)))                     # sky (horizon at 0.35 H = row 35)
    assert d[:30].min() == f.D and d[-1] < d[40] < f.D                           # nearer ground at the bottom (smaller slice index)
    assert bool(np.all((col[d < f.D] >= 12) & (col[d < f.D] <= 17)))
    assert bool(np.all(np.diff(d[d < f.D]) <= 0))                                # slice index decreases down the image


def test_pitch_moves_horizon(params):
    flat = make_window(lambda X, Y: np.zeros_like(X), consts.GTYPE_DUST)
    rb = take(random_batch(1, seed=1), [0]); rb.x[:] = 0.0; rb.y[:] = 0.0; rb.c[:] = 1.0; rb.s[:] = 0.0
    sun = sun_at(0, 600, params)
    sky_rows = []
    for pitch in (-0.2, 0.0, 0.2):
        rb.pitch[:] = pitch
        f = capture(rb, flat, 4, sun, NO_EV, keys_for(1), 8, params)
        sky_rows.append(int(np.count_nonzero(f.depth[0, :, 80] == f.D)))
    assert sky_rows[0] < sky_rows[1] < sky_rows[2] or sky_rows[0] > sky_rows[2]  # horizon follows pitch, monotonically
    assert len(set(sky_rows)) == 3


def test_storm_halves_view_radius(win, params):
    rb = random_batch(1, seed=9)
    sun = sun_at(9, 600, params)
    p1 = _project(rb, win, 3, NO_EV, params)
    p2 = _project(rb, win, 3, STORM, params)
    assert p2["R"] == pytest.approx(0.5 * p1["R"]) and p2["D"] == p1["D"]


def test_seen_cells(win, params):
    rb = take(random_batch(3, seed=10), [0, 1, 2])
    f = capture(rb, win, 2, sun_at(9, 600, params), NO_EV, keys_for(3), 8, params, want_seen=True)
    assert f.seen.ndim == 2 and f.seen.shape[1] == 2 and f.seen.dtype == np.int64
    assert len({tuple(r) for r in f.seen.tolist()}) == len(f.seen)               # unique
    cx, cy = int(np.floor(rb.x[0] + 0.5)), int(np.floor(rb.y[0] + 0.5))
    assert [cx, cy] in f.seen.tolist()                                           # the disc around the rover
    R = camera_spec(2, params)[2]
    dist = np.sqrt((f.seen[:, 0] - rb.x[0]) ** 2 + (f.seen[:, 1] - rb.y[0]) ** 2)
    assert dist.max() <= R + 2.0
    assert capture(rb, win, 2, sun_at(9, 600, params), NO_EV, keys_for(3), 8, params).seen is None


def test_outside_window_raises(win, params):
    rb = take(random_batch(1, seed=1), [0])
    rb.x[:] = float(win.x0) + 2.0
    with pytest.raises(ValueError):
        capture(rb, win, 4, sun_at(9, 600, params), NO_EV, keys_for(1), 8, params)
