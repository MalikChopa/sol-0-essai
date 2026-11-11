"""BRAIN panel (SPEC 7.4, ARCH 7): every node, bar and connection comes from the recorded FrameRecord and the
episode weights of the BrainSnapshot. Connection brightness = contribution |W_ij * a_i| / maximum of the layer over the sol."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core import consts
from rover.core.exact import to_int
from rover.core.mlp_layout import unpack_mlp
from rover.core.types import FrameRecord, Trace
from rover.render import draw, font
from rover.render.palette import BG, NEG, MARK, hud

PX, PY, PW, PH = 336, 24, 296, 200
COL_IN, COL_H, COL_MID, COL_OUT = 360, 440, 510, 590
ZY0, ZH = 56, 110
N_H, N_OUT = 16, 2
UNLOCK = {0: 0, 1: 1, 2: 1, 3: 3, 4: 4, 5: 5}      # module -> first stage (M0 always; M6-M8 never in P1/P2)


def module_active(m: int, stage: int) -> bool:
    return {0: 0, 1: 1, 2: 1, 3: 3, 4: 4, 5: 5}.get(m, 99) <= stage


def _label(img: np.ndarray, x: int, y: int, text: str, color: int) -> None:
    """Module label on a BG box, so connection lines never run through the text."""
    draw.rect(img, x - 1, y - 1, font.text_width(text) + 2, 9, BG)
    font.draw_text(img, x, y, text, color, 1)


def _level(a: float) -> int:
    return 1 + to_int(np.floor(9.0 * min(1.0, abs(float(a))) + 0.5))


class BrainView:
    def __init__(self, trace: Trace, params: Params):
        self.stage = trace.stage
        self.active = list(consts.M0_ACTIVE[trace.stage])
        n_in = consts.M0_N_IN
        self.W1, self.b1, self.W2, self.b2 = unpack_mlp(np.asarray(trace.snapshot.m0, dtype=np.float64), n_in, N_H, N_OUT)
        X = np.stack([f.x for f in trace.frames]).astype(np.float64)
        H = np.stack([f.h for f in trace.frames]).astype(np.float64)
        self.max1 = max(float(np.max(np.abs(X[:, :, None] * self.W1[None])[:, self.active, :])), 1e-12)
        self.max2 = max(float(np.max(np.abs(H[:, :, None] * self.W2[None]))), 1e-12)
        m1 = [np.abs(f.m1_pred) for f in trace.frames if f.m1_pred is not None] + [np.abs(f.m1_meas) for f in trace.frames if f.m1_meas is not None]
        self.m1max = max(float(np.max(np.stack(m1))) if m1 else 0.0, 1e-12)
        self.top1 = int(params.get("render.brain_top_l1"))
        self.top2 = int(params.get("render.brain_top_l2"))
        self.thick = float(params.get("render.thick_frac"))
        n = len(self.active)
        self.pitch_in = min(10, ZH // n)
        y0 = ZY0 + (ZH - self.pitch_in * n) // 2 + self.pitch_in // 2
        self.in_y = {i: y0 + k * self.pitch_in for k, i in enumerate(self.active)}
        yh = ZY0 + (ZH - 6 * N_H) // 2 + 3
        self.h_y = [yh + 6 * j for j in range(N_H)]
        self.out_y = [ZY0 + (ZH * (k + 1)) // (N_OUT + 1) for k in range(N_OUT)]

    # connections actually drawn for a frame: (x0, y0, x1, y1, fraction, negative)
    def connections(self, fr: FrameRecord) -> list:
        x = np.asarray(fr.x, dtype=np.float64)
        h = np.asarray(fr.h, dtype=np.float64)
        out = []
        c1 = x[:, None] * self.W1                                   # (24, 16), signed contribution
        mask = np.zeros(c1.shape, dtype=bool)
        mask[self.active, :] = True
        score = np.where(mask, np.abs(c1), -1.0).ravel()
        order = np.argsort(-score, kind="stable")[:self.top1]
        for k in order.tolist():
            i, j = divmod(k, N_H)
            if score[k] <= 0.0:
                continue
            out.append((COL_IN, self.in_y[i], COL_H, self.h_y[j], float(score[k]) / self.max1, bool(c1[i, j] < 0.0)))
        c2 = h[:, None] * self.W2
        for j in range(N_H):
            for k in range(N_OUT):
                a = abs(float(c2[j, k]))
                if a > 0.0:
                    out.append((COL_H, self.h_y[j], COL_OUT, self.out_y[k], a / self.max2, bool(c2[j, k] < 0.0)))
        return out

    def _node(self, img, cx, cy, r, a):
        if a < 0:
            draw.disc(img, cx, cy, r, 48)
            draw.ring(img, cx, cy, r, NEG)
        else:
            draw.disc(img, cx, cy, r, hud(_level(a)))

    def draw(self, img: np.ndarray, fr: FrameRecord, stage: int) -> None:
        draw.frame_rect(img, PX, PY, PW, PH, hud(4))
        font.draw_text(img, PX + 4, PY + 4, "BRAIN | LIVE ACTIVATIONS", hud(10), 1)
        asleep = fr.mode == "SLEEP"
        # M2 block
        if module_active(2, stage) and fr.z is not None:
            for k in range(40):
                v = min(1.0, max(0.0, float(fr.z[k])))
                hh = to_int(np.floor(v * 12.0 + 0.5))
                draw.rect(img, 340 + 3 * k, 50 - hh, 2, hh, hud(7))
            font.draw_text(img, 464, 40, "M2", hud(10), 1)
        else:
            draw.frame_rect(img, 340, 38, 120, 12, hud(3))
            font.draw_text(img, 380, 40, "???", hud(3), 1)
        # connections first (behind nodes)
        for (x0, y0, x1, y1, fr_c, neg) in self.connections(fr):
            lvl = hud(1 + to_int(np.floor(9.0 * min(1.0, fr_c) + 0.5)))
            draw.line(img, x0, y0, x1, y1, NEG if neg else lvl, dotted=neg, thick=2 if fr_c > self.thick else 1)
        for i in self.active:
            self._node(img, COL_IN, self.in_y[i], 2, float(fr.x[i]))
        for j in range(N_H):
            self._node(img, COL_H, self.h_y[j], 3, float(fr.h[j]))
        for k in range(N_OUT):
            self._node(img, COL_OUT, self.out_y[k], 4, float(fr.y[k]))
            font.draw_text(img, COL_OUT + 8, self.out_y[k] - 3, "LR"[k], hud(10), 1)
        # M1 block: predicted (HUD 7) and measured (MARK) displacement of the last segment
        if module_active(1, stage) and fr.m1_pred is not None:
            for k in range(3):
                for row, (arr, col) in enumerate(((fr.m1_pred, hud(7)), (fr.m1_meas, MARK))):
                    v = float(arr[k]) / self.m1max
                    n = to_int(np.floor(min(1.0, abs(v)) * 22.0 + 0.5))
                    xs = COL_MID if v >= 0 else COL_MID - n
                    draw.rect(img, xs, 62 + 12 * k + 4 * row, max(1, n), 3, col)
                draw.rect(img, COL_MID, 60 + 12 * k, 1, 11, hud(4))
            _label(img, 496, 52, "M1", hud(10))
        else:
            draw.rect(img, 484, 58, 52, 42, BG)
            draw.frame_rect(img, 484, 58, 52, 42, hud(3))
            font.draw_text(img, 498, 76, "???", hud(3), 1)
        # M3 block
        if module_active(3, stage) and fr.m3_out is not None:
            for k in range(3):
                self._node(img, COL_MID, 124 + 14 * k, 3, float(fr.m3_out[k]))
            _label(img, 496, 110, "M3", hud(10))
        else:
            draw.rect(img, 484, 106, 52, 52, BG)
            draw.frame_rect(img, 484, 106, 52, 52, hud(3))
            font.draw_text(img, 498, 130, "???", hud(3), 1)
        # commands really sent, exploration noise
        txt = "L %+.2f R %+.2f" % (float(fr.u[0]), float(fr.u[1]))
        font.draw_text(img, PX + PW - 4 - font.text_width(txt), 172, txt, hud(10), 1)
        xi = np.abs(np.asarray(fr.xi, dtype=np.float64))
        if float(np.max(xi)) > 0.0:
            font.draw_text(img, 540, 181, "XI", hud(10), 1)
            for k in range(2):
                n = to_int(np.floor(min(1.0, float(xi[k])) * 30.0 + 0.5))
                draw.rect(img, 556 + 36 * k, 182, max(1, n), 4, hud(7))
        label = "INTENT: " + consts.MODE_LABELS[fr.mode]
        font.draw_text(img, 340, 190, label, hud(10), 1)
        if asleep:
            font.draw_text(img, 340, 172, "ASLEEP", MARK, 1)
        for m in range(9):
            on = module_active(m, stage)
            bx = 340 + 32 * m
            draw.frame_rect(img, bx, 200, 30, 18, hud(10) if on else hud(3))
            font.draw_text(img, bx + 6 if on else bx + 6, 205, "M%d" % m if on else "???", hud(10) if on else hud(3), 1)
