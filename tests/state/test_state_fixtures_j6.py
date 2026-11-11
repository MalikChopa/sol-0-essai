"""Corpus v1 (J6): REAL states of a 75-sol chain, frozen at SCHEMA_VERSION 1 (tools/make_fixtures.py).

stage2_storm  : state after sol 46, stage 2, a storm in progress (events.storm_left = 2).
stage3_impact : state after sol 74, stage 3 (M3 awake), with the overlay of the comet impact drawn by the real event generator
                for sol 2620 (a natural impact is 1 sol in 3000: no short chain reaches one).
Each is reloaded without restoration, round-trips byte-identically, and is replayed 3 sols (no rendering) with the replay
fingerprint pinned in expected.json (same fingerprint on every machine: tests/state refs of the corpus)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rover import version
from rover.core.hashing import sha256_hex
from rover.pipeline import run_sol
from rover.state import core_bytes, core_for_compare, encode_files, load, migrate_explored, validate

DIR = Path(__file__).resolve().parent / "fixtures" / "v1"
EXPECTED = json.loads((DIR / "expected.json").read_text())


def test_schema_version_is_frozen_at_1():
    assert version.SCHEMA_VERSION == 1


def test_explored_header_is_the_frozen_format():
    raw = (DIR / "stage2_storm" / "state" / "explored").glob("r_*.bin.gz")
    import gzip
    for p in sorted(raw)[:3]:
        b = gzip.decompress(p.read_bytes())
        assert b.startswith(b"SOL0EXP1") and migrate_explored(b) == b


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_loads_valid_roundtrips_and_replays(name, params):
    lr = load(DIR / name, params)
    assert lr.restored_from is None and lr.state is not None and validate(lr.state) == []
    s = lr.state
    assert s["schema_version"] == 1
    again = encode_files(s, lr.explored, {}, json.loads((DIR / name / "status.json").read_text()))
    assert again["state/core.json.gz"] == (DIR / name / "state" / "core.json.gz").read_bytes()
    exp = EXPECTED[name]
    assert s["sol"] == exp["sol"] and s["stage"]["id"] == exp["stage"]
    kinds = []
    ex = lr.explored
    for _ in range(3):
        res = run_sol(s, ex, params, "2026-11-20T07:17:00Z", render=False, narrative=False)
        assert res.state["health"]["attempts"] == 0
        kinds.append(list(res.facts["events"]))
        s, ex = res.state, res.explored
    assert kinds[0] == exp["events_first_sol"]
    assert sha256_hex(core_bytes(core_for_compare(s))) == exp["replay3_core_sha256"]


def test_battery_regression_restores_m0_from_the_checkpoint_in_the_real_pipeline(params):
    """F-04 (verifier I-3): on the real stage-2 state of the corpus, a recorded battery history far above the new measure
    for `regress_consecutive` sols restores M0 from the checkpoint of the best measure (warning + M0 equal to the
    checkpoint's), and the published measure is the one of the restored brain."""
    import copy
    import numpy as np
    from rover.state import checkpoint_loaders
    lr = load(DIR / "stage2_storm", params)
    s = copy.deepcopy(lr.state)
    B = params.get("brain.battery")
    stage = s["stage"]["id"]
    m = s["metrics"]
    m["battery"], m["battery_stage"], m["battery_sol"] = [10 ** 6], [stage], [s["sol"] - 1]
    m["battery_low"] = int(B["regress_consecutive"]) - 1
    ck = checkpoint_loaders(DIR / "stage2_storm", params)
    assert ck, "the corpus carries checkpoints"
    best_sol = s["sol"] - 1
    sentinel = copy.deepcopy(s["brain"]["m0"])
    for k in sentinel:                                       # a recognisable M0: the checkpoint's, not the learned one
        if isinstance(sentinel[k], np.ndarray) and sentinel[k].dtype.kind == "f":
            sentinel[k] = np.zeros_like(sentinel[k])
    res = run_sol(s, lr.explored, params, "2026-11-20T07:17:00Z", render=False, narrative=False,
                  ckpts={best_sol: lambda: sentinel})
    assert "battery_restored_from_sol_%d" % best_sol in res.status["det"]["warnings"]
    assert res.state["metrics"]["battery_low"] == 0
    assert res.state["metrics"]["battery_sol"][-1] == s["sol"] + 1
