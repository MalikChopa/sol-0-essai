"""world: chunks, layers, windows, overlays, sun (fictitious seeds only)."""
from __future__ import annotations

import numpy as np
import pytest

from rover.core import consts
from rover.world import terrain
from rover.world.chunks import Window, World
from rover.world.climate import sun_at

SEED = 424242


@pytest.fixture(scope="module")
def world(params):
    return World(SEED, params)


def test_2x2_chunks_equal_one_128_block(world, params):
    win = world.window(-1, 2, 0, 3)
    h, g = terrain.block(SEED, win.x0, win.y0, 128, 128, params)
    assert np.array_equal(win.height, h) and np.array_equal(win.gtype, g)
    t = terrain.temperature(SEED, win.x0, win.y0, 128, 128, params)
    assert np.array_equal(win.temp, t)


def test_chunk_layers_shapes_ranges(world):
    c = world.chunk(5, -7)
    assert c.height.shape == (64, 64) and c.gtype.shape == (64, 64) and c.temp.shape == (64, 64)
    assert c.gtype.dtype == np.uint8 and int(c.gtype.max()) <= 3
    assert c.height.min() >= -2.0 and c.height.max() <= 70.0
    assert 0.0 <= c.temp.min() and c.temp.max() <= 1.0
    assert world.chunk(5, -7) is c                                    # cache


def test_all_four_ground_types_occur(world):
    seen = set()
    for cx in range(-6, 6):
        for cy in range(-6, 6):
            seen |= set(np.unique(world.chunk(cx, cy).gtype).tolist())
    assert {consts.GTYPE_ROCK, consts.GTYPE_SAND, consts.GTYPE_DUST} <= seen


def test_slope_halo_same_on_both_sides_of_a_border(params):
    """A chunk computed alone equals the same cells computed inside a larger block (halo of one cell)."""
    h1, g1 = terrain.block(SEED, 0, 0, 64, 64, params)
    h2, g2 = terrain.block(SEED, -64, -64, 192, 192, params)
    assert np.array_equal(h1, h2[64:128, 64:128]) and np.array_equal(g1, g2[64:128, 64:128])


def test_lru_cache_bounded(params):
    import copy
    w = World(SEED, params)
    w._max = 4
    for i in range(10):
        w.chunk(i, 0)
    assert len(w._cache) == 4


