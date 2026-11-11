"""Reference fingerprints of the render package (ARCH 6): font, palette, luminance table, vignette steps, one console frame."""
from __future__ import annotations

import numpy as np

from rover.core.consts import M0_ACTIVE
from rover.core.hashing import sha256_hex
from rover.core.types import BrainSnapshot, FrameRecord, SolEvents, Trace
from rover.render import font, photosens
from rover.render.console import render_frame
from rover.render.brain_view import BrainView
from rover.render.palette import PALETTE
from rover.render.vignettes import radial_steps
from rover.state.explored import Explored


def _h(*arrays) -> str:
    return "sha256:" + sha256_hex(b"".join(np.asarray(a).tobytes() for a in arrays))


def _tiny_trace() -> Trace:
    """Deterministic synthetic trace built from integer formulas only (no PRNG)."""
    frames = []
    for k in range(6):
        idx = np.zeros((20, 32), dtype=np.uint8)
        idx[:] = (np.indices((20, 32))[0] * 3 + np.indices((20, 32))[1] + k) % 18
        x = np.zeros(24)
        for i in M0_ACTIVE[2]:
            x[i] = ((i * 37 + k * 11) % 200) / 100.0 - 1.0
        frames.append(FrameRecord(
            tick=8 * k, hour=5.0 + 0.16 * k, mode="DRIVE", cam_index=idx, cam_depth=np.zeros((20, 32), dtype=np.uint8), D=40,
            z=np.asarray([((i * 13 + k) % 100) / 100.0 for i in range(40)]), f=x[7:15].copy(), x=x,
            h=np.asarray([((j * 29 + k * 7) % 200) / 100.0 - 1.0 for j in range(16)]), y=np.asarray([0.3, -0.2]),
            u=np.asarray([0.35, -0.1]), xi=np.asarray([0.05, 0.0]), m1_pred=np.asarray([0.1, 0.0, -0.1]),
            m1_meas=np.asarray([0.2, 0.1, 0.0]), m3_out=None, speed=0.1, battery=0.8, pitch=0.01, roll=-0.02, slip=0.1,
            solar=0.0, sun_elev=0.5, sun_dx=0.6, sun_dy=-0.8, pose=(float(k), 0.5 * k, 0.8, 0.6), target=(10.0, 5.0),
            stuck=False, tipped=False, asleep=False))
    theta = np.asarray([((i * 17) % 100) / 200.0 - 0.25 for i in range(434)], dtype=np.float32)
    snap = BrainSnapshot(stage=2, m0=theta, m1=None, m2_w=None, m2_mean=None, m2_var=None, m3=None)
    ev = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
    return Trace(sol=7, stage=2, acuity=(32, 20), frames=frames, snapshot=snap, events=ev,
                 seen=np.asarray([[0, 0, 0], [3, 2, 16], [5, 1, 40]], dtype=np.int64))


def fingerprints(params) -> dict:
    from rover.core.types import Progress
    tr = _tiny_trace()
    bv = BrainView(tr, params)
    prog = Progress(0.5, "Learning to drive", "x", "metric")
    img, _ = render_frame(tr, 3, {"stage": {"id": 2}}, prog, "2026-11-11T07:17:00Z", True, bv, Explored(),
                          lambda xs, ys: (xs // 8 + ys // 8) % 4, params)
    return {
        "render.font": _h(np.stack([font.GLYPHS[chr(c)] for c in range(32, 127)])),
        "render.palette": _h(np.asarray(PALETTE, dtype=np.uint8)),
        "render.luminance": _h(photosens.luminance_table()),
        "render.vignette": _h(radial_steps(360, 640, (500, 900))),
        "render.frame": _h(img),
    }
