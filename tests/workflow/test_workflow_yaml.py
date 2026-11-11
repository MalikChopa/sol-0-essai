"""Workflow YAML, trial variant, uses: SHAs, lock hashes, no network in src/rover (J8a acceptance)."""
from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import set_repo  # noqa: E402

WF = ROOT / ".github" / "workflows" / "sol.yml"


def load(text):
    return yaml.safe_load(text)


def test_production_workflow_shape():
    d = load(WF.read_text())
    on = d[True]                                           # YAML 1.1: the key `on` reads as True
    assert set(on) == {"schedule", "workflow_dispatch"}    # EF-05: no other trigger
    assert on["schedule"] == [{"cron": "17 1,7,13,19 * * *"}]
    assert on["workflow_dispatch"]["inputs"]["mode"]["options"] == ["sol", "check", "refs", "restore"]
    assert d["permissions"] == {"contents": "write"}
    assert d["concurrency"] == {"group": "sol-0", "cancel-in-progress": False}
    job = d["jobs"]["sol"]
    assert job["timeout-minutes"] == 15 and job["runs-on"] == "ubuntu-latest"
    assert "SOL0_TRIAL" not in job["env"]
    assert "pull_request_target" not in WF.read_text()
    assert "secrets." not in WF.read_text()


def test_inputs_go_through_env_not_shell_text():
    text = WF.read_text()
    run_lines = [l for l in text.splitlines() if "run:" in l or l.strip().startswith("python") or l.strip().startswith("bash")]
    assert not any("${{ inputs" in l for l in run_lines)


def test_uses_are_pinned_to_40_hex_sha():
    d = load(WF.read_text())
    uses = [s["uses"] for s in d["jobs"]["sol"]["steps"] if "uses" in s]
    assert uses
    for u in uses:
        assert re.fullmatch(r"actions/[\w-]+@[0-9a-f]{40}", u), u
    assert {u.split("@")[0] for u in uses} == {"actions/checkout", "actions/setup-python"}   # no other third-party action


def test_trial_variant_differs_only_by_the_declared_lines():
    prod = WF.read_text()
    trial = set_repo.trial_workflow(prod)
    assert set_repo.trial_workflow(trial) == trial         # idempotent
    p, t = load(prod), load(trial)
    assert p[True]["schedule"] == [{"cron": "17 1,7,13,19 * * *"}]
    assert t[True]["schedule"] == [{"cron": "23 * * * *"}]
    assert t[True]["workflow_dispatch"]["inputs"]["fault"]["options"] == ["none", "corrupt", "nan"]
    assert t["jobs"]["sol"]["env"]["SOL0_TRIAL"] == "1"
    # everything else is equal once the declared differences are removed
    t[True]["schedule"] = p[True]["schedule"]
    del t[True]["workflow_dispatch"]["inputs"]["fault"]
    del t["jobs"]["sol"]["env"]["SOL0_TRIAL"], t["jobs"]["sol"]["env"]["FAULT"]
    for s in t["jobs"]["sol"]["steps"]:
        for k in ("run",):
            if k in s:
                s[k] = s[k].replace(' --fault "$FAULT"', "").replace(' "$FAULT"', "")
    assert t == p
    only = [l for l in set(trial.splitlines()) ^ set(prod.splitlines())]
    assert len(only) <= 14


def test_sol_step_has_fault_only_in_trial():
    prod, trial = WF.read_text(), set_repo.trial_workflow(WF.read_text())
    assert "--fault" not in prod and '--fault "$FAULT"' in trial


LOCK = (ROOT / "requirements.lock").read_text()


def test_lock_has_exact_versions_and_hashes():
    blocks = re.findall(r"^([\w.-]+)==([\w.]+) \\\n((?:\s+--hash=sha256:[0-9a-f]{64}(?: \\)?\n?)+)", LOCK, re.M)
    names = {b[0]: b for b in blocks}
    assert set(names) == {"numpy", "pillow"}
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", names["numpy"][2])) == 3     # manylinux x86-64 + 2 macOS arm64
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", names["pillow"][2])) == 2    # manylinux x86-64 + macOS arm64
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'numpy==%s' % names["numpy"][1] in pyproject and 'Pillow==%s' % names["pillow"][1] in pyproject


def test_lock_hashes_match_pypi():
    for name, ver in (("numpy", "2.5.4"), ("pillow", "13.0.0")):
        try:
            data = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=30))
        except OSError:
            pytest.skip("PyPI unreachable")
        digests = {f["digests"]["sha256"] for f in data["urls"]}
        block = re.search(rf"^{name}==[\w.]+ \\\n((?:[ ]+--hash=.*\n?)+)", LOCK, re.M).group(1)
        for h in re.findall(r"sha256:([0-9a-f]{64})", block):
            assert h in digests


def test_no_network_in_src_rover():
    banned = {"socket", "urllib", "http", "requests", "ftplib", "smtplib", "ssl", "asyncio", "xmlrpc", "telnetlib", "aiohttp", "httpx"}
    bad = []
    for f in (ROOT / "src" / "rover").rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            for m in mods:
                if m.split(".")[0] in banned:
                    bad.append((f.name, m))
    assert not bad, bad


def test_set_repo_trial_is_idempotent_and_does_not_touch_the_project(tmp_path):
    d = tmp_path / "exp"
    (d / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(WF, d / ".github" / "workflows" / "sol.yml")
    before = {p: p.read_bytes() for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and "out" not in p.relative_to(ROOT).parts[:1] and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts}
    assert set_repo.main(["--trial", "--repo", "someone/some-repo", "--dir", str(d)]) == 0
    snap = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert set_repo.main(["--trial", "--repo", "someone/some-repo", "--dir", str(d)]) == 0
    assert snap == {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    after = {p: p.read_bytes() for p in before}
    assert before == after
    readme = (d / "README.md").read_text()
    assert "raw.githubusercontent.com/someone/some-repo/state/console.gif" in readme
    # J6: aligned with SPEC 9 (markers sol-0:start/end, tokens {OWNER}/{REPO}); the J8a version asserted SOL0:BEGIN and {{ }}
    assert readme.count("<!-- sol-0:start -->") == 1 and readme.count("<!-- sol-0:end -->") == 1
    assert "{OWNER}" not in readme and "{REPO}" not in readme


def test_set_repo_refuses_the_project_tree():
    with pytest.raises(SystemExit):
        set_repo.main(["--trial", "--repo", "a/b", "--dir", str(ROOT)])


def test_set_repo_prod_inserts_between_markers_idempotently(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# me\n\ntext\n")
    out = tmp_path / "copy.md"
    assert set_repo.main(["--prod", "--repo", "a/b", "--readme", str(readme), "--out", str(out)]) == 0
    first = out.read_text()
    assert first.startswith("# me") and first.count(set_repo.BEGIN) == 1
    out2 = tmp_path / "copy2.md"
    assert set_repo.main(["--prod", "--repo", "a/b", "--readme", str(out), "--out", str(out2)]) == 0
    assert out2.read_text() == first
    assert readme.read_text() == "# me\n\ntext\n"                # original untouched


def test_every_state_writing_mode_passes_now():
    d = load(WF.read_text())
    for s in d["jobs"]["sol"]["steps"]:
        run = s.get("run", "")
        if "-m rover sol" in run or "-m rover restore" in run:
            assert '--now "$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in run, s["name"]
