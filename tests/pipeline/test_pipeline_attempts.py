"""Attempts k = 1, 2, 3, passive sol, refusal paths, check, restore, tags, main_lag (J5, through the CLI and run_sol)."""
from __future__ import annotations

import copy
import json
import shutil

import numpy as np
import pytest

from conftest import NOW, play, run_cli
from rover import config
from rover.pipeline import check_dir, fresh_state, run_sol, simulate
from rover.pipeline import sol as sol_mod
from rover.state import Explored, core_bytes, core_for_compare, load


def _status(d):
    return json.loads((d / "status.json").read_text())


def _journal_text(root):
    return "".join(f.read_text(encoding="utf-8") for f in sorted((root / "main" / "journal").glob("2026-*.md")))


def _fail_on(monkeypatch, ks, exc=RuntimeError):
    orig = sol_mod._attempt
    calls = []

    def wrapper(state, explored, params, now_utc, k, *a, **kw):
        calls.append(k)
        if k in ks:
            raise exc("injected")
        return orig(state, explored, params, now_utc, k, *a, **kw)
    monkeypatch.setattr(sol_mod, "_attempt", wrapper)
    return calls


# ---- EF-02: the sol never comes from the clock -------------------------------------------------------------
def test_sol_number_is_state_plus_one_whatever_the_clock(params):
    s = fresh_state(params)
    a = run_sol(s, Explored(), params, "2026-11-11T07:17:00Z", render=False, narrative=False)
    b = run_sol(s, Explored(), params, "2031-01-01T00:00:00Z", render=False, narrative=False)
    assert a.state["sol"] == b.state["sol"] == 1
    assert core_bytes(core_for_compare(a.state)) == core_bytes(core_for_compare(b.state))
    assert s["sol"] == 0                                    # the input state is never modified


def test_input_state_and_explored_are_not_modified(params):
    s = fresh_state(params)
    ex = Explored()
    snap = core_bytes(s)
    run_sol(s, ex, params, "2026-11-11T07:17:00Z", render=False, narrative=False)
    assert core_bytes(s) == snap and ex.cells() == 0


# ---- attempts -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ks,attempts", [({0}, 1), ({0, 1}, 2)])
def test_exception_gives_a_later_attempt(params, monkeypatch, ks, attempts):
    s = fresh_state(params)
    calls = _fail_on(monkeypatch, ks)
    r = run_sol(s, Explored(), params, NOW[0], render=False, narrative=False)
    assert calls == list(range(attempts + 1)) and r.state["health"]["attempts"] == attempts
    assert r.state["health"]["incident"] is None and r.state["sol"] == 1
    assert (r.state["health"]["last_degraded"] == 1) is True


def test_systematic_exception_gives_a_passive_sol_then_a_normal_one(params, monkeypatch):
    s = fresh_state(params)
    with monkeypatch.context() as m:
        calls = _fail_on(m, {0, 1, 2}, ValueError)
        r = run_sol(s, Explored(), params, NOW[0], render=False, narrative=False)
    assert calls == [0, 1, 2]
    h = r.state["health"]
    assert (h["attempts"], h["incident"], h["passive_streak"]) == (3, "ValueError", 1) and r.state["sol"] == 1
    assert r.trace is None and r.images == {}                      # first sol: nothing to copy
    assert r.state["journal_tail"][-1]["fr"] and "ValueError" in r.state["journal_tail"][-1]["en"]
    r2 = run_sol(r.state, r.explored, params, NOW[1], render=False, narrative=False)       # next sol: normal
    h2 = r2.state["health"]
    assert (h2["attempts"], h2["incident"], h2["passive_streak"]) == (0, None, 0) and r2.state["sol"] == 2
    assert r2.state["journal_tail"] == r.state["journal_tail"]            # narrative=False appends nothing


