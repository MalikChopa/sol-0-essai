#!/usr/bin/env bash
# Usage: tools/chain.sh N DIR  -- chains N sols (rover sol then rover check) from an empty state into DIR/s1 ... DIR/sN,
# prints the fingerprints of each sol (MANIFEST sha256, console.gif sha256). Run from the project root.
# Env: PY (python, default .venv/bin/python), START (first --now, default 2026-11-11T07:17:00Z).
set -euo pipefail
N="${1:?usage: tools/chain.sh N DIR}"
DIR="${2:?usage: tools/chain.sh N DIR}"
case "$N" in ''|*[!0-9]*) echo "N must be a positive integer" >&2; exit 2;; esac
[ "$N" -ge 1 ] || { echo "N must be >= 1" >&2; exit 2; }
if [ -z "${PY:-}" ]; then if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi; fi
START="${START:-2026-11-11T07:17:00Z}"
export PYTHONPATH="${PYTHONPATH:-src}"
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
mkdir -p "$DIR/main" "$DIR/s0"
prev="$DIR/s0"
# the 4 daily sols: 01:17 07:17 13:17 19:17 UTC, advancing 6 h per sol from START
t0=$("$PY" -c 'import sys,datetime as d; print(int(d.datetime.strptime(sys.argv[1],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=d.timezone.utc).timestamp()))' "$START")
for i in $(seq 1 "$N"); do
  now=$("$PY" -c 'import sys,datetime as d; print(d.datetime.fromtimestamp(int(sys.argv[1]),d.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$((t0 + (i - 1) * 21600))")
  out="$DIR/s$i"
  "$PY" -m rover sol --in "$prev" --out "$out" --main "$DIR/main" --now "$now" --tags "$DIR/tags_$i.txt" > /dev/null
  "$PY" -m rover check --dir "$out" --prev "$prev"
  echo "sol $i manifest=$(sha "$out/state/MANIFEST.json") gif=$(sha "$out/console.gif")"
  prev="$out"
done
