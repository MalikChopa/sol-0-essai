"""J6 integration checks that cross two milestones (pins, README section, tags file, publish, truth of the images)."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_pins_agree_between_pyproject_and_lock():
    pyp = (ROOT / "pyproject.toml").read_text()
    lock = (ROOT / "requirements.lock").read_text()
    for name, lname in (("numpy", "numpy"), ("Pillow", "pillow")):
        v = re.search(rf'"{name}==([0-9.]+)"', pyp).group(1)
        assert re.search(rf"^{lname}=={re.escape(v)} ", lock, re.M), (name, v)
    assert lock.count("--hash=sha256:") >= 5


def test_readme_section_markers_tokens_and_idempotent_insertion(tmp_path):
    import set_repo
    sec = (ROOT / "pages" / "readme-section.md").read_text(encoding="utf-8")
    assert sec.count("<!-- sol-0:start -->") == 1 and sec.count("<!-- sol-0:end -->") == 1
    assert sec.count("{OWNER}") >= 3 and sec.count("{REPO}") >= 3
    assert (set_repo.BEGIN, set_repo.END) == ("<!-- sol-0:start -->", "<!-- sol-0:end -->")
    readme = tmp_path / "README.md"
    readme.write_text("# me\n\nbefore\n", encoding="utf-8")
    out = tmp_path / "out.md"
    assert set_repo.main(["--prod", "--repo", "acme/acme", "--readme", str(readme), "--out", str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert "raw.githubusercontent.com/acme/acme/state/console.gif" in first
    assert "{OWNER}" not in first and "{REPO}" not in first and first.startswith("# me\n\nbefore\n")
    out.write_text(first, encoding="utf-8")
    assert set_repo.main(["--prod", "--repo", "acme/acme", "--readme", str(out), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == first


def test_no_account_name_in_the_product():
    """Text files only (no `.pyc`, which carry the absolute build path); the pattern is built by concatenation so this
    test does not itself carry the account name into the exported tests."""
    pat = re.compile("mali" + "kchopa|cho" + "pa", re.I)
    hits = []
    for d in ("pages", "config", "src"):
        for f in sorted((ROOT / d).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".toml", ".md", ".svg", ".json", ".yml", ".yaml", ".txt", ".sh", ".html"):
                if pat.search(f.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(str(f.relative_to(ROOT)))
    assert hits == []


def test_tags_file_of_two_consecutive_sols_feeds_publish(chain3, tmp_path):
    """F-09: `rover sol --tags` writes `<tag> _out` (+ `<tag> _in` for the pending tags of the previous published state);
    publish.sh (J8a) pushes each tag once, from the real images, to a bare remote."""
    tag_files = sorted(chain3.glob("tags*.txt"))
    assert len(tag_files) == 3
    lines = [ln.split() for f in tag_files for ln in f.read_text().splitlines()]
    assert lines, "sol 1 has real firsts (e.g. first.stage.0 / night drive); no tag at all would hide the contract"
    assert all(len(ln) == 2 and ln[1] in ("_in", "_out") and re.fullmatch(r"m-e\d+-sol\d{4}-[A-Za-z0-9-]+", ln[0]) for ln in lines)
    remote = tmp_path / "remote.git"
    env = {**os.environ, "HOME": str(tmp_path / "home"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "PYTHON": sys.executable, "PUBLISH_SLEEPS": "0 0 0", "SOL0_NO_SIZE": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    (tmp_path / "home").mkdir()
    sh = lambda cwd, *a: subprocess.run(a, cwd=str(cwd), env=env, capture_output=True, text=True)
    assert sh(tmp_path, "git", "init", "--bare", "-q", str(remote)).returncode == 0
    work = tmp_path / "work"
    work.mkdir()
    sh(work, "git", "init", "-q")
    (work / "config").mkdir()
    (work / "config" / "run.toml").write_text((ROOT / "config" / "run.toml").read_text())
    (work / "README.md").write_text("seed\n")
    sh(work, "git", "add", "-A")
    sh(work, "git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "seed")
    sh(work, "git", "remote", "add", "origin", str(remote))
    sh(work, "git", "push", "-q", "origin", "HEAD:main")
    import shutil
    shutil.copytree(chain3 / "s1", work / "_out")
    (shaf := tmp_path / "sha").write_text("")
    r = subprocess.run(["bash", str(ROOT / "tools" / "ci" / "publish.sh"), "_out", str(shaf), str(tag_files[0])], cwd=str(work),
                       env={**env, "PUBLISH_REMOTE": "origin"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    got = sh(tmp_path, "git", "ls-remote", "--tags", str(remote)).stdout
    for tag, _ in (ln.split() for ln in tag_files[0].read_text().splitlines()):
        assert f"refs/tags/{tag}" in got


def test_journal_and_status_of_a_real_sol_cite_only_traced_numbers(chain3):
    """Truth audit (journal): every number written in the entry of sol 1 is a value of the real state / facts."""
    st = json.loads((chain3 / "s1" / "status.json").read_text())["det"]
    assert st["sol"] == 1 and st["attempts"] == 0
    j = (chain3 / "main" / "journal").glob("*.md")
    text = "".join(p.read_text(encoding="utf-8") for p in j)
    assert "### Sol 0001" in text
    # stage 0 entry: "J'ai envoyé N commandes au hasard" : N = couples of the sol = metrics.couples after sol 1 (real data)
    n = int(re.search(r"envoy\S* (\d+) commandes", text).group(1))
    assert n == st["metrics"]["couples"]
    assert "{" not in text and "None" not in text


def _gif_frames(data: bytes):
    import numpy as np
    im = Image.open(io.BytesIO(data))
    pal = im.getpalette()
    palette = [tuple(pal[3 * k:3 * k + 3]) for k in range(len(pal) // 3)]
    frames, durs = [], []
    for i in range(im.n_frames):
        im.seek(i)
        durs.append(int(im.info.get("duration", 100)))
        frames.append(np.asarray(im.convert("RGB")))
    return palette, frames, durs


def test_console_gif_of_real_sols_is_small_and_photosensitive_safe(chain3):
    """EF-87 on the decoded GIFs of real sols (RGB frames decoded, not the encoder's own view)."""
    import numpy as np
    from rover.render.photosens import luminance_table
    from rover.render.photosens import transitions
    for s in ("s1", "s2", "s3"):
        data = (chain3 / s / "console.gif").read_bytes()
        assert len(data) <= 2_000_000
        palette, frames, durs = _gif_frames(data)
        assert len(frames) >= 20
        # frames as exact-RGB images: map every RGB to a private index so that luminance_table can be applied
        flat = np.concatenate([f.reshape(-1, 3) for f in frames])
        uniq, inv = np.unique(flat, axis=0, return_inverse=True)
        lum = luminance_table([tuple(int(c) for c in u) for u in uniq])
        idx = inv.reshape(-1).reshape(len(frames), *frames[0].shape[:2])
        worst, _ = transitions([idx[k] for k in range(len(frames))], durs, lum)
        assert worst <= 3, (s, worst)
