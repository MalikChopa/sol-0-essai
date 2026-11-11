"""M1 (R2 with 300 vs 40 pairs), M2 (explained variance grows, constant input stays finite, Sanger convergence)."""
from __future__ import annotations

import copy

import numpy as np
from hypothesis import given, settings, strategies as st

from rover.brain.brain import Brain
from rover.brain.m1_model import r2_score, train_m1
from rover.brain.m2_encoder import explained_variance, train_m2
from rover.brain.mlp import m2_descriptors, visual_features
from rover.core.rng import gauss_ih4, uniform

from brain_synth import synthetic_couples


def test_m1_r2_reaches_0_7_with_300_pairs_but_not_0_9_with_40(params):
    m1 = Brain.initial(params, 1)["m1"]
    a = train_m1(copy.deepcopy(m1), synthetic_couples(300), 1, 50, 200, params)
    b = train_m1(copy.deepcopy(m1), synthetic_couples(40), 1, 50, 200, params)
    assert a["n_holdout"] > 0 and b["n_holdout"] > 0
    assert a["r2"] >= 0.7, a
    assert b["r2"] < 0.9, b


def test_m1_training_is_deterministic(params):
    m1 = Brain.initial(params, 1)["m1"]
    a, b = copy.deepcopy(m1), copy.deepcopy(m1)
    train_m1(a, synthetic_couples(120), 1, 7, 30, params)
    train_m1(b, synthetic_couples(120), 1, 7, 30, params)
    assert a["theta"].tobytes() == b["theta"].tobytes() and a["adam_v"].tobytes() == b["adam_v"].tobytes()


def test_m1_degenerate_inputs_are_finite(params):
    m1 = Brain.initial(params, 1)["m1"]
    rows = synthetic_couples(100)
    rows[:, 4] = 0.25                        # constant column: std floors at 1e-6, x - mean is exactly 0
    rows[:, 6] = 0.0                         # constant output: R2 of that output counts 0.0 (never a division by zero)
    r = train_m1(m1, rows, 1, 5, 20, params)
    assert np.isfinite(r["r2"]) and np.all(np.isfinite(m1["theta"]))
    assert r2_score(np.zeros((5, 3)), np.ones((5, 3))) == 0.0


def test_m1_report_names_the_worst_terrain(params):
    rows = synthetic_couples(200)
    rows[:, 9] = (np.arange(200) % 2).astype(np.float64)
    rows[rows[:, 9] == 1.0, 5] += 3.0 * np.asarray([1.0, -1.0] * 50)       # terrain 1 (sand) is unpredictable
    r = train_m1(Brain.initial(params, 1)["m1"], rows, 1, 5, 100, params)
    assert r["worst_terrain"] == "sand"


def _images(n: int, key: int = 3) -> np.ndarray:
    """Fictitious descriptors with a 4-dimensional structure plus small noise."""
    basis = np.stack([gauss_ih4(key, np.arange(40) + 40 * j) for j in range(4)])
    coef = np.stack([gauss_ih4(key + 1, np.arange(n) + n * j) for j in range(4)], axis=1) * np.asarray([3.0, 2.0, 1.5, 1.0])
    noise = np.stack([gauss_ih4(key + 2, np.arange(40) + 40 * i) for i in range(n)]) * 0.1
    return np.asarray([float(0.5)] * 40) + np.stack([np.asarray([float(np.sum(coef[i] * basis[:, j])) for j in range(40)])
                                                    for i in range(n)]) * 0.1 + noise * 0.1


def test_m2_explained_variance_increases(params):
    m2 = Brain.initial(params, 1)["m2"]
    z = _images(150)
    before = explained_variance(m2["w"], z)                               # random initial components
    ev = [train_m2(m2, z, params)["explained"] for _ in range(12)]
    assert ev[-1] > before + 0.3, (before, ev)
    assert all(b >= a - 0.02 for a, b in zip(ev, ev[1:]))                 # increasing (up to a small tolerance)
    assert m2["n_sols"] == 12


def test_m2_explained_variance_of_a_constant_input_is_zero(params):
    m2 = Brain.initial(params, 1)["m2"]
    assert explained_variance(m2["w"], np.full((20, 40), 0.3)) == 0.0
    assert train_m2(m2, np.full((20, 40), 0.3), params)["explained"] == 0.0
    assert np.all(np.isfinite(m2["w"]))


@settings(max_examples=40)
@given(lum=st.integers(0, 23), depth=st.integers(0, 40), slip=st.floats(0, 1))
def test_constant_input_gives_finite_outputs(lum, depth, slip):
    from rover import config
    from pathlib import Path
    params = config.load(Path(__file__).resolve().parents[2] / "config")
    b = Brain.initial(params, 1)
    img = np.full((3, 20, 32), lum, dtype=np.uint8)
    dep = np.full((3, 20, 32), depth, dtype=np.uint8)
    z = m2_descriptors(img, dep, 40)
    f = visual_features(z, b["m2"]["mean"], np.zeros(40), b["m2"]["w"])        # variance 0: safe_std floors at 1e-6
    assert np.all(np.isfinite(z)) and np.all(np.isfinite(f)) and np.all(np.abs(f) <= 1.0)
    m2 = copy.deepcopy(b["m2"])
    assert np.isfinite(train_m2(m2, np.tile(z, (8, 1)), params)["explained"])
    assert np.all(np.isfinite(m2["w"]))
