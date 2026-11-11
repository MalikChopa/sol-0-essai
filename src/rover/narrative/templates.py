"""Template choice, conditions and filling (SPEC 8.1): variant = u64(derive(seed, "journal", sol, crc32(id))) mod len."""
from __future__ import annotations

import re

import numpy as np

from rover.core.rng import derive, u64

_MARK = re.compile(r"\{(\w+)(?::(\d+))?\}")
_COND = re.compile(r"^(!?)(\w+)(?:(>=|<=|==|!=|>|<|=|:)(.+))?$")


def pick(variants: list, seed: int, sol: int, tid: str) -> str:
    key = derive(seed, "journal", sol, tid)
    return variants[int(u64(key, np.asarray(0))[()]) % len(variants)]


def markers(template: str) -> list:
    return [m.group(1) for m in _MARK.finditer(template)]


def fmt_number(v, lang: str, decimals: int | None) -> str:
    if isinstance(v, bool) or isinstance(v, int):
        s = str(int(v))
    else:
        s = "%.*f" % (decimals, v) if decimals is not None else "%.6g" % v  # no silent rounding
    return s.replace(".", ",") if lang == "fr" else s


def fill(template: str, facts: dict, lang: str, words: dict | None = None) -> str:
    """Fill {name} / {name:decimals}. A str value goes through words[name][lang] when that table exists."""
    words = words or {}

    def rep(m):
        name, dec = m.group(1), m.group(2)
        if name not in facts or facts[name] is None:
            raise KeyError(f"journal marker without fact: {name}")
        v = facts[name]
        if isinstance(v, (list, dict)):
            raise TypeError(f"journal marker {name} is not a scalar")
        if isinstance(v, str):
            tab = words.get(name)
            if tab is not None:
                return tab[lang][v]
            return v
        return fmt_number(v, lang, None if dec is None else int(dec))
    return _MARK.sub(rep, template)


def holds(cond: str, facts: dict) -> bool:
    """Evaluate one condition of a line's `when` list (see config/narrative/journal.toml header)."""
    m = _COND.match(cond)
    if m is None:
        raise ValueError(f"bad condition: {cond!r}")
    neg, key, op, arg = m.groups()
    v = facts.get(key)
    if op is None:
        ok = bool(v)
        return (not ok) if neg else ok
    if neg:
        raise ValueError(f"bad condition: {cond!r}")
    if op == ":":
        return isinstance(v, (list, tuple)) and arg in v
    if op == "=":
        return isinstance(v, str) and v == arg
    if v is None or isinstance(v, (str, list, dict)):
        return False
    x = float(arg)
    return {">=": v >= x, "<=": v <= x, "==": v == x, "!=": v != x, ">": v > x, "<": v < x}[op]


def condition_keys(cond: str) -> str:
    m = _COND.match(cond)
    if m is None:
        raise ValueError(f"bad condition: {cond!r}")
    return m.group(2)
