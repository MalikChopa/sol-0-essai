"""Input vector of M0 (SPEC 3.4): 24 values, masked by stage."""
from __future__ import annotations

import math

import numpy as np

from rover.config import Params
from rover.core import consts, dmath
from rover.core.types import Sun

Arr = np.ndarray


def observe(rb, stage: int, target: Arr, sun: Sun, features: Arr, prev_u: Arr, params: Params) -> Arr:
    """(B, 24) float64. target: (B, 2) absolute cell position (or None). A masked input is exactly 0."""
    B = rb.x.shape[0]
    x = np.zeros((B, 24), dtype=np.float64)
    x[:, 0] = rb.enc_l
    x[:, 1] = rb.enc_r
    x[:, 2] = np.clip(2.0 * rb.pitch, -1.0, 1.0)
    x[:, 3] = np.clip(2.0 * rb.roll, -1.0, 1.0)
    x[:, 4] = rb.slip
    x[:, 5] = prev_u[:, 0]
    x[:, 6] = prev_u[:, 1]
    if features is not None:
        x[:, 7:15] = features
    if target is not None:
        dx = target[:, 0] - rb.x
        dy = target[:, 1] - rb.y
        d = np.maximum(np.sqrt(dx * dx + dy * dy), 1e-9)
        x[:, 15] = (dx * rb.c + dy * rb.s) / d
        x[:, 16] = (-dx * rb.s + dy * rb.c) / d
        x[:, 17] = np.minimum(1.0, d / 40.0)
    x[:, 18] = rb.battery
    x[:, 19] = float(sun.elev)
    ang = 2.0 * math.pi * float(sun.hour) / 24.0
    x[:, 20] = dmath.cos(ang)
    x[:, 21] = dmath.sin(ang)
    mask = np.zeros(24, dtype=np.float64)
    mask[list(consts.M0_ACTIVE[stage])] = 1.0
    return x * mask[None, :]
