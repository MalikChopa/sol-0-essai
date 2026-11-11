#!/usr/bin/env python3
"""Build a committed state fixture from a real chain folder (J6).

  python tools/make_fixtures.py --src out/j6/a/s46 --dst tests/state/fixtures/v1/stage2_storm
  python tools/make_fixtures.py --src out/j6/a/s75 --dst tests/state/fixtures/v1/stage3_impact --impact-sol 2620

The state is loaded with `state.load` (validated), optionally given the overlay of the REAL event generator
(`world.draw_events`, the comet impact of the chosen sol: a natural impact is 1 sol in 3000, never reached by a 100-sol
chain), then saved without images (only state/ and status.json are kept). Never writes inside --src."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rover import config                       # noqa: E402
from rover.state import load, save             # noqa: E402
from rover.world import draw_events            # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--impact-sol", type=int, default=None)
    a = ap.parse_args(argv)
    params = config.load(ROOT / "config")
    src, dst = Path(a.src).resolve(), Path(a.dst)
    lr = load(src, params)
    s = lr.state
    if a.impact_sol is not None:
        ev = draw_events(int(s["world_seed"]), a.impact_sol, {"storm_left": 0}, (s["rover"]["x"], s["rover"]["y"]), params)
        imp = [o for o in ev.new_overlays if o["kind"] == "impact"]
        if not imp:
            print(f"no impact at sol {a.impact_sol}", file=sys.stderr)
            return 2
        s["overlays"] = list(s["overlays"]) + imp
    status = json.loads((src / "status.json").read_text())
    save(s, lr.explored, dst, {}, status)
    print(f"{dst}: sol {s['sol']} stage {s['stage']['id']} storm_left {s['events']['storm_left']} "
          f"overlays {[o['kind'] for o in s['overlays']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
