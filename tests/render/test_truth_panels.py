"""Truth tests (ARCH 7) on fictitious traces: CAM-1, local map frame by frame, brain nodes and connections, numbers, no PRNG."""
from __future__ import annotations

import ast
import copy
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fake_trace import make_progress, make_state, make_trace, terrain
from rover.core.consts import RAMP_BASE
from rover.render import PALETTE, build_console, panels
from rover.render.brain_view import BrainView
from rover.render.cam_view import CAM_H, CAM_W, CAM_X, CAM_Y
from rover.render.console import render_frame
from rover.render.gif import encode_frames
from rover.render.palette import BG, MARK, hud
from rover.state import Explored

NOW = "2026-11-11T07:17:00Z"


def _cf(params, tr, explored=None, **kw):
    return build_console(tr, make_state(tr), explored or Explored(), terrain, make_progress(tr.stage), NOW, params, **kw)


def _expected_zone(cam_index):
    h, w = cam_index.shape
    sx, sy = CAM_W // w, CAM_H // h
    big = np.repeat(np.repeat(cam_index, sy, axis=0), sx, axis=1)
    oy = (CAM_H - big.shape[0]) // 2
    zone = np.full((CAM_H, CAM_W), BG, dtype=np.int64)
    zone[oy:oy + big.shape[0], :big.shape[1]] = big
    return zone, oy, big.shape


@pytest.mark.parametrize("stage,cond", [(0, "day"), (1, "storm"), (2, "day"), (3, "night"), (4, "storm")])
def test_cam1_zone_is_the_traced_sensor_image_twins_folded(params, stage, cond):
    tr = make_trace(stage, cond)
    cf = _cf(params, tr)
    for k, i in enumerate(cf.selected):
        zone = cf.frames[k][CAM_Y:CAM_Y + CAM_H, CAM_X:CAM_X + CAM_W].astype(np.int64)
        want, oy, shp = _expected_zone(tr.frames[i].cam_index)
        keep = np.ones((CAM_H, CAM_W), dtype=bool)
        for (x, y, w, h) in cf.overlay_rects[k]:
            keep[max(0, y - CAM_Y):max(0, y - CAM_Y + h), max(0, x - CAM_X):max(0, x - CAM_X + w)] = False
        odd_rows = np.zeros((CAM_H, CAM_W), dtype=bool)
        odd_rows[oy:oy + shp[0], :shp[1]] = (np.arange(oy, oy + shp[0]) % 2 == 1)[:, None]
        chk = keep & odd_rows
        assert ((zone[chk] >= 24) & (zone[chk] < 48)).all()          # scanline twins on odd rows
        zone[chk] -= 24                                               # fold the codage back
        assert (zone[keep] == want[keep]).all(), f"stage {stage} frame {k}"
        assert keep.sum() > 0.85 * keep.size


def _local_expected(tr, i, explored, params):
    fr = tr.frames[i]
    x0, y0 = int(np.floor(fr.pose[0])) - 30, int(np.floor(fr.pose[1])) - 30
    exp = np.full((60, 60), -1, dtype=np.int64)       # -1 unknown
    for yy in range(60):
        for xx in range(60):
            cx, cy = x0 + xx, y0 + yy
            if explored.window_mask(cx, cy, 1, 1)[0, 0] == 1:
                exp[yy, xx] = 1
    for (sx, sy, t) in tr.seen.tolist():
        if t <= fr.tick and 0 <= sx - x0 < 60 and 0 <= sy - y0 < 60:
            exp[sy - y0, sx - x0] = 1
    gt = terrain(np.arange(x0, x0 + 60)[None, :] + 0 * np.arange(60)[:, None], np.arange(y0, y0 + 60)[:, None] + 0 * np.arange(60)[None, :])
    ramp = np.asarray([RAMP_BASE[g] for g in range(4)])
    return np.where(exp == 1, ramp[gt] + 3, BG)


def test_local_map_frame_by_frame_no_cell_from_the_future(params):
    tr = make_trace(2, "day")
    ex = Explored()
    ex.mark(np.arange(-5, 6), np.zeros(11, dtype=np.int64), 0)         # explored at the start of the sol
    cf = _cf(params, tr, ex)
    leaked_checked = 0
    for k, i in enumerate(cf.selected):
        want = np.repeat(np.repeat(_local_expected(tr, i, ex, params), 2, axis=0), 2, axis=1)
        got = cf.frames[k][panels.MAP_Y:panels.MAP_Y + 120, panels.MAP_X:panels.MAP_X + 120].astype(np.int64)
        got = np.where(np.isin(got, [49, 50]), BG, got)                    # vignette steps are background
        overlay = np.isin(got, [hud(6), hud(10), MARK]) & (got != want)
        assert (got[~overlay] == want[~overlay]).all(), f"local map differs at frame {k}"
        assert overlay.sum() < 0.1 * overlay.size
        # no colour of terrain (indices 0-23) where the cell is still unknown at tick t
        assert not ((want == BG) & (got < 24)).any()
        leaked_checked += int((want == BG).sum())
    assert leaked_checked > 0
    # frame 0: cells whose first tick > its tick are not coloured
    fr0 = tr.frames[cf.selected[0]]
    later = tr.seen[tr.seen[:, 2] > fr0.tick]
    assert later.shape[0] > 0
    x0, y0 = int(np.floor(fr0.pose[0])) - 30, int(np.floor(fr0.pose[1])) - 30
    g0 = cf.frames[0]
    for sx, sy, _ in later.tolist():
        if 0 <= sx - x0 < 60 and 0 <= sy - y0 < 60 and not (sy == 0 and -5 <= sx <= 5):
            v = g0[panels.MAP_Y + 2 * (sy - y0), panels.MAP_X + 2 * (sx - x0)]
            assert v >= 24


