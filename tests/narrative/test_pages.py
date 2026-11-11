"""Pages written on main (SPEC 8.1, 8.6) and static pages (SPEC 9)."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from rover.core.types import JournalEntry
from rover.narrative import write_pages
from rover.narrative.pages import check_repo, render_readme_section, tag_name
from rover.narrative.refs import sample_state

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "pages"
USERS = "/User" + "s/"
E = lambda sol, epoch=1, utc="2026-11-21T07:17:00Z": JournalEntry(epoch, sol, utc, f"fr {sol}", f"en {sol}")


def test_journal_append_only_and_idempotent(params, tmp_path):
    st = sample_state()
    w1 = write_pages(tmp_path, st, [E(41), E(42)], params, "owner/repo")
    text = (tmp_path / "journal" / "2026-11.md").read_text(encoding="utf-8")
    assert text.count("### Sol") == 2 and "### Sol 0042 · 2026-11-21 07:17 UTC\n**FR** — fr 42\n**EN** — en 42" in text
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    w2 = write_pages(tmp_path, st, [E(41), E(42)], params, "owner/repo")
    assert w2 == [] and {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == snapshot
    assert any(p.name == "2026-11.md" for p in w1)


def test_existing_entry_is_never_rewritten(params, tmp_path):
    st = sample_state()
    write_pages(tmp_path, st, [E(42)], params, "owner/repo")
    write_pages(tmp_path, st, [JournalEntry(1, 42, "2026-11-21T07:17:00Z", "autre", "other"), E(43)], params, "owner/repo")
    text = (tmp_path / "journal" / "2026-11.md").read_text(encoding="utf-8")
    assert "autre" not in text and text.count("### Sol 0042") == 1 and "### Sol 0043" in text


def test_new_epoch_makes_new_entries(params, tmp_path):
    st = sample_state()
    write_pages(tmp_path, st, [E(42)], params, "owner/repo")
    write_pages(tmp_path, st, [E(42, epoch=2)], params, "owner/repo")
    text = (tmp_path / "journal" / "2026-11.md").read_text(encoding="utf-8")
    assert "### Sol 0042 · 2026-11-21 07:17 UTC" in text and "### Sol 0042 · epoch 2 · 2026-11-21 07:17 UTC" in text


def test_months_and_index(params, tmp_path):
    write_pages(tmp_path, sample_state(), [E(1, utc="2026-11-30T23:00:00Z"), E(2, utc="2026-12-01T05:00:00Z")], params, "o/r")
    idx = (tmp_path / "journal" / "README.md").read_text(encoding="utf-8")
    assert "[2026-11](2026-11.md)" in idx and "[2026-12](2026-12.md)" in idx and "Journal de Sol-0" in idx


def test_writes_only_under_journal_atlas_firsts(params, tmp_path):
    write_pages(tmp_path, sample_state(), [E(1)], params, "o/r")
    tops = {p.relative_to(tmp_path).parts[0] for p in tmp_path.rglob("*") if p.is_file()}
    assert tops == {"journal", "atlas", "firsts"}


def test_firsts_page_tags_and_urls_come_from_repo(params, tmp_path):
    st = sample_state()
    st["firsts"] = {"first.stage.1": [1, 12], "first.move": [1, 1], "first.stuck": [2, 90]}
    write_pages(tmp_path, st, [], params, "acme/rover-x")
    t = (tmp_path / "firsts" / "README.md").read_text(encoding="utf-8")
    assert "m-e1-sol0001-first-move" in t and "m-e1-sol0012-first-stage-1" in t and "m-e2-sol0090-first-stuck" in t
    assert "https://raw.githubusercontent.com/acme/rover-x/m-e1-sol0001-first-move/console.gif" in t
    assert t.index("Sol 0001") < t.index("Sol 0012") < t.index("Sol 0090")
    assert "I CAN MOVE" in t and "Premier déplacement / First movement" in t and "epoch 2" in t


def test_firsts_page_without_repo_has_no_links(params, tmp_path):
    st = sample_state()
    st["firsts"] = {"first.move": [1, 1]}
    write_pages(tmp_path, st, [], params, "")
    t = (tmp_path / "firsts" / "README.md").read_text(encoding="utf-8")
    assert "m-e1-sol0001-first-move" in t and "http" not in t


def test_tag_name_matches_the_pipeline_construction():
    from rover.pipeline.sol import _tag
    for e, s, f in ((1, 42, "first.move"), (2, 7, "first.stage.3")):
        assert tag_name(e, s, f) == _tag(e, s, f)


def test_atlas_none_before_stage_5_then_listed(params, tmp_path):
    st = sample_state(3)
    st["names"] = {"c1": {"name": "Tervane", "sol": 300}}
    write_pages(tmp_path, st, [], params, "o/r")
    assert "Aucune entrée" in (tmp_path / "atlas" / "README.md").read_text(encoding="utf-8")
    st5 = sample_state(5)
    st5["names"] = {"c1": {"name": "Tervane", "sol": 300}, "c2": "Mokar"}
    write_pages(tmp_path, st5, [], params, "o/r")
    a = (tmp_path / "atlas" / "README.md").read_text(encoding="utf-8")
    assert "**Tervane**" in a and "**Mokar**" in a and "sol 0300" in a
    write_pages(tmp_path, sample_state(5), [], params, "o/r")
    assert "Aucune entrée" in (tmp_path / "atlas" / "README.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- static pages
def test_readme_section_markers_and_tokens():
    t = (PAGES / "readme-section.md").read_text(encoding="utf-8")
    assert t.startswith("<!-- sol-0:start -->\n") and t.rstrip().endswith("<!-- sol-0:end -->")
    assert t.count("<!-- sol-0:start -->") == 1 and t.count("<!-- sol-0:end -->") == 1
    assert "## Sol-0" in t
    for f in ("console.gif", "status.svg", "map.png"):
        assert f"https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/{f}" in t
    assert 'width="640"' in t


def test_readme_section_has_no_hard_coded_account():
    t = (PAGES / "readme-section.md").read_text(encoding="utf-8")
    for url in re.findall(r"https://[^\s\"')]+", t):
        assert "{OWNER}" in url and "{REPO}" in url, url
    assert USERS not in t


def test_readme_section_text_and_alts_are_bilingual():
    t = (PAGES / "readme-section.md").read_text(encoding="utf-8")
    for s in ("Console de Sol-0 : caméra CAM-1, cerveau en fonctionnement, carte locale et télémétrie du dernier sol / "
              "Sol-0 console: CAM-1 camera, live brain, local map and telemetry of the last sol",
              "Statut de Sol-0 : sol, stade, progression mesurée / Sol-0 status: sol, stage, measured progress",
              "Carte explorée par Sol-0 avec brouillard / Map explored by Sol-0 with fog of war",
              "Un rover simulé qui apprend seul à exister sur une planète procédurale.",
              "A simulated rover that learns on its own to exist on a procedural planet.",
              "Mis à jour 4 fois par jour par GitHub Actions. Tout ce qui est affiché vient du calcul réel.",
              "Updated 4 times a day by GitHub Actions. Everything shown comes from the actual computation."):
        assert s in t, s


def test_render_readme_section_builds_urls_from_repo():
    t = render_readme_section((PAGES / "readme-section.md").read_text(encoding="utf-8"), "acme/rover-x")
    assert "{OWNER}" not in t and "{REPO}" not in t and "{" not in t
    assert "https://raw.githubusercontent.com/acme/rover-x/state/console.gif" in t
    assert render_readme_section(render_readme_section("{OWNER}/{REPO}", "a/b"), "c/d") == "a/b"


@pytest.mark.parametrize("bad", ["", "owner", "a/b/c", "a b/c", "../x/y", "a/b;rm"])
def test_bad_repo_is_refused(bad):
    with pytest.raises(ValueError):
        check_repo(bad)


def _links(md: str) -> list:
    out = []
    for m in re.finditer(r"\]\(([^)]+)\)|href=\"([^\"]+)\"", md):
        out.append(m.group(1) or m.group(2))
    return out


def test_relative_links_resolve(params, tmp_path):
    """pages/ copied next to the generated pages: every relative link of pages/ and of the README section exists."""
    shutil.copytree(PAGES, tmp_path / "pages")
    st = sample_state()
    st["firsts"] = {"first.move": [1, 1]}
    write_pages(tmp_path, st, [E(1)], params, "o/r")
    (tmp_path / "README.md").write_text(render_readme_section((PAGES / "readme-section.md").read_text(encoding="utf-8"), "o/r"),
                                        encoding="utf-8")
    checked = 0
    for md in [tmp_path / "README.md", *sorted(q for q in (tmp_path / "pages").glob("how-it-works.*.md")), *sorted((tmp_path / "journal").glob("*.md")),
               *sorted((tmp_path / "firsts").glob("*.md")), *sorted((tmp_path / "atlas").glob("*.md"))]:
        for link in _links(md.read_text(encoding="utf-8")):
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = (md.parent / link.split("#")[0]).resolve()
            assert target.exists(), f"{md.name}: broken link {link}"
            checked += 1
    assert checked >= 12


def test_how_it_works_pages_match_the_config(params):
    fr = (PAGES / "how-it-works.fr.md").read_text(encoding="utf-8")
    en = (PAGES / "how-it-works.en.md").read_text(encoding="utf-8")
    stages = params.get("stages.stage")
    for s in stages:
        assert s["name"] in fr and s["name"] in en
    assert "200" in fr and "200" in en and stages[0]["threshold"] == 200
    assert stages[2]["threshold"] == 16 and "16" in fr and "16" in en
    assert stages[3]["threshold"] == 20 and "20 sols" in en and "20 sols" in fr
    assert params.get("brain.es.pop") == 48 and "48" in fr and "48" in en
    assert params.get("run.ticks_per_sol") == 1200 and params.get("run.tick_s") == 72
    for t in (fr, en):
        assert "1 200" in t or "1,200" in t
        assert "../journal/README.md" in t and "../atlas/README.md" in t and "../firsts/README.md" in t
    assert "how-it-works.en.md" in fr and "how-it-works.fr.md" in en
    from rover.version import MAX_STAGE
    assert MAX_STAGE == 3 and "stades 0 à 3" in fr and "stages 0 to 3" in en      # update with MAX_STAGE


def test_static_pages_state_the_rule_everything_is_real():
    fr = (PAGES / "how-it-works.fr.md").read_text(encoding="utf-8")
    en = (PAGES / "how-it-works.en.md").read_text(encoding="utf-8")
    assert "réel" in fr and "real" in en and "exactement l'entrée" in fr and "exactly the input" in en
    assert "cible de navigation" in fr and "navigation target" in en


def test_no_absolute_user_path_or_secret_in_deliverables():
    for f in [*PAGES.glob("*.md"), *(ROOT / "config" / "narrative").glob("*.toml"), *(ROOT / "src" / "rover" / "narrative").glob("*.py")]:
        t = f.read_text(encoding="utf-8")
        assert USERS not in t, f
        assert not re.search(r"ghp_|github_pat_|BEGIN [A-Z ]*PRIVATE", t), f
