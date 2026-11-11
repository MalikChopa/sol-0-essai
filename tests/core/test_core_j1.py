"""core: PRNG (numpy = pure Python), noise, exact primitives, dmath (fictitious data only)."""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from rover.core import dmath, exact, rng
from rover.core.noise import fbm

M = (1 << 64) - 1


def _mix_py(z):
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M
    return z ^ (z >> 31)


def _u64_py(key, i):
    return _mix_py((key + (i + 1) * 0x9E3779B97F4A7C15) & M)


def test_splitmix_numpy_equals_pure_python_10000():
    key = rng.derive(7, "height")
    idx = np.arange(10000)
    got = rng.u64(key, idx)
    want = [_u64_py(key, i) for i in range(10000)]
    assert got.tolist() == want


def test_key_array_broadcast_one_key_per_rover():
    keys = np.asarray([rng.derive(1, "cam", 0, i) for i in range(5)], dtype=np.uint64)
    a = rng.uniform(keys[:, None], np.arange(7)[None, :])
    for i in range(5):
        assert np.array_equal(a[i], rng.uniform(int(keys[i]), np.arange(7)))


def test_uniform_range_and_gauss_moments():
    k = rng.derive(3, "grain")
    u = rng.uniform(k, np.arange(200000))
    assert u.min() >= 0.0 and u.max() < 1.0
    g = rng.gauss_ih4(k, np.arange(100000))
    assert abs(exact.fsum(g) / g.size) < 0.02
    assert abs(exact.fsum(g * g) / g.size - 1.0) < 0.03


def test_derive_domain_separation_and_range():
    assert rng.derive(1, "slip", 2) != rng.derive(1, "cam", 2)
    assert rng.derive(1, "slip", 2) != rng.derive(1, "slip", 3)
    with pytest.raises(AssertionError):
        rng.derive(1 << 63, "slip")


@given(st.integers(0, 10**9), st.integers(1, 1000))
def test_randint_bounds(seed, n):
    r = rng.randint(rng.derive(seed, "event", 1), np.arange(200), n)
    assert r.min() >= 0 and r.max() < n


def test_fbm_range_and_block_independence():
    k = rng.derive(5, "height")
    xs = np.arange(-70.0, 70.0)
    X, Y = np.meshgrid(xs, xs)
    big = fbm(k, X, Y, 6, 256.0)
    assert big.min() >= 0.0 and big.max() <= 1.0
    sub = fbm(k, X[10:50, 20:90], Y[10:50, 20:90], 6, 256.0)       # same values whatever the block shape
    assert np.array_equal(sub, big[10:50, 20:90])


def test_fbm_continuous_at_lattice_and_varies():
    k = rng.derive(5, "dune")
    a = fbm(k, np.asarray([23.9999999]), np.asarray([5.0]), 1, 24.0)
    b = fbm(k, np.asarray([24.0000001]), np.asarray([5.0]), 1, 24.0)
    assert abs(a[0] - b[0]) < 1e-6
    v = fbm(k, np.arange(500.0), np.zeros(500), 2, 24.0)
    assert v.std() > 0.05


def test_dmath_accuracy():
    x = np.arange(-50.0, 50.0, 0.013)
    assert np.max(np.abs(dmath.sin(x) - np.sin(x))) < 1e-6
    assert np.max(np.abs(dmath.cos(x) - np.cos(x))) < 1e-6
    t = np.arange(-30.0, 30.0, 0.05)
    assert np.max(np.abs(dmath.atan(t) - np.arctan(t))) < 1e-6


@given(st.floats(-3.0, 3.0), st.floats(-1.0, 1.0))
def test_rot_keeps_unit_norm(a, w):
    c, s = dmath.rot(np.asarray([np.cos(a)]), np.asarray([np.sin(a)]), np.asarray([w]))
    assert abs(float(c[0] * c[0] + s[0] * s[0]) - 1.0) < 1e-12


def test_dot_fixed_equals_reference_loop():
    r = np.random.default_rng(0)           # test data only
    x = r.normal(size=(5, 12))
    W = r.normal(size=(5, 12, 7))
    got = exact.dot_fixed(x, W)
    for b in range(5):
        for o in range(7):
            acc = x[b, 0] * W[b, 0, o]
            for i in range(1, 12):
                acc = acc + x[b, i] * W[b, i, o]
            assert got[b, o] == acc


def test_to_int_rejects_non_finite_and_huge():
    assert exact.to_int(np.asarray([1.9, -1.9])).tolist() == [1, -1]
    with pytest.raises(AssertionError):
        exact.to_int(np.asarray([np.nan]))
    with pytest.raises(AssertionError):
        exact.to_int(np.asarray([2.0 ** 60]))
