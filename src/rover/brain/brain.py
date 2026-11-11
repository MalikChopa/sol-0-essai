"""The brain: M0-M3 weights, act, learn (SPEC 4, 6.5). Every recorded activation is the one actually computed."""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass

import numpy as np

from rover.agent.energy import panel_factor
from rover.agent.sensors import observe
from rover.brain.battery import battery_due, run_battery
from rover.brain.es import es_generation, es_key
from rover.brain.m0_drive import babble_noise, explore_target, sun_target
from rover.brain.m1_model import predict, train_m1
from rover.brain.m2_encoder import train_m2
from rover.brain.m3_energy import m3_decide, m3_inputs, rollout_m3_fitness
from rover.brain.mlp import m2_descriptors, mlp_forward, visual_features
from rover.brain.rollouts import rollout_fitness
from rover.config import Params
from rover.core.mlp_layout import mlp_npar
from rover.core.rng import derive, gauss_ih4
from rover.core.types import BrainSnapshot, NonFiniteError, SolEvents, StepOut, Sun
from rover.world.climate import sun_at
from rover.world.chunks import Window

Arr = np.ndarray


@dataclass
class ActCtx:
    sol: int
    tick: int
    stage: int
    sun: Sun
    ev: SolEvents
    win: Window
    explored_mask: Arr          # aligned on win from stage 2; (0, 0) before (J0 note: the target is not used before stage 2)
    explore_scale: float
    keys_babble: Arr


def _net(seed: int, i: int, n_in: int, n_h: int, n_out: int, w2_scale: float = 1.0) -> dict:
    npar = mlp_npar(n_in, n_h, n_out)
    g = gauss_ih4(derive(seed, "init", i), np.arange(npar))
    a, b = n_in * n_h, n_in * n_h + n_h
    c = b + n_h * n_out
    th = np.zeros(npar, dtype=np.float64)
    th[:a] = g[:a] * (0.5 / math.sqrt(n_in))
    th[b:c] = g[b:c] * (0.5 / math.sqrt(n_h)) * w2_scale
    z = np.zeros(npar, dtype=np.float32)
    return {"theta": th.astype(np.float32), "adam_m": z.copy(), "adam_v": z.copy(), "b1t": 1.0, "b2t": 1.0}


