"""Array (de)serialisation for core.json: {"dtype": "<f4", "shape": [...], "b64": "..."}."""
from __future__ import annotations

import base64

import numpy as np

Arr = np.ndarray


def pack_array(a: Arr) -> dict:
    a = np.asarray(a)
    dt = a.dtype.newbyteorder("<")
    data = np.asarray(a, dtype=dt, order="C").tobytes()
    return {"dtype": dt.str, "shape": [int(n) for n in a.shape], "b64": base64.b64encode(data).decode("ascii")}


def unpack_array(d: dict) -> Arr:
    raw = base64.b64decode(d["b64"].encode("ascii"))
    return np.frombuffer(raw, dtype=d["dtype"]).reshape(tuple(d["shape"])).copy()
