"""splitmix64 counter-mode PRNG with integer-only state (SPEC 1, ARCH 6). Declared exception of the determinism lint."""
from __future__ import annotations

import hashlib
import math
import zlib

import numpy as np

Arr = np.ndarray

_GOLDEN = 0x9E3779B97F4A7C15
_M1 = 0xBF58476D1CE4E5B9
_M2 = 0x94D049BB133111EB
_MASK = (1 << 64) - 1
_U = np.uint64
_SQRT3 = math.sqrt(3.0)


def derive(seed: int, domain: str, *ints) -> int:
    """Key (uint64 as Python int) from (seed, domain, ints). A str in `ints` goes through crc32 first."""
    vals = [seed]
    for v in ints:
        vals.append(zlib.crc32(v.encode("utf-8")) if isinstance(v, str) else int(v))
    payload = b"sol0|" + domain.encode("ascii") + b"|"
    for v in vals:
        assert -(1 << 63) <= v < (1 << 63), "derive: integer out of int64 range"
        payload += v.to_bytes(8, "little", signed=True)
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "little")


def _mix(z: Arr) -> Arr:
    z = (z ^ (z >> _U(30))) * _U(_M1)
    z = (z ^ (z >> _U(27))) * _U(_M2)
    return z ^ (z >> _U(31))


def u64(key, idx) -> Arr:
    """uint64 = mix(key + (idx + 1) * GOLDEN). key: int or uint64 array broadcast against idx."""
    with np.errstate(over="ignore"):
        i = np.asarray(idx).astype(np.uint64)
        k = np.asarray(key).astype(np.uint64) if not isinstance(key, int) else np.asarray(key & _MASK, dtype=np.uint64)
        return _mix(k + (i + _U(1)) * _U(_GOLDEN))


def uniform(key, idx) -> Arr:
    """float64 in [0, 1): (u64 >> 11) * 2^-53."""
    return (u64(key, idx) >> _U(11)).astype(np.float64) * 1.1102230246251565e-16


def gauss_ih4(key, idx) -> Arr:
    """Irwin-Hall with 4 uniforms, centred and scaled to unit variance; consumes 4*idx .. 4*idx+3."""
    base = np.asarray(idx).astype(np.uint64) * _U(4)
    s = uniform(key, base)
    for j in range(1, 4):
        s = s + uniform(key, base + _U(j))
    return (s - 2.0) * _SQRT3


def randint(key, idx, n: int) -> Arr:
    """Integer in [0, n)."""
    assert n > 0
    return (u64(key, idx) % _U(n)).astype(np.int64)
