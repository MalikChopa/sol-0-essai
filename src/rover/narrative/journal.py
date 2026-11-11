"""Journal entry, firsts and names, composed from real facts only (SPEC 8, EF-92 to EF-97)."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.exact import to_int
from rover.core.rng import derive, randint
from rover.core.types import JournalEntry
from rover.narrative.templates import fill, holds, pick

_ON = ("t", "k", "v", "r", "s", "m", "n", "d", "l", "z")
_VOW = ("a", "e", "i", "o", "u")
_CODA = ("n", "r", "s", "l", "")

MAX_CHARS = 600
MAX_EXTRAS = 3
TONE_STAGE_MAX = 5          # stages above 5 use the stage-5 tone

# derived marker -> facts it is computed from (params-only markers have an empty tuple)
DERIVED = {
    "battery_pct": ("battery_min",), "battery_clock": ("battery_min_hour",), "battery_n": (),
    "storm_view_pct": (), "tip_cost_pct": (), "safe_recharge_pct": (), "cutoff_pct": (),
    "no_progress_sols": (), "no_progress_cells": (), "new_name": ("new_names",),
    "truncated_module": ("truncated_at",), "truncated_gen": ("truncated_at",),
    "redone_n": ("redone_sols",), "redone_first": ("redone_sols",), "redone_last": ("redone_sols",),
    "restored_sol": ("redone_sols",),
}


def _pct(x: float) -> int:
    return to_int(100.0 * x + 0.5)            # round half up (x in [0, 1])


def derived_markers(facts: dict, params: Params) -> dict:
    d: dict = {}
    bm = facts.get("battery_min")
    if bm is not None:
        d["battery_pct"] = _pct(bm)
    h = facts.get("battery_min_hour")
    if h is not None:
        m = to_int(h * 60.0)
        d["battery_clock"] = "%02d:%02d" % ((m // 60) % 24, m % 60)
    d["battery_n"] = int(params.get("brain.battery.courses"))
    d["storm_view_pct"] = _pct(1.0 - params.get("events.storm_view"))
    en = params.get("rover.energy")
    d["tip_cost_pct"] = _pct(en["tip_cost"])
    d["safe_recharge_pct"] = _pct(en["safe_recharge"])
    d["cutoff_pct"] = _pct(en["cutoff"])
    d["no_progress_sols"] = int(params.get("stages.no_progress_sols"))
    d["no_progress_cells"] = int(params.get("stages.no_progress_cells"))
    names = facts.get("new_names")
    if names:
        d["new_name"] = names[-1]
    t = facts.get("truncated_at")
    if t:
        d["truncated_module"] = t["module"]
        d["truncated_gen"] = int(t["gen"])
    redone = facts.get("redone_sols")
    if redone:
        d["redone_n"] = len(redone)
        d["redone_first"] = int(min(redone))
        d["redone_last"] = int(max(redone))
        d["restored_sol"] = int(min(redone)) - 1
    return d


def lines(params: Params) -> list:
    return params.get("narrative.journal")["line"]


def _applies(line: dict, facts: dict) -> bool:
    if any(facts.get(k) is None for k in line.get("needs", ())):
        return False
    return all(holds(c, facts) for c in line.get("when", ()))


def _stage_ok(line: dict, stage: int) -> bool:
    st = line.get("stage")
    return st is None or min(stage, TONE_STAGE_MAX) in st


def _render(line: dict, facts: dict, seed: int, sol: int, words: dict) -> tuple:
    fr = fill(pick(line["fr"], seed, sol, line["id"]), facts, "fr", words)
    en = fill(pick(line["en"], seed, sol, line["id"]), facts, "en", words)
    return fr, en


def select(facts: dict, state: dict, params: Params) -> list:
    """Ids of the lines composing the entry, in order (summary, learn, extras), before the length trim."""
    f = dict(facts)
    f.update(derived_markers(facts, params))
    stage = int(f["stage"])
    chosen = []
    for slot in ("summary", "learn"):
        for ln in lines(params):
            if ln["slot"] == slot and _stage_ok(ln, stage) and _applies(ln, f):
                chosen.append(ln)
                break
    extras = [ln for ln in lines(params) if ln["slot"] == "extra" and _applies(ln, f)]
    gone = {r for ln in extras for r in ln.get("replaces", ())}
    extras = [ln for ln in extras if ln["id"] not in gone]
    extras = _lock_filter(extras, f, state, params)
    order = {ln["id"]: i for i, ln in enumerate(lines(params))}
    extras = sorted(extras, key=lambda ln: (ln["prio"], order[ln["id"]]))
    return chosen + extras[:MAX_EXTRAS]


def _lock_filter(extras: list, f: dict, state: dict, params: Params) -> list:
    """Firmware-lock line: the first time, then every `stages.consolidation_reminder` sols (SPEC 5.4)."""
    out = []
    every = int(params.get("stages.consolidation_reminder"))
    for ln in extras:
        if ln["id"] == "lock":
            text = ln["fr"][0]
            seen = any(text in e.get("fr", "") for e in state.get("journal_tail", ()))
            if seen and int(f["sol"]) % every != 0:
                continue
        out.append(ln)
    return out


def compose_entry(facts: dict, state: dict, params: Params) -> JournalEntry:
    f = dict(facts)
    f.update(derived_markers(facts, params))
    seed, sol = int(state["world_seed"]), int(facts["sol"])
    words = params.get("narrative.words")
    chosen = select(facts, state, params)
    core = [ln for ln in chosen if ln["slot"] != "extra"]
    extras = [ln for ln in chosen if ln["slot"] == "extra"]
    while True:
        parts = [_render(ln, f, seed, sol, words) for ln in core + extras]
        fr = " ".join(p[0] for p in parts)
        en = " ".join(p[1] for p in parts)
        if (len(fr) <= MAX_CHARS and len(en) <= MAX_CHARS) or not extras:
            break
        extras.pop()
    return JournalEntry(epoch=int(state["epoch"]), sol=sol, utc=facts["utc"], fr=fr, en=en)


def detect_firsts(facts: dict, state: dict) -> list:
    """(id, sol) of the firsts reached by these facts and not yet in state["firsts"] (SPEC 8.5)."""
    cand = []
    if facts.get("awake_cells", 0) >= 1:
        cand.append("first.move")
    if facts.get("advanced_to") is not None:
        cand.append("first.stage.%d" % facts["advanced_to"])
        if facts["advanced_to"] == 1:
            cand.append("first.image")
    if facts.get("targets_reached", 0) >= 1:
        cand.append("first.target")
    if "storm" in facts.get("events", []):
        cand.append("first.storm")
    if facts.get("breakdowns", 0) >= 1:
        cand.append("first.breakdown")
    if facts.get("night_drive_ticks", 0) >= 1:
        cand.append("first.night_drive")
    if facts.get("stuck") or facts.get("freed_by"):
        cand.append("first.stuck")
    if (facts.get("samples") or 0) >= 1:
        cand.append("first.sample")
    if (facts.get("spectra") or 0) >= 1:
        cand.append("first.spectrum")
    if (facts.get("new_categories") or 0) >= 1:
        cand.append("first.category")
    if facts.get("anomaly_seen"):
        cand.append("first.anomaly")
    return [(c, int(facts["sol"])) for c in cand if c not in state["firsts"]]


def make_name(seed: int, kind: str, sol: int, taken: set) -> str:
    """Deterministic ASCII name, 2-3 syllables (SPEC 8.4), free in `taken`."""
    for attempt in range(1000):
        key = derive(seed, "name", kind, sol, attempt)
        n_syl = 2 + int(randint(key, np.asarray(0), 2))
        s = ""
        for i in range(n_syl):
            s += _ON[int(randint(key, np.asarray(1 + 3 * i), len(_ON)))]
            s += _VOW[int(randint(key, np.asarray(2 + 3 * i), len(_VOW)))]
            if i == n_syl - 1:
                s += _CODA[int(randint(key, np.asarray(3 + 3 * i), len(_CODA)))]
        s = s.capitalize()
        if s not in taken:
            return s
    raise RuntimeError("no free name")
