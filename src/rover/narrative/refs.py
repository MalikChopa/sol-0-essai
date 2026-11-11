"""Reference fingerprints of the narrative package (ARCH 6): entries, names and pages built from fictitious facts."""
from __future__ import annotations

import tempfile
from pathlib import Path

from rover.core.hashing import canonical_json, sha256_hex
from rover.core.types import JournalEntry
from rover.narrative.journal import compose_entry, make_name
from rover.narrative.pages import write_pages


STAGE_NAMES = ("AWAKENING", "I CAN MOVE", "LEARNING TO DRIVE", "ENERGY", "SAMPLING", "ANALYSIS")


def sample_facts(stage: int = 3, sol: int = 42, **over) -> dict:
    """Fictitious facts with every key of SPEC 8.2 (plus `couples_sol`, J0 contract), quiet defaults."""
    f = {
        "sol": sol, "epoch": 1, "stage": stage, "utc": "2026-11-21T07:17:00Z", "stage_name": STAGE_NAMES[min(stage, 5)],
        "advanced_to": None,
        "distance_m": 132.4, "awake_cells": 26.5, "awake_ticks": 700, "forced_sleep_ticks": 0, "breakdowns": 0,
        "night_drive_ticks": 0, "targets_reached": 0, "stuck": False, "tipped": False, "anomaly_seen": False,
        "freed_by": None, "max_tilt_deg": 12.4, "battery_min": 0.22, "battery_min_hour": 18.67,
        "slip_worst_terrain": "sand", "r2": 0.58, "r2_worst_terrain": "sand", "battery_successes": 13,
        "metric_before": None, "metric_after": None, "threshold": None, "events": [], "firsts": [], "safe_actions": [],
        "samples": 0, "spectra": 0, "new_categories": 0, "n_categories": 0, "novel_vs_prev": None, "ari": None,
        "new_names": [], "restored_from": None, "restore_cause": None, "redone_sols": [], "degraded": False,
        "consolidation": False, "truncated_at": None, "incident": None, "days_since_last_run": None, "couples_sol": 34,
    }
    f.update(over)
    return f


def sample_state(stage: int = 3) -> dict:
    return {"world_seed": 20261111, "epoch": 1, "sol": 42, "firsts": {}, "names": {}, "journal_tail": [],
            "stage": {"id": stage}}


def _cases() -> list:
    return [
        sample_facts(0, couples_sol=34, distance_m=41.0),
        sample_facts(1, firsts=["first.image"], advanced_to=1, events=["storm"]),
        sample_facts(2, battery_successes=13, stuck=True, safe_actions=["freed"]),
        sample_facts(3, breakdowns=2, forced_sleep_ticks=130, firsts=["first.breakdown"], days_since_last_run=3),
        sample_facts(4, novel_vs_prev=3, samples=5),
        sample_facts(5, spectra=212, n_categories=6, ari=0.84, new_names=["Tervane"], new_categories=1),
        sample_facts(3, restore_cause="corrupt", redone_sols=[40, 41, 42], consolidation=True),
    ]


def fingerprints(params) -> dict:
    state = sample_state()
    entries = []
    for f in _cases():
        e = compose_entry(f, state, params)
        entries.append([e.epoch, e.sol, e.utc, e.fr, e.en])
    names, taken = [], set()
    for i in range(50):
        n = make_name(20261111, "category", i, taken)
        taken.add(n)
        names.append(n)
    st = sample_state(5)
    st["firsts"] = {"first.move": [1, 1], "first.stage.1": [1, 12]}
    st["names"] = {"c1": {"name": names[0], "sol": 300}}
    with tempfile.TemporaryDirectory() as d:
        write_pages(Path(d), st, [JournalEntry(1, 42, "2026-11-21T07:17:00Z", "fr", "en")], params, "owner/repo")
        pages = [(p.relative_to(d).as_posix(), p.read_text(encoding="utf-8")) for p in sorted(Path(d).rglob("*.md"))]
    h = lambda o: "sha256:" + sha256_hex(canonical_json(o))
    return {"narrative.entries": h(entries), "narrative.names": h(names), "narrative.pages": h(pages)}
