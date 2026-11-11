"""Local map, telemetry and SCAN panels of the console (SPEC 7.4). All values come from the FrameRecord / Trace / terrain."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.consts import M0_ACTIVE, RAMP_BASE
from rover.core.dmath import atan
from rover.core.exact import to_int
from rover.core.types import FrameRecord, Trace
from rover.render import draw, font
from rover.render.palette import BG, MARK, hud
from rover.state.explored import Explored

MAP_X, MAP_Y, MAP_S = 8, 232, 120
CELLS = 60                       # 2 px per cell
TEL_X, TEL_Y, TEL_W = 136, 232, 248
SCAN_X, SCAN_Y, SCAN_W, SCAN_H = 392, 232, 240, 120
_RAMP = np.asarray([RAMP_BASE[g] for g in range(4)], dtype=np.int64)


def local_map_cells(trace: Trace, fr: FrameRecord, explored_start: Explored, terrain) -> tuple:
    """The 60x60 window of explored cells at the instant of the frame: explored_start U cells of trace.seen with first tick <= t.
    Returns (x0, y0, known mask [y, x], gtype)."""
    x0 = to_int(np.floor(fr.pose[0])) - CELLS // 2
    y0 = to_int(np.floor(fr.pose[1])) - CELLS // 2
    known = explored_start.window_mask(x0, y0, CELLS, CELLS) == 1
    if trace.seen.shape[0]:
        s = trace.seen
        keep = s[:, 2] <= fr.tick
        sx, sy = s[keep, 0] - x0, s[keep, 1] - y0
        ok = (sx >= 0) & (sy >= 0) & (sx < CELLS) & (sy < CELLS)
        known[sy[ok], sx[ok]] = True
    gt = np.zeros(known.shape, dtype=np.int64)
    if bool(np.any(known)):
        gx, gy = np.meshgrid(x0 + np.arange(CELLS, dtype=np.int64), y0 + np.arange(CELLS, dtype=np.int64))
        gt[known] = terrain(gx[known], gy[known])
    return x0, y0, known, gt


def draw_local_map(img: np.ndarray, trace: Trace, i: int, explored_start: Explored, terrain) -> None:
    fr = trace.frames[i]
    x0, y0, known, gt = local_map_cells(trace, fr, explored_start, terrain)
    cells = np.where(known, np.take(_RAMP, gt) + 3, BG)
    big = np.repeat(np.repeat(cells, 2, axis=0), 2, axis=1)
    img[MAP_Y:MAP_Y + MAP_S, MAP_X:MAP_X + MAP_S] = to_int(big, np.uint8)
    draw.frame_rect(img, MAP_X - 1, MAP_Y - 1, MAP_S + 2, MAP_S + 2, hud(4))

    def px(x, y):
        return MAP_X + to_int(np.floor((x - x0) * 2.0)), MAP_Y + to_int(np.floor((y - y0) * 2.0))

    for k in range(i + 1):
        a, b = px(trace.frames[k].pose[0], trace.frames[k].pose[1])
        if MAP_X <= a < MAP_X + MAP_S and MAP_Y <= b < MAP_Y + MAP_S:
            img[b, a] = hud(6)
    if fr.target is not None:
        a, b = px(fr.target[0], fr.target[1])
        if MAP_X + 3 <= a < MAP_X + MAP_S - 3 and MAP_Y + 3 <= b < MAP_Y + MAP_S - 3:
            draw.cross(img, a, b, 3, MARK)
    a, b = px(fr.pose[0], fr.pose[1])
    c, s = fr.pose[2], fr.pose[3]
    tipx, tipy = a + to_int(np.floor(5.0 * c + 0.5)), b + to_int(np.floor(5.0 * s + 0.5))
    lx, ly = a - to_int(np.floor(2.0 * s + 0.5)), b + to_int(np.floor(2.0 * c + 0.5))
    rx, ry = a + to_int(np.floor(2.0 * s + 0.5)), b - to_int(np.floor(2.0 * c + 0.5))
    draw.line(img, lx, ly, tipx, tipy, hud(10))
    draw.line(img, rx, ry, tipx, tipy, hud(10))
    draw.line(img, lx, ly, rx, ry, hud(10))


BATTERY_INPUT = 18  # M0 input index of the battery level (SPEC 3.4)


def battery_unlocked(stage: int) -> bool:
    """The battery is shown once the M0 mask lets its input through (single source: core.consts.M0_ACTIVE)."""
    return BATTERY_INPUT in M0_ACTIVE[min(max(stage, 0), len(M0_ACTIVE) - 1)]


def tilt_deg(fr: FrameRecord) -> float:
    return float(atan(np.sqrt(fr.pitch * fr.pitch + fr.roll * fr.roll))) * 57.29577951308232


def telemetry_values(fr: FrameRecord, stage: int, params: Params) -> list:
    """(label, text, bar fraction or None) for the 4 lines; the numbers are the ones printed."""
    cm = fr.speed * params.get("world.cell_m") * 100.0 / params.get("run.tick_s")
    vmax_cm = params.get("rover.v_max") * params.get("world.cell_m") * 100.0 / params.get("run.tick_s")
    tl = tilt_deg(fr)
    bat = ("%d%%" % to_int(np.floor(fr.battery * 100.0 + 1e-9)), fr.battery) if battery_unlocked(stage) else ("LOCKED", None)
    return [("SPEED", "%.2f cm/s" % cm, min(1.0, cm / vmax_cm)),
            ("BATTERY", bat[0], bat[1]),
            ("TILT", "%.1f deg" % tl, min(1.0, tl / 35.0)),
            ("SLIP", "%d%%" % to_int(np.floor(fr.slip * 100.0 + 1e-9)), min(1.0, max(0.0, fr.slip)))]


def draw_telemetry(img: np.ndarray, fr: FrameRecord, stage: int, params: Params) -> list:
    draw.frame_rect(img, TEL_X, TEL_Y, TEL_W, 120, hud(4))
    font.draw_text(img, TEL_X + 4, TEL_Y + 4, "TELEMETRY", hud(10), 1)
    rows = telemetry_values(fr, stage, params)
    for k, (label, text, frac) in enumerate(rows):
        y = TEL_Y + 30 + 22 * k
        font.draw_text(img, TEL_X + 6, y + 4, label, hud(10), 1)
        font.draw_text(img, TEL_X + 54, y, text, hud(10), 2)
        bx = TEL_X + 170
        draw.frame_rect(img, bx, y + 3, 68, 8, hud(4))
        if frac is not None:
            draw.rect(img, bx + 1, y + 4, to_int(np.floor(66.0 * frac)), 6, hud(10))
    return rows


def draw_scan(img: np.ndarray, stage: int) -> None:
    draw.frame_rect(img, SCAN_X, SCAN_Y, SCAN_W, SCAN_H, hud(4))
    font.draw_text(img, SCAN_X + 4, SCAN_Y + 4, "SCAN | ???", hud(3), 1)
    font.draw_text(img, SCAN_X + (SCAN_W - font.text_width("INSTRUMENT NOT DISCOVERED")) // 2, SCAN_Y + 56,
                   "INSTRUMENT NOT DISCOVERED", hud(3), 1)
