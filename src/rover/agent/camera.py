"""Camera = palette sensor (SPEC 3.5). Its palette-index image is both the input of M2 and the pixels of CAM-1."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core import consts
from rover.core.exact import icumsum, to_int
from rover.core.rng import uniform
from rover.core.types import CamFrame, SolEvents, Sun

Arr = np.ndarray
_RAMP = np.asarray([consts.RAMP_BASE[g] for g in range(4)], dtype=np.int64)
_EMIS = np.asarray([1.0, 0.7, 0.5, 0.5])


def camera_spec(stage: int, params: Params) -> tuple[int, int, float, int]:
    C = params.get("rover.camera")
    w, h = C["acuity"][stage]
    return int(w), int(h), float(C["radius"][stage]), int(C["slices"][stage])


def _project(rb, win, stage: int, ev: SolEvents, params: Params):
    """Steps 1-2 of SPEC 3.5: sample points, heights, ytop and the clipped first row r0 of each slice. Everything is per rover
    (no operation mixes two rovers of the batch)."""
    C = params.get("rover.camera")
    cm = params.get("world.cell_m")
    W, H, R, D = camera_spec(stage, params)
    R = R * ev.view_scale
    d = np.arange(1, D + 1, dtype=np.float64)
    dist = C["near"] + (R - C["near"]) * (d / D) * (d / D)                                     # (D,)
    uw = (np.arange(W, dtype=np.float64) + 0.5) / W * 2.0 - 1.0
    dirx = rb.c[:, None] - rb.s[:, None] * C["fov_tan"] * uw[None, :]                          # (B, W)
    diry = rb.s[:, None] + rb.c[:, None] * C["fov_tan"] * uw[None, :]
    px = rb.x[:, None, None] + dist[None, :, None] * dirx[:, None, :]                          # (B, D, W)
    py = rb.y[:, None, None] + dist[None, :, None] * diry[:, None, :]
    ix = to_int(np.floor(px + 0.5)) - win.x0
    iy = to_int(np.floor(py + 0.5)) - win.y0
    wh, ww = win.height.shape
    if not bool(np.all((ix >= 0) & (iy >= 0) & (ix < ww) & (iy < wh))):
        raise ValueError("camera sees outside the materialised window")
    flat = iy * ww + ix
    hh = np.take(win.height.ravel(), flat)
    cam_h = win.height_at(rb.x, rb.y) + params.get("rover.eye_m")
    horizon = C["horizon"] * H + rb.pitch * C["scale"] * H                                      # (B,)
    ytop = horizon[:, None, None] + ((cam_h[:, None, None] - hh) / cm) * C["scale"] * H / dist[None, :, None]
    m = np.minimum.accumulate(ytop, axis=1)
    r0 = to_int(np.clip(np.ceil(m - 0.5), 0, H))                                               # (B, D, W) in [0, H]
    return {"W": W, "H": H, "R": R, "D": D, "dist": dist, "ix": ix, "iy": iy, "flat": flat, "px": px, "py": py,
            "horizon": horizon, "r0": r0}


def _slices_hist(r0: Arr, D: int, H: int) -> Arr:
    """Visible slice index per pixel by histogram (SPEC 3.5 step 3): (B, H, W) int64, D = sky."""
    B, _, W = r0.shape
    key = ((np.arange(B)[:, None, None] * W + np.arange(W)[None, None, :]) * (H + 1)) + r0
    cnt = np.bincount(key.ravel(), minlength=B * W * (H + 1)).reshape(B, W, H + 1)
    le = icumsum(cnt, 2)[:, :, :H]
    return np.transpose(D - le, (0, 2, 1))


def _slices_cmp(r0: Arr, D: int, H: int) -> Arr:
    """Same result by comparisons (reference, O(D*H*W)): slice count with first row <= r. Used by the tests."""
    B, _, W = r0.shape
    rows = np.arange(H, dtype=np.int64)[None, None, :]
    le = np.zeros((B, W, H), dtype=np.int64)
    for d in range(D):
        le = le + (r0[:, d, :, None] <= rows)
    return np.transpose(D - le, (0, 2, 1))


def capture(rb, win, stage: int, sun: Sun, ev: SolEvents, keys: Arr, tick: int, params: Params,
            want_seen: bool = False) -> CamFrame:
    C = params.get("rover.camera")
    cm = params.get("world.cell_m")
    pj = _project(rb, win, stage, ev, params)
    W, H, R, D, dist, ix, iy = pj["W"], pj["H"], pj["R"], pj["D"], pj["dist"], pj["ix"], pj["iy"]
    B = rb.x.shape[0]
    elev = float(sun.elev)
    sidx = _slices_hist(pj["r0"], D, H)                                                        # (B, H, W), D = sky
    valid = sidx < D
    sc = np.minimum(sidx, D - 1)
    pf = (np.arange(B)[:, None, None] * D + sc) * W + np.arange(W)[None, None, :]
    cell = np.take(pj["flat"].ravel(), pf)                                                     # window cell of each pixel
    g_pix = np.take(win.gtype.ravel(), cell)
    cgx, cgy = win.cell_gradient()
    nx, ny = -np.take(cgx.ravel(), cell) / cm, -np.take(cgy.ravel(), cell) / cm
    sxy = np.sqrt(np.maximum(0.0, 1.0 - sun.dir_z * sun.dir_z))
    n_pix = (nx * float(sun.dir_x * sxy) + ny * float(sun.dir_y * sxy) + float(sun.dir_z)) / np.sqrt(nx * nx + ny * ny + 1.0)
    f = (np.take(dist, sc) / R)
    f = f * f
    shade = elev * (0.55 + 0.45 * np.maximum(0.0, n_pix))
    level = 5.0 * shade * (1.0 - f) + 4.0 * f * min(1.0, 4.0 * elev)
    base = np.take(_RAMP, g_pix)
    night = elev < C["night_elev"]
    ir = stage >= 3 and night
    if ir:
        level = 1.0 + 4.0 * (1.0 - f) * (0.6 + 0.4 * np.take(_EMIS, g_pix))
        base = np.full_like(base, consts.RAMP_BASE[consts.GTYPE_SAND])
    if stage == 0:
        sigma = C["noise_offline"]
    elif ev.storm:
        sigma = C["noise_storm"]
    elif night:
        sigma = C["noise_night"]
    else:
        sigma = C["noise_day"]
    period = int(params.get("rover.cam_period"))
    j = (tick // period) * H * W + np.arange(H)[:, None] * W + np.arange(W)[None, :]
    noise = sigma * (2.0 * uniform(keys[:, None, None], j[None]) - 1.0)                        # keyed by (rover key, tick, pixel)
    if stage == 0:
        level = np.clip(0.25 * level + noise, 0.0, 1.49)
    else:
        level = level + noise
    if night and not ir:                                                                       # dark ground: indices 22-23
        ground = consts.DARK[0] + to_int(np.clip(np.floor(level + 0.5), 0, 1))
    else:
        ground = base + to_int(np.clip(np.floor(level + 0.5), 0, 5))
    horizon = pj["horizon"]
    rows = np.arange(H, dtype=np.float64)[None, :, None]
    sky = consts.SKY[0] + to_int(np.minimum(3.0, np.floor(4.0 * np.maximum(0.0, horizon[:, None, None] - rows) / np.maximum(1.0, horizon[:, None, None]))))
    sky = np.broadcast_to(sky, ground.shape)
    if night:
        sky = np.full_like(ground, consts.DARK[0])
    index = to_int(np.where(valid, ground, sky), np.uint8)
    depth = np.asarray(sidx, dtype=np.uint8)
    seen = None
    if want_seen:
        s0 = sidx[0]
        wcol = np.broadcast_to(np.arange(W)[None, :], s0.shape)
        sel = s0 < D
        ks = np.unique(s0[sel] * W + wcol[sel])
        cx = np.take(ix[0].ravel() + win.x0, ks)
        cy = np.take(iy[0].ravel() + win.y0, ks)
        cells = np.stack([cx, cy], axis=1)
        rr = C["seen_radius"]
        cxr = to_int(np.floor(rb.x[0] + 0.5))
        cyr = to_int(np.floor(rb.y[0] + 0.5))
        offs = np.arange(-2, 3)
        ox, oy = np.meshgrid(offs, offs)
        ox, oy = ox.ravel() + cxr, oy.ravel() + cyr
        near = ((ox - rb.x[0]) * (ox - rb.x[0]) + (oy - rb.y[0]) * (oy - rb.y[0])) <= rr * rr
        disc = np.stack([ox[near], oy[near]], axis=1)
        seen = np.unique(np.concatenate([cells, disc], axis=0), axis=0)
    return CamFrame(index=index, depth=depth, seen=seen, D=D)
