"""Performance budgets of ARCH 10 J1 (Mac). Run with: py -m pytest -q -m perf tests/agent"""
from __future__ import annotations

import time

import numpy as np
import pytest

from rover.agent import capture
from rover.core.rng import derive
from rover.core.types import SolEvents
from rover.world import World, sun_at

from agent_helpers import SEED, keys_for, random_batch

pytestmark = pytest.mark.perf
NO_EV = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])


def _median_ms(fn, n):
    ts = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        ts.append((time.perf_counter() - t) * 1e3)
    return sorted(ts)[len(ts) // 2]


def test_chunk_all_layers_under_5_ms(params):
    w = World(SEED, params)
    ms = _median_ms(lambda i: w.chunk(300 + i, -40), 30)       # height, dune, rock, grain, temp, type: uncached chunks
    print(f"chunk all layers: {ms:.2f} ms")
    assert ms <= 5.0


def test_image_160x100_with_noise_and_palette_under_1_ms(win, params):
    rb = random_batch(1, 21)
    k = keys_for(1)
    sun = sun_at(9, 600, params)
    capture(rb, win, 4, sun, NO_EV, k, 0, params)
    ms = _median_ms(lambda i: capture(rb, win, 4, sun, NO_EV, k, 8 * (i + 1), params), 40)
    print(f"160x100 image: {ms:.3f} ms")
    assert ms <= 1.0


def test_batch_96_in_80x50_under_30_ms(win, params):
    rb = random_batch(96, 22)
    k = keys_for(96)
    sun = sun_at(9, 600, params)
    capture(rb, win, 3, sun, NO_EV, k, 0, params)
    ms = _median_ms(lambda i: capture(rb, win, 3, sun, NO_EV, k, 8 * (i + 1), params), 15)
    print(f"batch 96 x 80x50: {ms:.2f} ms")
    assert ms <= 30.0
