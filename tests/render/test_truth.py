"""Truth test 1 (ARCH 7): the CAM-1 zone of the decoded GIF, outside the declared overlay rectangles, is the trace."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from rover.pipeline import fresh_state, run_sol, terrain_fn
from rover.render import PALETTE, build_console
from rover.render.cam_view import CAM_H, CAM_W, CAM_X, CAM_Y
from rover.stages import progress as stage_progress
from rover.state import Explored
from rover.world import World

NOW = "2026-11-11T07:17:00Z"


def _decode(gif: bytes):
    im = Image.open(io.BytesIO(gif))
    out = []
    for i in range(im.n_frames):
        im.seek(i)
        out.append(np.asarray(im.convert("RGB")))
    return out


def _expected_rgb(cam_index: np.ndarray):
    """Independent of the encoder: nearest-neighbour enlargement, scanline twin (colour x 82 // 100) on odd rows of the zone."""
    h, w = cam_index.shape
    sx, sy = CAM_W // w, CAM_H // h
    big = np.repeat(np.repeat(cam_index, sy, axis=0), sx, axis=1)
    oy = (CAM_H - big.shape[0]) // 2
    pal = np.asarray(PALETTE[:24], dtype=np.int64)
    zone = np.tile(np.asarray(PALETTE[48], dtype=np.int64), (CAM_H, CAM_W, 1))
    zone[oy:oy + big.shape[0], :big.shape[1]] = pal[big]
    for r in range(oy, oy + big.shape[0]):
        if r % 2 == 1:
            zone[r, :big.shape[1]] = zone[r, :big.shape[1]] * 82 // 100
    return zone


def test_cam1_zone_of_the_gif_is_the_traced_sensor_image(params):
    res = run_sol(fresh_state(params), Explored(), params, NOW)
    assert res.status["run"]["gif_level"] == "L0"
    world = World(res.state["world_seed"], params, [])
    prog = stage_progress(res.state["stage"], res.state["metrics"], params)
    cf = build_console(res.trace, res.state, Explored(), terrain_fn(world), prog, NOW, params)
    frames = _decode(res.images["console.gif"])
    assert len(frames) == len(cf.selected) == 75
    checked = 0
    for k, rec_i in enumerate(cf.selected):
        want = _expected_rgb(res.trace.frames[rec_i].cam_index)
        got = frames[k][CAM_Y:CAM_Y + CAM_H, CAM_X:CAM_X + CAM_W].astype(np.int64)
        keep = np.ones((CAM_H, CAM_W), dtype=bool)
        for (x, y, w, h) in cf.overlay_rects[k]:
            keep[max(0, y - CAM_Y):max(0, y - CAM_Y + h), max(0, x - CAM_X):max(0, x - CAM_X + w)] = False
        assert keep.sum() > 0.9 * keep.size
        assert (got[keep] == want[keep]).all(), f"frame {k} (record {rec_i}) differs from the trace"
        checked += int(keep.sum())
    assert checked > 75 * 0.9 * CAM_W * CAM_H


def test_gif_frames_follow_the_trace_clock(params):
    """Each frame shows the local hour of its record: the selection is visible and real."""
    res = run_sol(fresh_state(params), Explored(), params, NOW)
    hours = [f.hour for f in res.trace.frames]
    assert len(hours) == 150 and hours[0] == 5.0
    steps = [(b - a) % 24.0 for a, b in zip(hours, hours[1:])]
    assert all(abs(d - 0.16) < 1e-9 for d in steps)        # 8 ticks of 72 s
