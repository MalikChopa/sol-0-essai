"""Vignette (SPEC 7.4): only background pixels (index BG) outside the CAM-1 rectangle are darkened; never data."""
from __future__ import annotations

import numpy as np

from rover.core.exact import to_int

from rover.render.palette import BG, BG_SCAN, BG_VIG


def radial_steps(h: int, w: int, thresholds: tuple) -> np.ndarray:
    """Integer step map: number of thresholds (per mille of the squared normalised elliptical distance) reached."""
    ys, xs = np.indices((h, w))
    dx, dy = xs * 2 - (w - 1), ys * 2 - (h - 1)
    rr = (dx * dx * 1000) // (w * w) + (dy * dy * 1000) // (h * h)
    steps = np.zeros((h, w), dtype=np.int64)
    for t in thresholds:
        steps = steps + (rr >= t)
    return steps


_STEPS = {}


def apply_vignette(img: np.ndarray, cam_rect: tuple) -> None:
    """2 steps on the background: BG -> BG_SCAN (index 49) then BG_VIG (index 50)."""
    h, w = img.shape
    if (h, w) not in _STEPS:
        _STEPS[(h, w)] = radial_steps(h, w, (500, 900))
    st = _STEPS[(h, w)]
    target = to_int(np.where(st >= 2, BG_VIG, np.where(st == 1, BG_SCAN, BG)), np.uint8)
    mask = img == BG
    x, y, cw, ch = cam_rect
    mask[y:y + ch, x:x + cw] = False
    img[mask] = target[mask]
