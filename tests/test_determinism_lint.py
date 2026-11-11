"""AST lint of the critical path (ARCH 6): whitelist of exact operations on all of src/rover except cli.py.

Per-package additions: tests/lint_allow/<package>.txt (one `np.xxx  # reason` per line, exact operations only).
Heuristic limit (documented): `int(...)` is accepted unless its argument visibly contains a float operation.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "rover"
ALLOW_DIR = Path(__file__).resolve().parent / "lint_allow"
EXEMPT = {"core/exact.py", "core/dmath.py", "core/rng.py"}      # declared exceptions: they implement the primitives

NP_OK = {
    "minimum", "maximum", "sqrt", "floor", "ceil", "bincount", "argmin", "argmax", "where", "clip", "take", "concatenate",
    "stack", "zeros", "ones", "full", "empty", "arange", "array", "asarray", "frombuffer", "packbits", "unpackbits",
    "reshape", "isfinite", "isnan", "argsort", "abs",
    # closed list of exact structure operations (ARCH 6)
    "sign", "logical_and", "logical_or", "logical_not", "logical_xor", "flatnonzero", "nonzero", "argwhere", "sort",
    "lexsort", "unique", "searchsorted", "repeat", "roll", "tile", "broadcast_to", "zeros_like", "ones_like", "full_like",
    "empty_like", "copy", "ravel", "transpose", "flip", "expand_dims", "squeeze", "pad", "indices", "meshgrid", "diff",
    "square", "add", "subtract", "multiply", "divide", "negative", "floor_divide", "remainder", "rint", "trunc", "max",
    "min", "any", "all", "count_nonzero", "iinfo", "finfo", "ndarray",
    "uint8", "uint16", "uint32", "uint64", "int8", "int16", "int32", "int64", "float32", "float64", "bool_",
}
NP_REFUSED = {"linspace", "cumsum", "sin", "cos", "tan", "exp", "log", "log1p", "log2", "log10", "power", "tanh", "arctan",
              "arctan2", "hypot", "cbrt", "expm1", "sinh", "cosh", "dot", "matmul", "einsum", "inner", "tensordot", "vdot",
              "convolve", "polyval", "average", "median", "percentile", "cov", "corrcoef", "nansum", "cumprod", "linalg",
              "fft", "random", "sum", "mean", "std", "var", "prod"}
NP_DTYPES = {"uint8", "uint16", "uint32", "uint64", "int8", "int16", "int32", "int64", "float32", "float64", "bool_"}
ASTYPE_OK = {"np.float32", "np.float64", "np.bool_", "bool", "float"}
MATH_OK = {"sqrt", "floor", "ceil", "isfinite", "fsum", "pi"}
BAD_METHODS = {"dot", "sum", "mean", "std", "var", "prod", "cumsum", "reduce", "reduceat"}
BAD_CALLS = {"sum", "mean", "std", "var", "prod", "cumsum", "hash"}
STRUCT_ONLY_UFUNC = {"add", "subtract", "multiply", "divide", "negative", "floor_divide", "remainder", "minimum", "maximum"}
FLOAT_OPS = {"floor", "ceil", "sqrt", "rint", "trunc"}


def _allowed_extra(package: str) -> set[str]:
    f = ALLOW_DIR / f"{package}.txt"
    out = set()
    if f.is_file():
        for line in f.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                assert line.startswith("np."), f"{f}: only np.xxx names"
                name = line[3:]
                assert name not in NP_REFUSED, f"{f}: {name} is refused"
                out.add(name)
    return out


def _package(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "toplevel"


def _chain(node: ast.AST):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return list(reversed(parts))
    return None


def _dotted(node: ast.AST) -> str:
    c = _chain(node)
    return ".".join(c) if c else ""


def lint_source(src: str, extra: set[str] = frozenset()) -> list[str]:
    ok = NP_OK | set(extra)
    tree = ast.parse(src)
    errs: list[str] = []

    def contains_float_op(n: ast.AST) -> bool:
        for x in ast.walk(n):
            if isinstance(x, ast.BinOp) and isinstance(x.op, ast.Div):
                return True
            if isinstance(x, ast.Constant) and isinstance(x.value, float):
                return True
            if isinstance(x, ast.Call):
                ch = _chain(x.func)
                if ch and ch[0] in ("np", "math") and ch[-1] in FLOAT_OPS:
                    return True
        return False

    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "random":
                    errs.append(f"{line}: import random")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "random":
                errs.append(f"{line}: from random")
            if (node.module or "").split(".")[0] == "numpy":
                errs.append(f"{line}: from numpy import (use np.xxx)")
        elif isinstance(node, ast.Attribute):
            ch = _chain(node)
            if ch and ch[0] in ("np", "numpy") and len(ch) >= 2 and not (isinstance(getattr(node, "_parent", None), ast.Attribute)):
                pass
            if node.attr in BAD_METHODS and not (ch and ch[0] in ("np", "numpy")):
                errs.append(f"{line}: method .{node.attr}")
        elif isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.MatMult):
                errs.append(f"{line}: @ operator")
            if isinstance(node.op, ast.Pow) and not (isinstance(node.right, ast.Constant) and node.right.value == 2):
                errs.append(f"{line}: ** with a non-2 exponent")
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.op, ast.MatMult):
                errs.append(f"{line}: @= operator")
            if isinstance(node.op, ast.Pow):
                errs.append(f"{line}: **=")
        elif isinstance(node, ast.For):
            it = node.iter
            if isinstance(it, (ast.Set, ast.SetComp)) or (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                                                         and it.func.id in ("set", "frozenset")):
                errs.append(f"{line}: iteration over a set")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in BAD_CALLS:
                    errs.append(f"{line}: call {f.id}()")
                if f.id == "round" and len(node.args) == 1:
                    errs.append(f"{line}: round() converts float to int (use core.exact.to_int)")
                if f.id == "int" and node.args and contains_float_op(node.args[0]):
                    errs.append(f"{line}: int() of a float expression (use core.exact.to_int)")
            if isinstance(f, ast.Attribute):
                if f.attr == "astype":
                    a0 = node.args[0] if node.args else None
                    if a0 is None or _dotted(a0) not in ASTYPE_OK:
                        errs.append(f"{line}: astype to a type outside float32/float64/bool")
                if f.attr in ("argsort", "sort"):
                    kinds = [k for k in node.keywords if k.arg == "kind"]
                    if not (kinds and isinstance(kinds[0].value, ast.Constant) and kinds[0].value.value == "stable"):
                        errs.append(f"{line}: {f.attr} without kind='stable'")
                ch = _chain(f)
                if ch and ch[0] in ("np", "numpy") and len(ch) == 2 and ch[1] == "arange":
                    # J6: np.arange with a float argument gives other values on Mac arm64 and on x86-64 (measured by J8a on the real runner)
                    vals = list(node.args) + [k.value for k in node.keywords if k.arg != "dtype"]
                    if any(contains_float_op(v) for v in vals):
                        errs.append(f"{line}: np.arange with a float argument (use integers, then divide exactly)")
                if ch and ch[0] in ("np", "numpy") and len(ch) == 2 and ch[1] in NP_DTYPES:
                    if not all(isinstance(a, ast.Constant) for a in node.args):
                        errs.append(f"{line}: np.{ch[1]}(...) conversion of a non-constant (use to_int / float)")
    # names: every np.xxx / math.xxx chain (outermost attribute chains only)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            ch = _chain(node)
            if not ch:
                continue
            if ch[0] in ("np", "numpy") and len(ch) >= 2:
                name = ch[1]
                if name not in ok:
                    errs.append(f"{node.lineno}: np.{name} not in the whitelist")
                elif len(ch) > 2 and ch[-1] in ("reduce", "reduceat", "at", "outer"):
                    errs.append(f"{node.lineno}: np.{name}.{ch[-1]}")
                elif len(ch) > 2 and ch[-1] == "accumulate" and name not in ("minimum", "maximum"):
                    errs.append(f"{node.lineno}: np.{name}.accumulate")
            elif ch[0] == "math" and len(ch) == 2 and ch[1] not in MATH_OK:
                errs.append(f"{node.lineno}: math.{ch[1]} not in the whitelist")
    return sorted(set(errs), key=lambda e: int(e.split(":")[0]))


def _files():
    return [p for p in sorted(SRC.rglob("*.py")) if p.name != "cli.py" or p.parent != SRC]


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(SRC)))
def test_critical_path_is_exact(path):
    rel = path.relative_to(SRC).as_posix()
    src = path.read_text(encoding="utf-8")
    if rel in EXEMPT:
        errs = [e for e in lint_source(src, extra={n for n in NP_REFUSED}) if "random" in e or "set" in e or "hash" in e or "arange" in e]
    else:
        errs = lint_source(src, _allowed_extra(_package(path)))
    assert not errs, f"{rel}:\n  " + "\n  ".join(errs)


def test_lint_catches_forbidden_constructs():
    bad = "import numpy as np\nx = np.sum(a)\ny = a @ b\nz = a ** 3\nw = a.mean()\nv = np.sin(a)\nfor i in set(a): pass\nq = a.astype(np.int64)\n"
    errs = lint_source(bad)
    assert len(errs) >= 6, errs


def test_lint_accepts_exact_constructs():
    good = "import numpy as np\nimport math\nx = np.minimum.accumulate(a, axis=0)\ny = np.sqrt(a * a) / 2.0\nz = a.astype(np.float32)\nw = math.floor(2.5)\n"
    assert lint_source(good) == []


def test_lint_allow_files_exist_for_every_package():
    for p in ("core", "world", "agent", "brain", "stages", "state", "sim", "render", "narrative", "pipeline", "toplevel"):
        assert (ALLOW_DIR / f"{p}.txt").is_file()


def test_lint_refuses_arange_with_float_argument():
    """J6 (cross-machine bug measured by J8a): np.arange(-30.0, 30.0, 0.37) differs between Mac arm64 and x86-64."""
    for bad in ("import numpy as np\nx = np.arange(-30.0, 30.0, 0.37)\n",
                "import numpy as np\nx = np.arange(0, 1, step=0.1)\n",
                "import numpy as np\nx = np.arange(n / 2)\n",
                "import numpy as np\nx = np.arange(24.0)\n"):
        assert any("arange" in e for e in lint_source(bad)), bad
    for good in ("import numpy as np\nx = np.arange(-3000, 3000, 37) / 100.0\n",
                 "import numpy as np\nx = np.arange(24, dtype=np.float64)\n",
                 "import numpy as np\nx = np.arange(n)\n"):
        assert not any("arange" in e for e in lint_source(good)), good
