"""Golden fingerprints of the narrative package: entries, names and pages built from fictitious facts.

Update only by a dedicated commit that says why: SOL0_UPDATE_GOLDEN=1 pytest tests/narrative/test_golden.py
"""
import json
import os
from pathlib import Path

from rover.narrative.refs import fingerprints

GOLDEN = Path(__file__).resolve().parent / "golden.json"


def test_golden(params):
    got = fingerprints(params)
    assert set(got) == {"narrative.entries", "narrative.names", "narrative.pages"}
    if os.environ.get("SOL0_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))
