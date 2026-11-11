"""export_public.py (whitelist, private patterns) and compare_refs.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import compare_refs  # noqa: E402
import export_public  # noqa: E402

HOME_MARKER = "/Us" + "ers/"      # built by concatenation: this file never matches itself


def test_whitelist_excludes_private_and_internal_trees():
    files = export_public.list_files(ROOT)
    assert files
    for f in files:
        assert not f.startswith(("docs/briefs", "docs/audits", "docs/research", "maquette", "out/", ".claude", "tools/sonde-essai"))
        assert f != "CLAUDE.md" and not f.endswith(".pyc")
    docs = [f for f in files if f.startswith("docs/")]
    assert set(docs) <= {"docs/OPERATIONS.md", "docs/MAINTENANCE.md"}
    for must in (".github/workflows/sol.yml", "requirements.lock", "tools/ci/publish.sh", "pyproject.toml"):
        assert must in files


def test_exported_files_have_no_home_path_nor_private_pattern():
    assert export_public.scan(export_public.list_files(ROOT), ROOT) == []


def test_scan_detects_marker_and_private_pattern(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = '" + HOME_MARKER + "me'\n")
    (tmp_path / "src" / "b.py").write_text("name = 'zorglub'\n")
    (tmp_path / "src" / "c.py").write_text("ok = 1\n")
    (tmp_path / ".private_patterns").write_text("# comment\nzorg" + "lub\n")
    files = export_public.list_files(tmp_path)
    assert export_public.scan(files, tmp_path) == ["src/a.py", "src/b.py"]


def test_export_builds_one_commit_without_history(tmp_path):
    out = tmp_path / "exp"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "export_public.py"), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (out / "src" / "rover" / "cli.py").is_file()
    assert not (out / "CLAUDE.md").exists() and not (out / "docs" / "HANDOFF.md").exists()
    n = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(out), capture_output=True, text=True).stdout.strip()
    assert n == "1"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=str(out), capture_output=True, text=True).stdout == ""


def test_export_refuses_when_a_marker_is_present(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("p = '" + HOME_MARKER + "x'\n")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "export_public.py"), "--root", str(root), "--out", str(tmp_path / "o")], capture_output=True, text=True)
    assert r.returncode == 1 and "src/a.py" in r.stderr
    assert not (tmp_path / "o").exists()


def test_compare_refs(tmp_path, capsys):
    a = {"x": "sha256:1", "y": "sha256:2"}
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(a))
    pb.write_text(json.dumps(a))
    assert compare_refs.main([str(pa), str(pb)]) == 0
    pb.write_text(json.dumps({"x": "sha256:1", "y": "sha256:9"}))
    assert compare_refs.main([str(pa), str(pb)]) == 1
    assert compare_refs.main([str(pa), str(pb), "--only", "x"]) == 0
    pb.write_text(json.dumps({"x": "sha256:1"}))
    assert compare_refs.main([str(pa), str(pb)]) == 1
    assert compare_refs.main([str(pa), str(tmp_path / "missing.json")]) == 2


def test_extract_from_log_with_gh_prefixes():
    log = ("sol\tother step\t2026-11-11T07:00:00.123Z hello\n"
           "sol\trefs\t2026-11-11T07:00:01.000Z REFS-BEGIN\n"
           "sol\trefs\t2026-11-11T07:00:01.001Z {\n"
           "sol\trefs\t2026-11-11T07:00:01.002Z  \"k\": \"sha256:1\"\n"
           "sol\trefs\t2026-11-11T07:00:01.003Z }\n"
           "sol\trefs\t2026-11-11T07:00:01.004Z REFS-END\n")
    assert compare_refs.extract_from_log(log) == {"k": "sha256:1"}


def test_trailer_is_whitelisted_when_present_and_tolerated_when_absent(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    assert export_public.list_files(tmp_path) == ["src/a.py"]          # absence tolerated
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "trailer.gif").write_bytes(b"GIF89a")
    (tmp_path / "assets" / "other.png").write_bytes(b"x")
    (tmp_path / "tools" / "trailer").mkdir(parents=True)
    (tmp_path / "tools" / "trailer" / "make.py").write_text("y = 2\n")
    (tmp_path / "tools" / "private").mkdir()
    (tmp_path / "tools" / "private" / "z.py").write_text("z = 3\n")
    assert export_public.list_files(tmp_path) == ["assets/trailer.gif", "src/a.py", "tools/trailer/make.py"]
