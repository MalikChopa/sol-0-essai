"""Single definition of the flat MLP parameter vector (SPEC 4.1). FROZEN until J6.

Layout: [W1 (n_in x n_h, one row per input), b1 (n_h), W2 (n_h x n_out, one row per hidden unit), b2 (n_out)].
"""
from __future__ import annotations

import numpy as np

Arr = np.ndarray


def mlp_npar(n_in: int, n_h: int, n_out: int) -> int:
    return n_in * n_h + n_h + n_h * n_out + n_out


def unpack_mlp(theta: Arr, n_in: int, n_h: int, n_out: int) -> tuple[Arr, Arr, Arr, Arr]:
    """theta: (npar,) or (P, npar) -> W1 (..., n_in, n_h), b1 (..., n_h), W2 (..., n_h, n_out), b2 (..., n_out)."""
    theta = np.asarray(theta)
    assert theta.shape[-1] == mlp_npar(n_in, n_h, n_out), "theta size does not match the layout"
    lead = theta.shape[:-1]
    a = n_in * n_h
    b = a + n_h
    c = b + n_h * n_out
    w1 = theta[..., :a].reshape(lead + (n_in, n_h))
    b1 = theta[..., a:b]
    w2 = theta[..., b:c].reshape(lead + (n_h, n_out))
    b2 = theta[..., c:]
    return w1, b1, w2, b2
