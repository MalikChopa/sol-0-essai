"""status.svg 640x120 (SPEC 7.5). Every number comes from the state and the measured progress."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.exact import to_int
from rover.core.types import Progress

_CAPS = ("move", "drive", "energy", "sample", "analyze", "ecology", "curiosity")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def status_svg(state: dict, progress: Progress, now_utc: str, params: Params) -> str:
    sid = state["stage"]["id"]
    pct = to_int(np.floor(progress.fraction * 100.0 + 1e-9))
    head = "STAGE %d | %s" % (sid, progress.label_en)
    if state["stage"]["consolidation"]:
        head = "CONSOLIDATION | AWAITING FIRMWARE UPDATE"
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120" viewBox="0 0 640 120" role="img" '
           'aria-label="Sol-0 status: sol %d, stage %d, progress %d percent" font-family="ui-monospace, Menlo, Consolas, monospace">'
           % (state["sol"], sid, pct),
           '<rect x="0.5" y="0.5" width="639" height="119" fill="#120c0a" stroke="#412d16"/>',
           '<text x="16" y="32" font-size="22" fill="#ffb347">SOL %d</text>' % state["sol"],
           '<text x="16" y="54" font-size="13" fill="#ffb347">%s</text>' % _esc(head),
           '<rect x="16" y="66" width="300" height="12" fill="#291c10" stroke="#704e22"/>',
           '<rect x="16" y="66" width="%d" height="12" fill="#ffb347"/>' % to_int(np.floor(progress.fraction * 300.0))]
    out.append('<text x="16" y="96" font-size="12" fill="#ffb347">%d %% | %s</text>' % (pct, _esc(progress.value_text_en)))
    for i, name in enumerate(_CAPS):
        x, y = 350 + (i % 4) * 72, 30 + (i // 4) * 34
        out.append('<rect x="%d" y="%d" width="66" height="22" fill="none" stroke="#704e22"/>' % (x, y))
        cx, cy = x + 10, y + 11
        if sid > i:        # acquired: check mark
            out.append('<path d="M%d %dl3 3l6 -7" fill="none" stroke="#ffb347" stroke-width="2"/>' % (cx - 5, cy))
        elif sid == i:     # in progress: half disc
            out.append('<path d="M%d %dA5 5 0 0 1 %d %dz" fill="#ffb347"/>' % (cx - 5, cy, cx + 5, cy))
        else:              # locked: dot
            out.append('<circle cx="%d" cy="%d" r="2" fill="#593e1c"/>' % (cx, cy))
        out.append('<text x="%d" y="%d" font-size="12" fill="#ffb347">%s</text>' % (x + 20, y + 15, name))
    out.append('<text x="628" y="112" font-size="12" fill="#ffb347" text-anchor="end">last contact %s %s UTC | 4 sols/day</text>'
               % (now_utc[:10], now_utc[11:16]))
    out.append("</svg>")
    return "\n".join(out) + "\n"
