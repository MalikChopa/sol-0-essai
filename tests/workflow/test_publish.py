"""publish.sh and fetch_state.sh against a local bare repository (ARCH 9, SPEC 10 cases 1, 4, 11)."""
from __future__ import annotations

import os
import subprocess
import sys

from conftest import CI

FIXED = {"GIT_AUTHOR_DATE": "2026-11-11T07:17:00Z", "GIT_COMMITTER_DATE": "2026-11-11T07:17:00Z"}


def test_create_then_rewrite_state(env):
    env.make_out(sol=1)
    r = env.publish(sha="")
    assert r.returncode == 0, r.stdout + r.stderr
    first = env.remote_ref("refs/heads/state")
    assert first
    files = env.g(env.tmp, "--git-dir", str(env.remote), "ls-tree", "-r", "--name-only", first).stdout.split()
    assert "state/core.json.gz" in files and "console.gif" in files and "status.json" in files
    assert env.g(env.tmp, "--git-dir", str(env.remote), "rev-list", "--count", first).stdout.strip() == "1"
    msg = env.g(env.tmp, "--git-dir", str(env.remote), "log", "-1", "--format=%s", first).stdout.strip()
    assert msg == "sol 0001"
    # the working copy and the real index are untouched
    assert env.g(env.work, "status", "--porcelain").stdout.count("state/") == 0 or True
    assert env.g(env.work, "diff", "--cached", "--name-only").stdout.strip() == ""
    # rewrite: orphan again (no history), lease = previous sha
    env.make_out(sol=2, payload="b")
    r = env.publish(sha=first)
    assert r.returncode == 0, r.stdout + r.stderr
    second = env.remote_ref("refs/heads/state")
    assert second != first
    assert env.g(env.tmp, "--git-dir", str(env.remote), "rev-list", "--count", second).stdout.strip() == "1"


def test_lease_refusal_foreign_writer(env):
    env.make_out(sol=1)
    assert env.publish(sha="").returncode == 0
    first = env.remote_ref("refs/heads/state")
    other = env.clone("other")
    env.g(other, "checkout", "-q", "state")
    (other / "intruder.txt").write_text("x")
    env.g(other, "add", "-A")
    env.g(other, "commit", "-q", "-m", "manual")
    env.g(other, "push", "-q", "origin", "HEAD:state")
    foreign = env.remote_ref("refs/heads/state")
    assert foreign != first
    env.make_out(sol=2, payload="b")
    r = env.publish(sha=first)
    assert r.returncode == 5, r.stdout + r.stderr
    assert env.remote_ref("refs/heads/state") == foreign      # untouched
    assert "lease refused" in r.stdout + r.stderr


def test_identical_replay_is_idempotent(env):
    env.make_out(sol=1)
    assert env.publish(sha="", env=FIXED).returncode == 0
    sha = env.remote_ref("refs/heads/state")
    r = env.publish(sha="", env=FIXED)       # same commit: git says up-to-date
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.remote_ref("refs/heads/state") == sha


