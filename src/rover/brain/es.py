"""Evolution strategy (SPEC 4.5): antithetic, centred ranks, ordered gradient, Adam ascent with L2 decay."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from rover.brain.adam import adam_step, load_work, store_work
from rover.core.exact import centered_ranks
from rover.core.rng import derive, gauss_ih4
from rover.core.types import NonFiniteError

Arr = np.ndarray


def es_noise(key: int, n_pairs: int, npar: int) -> Arr:
    """(n_pairs, npar) ~N(0, 1): gauss_ih4(key, arange(n_pairs * npar)) (SPEC 4.5)."""
    return gauss_ih4(key, np.arange(n_pairs * npar)).reshape(n_pairs, npar)


def es_candidates(theta: Arr, eps: Arr, sigma: float) -> Arr:
    """(2 * n_pairs, npar): rows 0..n-1 = theta + sigma*eps_i, rows n..2n-1 = theta - sigma*eps_i."""
    return np.concatenate([theta[None, :] + sigma * eps, theta[None, :] - sigma * eps], axis=0)


def es_gradient(fitness: Arr, eps: Arr, sigma: float) -> Arr:
    """g = sum_pairs (r+ - r-) * eps / (N * sigma), ordered loop. fitness: (2n,) in the order of es_candidates."""
    n = eps.shape[0]
    r = centered_ranks(fitness)
    acc = np.zeros(eps.shape[1], dtype=np.float64)
    for i in range(n):
        acc = acc + (r[i] - r[n + i]) * eps[i]
    return acc / (2.0 * n * sigma)


def es_generation(net: dict, fitness_fn: Callable[[Arr], Arr], key: int, pop: int, cfg: dict, module: str) -> dict:
    """One generation; updates net (theta, adam_*, b1t, b2t) in place. fitness_fn: (N, npar) float64 -> (N,)."""
    theta, m, v = load_work(net)
    n = pop // 2
    eps = es_noise(key, n, theta.shape[0])
    cand = es_candidates(theta, eps, cfg["sigma"])
    fit = np.asarray(fitness_fn(cand), dtype=np.float64)
    if not bool(np.all(np.isfinite(fit))):
        raise NonFiniteError(module)
    g = es_gradient(fit, eps, cfg["sigma"]) - cfg["l2"] * theta
    theta, m, v = adam_step(net, theta, m, v, g, cfg["lr"], cfg["beta1"], cfg["beta2"], cfg["eps"], ascent=True)
    if not bool(np.all(np.isfinite(theta))):
        raise NonFiniteError(module)
    store_work(net, theta, m, v)
    return {"fit_mean": _fmean(fit), "fit_max": float(np.max(fit))}


def _fmean(a: Arr) -> float:
    return math.fsum(a.tolist()) / a.shape[0]


def es_key(seed: int, sol: int, module: int, gen: int) -> int:
    return derive(seed, "es", sol, module, gen)
