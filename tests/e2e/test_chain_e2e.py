"""End to end through the CLI: chains, idempotence of a replayed run, properties of saved states (J5)."""
from __future__ import annotations

import json
import shutil

from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import NOW, run_cli
from rover import config
from rover.pipeline import fresh_state, run_sol
from rover.state import Explored, core_bytes, load, save, validate


def test_replayed_run_gives_the_same_published_state(chain3, tmp_path):
    """EF-02: relaunching a run from the same published state gives the same state and the same MANIFEST."""
    out = tmp_path / "again"
    assert run_cli("sol", "--in", chain3 / "s2", "--out", out, "--main", tmp_path / "m", "--now", NOW[2]) == 0
    assert (out / "state" / "MANIFEST.json").read_bytes() == (chain3 / "s3" / "state" / "MANIFEST.json").read_bytes()
    assert (out / "console.gif").read_bytes() == (chain3 / "s3" / "console.gif").read_bytes()


def test_a_later_clock_changes_nothing_but_the_text(chain3, tmp_path):
    out = tmp_path / "later"
    assert run_cli("sol", "--in", chain3 / "s2", "--out", out, "--main", tmp_path / "m", "--now", "2026-12-24T09:00:00Z") == 0
    a = load(out, config.load()).state
    b = load(chain3 / "s3", config.load()).state
    for s in (a, b):
        s.pop("journal_tail"), s.pop("last_run_utc")
    assert core_bytes(a) == core_bytes(b)


def test_every_sol_of_the_chain_is_checkable_and_within_budget(chain3):
    params = config.load()
    from rover.pipeline import check_dir
    prev = chain3 / "empty"
    for i in (1, 2, 3):
        d = chain3 / f"s{i}"
        assert check_dir(d, prev, params) == []
        gif = (d / "console.gif").stat().st_size
        assert gif <= params.get("render.gif_max_bytes")
        total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        assert total <= 20_000_000
        prev = d


@settings(max_examples=4)
@given(seed=st.integers(1, 10**6))
def test_any_saved_state_reloads_valid_and_equal(tmp_path_factory, seed):
    params = config.load()
    s = fresh_state(params, seed)
    ex = Explored()
    for i in range(2):
        r = run_sol(s, ex, params, NOW[i], render=False, narrative=False)
        s, ex = r.state, r.explored
    d = tmp_path_factory.mktemp("p")
    save(s, ex, d, {}, {"det": {"sol": s["sol"]}, "run": {}})
    lr = load(d, params)
    assert lr.restored_from is None and validate(lr.state) == []
    assert core_bytes(lr.state) == core_bytes(s)
    assert 0.0 <= lr.state["rover"]["battery"] <= 1.0
    assert lr.explored.to_regions() == ex.to_regions()
