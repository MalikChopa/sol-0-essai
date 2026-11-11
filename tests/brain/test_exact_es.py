"""dot_fixed against a pure Python reference; ES on a quadratic; antithetic structure; Adam beta^t in the state."""
from __future__ import annotations

import numpy as np

from rover.brain.adam import adam_step
from rover.brain.brain import Brain
from rover.brain.es import es_candidates, es_generation, es_gradient, es_noise
from rover.core.exact import dot_fixed
from rover.core.rng import gauss_ih4


def test_dot_fixed_equals_pure_python_reference():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(5, 24))
    W = rng.normal(size=(24, 16))
    ref = np.zeros((5, 16))
    for b in range(5):
        for j in range(16):
            acc = x[b, 0] * W[0, j]
            for i in range(1, 24):
                acc = acc + x[b, i] * W[i, j]
            ref[b, j] = acc
    assert dot_fixed(x, W).tobytes() == ref.tobytes()
    Wb = np.stack([W, -W])
    got = dot_fixed(x[:2], Wb)
    assert got.tobytes() == np.stack([ref[0], -ref[1]]).tobytes()


def test_es_noise_is_the_documented_stream():
    e = es_noise(123, 3, 10)
    assert e.tobytes() == gauss_ih4(123, np.arange(30)).reshape(3, 10).tobytes()
    c = es_candidates(np.zeros(10), e, 0.05)
    assert c[:3].tobytes() == (0.05 * e).tobytes() and c[3:].tobytes() == (-0.05 * e).tobytes()


def test_es_gradient_points_uphill_on_a_linear_fitness():
    e = es_noise(5, 24, 8)
    c = es_candidates(np.zeros(8), e, 0.05)
    target = np.arange(8, dtype=np.float64)
    g = es_gradient(np.asarray([float(np.sum(r * target)) for r in c]), e, 0.05)
    assert float(np.sum(g * target)) > 0


def test_es_converges_on_a_quadratic(params):
    cfg = dict(params.get("brain.es"))
    target = np.linspace(-0.5, 0.5, 20)
    net = {"theta": np.zeros(20, dtype=np.float32), "adam_m": np.zeros(20, dtype=np.float32),
           "adam_v": np.zeros(20, dtype=np.float32), "b1t": 1.0, "b2t": 1.0}
    fit = lambda th: -np.asarray([float(np.sum((r - target) ** 2)) for r in th])
    d0 = float(np.sum((net["theta"] - target) ** 2))
    for g in range(300):
        es_generation(net, fit, 1000 + g, int(cfg["pop"]), cfg, "m0")
    d1 = float(np.sum((net["theta"].astype(np.float64) - target) ** 2))
    assert d1 < 0.05 * d0
    assert abs(net["b1t"] - 0.9 ** 300) < 1e-12                    # beta^t kept in the state (no exponent at run time)


def test_adam_keeps_beta_powers():
    net = {"b1t": 1.0, "b2t": 1.0}
    th = np.zeros(3)
    m = v = np.zeros(3)
    for _ in range(4):
        th, m, v = adam_step(net, th, m, v, np.ones(3), 0.1, 0.9, 0.999, 1e-8)
    assert net["b1t"] == ((((1.0 * 0.9) * 0.9) * 0.9) * 0.9)
    assert np.all(th < 0)


def test_initial_state_matches_spec(params):
    b = Brain.initial(params, 1)
    assert b["m0"]["theta"].shape == (434,) and b["m1"]["theta"].shape == (147,) and b["m3"]["theta"].shape == (99,)
    assert b["m2"]["w"].shape == (8, 40) and b["m4"] is None and b["m5"] is None
    assert b["m0"]["b1t"] == 1.0 and float(np.sum(np.abs(b["m0"]["adam_m"]))) == 0.0
    assert all(b[k]["theta"].dtype == np.float32 for k in ("m0", "m1", "m3"))
