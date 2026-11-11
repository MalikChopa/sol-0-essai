"""Fictitious data generators of the brain tests."""
from __future__ import annotations

import numpy as np

from rover.core.rng import gauss_ih4, uniform


def synthetic_couples(n: int, key: int = 7, noise: float = 0.05, per_sol: int = 6) -> np.ndarray:
    """(n, 10) fictitious command-effect pairs from a known law (forward = mean command x (1 - slip), heading = difference)."""
    i = np.arange(n)
    u = lambda j: uniform(key, i * 8 + j)
    uL, uR = 2 * u(0) - 1, 2 * u(1) - 1
    pitch, roll, slip = 0.3 * (2 * u(2) - 1), 0.3 * (2 * u(3) - 1), 0.3 * u(4)
    k = 1 - slip
    df = 5.0 * (uL + uR) / 2 * k * (1 - 1.5 * np.maximum(0, pitch))
    dl = 0.75 * roll * (uL + uR) / 2
    dh = 10.0 * (uR - uL) * k
    g = np.stack([gauss_ih4(key + 1, i * 3 + j) for j in range(3)], axis=1)
    y = np.stack([df, dl, dh], axis=1) + noise * g * np.asarray([1.0, 1.0, 3.0])
    return np.column_stack([uL, uR, pitch, roll, slip, y, i // per_sol + 1, np.zeros(n)])
