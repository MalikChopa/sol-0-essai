"""Common test configuration: hypothesis deterministic, project root on the path, params fixture."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

settings.register_profile("sol0", derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("sol0")


@pytest.fixture(scope="session")
def params():
    from rover import config
    return config.load(ROOT / "config")


NOW = ("2026-11-11T07:17:00Z", "2026-11-11T13:17:00Z", "2026-11-11T19:17:00Z", "2026-11-12T01:17:00Z", "2026-11-12T07:17:00Z",
       "2026-11-12T13:17:00Z")


def run_cli(*args) -> int:
    from rover.cli import main
    return main([str(a) for a in args])


def play(root: Path, n: int, start: int = 0, prev: Path | None = None) -> Path:
    """Chain `n` sols with the CLI from `prev` (default: an empty folder) into root/s<k>; returns the last folder."""
    cur = prev if prev is not None else root / "empty"
    for i in range(start, start + n):
        nxt = root / f"s{i + 1}"
        assert run_cli("sol", "--in", cur, "--out", nxt, "--main", root / "main", "--now", NOW[i],
                       "--tags", root / f"tags{i + 1}.txt") == 0
        cur = nxt
    return cur


@pytest.fixture(scope="session")
def chain3(tmp_path_factory):
    """Three real sols (read only: tests copy what they modify)."""
    root = tmp_path_factory.mktemp("chain3")
    play(root, 3)
    return root


# --- fixtures and perf hook moved here from tests/agent/conftest.py (J6: two conftest.py without __init__.py
# --- share the module name "conftest" in pytest's prepend import mode, which broke `from conftest import ...`).
AGENT_SEED = 31337


@pytest.fixture(scope="session")
def world(params):
    from rover.world import World
    return World(AGENT_SEED, params)


@pytest.fixture(scope="session")
def win(world):
    return world.window(-3, -3, 3, 3)


def pytest_collection_modifyitems(config, items):
    """Timing tests of tests/agent run only on request (`-m perf`): a loaded machine must not turn a plain `pytest` red."""
    if "perf" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="perf test: run with -m perf")
    for it in items:
        if "perf" in it.keywords and "tests/agent/" in str(it.fspath).replace("\\", "/"):
            it.add_marker(skip)


# --- tests/workflow/conftest.py (J8a), tests/render/conftest.py (J3) and tests/narrative/conftest.py (J4), merged here by J6
# --- (same reason: one `conftest` module name only).
import json      # noqa: E402
import os        # noqa: E402
import shutil    # noqa: E402
import subprocess  # noqa: E402

TOOLS_RENDER = ROOT / "tools" / "render"
if str(TOOLS_RENDER) not in sys.path:                       # fictitious traces of the render tests: tools/render/fake_trace.py
    sys.path.insert(0, str(TOOLS_RENDER))


@pytest.fixture
def state():
    from rover.narrative.refs import sample_state
    return sample_state()


CI = ROOT / "tools" / "ci"


def git(cwd, *args, env=None, check=True):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(["git", *args], cwd=str(cwd), env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed: {r.stderr}")
    return r


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.base_env = {
            "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(self.home / "gitconfig"),
            "GIT_TERMINAL_PROMPT": "0", "PYTHON": sys.executable, "PUBLISH_SLEEPS": "0 0 0", "SOL0_NO_SIZE": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        (self.home / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n")
        self.remote = tmp / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True, env={**os.environ, **self.base_env})
        self.work = tmp / "work"
        self.work.mkdir()
        self.g(self.work, "init", "-q")
        (self.work / "config").mkdir()
        shutil.copy(ROOT / "config" / "run.toml", self.work / "config" / "run.toml")
        (self.work / "README.md").write_text("seed\n")
        self.g(self.work, "add", "-A")
        self.g(self.work, "commit", "-q", "-m", "seed")
        self.g(self.work, "remote", "add", "origin", str(self.remote))
        self.g(self.work, "push", "-q", "origin", "HEAD:main")

    def g(self, cwd, *args, check=True, env=None):
        return git(cwd, *args, env={**self.base_env, **(env or {})}, check=check)

    def clone(self, name: str) -> Path:
        d = self.tmp / name
        self.g(self.tmp, "clone", "-q", str(self.remote), str(d))
        return d

    def make_out(self, name="_out", sol=1, passive=0, main_lag=0, payload="a") -> Path:
        d = self.work / name
        (d / "state").mkdir(parents=True, exist_ok=True)
        (d / "state" / "core.json.gz").write_text("core-" + payload)
        (d / "console.gif").write_bytes(b"GIF89a-" + payload.encode())
        (d / "status.svg").write_text("<svg/>")
        (d / "map.png").write_bytes(b"png-" + payload.encode())
        det = {"sol": sol, "epoch": 0, "last_success_utc": "2026-11-11T07:17:00Z", "passive_streak": passive, "main_lag": main_lag}
        (d / "status.json").write_text(json.dumps({"det": det, "run": {}}))
        return d

    def publish(self, out="_out", sha="", tags=None, remote=None, env=None):
        shafile = self.tmp / "state_sha"
        shafile.write_text(sha)
        args = ["bash", str(CI / "publish.sh"), out, str(shafile)]
        if tags is not None:
            tf = self.tmp / "tags.txt"
            tf.write_text(tags)
            args.append(str(tf))
        e = {**os.environ, **self.base_env, **(env or {})}
        if remote:
            e["PUBLISH_REMOTE"] = remote
        return subprocess.run(args, cwd=str(self.work), env=e, capture_output=True, text=True)

    def remote_ref(self, ref):
        o = self.g(self.tmp, "ls-remote", str(self.remote), ref).stdout.strip()
        return o.split()[0] if o else ""


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)