class Brain:
    def __init__(self, brain: dict, stage: int, params: Params, consolidation: bool = False, memory: Arr | None = None):
        self.b = brain
        self.stage = int(stage)
        self.params = params
        self.consolidation = bool(consolidation)     # maintenance learning only (SPEC 5.4)
        self.memory = memory                          # (n, 10) command-effect pairs of the buffer BEFORE this sol (SPEC 4.3)
        self.prev_u: Arr | None = None
        self.fixed_target: Arr | None = None          # (B, 2) absolute target imposed by the rollouts / battery
        self.target: Arr | None = None                # (B, 2) target used by the last act (None before stage 2)
        self.last_m3_x: Arr | None = None             # M3 inputs / hidden of the last decision (what the diagram shows)
        self.last_m3_h: Arr | None = None
        self._f: Arr | None = None
        self._z: Arr | None = None
        self._tgt: Arr | None = None
        self._tgt_tick: Arr | None = None
        self._tgt_seek: Arr | None = None
        self._m3_y: Arr | None = None
        self._mode3: Arr | None = None
        self._pose: tuple | None = None

    @staticmethod
    def initial(params: Params, seed: int) -> dict:
        P = params.get
        m0 = _net(seed, 0, P("brain.m0.n_in"), P("brain.m0.hidden"), P("brain.m0.n_out"), P("brain.m0.w2_init"))
        m1 = _net(seed, 1, P("brain.m1.n_in"), P("brain.m1.hidden"), P("brain.m1.n_out"))
        m1.update({"x_mean": np.zeros(5, dtype=np.float32), "x_std": np.ones(5, dtype=np.float32),
                   "y_mean": np.zeros(3, dtype=np.float32), "y_std": np.ones(3, dtype=np.float32)})
        k = P("brain.m2.k")
        n_z = 8 * 5
        w = gauss_ih4(derive(seed, "init", 2), np.arange(k * n_z)).reshape(k, n_z) * (1.0 / math.sqrt(n_z))
        m2 = {"w": w.astype(np.float32), "mean": np.zeros(n_z, dtype=np.float32), "var": np.ones(n_z, dtype=np.float32),
              "n_sols": 0}
        m3 = _net(seed, 3, P("brain.m3.n_in"), P("brain.m3.hidden"), P("brain.m3.n_out"))
        return {"m0": m0, "m1": m1, "m2": m2, "m3": m3, "m4": None, "m5": None}

    @classmethod
    def from_state(cls, brain: dict, stage: int, params: Params, consolidation: bool = False,
                   memory: Arr | None = None) -> "Brain":
        return cls(copy.deepcopy(brain), stage, params, consolidation, memory)

    def to_state(self) -> dict:
        return copy.deepcopy(self.b)

    def snapshot(self) -> BrainSnapshot:
        s, b = self.stage, self.b
        return BrainSnapshot(stage=s, m0=b["m0"]["theta"].copy(),
                             m1=b["m1"]["theta"].copy() if s >= 1 else None,
                             m2_w=b["m2"]["w"].copy() if s >= 1 else None,
                             m2_mean=b["m2"]["mean"].copy() if s >= 1 else None,
                             m2_var=b["m2"]["var"].copy() if s >= 1 else None,
                             m3=b["m3"]["theta"].copy() if s >= 3 else None)

    # ---- one tick ---------------------------------------------------------------------------------------------
    def _decide_m3(self, rb, ctx: ActCtx) -> None:
        P = self.params.get
        step = int(P("brain.m3.step_ticks"))
        B = rb.x.shape[0]
        if self._mode3 is None or self._mode3.shape[0] != B:
            self._mode3 = np.zeros(B, dtype=np.int64)
            self._m3_y = None
        if self._m3_y is None or ctx.tick % step == 0:
            gx, gy = ctx.win.gradient_at(rb.x, rb.y)
            prev = float(sun_at(ctx.sol, max(0, ctx.tick - step), self.params).elev)
            x3 = m3_inputs(rb, ctx.sun, prev, panel_factor(gx, gy, ctx.sun, self.params), self.params)
            y3, h3, self._mode3 = m3_decide(self.b["m3"]["theta"], x3, self._mode3, float(P("brain.m3.hysteresis")),
                                            self.params)
            self._m3_y, self.last_m3_x, self.last_m3_h = y3, x3, h3

    def _update_targets(self, rb, ctx: ActCtx, seek: Arr) -> Arr:
        P = self.params.get
        B = rb.x.shape[0]
        mask = ctx.explored_mask
        if mask.size == 0:
            mask = np.zeros(ctx.win.height.shape, dtype=np.uint8)
        if self._tgt is None or self._tgt.shape[0] != B:
            self._tgt = np.zeros((B, 2))
            self._tgt_tick = np.full(B, -1000000000, dtype=np.int64)
            self._tgt_seek = np.zeros(B, dtype=bool)
        arr_r = float(P("brain.arrive_r"))
        for i in range(B):
            d = math.sqrt((self._tgt[i, 0] - rb.x[i]) ** 2 + (self._tgt[i, 1] - rb.y[i]) ** 2)
            due = (ctx.tick - int(self._tgt_tick[i]) >= int(P("brain.target_period"))) or d < arr_r \
                or bool(self._tgt_seek[i]) != bool(seek[i])
            if not due:
                continue
            t = None
            if bool(seek[i]):
                t = sun_target(float(rb.x[i]), float(rb.y[i]), ctx.win, mask, ctx.sun, self.params)
            if t is None:
                t = explore_target(float(rb.x[i]), float(rb.y[i]), ctx.win, mask, self.params)
            self._tgt[i] = t
            self._tgt_tick[i] = ctx.tick
            self._tgt_seek[i] = bool(seek[i])
        return self._tgt

    def act(self, rb, cam, ctx: ActCtx) -> StepOut:
        P = self.params.get
        B = rb.x.shape[0]
        stage = self.stage
        if self.prev_u is None:
            self.prev_u = np.zeros((B, 2))
        self._pose = (float(rb.x[0]), float(rb.y[0]))
        m2 = self.b["m2"]
        if cam is not None and stage >= 1:                                   # M2 stage 1 (descriptors) and 2 (features)
            self._z = m2_descriptors(cam.index, cam.depth, cam.D)
            self._f = visual_features(self._z, m2["mean"], m2["var"], m2["w"])
        elev = float(ctx.sun.elev)
        forced = np.asarray(rb.forced, dtype=bool)
        m3_out = None
        seek = np.zeros(B, dtype=bool)
        if stage >= 3:                                                       # M3 decides sleep and sun seeking
            self._decide_m3(rb, ctx)
            m3_out = self._m3_y.copy()
            asleep = forced | (self._mode3 == 2)
            seek = (self._mode3 == 1) & ~asleep
        else:                                                                # stages 0-2: hardware sleep at night
            asleep = forced | (elev <= 0.0)
        target = None
        if stage >= 2:
            target = self.fixed_target if self.fixed_target is not None else self._update_targets(rb, ctx, seek)
        self.target = target
        x = observe(rb, stage, target, ctx.sun, self._f if stage >= 1 else None, self.prev_u, self.params)
        y, h = mlp_forward(self.b["m0"]["theta"], x, P("brain.m0.n_in"), P("brain.m0.hidden"), P("brain.m0.n_out"))
        amp = (P("brain.babble_amp") if stage <= 1 else P("brain.explore_amp")) * ctx.explore_scale
        xi = babble_noise(ctx.keys_babble, ctx.tick, amp, int(P("brain.babble_segment")))
        u = np.clip(y + xi, -1.0, 1.0)
        a2 = asleep[:, None]
        x, h, y = np.where(a2, 0.0, x), np.where(a2, 0.0, h), np.where(a2, 0.0, y)
        u, xi = np.where(a2, 0.0, u), np.where(a2, 0.0, xi)
        seg_end = np.full(B, (ctx.tick % int(P("brain.babble_segment"))) == int(P("brain.babble_segment")) - 1)
        base_mode = "BABBLE" if stage <= 1 else "DRIVE"
        modes = ["SLEEP" if bool(asleep[i]) else ("SEEK_SUN" if bool(seek[i]) else base_mode) for i in range(B)]
        m1_pred = None
        if stage >= 1:
            inp = np.stack([u[:, 0], u[:, 1], rb.pitch, rb.roll, rb.slip], axis=1)
            m1_pred = np.where(a2, 0.0, predict(self.b["m1"], inp, int(P("brain.m1.hidden"))))
        self.prev_u = u
        return StepOut(u=u, mode=modes, x=x, h=h, y=y, xi=xi, segment_end=seg_end,
                       z=self._z if stage >= 1 else None, f=self._f if stage >= 1 else None, m1_pred=m1_pred,
                       m3_out=m3_out)

    # ---- learning after the episode ---------------------------------------------------------------------------
    def learn(self, data, world, sol: int, deadline: float) -> dict:
        P = self.params.get
        stage, seed = self.stage, int(world.seed)
        rep = {"m1": None, "m2": None, "m0": None, "m3": None, "truncated_at": None, "battery": None}
        if stage < 1:
            return rep                                                        # stage 0: only the pairs are collected
        maint = self.consolidation
        learning_m0 = stage == 2 and not maint
        learning_m3 = stage == 3 and not maint
        rows = np.asarray(data.couples, dtype=np.float64).reshape(-1, 10)
        if self.memory is not None and len(self.memory):
            rows = np.concatenate([np.asarray(self.memory, dtype=np.float64).reshape(-1, 10), rows], axis=0)
        rows = rows[-int(P("brain.m1.buffer")):]
        steps = int(P("brain.m1.steps_learn")) if (stage == 1 and not maint) else int(P("brain.m1.steps_maint"))
        r = train_m1(self.b["m1"], rows, seed, sol, steps, self.params)
        rep["m1"] = {"r2": r["r2"], "steps": r["steps"], "n_holdout": r["n_holdout"], "r2_worst_terrain": r["worst_terrain"]}
        z = np.asarray(data.frames_z, dtype=np.float64).reshape(-1, 40)
        rep["m2"] = train_m2(self.b["m2"], z, self.params)
        center = self._pose or ((float(data.path[-1, 0]), float(data.path[-1, 1])) if len(data.path) else (0.0, 0.0))
        es = P("brain.es")
        if stage >= 2:
            gens = int(es["gens_learn"]) if learning_m0 else int(es["gens_maint"])
            pop = int(es["pop"]) if learning_m0 else int(es["pop_maint"])
            m_eps = int(es["episodes"]) if learning_m0 else int(es["episodes_maint"])
            fn = lambda th, g: rollout_fitness(world, self.params, stage, th, self.b["m2"], sol, g, m_eps, center)
            done = self._run_es(self.b["m0"], fn, seed, sol, 0, gens, pop, es, deadline, "m0", rep)
            rep["m0"] = {"gens": done}
        if stage >= 3:
            gens = int(es["gens_learn"]) if learning_m3 else int(es["gens_maint"])
            pop = int(es["pop"]) if learning_m3 else int(es["pop_maint"])
            if rep["truncated_at"] is None:
                fn = lambda th, g: rollout_m3_fitness(world, self.params, th, None, sol, g, center)
                done = self._run_es(self.b["m3"], fn, seed, sol, 1, gens, pop, es, deadline, "m3", rep)
                rep["m3"] = {"gens": done}
        for k in ("m0", "m1", "m3"):
            if not bool(np.all(np.isfinite(self.b[k]["theta"]))):
                raise NonFiniteError(k)
        if stage >= 2 and battery_due(sol, maint, self.params):
            b = run_battery(self, world, stage, self.params)
            rep["battery"] = {"successes": b.successes, "per_course": b.per_course, "categories": b.categories}
        return rep

    def _run_es(self, net: dict, fn, seed: int, sol: int, module: int, gens: int, pop: int, es: dict, deadline: float,
                name: str, rep: dict) -> int:
        done = 0
        for g in range(gens):
            es_generation(net, lambda th: fn(th, g), es_key(seed, sol, module, g), pop, es, name)
            done += 1
            if time.monotonic() > deadline and done < gens:
                rep["truncated_at"] = {"module": name, "gen": done}
                break
        return done
