"""Two runs of the same two-sol chain give the same bytes (ARCH 6): state/**, status.json without `run`, svg, journal, pixels."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from rover.cli import main


def _chain(root: Path):
    a = ["sol", "--in", str(root / "empty"), "--out", str(root / "s1"), "--main", str(root / "main"),
         "--now", "2026-11-11T07:17:00Z"]
    b = ["sol", "--in", str(root / "s1"), "--out", str(root / "s2"), "--main", str(root / "main"),
         "--now", "2026-11-11T13:17:00Z"]
    assert main(a) == 0 and main(b) == 0


def _pixels(p: Path) -> bytes:
    im = Image.open(io.BytesIO(p.read_bytes()))
    return b"".join((im.seek(i), np.asarray(im.convert("RGB")).tobytes())[1] for i in range(getattr(im, "n_frames", 1)))


def test_two_runs_are_identical(tmp_path):
    _chain(tmp_path / "x")
    _chain(tmp_path / "y")
    x, y = tmp_path / "x", tmp_path / "y"
    for rel in sorted(p.relative_to(x / "s2") for p in (x / "s2" / "state").rglob("*") if p.is_file()):
        assert (x / "s2" / rel).read_bytes() == (y / "s2" / rel).read_bytes(), rel
    sx = json.loads((x / "s2" / "status.json").read_text())
    sy = json.loads((y / "s2" / "status.json").read_text())
    assert sx["det"] == sy["det"]
    assert (x / "s2" / "status.svg").read_bytes() == (y / "s2" / "status.svg").read_bytes()
    assert (x / "main" / "journal" / "2026-11.md").read_bytes() == (y / "main" / "journal" / "2026-11.md").read_bytes()
    assert _pixels(x / "s2" / "console.gif") == _pixels(y / "s2" / "console.gif")
    assert _pixels(x / "s2" / "map.png") == _pixels(y / "s2" / "map.png")
    assert (x / "s2" / "console.gif").read_bytes() == (y / "s2" / "console.gif").read_bytes()    # same machine: same bytes
