"""Adam on a network dict {theta, adam_m, adam_v, b1t, b2t} (SPEC 4.1: beta^t kept in the state, no exponent)."""
from __future__ import annotations

import numpy as np

Arr = np.ndarray


def adam_step(net: dict, theta: Arr, m: Arr, v: Arr, g: Arr, lr: float, beta1: float, beta2: float, eps: float,
              ascent: bool = False) -> tuple[Arr, Arr, Arr]:
    """One float64 Adam step. Updates net["b1t"], net["b2t"] (beta^t). Returns (theta, m, v)."""
    net["b1t"] = float(net["b1t"]) * beta1
    net["b2t"] = float(net["b2t"]) * beta2
    m = beta1 * m + (1.0 - beta1) * g
    v = beta2 * v + (1.0 - beta2) * g * g
    mh = m / (1.0 - net["b1t"])
    vh = v / (1.0 - net["b2t"])
    step = lr * mh / (np.sqrt(vh) + eps)
    return (theta + step if ascent else theta - step), m, v


def load_work(net: dict) -> tuple[Arr, Arr, Arr]:
    return (np.asarray(net["theta"], dtype=np.float64), np.asarray(net["adam_m"], dtype=np.float64),
            np.asarray(net["adam_v"], dtype=np.float64))


def store_work(net: dict, theta: Arr, m: Arr, v: Arr) -> None:
    net["theta"] = theta.astype(np.float32)
    net["adam_m"] = m.astype(np.float32)
    net["adam_v"] = v.astype(np.float32)
