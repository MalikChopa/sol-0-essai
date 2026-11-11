"""Bitmap 5x7 font, ASCII 32-126 (SPEC 7.2). Advance 6 px, line 9 px, no anti-aliasing, no system font."""
from __future__ import annotations

import numpy as np

# Five column bytes per glyph (hex pairs), bit 0 = top row; glyphs for ASCII 32..126 in order.
_TABLE = (
    "0000000000 00005F0000 0007000700 147F147F14 242A7F2A12 2313086462 3649562050 0005030000 001C224100 0041221C00 "
    "2A1C7F1C2A 08083E0808 0050300000 0808080808 0060600000 2010080402 "
    "3E5149453E 00427F4000 4261514946 2141454B31 1814127F10 2745454539 3C4A494930 0171090503 3649494936 064949291E "
    "0036360000 0056360000 0814224100 1414141414 0041221408 0201510906 324979413E "
    "7E1111117E 7F49494936 3E41414122 7F4141221C 7F49494941 7F09090901 3E4149497A 7F0808087F 00417F4100 2040413F01 "
    "7F08142241 7F40404040 7F020C027F 7F0408107F 3E4141413E 7F09090906 3E4151215E 7F09192946 4649494931 01017F0101 "
    "3F4040403F 1F2040201F 3F4038403F 6314081463 0708700807 6151494543 "
    "007F414100 0204081020 0041417F00 0402010204 4040404040 0001020400 "
    "2054545478 7F48444438 3844444420 384444487F 3854545418 087E090102 081454543C 7F08040478 00447D4000 2040443D00 "
    "7F10284400 00417F4000 7C04180478 7C08040478 3844444438 7C14141408 081414187C 7C08040408 4854545420 043F444020 "
    "3C4040207C 1C2040201C 3C4030403C 4428102844 0C5050503C 4464544C44 "
    "0008364100 00007F0000 0041360800 0804081008"
).split()
assert len(_TABLE) == 95
GLYPHS = {chr(32 + i): np.asarray([int(h[k:k + 2], 16) for k in range(0, 10, 2)], dtype=np.uint8) for i, h in enumerate(_TABLE)}
ADVANCE = 6
LINE = 9


def text_width(s: str, scale: int = 1) -> int:
    return max(0, len(s) * ADVANCE - 1) * scale


def draw_text(img: np.ndarray, x: int, y: int, s: str, color: int, scale: int = 1) -> tuple[int, int, int, int]:
    """Draw `s` into the uint8 index image (unknown characters become '?'); returns its rectangle (x, y, w, h)."""
    H, W = img.shape
    for i, ch in enumerate(s):
        cols = GLYPHS.get(ch, GLYPHS["?"])
        for cx in range(5):
            col = int(cols[cx])
            for ry in range(7):
                if (col >> ry) & 1:
                    px = x + (i * ADVANCE + cx) * scale
                    py = y + ry * scale
                    if 0 <= px < W and 0 <= py < H:
                        img[py:min(py + scale, H), px:min(px + scale, W)] = color
    return (x, y, text_width(s, scale), 7 * scale)
