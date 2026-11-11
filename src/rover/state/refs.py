"""Reference fingerprints of the state package."""
from __future__ import annotations

import numpy as np

from rover.core.hashing import sha256_hex
from rover.state.explored import Explored
from rover.state.schema import new_state


def fingerprints(params) -> dict:
    e = Explored()
    xs = np.asarray([0, 1, 5, -1, 70, -70, 1100, 3])
    ys = np.asarray([0, 0, 9, -1, 3, 80, -900, 3])
    e.mark(xs, ys, 4)
    regions = e.to_regions()
    blob = b"".join(regions[k] for k in sorted(regions))
    back = Explored.from_regions(regions)
    mask_ok = bool(np.all(back.window_mask(-80, -80, 160, 160) == e.window_mask(-80, -80, 160, 160)))
    s = new_state(params)
    s.pop("memory"), s.pop("trail")
    from rover.core.hashing import canonical_json
    v0 = new_state(params)                       # fake schema 0 (no origin, no pending_tags) -> 1: the mechanism, ARCH 5
    v0["schema_version"] = 0
    del v0["origin"], v0["pending_tags"]
    v0.pop("memory"), v0.pop("trail")
    from rover.state.migrations import migrate_0_to_1
    return {"state.migration_0_to_1": "sha256:" + sha256_hex(canonical_json(migrate_0_to_1(v0))),
            "state.explored_regions": "sha256:" + sha256_hex(blob),
            "state.explored_roundtrip": "sha256:" + sha256_hex(b"1" if mask_ok and back.cells() == e.cells() else b"0"),
            "state.new_state": "sha256:" + sha256_hex(canonical_json(s))}
