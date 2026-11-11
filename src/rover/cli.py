"""Command line: python -m rover sol | check | refs | simulate | restore | bench (exit codes: SPEC 6.12).

0 success ; 1 reserved to publish.sh ; 2 invalid input ; 3 unrecoverable state, state newer than the code, foreign folder ;
4 validation failed (or the passive sol itself failed: nothing is published)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from rover import config
from rover.pipeline import (bench, check_dir, fresh_state, main_lag, restore_result, run_sol, simulate, write_main)
from rover.pipeline.refs import fingerprints
from rover.state import (ForeignDirError, StateNewerError, carry_checkpoints, checkpoint_loaders, load, load_checkpoint, save)

_IMAGES = ("console.gif", "status.svg", "map.png")
_NOW = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CKPT = re.compile(r"^sol-[0-9]{6}$")


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _prev_images(in_dir: Path) -> dict:
    return {n: (in_dir / n).read_bytes() for n in _IMAGES if (in_dir / n).is_file()}


def _prev_files(in_dir: Path) -> dict:
    out = {}
    if in_dir.is_dir():
        for f in sorted(in_dir.rglob("*")):
            rel = f.relative_to(in_dir).as_posix()
            if f.is_file() and not rel.startswith("state/checkpoints/") and rel != "state/MANIFEST.json" \
                    and not rel.startswith(".git"):
                b = f.read_bytes()
                out[rel] = (len(b), hashlib.sha256(b).hexdigest())
    return out


def _manifest_sol(in_dir: Path):
    try:
        return int(json.loads((in_dir / "state" / "MANIFEST.json").read_text(encoding="utf-8"))["sol"])
    except Exception:
        return None


def _ckpt_number(name: str | None):
    return None if name is None else int(name.split("-")[1])


def _sol(a) -> int:
    if a.fault != "none" and os.environ.get("SOL0_TRIAL") != "1":
        _err("--fault needs SOL0_TRIAL=1")
        return 2
    if not _NOW.match(a.now):
        _err("--now must be YYYY-MM-DDTHH:MM:SSZ")
        return 2
    params = config.load()
    in_dir, out_dir = Path(a.in_dir), Path(a.out)
    if in_dir.resolve() == out_dir.resolve():
        _err("--in and --out must differ")
        return 2
    tmp = None
    try:
        if a.fault == "corrupt":
            tmp = Path(tempfile.mkdtemp())
            if not (in_dir / "state" / "core.json.gz").is_file():
                _err("--fault corrupt needs an existing state in --in")
                return 2
            shutil.copytree(in_dir, tmp / "in")
            in_dir = tmp / "in"
            core = in_dir / "state" / "core.json.gz"
            b = bytearray(core.read_bytes())
            b[len(b) // 2] ^= 0xFF
            core.write_bytes(bytes(b))
        try:
            lr = load(in_dir, params)
        except (ForeignDirError, StateNewerError) as exc:
            _err(f"refused: {exc}")
            return 3
        except RuntimeError as exc:
            _err(f"unrecoverable: {exc}")
            return 3
        state = lr.state if lr.state is not None else fresh_state(params)
        prev_pending = list(state["pending_tags"])
        info = None if lr.restored_from is None else {"cause": lr.restore_cause, "redone_sols": lr.redone_sols}
        try:
            res = run_sol(state, lr.explored, params, a.now, fault="none" if a.fault == "corrupt" else a.fault,
                          prev_images=_prev_images(in_dir), prev_files=_prev_files(in_dir), restore_info=info,
                          ckpts=checkpoint_loaders(in_dir, params))
        except Exception as exc:                       # the passive sol itself failed: nothing is published
            _err(f"sol failed: {type(exc).__name__}: {str(exc)[:200]}")
            return 4
        det = res.status["det"]
        det["main_lag"] = main_lag(res.state, Path(a.main))
        if lr.state is not None and a.now < lr.state["last_run_utc"]:
            det["warnings"] = sorted(det["warnings"] + ["clock_before_last_run"])
        out_dir.mkdir(parents=True, exist_ok=True)
        carry_checkpoints(in_dir, out_dir, _ckpt_number(lr.restored_from))
        save(res.state, res.explored, out_dir, res.images, res.status)
        write_main(res, Path(a.main), Path(a.tags) if a.tags else None, a.repo or "", params, prev_pending)
        print(f"sol {res.state['sol']} stage {res.state['stage']['id']} attempts {res.state['health']['attempts']}")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _restore(a) -> int:
    if not _CKPT.match(a.checkpoint):
        _err("--checkpoint must match sol-NNNNNN")
        return 2
    if not _NOW.match(a.now):
        _err("--now must be YYYY-MM-DDTHH:MM:SSZ")
        return 2
    params = config.load()
    in_dir, out_dir = Path(a.in_dir), Path(a.out)
    if in_dir.resolve() == out_dir.resolve():
        _err("--in and --out must differ")
        return 2
    if not (in_dir / "state" / "MANIFEST.json").is_file():
        _err("restore needs an existing state in --in")
        return 3 if in_dir.is_dir() and any(in_dir.iterdir()) else 2
    try:
        lr = load_checkpoint(in_dir, a.checkpoint, params)
        res = restore_result(lr, a.now, _prev_images(in_dir), _manifest_sol(in_dir), params)
    except FileNotFoundError as exc:
        _err(str(exc))
        return 2
    except (StateNewerError, ValueError, OSError) as exc:
        _err(f"unrecoverable: {type(exc).__name__}: {str(exc)[:200]}")
        return 3
    res.status["det"]["main_lag"] = main_lag(res.state, Path(a.main)) if a.main else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    carry_checkpoints(in_dir, out_dir, _ckpt_number(a.checkpoint))
    save(res.state, res.explored, out_dir, res.images, res.status)
    if a.main:
        write_main(res, Path(a.main), None, "", params)
    print(f"restored {a.checkpoint}: sol {res.state['sol']} epoch {res.state['epoch']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rover")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sol")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--main", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--tags")
    p.add_argument("--repo")
    p.add_argument("--fault", default="none", choices=["none", "corrupt", "nan"])
    p = sub.add_parser("check")
    p.add_argument("--dir", required=True)
    p.add_argument("--prev")
    p = sub.add_parser("refs")
    p.add_argument("--out", required=True)
    p = sub.add_parser("simulate")
    p.add_argument("--sols", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--from", dest="from_dir")
    p.add_argument("--report")
    p.add_argument("--workers", type=int, default=1)
    p = sub.add_parser("restore")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--now", default="1970-01-01T00:00:00Z")
    p.add_argument("--main", default="")
    p = sub.add_parser("bench")
    p.add_argument("--only", default="")
    a = ap.parse_args(argv)
    if a.cmd == "sol":
        return _sol(a)
    if a.cmd == "restore":
        return _restore(a)
    params = config.load()
    if a.cmd == "check":
        probs = check_dir(Path(a.dir), Path(a.prev) if a.prev else None, params)
        for x in probs:
            _err("check: " + x)
        return 4 if probs else 0
    if a.cmd == "refs":
        fp = fingerprints(params)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(fp, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return 0
    if a.cmd == "simulate":
        if a.sols < 0 or a.workers < 1:
            _err("--sols >= 0 and --workers >= 1")
            return 2
        start = None
        if a.from_dir:
            try:
                lr = load(Path(a.from_dir), params)
            except (ForeignDirError, StateNewerError, RuntimeError) as exc:
                _err(f"refused: {exc}")
                return 3
            if lr.state is None:
                _err("--from: no state")
                return 2
            start = (lr.state, lr.explored)
        r = simulate(a.sols, params, a.seed, Path(a.report) if a.report else None, a.workers, start)
        print(json.dumps({k: r[k] for k in ("sols", "stage", "cells", "core_sha256")}))
        return 0
    if a.cmd == "bench":
        try:
            r = bench(params, [x for x in a.only.split(",") if x])
        except ValueError as exc:
            _err(str(exc))
            return 2
        print(json.dumps(r, sort_keys=True))
        return 0
    return 2
