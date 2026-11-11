"""GIF encoding: size ladder of ARCH 8 / SPEC 7.7 and the photosensitivity level LP (never touches noise or palette)."""
from __future__ import annotations

import io

from PIL import Image

from rover.config import Params
from rover.core.types import Progress, Trace
from rover.render import photosens
from rover.render.console import build_console
from rover.render.palette import PALETTE
from rover.state.explored import Explored


def _palette_bytes(palette=None) -> list:
    flat = [c for rgb in (PALETTE if palette is None else palette) for c in rgb]
    return flat + [0] * (768 - len(flat))


def encode_frames(frames: list, durations_ms: list, palette=None) -> bytes:
    pal = _palette_bytes(palette)
    ims = []
    for f in frames:
        im = Image.frombytes("P", (f.shape[1], f.shape[0]), f.tobytes())
        im.putpalette(pal)
        ims.append(im)
    buf = io.BytesIO()
    ims[0].save(buf, format="GIF", save_all=True, append_images=ims[1:], duration=list(durations_ms), loop=0, optimize=True,
                disposal=1)
    return buf.getvalue()


def ladder_levels(params: Params) -> list:
    return [tuple(x) for x in params.get("render.ladder")] + [tuple(params.get("render.ladder_last"))]


def encode_gif_report(trace: Trace, state: dict, explored_start: Explored, terrain, progress: Progress, now_utc: str,
                      params: Params, force_lp: bool = False) -> dict:
    """Full result: bytes, level, size per level tried, photosensitivity figures. Frames are rendered once and reused."""
    limit = int(params.get("render.gif_max_bytes"))
    cache: dict = {}
    sizes = {}
    chosen = None
    if not force_lp:
        for lvl, (n, ms, scan) in enumerate(ladder_levels(params)):
            cf = build_console(trace, state, explored_start, terrain, progress, now_utc, params, scanlines=bool(scan),
                               n_frames=int(n), durations_ms=int(ms), cache=cache)
            data = encode_frames(cf.frames, cf.durations_ms)
            sizes["L%d" % lvl] = len(data)
            chosen = (data, "L%d" % lvl, cf)
            if len(data) <= limit:
                break
    worst = None
    if chosen is not None:
        worst = photosens.transitions(chosen[2].frames, chosen[2].durations_ms)[0]
    if chosen is None or worst > 3:
        n, ms, scan = params.get("render.photosafe")
        cf = build_console(trace, state, explored_start, terrain, progress, now_utc, params, scanlines=bool(scan),
                           n_frames=int(n), durations_ms=int(ms), cache=cache)
        data = encode_frames(cf.frames, cf.durations_ms)
        sizes["LP"] = len(data)
        lp_worst = photosens.transitions(cf.frames, cf.durations_ms)[0]
        return {"data": data, "level": "LP", "sizes": sizes, "worst_transitions": lp_worst, "before_lp": worst,
                "oversize": len(data) > limit}
    return {"data": chosen[0], "level": chosen[1], "sizes": sizes, "worst_transitions": worst, "before_lp": None,
            "oversize": len(chosen[0]) > limit}


def encode_gif(trace: Trace, state: dict, explored_start: Explored, terrain, progress: Progress, now_utc: str,
               params: Params) -> tuple:
    r = encode_gif_report(trace, state, explored_start, terrain, progress, now_utc, params)
    return r["data"], r["level"]
