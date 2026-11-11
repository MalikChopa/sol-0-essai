"""sin / cos / atan from exact operations only (argument reduction + Horner, fixed order). Declared lint exception."""
from __future__ import annotations

import math

import numpy as np

Arr = np.ndarray

_PI = math.pi
_TWO_PI = 2.0 * math.pi
_HALF_PI = 0.5 * math.pi
# sin(y) = y * (1 - y^2/3! + y^4/5! - ...) on [-pi/2, pi/2], terms up to y^17
_SIN_C = (1.0, -1.0 / 6.0, 1.0 / 120.0, -1.0 / 5040.0, 1.0 / 362880.0, -1.0 / 39916800.0,
          1.0 / 6227020800.0, -1.0 / 1307674368000.0, 1.0 / 355687428096000.0)
_ATAN_C = (1.0, -1.0 / 3.0, 1.0 / 5.0, -1.0 / 7.0, 1.0 / 9.0, -1.0 / 11.0, 1.0 / 13.0)


def _ret(r, scalar):
    return float(r) if scalar else r


def _horner(t, coefs):
    acc = np.full_like(t, coefs[-1])
    for c in coefs[-2::-1]:
        acc = acc * t + c
    return acc


def sin(x):
    scalar = not isinstance(x, np.ndarray)
    a = np.asarray(x, dtype=np.float64)
    y = a - _TWO_PI * np.floor(a / _TWO_PI + 0.5)            # [-pi, pi]
    y = np.where(y > _HALF_PI, _PI - y, y)
    y = np.where(y < -_HALF_PI, -_PI - y, y)                  # [-pi/2, pi/2]
    return _ret(y * _horner(y * y, _SIN_C), scalar)


def cos(x):
    scalar = not isinstance(x, np.ndarray)
    return _ret(sin(np.asarray(x, dtype=np.float64) + _HALF_PI), scalar)


def atan(x):
    scalar = not isinstance(x, np.ndarray)
    a = np.asarray(x, dtype=np.float64)
    ax = np.abs(a)
    big = ax > 1.0
    t = np.where(big, 1.0 / np.maximum(ax, 1e-300), ax)        # t in [0, 1]
    t = t / (1.0 + np.sqrt(1.0 + t * t))                        # atan(t) = 2 atan(t / (1 + sqrt(1 + t^2)))
    t = t / (1.0 + np.sqrt(1.0 + t * t))
    r = 4.0 * t * _horner(t * t, _ATAN_C)
    r = np.where(big, _HALF_PI - r, r)
    return _ret(np.where(a < 0.0, -r, r), scalar)


def rot(c: Arr, s: Arr, w: Arr):
    """Rotate the unit vector (c, s) by w radians and renormalise."""
    cw = cos(w)
    sw = sin(w)
    c2 = c * cw - s * sw
    s2 = s * cw + c * sw
    n = np.sqrt(c2 * c2 + s2 * s2)
    return c2 / n, s2 / n
