"""Fixed test battery (SPEC 4.7, EF-50) and its regression rule, counted on the sols where the battery was played."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from rover.brain.rollouts import CALM, drive_batch, margin_cells, window_for
from rover.config import Params
from rover.core import consts, dmath
from rover.core.exact import to_int
from rover.core.rng import derive, uniform
from rover.world.chunks import World
from rover.world.climate import sun_at

Arr = np.ndarray
_N_CAND = 4000
CATEGORIES = ("flat", "slope", "sand", "any")
_CACHE: dict = {}


@dataclass
class BatteryResult:
    successes: int
    per_course: list
    categories: list = field(default_factory=list)      # category of each course (flat, slope, sand, any)


def _mean(a: Arr) -> float:
    return math.fsum(a.tolist()) / a.shape[0]


def _path_stats(win, x0: Arr, y0: Arr, tx: Arr, ty: Arr, cm: float, n: int = 7) -> tuple[Arr, Arr]:
    """Mean slope |grad h| / cell_m and fraction of SAND cells along each straight path (n samples), vectorised."""
    t = (np.arange(n, dtype=np.float64) / (n - 1.0))[None, :]
    xs, ys = x0[:, None] + (tx - x0)[:, None] * t, y0[:, None] + (ty - y0)[:, None] * t
    gx, gy = win.gradient_at(xs, ys)
    slope = np.sqrt(gx * gx + gy * gy) / cm
    sand = (win.gtype_at(xs, ys) == consts.GTYPE_SAND).astype(np.float64)
    ms = np.zeros(x0.shape[0])
    md = np.zeros(x0.shape[0])
    for j in range(n):                                   # fixed summation order
        ms = ms + slope[:, j]
        md = md + sand[:, j]
    return ms / n, md / n


def make_courses(seed: int, params: Params) -> list:
    """The 20 fixed courses (x, y, heading c, s, target x, target y, category), chosen once by derive(seed, "battery")
    on the overlay-free world among `_N_CAND` candidates: 5 flat (slope < 0.05, little sand), 5 sloped (0.10-0.30; if
    the world has fewer, the steepest remaining candidates complete the category: documented fallback), 5 crossing
    sand (>= 30 % sand cells), 5 any (the next unused candidates). Categories in that order, discovery order inside."""
    P = params.get
    n_total = int(P("brain.battery.courses"))
    per = n_total // 4
    region = float(P("brain.battery.region"))
    tdist = float(P("brain.battery.target_dist"))
    cm = P("world.cell_m")
    world = World(seed, params)
    half = region / 2.0
    win = window_for(world, np.asarray([-half, half]), np.asarray([-half, half]), tdist + 4.0)
    key = derive(seed, "battery")
    n = _N_CAND
    idx = np.arange(n)
    u = [uniform(key, 5 * idx + j) for j in range(4)]
    x0 = np.floor(-half + region * u[0])
    y0 = np.floor(-half + region * u[1])
    a, h = 2.0 * math.pi * u[2], 2.0 * math.pi * u[3]
    tx = x0 + tdist * dmath.cos(a)
    ty = y0 + tdist * dmath.sin(a)
    slope, sand = _path_stats(win, x0, y0, tx, ty, cm)
    used: set = set()
    picked: dict = {k: [] for k in CATEGORIES}

    def take(cat: str, order, k: int) -> None:
        for i in order:
            if len(picked[cat]) >= k:
                break
            if i not in used:
                used.add(i)
                picked[cat].append(i)

    take("flat", np.flatnonzero((slope < 0.05) & (sand < 0.15)).tolist(), per)
    take("slope", np.flatnonzero((slope >= 0.10) & (slope <= 0.30)).tolist(), per)
    if len(picked["slope"]) < per:                                          # fallback: the steepest unused candidates
        take("slope", np.argsort(-slope, kind="stable").tolist(), per)
    take("sand", np.flatnonzero(sand >= 0.30).tolist(), per)
    take("any", idx.tolist(), n_total - 3 * per)
    out = []
    for cat in CATEGORIES:
        for i in picked[cat]:
            out.append((float(x0[i]), float(y0[i]), float(dmath.cos(h[i])), float(dmath.sin(h[i])), float(tx[i]),
                        float(ty[i]), cat))
    return out




def run_battery(brain, world, stage: int, params: Params) -> BatteryResult:
    """Fixed exam: noon of sol 0 (no storm), slip and camera keys without `sol`, xi = 0, acuity of the stage."""
    P = params.get
    seed = world.seed
    ck = ("courses", seed, params.hash)
    courses = _CACHE.get(ck)
    if courses is None:
        courses = make_courses(seed, params)
        _CACHE.clear()
        _CACHE[ck] = courses
    n = len(courses)
    T = int(P("brain.battery.max_ticks"))
    exam = World(seed, params)                                        # overlay-free: the exam never changes
    xs = np.asarray([c[0] for c in courses] + [c[4] for c in courses])
    ys = np.asarray([c[1] for c in courses] + [c[5] for c in courses])
    win = window_for(exam, xs, ys, margin_cells(params, stage, T))
    f = lambda i: np.asarray([c[i] for c in courses], dtype=np.float64)
    k_slip = np.asarray([derive(seed, "slip", 0, 1000000, i) for i in range(n)], dtype=np.uint64)
    k_cam = np.asarray([derive(seed, "cam", 0, 1000000, i) for i in range(n)], dtype=np.uint64)
    th = np.repeat(np.asarray(brain.b["m0"]["theta"], dtype=np.float64)[None, :], n, axis=0)
    r = drive_batch(win, params, stage, th, brain.b["m2"], f(0), f(1), f(2), f(3), np.stack([f(4), f(5)], axis=1),
                    sun_at(0, 600, params), k_slip, k_cam, T, CALM)
    ok = r["arrived"] & ~r["tipped"] & ~r["stuck"]
    return BatteryResult(successes=int(np.count_nonzero(ok)), per_course=[bool(v) for v in ok],
                         categories=[c[6] for c in courses])


def battery_due(sol: int, consolidation: bool, params: Params) -> bool:
    """Played every sol from stage 2; in consolidation one sol in `every_consolidation` (EN-06 lever)."""
    if not consolidation:
        return True
    return int(sol) % int(params.get("brain.battery.every_consolidation")) == 0


@dataclass(frozen=True)
class Verdict:
    low: int                    # value of metrics["battery_low"] if this measure is kept as it is
    restore_sol: int | None     # sol of the checkpoint to restore (best measure of the window), else None
    warning: str | None         # "battery_regress_no_checkpoint" when the checkpoint no longer exists
    threshold: float | None


def evaluate_regression(metrics: dict, successes: int, stage: int, params: Params, checkpoint_sols) -> Verdict:
    """Regression rule (SPEC 4.7), on played sols only: window = the `regress_window` last measures of the same stage
    (before this one); threshold = regress x best of the window; battery_low = consecutive measures under the threshold;
    at `regress_consecutive` -> restore the checkpoint of the best measure's sol. Pure: nothing is mutated."""
    B = params.get("brain.battery")
    idx = [i for i, s in enumerate(metrics["battery_stage"]) if s == stage][-int(B["regress_window"]):]
    if not idx:
        return Verdict(0, None, None, None)
    best_i = idx[0]
    for i in idx:
        if metrics["battery"][i] > metrics["battery"][best_i]:
            best_i = i
    thr = float(B["regress"]) * metrics["battery"][best_i]
    if successes >= thr:
        return Verdict(0, None, None, thr)
    low = int(metrics["battery_low"]) + 1
    if low < int(B["regress_consecutive"]):
        return Verdict(low, None, None, thr)
    best_sol = int(metrics["battery_sol"][best_i])
    if best_sol in set(int(s) for s in checkpoint_sols):
        return Verdict(0, best_sol, None, thr)
    return Verdict(0, None, "battery_regress_no_checkpoint", thr)


def append_measure(metrics: dict, successes: int, stage: int, sol: int, low: int) -> None:
    """Record a measure (the one of the published brain) in the metrics (lists bounded to 30)."""
    metrics["battery"] = (list(metrics["battery"]) + [int(successes)])[-30:]
    metrics["battery_stage"] = (list(metrics["battery_stage"]) + [int(stage)])[-30:]
    metrics["battery_sol"] = (list(metrics["battery_sol"]) + [int(sol)])[-30:]
    metrics["battery_low"] = int(low)
