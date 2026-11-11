"""Photosensitivity check (EF-87, SPEC 7.3 / 11), applied to the frames of the GIF actually produced.

Relative luminance per pixel (WCAG, sRGB linearised with exact operations only); a "transition" between two consecutive
frames = >= 25 % of the image changes by >= 0.1 with the darker value < 0.8; at most 3 transitions in any 1 s window.
"""
from __future__ import annotations

import numpy as np

from rover.render.palette import PALETTE


def _root5(y: float) -> float:
    """Fifth root by bisection (multiplications and comparisons only: identical on every machine)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) * 0.5
        if mid * mid * mid * mid * mid < y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


def _lin(c8: int) -> float:
    c = c8 / 255.0
    if c <= 0.04045:
        return c / 12.92
    b = (c + 0.055) / 1.055
    b2 = b * b
    b4 = b2 * b2
    b12 = b4 * b4 * b4
    return _root5(b12)                       # b ** 2.4 = (b ** 12) ** (1 / 5)


def luminance_table(palette=PALETTE) -> np.ndarray:
    return np.asarray([0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b) for (r, g, b) in palette], dtype=np.float64)


_LUM = luminance_table()


def transitions(frames: list, durations_ms: list, lum: np.ndarray | None = None) -> tuple:
    """frames: palette-index images (same size). Returns (max transitions in any 1 s window, times (ms) of the transitions)."""
    lum = _LUM if lum is None else lum
    times, t = [], 0
    for k in range(1, len(frames)):
        t += int(durations_ms[k - 1])
        a, b = lum[frames[k - 1]], lum[frames[k]]
        changed = (np.abs(a - b) >= 0.1) & (np.minimum(a, b) < 0.8)
        if int(np.count_nonzero(changed)) * 4 >= changed.size:
            times.append(t)
    worst = 0
    for i, ti in enumerate(times):
        worst = max(worst, len([x for x in times if ti - 1000 < x <= ti]))
    return worst, times


def passes(frames: list, durations_ms: list, lum: np.ndarray | None = None) -> bool:
    return transitions(frames, durations_ms, lum)[0] <= 3
