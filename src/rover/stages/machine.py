"""Stage machine (SPEC 5): criteria, minimum durations, recalibration, version lock, progress."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from rover.config import Params
from rover.core.exact import isum_py
from rover.core.types import Progress


@dataclass(frozen=True)
class StageDecision:
    stage: dict
    advanced: bool
    recalibrated: bool
    consolidation_started: bool


def _cfg(params: Params, sid: int) -> dict:
    return params.get("stages.stage")[sid]


def _threshold(stage: dict, params: Params):
    cfg = _cfg(params, stage["id"])
    t = cfg["threshold"] * stage["threshold_scale"]
    return t if stage["id"] == 1 else math.floor(t + 1e-9)       # counts are rounded down, R2 stays a float


def _streak(values: list, thr: float) -> int:
    n = 0
    for v in reversed(values):
        if v >= thr:
            n += 1
        else:
            break
    return n


def _status(stage: dict, metrics: dict, params: Params) -> dict:
    """value, fraction (0-1, uncapped), met, blocking and the display text of the current criterion."""
    sid = stage["id"]
    thr = _threshold(stage, params)
    if sid == 0:
        v = metrics["couples"]
        return dict(met=v >= thr, frac=v / thr, block="metric", text=f"{v}/{thr} command-effect pairs")
    if sid == 1:
        r2 = metrics["r2"][-1] if metrics["r2"] else 0.0
        st = _streak(metrics["r2"], thr)
        frac = min(max(r2, 0.0) / thr, st / 3.0)
        return dict(met=st >= 3, frac=frac, block="streak" if r2 >= thr else "metric",
                    text=f"R2 {r2:.2f} / {thr:.2f} | stable {st}/3 sols")
    if sid == 2:
        v = metrics["battery"][-1] if (metrics["battery"] and metrics["battery_stage"][-1] == 2) else 0
        return dict(met=v >= thr, frac=v / thr, block="metric", text=f"{v}/20 test courses (need {thr})")
    if sid == 3:
        v = metrics["no_breakdown_streak"]
        return dict(met=v >= thr, frac=v / thr, block="streak", text=f"{v}/{thr} sols without breakdown")
    if sid == 4:
        v = isum_py(metrics["novel"][-20:])
        return dict(met=v >= thr, frac=v / thr, block="metric", text=f"{v}/{thr} novel samples (last 20)")
    a = metrics["ari"][-1] if metrics["ari"] else 0.0
    v = metrics["ari_stable"]
    return dict(met=v >= thr, frac=v / thr, block="streak", text=f"ARI {a:.2f} | {v}/{thr} stable sols")


def step_stage(stage: dict, metrics: dict, sol: int, max_stage: int, params: Params) -> StageDecision:
    s = copy.deepcopy(stage)
    s["sols_in_stage"] += 1
    cfg = _cfg(params, s["id"])
    met = _status(s, metrics, params)["met"]
    advanced = recal = started = False
    if met and s["sols_in_stage"] >= cfg["min"]:
        if s["id"] < max_stage:
            s.update(id=s["id"] + 1, entered_sol=sol, sols_in_stage=0, threshold_scale=1.0, recalibrations=0,
                     consolidation=False)
            s["history"] = s["history"] + [[s["id"], sol]]
            advanced = True
        elif not s["consolidation"]:
            s["consolidation"] = True
            started = True
    elif not met:
        f = params.get("stages.recal_factor")
        if s["recalibrations"] == 0 and s["sols_in_stage"] >= 3 * cfg["target"]:
            s["threshold_scale"] *= f
            s["recalibrations"] = 1
            recal = True
        elif s["recalibrations"] == 1 and s["sols_in_stage"] >= params.get("stages.recal_second") * cfg["target"]:
            s["threshold_scale"] *= f
            s["recalibrations"] = 2
            recal = True
    return StageDecision(stage=s, advanced=advanced, recalibrated=recal, consolidation_started=started)


def progress(stage: dict, metrics: dict, params: Params) -> Progress:
    cfg = _cfg(params, stage["id"])
    st = _status(stage, metrics, params)
    frac = min(max(st["frac"], 0.0), 1.0)
    text = st["text"]
    block = st["block"]
    if stage["consolidation"]:
        return Progress(1.0, cfg["name"], text, "none")
    if st["met"] and stage["sols_in_stage"] < cfg["min"]:
        frac = min(frac, 0.99)
        text = text + f" | min duration {stage['sols_in_stage']}/{cfg['min']} sols"
        block = "min_duration"
    else:
        frac = min(frac, 0.99)
    return Progress(frac, cfg["name"], text, block)