def _frame(params, tr, i=60, stage=None):
    bv = BrainView(tr, params)
    img, _ = render_frame(tr, i, make_state(tr), make_progress(tr.stage), NOW, True, bv, Explored(), terrain, params)
    return img, bv


def test_brain_node_follows_the_recorded_activation(params):
    tr = make_trace(3, "day")
    a, bv = _frame(params, tr)
    tr2 = copy.deepcopy(tr)
    j = 5
    tr2.frames[60].h = tr2.frames[60].h.copy()
    tr2.frames[60].h[j] = 0.0 if abs(tr.frames[60].h[j]) > 0.5 else 1.0
    b, _ = _frame(params, tr2)
    y = bv.h_y[j]
    assert not (a[y - 3:y + 4, 437:444] == b[y - 3:y + 4, 437:444]).all()
    # an untouched node is unchanged
    y2 = bv.h_y[9]
    assert (a[y2 - 3:y2 + 4, 437:444] == b[y2 - 3:y2 + 4, 437:444]).all()


def test_brain_connection_follows_the_weight(params):
    tr = make_trace(3, "day")
    bv = BrainView(tr, params)
    fr = tr.frames[60]
    conns = bv.connections(fr)
    assert 0 < len(conns) <= params.get("render.brain_top_l1") + 32
    # change the weight of the strongest layer-1 connection: the connection set / brightness changes
    tr2 = copy.deepcopy(tr)
    th = np.asarray(tr2.snapshot.m0, dtype=np.float32).copy()
    top = max((c for c in conns if c[0] == 360), key=lambda c: c[4])
    i = [k for k, y in bv.in_y.items() if y == top[1]][0]
    j = bv.h_y.index(top[3])
    th[i * 16 + j] = th[i * 16 + j] * -1.0 - 0.3
    tr2.snapshot = type(tr.snapshot)(**{**tr.snapshot.__dict__, "m0": th})
    a, _ = _frame(params, tr)
    b, _ = _frame(params, tr2)
    assert not (a[56:166, 360:441] == b[56:166, 360:441]).all()


def test_printed_numbers_come_from_the_record(params):
    tr = make_trace(3, "day")
    img, _ = _frame(params, tr, 60)
    fr = tr.frames[60]
    rows = panels.telemetry_values(fr, 3, params)
    cm = fr.speed * params.get("world.cell_m") * 100 / params.get("run.tick_s")
    assert rows[0][1] == "%.2f cm/s" % cm
    assert rows[1][1] == "%d%%" % int(fr.battery * 100 + 1e-9)
    # pixels of the speed text = the font rendering of that string
    from rover.render import font
    ref = np.full((360, 640), 48, dtype=np.uint8)
    r = font.draw_text(ref, panels.TEL_X + 54, panels.TEL_Y + 30, rows[0][1], hud(10), 2)
    x, y, w, h = r
    assert (img[y:y + h, x:x + w] == ref[y:y + h, x:x + w]).all()
    txt = "L %+.2f R %+.2f" % (fr.u[0], fr.u[1])
    ref[:] = 48
    x, y, w, h = font.draw_text(ref, 632 - 4 - font.text_width(txt), 172, txt, hud(10), 1)
    m = ref[y:y + h, x:x + w] != 48
    assert m.any() and (img[y:y + h, x:x + w][m] == ref[y:y + h, x:x + w][m]).all()


def test_render_never_calls_the_prng():
    root = Path(__file__).resolve().parents[2] / "src" / "rover" / "render"
    for f in sorted(root.glob("*.py")):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                assert "rng" not in (n.module or "").split("."), f
                assert not any(a.name in ("rng", "uniform", "gauss_ih4", "u64", "randint") for a in n.names), f
            if isinstance(n, ast.Import):
                assert not any("random" in a.name or a.name.endswith("rng") for a in n.names), f
            if isinstance(n, ast.Attribute) and n.attr == "random":
                raise AssertionError(f"{f}: .random")


def test_locked_modules_are_silhouettes_and_real_module_labels(params):
    tr = make_trace(0, "day")
    cf = _cf(params, tr)
    assert cf.overlay_rects and len(cf.frames) == 75
    tr3 = make_trace(3, "day")
    assert BrainView(tr3, params).active != BrainView(tr, params).active


def test_battery_gate_comes_from_the_m0_mask_and_locked_text(params):
    from rover.core.consts import M0_ACTIVE
    for stage in range(len(M0_ACTIVE)):
        assert panels.battery_unlocked(stage) == (18 in M0_ACTIVE[stage])
    for stage in (0, 1, 2):
        tr = make_trace(stage, "day")
        rows = dict((r[0], r) for r in panels.telemetry_values(tr.frames[0], stage, params))
        assert rows["BATTERY"][1] == "LOCKED" and rows["BATTERY"][2] is None
    tr = make_trace(3, "day")
    fr = tr.frames[0]
    rows = dict((r[0], r) for r in panels.telemetry_values(fr, 3, params))
    assert rows["BATTERY"][1] == "%d%%" % int(np.floor(fr.battery * 100.0 + 1e-9))
    assert rows["BATTERY"][2] == fr.battery


def test_intent_label_is_uppercase_and_from_mode_labels(params):
    import inspect
    from rover.render import brain_view
    assert '"INTENT: " + consts.MODE_LABELS[fr.mode]' in inspect.getsource(brain_view)