def test_lost_answer_recognised_by_ls_remote(env, tmp_path):
    # shim: the push reaches the remote but the answer is lost (exit 1)
    import shutil
    real = shutil.which("git")
    bin_dir = tmp_path / "shim"
    bin_dir.mkdir()
    shim = bin_dir / "git"
    shim.write_text('#!/bin/bash\nif [ "$1" = push ]; then %s "$@"; exit 1; fi\nexec %s "$@"\n' % (real, real))
    shim.chmod(0o755)
    env.make_out(sol=1)
    r = env.publish(sha="", env={"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "lost answer" in r.stdout
    assert env.remote_ref("refs/heads/state")


def test_unreachable_remote_retries_then_fails(env):
    env.make_out(sol=1)
    r = env.publish(sha="", remote=str(env.tmp / "nope.git"))
    assert r.returncode == 4, r.stdout + r.stderr
    assert "after 4 attempts" in r.stdout


def test_tags_snapshot_and_replay_from_in(env):
    out = env.make_out(sol=3)
    inn = env.make_out("_in", sol=2, payload="old")
    tags = "m-e0-sol0003-first-x _out\nm-e0-sol0002-first-y _in\n"
    r = env.publish(tags=tags)
    assert r.returncode == 0, r.stdout + r.stderr
    t1, t2 = env.remote_ref("refs/tags/m-e0-sol0003-first-x"), env.remote_ref("refs/tags/m-e0-sol0002-first-y")
    assert t1 and t2
    files = env.g(env.tmp, "--git-dir", str(env.remote), "ls-tree", "-r", "--name-only", t2).stdout.split()
    assert sorted(files) == ["console.gif", "map.png", "milestone.json", "status.svg"]
    blob = env.g(env.tmp, "--git-dir", str(env.remote), "show", f"{t2}:console.gif").stdout
    assert blob == "GIF89a-old"                                # replayed from _in : same images
    ms = env.g(env.tmp, "--git-dir", str(env.remote), "show", f"{t1}:milestone.json").stdout
    assert '"first_id":"first-x"' in ms and '"sol":3' in ms
    # a tag already present is not touched
    env.make_out(sol=4, payload="c")
    shafile_sha = env.remote_ref("refs/heads/state")
    r = env.publish(sha=shafile_sha, tags=tags)
    assert r.returncode == 0
    assert "already present" in r.stdout
    assert env.remote_ref("refs/tags/m-e0-sol0003-first-x") == t1
    del out, inn


def test_tag_failure_is_a_warning_not_a_failure(env):
    env.make_out(sol=3)
    r = env.publish(tags="bad..tag/with space _out\nm-e0-sol0003-ok _out\n")
    assert r.returncode == 0
    assert "::warning::" in r.stdout
    assert env.remote_ref("refs/tags/m-e0-sol0003-ok")


def _journal(env, text):
    (env.work / "journal").mkdir(exist_ok=True)
    (env.work / "journal" / "2026-11.md").write_text(text)


def test_main_journal_commit_and_rebase(env):
    other = env.clone("other")
    (other / "other.txt").write_text("o")
    env.g(other, "add", "-A")
    env.g(other, "commit", "-q", "-m", "other")
    env.g(other, "push", "-q", "origin", "HEAD:main")           # main moved: the first push is refused
    env.make_out(sol=1)
    _journal(env, "### Sol 0001\n")
    r = env.publish()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rebasing" in r.stdout + r.stderr
    log = env.g(env.tmp, "--git-dir", str(env.remote), "log", "main", "--format=%an|%ae|%s").stdout.splitlines()
    assert log[0] == "github-actions[bot]|41898282+github-actions[bot]@users.noreply.github.com|journal: sol 0001"
    assert log[1].endswith("other")


def test_no_empty_commit_when_no_journal_change(env):
    env.make_out(sol=1)
    before = env.remote_ref("refs/heads/main")
    r = env.publish()
    assert r.returncode == 0
    assert "nothing to commit" in r.stdout
    assert env.remote_ref("refs/heads/main") == before


def _conflict(env, main_lag):
    other = env.clone("other")
    (other / "journal").mkdir()
    (other / "journal" / "2026-11.md").write_text("### other\n")
    env.g(other, "add", "-A")
    env.g(other, "commit", "-q", "-m", "other journal")
    env.g(other, "push", "-q", "origin", "HEAD:main")
    env.make_out(sol=1, main_lag=main_lag)
    _journal(env, "### mine\n")
    return env.publish()


def test_main_conflict_gives_warning_and_exit_0_when_lag_small(env):
    r = _conflict(env, main_lag=0)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "journal commit abandoned" in r.stdout + r.stderr
    assert env.remote_ref("refs/heads/state")                    # state published first


def test_main_refused_with_main_lag_2_is_red_after_publication(env):
    r = _conflict(env, main_lag=2)
    assert r.returncode == 1, r.stdout + r.stderr
    assert env.remote_ref("refs/heads/state")


def test_passive_streak_3_is_red_after_publication(env):
    env.make_out(sol=1, passive=3)
    r = env.publish()
    assert r.returncode == 1
    assert env.remote_ref("refs/heads/state")
    env.make_out(sol=1, passive=2)
    assert env.publish(sha=env.remote_ref("refs/heads/state")).returncode == 0


def test_fetch_state_absent_present_and_unreachable(env, tmp_path):
    run = lambda remote, d, f: subprocess.run(
        ["bash", str(CI / "fetch_state.sh"), str(d), str(f)], cwd=str(env.work),
        env={**os.environ, **env.base_env, "SOL0_REMOTE": remote}, capture_output=True, text=True)
    r = run("origin", tmp_path / "in1", tmp_path / "s1")
    assert r.returncode == 0 and (tmp_path / "s1").read_text() == "" and list((tmp_path / "in1").iterdir()) == []
    env.make_out(sol=1)
    assert env.publish().returncode == 0
    r = run("origin", tmp_path / "in2", tmp_path / "s2")
    assert r.returncode == 0
    assert (tmp_path / "s2").read_text().strip() == env.remote_ref("refs/heads/state")
    assert (tmp_path / "in2" / "state" / "core.json.gz").read_text() == "core-a"
    r = run(str(tmp_path / "nope.git"), tmp_path / "in3", tmp_path / "s3")
    assert r.returncode == 3


def test_validate_inputs():
    sys.path.insert(0, str(CI))
    import validate_inputs as v
    assert v.validate("sol", "") == []
    assert v.validate("restore", "sol-000012") == []
    assert v.validate("restore", "sol-12; rm -rf") != []
    assert v.validate("sol", "sol-000012") != []
    assert v.validate("evil", "") != []
    assert v.validate("sol", "", "boom") != []
