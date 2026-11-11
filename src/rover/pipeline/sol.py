"""Orchestration of one sol (ARCH 4): attempts k = 0..3, fresh state, writes to main."""
from __future__ import annotations

import copy
import math
import platform
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np

from rover import version
from rover.brain.battery import append_measure, evaluate_regression, run_battery
from rover.brain.brain import Brain
from rover.config import Params
from rover.core import consts
from rover.core.exact import isum_py
from rover.core.hashing import canonical_json
from rover.core.types import JournalEntry, NonFiniteError, Progress, Trace
from rover.narrative import compose_entry, detect_firsts, write_pages
from rover.pipeline.check import check_result
from rover.render import encode_gif, map_png, status_svg
from rover.sim.episode import run_episode
from rover.stages import progress as stage_progress
from rover.stages import safe_mode, step_stage
from rover.state import Explored, new_state, validate
from rover.world import World, draw_events

Arr = np.ndarray


@dataclass
class SolResult:
    state: dict
    explored: Explored
    trace: Trace | None
    facts: dict
    journal: list
    tags: list
    images: dict
    status: dict


def terrain_fn(world: World) -> Callable:
    return world.gtype_cells


def fresh_state(params: Params, seed: int | None = None) -> dict:
    s = new_state(params)
    if seed is not None:
        s["world_seed"] = int(seed)
    s["brain"] = Brain.initial(params, s["world_seed"])
    world = World(s["world_seed"], params, [])
    win = world.window(-2, -2, 1, 1)                       # cells -128..127: covers +-64 with the gradient margin
    xs = np.arange(-64, 65, dtype=np.int64)
    X, Y = np.meshgrid(xs, xs)
    gx, gy = win.gradient_at(X.ravel().astype(np.float64), Y.ravel().astype(np.float64))
    slope = np.sqrt(gx * gx + gy * gy) / params.get("world.cell_m")
    gt = win.gtype_at(X.ravel().astype(np.float64), Y.ravel().astype(np.float64))
    bad = (gt == consts.GTYPE_ICE) | ((gt == consts.GTYPE_ROCK) & (slope > 0.2))
    centre = 64 * 129 + 64
    if bool(bad[centre]):
        x, y = X.ravel(), Y.ravel()
        ring = np.maximum(np.abs(x), np.abs(y))
        ok = (~bad) & (ring >= 1) & (ring <= 64)
        order = np.lexsort((x, y, x * x + y * y))
        for i in order.tolist():
            if bool(ok[i]):
                s["origin"] = [int(x[i]), int(y[i])]
                s["rover"]["x"], s["rover"]["y"] = float(x[i]), float(y[i])
                break
    probs = validate(s)
    assert probs == [], probs
    return s


