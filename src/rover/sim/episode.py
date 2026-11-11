"""One sol of simulation (ARCH 4 step 5): 1200 ticks, frozen brain, camera every 8 ticks, trace recording."""
from __future__ import annotations

import math

import numpy as np

from rover.agent.body import RoverBatch
from rover.agent.camera import camera_spec, capture
from rover.agent.physics import physics_step
from rover.agent.energy import panel_factor
from rover.brain.brain import ActCtx, Brain
from rover.brain.m1_model import predict
from rover.config import Params
from rover.core import consts, dmath
from rover.core.exact import to_int
from rover.core.rng import derive
from rover.core.types import CamFrame, FrameRecord, NonFiniteError, SolData, SolEvents, Sun, Trace
from rover.sim.trace import TraceRecorder
from rover.state.explored import Explored
from rover.world.chunks import World
from rover.world.climate import sun_at

Arr = np.ndarray


def _window(world: World, x: float, y: float):
    cx = to_int(np.floor(x / world.cs))
    cy = to_int(np.floor(y / world.cs))
    return world.window(cx - 3, cy - 3, cx + 3, cy + 3)


def run_episode(state: dict, world: World, brain: Brain, explored: Explored, ev: SolEvents, params: Params,
                salt: int = 0, record: bool = True) -> tuple[Trace | None, SolData, dict]:
    """state["sol"] is the sol being played. Mutates state["rover"] (final pose) and `explored`; nothing else."""
    P = params.get
    seed = int(state["world_seed"])
    sol = int(state["sol"])
    stage = int(state["stage"]["id"])
    T = int(P("run.ticks_per_sol"))
    period = int(P("rover.cam_period"))
    seg = int(P("brain.babble_segment"))
    cm = P("world.cell_m")
    vmax, track = P("rover.v_max"), P("rover.track")
    trail_every = int(P("run.trail_every_ticks"))
    extra = (salt,) if salt else ()
    k_slip = np.asarray([derive(seed, "slip", sol, 0, *extra)], dtype=np.uint64)
    k_cam = np.asarray([derive(seed, "cam", sol, 0, *extra)], dtype=np.uint64)
    k_bab = np.asarray([derive(seed, "babble", sol, 0)], dtype=np.uint64)
    rover = state["rover"]
    safe = list(rover.get("safe_pending", []))
    explore_scale = 2.0 if "noise_doubled" in safe else 1.0
    rb = RoverBatch.from_rover(rover, 1)
    if brain.prev_u is None:
        brain.prev_u = np.asarray([rover["prev_u"]], dtype=np.float64)
    W, H, _, D = camera_spec(stage, params)
    suns = sun_at(sol, np.arange(T), params)
    rec = TraceRecorder(sol, stage, (W, H), brain.snapshot(), ev) if record else None
    win = _window(world, rb.x[0], rb.y[0])
    mask_zero = np.zeros((0, 0), dtype=np.uint8)
    mask = mask_zero
    odo0 = float(rb.odometer[0])
    couples, trail, zs = [], [], []
    acc = None
    last_meas = None
    cam = None
    awake_ticks = night_drive = 0
    bat_min, bat_min_tick = float(rb.battery[0]), 0
    tilt2 = 0.0
    slip_sum, slip_cnt = [0.0] * 4, [0] * 4
    mode = rover["mode"]
    m1_pair = None                                   # (pred, meas) of the last awake segment (F-03)
    m1_hidden = int(P("brain.m1.hidden"))
    arrive_r = float(P("brain.arrive_r"))
    targets_reached = 0
    reversed_free = False
    anomaly_seen = False
    anomalies = [o for o in state.get("overlays", []) if o.get("kind") == "anomaly" and not o.get("seen_sol")]
    prev_target = None
    for tick in range(T):
        sun = Sun(elev=suns.elev[tick], dir_x=suns.dir_x[tick], dir_y=suns.dir_y[tick], dir_z=suns.dir_z[tick],
                  hour=suns.hour[tick], day_length=suns.day_length)
        if not bool(win.contains(rb.x, rb.y, 64.0)[0]):
            win = _window(world, rb.x[0], rb.y[0])
        cam = capture(rb, win, stage, sun, ev, k_cam, tick, params, want_seen=True) if tick % period == 0 else None
        ctx = ActCtx(sol=sol, tick=tick, stage=stage, sun=sun, ev=ev, win=win, explored_mask=mask,
                     explore_scale=explore_scale, keys_babble=k_bab)
        if stage >= 2 and prev_target is not None and not bool(rb.forced[0]):   # arrival (F-01): the same test as Brain._update_targets
            if math.sqrt((prev_target[0] - float(rb.x[0])) ** 2 + (prev_target[1] - float(rb.y[0])) ** 2) < arrive_r:
                targets_reached += 1
        out = brain.act(rb, cam, ctx)
        prev_target = None if brain.target is None else (float(brain.target[0, 0]), float(brain.target[0, 1]))
        mode = out.mode[0]
        asleep = mode == "SLEEP"
        if cam is not None:
            if not asleep:                                   # camera is off in sleep: no cell is seen
                explored.mark(cam.seen[:, 0], cam.seen[:, 1], sol)
                for o in anomalies:                      # A7: an anomaly is "seen" when one of its cells enters trace.seen
                    if not o.get("seen_sol") and bool(np.any((np.abs(cam.seen[:, 0] - o["x"]) <= o["r"])
                                                             & (np.abs(cam.seen[:, 1] - o["y"]) <= o["r"]))):
                        o["seen_sol"] = sol
                        anomaly_seen = True
                if rec is not None:
                    rec.mark_seen(cam.seen, tick)
            if stage >= 2:
                mask = explored.window_mask(win.x0, win.y0, win.height.shape[1], win.height.shape[0])
            if out.z is not None:
                zs.append(out.z[0])
            if rec is not None:
                dark = np.full((H, W), consts.DARK[0], dtype=np.uint8)
                rec.add_frame(FrameRecord(
                    tick=tick, hour=float(sun.hour), mode=mode,
                    cam_index=dark if asleep else cam.index[0].copy(),
                    cam_depth=np.full((H, W), D, dtype=np.uint8) if asleep else cam.depth[0].copy(), D=D,
                    z=None if out.z is None else out.z[0].copy(), f=None if out.f is None else out.f[0].copy(),
                    x=out.x[0].copy(), h=out.h[0].copy(), y=out.y[0].copy(), u=out.u[0].copy(), xi=out.xi[0].copy(),
                    m1_pred=None if m1_pair is None else m1_pair[0].copy(),
                    m1_meas=None if m1_pair is None else m1_pair[1].copy(),
                    m3_out=None if out.m3_out is None else out.m3_out[0].copy(),
                    speed=abs(float(rb.enc_l[0] + rb.enc_r[0])) * 0.5 * vmax, battery=float(rb.battery[0]),
                    pitch=float(rb.pitch[0]), roll=float(rb.roll[0]), slip=float(rb.slip[0]),
                    solar=float(rb.solar_in[0]),
                    sun_elev=float(sun.elev), sun_dx=float(sun.dir_x), sun_dy=float(sun.dir_y),
                    pose=(float(rb.x[0]), float(rb.y[0]), float(rb.c[0]), float(rb.s[0])), target=prev_target if stage >= 2 else None,
                    stuck=bool(rb.stuck[0]), tipped=bool(rb.tipped[0]), asleep=asleep))
        if tick % trail_every == 0:
            trail.append([float(rb.x[0]), float(rb.y[0]), float(sol)])
        gt = int(win.gtype_at(rb.x, rb.y)[0])
        if tick % seg == 0:
            acc = {"x": float(rb.x[0]), "y": float(rb.y[0]), "c": float(rb.c[0]), "s": float(rb.s[0]), "n": 0, "awake": True,
                   "u": [0.0, 0.0], "pitch": 0.0, "roll": 0.0, "slip": 0.0, "w": 0.0, "gt": [0, 0, 0, 0]}
        rb.asleep = np.asarray([asleep])
        gx0, gy0 = win.gradient_at(rb.x, rb.y) if mode == "SEEK_SUN" else (None, None)
        was_stuck = bool(rb.stuck[0])
        physics_step(rb, out.u, win, sun, ev, k_slip, tick, None, params)
        if was_stuck and not bool(rb.stuck[0]):                 # freed by the physics (reverse command held)
            reversed_free = True
        if mode == "SEEK_SUN" and not bool(rb.forced[0]):        # F-02: SEEK_SUN = panel 1 (SPEC 4.8), same bonus as the M3 rollouts
            bonus = P("rover.energy.solar") * float(sun.elev) * (1.0 - panel_factor(gx0, gy0, sun, params)) * ev.solar_factor
            rb.battery = np.clip(rb.battery + bonus, 0.0, 1.0)
            rb.solar_in = rb.solar_in + bonus
        if not (bool(np.all(np.isfinite(rb.x))) and bool(np.all(np.isfinite(rb.battery)))):
            raise NonFiniteError("episode")
        acc["n"] += 1
        acc["awake"] = acc["awake"] and not asleep
        acc["u"][0] += float(out.u[0, 0]); acc["u"][1] += float(out.u[0, 1])
        acc["pitch"] += float(rb.pitch[0]); acc["roll"] += float(rb.roll[0]); acc["slip"] += float(rb.slip[0])
        acc["w"] += float(rb.enc_r[0] - rb.enc_l[0]) * vmax / track
        acc["gt"][gt] += 1
        if not asleep:
            awake_ticks += 1
            slip_sum[gt] += float(rb.slip[0])
            slip_cnt[gt] += 1
            if float(sun.elev) <= 0.0 and mode == "DRIVE":
                night_drive += 1
        if float(rb.battery[0]) < bat_min:
            bat_min, bat_min_tick = float(rb.battery[0]), tick
        tilt2 = max(tilt2, float(rb.pitch[0]) ** 2 + float(rb.roll[0]) ** 2)
        if tick % seg == seg - 1:
            n = float(acc["n"])
            dx, dy = float(rb.x[0]) - acc["x"], float(rb.y[0]) - acc["y"]
            meas = np.asarray([dx * acc["c"] + dy * acc["s"], -dx * acc["s"] + dy * acc["c"], acc["w"]])
            last_meas = meas
            if acc["awake"]:
                if stage >= 1:                                      # F-03: prediction and measure of the SAME segment
                    inp = np.asarray([[acc["u"][0] / n, acc["u"][1] / n, acc["pitch"] / n, acc["roll"] / n, acc["slip"] / n]])
                    m1_pair = (predict(brain.b["m1"], inp, m1_hidden)[0], meas.copy())
                gmaj = int(np.argmax(np.asarray(acc["gt"])))
                couples.append([acc["u"][0] / n, acc["u"][1] / n, acc["pitch"] / n, acc["roll"] / n, acc["slip"] / n,
                                float(meas[0]), float(meas[1]), float(meas[2]), float(sol), float(gmaj)])
    r = rb.to_rover(0)
    r["prev_u"] = [float(brain.prev_u[0, 0]), float(brain.prev_u[0, 1])]
    r["mode"] = mode
    r["safe_pending"] = []
    state["rover"] = r
    dist_cells = float(rb.odometer[0]) - odo0
    worst = None
    means = [(slip_sum[g] / slip_cnt[g]) if slip_cnt[g] else 0.0 for g in range(4)]
    if max(means) >= 0.2:
        worst = consts.GTYPE_NAMES[int(np.argmax(np.asarray(means)))]
    facts = {
        "sol": sol, "stage": stage, "distance_m": dist_cells * cm, "awake_cells": dist_cells, "awake_ticks": awake_ticks,
        "forced_sleep_ticks": int(rb.forced_sleep_ticks[0]), "breakdowns": int(rb.breakdowns[0]),
        "night_drive_ticks": night_drive, "targets_reached": targets_reached, "stuck": bool(rb.stuck[0]), "tipped": bool(rb.tipped[0]),
        "anomaly_seen": anomaly_seen,
        "freed_by": "reverse" if reversed_free else ("safe_mode" if "freed" in safe else None),
        "max_tilt_deg": float(dmath.atan(math.sqrt(tilt2))) * (180.0 / math.pi),
        "battery_min": bat_min, "battery_min_hour": float(suns.hour[bat_min_tick]), "slip_worst_terrain": worst,
        "safe_actions": safe, "couples_sol": len(couples), "events": list(ev.kinds),
    }
    data = SolData(couples=np.asarray(couples, dtype=np.float64).reshape(-1, 10),
                   frames_z=np.asarray(zs, dtype=np.float64).reshape(-1, 40),
                   path=np.asarray(trail, dtype=np.float64).reshape(-1, 3), breakdowns=int(rb.breakdowns[0]), samples=[])
    return (rec.finish() if rec is not None else None), data, facts
