"""Value-noise fBm in world coordinates (SPEC 2): integer hash, quintic fade, octaves summed in order."""
from __future__ import annotations

import numpy as np

from rover.core.exact import to_int
from rover.core.rng import u64, uniform

Arr = np.ndarray
_C1 = np.uint64(0x9E3779B185EBCA87)
_C2 = np.uint64(0xC2B2AE3D27D4EB4F)


def _lattice(key: int, ix: Arr, iy: Arr) -> Arr:
    idx = to_int(ix, np.uint64) * _C1 + to_int(iy, np.uint64) * _C2     # uint64 arrays wrap silently
    return uniform(key, idx)


def fbm(key: int, x: Arr, y: Arr, octaves: int, wavelength: float, gain: float = 0.5) -> Arr:
    """Noise in [0, 1]; x, y world coordinates (cells), any broadcastable shapes."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    total = np.zeros_like(x + y)
    norm = 0.0
    amp = 1.0
    wl = float(wavelength)
    for o in range(octaves):
        ko = int(u64(key, np.asarray(o))[()])
        gx = x / wl
        gy = y / wl
        fx0 = np.floor(gx)
        fy0 = np.floor(gy)
        tx = gx - fx0
        ty = gy - fy0
        ix = to_int(fx0)
        iy = to_int(fy0)
        sx = tx * tx * tx * (tx * (tx * 6.0 - 15.0) + 10.0)
        sy = ty * ty * ty * (ty * (ty * 6.0 - 15.0) + 10.0)
        v00 = _lattice(ko, ix, iy)
        v10 = _lattice(ko, ix + 1, iy)
        v01 = _lattice(ko, ix, iy + 1)
        v11 = _lattice(ko, ix + 1, iy + 1)
        a = v00 + (v10 - v00) * sx
        b = v01 + (v11 - v01) * sx
        total = total + amp * (a + (b - a) * sy)
        norm = norm + amp
        amp = amp * gain
        wl = max(wl * 0.5, 1.0)
    return total / norm
