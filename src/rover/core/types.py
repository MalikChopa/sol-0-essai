"""Dataclasses shared between layers (SPEC 6.2). No logic. FROZEN until J6: additions with defaults only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

Arr = np.ndarray


@dataclass(frozen=True)
class Sun:
    elev: Arr
    dir_x: Arr
    dir_y: Arr
    dir_z: Arr      # = elev
    hour: Arr
    day_length: float


@dataclass(frozen=True)
class SolEvents:
    storm: bool
    storm_left: int
    view_scale: float
    solar_factor: float
    slip_add: float
    new_overlays: list
    kinds: list


@dataclass
class CamFrame:
    index: Arr                      # (B, H, W) uint8
    depth: Arr                      # (B, H, W) uint8
    seen: Optional[Arr]             # (n, 2) int64 cells (rover 0)
    D: int


@dataclass(frozen=True)
class BrainSnapshot:
    stage: int
    m0: Arr
    m1: Optional[Arr]
    m2_w: Optional[Arr]
    m2_mean: Optional[Arr]
    m2_var: Optional[Arr]
    m3: Optional[Arr]


@dataclass
class StepOut:
    u: Arr
    mode: list
    x: Arr
    h: Arr
    y: Arr
    xi: Arr
    segment_end: Arr
    z: Optional[Arr]
    f: Optional[Arr]
    m1_pred: Optional[Arr]
    m3_out: Optional[Arr]


@dataclass(frozen=True)
class Progress:
    fraction: float
    label_en: str
    value_text_en: str
    blocking: str                   # "metric" | "streak" | "min_duration" | "none"


@dataclass
class FrameRecord:
    tick: int
    hour: float
    mode: str
    cam_index: Arr
    cam_depth: Arr
    D: int
    z: Optional[Arr]
    f: Optional[Arr]
    x: Arr
    h: Arr
    y: Arr
    u: Arr
    xi: Arr
    m1_pred: Optional[Arr]
    m1_meas: Optional[Arr]
    m3_out: Optional[Arr]
    speed: float                    # cells per tick
    battery: float
    pitch: float
    roll: float
    slip: float
    solar: float
    sun_elev: float
    sun_dx: float
    sun_dy: float
    pose: tuple                     # (x, y, c, s)
    target: Optional[tuple]
    stuck: bool
    tipped: bool
    asleep: bool


@dataclass
class Trace:
    sol: int
    stage: int
    acuity: tuple
    frames: list
    snapshot: BrainSnapshot
    events: SolEvents
    seen: Arr                       # (n, 3) int64: x, y, first tick seen


@dataclass
class SolData:
    couples: Arr
    frames_z: Arr
    path: Arr
    breakdowns: int
    samples: list


@dataclass(frozen=True)
class JournalEntry:
    epoch: int
    sol: int
    utc: str
    fr: str
    en: str


class NonFiniteError(ArithmeticError):
    """Raised on NaN/inf by learn or the episode (triggers the attempts of ARCH 4)."""

    def __init__(self, module: str):
        super().__init__(module)
        self.module = module
