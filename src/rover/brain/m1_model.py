"""M1, the predictive model (SPEC 4.3): (uL, uR, pitch, roll, slip) -> (d_forward, d_lateral, d_heading) of a segment."""
from __future__ import annotations

import numpy as np

from rover.brain.adam import adam_step, load_work, store_work
from rover.brain.mlp import mlp_forward, mlp_mse_grad
from rover.core import consts
from rover.core.exact import fsum, safe_std
from rover.core.rng import derive, randint
from rover.core.types import NonFiniteError

Arr = np.ndarray


def _col_stats(a: Arr) -> tuple[Arr, Arr]:
    n = a.shape[0]
    mean = np.asarray([fsum(a[:, j]) / n for j in range(a.shape[1])])
    var = np.asarray([fsum((a[:, j] - mean[j]) ** 2) / n for j in range(a.shape[1])])
    return mean, var


def r2_score(y: Arr, p: Arr) -> float:
    """Mean R2 of the outputs: 1 - sum (y - p)^2 / sum (y - ybar)^2 (fsum); an output whose total variance < 1e-12 counts 0.0."""
    out = []
    for j in range(y.shape[1]):
        yb = fsum(y[:, j]) / y.shape[0]
        tot = fsum((y[:, j] - yb) ** 2)
        if tot < 1e-12:
            out.append(0.0)
        else:
            out.append(1.0 - fsum((y[:, j] - p[:, j]) ** 2) / tot)
    return fsum(np.asarray(out)) / len(out)


def predict(m1: dict, inp: Arr, n_h: int) -> Arr:
    """Raw (unstandardised) prediction of the 3 outputs for inputs (B, 5)."""
    xin = (inp - m1["x_mean"]) / np.maximum(m1["x_std"], 1e-6)
    yo, _ = mlp_forward(m1["theta"], xin, 5, n_h, 3, linear_out=True)
    return yo * m1["y_std"] + m1["y_mean"]


def train_m1(m1: dict, rows: Arr, seed: int, sol: int, steps: int, params) -> dict:
    """Standardise on the training rows, run `steps` Adam steps on minibatches, score on the held-out sols.

    rows (n, 10): u_L u_R pitch roll slip | d_fwd d_lat d_head | sol | gtype. Held out: sol mod holdout_mod == 0.
    Returns {"r2", "steps", "n_train", "n_holdout", "worst_terrain"}."""
    P = params.get("brain.m1")
    n_h = int(P["hidden"])
    rows = np.asarray(rows, dtype=np.float64)
    hold = (np.remainder(rows[:, 8], float(P["holdout_mod"])) == 0.0)
    tr, ho = rows[~hold], rows[hold]
    rep = {"r2": 0.0, "steps": 0, "n_train": int(tr.shape[0]), "n_holdout": int(ho.shape[0]), "worst_terrain": None}
    if tr.shape[0] < 4:
        return rep
    xm, xv = _col_stats(tr[:, 0:5])
    ym, yv = _col_stats(tr[:, 5:8])
    xs_, ys_ = safe_std(xv), safe_std(yv)
    m1["x_mean"], m1["x_std"] = xm.astype(np.float32), xs_.astype(np.float32)
    m1["y_mean"], m1["y_std"] = ym.astype(np.float32), ys_.astype(np.float32)
    X = (tr[:, 0:5] - xm) / xs_
    Y = (tr[:, 5:8] - ym) / ys_
    theta, mm, vv = load_work(m1)
    key = derive(seed, "m1", sol)
    bs = int(P["batch"])
    E = params.get("brain.es")
    for s in range(steps):
        idx = randint(key, np.arange(s * bs, (s + 1) * bs), tr.shape[0])
        g, _ = mlp_mse_grad(theta, X[idx], Y[idx], 5, n_h, 3)
        theta, mm, vv = adam_step(m1, theta, mm, vv, g, float(P["lr"]), E["beta1"], E["beta2"], E["eps"])
    if not bool(np.all(np.isfinite(theta))):
        raise NonFiniteError("m1")
    store_work(m1, theta, mm, vv)
    rep["steps"] = steps
    if ho.shape[0] >= 2:
        Xh = (ho[:, 0:5] - xm) / xs_
        Yh = (ho[:, 5:8] - ym) / ys_
        pred, _ = mlp_forward(theta, Xh, 5, n_h, 3, linear_out=True)
        rep["r2"] = r2_score(Yh, pred)
        worst, best = None, -1.0
        for g_id in range(4):
            sel = ho[:, 9] == float(g_id)
            if bool(np.any(sel)):
                e = fsum((Yh[sel] - pred[sel]) ** 2) / (int(np.count_nonzero(sel)) * 3)
                if e > best:
                    best, worst = e, consts.GTYPE_NAMES[g_id]
        rep["worst_terrain"] = worst
    return rep