def _nonfinite(obj) -> bool:
    if isinstance(obj, np.ndarray):
        return obj.dtype.kind == "f" and not bool(np.all(np.isfinite(obj)))
    if isinstance(obj, float):
        return not math.isfinite(obj)
    if isinstance(obj, dict):
        return any(_nonfinite(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_nonfinite(v) for v in obj)
    return False


def _env() -> dict:
    from importlib.metadata import version as dist_version
    return {"python": sys.version.split()[0], "numpy": dist_version("numpy"), "pillow": dist_version("pillow"),
            "machine": platform.machine()}


def _status(s: dict, prog: Progress, facts: dict, now_utc: str, warnings: list, timings: dict, gif_bytes: int,
            gif_level: str | None, params: Params) -> dict:
    h = s["health"]
    m = s["metrics"]
    det = {"sol": s["sol"], "epoch": s["epoch"], "last_success_utc": now_utc, "code_version": s["code_version"],
           "schema_version": s["schema_version"], "stage": s["stage"]["id"],
           "stage_name": params.get("stages.stage")[s["stage"]["id"]]["name"],
           "progress": {"fraction": prog.fraction, "text": prog.value_text_en, "blocking": prog.blocking},
           "consolidation": s["stage"]["consolidation"],
           "metrics": {"couples": m["couples"], "r2": m["r2"][-1] if m["r2"] else None,
                       "battery_successes": facts.get("battery_successes"), "breakdowns": facts.get("breakdowns", 0),
                       "distance_m": facts.get("distance_m", 0.0)},
           "restored_from": h["restored_from"], "degraded": h["last_degraded"] == s["sol"],
           "truncated_at": h["truncated_at"], "attempts": h["attempts"], "incident": h["incident"],
           "passive_streak": h["passive_streak"],
           "main_lag": 0,    # placeholder: cli.sol overwrites it with main_lag() (entries of journal_tail absent from main); run_sol alone (simulate, tests) keeps 0
           "warnings": warnings}
    run = {"timings": timings, "env": _env(), "gif_bytes": gif_bytes, "gif_level": gif_level}
    return {"det": det, "run": run}


def _days_since(last: str, now: str):
    """Whole days between two ISO dates (text only, never stored); None at the first sol or on a clock going backwards."""
    if not last:
        return None
    d = (date.fromisoformat(now[:10]) - date.fromisoformat(last[:10])).days
    return int(d) if d >= 0 else None


def _tag(epoch: int, sol: int, fid: str) -> str:
    return "m-e%d-sol%04d-%s" % (epoch, sol, fid.replace(".", "-"))


def _attempt(state, explored, params, now_utc, k, render, narrative, fault, deadline, restore_info=None, ckpts=None) -> SolResult:
    P = params.get
    t0 = time.monotonic()
    timings = {}
    s = copy.deepcopy(state)
    ex = explored.copy()
    if fault == "nan":
        s["brain"]["m0"]["theta"][0] = np.float32("nan")
    if _nonfinite(s["brain"]):
        raise NonFiniteError("brain")
    sol = int(state["sol"]) + 1
    s["sol"] = sol
    seed = int(s["world_seed"])
    world = World(seed, params, s["overlays"])
    ev = draw_events(seed, sol, s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    rover, safe = safe_mode(s["rover"], s["last_facts"], params)
    rover["safe_pending"] = safe
    s["rover"] = rover
    stage = int(s["stage"]["id"])
    brain = Brain.from_state(s["brain"], stage, params, consolidation=bool(s["stage"]["consolidation"]),
                             memory=s["memory"]["couples"])
    explored_start = ex.copy()
    timings["episode_start"] = round(time.monotonic() - t0, 3)
    trace, data, facts = run_episode(s, world, brain, ex, ev, params, salt=k if k >= 2 else 0, record=render)
    timings["episode"] = round(time.monotonic() - t0, 3)
    degraded = k >= 1
    report = {"m1": None, "m2": None, "m0": None, "m3": None, "truncated_at": None}
    if not degraded:
        report = brain.learn(data, world, sol, deadline)
        s["health"]["truncated_at"] = report["truncated_at"]
    else:
        s["health"]["last_degraded"] = sol
    s["brain"] = brain.to_state()
    if _nonfinite(s["brain"]):
        raise NonFiniteError("learn")
    m = s["metrics"]
    warnings = []
    if report.get("m1") is not None:                                    # F-04: R2 series (stage >= 1)
        m["r2"] = (list(m["r2"]) + [float(report["m1"]["r2"])])[-30:]
    battery_v = None
    bat = report.get("battery")
    if bat is not None:                                                  # F-04: battery series and regression rule (SPEC 4.7)
        battery_v = int(bat["successes"])
        ck = ckpts or {}
        verdict = evaluate_regression(m, battery_v, stage, params, list(ck.keys()))
        if verdict.warning:
            warnings.append(verdict.warning)
        if verdict.restore_sol is not None:                              # restore module M0 from the checkpoint of the best measure
            s["brain"]["m0"] = copy.deepcopy(ck[verdict.restore_sol]())
            battery_v = int(run_battery(Brain.from_state(s["brain"], stage, params), world, stage, params).successes)
            warnings.append("battery_restored_from_sol_%d" % verdict.restore_sol)
        append_measure(m, battery_v, stage, sol, verdict.low)
    timings["learn"] = round(time.monotonic() - t0, 3)
    mem = s["memory"]["couples"]
    s["memory"]["couples"] = np.concatenate([mem, data.couples.astype(np.float32)], axis=0)[-int(P("brain.m1.buffer")):]
    s["trail"] = np.concatenate([s["trail"], data.path.astype(np.float32)], axis=0)[-1500:]
    m["couples"] += int(data.couples.shape[0])
    m["breakdowns"] = (m["breakdowns"] + [facts["breakdowns"]])[-30:]
    ok = facts["breakdowns"] == 0 and facts["awake_cells"] >= P("stages.energy_min_cells")
    m["no_breakdown_streak"] = m["no_breakdown_streak"] + 1 if ok else 0
    s["rover"]["safe_pending"] = []
    dec = step_stage(s["stage"], m, sol, version.MAX_STAGE, params)
    s["stage"] = dec.stage
    if dec.stage["id"] != stage:
        m["battery_low"] = 0                                             # the window filters by stage already
    low = stage >= 2 and facts["awake_cells"] < P("stages.no_progress_cells")
    s["last_facts"] = {"stuck": facts["stuck"], "tipped": facts["tipped"], "battery_min": facts["battery_min"],
                       "awake_cells": facts["awake_cells"],
                       "low_awake_streak": s["last_facts"]["low_awake_streak"] + 1 if low else 0}
    s["events"] = {"storm_left": ev.storm_left}
    s["overlays"] = s["overlays"] + list(ev.new_overlays)
    h = s["health"]
    h.update(attempts=k, incident=None, passive_streak=0, restored_from=h.get("restored_from"))
    s["last_run_utc"] = now_utc
    s["params_hash"] = params.hash
    s["code_version"] = version.CODE_VERSION
    facts.update(utc=now_utc, epoch=s["epoch"], stage_name=P("stages.stage")[stage]["name"],
                 advanced_to=s["stage"]["id"] if dec.advanced else None, restored_from=h["restored_from"],
                 restore_cause=(restore_info or {}).get("cause"), degraded=degraded, consolidation=s["stage"]["consolidation"],
                 truncated_at=h["truncated_at"], incident=None, days_since_last_run=_days_since(state["last_run_utc"], now_utc), new_names=[],
                 battery_successes=battery_v, r2=None if report.get("m1") is None else float(report["m1"]["r2"]),
                 r2_worst_terrain=None if report.get("m1") is None else report["m1"].get("r2_worst_terrain"), samples=0, spectra=0, new_categories=0,
                 n_categories=0, novel_vs_prev=None, ari=None, metric_before=None,
                 metric_after=None, threshold=None)
    facts["redone_sols"] = list((restore_info or {}).get("redone_sols", []))
    firsts = detect_firsts(facts, s)
    for fid, fs in firsts:
        s["firsts"][fid] = [s["epoch"], fs]
    facts["firsts"] = [f for f, _ in firsts]
    tags = [_tag(s["epoch"], sol, f) for f, _ in firsts]
    s["pending_tags"] = list(tags)
    journal = []
    if narrative:
        e = compose_entry(facts, s, params)
        journal = [e]
        s["journal_tail"] = (s["journal_tail"] + [{"epoch": e.epoch, "sol": e.sol, "utc": e.utc, "fr": e.fr, "en": e.en}])[-30:]
    prog = stage_progress(s["stage"], m, params)
    images, level, gif_bytes = {}, None, 0
    if render:
        terrain = terrain_fn(world)
        gif, level = encode_gif(trace, s, explored_start, terrain, prog, now_utc, params)
        gif_bytes = len(gif)
        images = {"console.gif": gif, "status.svg": status_svg(s, prog, now_utc, params).encode("utf-8"),
                  "map.png": map_png(s, ex, terrain, trace, params)}
    timings["total"] = round(time.monotonic() - t0, 3)
    status = _status(s, prog, facts, now_utc, warnings, timings, gif_bytes, level, params)
    return SolResult(state=s, explored=ex, trace=trace, facts=facts, journal=journal, tags=tags, images=images, status=status)


def _passive(state, explored, params, now_utc, exc_name, prev_images, restore_info=None) -> SolResult:
    """k = 3: nothing simulated, no call into render or narrative; images copied from _in (SPEC 6.7, ARCH 4)."""
    t0 = time.monotonic()
    s = copy.deepcopy(state)
    sol = int(state["sol"]) + 1
    s["sol"] = sol
    s["last_run_utc"] = now_utc
    h = s["health"]
    h.update(attempts=3, incident=exc_name, passive_streak=h["passive_streak"] + 1)
    fr = f"Incident technique ({exc_name}) : je suis resté en veille ce sol."
    en = f"Technical incident ({exc_name}): I stayed in standby this sol."
    e = JournalEntry(epoch=s["epoch"], sol=sol, utc=now_utc, fr=fr, en=en)
    s["journal_tail"] = (s["journal_tail"] + [{"epoch": e.epoch, "sol": e.sol, "utc": e.utc, "fr": fr, "en": en}])[-30:]
    s["pending_tags"] = []
    images = dict(prev_images or {})
    warnings = [f"images_from_sol_{state['sol']}"] if images else []
    prog = stage_progress(s["stage"], s["metrics"], params)    # arithmetic on the state only (stages: no render/narrative)
    status = _status(s, prog, {}, now_utc, warnings, {"total": round(time.monotonic() - t0, 3)}, len(images.get("console.gif", b"")),
                     None, params)
    return SolResult(state=s, explored=explored.copy(), trace=None,
                     facts={"incident": exc_name, "restore_cause": (restore_info or {}).get("cause")}, journal=[e], tags=[],
                     images=images, status=status)


def run_sol(state: dict, explored: Explored, params: Params, now_utc: str, render: bool = True, narrative: bool = True,
            fault: str = "none", deadline: float = float("inf"), prev_images: dict | None = None,
            prev_files: dict | None = None, restore_info: dict | None = None, ckpts: dict | None = None) -> SolResult:
    """Attempts k = 0, 1, 2 then the passive sol (k = 3). `restore_info` (addition J5) = {"cause", "redone_sols"} of the
    restoration that produced `state` (cli.sol), copied into the facts; None otherwise. `ckpts` (addition J6) = {sol: loader}
    of the checkpoints available for the regression rule of the test battery (loader() returns the checkpoint's M0 dict)."""
    last = ""
    for k in range(0, 3):
        try:
            res = _attempt(state, explored, params, now_utc, k, render, narrative, fault if k == 0 else "none", deadline,
                           restore_info, ckpts)
            problems = check_result(res, state, prev_files, params)
            if problems:
                raise ValueError("check_result: " + "; ".join(problems[:3]))
            return res
        except Exception as exc:
            last = type(exc).__name__
    return _passive(state, explored, params, now_utc, last, prev_images, restore_info)      # k = 3: its own failure propagates (code 4)


_HEAD = re.compile(r"^### Sol (\d+)(?: · epoch (\d+))? · ", re.M)


def _main_keys(main_dir: Path) -> set:
    """(epoch, sol) of every journal entry already on main (format of SPEC 8.1; the journal is append-only)."""
    keys = set()
    jdir = Path(main_dir) / "journal"
    if jdir.is_dir():
        for f in sorted(jdir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md")):
            for m in _HEAD.finditer(f.read_text(encoding="utf-8")):
                keys.add((int(m.group(2) or 1), int(m.group(1))))
    return keys


def main_lag(state: dict, main_dir: Path) -> int:
    """`status.json.det.main_lag` (SPEC 10 case 3): entries of journal_tail absent from main, not counting the entry of
    the sol being published (still to be written); 0 on a healthy chain."""
    have = _main_keys(main_dir)
    return isum_py(1 for e in state["journal_tail"] if (e["epoch"], e["sol"]) not in have and e["sol"] != state["sol"])


def write_main(result: SolResult, main_dir: Path, tags_file: Path | None, repo: str, params: Params,
               prev_pending: list | None = None) -> None:
    """Pages on main, then the tag list (`<tag> <source folder>`): `_in` for the `pending_tags` of the previous published
    state that were not yet pushed (re-proposed once), `_out` for this sol's tags."""
    main_dir = Path(main_dir)
    entries = [JournalEntry(epoch=e["epoch"], sol=e["sol"], utc=e["utc"], fr=e["fr"], en=e["en"])
               for e in result.state["journal_tail"]]
    if result.state["health"]["incident"] is None:      # a passive sol writes no pages: its line reaches main at the next normal sol
        write_pages(main_dir, result.state, entries, params, repo)
    if tags_file is not None:
        lines = ["%s _in\n" % t for t in (prev_pending or []) if t not in result.tags]
        lines += ["%s _out\n" % t for t in result.tags]
        Path(tags_file).write_text("".join(lines), encoding="utf-8")