def test_check_result_refusal_goes_to_the_next_attempt(params, monkeypatch):
    s = fresh_state(params)
    seen = []

    def refuse_once(res, prev, prev_files, p):
        seen.append(res.state["health"]["attempts"])
        return ["refused for the test"] if len(seen) == 1 else []
    monkeypatch.setattr(sol_mod, "check_result", refuse_once)
    r = run_sol(s, Explored(), params, NOW[0], render=False, narrative=False)
    assert seen == [0, 1] and r.state["health"]["attempts"] == 1


def test_passive_sol_itself_failing_propagates(params, monkeypatch):
    _fail_on(monkeypatch, {0, 1, 2})
    monkeypatch.setattr(sol_mod, "_passive", lambda *a, **k: (_ for _ in ()).throw(OSError("passive failed")))
    with pytest.raises(OSError):
        run_sol(fresh_state(params), Explored(), params, NOW[0], render=False, narrative=False)


@pytest.mark.parametrize("where", ["encode_gif", "compose_entry"])
def test_exception_in_render_or_narrative_gives_a_published_passive_sol(chain3, tmp_path, monkeypatch, where):
    """The audit rule: the passive sol calls no render and no narrative code; the sol after it is normal."""
    prev = chain3 / "s2"
    out = tmp_path / "s3"
    with monkeypatch.context() as m:
        m.setattr(sol_mod, where, lambda *a, **k: (_ for _ in ()).throw(RuntimeError(where)))
        # a passive sol must not call these either: they would raise again
        for name in ("status_svg", "map_png", "detect_firsts", "write_pages"):
            m.setattr(sol_mod, name, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("called by the passive sol")))
        assert run_cli("sol", "--in", prev, "--out", out, "--main", tmp_path / "main", "--now", NOW[2]) == 0
    st = _status(out)["det"]
    assert st["sol"] == 3 and st["incident"] == "RuntimeError" and st["attempts"] == 3 and st["passive_streak"] == 1
    assert "images_from_sol_2" in st["warnings"]
    for n in ("console.gif", "status.svg", "map.png"):
        assert (out / n).read_bytes() == (prev / n).read_bytes()           # copied byte for byte from _in
    assert run_cli("check", "--dir", out, "--prev", prev) == 0
    assert not (tmp_path / "main" / "journal").exists()                      # a passive sol writes no pages
    out2 = tmp_path / "s4"
    assert run_cli("sol", "--in", out, "--out", out2, "--main", tmp_path / "main", "--now", NOW[3]) == 0
    st2 = _status(out2)["det"]
    assert st2["sol"] == 4 and st2["incident"] is None and st2["passive_streak"] == 0 and st2["attempts"] == 0
    j = (tmp_path / "main" / "journal" / "2026-11.md").read_text(encoding="utf-8")
    assert "Sol 0003" in j and "Sol 0004" in j and "RuntimeError" in j       # the incident line reaches main afterwards
    assert run_cli("check", "--dir", out2, "--prev", out) == 0


