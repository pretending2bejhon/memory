#!/bin/bash
# Publish dist/ through a temporary gh-pages worktree. Owner runs this script.
# Usage: bash tools/deploy.sh "message"
set -euo pipefail
cd "$(dirname "$0")/.."
MSG="${1:-memory: refresh}"
test -f dist/index.html || { echo "no build: run python viewer/build.py --public first"; exit 1; }
test -f dist/.nojekyll || { echo ".nojekyll missing from the build"; exit 1; }
test -f dist/og.jpg || { echo "og.jpg missing from the build"; exit 1; }
python qa_public.py
WT="$PWD/.gh-pages-wt"
# Never remove an existing checkout or an unexpected path.
test ! -e "$WT" || { echo "temporary worktree already exists: $WT"; exit 1; }
if git show-ref --verify --quiet refs/heads/gh-pages; then
  git worktree add "$WT" gh-pages >/dev/null
else
  git worktree add --detach "$WT" >/dev/null
  git -C "$WT" checkout --orphan gh-pages >/dev/null 2>&1
fi
trap 'git worktree remove "$WT" 2>/dev/null || true' EXIT
# Only tracked contents inside this dedicated checkout are removed.
# --force is required on the first run: an orphan branch has no HEAD, so every
# path is staged-only and git refuses to remove it without it. Scope is this
# dedicated worktree, never the project tree.
git -C "$WT" rm -rq --force --ignore-unmatch -- .
cp dist/index.html dist/.nojekyll dist/og.jpg "$WT/"
git -C "$WT" add -- index.html .nojekyll og.jpg
if git -C "$WT" diff --cached --quiet; then
  echo "build unchanged"
else
  git -C "$WT" commit -qm "$MSG"
fi
git -C "$WT" push -q origin gh-pages
git worktree remove "$WT"
trap - EXIT
echo "pushed gh-pages: $(git rev-parse --short gh-pages)"
