"""Energy model (SPEC 3.3). Unit = fraction of the capacity."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.types import SolEvents, Sun

Arr = np.ndarray


def _sun3(sun: Sun):
    sxy = np.sqrt(np.maximum(0.0, 1.0 - sun.dir_z * sun.dir_z))
    return sun.dir_x * sxy, sun.dir_y * sxy, sun.dir_z


def panel_factor(gx: Arr, gy: Arr, sun: Sun, params: Params) -> Arr:
    """panel = 0.75 + 0.25 * max(0, n . sun); n = terrain normal (z up) from gradients in m per cell."""
    cm = params.get("world.cell_m")
    nx, ny = -gx / cm, -gy / cm
    nn = np.sqrt(nx * nx + ny * ny + 1.0)
    sx, sy, sz = _sun3(sun)
    dot = (nx * sx + ny * sy + sz) / nn
    pb = params.get("rover.energy.panel_base")
    return pb + (1.0 - pb) * np.maximum(0.0, dot)


def energy_step(rb, u: Arr, pitch: Arr, gx: Arr, gy: Arr, sun: Sun, ev: SolEvents, params: Params,
                drilling: Arr | None, temp: Arr | None = None) -> None:
    E = params.get("rover.energy")
    elev = float(sun.elev)
    motors = E["motor"] * (np.abs(u[:, 0]) + np.abs(u[:, 1])) * 0.5 * (1.0 + E["motor_slope"] * np.maximum(0.0, pitch))
    cost = E["base"] + motors
    if elev <= 0.0:
        # SPEC 2: cold = clip(1 - (0.6 T + 0.4 warmth), 0, 1), warmth = 0.5 + 0.5 sin(2 pi phi); sin(2 pi phi) is read back
        # from the day length L = base + amp * sin(2 pi phi) (same sun object, no second source of truth)
        sp = (sun.day_length - params.get("world.day_base_h")) / params.get("world.day_amp_h")
        warmth = 0.5 + 0.5 * sp
        T = 0.5 if temp is None else temp
        cold = np.clip(1.0 - (0.6 * T + 0.4 * warmth), 0.0, 1.0)
        cost = cost + E["heater"] * (1.0 + cold)
    if drilling is not None:
        cost = cost + E["drill"] * drilling
    solar = E["solar"] * elev * panel_factor(gx, gy, sun, params) * ev.solar_factor
    rb.solar_in = solar
    rb.battery = np.clip(rb.battery + solar - cost, 0.0, 1.0)
    newly = (~rb.forced) & (rb.battery <= E["cutoff"])
    rb.breakdowns = rb.breakdowns + newly
    rb.forced = (rb.forced | newly) & ~(rb.battery >= E["resume"])
    rb.forced_sleep_ticks = rb.forced_sleep_ticks + rb.forced