def test_passive_failure_in_the_cli_is_code_4_and_writes_nothing(chain3, tmp_path, monkeypatch):
    _fail_on(monkeypatch, {0, 1, 2})
    monkeypatch.setattr(sol_mod, "_passive", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    out = tmp_path / "o"
    assert run_cli("sol", "--in", chain3 / "s1", "--out", out, "--main", tmp_path / "m", "--now", NOW[1]) == 4
    assert not out.exists() and not (tmp_path / "m").exists()


# ---- faults, refusals ------------------------------------------------------------------------------------------
def test_fault_needs_the_trial_variable(chain3, tmp_path, monkeypatch):
    monkeypatch.delenv("SOL0_TRIAL", raising=False)
    out = tmp_path / "o"
    assert run_cli("sol", "--in", chain3 / "s1", "--out", out, "--main", tmp_path / "m", "--now", NOW[1], "--fault", "nan") == 2
    assert not out.exists()


def test_fault_nan_publishes_a_sol_at_attempt_1(chain3, tmp_path, monkeypatch):
    monkeypatch.setenv("SOL0_TRIAL", "1")
    out = tmp_path / "o"
    assert run_cli("sol", "--in", chain3 / "s1", "--out", out, "--main", tmp_path / "m", "--now", NOW[1], "--fault", "nan") == 0
    st = _status(out)["det"]
    assert st["attempts"] == 1 and st["sol"] == 2 and st["incident"] is None and st["degraded"] is True
    assert run_cli("check", "--dir", out, "--prev", chain3 / "s1") == 0


def test_fault_corrupt_restores_and_bumps_the_epoch(chain3, tmp_path, monkeypatch):
    monkeypatch.setenv("SOL0_TRIAL", "1")
    out = tmp_path / "o"
    before = (chain3 / "s2" / "state" / "core.json.gz").read_bytes()
    assert run_cli("sol", "--in", chain3 / "s2", "--out", out, "--main", tmp_path / "m", "--now", NOW[2], "--fault", "corrupt") == 0
    assert (chain3 / "s2" / "state" / "core.json.gz").read_bytes() == before          # the input is never touched
    st = _status(out)["det"]
    assert st["epoch"] == 2 and st["restored_from"] == "sol-000002" and st["sol"] == 3
    lr = load(out, config.load())
    assert lr.restored_from is None and lr.state["epoch"] == 2
    assert run_cli("check", "--dir", out, "--prev", chain3 / "s2") == 0


def test_foreign_dir_is_code_3_and_writes_nothing(tmp_path):
    src = tmp_path / "foreign"
    src.mkdir()
    (src / "README.md").write_text("someone else's branch")
    out, main = tmp_path / "o", tmp_path / "m"
    assert run_cli("sol", "--in", src, "--out", out, "--main", main, "--now", NOW[0]) == 3
    assert not out.exists() and not main.exists()
    assert sorted(p.name for p in src.iterdir()) == ["README.md"]


def test_state_newer_than_the_code_is_code_3_and_writes_nothing(chain3, tmp_path):
    src = tmp_path / "newer"
    shutil.copytree(chain3 / "s1", src)
    from rover.state import save
    params = config.load()
    lr = load(src, params)
    s = copy.deepcopy(lr.state)
    s["stage"]["id"] = 4                                   # > MAX_STAGE (3): the code must not touch it
    shutil.rmtree(src / "state")
    save(s, lr.explored, src, {}, {"det": {"sol": 1}, "run": {}})
    out, main = tmp_path / "o", tmp_path / "m"
    assert run_cli("sol", "--in", src, "--out", out, "--main", main, "--now", NOW[1]) == 3
    assert not out.exists() and not main.exists()


def test_bad_arguments_are_code_2(chain3, tmp_path):
    base = ["sol", "--in", chain3 / "s1", "--out", tmp_path / "o", "--main", tmp_path / "m"]
    assert run_cli(*base, "--now", "yesterday") == 2
    assert run_cli("sol", "--in", chain3 / "s1", "--out", chain3 / "s1", "--main", tmp_path / "m", "--now", NOW[1]) == 2
    assert run_cli("restore", "--in", chain3 / "s3", "--out", tmp_path / "r", "--checkpoint", "../etc") == 2
    assert run_cli("restore", "--in", chain3 / "s3", "--out", tmp_path / "r", "--checkpoint", "sol-000099") == 2
    assert run_cli("bench", "--only", "nonsense") == 2
    assert not (tmp_path / "o").exists()


# ---- restore + checkpoints > K ---------------------------------------------------------------------------------
def test_manual_restore_then_chain_continues(chain3, tmp_path):
    r = tmp_path / "restored"
    assert run_cli("restore", "--in", chain3 / "s3", "--out", r, "--checkpoint", "sol-000001", "--now", NOW[3]) == 0
    st = _status(r)["det"]
    assert st["sol"] == 1 and st["epoch"] == 2 and st["restored_from"] == "sol-000001" and "manual_restore" in st["warnings"]
    ck = sorted(p.name for p in (r / "state" / "checkpoints").glob("sol-*.json.gz"))
    assert ck == ["sol-000001.json.gz"]       # checkpoints > 1 are gone
    assert (chain3 / "s3" / "state" / "checkpoints" / "sol-000003.json.gz").is_file()   # the input is untouched
    assert run_cli("check", "--dir", r, "--prev", chain3 / "s3") == 0
    # the cells seen during the abandoned sols stay explored
    assert load(r, config.load()).explored.cells() >= load(chain3 / "s3", config.load()).explored.cells()
    nxt = tmp_path / "next"
    assert run_cli("sol", "--in", r, "--out", nxt, "--main", tmp_path / "main", "--now", NOW[4]) == 0
    st2 = _status(nxt)["det"]
    assert st2["sol"] == 2 and st2["epoch"] == 2 and st2["restored_from"] is None
    assert run_cli("check", "--dir", nxt, "--prev", r) == 0
    j = (tmp_path / "main" / "journal" / "2026-11.md").read_text(encoding="utf-8")
    assert "epoch 2" in j


def test_auto_restore_drops_newer_checkpoints(chain3, tmp_path):
    """Corrupt core + the newest checkpoint damaged too: restoration to sol-K removes the checkpoints numbered > K."""
    src = tmp_path / "in"
    shutil.copytree(chain3 / "s3", src)
    for rel in ("state/core.json.gz", "state/checkpoints/sol-000003.json.gz"):
        b = bytearray((src / rel).read_bytes())
        b[len(b) // 2] ^= 0xFF
        (src / rel).write_bytes(bytes(b))
    out = tmp_path / "out"
    assert run_cli("sol", "--in", src, "--out", out, "--main", tmp_path / "main", "--now", NOW[3]) == 0
    st = _status(out)["det"]
    assert st["restored_from"] == "sol-000002" and st["epoch"] == 2 and st["sol"] == 3
    names = sorted(p.name[:-len(".json.gz")] for p in (out / "state" / "checkpoints").glob("sol-*.json.gz"))
    assert names == ["sol-000001", "sol-000002", "sol-000003"]       # old 3 (corrupt) dropped, new 3 written
    assert load(out, config.load()).state["epoch"] == 2
    assert run_cli("check", "--dir", out, "--prev", src) == 0


# ---- check ------------------------------------------------------------------------------------------------------
def test_check_accepts_a_real_chain_and_sees_its_defects(chain3, tmp_path):
    params = config.load()
    assert check_dir(chain3 / "s2", chain3 / "s1", params) == []
    assert check_dir(chain3 / "s3", None, params) == []
    assert any("sol" in p for p in check_dir(chain3 / "s3", chain3 / "s1", params))          # skipped a sol
    d = tmp_path / "bad"
    shutil.copytree(chain3 / "s2", d)
    (d / "map.png").unlink()
    assert any("images missing" in p for p in check_dir(d, chain3 / "s1", params))
    shutil.copytree(chain3 / "s2", tmp_path / "bad2")
    c = tmp_path / "bad2" / "state" / "core.json.gz"
    b = bytearray(c.read_bytes())
    b[len(b) // 2] ^= 1
    c.write_bytes(bytes(b))
    assert any("restore" in p for p in check_dir(tmp_path / "bad2", chain3 / "s1", params))
    assert check_dir(tmp_path / "nothing", None, params)
    shutil.copytree(chain3 / "s2", tmp_path / "bad3")
    (tmp_path / "bad3" / "console.gif").write_bytes(b"GIF89a-not-a-gif")
    assert any("console.gif" in p for p in check_dir(tmp_path / "bad3", chain3 / "s1", params))


def test_check_with_an_empty_prev_means_the_first_sol(chain3, tmp_path):
    (tmp_path / "empty").mkdir()
    params = config.load()
    assert check_dir(chain3 / "s1", tmp_path / "empty", params) == []
    assert any("sol" in p for p in check_dir(chain3 / "s2", tmp_path / "empty", params))


# ---- tags and main_lag ------------------------------------------------------------------------------------------
def test_tags_file_lists_this_sols_firsts_from_out(chain3):
    t1 = (chain3 / "tags1.txt").read_text().split("\n")
    assert all(line.endswith(" _out") for line in t1 if line)
    st = load(chain3 / "s1", config.load()).state
    assert sorted(line.split()[0] for line in t1 if line) == sorted(st["pending_tags"])


def test_previous_pending_tags_are_reproposed_from_in(chain3, tmp_path):
    src = tmp_path / "in"
    shutil.copytree(chain3 / "s1", src)
    pend = load(src, config.load()).state["pending_tags"]
    assert pend, "the first sol must have at least one first-time tag"
    out = tmp_path / "out"
    assert run_cli("sol", "--in", src, "--out", out, "--main", tmp_path / "m", "--now", NOW[1], "--tags", tmp_path / "t.txt") == 0
    lines = (tmp_path / "t.txt").read_text().split("\n")
    for t in pend:
        assert f"{t} _in" in lines
    assert all(not line.endswith(" _in") or line.split()[0] in pend for line in lines if line)


def test_main_lag_counts_entries_missing_from_main(chain3, tmp_path):
    # chain3 never pushed 'main' anywhere else than root/main; replay sol 3 against an empty main: 2 entries are missing
    out = tmp_path / "o"
    assert run_cli("sol", "--in", chain3 / "s2", "--out", out, "--main", tmp_path / "emptymain", "--now", NOW[2]) == 0
    assert _status(out)["det"]["main_lag"] == 2
    out2 = tmp_path / "o2"
    assert run_cli("sol", "--in", chain3 / "s2", "--out", out2, "--main", chain3 / "main", "--now", NOW[2]) == 0
    assert _status(out2)["det"]["main_lag"] == 0


def test_clock_going_backwards_is_noted(chain3, tmp_path):
    out = tmp_path / "o"
    assert run_cli("sol", "--in", chain3 / "s2", "--out", out, "--main", tmp_path / "m", "--now", "2026-11-01T00:00:00Z") == 0
    assert "clock_before_last_run" in _status(out)["det"]["warnings"]


# ---- simulate = sol ---------------------------------------------------------------------------------------------
def test_simulate_5_equals_5_sols_on_core_for_compare(tmp_path):
    params = config.load()
    sim = simulate(5, params, params.get("run.world_seed"), None)
    last = play(tmp_path, 5)
    lr = load(last, params)
    assert core_bytes(core_for_compare(lr.state)) == core_bytes(core_for_compare(sim["state"]))
    assert lr.explored.to_regions() == sim["explored"].to_regions()


def test_simulate_from_a_published_state_continues_it(chain3, tmp_path):
    params = config.load()
    lr = load(chain3 / "s2", params)
    a = simulate(1, params, 0, None, start=(lr.state, lr.explored))
    b = load(chain3 / "s3", params)
    assert core_bytes(core_for_compare(a["state"])) == core_bytes(core_for_compare(b.state))
    assert run_cli("simulate", "--sols", 1, "--seed", 1, "--from", chain3 / "s2", "--report", tmp_path / "r.csv") == 0
    assert (tmp_path / "r.csv").read_text().splitlines()[0].startswith("sol,")


def test_cli_simulate_and_bench_run(capsys):
    assert run_cli("simulate", "--sols", 1, "--seed", 7) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["sols"] == 1 and len(out["core_sha256"]) == 64
    assert run_cli("bench", "--only", "fresh_state") == 0
    assert list(json.loads(capsys.readouterr().out)) == ["fresh_state"]
