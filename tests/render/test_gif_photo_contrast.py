"""Photosensitivity (EF-87), LP level, size ladder, contrasts (SPEC 7.1), CAM_LUT, SVG and map limits."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fake_trace import make_progress, make_state, make_trace, terrain
from rover import config
from rover.config import Params
from rover.core.consts import CAM_LUT
from rover.render import PALETTE, map_png, photosens, status_svg
from rover.render.gif import encode_gif_report
from rover.render.palette import BG, MARK, NEG, REC, hud
from rover.state import Explored

NOW = "2026-11-11T07:17:00Z"


def _report(params, tr, **kw):
    return encode_gif_report(tr, make_state(tr), Explored(), terrain, make_progress(tr.stage), NOW, params, **kw)


def _decode_rgb(gif):
    im = Image.open(io.BytesIO(gif))
    out = []
    for i in range(im.n_frames):
        im.seek(i)
        out.append(np.asarray(im.convert("RGB")).astype(np.float64))
    return out, [Image.open(io.BytesIO(gif)).info.get("duration")]


def _lum(rgb):
    def lin(c):
        c = c / 255.0
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)      # test only: float reference
    return 0.2126 * lin(rgb[..., 0]) + 0.7152 * lin(rgb[..., 1]) + 0.0722 * lin(rgb[..., 2])


def _worst_from_rgb(frames, ms):
    times, t = [], 0
    for k in range(1, len(frames)):
        t += ms
        a, b = _lum(frames[k - 1]), _lum(frames[k])
        ch = (np.abs(a - b) >= 0.1) & (np.minimum(a, b) < 0.8)
        if ch.sum() * 4 >= ch.size:
            times.append(t)
    return max([len([x for x in times if ti - 1000 < x <= ti]) for ti in times] + [0])


@pytest.mark.parametrize("stage,cond", [(0, "day"), (2, "night"), (3, "storm"), (4, "day")])
def test_gif_photosensitivity_on_the_decoded_gif(params, stage, cond):
    r = _report(params, make_trace(stage, cond))
    frames, dur = _decode_rgb(r["data"])
    assert r["level"] == "L0"
    assert _worst_from_rgb(frames, dur[0]) <= 3
    assert r["worst_transitions"] <= 3


def test_flicker_triggers_level_lp_and_lp_is_compliant(params):
    tr = make_trace(3, "day", flicker=True)
    r = _report(params, tr)
    assert r["level"] == "LP" and r["before_lp"] > 3
    frames, dur = _decode_rgb(r["data"])
    assert len(frames) == params.get("render.photosafe")[0] == 22
    assert dur[0] == 340
    assert _worst_from_rgb(frames, 340) <= 3 and r["worst_transitions"] <= 3
    assert len(r["data"]) <= params.get("render.gif_max_bytes")


def test_transitions_detector_unit():
    a = np.zeros((10, 10), dtype=np.uint8)
    b = np.full((10, 10), 17, dtype=np.uint8)
    seq = [a, b] * 6
    assert photosens.transitions(seq, [100] * 12)[0] > 3
    assert photosens.transitions(seq, [340] * 12)[0] <= 3
    c = b.copy()
    c[:1] = 0                                       # 10 % of the image: not a transition
    assert photosens.transitions([b, c, b, c, b, c, b], [100] * 7)[0] == 0
    assert photosens.transitions([b, b + 0, b], [100] * 3)[0] == 0


def test_luminance_table_matches_float_reference():
    ref = _lum(np.asarray(PALETTE, dtype=np.float64))
    assert np.abs(ref - photosens.luminance_table()).max() < 1e-9


def test_ladder_reduces_and_lands_under_the_cap(params):
    tr = make_trace(4, "storm")
    full = _report(params, tr)["sizes"]["L0"]
    for cap, expected_min_level in ((int(full * 0.8), 1), (int(full * 0.55), 2), (int(full * 0.3), 3)):
        data = dict(params.data)
        data["render"] = {**params.data["render"], "gif_max_bytes": cap}
        p2 = Params(data=data, hash=params.hash)
        r = _report(p2, tr)
        lvl = int(r["level"][1:]) if r["level"] != "LP" else 99
        assert lvl >= expected_min_level
        if not r["oversize"]:
            assert len(r["data"]) <= cap
        sizes = list(r["sizes"].values())
        assert sizes == sorted(sizes, reverse=True) or r["level"] == "LP"


def test_cam_lut_equals_the_formula_on_the_palette():
    got = tuple((2 * r + 5 * g + b) // 8 for (r, g, b) in PALETTE[:24])
    assert got == CAM_LUT


def test_twins_are_82_percent():
    for i in range(24):
        assert PALETTE[24 + i] == tuple(c * 82 // 100 for c in PALETTE[i])


def _wcag(rgb):
    return float(_lum(np.asarray(rgb, dtype=np.float64)))


def _ratio(a, b):
    la, lb = _wcag(a), _wcag(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_contrast_values_of_the_spec():
    bg = PALETTE[BG]
    assert abs(_ratio(PALETTE[hud(5)], bg) - 3.43) < 0.02
    assert abs(_ratio(PALETTE[hud(6)], bg) - 4.48) < 0.02
    assert abs(_ratio(PALETTE[hud(7)], bg) - 5.68) < 0.02
    assert abs(_ratio(PALETTE[hud(10)], bg) - 10.89) < 0.02
    assert abs(_ratio(PALETTE[NEG], bg) - 8.31) < 0.02
    assert abs(_ratio(PALETTE[MARK], bg) - 15.54) < 0.02
    assert abs(_ratio(PALETTE[REC], bg) - 5.93) < 0.02


def test_informative_text_keeps_3_to_1_after_reduction_to_053(params):
    from rover.render import build_console
    from rover.render.gif import _palette_bytes
    for stage in (0, 2, 3):
        tr = make_trace(stage, "day")
        cf = build_console(tr, make_state(tr), Explored(), terrain, make_progress(stage), NOW, params, n_frames=3)
        img = cf.frames[1]
        im = Image.frombytes("P", (640, 360), img.tobytes())
        im.putpalette(_palette_bytes())
        small = np.asarray(im.convert("RGB").resize((339, 191), Image.BOX)).astype(np.float64)
        from rover.render import font, panels
        regions = [(150, 6, 480, 7)]                                    # title bar text (x1, informative)
        fr = tr.frames[cf.selected[1]]
        for label_x, label_y, text in ((panels.TEL_X + 6, panels.TEL_Y + 34, "BATTERY"),
                                       (340, 190, "intent: " + "x" * 8)):
            regions.append((label_x, label_y, font.text_width(text), 7))
        bgl = _wcag(PALETTE[BG])
        for (x, y, w, h) in regions:
            sub = small[int(y * 0.53):int((y + h) * 0.53) + 1, int(x * 0.53):int((x + w) * 0.53) + 1]
            best = max(_wcag(p) for row in sub for p in row)
            assert (best + 0.05) / (bgl + 0.05) >= 3.0, (stage, x, y, best)


def test_status_svg_and_map_limits(params):
    tr = make_trace(2, "day")
    st = {"sol": 42, "stage": {"id": 2, "consolidation": False}}
    svg = status_svg(st, make_progress(2), NOW, params)
    assert len(svg.encode()) <= 20 * 1024
    assert "<script" not in svg and "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "last contact 2026-11-11 07:17 UTC" in svg and "81 %" in svg
    ex = Explored()
    xs, ys = np.meshgrid(np.arange(-70, 90), np.arange(-60, 60))
    ex.mark(xs.ravel(), ys.ravel(), 1)
    png = map_png(make_state(tr), ex, terrain, tr, params)
    im = Image.open(io.BytesIO(png))
    assert im.mode == "P" and im.size[0] <= 1200 and im.size[1] <= 800


def test_map_fog_three_states(params):
    tr = make_trace(2, "day")
    ex = Explored()
    ex.mark(np.arange(-20, 20), np.arange(-20, 20), 1)
    st = make_state(tr)
    png = map_png(st, ex, terrain, tr, params)
    arr = np.asarray(Image.open(io.BytesIO(png)))
    assert (arr == BG).sum() > 1000                        # unknown
    ramp = {0, 6, 12}
    levels = {int(v) - min(ramp, key=lambda r: abs(r - int(v)) if int(v) >= r else 99) for v in np.unique(arr[arr < 18])}
    assert 1 in levels and 3 in levels                     # explored (1) and seen during the last sol (3)


def test_golden_fingerprints(params):
    import json, os
    from rover.render.refs import fingerprints
    got = fingerprints(params)
    f = Path(__file__).resolve().parent / "golden.json"
    if os.environ.get("SOL0_UPDATE_GOLDEN") == "1":
        f.write_text(json.dumps(got, sort_keys=True, indent=1) + "\n")
    assert got == json.loads(f.read_text())
