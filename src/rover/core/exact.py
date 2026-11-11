"""Exact (platform independent) numeric primitives (ARCH 6). Declared exception of the determinism lint."""
from __future__ import annotations

import math

import numpy as np

Arr = np.ndarray


def dot_fixed(x: Arr, W: Arr) -> Arr:
    """x (..., n_in), W (..., n_in, n_out) -> (..., n_out); loop over n_in in a fixed order."""
    x = np.asarray(x, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)
    acc = x[..., 0:1] * W[..., 0, :]
    for i in range(1, x.shape[-1]):
        acc = acc + x[..., i:i + 1] * W[..., i, :]
    return acc


def sum_axis(a: Arr, axis: int) -> Arr:
    """Float sum in fixed sequential order along axis."""
    a = np.moveaxis(np.asarray(a, dtype=np.float64), axis, 0)
    acc = a[0]
    for i in range(1, a.shape[0]):
        acc = acc + a[i]
    return acc


def fsum(a: Arr) -> float:
    return math.fsum(np.asarray(a, dtype=np.float64).ravel().tolist())


def isum(a: Arr, axis: int | None = None) -> Arr:
    a = np.asarray(a)
    assert a.dtype.kind in "iub", "isum: integers only"
    return a.astype(np.int64).sum(axis=axis)


def icumsum(a: Arr, axis: int) -> Arr:
    a = np.asarray(a)
    assert a.dtype.kind in "iub", "icumsum: integers only"
    return a.astype(np.int64).cumsum(axis=axis)


def to_int(a, dtype=np.int64):
    """The only float -> integer conversion allowed (truncates toward zero). Floats: finite and |a| < 2**53."""
    scalar = not isinstance(a, np.ndarray)
    arr = np.asarray(a)
    if arr.dtype.kind == "f":
        assert bool(np.all(np.isfinite(arr))), "to_int: non finite value"
        assert bool(np.all(np.abs(arr) < 9007199254740992.0)), "to_int: value too large"
    out = arr.astype(dtype)
    return int(out) if scalar else out


def softsign(x: Arr) -> Arr:
    x = np.asarray(x, dtype=np.float64)
    return x / (1.0 + np.abs(x))


def safe_std(var):
    """max(sqrt(var), 1e-6): the only division by a standard deviation allowed."""
    if isinstance(var, (int, float)):
        return max(math.sqrt(var), 1e-6)
    return np.maximum(np.sqrt(np.asarray(var, dtype=np.float64)), 1e-6)


def centered_ranks(f: Arr) -> Arr:
    """Ranks centred in [-0.5, 0.5]; stable argsort, ties broken by index."""
    f = np.asarray(f, dtype=np.float64)
    n = f.shape[0]
    order = np.argsort(f, kind="stable")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(n, dtype=np.float64)
    if n == 1:
        return np.zeros(1)
    return ranks / (n - 1.0) - 0.5


def isum_py(xs) -> int:
    """Exact sum of a sequence of Python integers."""
    return int(isum(np.asarray(list(xs), dtype=np.int64)))
