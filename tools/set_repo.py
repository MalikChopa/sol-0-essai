#!/usr/bin/env python3
"""Adapt an exported copy to a repository (ARCH 9). Idempotent; never writes inside the project tree itself.

  set_repo.py --trial --repo OWNER/REPO --dir DIR   trial variant of the workflow + README = section only
  set_repo.py --prod  --repo OWNER/REPO --readme FILE [--section FILE] [--out FILE]
                                                    insert the section between the markers of a COPY of a README
`pages/readme-section.md` (SPEC 9): tokens {OWNER} and {REPO} (repository name only), markers <!-- sol-0:start --> / <!-- sol-0:end -->.
If the section file is absent (before J4 delivers it), a minimal section with the raw GIF URL is used.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN, END = "<!-- sol-0:start -->", "<!-- sol-0:end -->"      # SPEC 9 (J6: aligned with pages/readme-section.md)
PROD_CRON = 'cron: "17 1,7,13,19 * * *"'
TRIAL_CRON = 'cron: "23 * * * *"'
FAULT_INPUT = '      fault:\n        type: choice\n        options: [none, corrupt, nan]\n        default: none\n'


def trial_workflow(text: str) -> str:
    if TRIAL_CRON in text:
        return text                                    # idempotent
    def once(s, old, new):
        if s.count(old) != 1:
            raise ValueError(f"expected exactly one occurrence of {old!r}")
        return s.replace(old, new)
    text = once(text, PROD_CRON, TRIAL_CRON)
    text = once(text, '      checkpoint:\n        type: string\n        default: ""\n',
                '      checkpoint:\n        type: string\n        default: ""\n' + FAULT_INPUT)
    text = once(text, "      CHECKPOINT: ${{ inputs.checkpoint || '' }}\n",
                "      CHECKPOINT: ${{ inputs.checkpoint || '' }}\n      FAULT: ${{ inputs.fault || 'none' }}\n      SOL0_TRIAL: \"1\"\n")
    text = once(text, 'python tools/ci/validate_inputs.py "$MODE" "$CHECKPOINT"', 'python tools/ci/validate_inputs.py "$MODE" "$CHECKPOINT" "$FAULT"')
    text = once(text, '--repo "$GITHUB_REPOSITORY"', '--repo "$GITHUB_REPOSITORY" --fault "$FAULT"')
    return text


def section_text(repo: str, section: Path | None) -> str:
    owner, name = repo.split("/")
    if section is not None and section.is_file():
        body = section.read_text(encoding="utf-8")
    else:
        body = (f"{BEGIN}\n# Sol-0\n\n![Sol-0 console](https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/console.gif)\n\n"
                f"![Sol-0 status](https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/status.svg)\n\n"
                f"![Sol-0 map](https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/map.png)\n{END}\n")
    return body.replace("{OWNER}", owner).replace("{REPO}", name)


def check_not_project(d: Path) -> None:
    d = d.resolve()
    if d == ROOT or (d / "CLAUDE.md").exists() or (d / "docs" / "HANDOFF.md").exists():
        raise SystemExit("refused: that folder looks like the project tree, not an export")


def insert_section(readme: str, section: str) -> str:
    sec = section if section.endswith("\n") else section + "\n"
    if BEGIN in readme and END in readme:
        pre, rest = readme.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        inner = sec[sec.index(BEGIN) + len(BEGIN):sec.rindex(END)] if BEGIN in sec and END in sec else sec
        return pre + BEGIN + inner + END + post
    inner = sec if BEGIN not in sec else sec[sec.index(BEGIN) + len(BEGIN):sec.rindex(END)]
    sep = "" if readme.endswith("\n\n") or not readme else ("\n" if readme.endswith("\n") else "\n\n")
    return readme + sep + BEGIN + inner + END + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--trial", action="store_true")
    g.add_argument("--prod", action="store_true")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dir")
    ap.add_argument("--readme")
    ap.add_argument("--section")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a.repo):
        print("bad --repo", file=sys.stderr)
        return 2
    sec_path = Path(a.section) if a.section else None
    if a.trial:
        if not a.dir:
            print("--trial needs --dir", file=sys.stderr)
            return 2
        d = Path(a.dir)
        check_not_project(d)
        wf = d / ".github" / "workflows" / "sol.yml"
        wf.write_text(trial_workflow(wf.read_text(encoding="utf-8")), encoding="utf-8")
        if sec_path is None and (d / "pages" / "readme-section.md").is_file():
            sec_path = d / "pages" / "readme-section.md"
        sec = section_text(a.repo, sec_path)
        if BEGIN not in sec:
            sec = BEGIN + "\n" + sec + "\n" + END + "\n"
        (d / "README.md").write_text(sec, encoding="utf-8")
        print(f"trial variant written in {d}")
        return 0
    if not a.readme:
        print("--prod needs --readme", file=sys.stderr)
        return 2
    src = Path(a.readme)
    out = Path(a.out) if a.out else src
    o = out.resolve()
    if ROOT in o.parents and ROOT / "out" not in o.parents:
        print("refused: output inside the project tree", file=sys.stderr)
        return 2
    out.write_text(insert_section(src.read_text(encoding="utf-8"), section_text(a.repo, sec_path)), encoding="utf-8")
    print(f"section inserted in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
