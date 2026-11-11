"""Reference fingerprints of the brain package (ARCH 6): same bytes on every machine."""
from __future__ import annotations

import numpy as np

from rover.brain.battery import evaluate_regression, make_courses, run_battery
from rover.brain.brain import Brain
from rover.brain.es import es_candidates, es_gradient, es_noise
from rover.brain.m1_model import train_m1
from rover.brain.m2_encoder import train_m2
from rover.brain.m3_energy import rollout_m3_fitness
from rover.brain.mlp import m2_descriptors, mlp_forward
from rover.brain.rollouts import rollout_fitness
from rover.core.exact import fsum, to_int
from rover.core.hashing import canonical_json, sha256_hex
from rover.core.rng import gauss_ih4, uniform
from rover.world.chunks import World


def _h(*arrays) -> str:
    return "sha256:" + sha256_hex(b"".join(np.asarray(a).tobytes() for a in arrays))


def _couples(n: int) -> np.ndarray:
    i = np.arange(n)
    u = lambda j: uniform(11, i * 8 + j)
    uL, uR, slip = 2 * u(0) - 1, 2 * u(1) - 1, 0.3 * u(4)
    y = np.stack([5.0 * (uL + uR) / 2 * (1 - slip), 0.2 * u(2), 10.0 * (uR - uL) * (1 - slip)], axis=1)
    return np.concatenate([np.stack([uL, uR, 0.1 * u(2), 0.1 * u(3), slip], axis=1), y,
                           np.stack([(i // 6 + 1).astype(np.float64), np.zeros(n)], axis=1)], axis=1)


def fingerprints(params) -> dict:
    seed = int(params.get("run.world_seed"))
    b = Brain.initial(params, seed)
    x = uniform(7, np.arange(24)) * 2.0 - 1.0
    y, h = mlp_forward(b["m0"]["theta"], x[None, :], 24, 16, 2)
    rng_img = (uniform(11, np.arange(6 * 8)) * 24.0)
    ii = to_int(np.floor(rng_img), np.uint8).reshape(1, 6, 8)
    z = m2_descriptors(ii, ii, 24)
    out = {"brain.initial_m0": _h(b["m0"]["theta"]), "brain.initial_m1": _h(b["m1"]["theta"]),
           "brain.initial_m2": _h(b["m2"]["w"]), "brain.initial_m3": _h(b["m3"]["theta"]),
           "brain.m0_forward": _h(y, h), "brain.m2_descriptors": _h(z)}
    eps = es_noise(5, 6, 10)
    fit = np.asarray([fsum(r * np.arange(10)) for r in es_candidates(np.zeros(10), eps, 0.05)])
    out["brain.es_gradient"] = _h(es_gradient(fit, eps, 0.05))
    m1 = Brain.initial(params, seed)["m1"]
    rep = train_m1(m1, _couples(90), seed, 7, 25, params)
    out["brain.m1_train"] = _h(m1["theta"], m1["x_std"], m1["adam_m"], np.asarray([rep["r2"], m1["b1t"]]))
    m2 = Brain.initial(params, seed)["m2"]
    zz = np.stack([gauss_ih4(3, np.arange(40) + 40 * i) for i in range(12)]) * 0.2 + 0.5
    rep2 = train_m2(m2, zz, params)
    out["brain.m2_train"] = _h(m2["w"], m2["mean"], m2["var"], np.asarray([rep2["explained"]]))
    courses = make_courses(seed, params)
    out["brain.battery_courses"] = "sha256:" + sha256_hex(canonical_json([list(c) for c in courses]))
    world = World(seed, params)
    th = np.stack([b["m0"]["theta"].astype(np.float64) * s for s in (1.0, 2.0, -1.0)])
    out["brain.rollout_m0"] = _h(rollout_fitness(world, params, 2, th, b["m2"], 3, 0, 1, (0.0, 0.0)))
    br = Brain.from_state(b, 2, params)
    res = run_battery(br, world, 2, params)
    out["brain.battery_run"] = "sha256:" + sha256_hex(canonical_json([res.successes, res.per_course]))
    th3 = np.stack([b["m3"]["theta"].astype(np.float64), b["m3"]["theta"].astype(np.float64) * 3.0])
    out["brain.rollout_m3"] = _h(rollout_m3_fitness(world, params, th3, None, 3, 0, (0.0, 0.0)))
    m = {"battery": [18, 19, 20], "battery_stage": [2, 2, 2], "battery_sol": [10, 11, 12], "battery_low": 1}
    v = evaluate_regression(m, 15, 2, params, {10, 12})
    out["brain.regression"] = "sha256:" + sha256_hex(canonical_json([v.low, v.restore_sol, v.warning, v.threshold]))
    return out
