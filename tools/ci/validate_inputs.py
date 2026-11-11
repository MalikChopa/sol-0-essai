"""Validate workflow inputs against closed lists (ARCH 9). Exit 2 on refusal."""
import re
import sys

MODES = ("sol", "check", "refs", "restore")
FAULTS = ("none", "corrupt", "nan")


def validate(mode: str, checkpoint: str, fault: str = "none") -> list[str]:
    errs = []
    if mode not in MODES:
        errs.append(f"mode not allowed: {mode!r}")
    if fault not in FAULTS:
        errs.append(f"fault not allowed: {fault!r}")
    if mode == "restore":
        if not re.fullmatch(r"sol-[0-9]{6}", checkpoint):
            errs.append(f"checkpoint must match ^sol-[0-9]{{6}}$: {checkpoint!r}")
    elif checkpoint:
        errs.append("checkpoint is only for mode restore")
    return errs


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "sol"
    checkpoint = argv[2] if len(argv) > 2 else ""
    fault = argv[3] if len(argv) > 3 else "none"
    errs = validate(mode, checkpoint, fault)
    for e in errs:
        print("::error::" + e.replace("\n", " ")[:200])
    return 2 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
