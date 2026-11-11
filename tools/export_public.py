#!/usr/bin/env python3
"""Build the public perimeter (ARCH 9): whitelist copy of the project + ONE commit without history.

Usage: export_public.py --out DIR [--list] [--no-commit]
Never exported: CLAUDE.md, docs/ (except OPERATIONS.md and MAINTENANCE.md), .claude/, tools/sonde-essai/, maquette/, out/.
Also exported when present (JT, fixed teaser): assets/trailer.gif and tools/trailer/ (absence tolerated).
Exit 1 if an exported file contains the home-directory marker or a pattern of `.private_patterns`
(local, git-ignored file, one regex per line; its content is never printed).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ["src", "config", "tests", "tools/ci", "tools/brain", "tools/render", "tools/trailer", "pages", ".github"]
GLOBS = ["tools/*.py", "tools/chain.sh", "pyproject.toml", "requirements.lock", "requirements-dev.txt",
         "docs/OPERATIONS.md", "docs/MAINTENANCE.md", "assets/trailer.gif"]
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".hypothesis", ".DS_Store"}
GITIGNORE = "_in/\n_out/\nout/\n__pycache__/\n.pytest_cache/\n.hypothesis/\n.venv/\n"
HOME_MARKER = "/Us" + "ers/"


def list_files(root: Path = ROOT) -> list[str]:
    found: set[str] = set()
    for d in DIRS:
        base = root / d
        if base.is_dir():
            for f in base.rglob("*"):
                if f.is_file() and not (set(f.relative_to(root).parts) & SKIP_PARTS) and f.suffix != ".pyc":
                    found.add(f.relative_to(root).as_posix())
    for g in GLOBS:
        for f in root.glob(g):
            if f.is_file():
                found.add(f.relative_to(root).as_posix())
    return sorted(found)


def private_regexes(root: Path = ROOT) -> list[re.Pattern]:
    p = root / ".private_patterns"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line.encode("utf-8"), re.IGNORECASE))
    return out


def scan(files: list[str], root: Path = ROOT) -> list[str]:
    """Names of files that contain the home marker or a private pattern (patterns never returned)."""
    pats = private_regexes(root)
    bad = []
    for rel in files:
        data = (root / rel).read_bytes()
        if HOME_MARKER.encode() in data or any(p.search(data) for p in pats):
            bad.append(rel)
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--list", action="store_true", help="print the file list only")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    files = list_files(root)
    bad = scan(files, root)
    if a.list:
        print("\n".join(files))
        return 1 if bad else 0
    if bad:
        print("export refused: private marker found in: " + ", ".join(bad), file=sys.stderr)
        return 1
    out = Path(a.out).resolve()
    if out == root or root in out.parents and (out / "CLAUDE.md").exists() or out in root.parents:
        print("refused: bad output folder", file=sys.stderr)
        return 2
    if out.exists():
        if any(out.iterdir()):
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for rel in files:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    (out / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    if not a.no_commit:
        env = {**os.environ, "GIT_AUTHOR_NAME": "sol-0", "GIT_AUTHOR_EMAIL": "sol-0@users.noreply.github.com",
               "GIT_COMMITTER_NAME": "sol-0", "GIT_COMMITTER_EMAIL": "sol-0@users.noreply.github.com",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "Sol-0: public export (no history)"]):
            subprocess.run(["git", *cmd], cwd=str(out), env=env, check=True)
    print(f"exported {len(files)} files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
