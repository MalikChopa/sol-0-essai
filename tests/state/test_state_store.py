"""State store: exact round trip, corruption detected and restored, migrations, newer-than-code, checkpoints (J5)."""
from __future__ import annotations

import copy
import shutil

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rover import version
from rover.core.hashing import canonical_json
from rover.pipeline import fresh_state
from rover.state import (Explored, ForeignDirError, StateNewerError, carry_checkpoints, core_bytes, load, load_checkpoint,
                         migrate, migrate_explored, save, validate)
from rover.state import migrations as mig


@pytest.fixture(scope="module")
def base(params):
    return fresh_state(params)


def _explored(sol=1, extra=()):
    e = Explored()
    xs = np.asarray([0, 1, 2, 70, -70, 1100] + [x for x, _ in extra])
    ys = np.asarray([0, 0, 1, 5, 80, -900] + [y for _, y in extra])
    e.mark(xs, ys, sol)
    return e


def _save(state, explored, d, status=None):
    return save(state, explored, d, {}, status or {"det": {"sol": state["sol"]}, "run": {}})


def test_roundtrip_is_exact(tmp_path, params, base):
    s = copy.deepcopy(base)
    s["sol"] = 3
    s["memory"]["couples"] = np.arange(30, dtype=np.float32).reshape(3, 10) / 7
    e = _explored()
    _save(s, e, tmp_path)
    lr = load(tmp_path, params)
    assert lr.restored_from is None and lr.notes == [] and lr.cause is None
    assert core_bytes(lr.state) == core_bytes(s)
    assert lr.explored.cells() == e.cells()
    assert lr.explored.to_regions() == e.to_regions()
    assert validate(lr.state) == []


