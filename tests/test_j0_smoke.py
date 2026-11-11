"""J0 checks of the determinism base and of the skeleton (J1-J5 add their own tests per package)."""
from __future__ import annotations

import numpy as np

from rover.core import rng
from rover.core.exact import centered_ranks, dot_fixed, to_int
from rover.core.mlp_layout import mlp_npar, unpack_mlp

_M = (1 << 64) - 1


def _mix(z):                                   # independent pure-Python splitmix64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M
    return z ^ (z >> 31)


def test_splitmix_numpy_equals_pure_python_on_10000_indices():
    key = rng.derive(20261111, "height")
    got = rng.u64(key, np.arange(10000))
    want = [_mix((key + (i + 1) * 0x9E3779B97F4A7C15) & _M) for i in range(10000)]
    assert [int(v) for v in got] == want


def test_first_16_outputs_are_pinned():
    key = rng.derive(20261111, "height")
    assert key == 4103880057153006468
    assert [int(v) for v in rng.u64(key, np.arange(16))] == [
        13766339994361387668, 10916922155795021700, 2615874747637940357, 13725212000587134426, 9761164002342810417,
        7500862717292172994, 849088314155761311, 12698318806861548189, 1233941407613791476, 12278236505922701816,
        17036996437919605563, 8541509553113800635, 17511074120018263005, 17882538238898315673, 3445457764820949661,
        2621422122755248890]
    assert rng.derive(1, "slip", 2, 3) == 12254059856960280208
    assert rng.derive(1, "journal", 4, "summary.s0") == 2678246894509573246


def test_per_rover_keys_do_not_depend_on_batch_position():
    keys = np.asarray([rng.derive(1, "cam", 3, 0), rng.derive(1, "cam", 3, 0)], dtype=np.uint64)
    a = rng.uniform(keys[:, None], np.arange(5)[None, :])
    assert (a[0] == a[1]).all()


def test_dot_fixed_equals_reference_loop():
    x = rng.uniform(5, np.arange(7)).reshape(1, 7)
    W = rng.uniform(6, np.arange(21)).reshape(7, 3)
    ref = [0.0, 0.0, 0.0]
    for j in range(3):
        acc = float(x[0, 0] * W[0, j])
        for i in range(1, 7):
            acc = acc + float(x[0, i] * W[i, j])
        ref[j] = acc
    assert dot_fixed(x, W)[0].tolist() == ref


def test_to_int_and_ranks_and_layout():
    assert to_int(np.asarray([1.9, -1.9])).tolist() == [1, -1]
    import pytest
    assert centered_ranks(np.asarray([3.0, 1.0, 2.0, 2.0])).tolist() == pytest.approx([0.5, -0.5, -1 / 6, 1 / 6])
    n = mlp_npar(24, 16, 2)
    assert n == 434
    W1, b1, W2, b2 = unpack_mlp(np.arange(n, dtype=np.float32), 24, 16, 2)
    assert W1.shape == (24, 16) and b1.shape == (16,) and W2.shape == (16, 2) and b2.shape == (2,)
    assert W1[1, 0] == 16 and W2[0, 0] == 24 * 16 + 16


def test_fresh_state_is_valid_and_brain_sizes_match_spec(params):
    from rover.pipeline import fresh_state
    from rover.state import validate
    s = fresh_state(params)
    assert validate(s) == []
    b = s["brain"]
    assert [b[m]["theta"].shape[0] for m in ("m0", "m1", "m3")] == [434, 147, 99]
    assert b["m2"]["w"].shape == (8, 40) and b["m4"] is None
    assert float(np.abs(b["m0"]["theta"][-2:]).max()) == 0.0        # b2 = 0


def test_state_roundtrip_and_corruption_is_restored(params, tmp_path):
    from rover.pipeline import fresh_state, run_sol
    from rover.state import Explored, load, save
    s = fresh_state(params)
    r1 = run_sol(s, Explored(), params, "2026-11-11T07:17:00Z", render=False, narrative=False)
    save(r1.state, r1.explored, tmp_path / "a", r1.images, r1.status)
    lr = load(tmp_path / "a", params)
    assert lr.restored_from is None and lr.state["sol"] == 1
    assert (lr.state["brain"]["m0"]["theta"] == r1.state["brain"]["m0"]["theta"]).all()
    assert lr.explored.cells() == r1.explored.cells()
    r2 = run_sol(r1.state, r1.explored, params, "2026-11-11T13:17:00Z", render=False, narrative=False)
    save(r2.state, r2.explored, tmp_path / "b", r2.images, r2.status)
    import shutil
    shutil.copytree(tmp_path / "a" / "state" / "checkpoints", tmp_path / "b" / "state" / "checkpoints", dirs_exist_ok=True)
    core = tmp_path / "b" / "state" / "core.json.gz"
    raw = bytearray(core.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    core.write_bytes(bytes(raw))
    lr2 = load(tmp_path / "b", params)
    assert lr2.restored_from is not None and lr2.state["epoch"] == 2
