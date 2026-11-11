"""Recorder of the sol (EF-70). FROZEN until J6: the only source of the renders. Types: core.types (Trace, FrameRecord)."""
from __future__ import annotations

import numpy as np

from rover.core.types import BrainSnapshot, FrameRecord, SolEvents, Trace

Arr = np.ndarray


class TraceRecorder:
    def __init__(self, sol: int, stage: int, acuity: tuple, snapshot: BrainSnapshot, events: SolEvents):
        self.sol, self.stage, self.acuity = sol, stage, acuity
        self.snapshot, self.events = snapshot, events
        self.frames: list[FrameRecord] = []
        self._seen: dict[tuple[int, int], int] = {}      # (x, y) -> first tick seen, insertion order

    def add_frame(self, rec: FrameRecord) -> None:
        self.frames.append(rec)

    def mark_seen(self, cells: Arr, tick: int) -> None:
        for x, y in np.asarray(cells, dtype=np.int64).tolist():
            if (x, y) not in self._seen:
                self._seen[(x, y)] = tick

    def finish(self) -> Trace:
        arr = np.asarray([[x, y, t] for (x, y), t in self._seen.items()], dtype=np.int64).reshape(-1, 3)
        return Trace(sol=self.sol, stage=self.stage, acuity=self.acuity, frames=self.frames, snapshot=self.snapshot,
                     events=self.events, seen=arr)
