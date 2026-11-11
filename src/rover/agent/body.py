"""Batch of rovers (SPEC 6.4): arrays of shape (B,)."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

Arr = np.ndarray


@dataclass
class RoverBatch:
    x: Arr
    y: Arr
    c: Arr
    s: Arr
    battery: Arr
    stuck: Arr
    tipped: Arr
    asleep: Arr
    sink_n: Arr
    rev_n: Arr
    enc_l: Arr
    enc_r: Arr
    pitch: Arr
    roll: Arr
    slip: Arr
    solar_in: Arr
    odometer: Arr
    breakdowns: Arr
    forced_sleep_ticks: Arr
    forced: Arr = None          # added (contract addition J0): hardware forced sleep flag (battery <= cutoff until >= resume)
    extra: dict = field(default_factory=dict)    # prev_u, mode, safe_pending of the source rover dict

    @classmethod
    def from_rover(cls, rover: dict, b: int = 1) -> "RoverBatch":
        f = lambda v: np.full(b, v, dtype=np.float64)
        i = lambda v: np.full(b, v, dtype=np.int64)
        t = lambda v: np.full(b, v, dtype=bool)
        return cls(x=f(rover["x"]), y=f(rover["y"]), c=f(rover["c"]), s=f(rover["s"]), battery=f(rover["battery"]),
                   stuck=t(rover["stuck"]), tipped=t(rover["tipped"]), asleep=t(rover["asleep"]),
                   sink_n=i(rover["sink_n"]), rev_n=i(rover["rev_n"]), enc_l=f(0.0), enc_r=f(0.0), pitch=f(0.0),
                   roll=f(0.0), slip=f(0.0), solar_in=f(0.0), odometer=f(rover["odometer"]), breakdowns=i(0),
                   forced_sleep_ticks=i(0), forced=t(bool(rover["asleep"]) and rover["battery"] < 0.40),
                   extra={"prev_u": list(rover["prev_u"]), "mode": rover["mode"],
                          "safe_pending": list(rover["safe_pending"])})

    def to_rover(self, i: int = 0) -> dict:
        e = copy.deepcopy(self.extra)
        return {"x": float(self.x[i]), "y": float(self.y[i]), "c": float(self.c[i]), "s": float(self.s[i]),
                "battery": float(self.battery[i]), "stuck": bool(self.stuck[i]), "tipped": bool(self.tipped[i]),
                "asleep": bool(self.asleep[i]), "sink_n": int(self.sink_n[i]), "rev_n": int(self.rev_n[i]),
                "odometer": float(self.odometer[i]), "prev_u": e["prev_u"], "mode": e["mode"],
                "safe_pending": e["safe_pending"]}
