"""Global 64-entry palette (SPEC 7.1). Indices 0-23 are the camera sensor colours; 24-47 their scanline twins."""
from __future__ import annotations


def _hex(s: str) -> tuple[int, int, int]:
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))


_SENSOR = (
    "#1c0d08 #401c0f #652b16 #8a3b1e #a65a38 #c27a52 "
    "#2a140a #643b1f #9e6434 #d98c4a #e49f62 #f0b27a "
    "#33201a #72563f #b28c65 #f2c38b #f7d3a5 #fde3c0 "
    "#e39a68 #d8854f #c9673a #a8522e #050302 #1c100b"
).split()
_HUD = "#291c10 #412d16 #593e1c #704e22 #885f28 #a0702e #b78034 #cf913a #e7a240 #ffb347".split()
_OTHER = "#120c0a #0e0908 #0b0706 #ff4d4d".split()   # BG, BG scan, BG vignette, REC

_base = [_hex(h) for h in _SENSOR]
PALETTE: list[tuple[int, int, int]] = (
    _base
    + [(r * 82 // 100, g * 82 // 100, b * 82 // 100) for (r, g, b) in _base]
    + [_hex(h) for h in _OTHER]
    + [_hex(h) for h in _HUD]
    + [_hex("#78aaff"), _hex("#e6e6e6")]
)
assert len(PALETTE) == 64

BG, BG_SCAN, BG_VIG, REC = 48, 49, 50, 51
HUD0 = 51            # HUD level n (1..10) = HUD0 + n
NEG, MARK = 62, 63
TWIN = 24            # scanline twin offset


def hud(level: int) -> int:
    return HUD0 + max(1, min(10, level))


def palette_hex() -> list[str]:
    return ["#%02x%02x%02x" % c for c in PALETTE]
