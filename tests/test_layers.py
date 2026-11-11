"""Import layers (ARCH 3): the exhaustive list of permitted imports per package, read from tests/layers/<package>.toml."""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "rover"
LAYERS = Path(__file__).resolve().parent / "layers"
TOP_ONLY = {"config.py", "version.py"}                       # import nothing from the project (ARCH 3)
CLI_RULE = {"pipeline", "state", "config", "version"}


def _package_of(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "toplevel"


def _rule(path: Path) -> tuple[set, set]:
    if path.name in TOP_ONLY and path.parent == SRC:
        return set(), set()
    if path.name == "cli.py" and path.parent == SRC:
        return CLI_RULE, {"numpy", "PIL"}
    d = tomllib.loads((LAYERS / f"{_package_of(path)}.toml").read_text())
    return set(d["project"]), set(d["third_party"])


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split(".")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue                                    # relative: same package
            mod = (node.module or "").split(".")
            if mod == ["rover"]:
                for a in node.names:
                    yield ["rover", a.name]
            else:
                yield mod


def _files():
    return sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(SRC)))
def test_imports_follow_layers(path):
    allowed_proj, allowed_3p = _rule(path)
    own = _package_of(path)
    bad = []
    for parts in _imports(ast.parse(path.read_text(encoding="utf-8"))):
        top = parts[0]
        if top == "rover":
            target = parts[1] if len(parts) > 1 else ""
            if target and target != own and target not in allowed_proj:
                bad.append(".".join(parts))
        elif top in sys.stdlib_module_names or top == "__future__":
            continue
        elif top not in allowed_3p:
            bad.append(".".join(parts))
    assert not bad, f"{path.relative_to(SRC)}: forbidden imports {bad}"


def test_every_package_has_a_layer_file():
    pkgs = {_package_of(p) for p in _files()}
    for p in pkgs:
        assert (LAYERS / f"{p}.toml").is_file(), p
    assert len(list(LAYERS.glob("*.toml"))) == 11
