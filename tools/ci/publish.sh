#!/usr/bin/env bash
# Usage: publish.sh OUT_DIR SHA_FILE TAGS_FILE   (run from the repository root, i.e. the checkout of main)
# Order (ARCH 9): state (source of truth), tags, then main. Never an empty commit.
# Env: PUBLISH_REMOTE (default origin), PYTHON (default python), PUBLISH_SLEEPS (default "5 15 30"),
#      GITHUB_REPOSITORY, GH_TOKEN (size check only, optional), SOL0_NO_SIZE=1 to skip the size check.
set -euo pipefail
out="${1:?out dir}"
shafile="${2:?sha file}"
tagsfile="${3:-}"
remote="${PUBLISH_REMOTE:-origin}"
py="${PYTHON:-python}"
sleeps="${PUBLISH_SLEEPS:-5 15 30}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$here/publish_lib.py"
cfg="config/run.toml"
expected="$(cat "$shafile" 2>/dev/null || true)"
sol="$("$py" "$lib" sol "$out")"
solfmt="$(printf '%04d' "$sol")"
BOT_NAME="github-actions[bot]"
BOT_MAIL="41898282+github-actions[bot]@users.noreply.github.com"
export GIT_AUTHOR_NAME="$BOT_NAME" GIT_AUTHOR_EMAIL="$BOT_MAIL" GIT_COMMITTER_NAME="$BOT_NAME" GIT_COMMITTER_EMAIL="$BOT_MAIL"
gitid=(-c commit.gpgsign=false)

orphan_commit() {  # orphan_commit DIR MESSAGE -> prints commit sha, working copy and real index untouched
  local d="$1" msg="$2" idx tree
  idx="$(mktemp -u "${TMPDIR:-/tmp}/idx.XXXXXX")"
  GIT_INDEX_FILE="$idx" git --work-tree="$d" add -A -f -- .
  tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  rm -f "$idx"
  git "${gitid[@]}" commit-tree -m "$msg" "$tree" </dev/null
}

remote_sha() {  # remote_sha REF -> sha or empty ; returns 1 when the remote is unreachable
  local o
  o="$(git ls-remote "$remote" "$1")" || return 1
  printf '%s' "${o%%[[:space:]]*}"
}

# (1)(2) state
commit="$(orphan_commit "$out" "sol $solfmt")"
echo "state commit: $commit (expected remote: [$expected])"
pushed=0
attempt=0
for s in 0 $sleeps; do
  [ "$s" != 0 ] && { echo "::warning::state push retry in ${s}s"; sleep "$s"; }
  attempt=$((attempt + 1))
  if git push --force-with-lease="refs/heads/state:$expected" "$remote" "$commit:refs/heads/state"; then
    pushed=1; break
  fi
  if now="$(remote_sha refs/heads/state)"; then
    if [ "$now" = "$commit" ]; then
      echo "lease refused but remote == local commit: success (lost answer)"; pushed=1; break
    elif [ "$now" != "$expected" ]; then
      echo "::error::state changed on the remote (lease refused): remote=[$now] expected=[$expected]; nothing else pushed"
      exit 5
    fi
    # remote unchanged: transient error, retry
  fi
done
if [ "$pushed" != 1 ]; then
  echo "::error::state push failed after $attempt attempts"
  exit 4
fi
echo "state pushed: $commit"

# (3) tags
if [ -n "$tagsfile" ] && [ -s "$tagsfile" ]; then
  while read -r tag dir _rest; do
    [ -z "${tag:-}" ] && continue
    if ! [[ "$tag" =~ ^[A-Za-z0-9._-]+$ ]]; then echo "::warning::tag name refused: $tag"; continue; fi
    if t="$(remote_sha "refs/tags/$tag")" && [ -n "$t" ]; then echo "tag $tag already present"; continue; fi
    (
      set -e
      snap="$(mktemp -d "${TMPDIR:-/tmp}/snap.XXXXXX")"
      trap 'rm -rf "$snap"' EXIT
      for f in console.gif status.svg map.png; do
        [ -f "$dir/$f" ] && cp "$dir/$f" "$snap/$f"
      done
      "$py" "$lib" milestone "$tag" "$out" > "$snap/milestone.json"
      c="$(orphan_commit "$snap" "milestone $tag")"
      git tag -f "$tag" "$c" >/dev/null
      git push "$remote" "refs/tags/$tag:refs/tags/$tag"
    ) && echo "tag $tag pushed" || echo "::warning::tag $tag not pushed (stays in pending_tags, retried next run)"
  done < "$tagsfile"
fi

# (4) main: journal, atlas, firsts (append only)
main_ok=1
for d in journal atlas firsts; do [ -e "$d" ] && git add -A -- "$d"; done || true
if git diff --cached --quiet; then
  echo "nothing to commit on main"
else
  git "${gitid[@]}" commit -q -m "journal: sol $solfmt"
  main_ok=0
  attempt=0
  while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt + 1))
    if git push "$remote" HEAD:main; then main_ok=1; break; fi
    echo "::warning::main push refused (attempt $attempt), rebasing"
    if ! { git fetch "$remote" main && git "${gitid[@]}" rebase "$remote/main"; }; then
      git rebase --abort 2>/dev/null || true
      echo "::warning::rebase conflict: journal commit abandoned, the entry stays in journal_tail"
      break
    fi
  done
  [ "$main_ok" = 1 ] || echo "::warning::main not updated"
fi

# (5) repository size (informative)
if [ "${SOL0_NO_SIZE:-0}" != 1 ] && [ -n "${GITHUB_REPOSITORY:-}" ] && command -v gh >/dev/null 2>&1; then
  if size="$(gh api "repos/$GITHUB_REPOSITORY" -q .size 2>/dev/null)"; then
    limit="$("$py" "$lib" sizelimit "$cfg")"
    if [ "$size" -gt "$limit" ]; then echo "::warning::repository size $size KB > $limit KB"; else echo "::notice::repository size $size KB"; fi
  else
    echo "::notice::repository size unavailable"
  fi
fi

# (6) exit code
"$py" "$lib" verdict "$out" "$cfg" "$main_ok"
