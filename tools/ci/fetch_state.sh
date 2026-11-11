#!/usr/bin/env bash
# Usage: fetch_state.sh DIR SHA_FILE
# Fetch the `state` branch (depth 1) into DIR and write its SHA to SHA_FILE.
# Branch absent: DIR empty, SHA_FILE empty. Network error: failure (never mistaken for "absent").
set -euo pipefail
dir="${1:?dir}"
shafile="${2:?sha file}"
remote="${SOL0_REMOTE:-origin}"
rm -rf "$dir"
mkdir -p "$dir" "$(dirname "$shafile")"
rc=0
git ls-remote --exit-code --heads "$remote" state >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 0 ]; then
  git fetch --depth 1 "$remote" state
  git rev-parse FETCH_HEAD > "$shafile"
  git archive FETCH_HEAD | tar -x -C "$dir"
elif [ "$rc" -eq 2 ]; then
  : > "$shafile"
else
  echo "::error::cannot reach remote (ls-remote exit $rc)"
  exit 3
fi
echo "state sha: [$(cat "$shafile")]"
