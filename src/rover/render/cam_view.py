"""CAM-1 zone: the camera palette-index image, enlarged by nearest neighbour (SPEC 7.4)."""
from __future__ import annotations

import numpy as np

from rover.core import consts
from rover.render.palette import BG, TWIN

CAM_X, CAM_Y, CAM_W, CAM_H = 8, 24, 320, 200


def scale_for(w: int, h: int) -> tuple[int, int]:
    return CAM_W // w, CAM_H // h


def draw_cam(frame: np.ndarray, cam_index: np.ndarray, scanlines: bool) -> None:
    """Write the enlarged sensor image into the frame. Odd rows of the zone use the scanline twin (index + 24)."""
    h, w = cam_index.shape
    sx, sy = scale_for(w, h)
    big = np.repeat(np.repeat(cam_index, sy, axis=0), sx, axis=1)
    oy = (CAM_H - big.shape[0]) // 2
    zone = np.full((CAM_H, CAM_W), BG, dtype=np.uint8)
    zone[oy:oy + big.shape[0], :big.shape[1]] = big
    if scanlines:
        rows = np.arange(oy, oy + big.shape[0])
        odd = (rows % 2) == 1
        sub = zone[oy:oy + big.shape[0], :big.shape[1]]
        sub[odd] = sub[odd] + TWIN
    frame[CAM_Y:CAM_Y + CAM_H, CAM_X:CAM_X + CAM_W] = zone


def expected_cam(cam_index: np.ndarray, scanlines: bool = False) -> np.ndarray:
    """What the CAM-1 zone must contain for a given sensor image, twins folded back (used by the truth test)."""
    h, w = cam_index.shape
    sx, sy = scale_for(w, h)
    big = np.repeat(np.repeat(cam_index, sy, axis=0), sx, axis=1)
    zone = np.full((CAM_H, CAM_W), BG, dtype=np.uint8)
    oy = (CAM_H - big.shape[0]) // 2
    zone[oy:oy + big.shape[0], :big.shape[1]] = big
    return zone


def draw_overlays(img: np.ndarray, fr, stage: int, params) -> list:
    """Overlays of SPEC 7.4 on CAM-1, from the FrameRecord only. Returns their rectangles (excluded from the truth test)."""
    from rover.core.exact import to_int
    from rover.render import draw, font
    from rover.render.palette import MARK, hud
    rects = []
    h, w = fr.cam_index.shape
    sx, sy = scale_for(w, h)
    zw, zh = w * sx, h * sy
    oy = (CAM_H - zh) // 2
    if stage >= 2 and fr.target is not None and fr.mode != "SLEEP":
        px, py, c, s = fr.pose
        dx, dy = fr.target[0] - px, fr.target[1] - py
        fwd = dx * c + dy * s
        lat = -dx * s + dy * c
        if fwd > 0.0:
            uw = lat / fwd / 0.7
            if -1.0 <= uw <= 1.0:
                cx = CAM_X + to_int(np.floor((uw + 1.0) / 2.0 * zw))
                hor = 0.35 * h + fr.pitch * 0.9 * h
                cy = CAM_Y + oy + to_int(np.floor(min(max(hor, 0.0), h - 1.0) * sy))
                draw.ring(img, cx, cy, 6, MARK)
                draw.cross(img, cx, cy, 9, MARK)
                rects.append((cx - 9, cy - 9, 19, 19))
    if 18 in consts.M0_ACTIVE[min(max(stage, 0), len(consts.M0_ACTIVE) - 1)]:  # battery input unlocked
        t = "BAT %d%%" % to_int(np.floor(fr.battery * 100.0 + 1e-9))
        rects.append(font.draw_text(img, CAM_X + CAM_W - 4 - font.text_width(t), CAM_Y + 4, t, MARK, 1))
        if fr.sun_elev > 0.0 and fr.mode != "SLEEP":
            px, py, c, s = fr.pose
            fwd = fr.sun_dx * c + fr.sun_dy * s
            lat = -fr.sun_dx * s + fr.sun_dy * c
            ax, ay = CAM_X + 22, CAM_Y + CAM_H - 26
            ex, ey = ax + to_int(np.floor(14.0 * lat + 0.5)), ay - to_int(np.floor(14.0 * fwd + 0.5))
            draw.ring(img, ax, ay, 16, hud(7))
            draw.line(img, ax, ay, ex, ey, MARK, thick=2)
            draw.disc(img, ex, ey, 2, MARK)
            rects.append((ax - 17, ay - 17, 35, 35))
            rects.append(font.draw_text(img, ax - 9, ay + 19, "SUN", MARK, 1))
    return rects