def test_save_is_byte_stable(tmp_path, base):
    _save(base, _explored(), tmp_path / "a")
    _save(base, _explored(), tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*")):
        if f.is_file():
            assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes()


def test_empty_and_foreign_dirs(tmp_path, params):
    assert load(tmp_path / "nope", params).state is None
    (tmp_path / "e").mkdir()
    assert load(tmp_path / "e", params).state is None
    (tmp_path / "f").mkdir()
    (tmp_path / "f" / "x.txt").write_text("not ours")
    with pytest.raises(ForeignDirError):
        load(tmp_path / "f", params)


@settings(max_examples=40)
@given(which=st.sampled_from(["core", "manifest", "region", "checkpoint", "sha"]), pos=st.integers(0, 10**6),
       x=st.integers(1, 255))
def test_any_single_byte_change_is_detected_or_harmless(tmp_path_factory, params, base, which, pos, x):
    d = tmp_path_factory.mktemp("c")
    s = copy.deepcopy(base)
    s["sol"] = 2
    _save(s, _explored(), d)
    target = {"core": d / "state/core.json.gz", "manifest": d / "state/MANIFEST.json",
              "region": next((d / "state/explored").glob("*.gz")),
              "checkpoint": d / "state/checkpoints/sol-000002.json.gz",
              "sha": d / "state/checkpoints/sol-000002.json.gz.sha256"}[which]
    b = bytearray(target.read_bytes())
    b[pos % len(b)] ^= x
    target.write_bytes(bytes(b))
    try:
        lr = load(d, params)
    except RuntimeError:
        return                                     # damaged beyond repair: refused, never invented
    if lr.restored_from is None:
        assert core_bytes(lr.state) == core_bytes(s)       # benign (e.g. gzip header, ascii newline): same content
    else:
        assert lr.state["epoch"] == s["epoch"] + 1 and lr.restored_from == "sol-000002"


def test_corrupt_core_is_restored_from_the_newest_checkpoint(tmp_path, params, base):
    d = tmp_path
    for sol in (1, 2, 3):
        s = copy.deepcopy(base)
        s["sol"] = sol
        carry_checkpoints(d, tmp_path / f"n{sol}") if (d / "state").is_dir() else None
        out = tmp_path / f"n{sol}"
        _save(s, _explored(sol), out)
        d = out
    core = d / "state/core.json.gz"
    b = bytearray(core.read_bytes())
    b[len(b) // 2] ^= 0xFF
    core.write_bytes(bytes(b))
    lr = load(d, params)
    assert lr.restored_from == "sol-000003" and lr.state["epoch"] == 2 and lr.state["health"]["restored_from"] == "sol-000003"
    assert lr.restore_cause == "corrupt" and lr.cause and lr.redone_sols == []
    assert lr.state["sol"] == 3 and validate(lr.state) == []


def test_no_valid_checkpoint_is_an_error(tmp_path, params, base):
    _save(base, Explored(), tmp_path)
    for f in (tmp_path / "state/checkpoints").glob("sol-*"):
        f.unlink()
    (tmp_path / "state/core.json.gz").write_bytes(b"garbage")
    with pytest.raises(RuntimeError):
        load(tmp_path, params)


def test_nan_in_the_loaded_state_is_a_corruption_not_code_3(tmp_path, params, base):
    s = copy.deepcopy(base)
    _save(s, Explored(), tmp_path)                       # healthy checkpoint
    bad = copy.deepcopy(base)
    bad["sol"] = 1
    bad["brain"]["m0"]["theta"][0] = np.float32("nan")
    # write the poisoned core the way an old buggy run would: valid gzip + sha, but a NaN inside (JSON allows it here)
    import gzip, json
    from rover.core.hashing import sha256_hex
    from rover.state.store import _enc
    raw = json.dumps(_enc(bad), sort_keys=True, separators=(",", ":"), allow_nan=True).encode()
    (tmp_path / "state/core.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    man = json.loads((tmp_path / "state/MANIFEST.json").read_text())
    man["files"]["state/core.json.gz"] = {"sha256": sha256_hex(raw), "size": len(raw)}
    man.pop("manifest_sha256")
    man["manifest_sha256"] = sha256_hex(canonical_json(man))
    (tmp_path / "state/MANIFEST.json").write_bytes(canonical_json(man))
    lr = load(tmp_path, params)
    assert lr.restored_from == "sol-000000" and lr.restore_cause == "nan" and lr.state["epoch"] == 2


def test_save_refuses_nan(tmp_path, base):
    bad = copy.deepcopy(base)
    bad["brain"]["m0"]["theta"][0] = np.float32("nan")
    with pytest.raises(Exception):
        _save(bad, Explored(), tmp_path)


def test_checkpoint_rotation_keeps_five_and_each_verifies(tmp_path, params, base):
    prev = None
    for sol in range(1, 9):
        s = copy.deepcopy(base)
        s["sol"] = sol
        out = tmp_path / f"s{sol}"
        if prev is not None:
            carry_checkpoints(prev, out)
        _save(s, _explored(sol), out)
        prev = out
    names = sorted(p.name for p in (prev / "state/checkpoints").glob("sol-*.json.gz"))
    assert names == [f"sol-{i:06d}.json.gz" for i in range(4, 9)]
    assert len(list((prev / "state/checkpoints").glob("*.sha256"))) == 5


def test_explored_checkpoint_keeps_only_regions_changed_by_the_last_sol(tmp_path, params, base):
    s1 = copy.deepcopy(base)
    s1["sol"] = 1
    d1 = tmp_path / "s1"
    _save(s1, _explored(1), d1)
    assert not list((d1 / "state/checkpoints/explored").glob("*")) if (d1 / "state/checkpoints/explored").exists() else True
    s2 = copy.deepcopy(base)
    s2["sol"] = 2
    d2 = tmp_path / "s2"
    carry_checkpoints(d1, d2)
    e2 = _explored(1)
    e2.mark(np.asarray([3]), np.asarray([3]), 2)                # new cell in the origin region only
    _save(s2, e2, d2)
    kept = sorted(p.name for p in (d2 / "state/checkpoints/explored").glob("*"))
    changed = [p.name for p in (d2 / "state/explored").glob("*") if p.read_bytes() != (d1 / "state/explored" / p.name).read_bytes()]
    assert kept == sorted(changed) and len(kept) == 1
    # the previous version of that region is the old sol's bytes
    assert (d2 / "state/checkpoints/explored" / kept[0]).read_bytes() == (d1 / "state/explored" / kept[0]).read_bytes()
    # corrupt the changed region: the load falls back to the previous version of it and says nothing is invented
    reg = d2 / "state/explored" / kept[0]
    reg.write_bytes(reg.read_bytes()[:-5])
    lr = load(d2, params)
    assert lr.restored_from == "sol-000002"
    assert lr.explored.cells() == _explored(1).cells()


def test_load_checkpoint_manual_and_unknown(tmp_path, params, base):
    s = copy.deepcopy(base)
    s["sol"] = 4
    _save(s, _explored(), tmp_path)
    lr = load_checkpoint(tmp_path, "sol-000004", params)
    assert lr.restore_cause == "manual" and lr.state["epoch"] == 2 and lr.state["sol"] == 4
    with pytest.raises(FileNotFoundError):
        load_checkpoint(tmp_path, "sol-000009", params)


# ---- migrations ----------------------------------------------------------------------------------------------
def test_fake_migration_0_to_1(base):
    v0 = copy.deepcopy(base)
    v0["schema_version"] = 0
    del v0["origin"], v0["pending_tags"]
    before = copy.deepcopy(v0)
    out = migrate(v0)
    assert out["schema_version"] == version.SCHEMA_VERSION == 1 and out["origin"] == [0, 0] and out["pending_tags"] == []
    assert validate(out) == []
    assert core_bytes(v0) == core_bytes(before)               # pure: the input is untouched


def test_migration_chain_and_missing_step(base):
    d = copy.deepcopy(base)
    d["schema_version"] = 0
    table = {0: lambda x: {**x, "schema_version": 1, "a": 1}, 1: lambda x: {**x, "schema_version": 2, "b": 2}}
    out = mig.migrate_state(d, 3 - 1, table)
    assert out["schema_version"] == 2 and out["a"] == 1 and out["b"] == 2
    with pytest.raises(ValueError):
        mig.migrate_state(d, 3, table)                        # no step 2 -> 3
    with pytest.raises(ValueError):
        mig.migrate_state(d, 1, {0: lambda x: {**x, "schema_version": 5}})


def test_migrate_loads_a_v0_core_through_the_store(tmp_path, params, base):
    v0 = copy.deepcopy(base)
    v0["schema_version"] = 0
    del v0["origin"], v0["pending_tags"]
    _save(v0, Explored(), tmp_path)
    lr = load(tmp_path, params)
    assert lr.restored_from is None and lr.state["schema_version"] == 1 and lr.state["origin"] == [0, 0]


def test_explored_header_migration():
    good = b"SOL0EXP1" + b"\x00\x00\x00\x00"
    assert migrate_explored(good) == good
    with pytest.raises(ValueError):
        migrate_explored(b"SOL0EXP2" + b"\x00" * 4)             # newer than the code
    with pytest.raises(ValueError):
        migrate_explored(b"NOTEXP00")
    # the mechanism: a fake format 0 is rewritten to the current header
    out = mig.migrate_explored_bytes(b"SOL0EXP0xyz", {0: lambda b: b"SOL0EXP1" + b[8:]}) if mig.EXPLORED_FORMAT == 1 else None
    assert out == b"SOL0EXP1xyz"


# ---- newer than the code -------------------------------------------------------------------------------------
@pytest.mark.parametrize("change", ["schema", "stage", "world_gen", "world_params"])
def test_state_newer_than_code_is_refused_not_restored(tmp_path, params, base, change):
    s = copy.deepcopy(base)
    s["sol"] = 2
    if change == "schema":
        s["schema_version"] = version.SCHEMA_VERSION + 1
    elif change == "stage":
        s["stage"]["id"] = version.MAX_STAGE + 1
    elif change == "world_gen":
        s["world_gen_version"] = version.WORLD_GEN_VERSION + 1
    else:
        s["world_params_hash"] = "0" * 64
    _save(s, Explored(), tmp_path)
    shutil.copytree(tmp_path, tmp_path.parent / (tmp_path.name + "_copy"))
    with pytest.raises(StateNewerError):
        load(tmp_path, params)
    assert not (tmp_path / "x").exists()


# ---- properties -----------------------------------------------------------------------------------------------
@settings(max_examples=25)
@given(cells=st.lists(st.tuples(st.integers(-5000, 5000), st.integers(-5000, 5000)), min_size=1, max_size=40),
       sol=st.integers(1, 3000))
def test_explored_roundtrip_property(cells, sol):
    e = Explored()
    e.mark(np.asarray([c[0] for c in cells]), np.asarray([c[1] for c in cells]), sol)
    back = Explored.from_regions(e.to_regions())
    assert back.cells() == e.cells() == len(set(cells))
    assert back.to_regions() == e.to_regions()
    for x, y in cells[:5]:
        assert int(back.window_mask(x, y, 1, 1)[0, 0]) == 1
