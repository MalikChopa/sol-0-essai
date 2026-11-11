"""Small helpers for publish.sh (kept in Python so JSON and TOML are parsed by a real parser).

Usage:
  publish_lib.py sol OUT_DIR                 -> prints the sol number (status.json det.sol)
  publish_lib.py verdict OUT_DIR CFG MAIN_OK -> exit 1 (red) if passive_streak >= passive_red_after,
                                                or MAIN_OK = 0 and main_lag >= main_lag_red - 1; else exit 0
  publish_lib.py milestone TAG OUT_DIR       -> prints the canonical milestone.json for TAG
  publish_lib.py sizelimit CFG               -> prints repo_size_alert_kb
"""
import json
import re
import sys
import tomllib
from pathlib import Path


def _det(out_dir: str) -> dict:
    return json.loads((Path(out_dir) / "status.json").read_text(encoding="utf-8"))["det"]


def _cfg(path: str) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    cmd = argv[1]
    if cmd == "sol":
        print(int(_det(argv[2])["sol"]))
        return 0
    if cmd == "verdict":
        det, cfg, main_ok = _det(argv[2]), _cfg(argv[3]), argv[4] == "1"
        if int(det.get("passive_streak", 0)) >= int(cfg.get("passive_red_after", 3)):
            print("::error::passive_streak >= %s" % cfg.get("passive_red_after", 3))
            return 1
        if not main_ok and int(det.get("main_lag", 0)) >= int(cfg.get("main_lag_red", 3)) - 1:
            print("::error::main refused the journal commit and main_lag >= %d" % (int(cfg.get("main_lag_red", 3)) - 1))
            return 1
        return 0
    if cmd == "milestone":
        tag, out_dir = argv[2], argv[3]
        m = re.fullmatch(r"m-e([0-9]+)-sol([0-9]+)-(.+)", tag)
        det = _det(out_dir)
        epoch, sol, fid = (int(m.group(1)), int(m.group(2)), m.group(3)) if m else (int(det.get("epoch", 0)), int(det["sol"]), tag)
        obj = {"tag": tag, "epoch": epoch, "sol": sol, "first_id": fid, "utc": det.get("last_success_utc", "")}
        print(json.dumps(obj, sort_keys=True, separators=(",", ":")))
        return 0
    if cmd == "sizelimit":
        print(int(_cfg(argv[2]).get("repo_size_alert_kb", 1048576)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
