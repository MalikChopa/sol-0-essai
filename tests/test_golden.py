"""Golden fingerprints (ARCH 6): tests/<package>/golden.json is compared on every pytest.

Update only by a dedicated commit that says why: SOL0_UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PACKAGES = ("core", "world", "agent", "brain", "state", "render", "narrative", "pipeline")


@pytest.fixture(scope="module")
def fps(params):
    from rover.pipeline.refs import fingerprints
    return fingerprints(params)


@pytest.mark.parametrize("pkg", PACKAGES)
def test_golden(pkg, fps):
    got = {k: v for k, v in fps.items() if k.startswith(pkg + ".")}
    assert got, f"no fingerprint for {pkg}"
    f = HERE / pkg / "golden.json"
    if os.environ.get("SOL0_UPDATE_GOLDEN") == "1":
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(got, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    want = json.loads(f.read_text(encoding="utf-8"))
    assert got == want
