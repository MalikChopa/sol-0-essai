"""`rover refs`: all package fingerprints plus the end-to-end ones (state, images, journal of one sol)."""
from __future__ import annotations

import gzip
import io

import numpy as np
from PIL import Image

from rover.agent import refs as agent_refs
from rover.brain import refs as brain_refs
from rover.core import refs as core_refs
from rover.core.hashing import canonical_json, sha256_hex
from rover.narrative import refs as narrative_refs
from rover.pipeline.sol import fresh_state, run_sol
from rover.render import refs as render_refs
from rover.state import Explored, core_bytes, core_for_compare
from rover.state import refs as state_refs
from rover.world import refs as world_refs

PACKAGES = (("core", core_refs), ("world", world_refs), ("agent", agent_refs), ("brain", brain_refs), ("state", state_refs),
            ("render", render_refs), ("narrative", narrative_refs))      # J6 (F-07): the rendering and the text also cross Mac <-> runner


def _decoded(data: bytes) -> bytes:
    im = Image.open(io.BytesIO(data))
    out = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        out.append(np.asarray(im.convert("RGB")).tobytes())
    return b"".join(out)


def fingerprints(params) -> dict:
    out = {}
    for _, mod in PACKAGES:
        out.update(mod.fingerprints(params))
    s = fresh_state(params)
    res = run_sol(s, Explored(), params, "2026-11-11T07:17:00Z")
    out["pipeline.sol1_core"] = "sha256:" + sha256_hex(core_bytes(core_for_compare(res.state)))
    out["pipeline.sol1_det"] = "sha256:" + sha256_hex(canonical_json(res.status["det"]))
    out["pipeline.sol1_journal"] = "sha256:" + sha256_hex(canonical_json(res.state["journal_tail"]))
    out["pipeline.sol1_svg"] = "sha256:" + sha256_hex(res.images["status.svg"])
    out["pipeline.sol1_gif_pixels"] = "sha256:" + sha256_hex(_decoded(res.images["console.gif"]))
    out["pipeline.sol1_map_pixels"] = "sha256:" + sha256_hex(_decoded(res.images["map.png"]))
    return out
