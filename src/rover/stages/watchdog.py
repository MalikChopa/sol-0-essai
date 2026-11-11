"""Safe mode (SPEC 5.4): corrective actions decided at the start of the next sol. Every action is reported."""
from __future__ import annotations

import copy

from rover.config import Params


def safe_mode(rover: dict, last: dict, params: Params) -> tuple[dict, list]:
    r = copy.deepcopy(rover)
    E = params.get("rover.energy")
    actions = []
    if last["stuck"]:
        r["stuck"] = False
        r["sink_n"] = 0
        r["rev_n"] = 0
        r["x"] = r["x"] - r["c"]
        r["y"] = r["y"] - r["s"]
        actions.append("freed")
    if last["tipped"]:
        r["tipped"] = False
        r["battery"] = max(0.0, r["battery"] - E["tip_cost"])
        actions.append("righted")
    # Decision J0 (to confirm by J2): "battery below cutoff during the whole sol" = min and final battery both <= cutoff
    if last["battery_min"] <= E["cutoff"] and r["battery"] <= E["cutoff"]:
        r["battery"] = E["safe_recharge"]
        actions.append("recharged")
    if last["low_awake_streak"] >= params.get("stages.no_progress_sols"):
        actions.append("noise_doubled")
    return r, actions
