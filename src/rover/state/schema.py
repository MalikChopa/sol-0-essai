"""State schema (SPEC 6.9): new_state, validate, migrations, core_for_compare."""
from __future__ import annotations

import copy
import math

import numpy as np

from rover import version
from rover.config import Params, world_params_hash
from rover.state.migrations import migrate_explored_bytes, migrate_state

ARRAY_KEYS = ("theta", "adam_m", "adam_v", "x_mean", "x_std", "y_mean", "y_std", "w", "mean", "var")


def new_state(params: Params) -> dict:
    """Non-brain part of a fresh state (brain = {} is invalid on its own)."""
    P = params.get
    return {
        "schema_version": version.SCHEMA_VERSION, "code_version": version.CODE_VERSION, "params_hash": params.hash,
        "world_seed": int(P("run.world_seed")), "world_gen_version": version.WORLD_GEN_VERSION,
        "world_params_hash": world_params_hash(params),
        "epoch": 1, "sol": 0, "last_run_utc": "",
        "stage": {"id": 0, "entered_sol": 0, "sols_in_stage": 0, "threshold_scale": 1.0, "recalibrations": 0,
                  "consolidation": False, "history": [[0, 0]]},
        "metrics": {"couples": 0, "r2": [], "r2_stable": 0, "battery": [], "battery_stage": [], "battery_sol": [],
                    "battery_low": 0, "no_breakdown_streak": 0, "breakdowns": [], "novel": [], "ari": [], "ari_stable": 0},
        "rover": {"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": 1.0, "stuck": False, "tipped": False,
                  "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "BABBLE",
                  "safe_pending": []},
        "origin": [0, 0],
        "brain": {},
        "memory": {"couples": np.zeros((0, 10), dtype=np.float32)},
        "trail": np.zeros((0, 3), dtype=np.float32),
        "overlays": [], "events": {"storm_left": 0},
        "last_facts": {"stuck": False, "tipped": False, "battery_min": 1.0, "awake_cells": 0, "low_awake_streak": 0},
        "firsts": {}, "names": {}, "journal_tail": [], "pending_tags": [],
        "health": {"attempts": 0, "incident": None, "passive_streak": 0, "last_degraded": None,
                   "truncated_at": None, "restored_from": None},
    }


_TOP = ("schema_version", "code_version", "params_hash", "world_seed", "world_gen_version", "world_params_hash", "epoch",
        "sol", "last_run_utc", "stage", "metrics", "rover", "origin", "brain", "memory", "trail", "overlays", "events",
        "last_facts", "firsts", "names", "journal_tail", "pending_tags", "health")
_BRAIN_KEYS = {"m0": ("theta", "adam_m", "adam_v", "b1t", "b2t"),
               "m1": ("theta", "adam_m", "adam_v", "b1t", "b2t", "x_mean", "x_std", "y_mean", "y_std"),
               "m2": ("w", "mean", "var", "n_sols"),
               "m3": ("theta", "adam_m", "adam_v", "b1t", "b2t")}


def _walk(obj, path, probs):
    if isinstance(obj, np.ndarray):
        if obj.dtype.kind == "f":
            if not bool(np.all(np.isfinite(obj))):
                probs.append(f"{path}: non finite")
            elif obj.size and float(np.max(np.abs(obj))) >= 1e6:
                probs.append(f"{path}: |value| >= 1e6")
    elif isinstance(obj, float):
        if not math.isfinite(obj):
            probs.append(f"{path}: non finite")
        elif abs(obj) >= 1e6:
            probs.append(f"{path}: |value| >= 1e6")
    elif isinstance(obj, dict):
        for k in sorted(obj, key=str):
            _walk(obj[k], f"{path}.{k}", probs)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, f"{path}[{i}]", probs)


def nonfinite_paths(state: dict) -> list[str]:
    """Paths of NaN / infinite values (arrays packed as base64 are invisible to the JSON encoder's allow_nan check)."""
    probs: list[str] = []
    _walk(state, "state", probs)
    return [p for p in probs if p.endswith("non finite")]


def validate(state: dict) -> list[str]:
    probs: list[str] = []
    for k in _TOP:
        if k not in state:
            probs.append(f"missing key {k}")
    if probs:
        return probs
    r = state["rover"]
    if not (0.0 <= r["battery"] <= 1.0):
        probs.append("battery out of [0, 1]")
    if not (abs(r["c"] * r["c"] + r["s"] * r["s"] - 1.0) < 1e-9):
        probs.append("heading not unit")
    if not (0 <= state["stage"]["id"] <= 5):
        probs.append("stage out of [0, 5]")
    b = state["brain"]
    for m, keys in _BRAIN_KEYS.items():
        if m not in b or not isinstance(b[m], dict):
            probs.append(f"brain.{m} missing")
        else:
            for kk in keys:
                if kk not in b[m]:
                    probs.append(f"brain.{m}.{kk} missing")
    if state["memory"]["couples"].shape[0] > 4000 or state["memory"]["couples"].shape[1:] != (10,):
        probs.append("memory.couples size")
    if state["trail"].shape[0] > 1500 or state["trail"].shape[1:] != (3,):
        probs.append("trail size")
    if len(state["journal_tail"]) > 30:
        probs.append("journal_tail size")
    for key in ("r2", "battery", "battery_stage", "battery_sol", "breakdowns", "ari"):
        if len(state["metrics"][key]) > 30:
            probs.append(f"metrics.{key} size")
    if len(state["metrics"]["novel"]) > 20:
        probs.append("metrics.novel size")
    _walk(state, "state", probs)
    return probs


def migrate(d: dict) -> dict:
    """Bring a core dict to `version.SCHEMA_VERSION` (pure: the input is not modified)."""
    return migrate_state(d, version.SCHEMA_VERSION)


def migrate_explored(b: bytes) -> bytes:
    """SOL0EXP<n> header -> current format (only format 1 exists)."""
    return migrate_explored_bytes(b)


def core_for_compare(state: dict) -> dict:
    d = copy.deepcopy(state)
    d.pop("journal_tail", None)
    d.pop("last_run_utc", None)
    return d
