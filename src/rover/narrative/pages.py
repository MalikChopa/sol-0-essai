"""Pages written on main (SPEC 8.6): journal/, firsts/README.md, atlas/README.md; README section helper (SPEC 9).

Everything written here comes from the entries and the state: the journal is append only, the other two pages are
regenerated whole from `state.firsts` and `state.names` (same input, same bytes). Nothing is written outside
main_dir/journal, main_dir/firsts and main_dir/atlas.
"""
from __future__ import annotations

import re
from pathlib import Path

from rover.config import Params
from rover.core.types import JournalEntry

_HEAD = re.compile(r"^### Sol (\d+)(?: · epoch (\d+))? · ", re.M)
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
ATLAS_MIN_STAGE = 5

FIRST_LABELS = {
    "first.move": ("Premier déplacement", "First movement"),
    "first.image": ("Première image résumée en 8 nombres", "First image summarised in 8 numbers"),
    "first.target": ("Première cible atteinte", "First target reached"),
    "first.storm": ("Première tempête de poussière", "First dust storm"),
    "first.breakdown": ("Première panne de batterie", "First battery breakdown"),
    "first.night_drive": ("Première conduite de nuit", "First night drive"),
    "first.stuck": ("Premier ensablement", "First time stuck in sand"),
    "first.sample": ("Premier prélèvement", "First sample"),
    "first.spectrum": ("Premier spectre", "First spectrum"),
    "first.category": ("Première catégorie reconnue", "First category recognised"),
    "first.anomaly": ("Première anomalie vue", "First anomaly seen"),
}


def _when(utc: str) -> str:
    return utc[:10] + " " + utc[11:16] + " UTC"


def _block(e: JournalEntry) -> str:
    ep = f" · epoch {e.epoch}" if e.epoch > 1 else ""
    return f"### Sol {e.sol:04d}{ep} · {_when(e.utc)}\n**FR** — {e.fr}\n**EN** — {e.en}\n\n"


def check_repo(repo: str) -> str:
    if not _REPO.match(repo or ""):
        raise ValueError(f"repo must look like OWNER/REPO, got {repo!r}")
    return repo


def render_readme_section(text: str, repo: str) -> str:
    """Replace the {OWNER} and {REPO} tokens of pages/readme-section.md (SPEC 9)."""
    owner, name = check_repo(repo).split("/")
    return text.replace("{OWNER}", owner).replace("{REPO}", name)


def tag_name(epoch: int, sol: int, fid: str) -> str:
    """Same construction as pipeline.sol._tag (SPEC 8.5)."""
    return "m-e%d-sol%04d-%s" % (epoch, sol, fid.replace(".", "-"))


def _first_label(fid: str, params: Params) -> tuple:
    if fid.startswith("first.stage."):
        n = int(fid.rsplit(".", 1)[1])
        name = params.get("stages.stage")[n]["name"]
        return (f"Entrée au stade {n} : {name}", f"Entered stage {n}: {name}")
    return FIRST_LABELS[fid]


def firsts_page(state: dict, params: Params, repo: str) -> str:
    linked = bool(_REPO.match(repo or ""))      # no --repo (local run): tag names without links
    items = sorted(((int(v[0]), int(v[1]), k) for k, v in state["firsts"].items()))
    out = ["# Premières fois | Firsts\n\n"]
    if not items:
        out.append("Aucune entrée pour l'instant. | No entry yet.\n")
        return "".join(out)
    out.append("Chaque première fois a un tag Git ; le lien ouvre l'image de la console à cet instant. | "
               "Each first has a Git tag; the link opens the console image at that moment.\n\n")
    for epoch, sol, fid in items:
        fr, en = _first_label(fid, params)
        tag = tag_name(epoch, sol, fid)
        ep = f", epoch {epoch}" if epoch > 1 else ""
        link = f" · [console.gif](https://raw.githubusercontent.com/{repo}/{tag}/console.gif)" if linked else ""
        out.append(f"- **Sol {sol:04d}**{ep} · {fr} / {en} · `{tag}`{link}\n")
    return "".join(out)


def atlas_page(state: dict, params: Params) -> str:
    out = ["# Atlas\n\n"]
    names = state.get("names") or {}
    if int(state["stage"]["id"]) < ATLAS_MIN_STAGE or not names:
        out.append("Aucune entrée. | No entry.\n")
        return "".join(out)
    for key in sorted(names):
        v = names[key]
        if isinstance(v, dict):
            name = str(v.get("name", key))
            where = f" · sol {int(v['sol']):04d}" if "sol" in v else ""
        else:
            name, where = str(v), ""
        out.append(f"- **{name}** · {key}{where}\n")
    return "".join(out)


def _write_if_changed(path: Path, text: str, written: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
        written.append(path)


def write_pages(main_dir: Path, state: dict, entries: list, params: Params, repo: str) -> list:
    main_dir = Path(main_dir)
    jdir = main_dir / "journal"
    jdir.mkdir(parents=True, exist_ok=True)
    written: list = []
    by_month: dict = {}
    for e in entries:
        by_month.setdefault(e.utc[:7], []).append(e)
    for month in sorted(by_month):
        f = jdir / f"{month}.md"
        text = f.read_text(encoding="utf-8") if f.exists() else f"# Journal | Journal — {month}\n\n"
        have = {(int(m.group(2) or 1), int(m.group(1))) for m in _HEAD.finditer(text)}
        add = []
        for e in sorted(by_month[month], key=lambda x: (x.epoch, x.sol)):
            if (e.epoch, e.sol) not in have:
                add.append(e)
                have.add((e.epoch, e.sol))
        if add:
            f.write_text(text + "".join(_block(e) for e in add), encoding="utf-8")
            written.append(f)
    months = sorted(p.stem for p in jdir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md"))
    idx = "# Journal of Sol-0 | Journal de Sol-0\n\n" + "".join(f"- [{m}]({m}.md)\n" for m in months)
    _write_if_changed(jdir / "README.md", idx, written)
    _write_if_changed(main_dir / "firsts" / "README.md", firsts_page(state, params, repo), written)
    _write_if_changed(main_dir / "atlas" / "README.md", atlas_page(state, params), written)
    return written
