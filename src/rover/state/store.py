"""State store: canonical JSON + gzip(mtime=0), MANIFEST, 5 checkpoints, atomic writes (ARCH 5, SPEC 6.8)."""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rover import version
from rover.config import Params, world_params_hash
from rover.core.hashing import canonical_json, sha256_hex
from rover.core.serial import pack_array, unpack_array
from rover.state.explored import Explored
from rover.state.schema import migrate, nonfinite_paths, validate


class StateNewerError(Exception):
    """Schema, stage or world newer than / different from this code (exit code 3)."""


class ForeignDirError(Exception):
    """Non empty directory without state/MANIFEST.json (exit code 3)."""


@dataclass
class LoadResult:
    state: dict | None
    explored: Explored
    restored_from: str | None
    notes: list
    cause: str | None
    redone_sols: list = field(default_factory=list)     # sols refaits après une restauration (addition J5)
    restore_cause: str | None = None                    # "corrupt" | "nan" | "manual" (addition J5)


def _enc(o):
    if isinstance(o, np.ndarray):
        return pack_array(o)
    if isinstance(o, dict):
        return {k: _enc(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_enc(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):      # numpy scalar
        return o.item()
    return o


def _dec(o):
    if isinstance(o, dict):
        if set(o.keys()) == {"dtype", "shape", "b64"}:
            return unpack_array(o)
        return {k: _dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_dec(v) for v in o]
    return o


def _gz(b: bytes) -> bytes:
    return gzip.compress(b, compresslevel=9, mtime=0)


def encode_files(state: dict, explored: Explored, images: dict, status: dict) -> dict:
    bad = nonfinite_paths(state)
    if bad:                                              # ARCH 5: a NaN makes the write fail
        raise ValueError("non finite value in the state: " + ", ".join(bad[:3]))
    files = {"state/core.json.gz": _gz(canonical_json(_enc(state)))}
    for (rx, ry), b in sorted(explored.to_regions().items()):
        files[f"state/explored/r_{rx}_{ry}.bin.gz"] = _gz(b)
    for name in sorted(images):
        files[name] = images[name]
    files["status.json"] = canonical_json(status)
    return files


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _ckpt_sol(name: str) -> int:
    return int(name.split(".")[0].split("-")[1])


def carry_checkpoints(in_dir: Path, out_dir: Path, max_sol: int | None = None) -> None:
    """Copy the checkpoints of the previous state into out_dir (before save, which rotates them).

    `max_sol`: after a restoration to sol-K, the checkpoints numbered > K are not carried (never the branch itself).
    The explored regions of the previous state are also copied to state/checkpoints/explored/ ; `save` then keeps
    only those that the new sol changed (the previous version of the modified regions, ARCH 5)."""
    in_dir, out_dir = Path(in_dir), Path(out_dir)
    src = in_dir / "state" / "checkpoints"
    if src.is_dir():
        for f in sorted(src.glob("sol-*")):
            if max_sol is not None and _ckpt_sol(f.name) > max_sol:
                continue
            _atomic(out_dir / "state" / "checkpoints" / f.name, f.read_bytes())
    rdir = in_dir / "state" / "explored"
    if rdir.is_dir():
        for f in sorted(rdir.glob("r_*.bin.gz")):
            b = f.read_bytes()
            try:
                gzip.decompress(b)
            except Exception:
                alt = src / "explored" / f.name        # unreadable region: keep the older good copy if any
                if not alt.is_file():
                    continue
                b = alt.read_bytes()
            _atomic(out_dir / "state" / "checkpoints" / "explored" / f.name, b)


def save(state: dict, explored: Explored, out_dir: Path, images: dict, status: dict) -> dict:
    out_dir = Path(out_dir)
    files = encode_files(state, explored, images, status)
    for rel, b in files.items():
        _atomic(out_dir / rel, b)
    entries = {}
    for rel, b in files.items():
        if rel.startswith("state/"):
            raw = gzip.decompress(b)
            entries[rel] = {"sha256": sha256_hex(raw), "size": len(raw)}
    manifest = {"schema_version": state["schema_version"], "code_version": state["code_version"], "epoch": state["epoch"],
                "sol": state["sol"], "files": entries}
    manifest["manifest_sha256"] = sha256_hex(canonical_json(manifest))
    _atomic(out_dir / "state" / "MANIFEST.json", canonical_json(manifest))
    # checkpoint of the core (healthy sol), rotation to P.run.checkpoints
    raw = gzip.decompress(files["state/core.json.gz"])
    name = "sol-%06d" % state["sol"]
    cdir = out_dir / "state" / "checkpoints"
    _atomic(cdir / (name + ".json.gz"), files["state/core.json.gz"])
    _atomic(cdir / (name + ".json.gz.sha256"), (sha256_hex(raw) + "\n").encode("ascii"))
    edir = cdir / "explored"
    if edir.is_dir():
        for p in sorted(edir.glob("r_*.bin.gz")):
            new = files.get("state/explored/" + p.name)
            if new is None or new == p.read_bytes():       # unchanged (or vanished) region: no copy needed
                p.unlink()
    keep = sorted(p.name[:-len(".json.gz")] for p in cdir.glob("sol-*.json.gz"))[-5:]
    for p in sorted(cdir.glob("sol-*")):
        if p.name.split(".")[0] not in keep:
            p.unlink()
    return manifest


def _read_core(b_gz: bytes) -> dict:
    return _dec(json.loads(gzip.decompress(b_gz).decode("utf-8")))


def _check_newer(core: dict, params: Params) -> None:
    if core["schema_version"] > version.SCHEMA_VERSION:
        raise StateNewerError(f"state schema {core['schema_version']} > code schema {version.SCHEMA_VERSION}")
    if core["stage"]["id"] > version.MAX_STAGE:
        raise StateNewerError(f"state stage {core['stage']['id']} > MAX_STAGE {version.MAX_STAGE}")
    if core["world_gen_version"] != version.WORLD_GEN_VERSION:
        raise StateNewerError("world_gen_version differs from the code")
    if core["world_params_hash"] != world_params_hash(params):
        raise StateNewerError("world_params_hash differs from the code")


def _region_key(rel: str) -> tuple[int, int]:
    stem = rel.split("/")[-1].split(".")[0].split("_")
    return int(stem[1]), int(stem[2])


def _manifest(in_dir: Path) -> dict | None:
    try:
        man = json.loads((in_dir / "state" / "MANIFEST.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in man.items() if k != "manifest_sha256"}
        if sha256_hex(canonical_json(body)) != man["manifest_sha256"]:
            return None
        return man
    except Exception:
        return None


def _load_dir(in_dir: Path) -> tuple[dict, Explored]:
    """Strict load: any mismatch raises."""
    man = json.loads((in_dir / "state" / "MANIFEST.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in man.items() if k != "manifest_sha256"}
    if sha256_hex(canonical_json(body)) != man["manifest_sha256"]:
        raise ValueError("MANIFEST fingerprint mismatch")
    regions = {}
    core = None
    for rel, e in sorted(man["files"].items()):
        raw = gzip.decompress((in_dir / rel).read_bytes())
        if sha256_hex(raw) != e["sha256"] or len(raw) != e["size"]:
            raise ValueError(f"fingerprint mismatch: {rel}")
        if rel == "state/core.json.gz":
            core = json.loads(raw.decode("utf-8"))
        elif rel.startswith("state/explored/"):
            regions[_region_key(rel)] = raw
    if core is None:
        raise ValueError("core missing from MANIFEST")
    return _dec(core), Explored.from_regions(regions)


def _regions_tolerant(in_dir: Path, notes: list) -> Explored:
    """Explored regions after a corruption: each region is checked on its own (MANIFEST fingerprint when the MANIFEST is
    sound, else a parse), falling back to its copy in state/checkpoints/explored/, else skipped (and said)."""
    man = _manifest(in_dir)
    want = {} if man is None else man["files"]
    names = {p.name for p in (in_dir / "state" / "explored").glob("r_*.bin.gz")} if (in_dir / "state" / "explored").is_dir() else set()
    names |= {rel.split("/")[-1] for rel in want if rel.startswith("state/explored/")}
    regions = {}
    for name in sorted(names):
        rel = "state/explored/" + name
        got = None
        for path, check in ((in_dir / rel, True), (in_dir / "state" / "checkpoints" / "explored" / name, False)):
            try:
                raw = gzip.decompress(path.read_bytes())
                if check and rel in want and sha256_hex(raw) != want[rel]["sha256"]:
                    raise ValueError("fingerprint")
                Explored.from_regions({_region_key(rel): raw})          # parses
                got = raw
                break
            except Exception:
                continue
        if got is None:
            notes.append(f"explored region {name} lost")
        else:
            regions[_region_key(rel)] = got
    return Explored.from_regions(regions)


def _cause_kind(cause: str) -> str:
    return "nan" if "non finite" in cause else "corrupt"


def _checkpoint_core(in_dir: Path, gz: Path, params: Params) -> dict:
    cdir = gz.parent
    b = gz.read_bytes()
    want = (cdir / (gz.name + ".sha256")).read_text().strip()
    if sha256_hex(gzip.decompress(b)) != want:
        raise ValueError("fingerprint mismatch")
    core = _read_core(b)
    _check_newer(core, params)
    core = migrate(core)
    probs = validate(core)
    if probs:
        raise ValueError("invalid: " + "; ".join(probs[:2]))
    return core


def _top_sol(in_dir: Path, restored_sol: int) -> int:
    top = restored_sol
    man = _manifest(in_dir)
    if man is not None:
        top = max(top, int(man["sol"]))
    cdir = in_dir / "state" / "checkpoints"
    for gz in cdir.glob("sol-*.json.gz"):
        top = max(top, _ckpt_sol(gz.name))
    return top


def load(in_dir: Path, params: Params) -> LoadResult:
    in_dir = Path(in_dir)
    if not in_dir.is_dir() or not any(in_dir.iterdir()):
        return LoadResult(None, Explored(), None, [], None)
    if not (in_dir / "state" / "MANIFEST.json").is_file():
        raise ForeignDirError(f"{in_dir} is not empty and has no state/MANIFEST.json")
    cause = None
    try:
        core, explored = _load_dir(in_dir)
        _check_newer(core, params)
        core = migrate(core)
        probs = validate(core)
        if probs:
            raise ValueError("invalid state: " + "; ".join(probs[:3]))
        core["health"]["restored_from"] = None        # "restored" describes this run's input only
        return LoadResult(core, explored, None, [], None)
    except StateNewerError:
        raise
    except Exception as exc:                       # corrupted: try the checkpoints, newest first
        cause = type(exc).__name__ + ": " + str(exc)[:120]
    notes = [f"state unreadable ({cause})"]
    cdir = in_dir / "state" / "checkpoints"
    for gz in sorted(cdir.glob("sol-*.json.gz"), reverse=True):
        try:
            core = _checkpoint_core(in_dir, gz, params)
        except StateNewerError:
            raise
        except Exception as exc:
            notes.append(f"{gz.name}: {type(exc).__name__}")
            continue
        explored = _regions_tolerant(in_dir, notes)
        k = int(core["sol"])
        name = gz.name[:-len(".json.gz")]
        core["epoch"] = core["epoch"] + 1
        core["health"]["restored_from"] = name
        return LoadResult(core, explored, name, notes, cause, list(range(k + 1, _top_sol(in_dir, k) + 1)),
                          _cause_kind(cause))
    raise RuntimeError("state unreadable and no valid checkpoint: " + "; ".join(notes))


def load_checkpoint(in_dir: Path, name: str, params: Params) -> LoadResult:
    """Manual restoration (`rover restore`): the named checkpoint, validated; epoch + 1, restore_cause 'manual'."""
    in_dir = Path(in_dir)
    gz = in_dir / "state" / "checkpoints" / (name + ".json.gz")
    if not gz.is_file():
        raise FileNotFoundError(f"no checkpoint {name}")
    core = _checkpoint_core(in_dir, gz, params)              # StateNewerError / ValueError propagate
    notes: list = []
    explored = _regions_tolerant(in_dir, notes)
    k = int(core["sol"])
    core["epoch"] = core["epoch"] + 1
    core["health"]["restored_from"] = name
    return LoadResult(core, explored, name, notes, None, list(range(k + 1, _top_sol(in_dir, k) + 1)), "manual")


def core_bytes(state: dict) -> bytes:
    """Canonical (decompressed) JSON of the core state: the exact bytes whose SHA-256 the MANIFEST records."""
    return canonical_json(_enc(state))


def checkpoint_loaders(in_dir: Path, params: Params) -> dict:
    """{sol: loader} of the checkpoints of `in_dir` (J6): loader() returns the checkpoint's module M0 (validated, read lazily)."""
    out = {}
    cdir = Path(in_dir) / "state" / "checkpoints"
    if not cdir.is_dir():
        return out
    for gz in sorted(cdir.glob("sol-*.json.gz")):
        out[_ckpt_sol(gz.name)] = (lambda gz=gz: _checkpoint_core(Path(in_dir), gz, params)["brain"]["m0"])
    return out