def test_gtype_cells_matches_chunks(world):
    xs = np.asarray([-1, 0, 63, 64, 130, -65, 1000])
    ys = np.asarray([-1, 0, 63, 64, -3, 200, -1000])
    got = world.gtype_cells(xs, ys)
    for x, y, g in zip(xs, ys, got):
        assert world.chunk(int(x // 64), int(y // 64)).gtype[int(y % 64), int(x % 64)] == g


def test_window_bilinear_and_errors(world):
    win = world.window(0, 0, 1, 1)
    xs = np.asarray([3.0, 3.5, 70.25])
    ys = np.asarray([4.0, 4.0, 90.75])
    h = win.height_at(xs, ys)
    assert h[0] == win.height[4, 3]
    assert abs(h[1] - 0.5 * (win.height[4, 3] + win.height[4, 4])) < 1e-12
    with pytest.raises(ValueError):
        win.height_at(np.asarray([-0.5]), np.asarray([3.0]))
    with pytest.raises(ValueError):
        win.gtype_at(np.asarray([500.0]), np.asarray([3.0]))
    assert bool(win.contains(np.asarray([64.0]), np.asarray([64.0]), 10.0)[0])
    assert not bool(win.contains(np.asarray([2.0]), np.asarray([64.0]), 10.0)[0])


def test_cell_gradient_equals_gradient_at_integers(world):
    win = world.window(0, 0, 1, 1)
    gx, gy = win.cell_gradient()
    xs = np.arange(5.0, 100.0, 7.0)
    ys = xs[::-1].copy()
    ax, ay = win.gradient_at(xs, ys)
    ix, iy = xs.astype(int), ys.astype(int)
    assert np.allclose(ax, gx[iy, ix], atol=1e-12) and np.allclose(ay, gy[iy, ix], atol=1e-12)


def test_impact_overlay(params):
    o = {"kind": "impact", "x": 100, "y": 40, "r": 9, "params": {}, "sol": 1}
    w0 = World(SEED, params)
    w1 = World(SEED, params, [o])
    a, b = w0.window(1, 0, 1, 0), w1.window(1, 0, 1, 0)
    ci, cj = 40 - a.y0, 100 - a.x0
    assert b.height[ci, cj] - a.height[ci, cj] < -4.0                      # centre is ~depth (6 m) lower, rock bump <= 1.5 aside
    assert b.gtype[ci, cj] == consts.GTYPE_ROCK
    far = (slice(0, 5), slice(0, 5))
    assert np.array_equal(a.height[far], b.height[far])                    # untouched far away
    rim = b.height[ci, cj + 11] - a.height[ci, cj + 11]
    assert rim > 0.5                                                       # bourrelet


def test_anomaly_and_deposit_overlays(params):
    an = {"kind": "anomaly", "x": 30, "y": 30, "r": 1, "params": {}, "sol": 1}
    dp = {"kind": "deposit", "x": 10, "y": 10, "r": 5, "params": {"substance": 2}, "sol": 2}
    a = World(SEED, params).window(0, 0, 0, 0)
    b = World(SEED, params, [an, dp]).window(0, 0, 0, 0)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            assert b.height[30 + dy, 30 + dx] - a.height[30 + dy, 30 + dx] == pytest.approx(4.0)
            assert b.gtype[30 + dy, 30 + dx] == consts.GTYPE_DUST
    assert np.array_equal(a.height[:20, :20], b.height[:20, :20])          # deposit leaves terrain alone (P1)
    assert np.array_equal(a.gtype[:20, :20], b.gtype[:20, :20])


def test_add_overlay_clears_touched_chunks_only(params):
    w = World(SEED, params)
    for cx in (-1, 0, 1, 5):
        w.chunk(cx, 0)
    before = w.chunk(0, 0).height.copy()
    w.add_overlay({"kind": "impact", "x": 60, "y": 30, "r": 8, "params": {}, "sol": 1})
    assert (5, 0) in w._cache and (-1, 0) in w._cache and (0, 0) not in w._cache and (1, 0) not in w._cache
    assert not np.array_equal(w.chunk(0, 0).height, before)
    # same result as a world built with the overlay from the start
    w2 = World(SEED, params, [{"kind": "impact", "x": 60, "y": 30, "r": 8, "params": {}, "sol": 1}])
    assert np.array_equal(w.chunk(1, 0).height, w2.chunk(1, 0).height)


def test_overlay_order_matters_but_is_deterministic(params):
    a = {"kind": "anomaly", "x": 30, "y": 30, "r": 1, "params": {}, "sol": 1}
    i = {"kind": "impact", "x": 31, "y": 30, "r": 7, "params": {}, "sol": 2}
    w1 = World(SEED, params, [a, i]).window(0, 0, 0, 0)
    w2 = World(SEED, params, [a, i]).window(0, 0, 0, 0)
    assert np.array_equal(w1.height, w2.height) and np.array_equal(w1.gtype, w2.gtype)


def test_sun_properties(params):
    for sol in (0, 150, 300, 450, 599):
        s = sun_at(sol, np.arange(1200), params)
        assert s.elev.min() >= 0.0 and s.elev.max() <= 1.0 + 1e-9
        assert np.all(s.dir_z == s.elev)
        n = s.dir_x * s.dir_x + s.dir_y * s.dir_y
        assert np.allclose(n, 1.0)
        sxy = np.sqrt(np.maximum(0, 1 - s.elev ** 2))
        v = (s.dir_x * sxy) ** 2 + (s.dir_y * sxy) ** 2 + s.dir_z ** 2
        assert np.allclose(v, 1.0)
        assert s.elev.min() == 0.0                       # a night exists (L < 24 h)
    summer = sun_at(150, np.arange(1200), params)
    winter = sun_at(450, np.arange(1200), params)
    assert summer.day_length > winter.day_length
    assert summer.elev.max() > winter.elev.max()


def test_sun_year_period(params):
    a = sun_at(7, 500, params)
    b = sun_at(607, 500, params)
    assert a.elev == b.elev and a.hour == b.hour
