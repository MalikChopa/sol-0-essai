"""Exploration masks by chunk (EF-61); region serialisation (SPEC 6.8)."""
from __future__ import annotations

import struct

import numpy as np

from rover.core.exact import isum, isum_py

Arr = np.ndarray
CH = 64
RG = 16
MAGIC = b"SOL0EXP1"


class Explored:
    def __init__(self) -> None:
        self._m: dict[tuple[int, int], Arr] = {}       # (cx, cy) -> (64, 64) uint8 mask [y, x]
        self._last: dict[tuple[int, int], int] = {}    # (cx, cy) -> last sol with a newly marked cell

    def mark(self, xs: Arr, ys: Arr, sol: int) -> None:
        xs = np.asarray(xs, dtype=np.int64).ravel()
        ys = np.asarray(ys, dtype=np.int64).ravel()
        if xs.size == 0:
            return
        cx = np.floor_divide(xs, CH)
        cy = np.floor_divide(ys, CH)
        order = np.lexsort((cx, cy))
        cx, cy, xs, ys = cx[order], cy[order], xs[order], ys[order]
        keys = np.unique(np.stack([cy, cx], axis=1), axis=0)
        for ky, kx in keys.tolist():
            sel = (cx == kx) & (cy == ky)
            m = self._m.get((kx, ky))
            if m is None:
                m = np.zeros((CH, CH), dtype=np.uint8)
                self._m[(kx, ky)] = m
            lx = xs[sel] - kx * CH
            ly = ys[sel] - ky * CH
            if bool(np.any(m[ly, lx] == 0)):
                self._last[(kx, ky)] = int(sol)
            m[ly, lx] = 1

    def cells(self) -> int:
        return isum_py(int(isum(m)) for m in self._m.values())

    def window_mask(self, x0: int, y0: int, w: int, h: int) -> Arr:
        out = np.zeros((h, w), dtype=np.uint8)
        for cx in range(x0 // CH, (x0 + w - 1) // CH + 1):
            for cy in range(y0 // CH, (y0 + h - 1) // CH + 1):
                m = self._m.get((cx, cy))
                if m is None:
                    continue
                ax0, ay0 = max(x0, cx * CH), max(y0, cy * CH)
                ax1, ay1 = min(x0 + w, cx * CH + CH), min(y0 + h, cy * CH + CH)
                if ax1 > ax0 and ay1 > ay0:
                    out[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = m[ay0 - cy * CH:ay1 - cy * CH, ax0 - cx * CH:ax1 - cx * CH]
        return out

    def chunk_keys(self) -> list[tuple[int, int]]:
        return sorted(self._m.keys(), key=lambda k: (k[1], k[0]))

    def copy(self) -> "Explored":
        e = Explored()
        e._m = {k: v.copy() for k, v in self._m.items()}
        e._last = dict(self._last)
        return e

    def to_regions(self) -> dict[tuple[int, int], bytes]:
        groups: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for (cx, cy) in self.chunk_keys():
            groups.setdefault((cx // RG, cy // RG), []).append((cx, cy))     # floor division: signed regions
        out = {}
        for rk in sorted(groups):
            parts = [MAGIC, struct.pack("<I", len(groups[rk]))]
            for (cx, cy) in groups[rk]:
                parts.append(struct.pack("<iiI", cx, cy, self._last.get((cx, cy), 0)))
                parts.append(np.packbits(self._m[(cx, cy)].ravel(), bitorder="little").tobytes())
            out[rk] = b"".join(parts)
        return out

    @classmethod
    def from_regions(cls, regions: dict[tuple[int, int], bytes]) -> "Explored":
        from rover.state.schema import migrate_explored
        e = cls()
        for rk in sorted(regions):
            b = migrate_explored(regions[rk])
            assert b[:8] == MAGIC, "unknown explored region format"
            (n,) = struct.unpack_from("<I", b, 8)
            pos = 12
            for _ in range(n):
                cx, cy, last = struct.unpack_from("<iiI", b, pos)
                pos += 12
                bits = np.frombuffer(b[pos:pos + 512], dtype=np.uint8)
                pos += 512
                e._m[(cx, cy)] = np.unpackbits(bits, bitorder="little").reshape(CH, CH).copy()
                e._last[(cx, cy)] = last
        return e
