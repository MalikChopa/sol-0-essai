"""GIF size matrix on fictitious traces (day / night / storm x 4 acuities) after the ladder, the palette-128 + 6 vignette steps
variant (for the pending vignette decision, ARCH 12) and the contact sheet of the 4 stages.

Run from the project root:  PYTHONPATH=src .venv/bin/python tools/render/gif_matrix.py --out out/j3
Exit code 1 if any GIF exceeds gif_max_bytes after the ladder.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_trace import make_progress, make_state, make_trace, terrain          # noqa: E402

from rover import config                                                           # noqa: E402
from rover.render import PALETTE, build_console, map_png, photosens, status_svg    # noqa: E402
from rover.render.cam_view import CAM_H, CAM_W, CAM_X, CAM_Y                       # noqa: E402
from rover.render.gif import _palette_bytes, encode_frames, encode_gif_report      # noqa: E402
from rover.render.vignettes import radial_steps                                    # noqa: E402
from rover.state import Explored                                                   # noqa: E402

NOW = "2026-11-11T07:17:00Z"
ACUITIES = ((8, 6), (32, 20), (80, 50), (160, 100))
FAMILIES = (48, 52, 54, 55, 57, 58, 61, 62, 63, 51)       # BG, HUD1, HUD3, HUD4, HUD6, HUD7, HUD10, NEG, MARK, REC
STEPS = (300, 450, 600, 750, 900, 1050)


def _mark(ex, x0, x1, y0, y1) -> None:
    xs, ys = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    ex.mark(xs.ravel(), ys.ravel(), 1)


def palette128() -> list:
    """64 base colours + 6 vignette steps x 10 families (darkened by 7.5 % per step) + 4 black pads = 128."""
    extra = []
    for s in range(1, 7):
        f = 1000 - 75 * s
        for fam in FAMILIES:
            r, g, b = PALETTE[fam]
            extra.append((r * f // 1000, g * f // 1000, b * f // 1000))
    return list(PALETTE) + extra + [(0, 0, 0)] * 4


def vignette128(frame: np.ndarray, local_map_rect: tuple) -> np.ndarray:
    """Re-vignette a console frame (HUD / background pixels only, never the CAM-1 zone nor the local map) with 6 steps."""
    out = frame.copy()
    # undo the 2-step vignette of the 64 palette: indices 49 and 50 are background
    out = np.where((out == 49) | (out == 50), 48, out)
    st = radial_steps(360, 640, STEPS)
    fam_of = np.zeros(64, dtype=np.int64) - 1
    for p in range(48, 64):
        d = [sum((PALETTE[p][c] - PALETTE[f][c]) ** 2 for c in range(3)) for f in FAMILIES]
        fam_of[p] = int(np.argmin(d))
    protect = np.zeros(out.shape, dtype=bool)
    protect[CAM_Y - 1:CAM_Y + CAM_H + 1, CAM_X - 1:CAM_X + CAM_W + 1] = True
    x, y, w, h = local_map_rect
    protect[y:y + h, x:x + w] = True
    sel = (~protect) & (out >= 48) & (st >= 1)
    fam = fam_of[out[sel]]
    out[sel] = 64 + (st[sel] - 1) * 10 + fam
    return out


def run_matrix(params, out: Path) -> tuple:
    rows, worst_ok = [], True
    limit = params.get("render.gif_max_bytes")
    for cond in ("day", "night", "storm", "stress"):
        for (w, h) in ACUITIES:
            stage = {8: 0, 32: 2, 80: 3, 160: 4}[w]
            tr = make_trace(stage, cond, acuity=(w, h))
            t = time.time()
            r = encode_gif_report(tr, make_state(tr), Explored(), terrain, make_progress(stage), NOW, params)
            dt = time.time() - t
            worst_ok &= len(r["data"]) <= limit
            rows.append((cond, "%dx%d" % (w, h), r["level"], r["sizes"].get("L0", 0), len(r["data"]), r["worst_transitions"],
                         dt))
    return rows, worst_ok


def run_variant(params) -> list:
    rows = []
    pal128 = palette128()
    for cond in ("day", "night", "storm"):
        for (w, h) in ACUITIES:
            stage = {8: 0, 32: 2, 80: 3, 160: 4}[w]
            tr = make_trace(stage, cond, acuity=(w, h))
            cf = build_console(tr, make_state(tr), Explored(), terrain, make_progress(stage), NOW, params)
            a = encode_frames(cf.frames, cf.durations_ms)
            fr128 = [vignette128(f, (8, 232, 120, 120)) for f in cf.frames]
            b = encode_frames(fr128, cf.durations_ms, pal128)
            rows.append((cond, "%dx%d" % (w, h), len(a), len(b)))
    return rows


def contact_sheet(params, out: Path) -> None:
    tiles = []
    for stage in (0, 1, 2, 3):
        tr = make_trace(stage, "day", seed=3)
        st = make_state(tr)
        ex = Explored()
        _mark(ex, -20, 20, -5, 5)
        cf = build_console(tr, st, ex, terrain, make_progress(stage), NOW, params, n_frames=75)
        k = 44
        im = Image.frombytes("P", (640, 360), cf.frames[k].tobytes())
        im.putpalette(_palette_bytes())
        im.resize((1280, 720), Image.NEAREST).save(out / ("console_stage%d.png" % stage))
        tiles.append(im.convert("RGB"))
        if stage == 2:                                               # vignette variant, same frame
            v = vignette128(cf.frames[k], (8, 232, 120, 120))
            iv = Image.frombytes("P", (640, 360), v.tobytes())
            iv.putpalette([c for rgb in palette128() for c in rgb])
            iv.resize((1280, 720), Image.NEAREST).save(out / "console_stage2_palette128.png")
        if stage == 3:
            (out / "status.svg").write_text(status_svg({"sol": tr.sol, "stage": {"id": 3, "consolidation": False}},
                                                       make_progress(3), NOW, params))
    sheet = Image.new("RGB", (1280, 720))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 2) * 640, (i // 2) * 360))
    sheet.save(out / "contact_sheet.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/j3")
    ap.add_argument("--no-variant", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    params = config.load(Path("config"))
    rows, ok = run_matrix(params, out)
    lines = ["| condition | acuity | level | L0 bytes | final bytes | max transitions/s | time (s) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %d | %d | %d | %.2f |" % r)
    if not a.no_variant:
        lines += ["", "| condition | acuity | palette 64 (L0, bytes) | palette 128 + 6 vignette steps (bytes) | delta |", "|---|---|---|---|---|"]
        for (c, ac, x, y) in run_variant(params):
            lines.append("| %s | %s | %d | %d | %+.1f %% |" % (c, ac, x, y, 100.0 * (y - x) / x))
    contact_sheet(params, out)
    tr = make_trace(3, "day", seed=3)
    ex = Explored()
    _mark(ex, -90, 130, -70, 90)
    (out / "map.png").write_bytes(map_png(make_state(tr), ex, terrain, tr, params))
    (out / "gif_matrix.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("ALL <= gif_max_bytes:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
