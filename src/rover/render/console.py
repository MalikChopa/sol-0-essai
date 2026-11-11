"""Console 640x360 (SPEC 7.4): title bar, CAM-1 (the real sensor image), BRAIN, local map, telemetry, SCAN placeholder."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rover.config import Params
from rover.core.consts import MODE_LABELS
from rover.core.exact import to_int
from rover.core.types import Progress, Trace
from rover.render import draw, font, panels
from rover.render.brain_view import BrainView
from rover.render.cam_view import CAM_H, CAM_W, CAM_X, CAM_Y, draw_cam, draw_overlays
from rover.render.palette import BG, MARK, REC, hud
from rover.render.vignettes import apply_vignette
from rover.state.explored import Explored

Arr = np.ndarray
Rect = tuple


@dataclass
class ConsoleFrames:
    frames: list
    durations_ms: list
    selected: list
    cam_rect: Rect
    overlay_rects: list


def select_frames(trace: Trace, n: int, max_sleep: int, min_run: int) -> list:
    """SPEC 7.3: at most `max_sleep` sleep frames, the rest awake frames spread evenly; every sleep run in the result has
    >= min_run frames (a shorter run is dropped and replaced by unused awake frames)."""
    n = min(n, len(trace.frames))
    sleep = [i for i, f in enumerate(trace.frames) if f.mode == "SLEEP"]
    awake = [i for i, f in enumerate(trace.frames) if f.mode != "SLEEP"]
    ns = min(max_sleep, len(sleep), n)
    if 0 < ns < min_run:
        ns = 0
    na = n - ns
    if na > len(awake):
        na = len(awake)
        ns = min(len(sleep), n - na)
    pick_a = [awake[(i * len(awake)) // na] for i in range(na)] if na else []
    pick_s = [sleep[(i * len(sleep)) // ns] for i in range(ns)] if ns else []
    sel = sorted(pick_a + pick_s)
    is_sleep = {i: True for i in sleep}
    runs, cur = [], []
    for i in sel:
        if i in is_sleep:
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    drop = [i for r in runs if len(r) < min_run for i in r]
    if drop:
        sel = [i for i in sel if i not in drop]
        pool = [i for i in awake if i not in sel]
        k = len(drop)
        extra = [pool[(j * len(pool)) // k] for j in range(min(k, len(pool)))] if pool else []
        sel = sorted(sel + extra)
    return sel


def _hhmm(hour: float) -> str:
    hh = to_int(np.floor(hour))
    mm = to_int(np.floor((hour - hh) * 60.0))
    return "%02d:%02d" % (hh, mm)


def render_frame(trace: Trace, i: int, state: dict, progress: Progress, now_utc: str, scanlines: bool, bv: BrainView,
                 explored_start: Explored, terrain, params: Params):
    fr = trace.frames[i]
    img = np.full((360, 640), BG, dtype=np.uint8)
    rects = []
    font.draw_text(img, 8, 3, "SOL-0", hud(10), 2)
    font.draw_text(img, 72, 6, "CAM-1", hud(10), 1)
    img[7:14, 112:119] = REC if fr.mode != "SLEEP" else hud(3)
    font.draw_text(img, 122, 6, "REC", hud(10), 1)
    center = "SOL %04d | STAGE %d %s" % (trace.sol, trace.stage, progress.label_en.upper())
    right = "LAST CONTACT " + now_utc[:10] + " " + now_utc[11:16] + " UTC"
    rx = 632 - font.text_width(right)
    cx = max(150, 150 + (rx - 8 - 150 - font.text_width(center)) // 2)
    font.draw_text(img, cx, 6, center, hud(10), 1)
    font.draw_text(img, rx, 6, right, hud(10), 1)
    draw.rect(img, 0, 20, 640, 1, hud(2))
    draw_cam(img, fr.cam_index, scanlines)
    draw.frame_rect(img, CAM_X - 1, CAM_Y - 1, CAM_W + 2, CAM_H + 2, hud(4))
    rects.append(font.draw_text(img, CAM_X + 4, CAM_Y + 4, _hhmm(fr.hour), MARK, 1))
    h, w = fr.cam_index.shape
    acu = "%dX%d" % (w, h)
    rects.append(font.draw_text(img, CAM_X + CAM_W - 4 - font.text_width(acu), CAM_Y + CAM_H - 11, acu, MARK, 1))
    if trace.stage == 0:
        t = "VISION OFFLINE"
        rects.append(font.draw_text(img, CAM_X + (CAM_W - font.text_width(t)) // 2, CAM_Y + CAM_H // 2 - 3, t, MARK, 1))
    if fr.mode == "SLEEP":
        t = MODE_LABELS["SLEEP"]
        rects.append(font.draw_text(img, CAM_X + (CAM_W - font.text_width(t)) // 2, CAM_Y + 20, t, MARK, 1))
    for flag, t in ((fr.stuck, "STUCK"), (fr.tipped, "TIPPED")):
        if flag:
            rects.append(font.draw_text(img, CAM_X + 4, CAM_Y + 14 + (0 if t == "STUCK" else 9), t, MARK, 1))
    rects.extend(draw_overlays(img, fr, trace.stage, params))
    bv.draw(img, fr, trace.stage)
    panels.draw_local_map(img, trace, i, explored_start, terrain)
    panels.draw_telemetry(img, fr, trace.stage, params)
    panels.draw_scan(img, trace.stage)
    apply_vignette(img, (CAM_X - 1, CAM_Y - 1, CAM_W + 2, CAM_H + 2))
    return img, rects


def build_console(trace: Trace, state: dict, explored_start: Explored, terrain, progress: Progress, now_utc: str,
                  params: Params, scanlines: bool = True, n_frames: int = 75, durations_ms: int = 100,
                  cache: dict | None = None) -> ConsoleFrames:
    sel = select_frames(trace, n_frames, int(params.get("render.max_sleep_frames")), int(params.get("render.min_sleep_run")))
    bv = BrainView(trace, params)
    frames, rects = [], []
    for i in sel:
        key = (i, bool(scanlines))
        if cache is not None and key in cache:
            img, r = cache[key]
        else:
            img, r = render_frame(trace, i, state, progress, now_utc, scanlines, bv, explored_start, terrain, params)
            if cache is not None:
                cache[key] = (img, r)
        frames.append(img)
        rects.append(r)
    return ConsoleFrames(frames=frames, durations_ms=[durations_ms] * len(frames), selected=sel,
                         cam_rect=(CAM_X, CAM_Y, CAM_W, CAM_H), overlay_rects=rects)
