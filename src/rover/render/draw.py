"""Integer drawing primitives on a uint8 palette-index image (exact: no float to int conversion, no PRNG)."""
from __future__ import annotations

import numpy as np


def put(img: np.ndarray, x: int, y: int, c: int) -> None:
    if 0 <= y < img.shape[0] and 0 <= x < img.shape[1]:
        img[y, x] = c


def rect(img: np.ndarray, x: int, y: int, w: int, h: int, c: int) -> None:
    H, W = img.shape
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 > x0 and y1 > y0:
        img[y0:y1, x0:x1] = c


def frame_rect(img: np.ndarray, x: int, y: int, w: int, h: int, c: int) -> None:
    rect(img, x, y, w, 1, c)
    rect(img, x, y + h - 1, w, 1, c)
    rect(img, x, y, 1, h, c)
    rect(img, x + w - 1, y, 1, h, c)


def line(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, c: int, dotted: bool = False, thick: int = 1) -> None:
    """Bresenham; `dotted` draws 1 px out of 2; `thick` 2 adds the pixel below."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    n = 0
    while True:
        if not dotted or n % 2 == 0:
            put(img, x0, y0, c)
            if thick > 1:
                put(img, x0, y0 + 1, c)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
        n += 1


def disc(img: np.ndarray, cx: int, cy: int, r: int, c: int) -> None:
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r + r // 2:
                put(img, cx + dx, cy + dy, c)


def ring(img: np.ndarray, cx: int, cy: int, r: int, c: int) -> None:
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            d = dx * dx + dy * dy
            if r * r - r <= d <= r * r + r:
                put(img, cx + dx, cy + dy, c)


def cross(img: np.ndarray, cx: int, cy: int, r: int, c: int) -> None:
    line(img, cx - r, cy, cx + r, cy, c)
    line(img, cx, cy - r, cx, cy + r, c)
