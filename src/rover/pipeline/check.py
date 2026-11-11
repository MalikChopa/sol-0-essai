"""Result validation: in memory (check_result, used by the attempts loop) and on files (check_dir, `rover check`)."""
from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from rover.config import Params
from rover.core.exact import isum_py
from rover.core.hashing import sha256_hex
from rover.state import ForeignDirError, StateNewerError, encode_files, load, validate

_STATE_MAX = 20_000_000
_IMAGES = ("console.gif", "status.svg", "map.png")


def _image_problems(images: dict, params: Params) -> list:
    P = params.get
    probs = []
    if "console.gif" in images:
        g = images["console.gif"]
        if len(g) > P("render.gif_max_bytes"):
            probs.append("console.gif too large")
        try:
            im = Image.open(io.BytesIO(g))
            if im.size != (P("render.width"), P("render.height")):
                probs.append("console.gif size %s" % (im.size,))
        except Exception as exc:
            probs.append("console.gif unreadable: " + type(exc).__name__)
    if "map.png" in images:
        try:
            im = Image.open(io.BytesIO(images["map.png"]))
            mw, mh = P("render.map_max")
            if im.size[0] > mw or im.size[1] > mh:
                probs.append("map.png too large")
        except Exception as exc:
            probs.append("map.png unreadable: " + type(exc).__name__)
    if "status.svg" in images:
        try:
            ET.fromstring(images["status.svg"])
            if len(images["status.svg"]) > 20_000:
                probs.append("status.svg > 20 KB")
        except ET.ParseError:
            probs.append("status.svg is not valid XML")
    return probs


def check_result(result, prev: dict | None, prev_files: dict | None, params: Params) -> list:
    probs = list(validate(result.state))
    want = 1 if prev is None else prev["sol"] + 1
    if result.state["sol"] != want:
        probs.append(f"sol {result.state['sol']} != {want}")
    if prev_files is None:
        return probs
    probs += _image_problems(result.images, params)
    files = encode_files(result.state, result.explored, result.images, result.status)
    if isum_py(len(b) for b in files.values()) > _STATE_MAX + 3_000_000:
        probs.append("state too large")
    new = isum_py(len(b) for rel, b in files.items() if rel not in prev_files or prev_files[rel][1] != sha256_hex(b))
    if new > params.get("run.new_bytes_max"):
        probs.append(f"new bytes {new} > {params.get('run.new_bytes_max')}")
    return probs


def _tree(d: Path) -> dict:
    out = {}
    for f in sorted(d.rglob("*")):
        rel = f.relative_to(d).as_posix()
        if f.is_file() and not rel.startswith("state/checkpoints/") and rel != "state/MANIFEST.json":
            out[rel] = f.read_bytes()
    return out


def _all_bytes(d: Path) -> int:
    return isum_py(f.stat().st_size for f in Path(d).rglob("*") if f.is_file())


def check_dir(out_dir: Path, prev_dir: Path | None, params: Params) -> list:
    """Second guard of the workflow (ARCH 9), on the files as written. `prev_dir` None: no comparison with a previous state
    (`rover check --dir _in`: structure, fingerprints, reload and content only)."""
    out_dir = Path(out_dir)
    probs = []
    for rel in ("state/core.json.gz", "state/MANIFEST.json", "status.json"):
        if not (out_dir / rel).is_file():
            probs.append(f"missing {rel}")
    if probs:
        return probs
    try:
        status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
        det = status["det"]
        status["run"]
    except Exception as exc:
        return ["status.json unreadable: " + type(exc).__name__]
    try:
        lr = load(out_dir, params)
    except (ForeignDirError, StateNewerError, RuntimeError) as exc:
        return [type(exc).__name__ + ": " + str(exc)[:100]]
    if lr.restored_from is not None:
        probs.append("state needed a restore: " + str(lr.cause))
        return probs
    probs += validate(lr.state)
    sol = lr.state["sol"]
    if det.get("sol") != sol:
        probs.append(f"status.json sol {det.get('sol')} != state sol {sol}")
    prev_files: dict = {}
    if prev_dir is not None:
        prev_sol = 0
        if Path(prev_dir).is_dir() and any(Path(prev_dir).iterdir()):
            try:
                pl = load(Path(prev_dir), params)
                if pl.state is not None:
                    prev_sol = pl.state["sol"]
            except Exception as exc:
                probs.append("prev unreadable: " + type(exc).__name__)
            prev_files = {rel: (len(b), sha256_hex(b)) for rel, b in _tree(Path(prev_dir)).items()}
        if "manual_restore" in det.get("warnings", []):       # `rover restore`: the checkpoint's own sol, epoch + 1
            if det.get("restored_from") != "sol-%06d" % sol or sol > prev_sol:
                probs.append(f"manual restore inconsistent (sol {sol}, restored_from {det.get('restored_from')})")
        elif sol != prev_sol + 1:
            probs.append(f"sol {sol} != {prev_sol + 1}")
    images = {n: (out_dir / n).read_bytes() for n in _IMAGES if (out_dir / n).is_file()}
    prev_has_images = any(n in prev_files for n in _IMAGES)
    if len(images) not in (0, 3) or (not images and prev_has_images):
        probs.append("images missing: " + ",".join(n for n in _IMAGES if n not in images))
    probs += _image_problems(images, params)
    if _all_bytes(out_dir) > _STATE_MAX:
        probs.append("state too large")
    if prev_dir is not None:
        new = isum_py(len(b) for rel, b in _tree(out_dir).items() if rel not in prev_files or prev_files[rel][1] != sha256_hex(b))
        if new > params.get("run.new_bytes_max"):
            probs.append(f"new bytes {new} > {params.get('run.new_bytes_max')}")
    return probs
