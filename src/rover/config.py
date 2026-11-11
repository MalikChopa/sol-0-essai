"""Parameters: every config/*.toml (and config/narrative/*.toml) read into one frozen structure (SPEC 1, 6.1)."""
from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _canon(obj: Any) -> bytes:   # same encoding as core.hashing.canonical_json (config imports nothing from the project)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class Params:
    data: Mapping[str, Any]
    hash: str

    def get(self, pid: str) -> Any:
        parts = pid.split(".")
        if parts[0] == "P":
            parts = parts[1:]
        cur: Any = self.data
        for p in parts:
            cur = cur[p]
        return cur


def _resolve(config_dir: Path) -> Path:
    if config_dir.is_dir():
        return config_dir
    alt = Path(__file__).resolve().parents[2] / "config"
    return alt if alt.is_dir() else config_dir


def load(config_dir: Path = Path("config")) -> Params:
    d = _resolve(Path(config_dir))
    data: dict[str, Any] = {}
    for f in sorted(d.glob("*.toml")):
        with open(f, "rb") as fh:
            data[f.stem] = tomllib.load(fh)
    nar: dict[str, Any] = {}
    if (d / "narrative").is_dir():
        for f in sorted((d / "narrative").glob("*.toml")):
            with open(f, "rb") as fh:
                nar[f.stem] = tomllib.load(fh)
    data["narrative"] = nar
    return Params(data=data, hash="sha256:" + hashlib.sha256(_canon(data)).hexdigest())


def world_params_hash(params: Params) -> str:
    return "sha256:" + hashlib.sha256(_canon(params.data["world"])).hexdigest()
