"""Reference fingerprints of the core package (ARCH 6)."""
from __future__ import annotations

import numpy as np

from rover.core import dmath, exact, rng
from rover.core.hashing import sha256_hex
from rover.core.noise import fbm


def _h(*arrays) -> str:
    return "sha256:" + sha256_hex(b"".join(np.asarray(a).tobytes() for a in arrays))


def fingerprints(params) -> dict:
    k = rng.derive(20261111, "height")
    idx = np.arange(16)
    xs = np.arange(-40, 40, dtype=np.float64)
    gx, gy = np.meshgrid(xs, xs)
    ang = np.arange(-3000, 3000, 37) / 100.0     # integer arange then exact IEEE division: same values on every CPU (J8a measured float-step arange differing Mac/x86-64)
    return {
        "core.derive": _h(np.asarray([k, rng.derive(1, "slip", 2, 3), rng.derive(1, "journal", 4, "summary.s0")], dtype=np.uint64)),
        "core.u64_16": _h(rng.u64(k, idx)),
        "core.uniform_16": _h(rng.uniform(k, idx)),
        "core.gauss_16": _h(rng.gauss_ih4(k, idx)),
        "core.fbm": _h(fbm(k, gx, gy, 5, 64.0)),
        "core.randint": _h(rng.randint(k, np.arange(64), 40)),
        "core.dot_fixed": _h(exact.dot_fixed(np.arange(24, dtype=np.float64).reshape(2, 12) * 0.37 - 3.0, np.arange(72, dtype=np.float64).reshape(12, 6) * 0.11 - 4.0)),
        "core.dmath": _h(dmath.sin(ang), dmath.cos(ang), dmath.atan(ang)),
    }
