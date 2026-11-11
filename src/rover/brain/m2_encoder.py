"""M2, the visual encoder (SPEC 4.4): stage 1 = fixed descriptors z (mlp.m2_descriptors), stage 2 = learned W (8 x 40)
by Sanger's rule on the images of the sol. Frozen during the episode and the rollouts; learns after the episode."""
from __future__ import annotations

import numpy as np

from rover.brain.mlp import Z_CLIP
from rover.core.exact import dot_fixed, fsum, safe_std

Arr = np.ndarray


def update_standardisation(m2: dict, z: Arr) -> None:
    """Running mean and variance, once per sol: weight max(1/(n_sols+1), 0.05); the first sol sets them."""
    n = z.shape[0]
    mean = np.asarray([fsum(z[:, j]) / n for j in range(z.shape[1])])
    var = np.asarray([fsum((z[:, j] - mean[j]) ** 2) / n for j in range(z.shape[1])])
    w = max(1.0 / (int(m2["n_sols"]) + 1.0), 0.05)
    m2["mean"] = ((1.0 - w) * np.asarray(m2["mean"], dtype=np.float64) + w * mean).astype(np.float32)
    m2["var"] = ((1.0 - w) * np.asarray(m2["var"], dtype=np.float64) + w * var).astype(np.float32)


def sanger(W: Arr, zs: Arr, eta: float) -> Arr:
    """Sequential Sanger updates dW = eta * (f z^T - LT[f f^T] W), one image at a time (fixed order)."""
    W = np.asarray(W, dtype=np.float64).copy()
    k = W.shape[0]
    tri = np.asarray([[1.0 if j <= i else 0.0 for j in range(k)] for i in range(k)])
    for t in range(zs.shape[0]):
        z = zs[t:t + 1]                                                    # (1, 40)
        big = fsum(z * z) / 40.0
        e = eta / big if big > 1.0 else eta                                # J2 safeguard: step normalised for outliers
        f = dot_fixed(z, np.transpose(W))                                  # (1, k)
        ff = np.transpose(f) * f * tri                                     # (k, k) lower triangle of f f^T
        W = W + e * (np.transpose(f) * z - dot_fixed(ff, W))
    return W


def explained_variance(W: Arr, zs: Arr) -> float:
    """Share of the variance of the (centred) images explained by the span of the 8 components (Gram-Schmidt in a
    fixed order, then projection); 0.0 if the total variance is < 1e-12."""
    W = np.asarray(W, dtype=np.float64)
    n = zs.shape[0]
    zc = zs - np.asarray([fsum(zs[:, j]) / n for j in range(zs.shape[1])])
    tot = fsum(zc * zc)
    if tot < 1e-12:
        return 0.0
    q = []
    for i in range(W.shape[0]):
        v = W[i].copy()
        for p in q:
            v = v - fsum(v * p) * p
        nv = float(np.sqrt(fsum(v * v)))
        if nv > 1e-12:
            q.append(v / nv)
    if not q:
        return 0.0
    Q = np.stack(q, axis=0)
    proj = dot_fixed(zc, np.transpose(Q))
    return min(1.0, fsum(proj * proj) / tot)


def train_m2(m2: dict, z: Arr, params) -> dict:
    """One sol of learning from the sol's descriptors z (n, 40). Returns {"explained": float}."""
    P = params.get("brain.m2")
    if z.shape[0] < 2:
        return {"explained": 0.0}
    update_standardisation(m2, z)
    zs = np.clip((z - np.asarray(m2["mean"], dtype=np.float64)) / safe_std(np.asarray(m2["var"], dtype=np.float64)),
                 -Z_CLIP, Z_CLIP)
    eta = float(P["eta"]) / (1.0 + float(m2["n_sols"]) / float(P["eta_decay_sols"]))
    W = sanger(m2["w"], zs, eta)
    m2["w"] = W.astype(np.float32)
    m2["n_sols"] = int(m2["n_sols"]) + 1
    return {"explained": explained_variance(W, zs)}
