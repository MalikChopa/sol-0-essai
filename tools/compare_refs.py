#!/usr/bin/env python3
"""Compare two `rover refs` JSON files (Mac vs runner). Exit 0 = identical, 1 = differences, 2 = unreadable input.

Usage:
  compare_refs.py A.json B.json [--only PREFIX[,PREFIX...]]
  compare_refs.py A.json --run RUN_ID --repo OWNER/REPO       (B read from the job log of a `refs` run)
The runner side is printed by tools/ci/emit_refs.py between the lines REFS-BEGIN and REFS-END.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def extract_from_log(log: str) -> dict:
    lines, inside = [], False
    for raw in log.splitlines():
        text = raw.split("\t")[-1]
        text = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ", "", text)
        if text.strip() == "REFS-BEGIN":
            inside, lines = True, []
        elif text.strip() == "REFS-END":
            inside = False
            break
        elif inside:
            lines.append(text)
    if inside or not lines:
        raise ValueError("REFS-BEGIN/REFS-END block not found in the log")
    return json.loads("\n".join(lines))


def compare(a: dict, b: dict, only: list[str] | None = None) -> dict:
    if only:
        a = {k: v for k, v in a.items() if any(k.startswith(p) for p in only)}
        b = {k: v for k, v in b.items() if any(k.startswith(p) for p in only)}
    ka, kb = set(a), set(b)
    diff = sorted(k for k in ka & kb if a[k] != b[k])
    return {"equal": sorted(k for k in ka & kb if a[k] == b[k]), "different": diff,
            "only_a": sorted(ka - kb), "only_b": sorted(kb - ka)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b", nargs="?")
    ap.add_argument("--run")
    ap.add_argument("--repo")
    ap.add_argument("--only", default="")
    n = ap.parse_args(argv)
    try:
        a = json.loads(Path(n.a).read_text(encoding="utf-8"))
        if n.run:
            if not n.repo:
                raise ValueError("--run needs --repo")
            if not re.fullmatch(r"[0-9]+", n.run) or not re.fullmatch(r"[\w.-]+/[\w.-]+", n.repo):
                raise ValueError("bad --run or --repo")
            log = subprocess.run(["gh", "run", "view", n.run, "-R", n.repo, "--log"], capture_output=True, text=True, check=True).stdout
            b = extract_from_log(log)
        elif n.b:
            b = json.loads(Path(n.b).read_text(encoding="utf-8"))
        else:
            raise ValueError("second file or --run needed")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"compare_refs: {exc}", file=sys.stderr)
        return 2
    r = compare(a, b, [p for p in n.only.split(",") if p])
    print(f"equal: {len(r['equal'])}  different: {len(r['different'])}  only A: {len(r['only_a'])}  only B: {len(r['only_b'])}")
    for k in r["different"]:
        print(f"DIFF {k}\n  A {a[k]}\n  B {b[k]}")
    for k in r["only_a"]:
        print(f"ONLY-A {k}")
    for k in r["only_b"]:
        print(f"ONLY-B {k}")
    return 0 if not (r["different"] or r["only_a"] or r["only_b"]) and r["equal"] else 1


if __name__ == "__main__":
    sys.exit(main())
