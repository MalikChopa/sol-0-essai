"""Schema and region-format migrations (ARCH 5): pure functions, `MIGRATIONS = {n: migrate_n_to_n+1}`.

Schema 1 is the first real schema, so the only registered migration is the *fake* 0 -> 1 one, which exists to test the
mechanism (a hypothetical schema 0 lacked `origin` and `pending_tags`). It never runs on a published state.
"""
from __future__ import annotations

import copy


def migrate_0_to_1(d: dict) -> dict:
    d = copy.deepcopy(d)
    d.setdefault("origin", [0, 0])
    d.setdefault("pending_tags", [])
    d["schema_version"] = 1
    return d


MIGRATIONS: dict = {0: migrate_0_to_1}

# Explored-region formats: header b"SOL0EXP<n>"; {n: bytes -> bytes (n+1)}. Only format 1 exists.
EXPLORED_FORMAT = 1
EXPLORED_MIGRATIONS: dict = {}


def migrate_state(d: dict, target: int, table: dict | None = None) -> dict:
    """Apply migrations one version at a time up to `target`; a missing step is an error (never guessed)."""
    table = MIGRATIONS if table is None else table
    d = copy.deepcopy(d)
    while d["schema_version"] < target:
        step = table.get(d["schema_version"])
        if step is None:
            raise ValueError(f"no migration from schema {d['schema_version']}")
        before = d["schema_version"]
        d = step(d)
        if d["schema_version"] != before + 1:
            raise ValueError(f"migration {before} did not advance the schema by one")
    return d


def migrate_explored_bytes(b: bytes, table: dict | None = None) -> bytes:
    table = EXPLORED_MIGRATIONS if table is None else table
    if b[:7] != b"SOL0EXP" or not b[7:8].isdigit():
        raise ValueError("not an explored region")
    n = int(b[7:8])
    if n > EXPLORED_FORMAT:
        raise ValueError(f"explored format {n} newer than the code ({EXPLORED_FORMAT})")
    while n < EXPLORED_FORMAT:
        step = table.get(n)
        if step is None:
            raise ValueError(f"no explored migration from format {n}")
        b = step(b)
        n += 1
        if b[:8] != b"SOL0EXP" + str(n).encode():
            raise ValueError("explored migration produced a wrong header")
    return b
