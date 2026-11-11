"""Templates (config/narrative): well-formedness, facts of SPEC 8.2, coverage, length, determinism."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rover.narrative import compose_entry, detect_firsts
from rover.narrative.journal import DERIVED, MAX_CHARS, derived_markers, lines, select
from rover.narrative.pages import FIRST_LABELS
from rover.narrative.refs import sample_facts, sample_state
from rover.narrative.templates import condition_keys, fill, holds, markers

ROOT = Path(__file__).resolve().parents[2]


def spec_fact_keys() -> set:
    text = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    part = text.split("### 8.2", 1)[1].split("### 8.3", 1)[0]
    keys = set()
    for row in part.splitlines():
        if row.startswith("| `"):
            keys |= set(re.findall(r"`(\w+)`", row.split("|")[1]))
    return keys


FACT_KEYS = spec_fact_keys() | {"couples_sol"}          # couples_sol: J0 contract (addition to 8.2)
DERIVED_KEYS = set(DERIVED)


def test_sample_facts_conform_to_spec_8_2():
    assert len(spec_fact_keys()) >= 40
    assert set(sample_facts()) == FACT_KEYS


def test_every_line_is_well_formed(params):
    ls = lines(params)
    assert len({ln["id"] for ln in ls}) == len(ls)
    ids = {ln["id"] for ln in ls}
    for ln in ls:
        assert ln["slot"] in ("summary", "learn", "extra"), ln["id"]
        assert ln["needs"], f"{ln['id']}: a line without needs is tied to no fact"
        assert set(ln["needs"]) <= FACT_KEYS, ln["id"]
        for c in ln.get("when", ()):
            assert condition_keys(c) in FACT_KEYS | DERIVED_KEYS, (ln["id"], c)
        assert set(ln.get("replaces", ())) <= ids
        if ln["slot"] == "extra":
            assert isinstance(ln["prio"], int)
        assert len(ln["fr"]) == len(ln["en"]) > 0, ln["id"]
        for fr, en in zip(ln["fr"], ln["en"]):
            assert sorted(markers(fr)) == sorted(markers(en)), ln["id"]
            for m in markers(fr):
                assert m in ln["needs"] or m in DERIVED_KEYS, (ln["id"], m)
                for src in DERIVED.get(m, ()):
                    assert src in ln["needs"], (ln["id"], m, src)
            assert fr == fr.strip() and en == en.strip()


CAUSAL = re.compile(r"surtout|mostly|parce que|because|faute|à cause|diffère|differs|ne diffère|ensabl|stuck|tempête|storm"
                    r"|basculé|tipped|panne|breakdown|inconnu|illisible|unreadable|non numérique|non-numeric", re.I)


def test_every_adjective_or_cause_is_tied_to_a_fact(params):
    """Words that state a cause, a comparison or a drama appear only in lines with `needs` and a `when` or a marker."""
    for ln in lines(params):
        for text in ln["fr"] + ln["en"]:
            if CAUSAL.search(text):
                assert ln["needs"]
                assert ln.get("when") or any(m in ln["needs"] for m in markers(text)), ln["id"]


def test_condition_language():
    f = {"a": 3, "b": 0, "c": None, "s": "x", "l": ["u", "v"], "t": True}
    assert holds("a", f) and not holds("b", f) and holds("!b", f) and holds("!c", f) and holds("!zz", f)
    assert holds("a>=3", f) and holds("a>2", f) and not holds("a<3", f) and holds("a==3", f) and holds("a!=4", f)
    assert not holds("c>=0", f) and not holds("s>=0", f)           # comparison with None / str is false
    assert holds("s=x", f) and not holds("s=y", f) and holds("l:u", f) and not holds("l:w", f) and holds("t", f)
    with pytest.raises(ValueError):
        holds("a ~ 3", f)


def test_fill_formats_by_language():
    f = {"x": 0.5834, "n": 12, "w": "sand"}
    words = {"w": {"fr": {"sand": "le sable"}, "en": {"sand": "sand"}}}
    assert fill("{x:2} {n}", f, "fr") == "0,58 12" and fill("{x:2} {n}", f, "en") == "0.58 12"
    assert fill("sur {w}", f, "fr", words) == "sur le sable" and fill("on {w}", f, "en", words) == "on sand"
    with pytest.raises(KeyError):
        fill("{zz}", f, "fr")
    with pytest.raises(KeyError):
        fill("{x}", {"x": None}, "fr")


@pytest.mark.parametrize("stage", range(0, 7))
def test_one_entry_per_stage(params, state, stage):
    e = compose_entry(sample_facts(stage), state, params)
    assert e.fr and e.en and e.sol == 42 and e.epoch == 1
    for t in (e.fr, e.en):
        assert "{" not in t and "}" not in t and len(t) <= MAX_CHARS
    ids = [ln["id"] for ln in select(sample_facts(stage), state, params)]
    assert any(i.startswith("summary.") for i in ids)


def test_stage_lines_use_the_expected_facts(params, state):
    e0 = compose_entry(sample_facts(0, couples_sol=34, distance_m=41.0), state, params)
    assert "34 commandes" in e0.fr and "41 m" in e0.fr and "34 random commands" in e0.en and "41 m" in e0.en
    e1 = compose_entry(sample_facts(1, r2=0.58, r2_worst_terrain="sand"), state, params)
    assert "R² de 0,58" in e1.fr and "le sable" in e1.fr and "R² of 0.58" in e1.en and "on sand" in e1.en
    e2 = compose_entry(sample_facts(2, battery_successes=13, slip_worst_terrain="sand"), state, params)
    assert "13 des 20" in e2.fr and "glissé sur le sable" in e2.fr and "13 of the 20" in e2.en
    e3 = compose_entry(sample_facts(3), state, params)
    assert "22 % vers 18:40" in e3.fr and "Aucune panne" in e3.fr and "22% around 18:40" in e3.en and "No breakdown" in e3.en
    e4 = compose_entry(sample_facts(4, novel_vs_prev=3), state, params)
    assert "3 des échantillons précédents" in e4.fr and "3 of the earlier samples" in e4.en
    e5 = compose_entry(sample_facts(5, spectra=212, n_categories=6, ari=0.84, new_names=["Tervane"]), state, params)
    assert "212 spectres en 6 catégories" in e5.fr and "Tervane" in e5.fr and "212 spectra into 6 categories" in e5.en


def test_missing_fact_means_no_sentence(params, state):
    """A cause or comparison is never written without its fact: with the fact missing the line falls back."""
    ids = lambda f: [ln["id"] for ln in select(f, state, params)]
    assert "learn.s1.r2.terrain" in ids(sample_facts(1))
    assert "learn.s1.r2" in ids(sample_facts(1, r2_worst_terrain=None))
    assert "learn.generic" in ids(sample_facts(1, r2=None, r2_worst_terrain=None))
    assert "learn.s2.battery" in ids(sample_facts(2, slip_worst_terrain=None))
    assert "event.storm" not in ids(sample_facts(3, events=[]))
    assert not any(i.startswith("safe.") for i in ids(sample_facts(3, safe_actions=[])))
    assert "gap" not in ids(sample_facts(3, days_since_last_run=1))
    assert "gap" not in ids(sample_facts(3, days_since_last_run=None))
    assert "summary.idle" in ids(sample_facts(3, awake_ticks=0)) and "summary.s3" not in ids(sample_facts(3, awake_ticks=0))


@pytest.mark.parametrize("event", ["storm", "deposit", "anomaly", "impact"])
def test_every_event_has_an_entry(params, state, event):
    f = sample_facts(2, events=[event])
    assert f"event.{event}" in [ln["id"] for ln in select(f, state, params)]
    e = compose_entry(f, state, params)
    assert "{" not in e.fr + e.en and len(e.fr) <= MAX_CHARS and len(e.en) <= MAX_CHARS


@pytest.mark.parametrize("act", ["freed", "righted", "recharged", "noise_doubled"])
def test_every_safe_mode_intervention_has_an_entry(params, state, act):
    f = sample_facts(2, safe_actions=[act])
    assert f"safe.{act}" in [ln["id"] for ln in select(f, state, params)]
    e = compose_entry(f, state, params)
    if act != "recharged":
        assert "mode sûr" in e.fr.lower() and "safe mode" in e.en.lower()
    else:
        assert "40 %" in e.fr and "40%" in e.en           # P.rover.energy.safe_recharge, not a literal in the code


@pytest.mark.parametrize("cause", ["corrupt", "nan", "manual"])
@pytest.mark.parametrize("redone", [[42], [40, 41, 42]])
def test_restoration_names_the_real_cause_and_sols(params, state, cause, redone):
    e = compose_entry(sample_facts(2, restore_cause=cause, redone_sols=redone), state, params)
    back = min(redone) - 1
    assert f"sol {back} " in e.fr and f"sol {back};" in e.en
    assert ("40 à 42" in e.fr) == (len(redone) > 1) and ("sols 40 to 42" in e.en) == (len(redone) > 1)
    assert {"corrupt": "illisible", "nan": "pas un nombre", "manual": "manuelle"}[cause] in e.fr


def test_restoration_example_of_the_spec(params, state):
    e = compose_entry(sample_facts(2, restore_cause="corrupt", redone_sols=[40, 41, 42]), state, params)
    assert "Une partie de ma mémoire était illisible. Je suis reparti de ma sauvegarde du sol 39 ; les sols 40 à 42 sont refaits." in e.fr
    assert "Part of my memory was unreadable. I restarted from my backup of sol 39; sols 40 to 42 are redone." in e.en


def test_firmware_lock_first_time_then_every_28_sols(params):
    f = sample_facts(3, consolidation=True, sol=43)
    st = sample_state()
    e1 = compose_entry(f, st, params)
    assert "micrologiciel" in e1.fr and "firmware" in e1.en
    st["journal_tail"] = [{"epoch": 1, "sol": 43, "utc": "", "fr": e1.fr, "en": e1.en}]
    assert "micrologiciel" not in compose_entry(dict(f, sol=44), st, params).fr
    assert "micrologiciel" in compose_entry(dict(f, sol=56), st, params).fr          # 56 = 2 x 28


def test_other_extras(params, state):
    e = compose_entry(sample_facts(3, degraded=True, truncated_at={"module": "m0", "gen": 7}, days_since_last_run=3), state, params)
    assert "génération 7" in e.fr or "suspendu" in e.fr
    e = compose_entry(sample_facts(3, days_since_last_run=3), state, params)
    assert "Mon dernier contact date de 3 jours." in e.fr and "My last contact was 3 days ago." in e.en
    e = compose_entry(sample_facts(3, tipped=True, max_tilt_deg=31.4), state, params)
    assert "31°" in e.fr and "31°" in e.en


def test_first_times_have_a_line_each(params, state):
    covered = {i for ln in lines(params) for i in [ln["id"]]}
    for fid in FIRST_LABELS:
        assert fid in covered, fid


def test_length_budget_in_the_worst_case(params, state):
    """Everything true at once: the trim keeps both languages within 600 characters."""
    for stage in range(0, 7):
        f = sample_facts(stage, events=["storm", "deposit", "anomaly", "impact"], safe_actions=["freed", "righted", "recharged", "noise_doubled"],
                         stuck=True, tipped=True, breakdowns=3, forced_sleep_ticks=300, freed_by="reverse", advanced_to=min(stage, 5) or None,
                         restore_cause="corrupt", redone_sols=[40, 41, 42], consolidation=True, degraded=True,
                         truncated_at={"module": "m0", "gen": 3}, days_since_last_run=9, novel_vs_prev=3, spectra=212, n_categories=6,
                         ari=0.84, new_names=["Tervane"], samples=4, anomaly_seen=True, targets_reached=2,
                         firsts=["first.move", "first.stuck", "first.breakdown"])
        for sol in range(1, 60):
            e = compose_entry(dict(f, sol=sol), state, params)
            assert len(e.fr) <= MAX_CHARS and len(e.en) <= MAX_CHARS, (stage, sol)
        assert len(select(f, state, params)) <= 2 + 3


def test_core_lines_alone_fit(params):
    """The longest summary variant plus the longest learn variant, in each language, leaves room for extras."""
    for lang in ("fr", "en"):
        longest = {}
        for ln in lines(params):
            if ln["slot"] != "extra":
                for st in ln.get("stage", range(0, 6)):
                    longest[(ln["slot"], st)] = max(longest.get((ln["slot"], st), 0), max(map(len, ln[lang])) + 40)
        for st in range(6):
            assert longest[("summary", st)] + longest[("learn", st)] <= 450


def test_same_entry_same_text(params, state):
    f = sample_facts(3, events=["storm"], safe_actions=["righted"])
    a, b = compose_entry(f, state, params), compose_entry(dict(f), sample_state(), params)
    assert a == b


def test_variants_depend_on_the_sol(params, state):
    seen = {compose_entry(sample_facts(1, sol=s), state, params).fr.split(".")[0] for s in range(1, 40)}
    assert len(seen) == 2


def test_numbers_are_formatted_per_language(params, state):
    e = compose_entry(sample_facts(1, r2=0.5, r2_worst_terrain="ice"), state, params)
    assert "0,50" in e.fr and "0.50" in e.en and "0,50" not in e.en
    e = compose_entry(sample_facts(3, battery_min=0.5, battery_min_hour=5.0), state, params)
    assert "50 %" in e.fr and "50%" in e.en and "05:00" in e.fr


def test_derived_markers_come_from_facts_and_params(params):
    d = derived_markers(sample_facts(3, battery_min=0.224, battery_min_hour=18.67, new_names=["A", "B"],
                                     redone_sols=[3, 4], truncated_at={"module": "m1", "gen": 2}), params)
    assert d["battery_pct"] == 22 and d["battery_clock"] == "18:40" and d["new_name"] == "B"
    assert (d["redone_n"], d["redone_first"], d["redone_last"], d["restored_sol"]) == (2, 3, 4, 2)
    assert (d["truncated_module"], d["truncated_gen"]) == ("m1", 2)
    assert d["storm_view_pct"] == 50 and d["safe_recharge_pct"] == 40 and d["cutoff_pct"] == 15 and d["battery_n"] == 20


def test_detect_firsts(params):
    st = sample_state()
    f = sample_facts(1, advanced_to=1, awake_cells=3.0, targets_reached=1, events=["storm"], breakdowns=1, night_drive_ticks=5,
                     stuck=True, anomaly_seen=True, samples=1, spectra=2, new_categories=1)
    got = dict(detect_firsts(f, st))
    assert set(got) == {"first.move", "first.stage.1", "first.image", "first.target", "first.storm", "first.breakdown",
                        "first.night_drive", "first.stuck", "first.anomaly", "first.sample", "first.spectrum", "first.category"}
    assert set(got.values()) == {42}
    assert [i for i, _ in detect_firsts(sample_facts(3, freed_by="reverse", awake_cells=0.0), st)] == ["first.stuck"]
    st["firsts"] = {k: [1, 42] for k in got}
    assert detect_firsts(f, st) == []
    assert detect_firsts(sample_facts(3, awake_cells=0.5), sample_state()) == []
