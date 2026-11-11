"""Shared MLP forward pass (SPEC 4.1) and M2 stage-1 descriptors (SPEC 4.4)."""
from __future__ import annotations

import numpy as np

from rover.core.consts import CAM_LUT
from rover.core.exact import dot_fixed, fsum, isum, safe_std, softsign, sum_axis
from rover.core.mlp_layout import unpack_mlp

Arr = np.ndarray
_LUT = np.asarray(CAM_LUT, dtype=np.int64)
Z_CLIP = 5.0        # J2 safeguard (SPEC silent): a standardised descriptor never exceeds 5 sigma (running variance can be ~0)


def mlp_forward(theta: Arr, x: Arr, n_in: int, n_h: int, n_out: int, linear_out: bool = False) -> tuple[Arr, Arr]:
    W1, b1, W2, b2 = unpack_mlp(theta, n_in, n_h, n_out)
    h = softsign(dot_fixed(x, W1) + b1)
    y = dot_fixed(h, W2) + b2
    if not linear_out:
        y = softsign(y)
    return y, h


def m2_descriptors(index: Arr, depth: Arr, D: int) -> Arr:
    """(B, 40): per sector (8 column sectors) [lum_top, depth_top, lum_low, depth_low, min_depth_low], all in [0, 1]."""
    index = np.asarray(index)
    B, H, W = index.shape
    hb, wb = H // 2, W // 8
    lum = np.take(_LUT, index)
    dep = np.asarray(depth, dtype=np.int64)
    cnt = float(hb * wb)
    ls = isum(isum(lum.reshape(B, 2, hb, 8, wb), 4), 2)               # (B, 2, 8)
    ds = isum(isum(dep.reshape(B, 2, hb, 8, wb), 4), 2)
    mind = dep.reshape(B, 2, hb, 8, wb)[:, 1].min(axis=3).min(axis=1)  # (B, 8)
    out = np.zeros((B, 8, 5), dtype=np.float64)
    out[:, :, 0] = ls[:, 0, :] / (cnt * 255.0)
    out[:, :, 1] = ds[:, 0, :] / (cnt * D)
    out[:, :, 2] = ls[:, 1, :] / (cnt * 255.0)
    out[:, :, 3] = ds[:, 1, :] / (cnt * D)
    out[:, :, 4] = mind / float(D)
    return out.reshape(B, 40)


def visual_features(z: Arr, mean: Arr, var: Arr, w: Arr) -> Arr:
    """M2 stage 2 (SPEC 4.4): f = softsign(W z_std), W (8, 40). z (B, 40) -> (B, 8)."""
    zs = np.clip((z - mean) / safe_std(var), -Z_CLIP, Z_CLIP)
    return softsign(dot_fixed(zs, np.transpose(np.asarray(w, dtype=np.float64))))


def mlp_mse_grad(theta: Arr, x: Arr, t: Arr, n_in: int, n_h: int, n_out: int) -> tuple[Arr, float]:
    """Gradient of the mean squared error (mean over batch and outputs) of a linear-output MLP.

    Returns (flat gradient in core.mlp_layout order, loss). Exact operations only (dot_fixed, ordered sums)."""
    W1, b1, W2, b2 = unpack_mlp(np.asarray(theta, dtype=np.float64), n_in, n_h, n_out)
    n = x.shape[0]
    a1 = dot_fixed(x, W1) + b1
    h = softsign(a1)
    y = dot_fixed(h, W2) + b2
    err = y - t
    loss = fsum(err * err) / (n * n_out)
    dy = 2.0 * err / (n * n_out)
    gW2 = dot_fixed(np.transpose(h), dy)
    gb2 = sum_axis(dy, 0)
    dh = dot_fixed(dy, np.transpose(W2))
    da = dh / ((1.0 + np.abs(a1)) * (1.0 + np.abs(a1)))
    gW1 = dot_fixed(np.transpose(x), da)
    gb1 = sum_axis(da, 0)
    return np.concatenate([gW1.ravel(), gb1, gW2.ravel(), gb2]), loss
